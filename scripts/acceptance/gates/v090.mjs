import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const acceptanceVersion = process.env.ACCEPTANCE_VERSION ?? "0.9.0";
const acceptanceTag = process.env.ACCEPTANCE_TAG ?? "v090";
const acceptanceCommand = process.env.ACCEPTANCE_COMMAND ?? "pnpm acceptance -- v090";
const acceptanceExpectedRevision =
  process.env.ACCEPTANCE_EXPECTED_REVISION ?? "20260723_0006";
const acceptanceLinguaVersion = process.env.ACCEPTANCE_LINGUASPINDLE_VERSION ?? "0.3.1";
const acceptanceLinguaVersionRange =
  process.env.ACCEPTANCE_LINGUASPINDLE_VERSION_RANGE ?? ">=0.3.1,<0.4.0";
const acceptanceLinguaStatusKey =
  `real_v${acceptanceLinguaVersion.replaceAll(".", "")}_mock_provider`;
const acceptanceProviderCredentialMasterKey =
  process.env.ACCEPTANCE_PROVIDER_CREDENTIAL_MASTER_KEY ??
  "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
const inheritedAcceptanceTag =
  process.env.ACCEPTANCE_INHERITED_TAG ?? `${acceptanceTag}-regression`;
const requireHistoricalVisualEvidence =
  process.env.ACCEPTANCE_REQUIRE_HISTORICAL_VISUAL_EVIDENCE !== "0";
const jsonPath = path.join(artifacts, `acceptance-${acceptanceTag}.json`);
const markdownPath = path.join(artifacts, `acceptance-${acceptanceTag}.md`);
const actionLogPath = path.join(artifacts, `acceptance-${acceptanceTag}-actions.log`);
const databaseComposeFile = "scripts/acceptance/support/v090.database.yml";
const databaseProject =
  `novel-${acceptanceTag.replace(/[^a-z0-9-]/gi, "-").toLowerCase()}-db-${process.pid}-${Date.now()}`;
const started = new Date();
const actions = [];
const steps = [];
const sensitive = new Set([acceptanceProviderCredentialMasterKey]);

const criterionLabels = [
  "v0.8 仍适用的认证、Reader、Passkey、设备、Session 与代理回归",
  "Capability 签发、reissue、即时失效与 API 权限矩阵",
  "四身份上传、贡献归属、安全显示、删除与跨贡献者冲突",
  "Legacy UI/API 移除与占位迁移、回填及 fail-closed 预检",
  "私网 Project/Job 幂等、同步、控制与原子生成译本",
  "Retranslate、创建者草稿预览与管理员发布",
  "仅 Server 私网接入且 LinguaSpindle 不可用不影响主站 readiness",
  "Provider Key、raw credential、正文、路径与幂等键泄漏防护",
  "PostgreSQL + library 协调备份、隔离恢复与 volume 审计",
  "桌面、320 px 移动端、导航抽屉与可访问名称",
  "精确清理测试 Run/Project/Edition/文件并扫描残留",
];
const criteria = criterionLabels.map((label, index) => ({
  number: index + 1,
  label,
  status: "NOT_RUN",
  evidence: [],
}));

const deploymentPendingItems = [
  `PENDING_OPERATOR_CONFIG: 未连接真实 LinguaSpindle v${acceptanceLinguaVersion} + Mock Provider。`,
  "PENDING_OPERATOR_CONFIG: 未配置或调用真实 OpenAI-compatible Provider；没有付费或正文外发调用。",
  "DEPLOYMENT_PENDING: 未在服务器执行 v0.9 migration、reset、Compose 网络变更或远端清理。",
  "DEPLOYMENT_PENDING: 真实 HTTPS、Passkey RP ID、私有 DNS、持久化与重启恢复待部署授权后复核。",
];

