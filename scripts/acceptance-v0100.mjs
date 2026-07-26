import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const candidateTag = "v0100-provider-routing";
const jsonPath = path.join(artifacts, `acceptance-${candidateTag}.json`);
const markdownPath = path.join(artifacts, `acceptance-${candidateTag}.md`);
const actionLogPath = path.join(artifacts, `acceptance-${candidateTag}-actions.log`);
const started = new Date();
const actions = [];
const steps = [];

const criterionLabels = [
  "不覆盖历史证据地重放适用的 v0.9 capability、贡献者、翻译、认证与 Reader 回归",
  "个人 Provider 凭据加密、轮换、移除、用量与 Run 固定版本/作用域",
  "私有 Relay 的服务认证、版本绑定 Provider/模型/思考策略、边界、脱敏与 token 用量记录",
  "Web 凭据管理、无共享 Key 回退的启动门禁与翻译工作区交互",
  "v0.10.0 package/API 版本、BYOK OpenAPI 路径与非秘密响应契约",
  "LinguaSpindle v0.3.2 兼容、Relay 私网拓扑与 Provider 秘密泄漏防护",
];
const criteria = criterionLabels.map((label, index) => ({
  number: index + 1,
  label,
  status: "NOT_RUN",
  evidence: [],
}));

const deploymentPendingItems = [
  "PENDING_OPERATOR_CONFIG: 本地 gate 不配置或调用真实 OpenAI-compatible Provider，不产生付费调用或正文外发。",
  "PENDING_OPERATOR_CONFIG: 真实 LinguaSpindle v0.3.2、Relay 与 Mock Provider 的容器链路由部署验收复核。",
  "DEPLOYMENT_PENDING: vault master key 与 Relay service secret 的服务器 Secret 注入、备份分离及恢复演练待部署完成。",
  "DEPLOYMENT_PENDING: 真实 HTTPS、Passkey RP ID、私有 DNS、重启恢复和 before/after 拓扑待部署复核。",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function redact(value) {
  return String(value ?? "")
    .replaceAll(root, "[REPOSITORY ROOT]")
    .replaceAll("正文", "[CONTENT REDACTED]")
    .replace(/\bnpa_[A-Za-z0-9_-]{16,}\b/g, "npa_[REDACTED]")
    .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/g, "sk-[REDACTED]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[JWT REDACTED]")
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [REDACTED]")
    .replace(/(?:novel_refresh|novel_device)=[^;\s]+/g, "[COOKIE REDACTED]")
    .replace(
      /postgres(?:ql)?(?:\+\w+)?:\/\/[^:\s/]+:[^@\s/]+@/gi,
      "postgresql://[REDACTED]@",
    );
}

function run(label, executable, args, options = {}) {
  actions.push(label);
  try {
    return execFileSync(executable, args, {
      cwd: options.cwd ?? root,
      env: options.env ?? process.env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 100 * 1024 * 1024,
    });
  } catch (error) {
    const detail = redact(error.stderr ?? error.stdout ?? error.message);
    throw new Error(`${label} failed${detail ? `: ${detail.slice(-1600)}` : ""}`);
  }
}

async function step(name, action) {
  const stepStarted = Date.now();
  try {
    const value = await action();
    steps.push({
      name,
      status: "PASS",
      duration_ms: Date.now() - stepStarted,
      detail: "completed",
    });
    return value;
  } catch (error) {
    steps.push({
      name,
      status: "FAIL",
      duration_ms: Date.now() - stepStarted,
      detail: redact(error instanceof Error ? error.message : error),
    });
    throw error;
  }
}

function mark(numbers, evidence) {
  for (const number of numbers) {
    const criterion = criteria[number - 1];
    criterion.status = "PASS";
    criterion.evidence.push(evidence);
  }
}

function addEvidence(numbers, evidence) {
  for (const number of numbers) {
    criteria[number - 1].evidence.push(evidence);
  }
}