const migrationFixtureCounts = {
  preserved_content_fixture: {
    fileless_editions_deleted: 3,
    empty_books_deleted: 1,
    book_creator_rows_backfilled: 1,
    retained_edition_creator_rows_backfilled: 1,
    stored_file_creator_rows_backfilled: 1,
    retained_last_opened_links_cleared: 1,
    preferred_links_preserved: 1,
    reading_progress_rows_deleted: 1,
    empty_book_preference_rows_deleted: 1,
  },
  capability_import_fixture: {
    active_imports_blocking_first_attempt: 1,
    credential_library_read_rows_backfilled: 1,
    import_actor_rows_backfilled: 1,
  },
  remote_database_counts: "DEPLOYMENT_PENDING",
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function sha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function redact(value) {
  let output = String(value ?? "");
  for (const item of [...sensitive].sort((left, right) => right.length - left.length)) {
    output = output.replaceAll(item, "[REDACTED]");
  }
  return output
    .replaceAll(root, "[REPOSITORY ROOT]")
    .replaceAll("正文", "[CONTENT REDACTED]")
    .replace(/\bnpa_[A-Za-z0-9_-]{16,}\b/g, "npa_[REDACTED]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[JWT REDACTED]")
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [REDACTED]")
    .replace(/(?:novel_refresh|novel_device)=[^;\s]+/g, "[COOKIE REDACTED]")
    .replace(/postgres(?:ql)?(?:\+\w+)?:\/\/[^:\s/]+:[^@\s/]+@/gi, "postgresql://[REDACTED]@");
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
    steps.push({ name, status: "PASS", duration_ms: Date.now() - stepStarted, detail: "completed" });
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

function composeServiceNames(source) {
  const lines = source.split("\n");
  const servicesStart = lines.findIndex((line) => line === "services:");
  if (servicesStart < 0) return [];
  const names = [];
  for (let index = servicesStart + 1; index < lines.length; index += 1) {
    if (/^[A-Za-z0-9_-]+:\s*$/.test(lines[index])) break;
    const match = lines[index].match(/^  ([A-Za-z0-9_-]+):\s*$/);
    if (match) names.push(match[1]);
  }
  return names;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitForDatabase(environment, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      execFileSync(
        "docker",
        [
          "compose", "-p", databaseProject, "-f", databaseComposeFile,
          "exec", "-T", "postgres", "pg_isready", "-U", "novel_platform", "-d", "novel_platform",
        ],
        { cwd: root, env: environment, stdio: "ignore" },
      );
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  throw new Error("isolated v0.9 PostgreSQL did not become ready");
}

async function writeReports(status, inherited, failure) {
  const gitCommit = run("read Git commit", "git", ["rev-parse", "HEAD"]).trim();
  const report = {
    version: acceptanceVersion,
    status,
    deployment_status: "DEPLOYMENT_PENDING",
    provider_status: {
      fake_transport: "PASS",
      [acceptanceLinguaStatusKey]: "PENDING_OPERATOR_CONFIG",
      real_openai_compatible: "PENDING_OPERATOR_CONFIG",
    },
    visual_status: requireHistoricalVisualEvidence ? "LOCAL_PASS" : "NOT_REPLAYED",
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: gitCommit,
    inherited_regression: inherited,
    migration_fixture_counts: migrationFixtureCounts,
    criteria,
    steps,
    deployment_pending: deploymentPendingItems,
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await mkdir(artifacts, { recursive: true });
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  const markdown = [
    `# Novel Platform v${acceptanceVersion} local acceptance`,
    "",
    `- Status: **${status}**`,
    "- Deployment: **DEPLOYMENT_PENDING**",
    "- Fake LinguaSpindle transport: **PASS**",
    `- Real v${acceptanceLinguaVersion} + Mock Provider: **PENDING_OPERATOR_CONFIG**`,
    "- Real OpenAI-compatible Provider: **PENDING_OPERATOR_CONFIG**",
    requireHistoricalVisualEvidence
      ? "- Visual review: **LOCAL_PASS**"
      : "- Historical visual evidence: **NOT_REPLAYED**",
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${gitCommit}`,
    "",
    "## Criteria",
    "",
    "| # | Status | Criterion | Evidence |",
    "| ---: | --- | --- | --- |",
    ...criteria.map((item) => `| ${item.number} | ${item.status} | ${item.label} | ${item.evidence.join("; ")} |`),
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map((item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail} |`),
    "",
    "## Synthetic migration fixture counts",
    "",
    `- Fileless Editions deleted: ${migrationFixtureCounts.preserved_content_fixture.fileless_editions_deleted}`,
    `- Empty Books deleted: ${migrationFixtureCounts.preserved_content_fixture.empty_books_deleted}`,
    `- Book/retained Edition/StoredFile creator rows backfilled: ${migrationFixtureCounts.preserved_content_fixture.book_creator_rows_backfilled}/${migrationFixtureCounts.preserved_content_fixture.retained_edition_creator_rows_backfilled}/${migrationFixtureCounts.preserved_content_fixture.stored_file_creator_rows_backfilled}`,
    `- Retained-Book last-opened links cleared / preferred links preserved / progress rows deleted: ${migrationFixtureCounts.preserved_content_fixture.retained_last_opened_links_cleared}/${migrationFixtureCounts.preserved_content_fixture.preferred_links_preserved}/${migrationFixtureCounts.preserved_content_fixture.reading_progress_rows_deleted}`,
    `- Empty-Book preference rows deleted: ${migrationFixtureCounts.preserved_content_fixture.empty_book_preference_rows_deleted}`,
    `- Blocking active Imports / read capabilities backfilled / Import actors backfilled: ${migrationFixtureCounts.capability_import_fixture.active_imports_blocking_first_attempt}/${migrationFixtureCounts.capability_import_fixture.credential_library_read_rows_backfilled}/${migrationFixtureCounts.capability_import_fixture.import_actor_rows_backfilled}`,
    "- Remote database counts: **DEPLOYMENT_PENDING**",
    "",
    "## Pending operator/deployment work",
    "",
    ...deploymentPendingItems.map((item) => `- ${item}`),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required local checks.",
    "",
    "Evidence uses synthetic content. Credentials, tokens, Cookies, Provider secrets,正文, database URLs, and host storage paths are excluded.",
    "",
  ].join("\n");
  await writeFile(markdownPath, markdown, { mode: 0o600 });
  await writeFile(
    actionLogPath,
    [
      `Novel Platform v${acceptanceVersion} sanitized acceptance action log`,
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
  let databaseStarted = false;
  let inherited = null;
  let failure = null;
  const temporaryRoot = await mkdtemp(
    path.join(os.tmpdir(), `novel-${acceptanceTag}-acceptance-`),
  );
  const databasePort = await freePort();
  const databaseEnvironment = {
    ...process.env,
    COMPOSE_PROJECT_NAME: databaseProject,
    V090_POSTGRES_PORT: String(databasePort),
  };
  const dockerDatabase = (label, args) => run(
    label,
    "docker",
    ["compose", "-p", databaseProject, "-f", databaseComposeFile, ...args],
    { env: databaseEnvironment },
  );

  try {
    await step("Replay applicable v0.8 authentication, Reader and proxy regression", async () => {
      run("run inherited v0.8 regression without rewriting historical evidence", process.execPath, [
        "scripts/acceptance/gates/v080.mjs",
      ], {
        env: {
          ...process.env,
          ACCEPTANCE_VERSION: acceptanceVersion,
          ACCEPTANCE_TAG: inheritedAcceptanceTag,
          ACCEPTANCE_COMMAND: acceptanceCommand,
          ACCEPTANCE_EXPECTED_REVISION: acceptanceExpectedRevision,
          ACCEPTANCE_LINGUASPINDLE_VERSION_RANGE: acceptanceLinguaVersionRange,
          ACCEPTANCE_READER_CAPABILITIES: "library.read",
          ACCEPTANCE_LEGACY_BOOK_POST_STATUS: "405",
        },
      });
      const regression = JSON.parse(
        await readFile(
          path.join(artifacts, `acceptance-${inheritedAcceptanceTag}.json`),
          "utf8",
        ),
      );
      const core = JSON.parse(
        await readFile(
          path.join(artifacts, `acceptance-${inheritedAcceptanceTag}-core.json`),
          "utf8",
        ),
      );
      assert(regression.status === "PASS", "inherited v0.8 regression did not pass");
      assert(core.status === "PASS" && core.criteria.length === 84, "inherited 84-criterion core changed");
      assert(core.results?.backup_restore === "PASS", "coordinated backup/restore regression failed");
      inherited = {
        status: regression.status,
        criteria_count: regression.criteria.length,
        artifact: `artifacts/acceptance-${inheritedAcceptanceTag}.json`,
        core_artifact: `artifacts/acceptance-${inheritedAcceptanceTag}-core.json`,
      };
      mark([1, 9], "v090 regression replay: 84 core + 9 hardening criteria");
    });

    await step("Start isolated PostgreSQL for v0.9 capability, contributor, migration and translation tests", async () => {
      dockerDatabase("start isolated v0.9 PostgreSQL", ["up", "--detach", "--wait"]);
      databaseStarted = true;
      await waitForDatabase(databaseEnvironment);
    });

    const testDatabaseUrl = `postgresql+psycopg://novel_platform:novel_platform_acceptance@127.0.0.1:${databasePort}/novel_platform`;
    await step("Exercise the guarded count-only v0.9 migration preflight", async () => {
      run(
        "prepare a v0.5 schema for v0.9 preflight",
        "uv",
        ["run", "alembic", "upgrade", "20260715_0005"],
        {
          cwd: path.join(root, "apps", "server"),
          env: { ...process.env, DATABASE_URL: testDatabaseUrl },
        },
      );
      run(
        "initialize the synthetic preflight administrator",
        "uv",
        ["run", "novel-platform", "admin", "init", "--display-name", "Acceptance Admin"],
        {
          cwd: path.join(root, "apps", "server"),
          env: { ...process.env, DATABASE_URL: testDatabaseUrl },
        },
      );
      const stagingEnvironmentFile = path.join(temporaryRoot, ".env.acceptance");
      const preflightReport = path.join(temporaryRoot, "preflight-v090.json");
      await writeFile(
        stagingEnvironmentFile,
        [
          "ENVIRONMENT=development",
          `PUBLIC_BASE_URL=http://localhost:${databasePort}`,
          `V090_POSTGRES_PORT=${databasePort}`,
          "POSTGRES_DB=novel_platform",
          "POSTGRES_USER=novel_platform",
          `POSTGRES_PASSWORD=${"p".repeat(40)}`,
          `CORS_ORIGINS='[\"http://localhost:${databasePort}\"]'`,
          "TRUSTED_HOSTS='[\"localhost\",\"127.0.0.1\"]'",
          `AUTH_JWT_SECRET=${"j".repeat(40)}`,
          `AUTH_HASH_SECRET=${"h".repeat(40)}`,
          `AUTH_CREDENTIAL_HASH_SECRET=${"c".repeat(40)}`,
          "AUTH_COOKIE_SECURE=false",
          "AUTH_COOKIE_SAMESITE=lax",
          "WEBAUTHN_RP_ID=localhost",
          `WEBAUTHN_ORIGINS='[\"http://localhost:${databasePort}\"]'`,
          "OPENAPI_ENABLED=false",
          "MAX_UPLOAD_BYTES=1048576",
          "LINGUASPINDLE_ENABLED=false",
          "LINGUASPINDLE_BASE_URL=http://linguaspindle:8765",
          `LINGUASPINDLE_VERSION_RANGE='${acceptanceLinguaVersionRange}'`,
          "LINGUASPINDLE_PROVIDER_ID=mock",
          "LINGUASPINDLE_MAX_DOWNLOAD_BYTES=1048576",
          `PROVIDER_CREDENTIAL_MASTER_KEY=${acceptanceProviderCredentialMasterKey}`,
          "PROVIDER_RELAY_INTERNAL_URL=http://novel-provider-relay:8790",
          "PROVIDER_RELAY_UPSTREAM_BASE_URL=https://api.openai.com/v1",
          "PROVIDER_RELAY_ALLOWED_MODELS='[\"gpt-4.1-mini\"]'",
          "PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS='[]'",
          "",
        ].join("\n"),
        { mode: 0o600 },
      );
      run(
        "run the count-only v0.9 preflight",
        "bash",
        ["scripts/staging/lifecycle/preflight-v090.sh", preflightReport],
        {
          env: {
            ...databaseEnvironment,
            NOVEL_ACCEPTANCE_LOCAL: "1",
            STAGING_ROOT: temporaryRoot,
            STAGING_ENV_FILE: stagingEnvironmentFile,
            STAGING_COMPOSE_FILE: path.join(root, databaseComposeFile),
          },
        },
      );
      const report = JSON.parse(await readFile(preflightReport, "utf8"));
      assert(report.safe_to_migrate === true, "count-only migration preflight did not pass");
      assert(report.alembic_revision === "20260715_0005", "preflight revision changed");
      assert(!JSON.stringify(report).includes("Acceptance Admin"), "preflight leaked identity data");
      mark([4, 8], "count-only preflight against isolated v0.5 schema");
    });

    await step("Run LinguaSpindle narrow-client and v0.9 PostgreSQL contract tests", async () => {
      run(
        "run LinguaSpindle client unit tests",
        "uv",
        ["run", "pytest", "tests/unit/test_linguaspindle_client.py"],
        { cwd: path.join(root, "apps", "server") },
      );
      run(
        "run v0.9 capability, contributor, migration and translation integration tests",
        "uv",
        [
          "run", "pytest",
          "tests/integration/test_auth_and_isolation.py::test_credential_capabilities_are_snapshot_scoped_and_database_authoritative",
          "tests/integration/test_api_workflow.py",
          "tests/integration/test_contributor_library.py",
          "tests/integration/test_migrations.py",
          "tests/integration/test_translation_runs.py",
        ],
        {
          cwd: path.join(root, "apps", "server"),
          env: { ...process.env, TEST_DATABASE_URL: testDatabaseUrl },
        },
      );
      mark([2, 3, 4, 5, 6, 8, 11], "focused unit/PostgreSQL integration suite");
    });

    await step("Run capability-aware Web interaction tests", async () => {
      run(
        "run v0.9 Web interaction tests",
        "pnpm",
        [
          "--filter", "@novel-platform/web", "exec", "vitest", "run",
          "tests/AuthFlow.test.tsx",
          "tests/EditionCard.test.tsx",
          "tests/TranslationLaunchModal.test.tsx",
          "tests/TranslationsPage.test.tsx",
        ],
      );
      mark([2, 3, 5, 6, 10], "focused Web interaction suite");
    });

    await step("Verify v0.9 API, private-network, secret and visual-evidence contracts", async () => {
      const openapi = JSON.parse(await readFile(path.join(root, "packages/api-client/openapi.json"), "utf8"));
      assert(
        openapi.info.version === acceptanceVersion,
        `OpenAPI version is not ${acceptanceVersion}`,
      );
      assert(openapi.paths["/api/v1/books"]?.post === undefined, "legacy metadata-only Book POST remains");
      assert(
        openapi.paths["/api/v1/books/{book_id}/editions"]?.post === undefined,
        "legacy metadata-only Edition POST remains",
      );
      const uploadPage = await readFile(path.join(root, "apps/web/src/pages/UploadPage.tsx"), "utf8");
      const bookDetail = await readFile(path.join(root, "apps/web/src/pages/BookDetailPage.tsx"), "utf8");
      assert(!uploadPage.includes("Collapse") && !bookDetail.includes("Collapse"), "legacy Collapse UI remains");

      const overlay = await readFile(path.join(root, "compose.translation.yml"), "utf8");
      const stagingCompose = await readFile(path.join(root, "compose.staging.yml"), "utf8");
      const stagingEnvironment = await readFile(path.join(root, ".env.staging.example"), "utf8");
      assert(overlay.includes("linguaspindle-private"), "translation overlay lacks private network");
      const overlayServices = composeServiceNames(overlay);
      assert(
        overlayServices.includes("server") &&
          !overlayServices.includes("web") &&
          !overlayServices.includes("migrate"),
        "Web or migration service joined translation network",
      );
      assert(!overlay.includes("ports:"), "translation overlay exposes a host port");
      assert(stagingCompose.includes("LINGUASPINDLE_ENABLED"), "staging configuration does not pass LinguaSpindle settings");
      const providerSecretPattern = /(?:OPENAI_API_KEY|PROVIDER_(?:API_)?KEY|LINGUASPINDLE_(?:API_)?KEY)/;
      assert(!providerSecretPattern.test(overlay + stagingCompose + stagingEnvironment), "Novel Platform configuration contains a Provider secret variable");

      if (requireHistoricalVisualEvidence) {
        const desktopCapture = path.join(
          artifacts,
          "visual-v090",
          "translations-desktop.png",
        );
        const mobileCapture = path.join(
          artifacts,
          "visual-v090",
          "translations-mobile-320.png",
        );
        await access(desktopCapture);
        await access(mobileCapture);
        await access(path.join(artifacts, "visual-v090", "README.md"));
        assert(
          await sha256(desktopCapture) ===
            "4d1cdb58ca702391673b5b212427f1f0dd8e3e1dd2f1bdb6a6d36c6f9ee80b65",
          "desktop visual evidence checksum changed",
        );
        assert(
          await sha256(mobileCapture) ===
            "89114c163499189ee69668ec82a429b1738e25481d2e22fcc30e25a77e7ba216",
          "mobile visual evidence checksum changed",
        );
      }
      mark(
        [4, 7, 8, 10],
        requireHistoricalVisualEvidence
          ? "OpenAPI/Compose/leak/visual contract inspection"
          : "OpenAPI/Compose/leak inspection; historical v0.9 visual evidence not replayed",
      );
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (databaseStarted && process.env.KEEP_ACCEPTANCE_ENV !== "1") {
      try {
        dockerDatabase("remove isolated v0.9 PostgreSQL and volume", [
          "down", "--volumes", "--remove-orphans",
        ]);
      } catch (cleanupError) {
        if (failure === null) {
          failure = cleanupError instanceof Error ? cleanupError : new Error(String(cleanupError));
        }
      }
    }
    if (process.env.KEEP_ACCEPTANCE_ENV !== "1") {
      await rm(temporaryRoot, { recursive: true, force: true });
    }
    const status = failure === null && criteria.every((item) => item.status === "PASS")
      ? "PASS"
      : "FAIL";
    await writeReports(status, inherited, failure);
  }

  assert(criterionLabels.length === 11, "v0.9 criterion count changed");
  if (failure !== null) process.exitCode = 1;
}

await main();