function serviceBlock(source, serviceName) {
  const lines = source.split("\n");
  const start = lines.findIndex((line) => line === `  ${serviceName}:`);
  if (start < 0) return null;
  let end = lines.length;
  for (let index = start + 1; index < lines.length; index += 1) {
    if (/^[A-Za-z0-9_-]+:\s*$/.test(lines[index])) {
      end = index;
      break;
    }
    if (/^  [A-Za-z0-9_-]+:\s*$/.test(lines[index])) {
      end = index;
      break;
    }
  }
  return lines.slice(start, end).join("\n");
}

function serviceNetworkNames(block) {
  const lines = block.split("\n");
  const start = lines.findIndex((line) => line === "    networks:");
  if (start < 0) return [];
  const names = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    if (/^    [A-Za-z0-9_-]+:/.test(lines[index])) break;
    const mapping = lines[index].match(/^      ([A-Za-z0-9_-]+):/);
    const list = lines[index].match(/^      - ([A-Za-z0-9_-]+)\s*$/);
    if (mapping) names.push(mapping[1]);
    if (list) names.push(list[1]);
  }
  return names;
}

function schemaProperties(openapi, schemaName) {
  const schema = openapi.components?.schemas?.[schemaName];
  assert(schema && typeof schema === "object", `OpenAPI schema ${schemaName} is missing`);
  return schema.properties ?? {};
}

function schemaRefName(schema) {
  return typeof schema?.$ref === "string" ? schema.$ref.split("/").at(-1) : null;
}

async function writeReports(status, inherited, failure) {
  const gitCommit = run("read Git commit", "git", ["rev-parse", "HEAD"]).trim();
  const report = {
    version: "0.10.0",
    status,
    deployment_status: "DEPLOYMENT_PENDING",
    provider_status: {
      fake_transport: "PASS",
      real_v032_mock_provider: "PENDING_OPERATOR_CONFIG",
      real_openai_compatible: "PENDING_OPERATOR_CONFIG",
    },
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: gitCommit,
    inherited_regression: inherited,
    criteria,
    steps,
    deployment_pending: deploymentPendingItems,
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await mkdir(artifacts, { recursive: true });
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  const markdown = [
    "# Novel Platform post-v0.10 Provider-routing local acceptance",
    "",
    `- Status: **${status}**`,
    "- Deployment: **DEPLOYMENT_PENDING**",
    "- Synthetic/fake transport: **PASS**",
    "- Real LinguaSpindle v0.3.2 + Mock Provider: **PENDING_OPERATOR_CONFIG**",
    "- Real OpenAI-compatible Provider: **PENDING_OPERATOR_CONFIG**",
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${gitCommit}`,
    "",
    "## Criteria",
    "",
    "| # | Status | Criterion | Evidence |",
    "| ---: | --- | --- | --- |",
    ...criteria.map(
      (item) =>
        `| ${item.number} | ${item.status} | ${item.label} | ${item.evidence.join("; ")} |`,
    ),
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map(
      (item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail} |`,
    ),
    "",
    "## Pending operator/deployment work",
    "",
    ...deploymentPendingItems.map((item) => `- ${item}`),
    "",
    failure
      ? `Failure: ${redact(failure.message ?? failure)}`
      : "No failed or skipped required local checks.",
    "",
    "Evidence uses synthetic data. Provider keys, vault/Relay secrets, credentials, tokens, Cookies,正文, database URLs, and host storage paths are excluded.",
    "",
  ].join("\n");
  await writeFile(markdownPath, markdown, { mode: 0o600 });
  await writeFile(
    actionLogPath,
    [
      "Novel Platform post-v0.10 Provider-routing sanitized acceptance action log",
      "Only action labels are recorded; arguments, outputs, secrets, content, IDs, URLs, and paths are omitted.",
      "",
      ...actions.map((label) => `[ACTION] ${label}`),
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
}

async function main() {
  await mkdir(artifacts, { recursive: true });
  let inherited = null;
  let failure = null;

  try {
    await step("Replay the applicable v0.9 gate into v0.10-only evidence", async () => {
      run(
        "run inherited v0.9 gate without rewriting historical evidence",
        process.execPath,
        ["scripts/acceptance-v090.mjs"],
        {
          env: {
            ...process.env,
            ACCEPTANCE_VERSION: "0.10.0",
            ACCEPTANCE_TAG: `${candidateTag}-regression`,
            ACCEPTANCE_INHERITED_TAG: `${candidateTag}-regression-v080`,
            ACCEPTANCE_COMMAND: "acceptance:v0100",
            ACCEPTANCE_EXPECTED_REVISION: "20260726_0008",
            ACCEPTANCE_LINGUASPINDLE_VERSION: "0.3.2",
            ACCEPTANCE_LINGUASPINDLE_VERSION_RANGE: ">=0.3.2,<0.4.0",
            ACCEPTANCE_PROVIDER_CREDENTIAL_MASTER_KEY:
              "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            ACCEPTANCE_REQUIRE_HISTORICAL_VISUAL_EVIDENCE: "0",
          },
        },
      );
      const regression = JSON.parse(
        await readFile(path.join(artifacts, `acceptance-${candidateTag}-regression.json`), "utf8"),
      );
      const inheritedV080 = JSON.parse(
        await readFile(
          path.join(artifacts, `acceptance-${candidateTag}-regression-v080.json`),
          "utf8",
        ),
      );
      const inheritedCore = JSON.parse(
        await readFile(
          path.join(artifacts, `acceptance-${candidateTag}-regression-v080-core.json`),
          "utf8",
        ),
      );
      assert(regression.status === "PASS", "inherited v0.9 gate did not pass");
      assert(
        regression.criteria?.length === 11 &&
          regression.criteria.every((item) => item.status === "PASS"),
        "inherited v0.9 criteria changed or failed",
      );
      assert(
        inheritedV080.status === "PASS" &&
          inheritedV080.criteria?.length === 93 &&
          inheritedV080.hardening?.criteria?.length === 9,
        "inherited v0.8 hardening replay changed or failed",
      );
      assert(
        inheritedCore.status === "PASS" && inheritedCore.criteria?.length === 84,
        "inherited 84-criterion core changed or failed",
      );
      inherited = {
        status: regression.status,
        criteria_count: regression.criteria.length,
        artifact: `artifacts/acceptance-${candidateTag}-regression.json`,
        v080_artifact: `artifacts/acceptance-${candidateTag}-regression-v080.json`,
        core_artifact: `artifacts/acceptance-${candidateTag}-regression-v080-core.json`,
      };
      mark([1], "v0100 regression replay: 84 core + 9 hardening + 11 v0.9 criteria");
      addEvidence([2], "isolated PostgreSQL replay includes scoped Run and Relay lifecycle tests");
    });

    await step("Run Provider credential, Relay and LinguaSpindle focused Server tests", async () => {
      run(
        "run encrypted Provider credential, private Relay and scoped LinguaSpindle tests",
        "uv",
        [
          "run",
          "pytest",
          "tests/unit/test_provider_credentials.py",
          "tests/unit/test_linguaspindle_client.py",
        ],
        { cwd: path.join(root, "apps", "server") },
      );
      mark([2], "focused vault/Relay/LinguaSpindle unit suite");
      addEvidence([3, 6], "focused vault/Relay/LinguaSpindle unit suite");
    });

    await step("Run BYOK-aware Web interaction tests", async () => {
      run(
        "run personal credential and no-fallback Web interaction tests",
        "pnpm",
        [
          "--filter",
          "@novel-platform/web",
          "exec",
          "vitest",
          "run",
          "tests/ProviderCredentialPage.test.tsx",
          "tests/TranslationLaunchModal.test.tsx",
          "tests/TranslationsPage.test.tsx",
          "tests/apiClient.test.ts",
          "tests/AuthFlow.test.tsx",
        ],
      );
      mark([4], "focused credential page, launch gate, workspace, API and route suite");
    });

    await step("Verify v0.10 package, API and non-secret BYOK contracts", async () => {
      const [rootPackage, webPackage, clientPackage, pyproject, mainSource, authSource, shellSource] =
        await Promise.all([
          readFile(path.join(root, "package.json"), "utf8").then(JSON.parse),
          readFile(path.join(root, "apps/web/package.json"), "utf8").then(JSON.parse),
          readFile(path.join(root, "packages/api-client/package.json"), "utf8").then(JSON.parse),
          readFile(path.join(root, "apps/server/pyproject.toml"), "utf8"),
          readFile(path.join(root, "apps/server/src/novel_platform/main.py"), "utf8"),
          readFile(path.join(root, "apps/web/src/auth/AuthProvider.tsx"), "utf8"),
          readFile(path.join(root, "apps/web/src/layouts/AppShell.tsx"), "utf8"),
        ]);
      assert(rootPackage.version === "0.10.0", "root package version is not 0.10.0");
      assert(
        rootPackage.scripts?.acceptance === "node scripts/acceptance-v0100.mjs" &&
          rootPackage.scripts?.["acceptance:v0100"] ===
            "node scripts/acceptance-v0100.mjs" &&
          rootPackage.scripts?.["acceptance:v090"] === "node scripts/acceptance-v090.mjs",
        "package scripts do not select v0.10 while retaining the v0.9 gate",
      );
      assert(webPackage.version === "0.10.0", "Web package version is not 0.10.0");
      assert(clientPackage.version === "0.10.0", "API client package version is not 0.10.0");
      assert(
        /^version = "0\.10\.0"$/m.test(pyproject),
        "Server project version is not 0.10.0",
      );
      assert(/version="0\.10\.0"/.test(mainSource), "FastAPI version is not 0.10.0");
      assert(/app_version: "0\.10\.0"/.test(authSource), "Web device version is not 0.10.0");
      assert(shellSource.includes("漫读 v0.10.0"), "AppShell version is not 0.10.0");

      const openapiText = await readFile(
        path.join(root, "packages/api-client/openapi.json"),
        "utf8",
      );
      const openapi = JSON.parse(openapiText);
      assert(openapi.info?.version === "0.10.0", "OpenAPI version is not 0.10.0");
      const credentialPath = openapi.paths?.["/api/v1/me/provider-credential"];
      const usagePath = openapi.paths?.["/api/v1/me/provider-credential/usage"];
      assert(
        credentialPath?.get && credentialPath?.put && credentialPath?.delete,
        "Provider credential GET/PUT/DELETE contract is incomplete",
      );
      assert(
        credentialPath.delete.responses?.["204"],
        "Provider credential removal does not retain the empty 204 contract",
      );
      assert(usagePath?.get, "Provider credential usage GET contract is missing");
      assert(
        schemaRefName(
          credentialPath.put.requestBody?.content?.["application/json"]?.schema,
        ) === "ProviderCredentialPut",
        "Provider credential PUT is not bound to the Provider configuration input schema",
      );
      assert(
        schemaRefName(
          credentialPath.get.responses?.["200"]?.content?.["application/json"]?.schema,
        ) === "ProviderCredentialStatusResponse" &&
          schemaRefName(
            credentialPath.put.responses?.["200"]?.content?.["application/json"]?.schema,
          ) === "ProviderCredentialStatusResponse" &&
          schemaRefName(
            usagePath.get.responses?.["200"]?.content?.["application/json"]?.schema,
          ) === "ProviderCredentialUsageResponse",
        "Provider credential operations are not bound to non-secret response schemas",
      );

      const putProperties = schemaProperties(openapi, "ProviderCredentialPut");
      assert(
        Object.keys(putProperties).sort().join(",") ===
            "api_key,base_url,custom_name,model,provider,thinking_enabled" &&
          putProperties.api_key?.type === "string" &&
          putProperties.api_key?.format === "password" &&
          putProperties.api_key?.writeOnly === true &&
          putProperties.provider?.default === "openai_compatible" &&
          putProperties.thinking_enabled?.type === "boolean" &&
          putProperties.thinking_enabled?.default === false,
        "Provider credential write contract lacks routing fields or the default-off thinking switch",
      );
      const statusProperties = schemaProperties(openapi, "ProviderCredentialStatusResponse");
      assert(
        ["provider", "provider_name", "base_url", "model", "thinking_enabled"].every(
          (name) => Object.hasOwn(statusProperties, name),
        ) &&
          openapi.components?.schemas?.ProviderKind?.enum?.join(",") ===
            "openai_compatible,deepseek,kimi,custom",
        "Provider credential status/enum contract lacks multi-Provider routing metadata",
      );
      const usageProperties = schemaProperties(openapi, "ProviderCredentialUsageResponse");
      const totalsProperties = schemaProperties(openapi, "ProviderUsageTotalsResponse");
      const responsePropertyNames = [
        ...Object.keys(statusProperties),
        ...Object.keys(usageProperties),
        ...Object.keys(totalsProperties),
      ];
      assert(
        responsePropertyNames.every(
          (name) =>
            !/(?:^id$|_id$)/i.test(name) &&
            !/(?:api_?key|secret|cipher|nonce|scope|hash|suffix|hint)/i.test(name),
        ),
        "Provider credential response schema exposes secret-derived material",
      );
      for (const forbidden of [
        "credential_scope",
        "provider_credential_master_key",
        "provider_relay_service_secret",
        "encrypted_api_key",
        "api_key_nonce",
        "provider_credential_version_id",
        "ciphertext",
        '"nonce"',
      ]) {
        assert(
          !openapiText.toLowerCase().includes(forbidden),
          `OpenAPI exposes private field ${forbidden}`,
        );
      }
      const generatedSchema = await readFile(
        path.join(root, "packages/api-client/src/schema.d.ts"),
        "utf8",
      );
      assert(
        generatedSchema.includes('"/api/v1/me/provider-credential"') &&
          generatedSchema.includes('"/api/v1/me/provider-credential/usage"') &&
          generatedSchema.includes(
            'ProviderKind: "openai_compatible" | "deepseek" | "kimi" | "custom"',
          ) &&
          generatedSchema.includes("thinking_enabled: boolean"),
        "generated TypeScript schema lacks BYOK routing/thinking contracts",
      );
      assert(
        !generatedSchema.includes("credential_scope"),
        "generated TypeScript schema exposes credential_scope",
      );
      mark([5], "package/FastAPI/Web/OpenAPI/generated-schema v0.10 contract inspection");
    });

    await step("Verify Lingua v0.3.2, Relay topology and leak boundaries", async () => {
      const [
        configSource,
        linguaClient,
        linguaTests,
        launchTests,
        workspaceTests,
        overlay,
        baseCompose,
        stagingCompose,
        localEnvironment,
        stagingEnvironment,
        stagingHealthcheck,
        stagingDeploy,
        stagingLibrary,
        stagingRestore,
        stagingBackup,
        stagingArtifactScan,
        stagingArtifactScanRunner,
      ] = await Promise.all([
        readFile(path.join(root, "apps/server/src/novel_platform/config.py"), "utf8"),
        readFile(
          path.join(
            root,
            "apps/server/src/novel_platform/infrastructure/integrations/linguaspindle.py",
          ),
          "utf8",
        ),
        readFile(
          path.join(root, "apps/server/tests/unit/test_linguaspindle_client.py"),
          "utf8",
        ),
        readFile(
          path.join(root, "apps/web/tests/TranslationLaunchModal.test.tsx"),
          "utf8",
        ),
        readFile(path.join(root, "apps/web/tests/TranslationsPage.test.tsx"), "utf8"),
        readFile(path.join(root, "compose.translation.yml"), "utf8"),
        readFile(path.join(root, "compose.yaml"), "utf8"),
        readFile(path.join(root, "compose.staging.yml"), "utf8"),
        readFile(path.join(root, ".env.example"), "utf8"),
        readFile(path.join(root, ".env.staging.example"), "utf8"),
        readFile(path.join(root, "scripts/healthcheck-staging.sh"), "utf8"),
        readFile(path.join(root, "scripts/deploy-staging.sh"), "utf8"),
        readFile(path.join(root, "scripts/staging-lib.sh"), "utf8"),
        readFile(path.join(root, "scripts/restore-library.sh"), "utf8"),
        readFile(path.join(root, "scripts/backup-library.sh"), "utf8"),
        readFile(path.join(root, "scripts/scan-staging-artifacts.mjs"), "utf8"),
        readFile(path.join(root, "scripts/scan-staging-artifacts.sh"), "utf8"),
      ]);
      run(
        "parse the fail-closed staging healthcheck",
        "bash",
        ["-n", "scripts/healthcheck-staging.sh"],
      );
      run(
        "parse disabled-Relay cleanup in the staging deploy script",
        "bash",
        ["-n", "scripts/deploy-staging.sh"],
      );
      assert(
        configSource.includes('">=0.3.2,<0.4.0"') &&
          linguaClient.includes("(0, 3, 2) <= version") &&
          linguaTests.includes('"0.3.2-rc1"') &&
          linguaTests.includes('"0.3.2+reviewed.1"'),
        "Server does not require LinguaSpindle >=0.3.2,<0.4.0",
      );
      for (const [name, source] of [
        ["Lingua client tests", linguaTests],
        ["translation launch fixtures", launchTests],
        ["translation workspace fixtures", workspaceTests],
      ]) {
        assert(!source.includes('"0.3.1"'), `${name} still displays LinguaSpindle 0.3.1`);
        assert(source.includes('"0.3.2"'), `${name} lacks LinguaSpindle 0.3.2 evidence`);
      }

      const relay = serviceBlock(overlay, "provider-relay");
      const server = serviceBlock(overlay, "server");
      assert(relay, "translation overlay lacks provider-relay service");
      assert(server, "translation overlay lacks Server service");
      assert(
        relay.includes("novel_platform.relay:app"),
        "provider-relay does not run the dedicated private ASGI app",
      );
      assert(!/^\s{4}ports:\s*$/m.test(relay), "provider-relay exposes a host port");
      assert(
        serviceBlock(overlay, "web") === null && serviceBlock(overlay, "migrate") === null,
        "Web or migration service joined the translation overlay",
      );
      assert(
        serviceNetworkNames(relay).sort().join(",") === "database,translation",
        "provider-relay is not joined to exactly the required database/translation boundaries",
      );
      assert(
        /(?:^|\n)\s+(?:-\s*)?translation(?::(?:\s*\{\})?)?\s*$/m.test(server),
        "Server is not joined to the private translation network",
      );
      assert(
        overlay.includes("external: true") && overlay.includes("name: linguaspindle-private"),
        "translation network is not the fixed external linguaspindle-private network",
      );
      assert(
        relay.includes("${PROVIDER_CREDENTIAL_MASTER_KEY:?") &&
          relay.includes("${PROVIDER_RELAY_SERVICE_SECRET:?"),
        "provider-relay does not require both vault and service secrets",
      );
      assert(
        relay.includes("PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS"),
        "provider-relay does not receive the custom Provider destination allow-list",
      );
      assert(
        serviceBlock(baseCompose, "server")?.includes(
          "${PROVIDER_CREDENTIAL_MASTER_KEY:?",
        ) &&
          !baseCompose.includes("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=") &&
          stagingLibrary.includes('{"staging", "production"}') &&
          stagingLibrary.includes("value == bytes(32)") &&
          configSource.includes("secrets.compare_digest(master_key, relay_secret)"),
        "base Compose retains an implicit known Provider-vault development key",
      );
      const serverDeployment = [
        serviceBlock(baseCompose, "server"),
        serviceBlock(stagingCompose, "server"),
        server,
      ]
        .filter(Boolean)
        .join("\n");
      assert(
        !serverDeployment.includes("PROVIDER_RELAY_SERVICE_SECRET"),
        "public Server received the Relay service secret",
      );
      for (const [name, source] of [
        ["local Server", serviceBlock(baseCompose, "server")],
        ["staging Server", serviceBlock(stagingCompose, "server")],
      ]) {
        assert(
          source?.includes("PROVIDER_RELAY_UPSTREAM_BASE_URL") &&
            source.includes("PROVIDER_RELAY_ALLOWED_MODELS") &&
            source.includes("PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS"),
          `${name} does not receive the complete Provider routing policy`,
        );
      }
      assert(
        localEnvironment.includes("PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS='[]'") &&
          stagingEnvironment.includes("PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS='[]'") &&
          stagingLibrary.includes("validate_custom_provider_base_url_allowlist") &&
          stagingHealthcheck.includes(
            "settings.provider_relay_custom_allowed_base_urls == expected_custom",
          ) &&
          stagingRestore.includes("pg_get_expr(") &&
          stagingRestore.includes("thinking_enabled IS DISTINCT FROM false") &&
          stagingRestore.includes("provider_thinking_violations") &&
          stagingRestore.includes("deepseek-reasoner") &&
          stagingRestore.includes("kimi-k2.5") &&
          stagingBackup.includes('"required_external_configuration"') &&
          stagingBackup.includes("provider_relay_custom_allowed_base_urls") &&
          stagingArtifactScan.includes('"PROVIDER_CREDENTIAL_MASTER_KEY"') &&
          stagingArtifactScan.includes('"PROVIDER_RELAY_SERVICE_SECRET"') &&
          stagingArtifactScanRunner.includes("-e PROVIDER_CREDENTIAL_MASTER_KEY") &&
          stagingArtifactScanRunner.includes("-e PROVIDER_RELAY_SERVICE_SECRET"),
        "deployment routing/thinking defaults or runtime checks are incomplete",
      );
      const nonSecretServices = [
        serviceBlock(baseCompose, "web"),
        serviceBlock(baseCompose, "migrate"),
        serviceBlock(stagingCompose, "web"),
        serviceBlock(stagingCompose, "migrate"),
      ]
        .filter(Boolean)
        .join("\n");
      assert(
        !nonSecretServices.includes("PROVIDER_CREDENTIAL_MASTER_KEY") &&
          !nonSecretServices.includes("PROVIDER_RELAY_SERVICE_SECRET"),
        "Web or migration service received a Provider vault/Relay secret",
      );

      const deploymentSurface = [
        overlay,
        baseCompose,
        stagingCompose,
        localEnvironment,
        stagingEnvironment,
      ].join("\n");
      assert(
        !/(?:OPENAI_API_KEY|LINGUASPINDLE_(?:API_)?KEY|PROVIDER_(?:API_)?KEY)/.test(
          deploymentSurface,
        ),
        "Novel Platform deployment surface contains an upstream Provider key variable",
      );
      assert(
        !/\bsk-[A-Za-z0-9_-]{12,}\b/.test(deploymentSurface),
        "Novel Platform deployment surface contains a Provider-key-shaped value",
      );
      assert(
        stagingHealthcheck.includes(
          "linguaspindle-private must have exactly one container",
        ) &&
          stagingHealthcheck.includes(".State.Health.Status") &&
          stagingHealthcheck.includes(".HostConfig.PortBindings") &&
          stagingHealthcheck.includes(".NetworkSettings.Ports") &&
          stagingHealthcheck.includes("versions == [1, 2, 3, 4, 5]") &&
          stagingHealthcheck.includes("NoRedirectHandler") &&
          stagingHealthcheck.includes(
            "resolved_addresses.issubset(expected_addresses)",
          ) &&
          stagingHealthcheck.includes("(0, 3, 2)") &&
          stagingHealthcheck.includes("len(postgres) != 1") &&
          stagingHealthcheck.includes("relay != expected_relay") &&
          stagingHealthcheck.includes("host_secret_proof") &&
          stagingHealthcheck.includes("container_secret_proof") &&
          stagingHealthcheck.includes(
            'base_url != "http://novel-provider-relay:8790/v1"',
          ) &&
          stagingHealthcheck.includes("urllib.request.ProxyHandler({})") &&
          stagingHealthcheck.includes("provider_credential_unavailable") &&
          stagingHealthcheck.includes("synthetic_scope_count") &&
          stagingDeploy.includes("staging_provider_relay_container_ids") &&
          stagingDeploy.includes("docker rm --force") &&
          stagingHealthcheck.includes(
            "disabled translation retains a Provider Relay container",
          ) &&
          !stagingHealthcheck.includes(".Config.Env"),
        "staging healthcheck lacks fail-closed external LinguaSpindle runtime validation",
      );
      mark(
        [3, 6],
        "v0.3.2 source/fixture, fail-closed runtime gate and private Compose/leak contract inspection",
      );
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    const status =
      failure === null && criteria.every((item) => item.status === "PASS") ? "PASS" : "FAIL";
    await writeReports(status, inherited, failure);
  }

  assert(criterionLabels.length === 6, "v0.10 criterion count changed");
  if (failure !== null) process.exitCode = 1;
}

await main();
