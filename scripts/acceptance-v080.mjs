import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const markdownPath = path.join(artifacts, "acceptance-v080.md");
const jsonPath = path.join(artifacts, "acceptance-v080.json");
const actionLogPath = path.join(artifacts, "acceptance-v080-actions.log");
const coreJsonPath = path.join(artifacts, "acceptance-v080-core.json");
const chainComposeFile = "scripts/acceptance-v080.chain.yml";
const started = new Date();
const actions = [];
const steps = [];
const sensitive = new Set();

const CLIENT_IP = "10.208.8.3";
const EDGE_IP = "10.208.8.2";
const FORGED_IP = "198.51.100.7";

const hardeningCriterionLabels = [
  "两跳代理链路向应用交付真实客户端 IP",
  "客户端伪造 X-Forwarded-For 不影响应用所见来源",
  "非可信 peer 直连不能注入伪造来源地址",
  "登录入口限流返回稳定 429 JSON、no-store、Retry-After 且被拦截请求不写审计",
  "Passkey authentication options 入口限流且被拦截请求不写入挑战行",
  "健康探针、公开站点接口与 SPA 经两跳链路保持可用",
  "Cookie 模式 refresh 缺失或伪造 Origin 被拒绝且不清除会话 Cookie",
  "refresh 绑定设备密钥：仅持 refresh token 不能轮换或撤销会话，持设备密钥 replay 仍撤销整个会话",
  "staging 环境强制 SameSite=Strict 认证 Cookie 并通过启动校验",
];

const deploymentPendingItems = [
  "在真实 HTTPS 域名上复核宿主 Caddy/Nginx → Compose Nginx → FastAPI 两跳链路交付真实访客 IP（含伪造 X-Forwarded-For 负面用例）",
  "在真实域名完成管理员 Passkey 注册/登录并复核 SameSite=Strict 认证 Cookie 行为",
  "按真实流量复核登录与 Passkey options 入口限流阈值并记录实测依据",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function secret(bytes = 32) {
  const value = randomBytes(bytes).toString("base64url");
  sensitive.add(value);
  return value;
}

function remember(value) {
  if (typeof value === "string" && value.length >= 8) sensitive.add(value);
  return value;
}

function redact(value) {
  let output = String(value ?? "");
  for (const item of [...sensitive].sort((left, right) => right.length - left.length)) {
    output = output.replaceAll(item, "[REDACTED]");
  }
  return output
    .replace(/\bnpa_[A-Za-z0-9_-]{32,}\b/g, "npa_[REDACTED]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[JWT REDACTED]")
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [REDACTED]")
    .replace(/(?:novel_refresh|novel_device)=[^;\s]+/g, "[COOKIE REDACTED]")
    .replace(/postgres(?:ql)?(?:\+\w+)?:\/\/[^:\s/]+:[^@\s/]+@/gi, "postgresql://[REDACTED]@")
    .replaceAll("/data/library", "[STORAGE ROOT]");
}

function run(label, executable, args, options = {}) {
  actions.push(label);
  try {
    return execFileSync(executable, args, {
      cwd: options.cwd ?? root,
      env: options.env ?? process.env,
      encoding: "utf8",
      stdio: [options.input === undefined ? "ignore" : "pipe", "pipe", "pipe"],
      input: options.input,
      maxBuffer: 80 * 1024 * 1024,
    });
  } catch (error) {
    const detail = redact(error.stderr ?? error.stdout ?? error.message);
    throw new Error(`${label} failed${detail ? `: ${detail.slice(-1200)}` : ""}`);
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

async function waitFor(url, timeoutMs = 240_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // Containers can be healthy before the host socket is ready.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${url} did not become ready`);
}

const chainProject = `novel-v080-chain-${process.pid}-${Date.now()}`;
const chainEnvironment = { ...process.env };
const dockerChain = (label, args) =>
  run(label, "docker", ["compose", "-p", chainProject, "-f", chainComposeFile, ...args], {
    env: chainEnvironment,
  });
const psql = (label, sql) =>
  dockerChain(label, [
    "exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
    "-U", "novel_platform", "-d", "novel_platform", "-Atc", sql,
  ]);
const clientExec = (label, args) => dockerChain(label, ["exec", "-T", "client", ...args]);

function bogusLoginPayload() {
  return {
    credential: `npa_${"x".repeat(43)}`,
    refresh_token_delivery: "body",
    device: {
      client_instance_id: randomUUID(),
      name: "链路探测设备",
      platform: "web",
      app_version: "0.8.0-acceptance",
    },
  };
}

async function bogusLogin({ viaEdge = true, forged = null } = {}) {
  const target = `http://${viaEdge ? "edge" : "web"}:8080/api/v1/auth/login`;
  const args = [
    "curl", "-sS", "-o", "/tmp/body.json", "-w", "%{http_code}",
    "-X", "POST", "-H", "Content-Type: application/json",
  ];
  if (forged) args.push("-H", `X-Forwarded-For: ${forged}`);
  args.push("--data", JSON.stringify(bogusLoginPayload()), target);
  const code = (await clientExec("send bogus credential login through the chain", args)).trim();
  return Number(code);
}

async function latestLoginFailureIp() {
  return (
    await psql(
      "read latest login failure client IP",
      "SELECT client_ip FROM auth_audit_events WHERE event_type = 'login_failed' ORDER BY created_at DESC LIMIT 1",
    )
  ).trim();
}

async function auditWriteCount() {
  const output = await psql(
    "count login audit rows",
    "SELECT count(*) FROM auth_audit_events WHERE event_type IN ('login_failed','login_rate_limited')",
  );
  return Number(output.trim());
}

async function challengeRowCount() {
  const output = await psql(
    "count WebAuthn challenge rows",
    "SELECT count(*) FROM webauthn_challenges",
  );
  return Number(output.trim());
}

function extractCredential(cliOutput) {
  const match = String(cliOutput).match(/npa_[A-Za-z0-9_-]+/);
  assert(match, "CLI did not emit a credential");
  return remember(match[0]);
}

async function cookieLogin(jarPath, credential) {
  await clientExec("prepare cookie jar", ["touch", jarPath]);
  const payload = {
    credential,
    refresh_token_delivery: "cookie",
    device: {
      client_instance_id: randomUUID(),
      name: "链路验收浏览器",
      platform: "web",
      app_version: "0.8.0-acceptance",
    },
  };
  const code = (
    await clientExec("perform cookie-delivery login through the chain", [
      "curl", "-sS", "-D", "/tmp/login-headers.txt", "-o", "/tmp/login-body.json",
      "-w", "%{http_code}", "-c", jarPath, "-b", jarPath,
      "-X", "POST", "-H", "Content-Type: application/json",
      "-H", "Origin: http://edge:8080",
      "--data", JSON.stringify(payload), "http://edge:8080/api/v1/auth/login",
    ])
  ).trim();
  assert(code === "200", `cookie login returned ${code}`);
}

async function readJarValue(jarPath, name) {
  const jar = await clientExec("read cookie jar", ["cat", jarPath]);
  const line = jar.split("\n").find((entry) => entry.includes(`\t${name}\t`));
  assert(line, `${name} cookie missing from jar`);
  return remember(line.trim().split("\t").pop());
}

async function writeReports(status, core, criteria, failure) {
  const report = {
    version: "0.8.0",
    status,
    deployment_status: "DEPLOYMENT_PENDING",
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: run("read Git commit", "git", ["rev-parse", "HEAD"]).trim(),
    inherited_v050: {
      status: core?.status ?? "NOT_RUN",
      criteria_count: core?.criteria?.length ?? 0,
      artifact: "artifacts/acceptance-v080-core.json",
    },
    hardening: {
      criteria,
      steps,
    },
    deployment_pending: deploymentPendingItems,
    criteria: [...(core?.criteria ?? []), ...criteria],
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await mkdir(artifacts, { recursive: true });
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  const markdown = [
    "# Novel Platform v0.8.0 authentication hardening acceptance",
    "",
    `- Status: **${status}**`,
    "- Real-domain verification: **DEPLOYMENT_PENDING**",
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${report.git_commit}`,
    `- Inherited v0.5.0 criteria: ${report.inherited_v050.criteria_count} (${report.inherited_v050.status})`,
    `- v0.8.0 hardening criteria: ${criteria.length}`,
    "",
    "## v0.8.0 hardening criteria",
    "",
    "| # | Status | Criterion |",
    "| ---: | --- | --- |",
    ...criteria.map((item) => `| ${item.number} | ${item.status} | ${item.label} |`),
    "",
    "## Hardening steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map((item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail} |`),
    "",
    "## Deployment pending",
    "",
    ...deploymentPendingItems.map((item) => `- DEPLOYMENT_PENDING: ${item}`),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required checks.",
    "",
    "Reports use synthetic, sanitized data. Credentials, tokens, Cookies, WebAuthn challenges, database URLs, and host paths are excluded.",
    "",
  ].join("\n");
  await writeFile(markdownPath, markdown, { mode: 0o600 });
  await writeFile(
    actionLogPath,
    [
      "Novel Platform v0.8.0 sanitized acceptance action log",
      "No command arguments, command output, credentials, tokens, Cookies, request bodies, or host paths are recorded.",
      "",
      ...actions.map((label) => `[ACTION] ${label}`),
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
}

async function main() {
  await mkdir(artifacts, { recursive: true });
  const edgePort = await freePort();
  const criteria = hardeningCriterionLabels.map((label, index) => ({
    number: 106 + index,
    label,
    status: "NOT_RUN",
  }));
  let core;
  let failure = null;
  let chainStarted = false;

  Object.assign(chainEnvironment, {
    POSTGRES_PASSWORD: secret(24),
    EDGE_PORT: String(edgePort),
    ENVIRONMENT: "staging",
    CORS_ORIGINS: `["http://127.0.0.1:${edgePort}","http://edge:8080"]`,
    WEBAUTHN_ORIGINS: `["http://127.0.0.1:${edgePort}","http://edge:8080"]`,
    TRUSTED_HOSTS: '["127.0.0.1","localhost","edge","web"]',
    AUTH_JWT_SECRET: secret(),
    AUTH_HASH_SECRET: secret(),
    AUTH_CREDENTIAL_HASH_SECRET: secret(),
    AUTH_COOKIE_SECURE: "false",
    AUTH_COOKIE_SAMESITE: "strict",
    MAX_UPLOAD_BYTES: String(1024 * 1024),
    STAGING_REAL_IP_PEER: EDGE_IP,
  });

  const chainCriterion = async (number, action) => {
    const item = criteria.find((entry) => entry.number === number);
    try {
      await step(`criterion ${number}`, action);
      item.status = "PASS";
    } catch (error) {
      item.status = "FAIL";
      throw error;
    }
  };

  try {
    await step("Replay all 84 v0.5.0 criteria against v0.8.0", async () => {
      run("run inherited v0.5.0 acceptance core", process.execPath, [
        "scripts/acceptance-v050.mjs",
      ], {
        env: {
          ...process.env,
          ACCEPTANCE_VERSION: "0.8.0",
          ACCEPTANCE_TAG: "v080-core",
          ACCEPTANCE_COMMAND: "acceptance:v080",
          // The current Web UI is the v0.7 Quiet Trace generation; the v0.5 core
          // uses this profile only to pick the current labels and task paths.
          ACCEPTANCE_PROFILE: "v070",
        },
      });
      core = JSON.parse(await readFile(coreJsonPath, "utf8"));
      assert(core.status === "PASS", "Inherited v0.5.0 acceptance core did not pass");
      assert(core.criteria.length === 84, "Inherited criterion count changed");
      assert(
        core.criteria.every((item) => item.status === "PASS"),
        "Inherited criteria contain a failure",
      );
    });

    await step("Verify staging proxy hardening configuration contract", async () => {
      const nginxConfig = await readFile(
        path.join(root, "apps", "web", "nginx.staging.conf"),
        "utf8",
      );
      const dockerfile = await readFile(
        path.join(root, "apps", "web", "Dockerfile.staging"),
        "utf8",
      );
      const upstreamSnippet = await readFile(
        path.join(root, "apps", "web", "nginx", "staging-upstream-headers.conf"),
        "utf8",
      );
      assert(
        nginxConfig.includes("set_real_ip_from __STAGING_REAL_IP_PEER__;"),
        "staging Nginx no longer restricts the trusted real-ip peer",
      );
      assert(
        nginxConfig.includes("real_ip_header X-Forwarded-For;")
          && nginxConfig.includes("real_ip_recursive on;"),
        "staging Nginx real-ip resolution is not recursive X-Forwarded-For",
      );
      assert(
        /ARG STAGING_REAL_IP_PEER=172\.30\.19\.1\b/.test(dockerfile),
        "trusted peer default must stay the measured host bridge 172.30.19.1",
      );
      assert(dockerfile.includes("nginx -t"), "image build must run nginx -t");
      assert(
        dockerfile.includes('!= "0.0.0.0"'),
        "image build must reject the meaningless 0.0.0.0 peer",
      );
      const peerValidation = dockerfile.match(/grep -Eq '([^']+)'/);
      assert(peerValidation, "Dockerfile lost the canonical IPv4 validation");
      const peerAccepted = (value) => {
        try {
          run("probe real-ip peer validation", "grep", ["-Eq", peerValidation[1]], {
            input: `${value}\n`,
          });
          return true;
        } catch {
          return false;
        }
      };
      for (const good of ["172.30.19.1", "10.208.8.2", "255.255.255.255", "0.0.0.1"]) {
        assert(peerAccepted(good), `canonical IPv4 ${good} must be accepted`);
      }
      for (const bad of [
        "999.999.999.999",
        "172.30.19.256",
        "172.30.19.1/32",
        "0.0.0.0/0",
        "",
        "example.com",
        "172.30.19.01",
      ]) {
        assert(!peerAccepted(bad), `invalid peer ${bad || "(empty)"} must be rejected`);
      }
      const envScript = await readFile(
        path.join(root, "scripts", "create-staging-env.sh"),
        "utf8",
      );
      assert(
        envScript.includes("AUTH_COOKIE_SAMESITE=strict"),
        "staging env generation must emit SameSite=Strict",
      );
      const zones = [...nginxConfig.matchAll(/limit_req_zone\s+\$binary_remote_addr\s+zone=(\w+)/g)];
      assert(zones.length === 2, "entry rate limiting must key on exactly two realip-based zones");
      const loginBlock = nginxConfig.match(/location = \/api\/v1\/auth\/login \{([^}]*)\}/);
      const optionsBlock = nginxConfig.match(
        /location = \/api\/v1\/auth\/passkeys\/authentication\/options \{([^}]*)\}/,
      );
      assert(loginBlock?.[1].includes("limit_req zone="), "login endpoint lost its entry limit");
      assert(
        optionsBlock?.[1].includes("limit_req zone="),
        "passkey options endpoint lost its entry limit",
      );
      const limitDirectives = [...nginxConfig.matchAll(/limit_req zone=/g)];
      assert(limitDirectives.length === 2, "rate limiting must stay scoped to the two auth entries");
      assert(nginxConfig.includes("limit_req_status 429;"), "429 status mapping missing");
      const rateLimitedBlock = nginxConfig.match(/location @rate_limited \{([^}]*)\}/);
      assert(
        rateLimitedBlock?.[1].includes("auth_entry_rate_limited")
          && rateLimitedBlock?.[1].includes("Retry-After")
          && rateLimitedBlock?.[1].includes("no-store"),
        "429 response must be stable JSON with Retry-After and no-store",
      );
      assert(
        !nginxConfig.includes("proxy_set_header X-Forwarded-For"),
        "proxy forwarding headers must live in the shared snippet, not per-location copies",
      );
      assert(
        upstreamSnippet.includes("proxy_set_header X-Forwarded-For $remote_addr;"),
        "shared upstream snippet lost the real-ip forwarding rule",
      );
      const policies = [...nginxConfig.matchAll(
        /add_header Content-Security-Policy "([^"]+)"/g,
      )].map((match) => match[1]);
      assert(policies.length > 0, "Staging Content-Security-Policy headers are missing");
      for (const policy of policies) {
        assert(
          /(?:^|;\s*)style-src 'self' 'unsafe-inline'(?:;|$)/.test(policy),
          "Staging CSP blocks Ant Design runtime styles",
        );
        assert(
          /(?:^|;\s*)script-src 'self'(?:;|$)/.test(policy),
          "Staging CSP no longer restricts scripts to same-origin files",
        );
        assert(
          !/(?:^|;\s*)script-src[^;]*'unsafe-inline'/.test(policy),
          "Staging CSP allows inline scripts",
        );
      }
    });

    await step("Build and start the two-hop proxy chain environment", async () => {
      run("check Docker", "docker", ["--version"]);
      run("check Docker Compose", "docker", ["compose", "version"]);
      chainStarted = true;
      dockerChain("build and start v0.8.0 proxy chain stack", ["up", "--build", "--detach"]);
      await waitFor(`http://127.0.0.1:${edgePort}/healthz`);
      dockerChain("validate built staging Nginx configuration", ["exec", "-T", "web", "nginx", "-t"]);
      const revision = (
        await psql("read Alembic revision", "SELECT version_num FROM alembic_version")
      ).trim();
      assert(revision === "20260715_0005", `unexpected migration revision ${revision}`);
    });

    await chainCriterion(106, async () => {
      const status = await bogusLogin({ viaEdge: true });
      assert(status === 401, `expected 401 from bogus login, got ${status}`);
      const clientIp = await latestLoginFailureIp();
      assert(
        clientIp === CLIENT_IP,
        `application saw ${clientIp}, expected the real client ${CLIENT_IP}`,
      );
    });

    await chainCriterion(107, async () => {
      const status = await bogusLogin({ viaEdge: true, forged: FORGED_IP });
      assert(status === 401, `expected 401 from bogus login, got ${status}`);
      const clientIp = await latestLoginFailureIp();
      assert(
        clientIp === CLIENT_IP,
        `forged X-Forwarded-For changed the application source to ${clientIp}`,
      );
    });

    await chainCriterion(108, async () => {
      const status = await bogusLogin({ viaEdge: false, forged: FORGED_IP });
      assert(status === 401, `expected 401 from direct bogus login, got ${status}`);
      const clientIp = await latestLoginFailureIp();
      assert(
        clientIp === CLIENT_IP,
        `untrusted peer injected ${clientIp} as the application source`,
      );
    });

    await chainCriterion(111, async () => {
      const base = `http://127.0.0.1:${edgePort}`;
      const health = await fetch(`${base}/healthz`);
      assert(health.ok, "health probe failed through the chain");
      const site = await fetch(`${base}/api/v1/site`);
      assert(site.ok, "public site endpoint failed through the chain");
      assert(
        site.headers.get("x-robots-tag")?.includes("noindex"),
        "noindex header missing through the chain",
      );
      const page = await fetch(`${base}/`);
      assert(page.ok, "SPA entry failed through the chain");
      assert((await page.text()).includes('<div id="root">'), "SPA entry HTML changed");
    });

    await chainCriterion(112, async () => {
      const initOutput = await dockerChain("initialize chain administrator", [
        "exec", "-T", "server", "novel-platform", "admin", "init",
        "--display-name", "链路验收管理员",
      ]);
      const credential = extractCredential(initOutput);
      await cookieLogin("/tmp/jar-a", credential);

      const missingOrigin = (
        await clientExec("cookie refresh without Origin", [
          "curl", "-sS", "-o", "/tmp/r1.json", "-w", "%{http_code}",
          "-c", "/tmp/jar-a", "-b", "/tmp/jar-a",
          "-X", "POST", "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(missingOrigin === "403", `missing Origin returned ${missingOrigin}`);
      const jarAfterRejection = await clientExec("inspect jar after Origin rejection", [
        "cat", "/tmp/jar-a",
      ]);
      assert(
        jarAfterRejection.includes("novel_refresh"),
        "Origin rejection must not clear the session cookie",
      );

      const evilOrigin = (
        await clientExec("cookie refresh with forged Origin", [
          "curl", "-sS", "-o", "/tmp/r2.json", "-w", "%{http_code}",
          "-c", "/tmp/jar-a", "-b", "/tmp/jar-a",
          "-X", "POST", "-H", "Origin: https://evil.example",
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(evilOrigin === "403", `forged Origin returned ${evilOrigin}`);

      const allowed = (
        await clientExec("cookie refresh with allowed Origin", [
          "curl", "-sS", "-o", "/tmp/r3.json", "-w", "%{http_code}",
          "-c", "/tmp/jar-a", "-b", "/tmp/jar-a",
          "-X", "POST", "-H", "Origin: http://edge:8080",
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(allowed === "200", `allowed Origin refresh returned ${allowed}`);
      const rotated = JSON.parse(
        await clientExec("read rotated refresh response", ["cat", "/tmp/r3.json"]),
      );
      assert(rotated.access_token, "refresh rotation did not return an access token");
    });

    await chainCriterion(113, async () => {
      const recoveryOutput = await dockerChain("issue a second recovery credential", [
        "exec", "-T", "server", "novel-platform", "admin", "recovery", "create",
      ]);
      const credential = extractCredential(recoveryOutput);
      await cookieLogin("/tmp/jar-b", credential);
      const refreshCookie = await readJarValue("/tmp/jar-b", "novel_refresh");
      const deviceCookie = await readJarValue("/tmp/jar-b", "novel_device");

      const stolenOnly = (
        await clientExec("refresh with only the stolen refresh token", [
          "curl", "-sS", "-o", "/tmp/rb1.json", "-w", "%{http_code}",
          "-X", "POST", "-H", "Origin: http://edge:8080",
          "-b", `novel_refresh=${refreshCookie}`,
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(stolenOnly === "401", `stolen-token refresh returned ${stolenOnly}`);
      const stolenBody = JSON.parse(
        await clientExec("read stolen-token response", ["cat", "/tmp/rb1.json"]),
      );
      assert(
        stolenBody?.error?.code === "invalid_refresh_token",
        "stolen-token refresh must get the uniform invalid credential error",
      );

      const legitimate = (
        await clientExec("legitimate refresh with both cookies", [
          "curl", "-sS", "-o", "/tmp/rb2.json", "-w", "%{http_code}",
          "-c", "/tmp/jar-b", "-b", "/tmp/jar-b",
          "-X", "POST", "-H", "Origin: http://edge:8080",
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(
        legitimate === "200",
        "session must survive a stolen-token attempt without the device secret",
      );

      const replay = (
        await clientExec("replay old token with the correct device secret", [
          "curl", "-sS", "-o", "/tmp/rb3.json", "-w", "%{http_code}",
          "-X", "POST", "-H", "Origin: http://edge:8080",
          "-b", `novel_refresh=${refreshCookie}; novel_device=${deviceCookie}`,
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(replay === "401", `device-bound replay returned ${replay}`);
      const replayBody = JSON.parse(
        await clientExec("read replay response", ["cat", "/tmp/rb3.json"]),
      );
      assert(
        replayBody?.error?.code === "refresh_token_reused",
        "device-bound replay must still be detected and revoked",
      );
      const afterRevoke = (
        await clientExec("refresh after replay revocation", [
          "curl", "-sS", "-o", "/tmp/rb4.json", "-w", "%{http_code}",
          "-c", "/tmp/jar-b", "-b", "/tmp/jar-b",
          "-X", "POST", "-H", "Origin: http://edge:8080",
          "http://edge:8080/api/v1/auth/refresh",
        ])
      ).trim();
      assert(afterRevoke === "401", "session must be revoked after a confirmed replay");
    });

    await chainCriterion(114, async () => {
      const headers = await clientExec("read login response headers", [
        "cat", "/tmp/login-headers.txt",
      ]);
      const cookieLines = headers
        .split("\n")
        .filter((line) => line.toLowerCase().startsWith("set-cookie: novel_"));
      assert(cookieLines.length >= 2, "login must set refresh and device cookies");
      for (const line of cookieLines) {
        assert(
          /samesite=strict/i.test(line),
          `authentication cookie is not SameSite=Strict: ${redact(line)}`,
        );
      }
    });

    await chainCriterion(109, async () => {
      const auditBefore = await auditWriteCount();
      const payload = JSON.stringify(bogusLoginPayload());
      const burstScript = [
        "rm -f /tmp/rl-*.json /tmp/rl-codes.txt /tmp/rl-headers-*.txt /tmp/rl-final-codes.txt",
        "for i in $(seq 1 20); do",
        `  code=$(curl -sS -o "/tmp/rl-$i.json" -w "%{http_code}" -X POST -H "Content-Type: application/json" --data '${payload}' http://edge:8080/api/v1/auth/login)`,
        '  echo "$i:$code" >> /tmp/rl-codes.txt',
        "done",
        "for j in $(seq 1 5); do",
        `  code=$(curl -sS -D "/tmp/rl-headers-$j.txt" -o "/tmp/rl-final-$j.json" -w "%{http_code}" -X POST -H "Content-Type: application/json" --data '${payload}' http://edge:8080/api/v1/auth/login)`,
        '  echo "$j:$code" >> /tmp/rl-final-codes.txt',
        "done",
      ].join("\n");
      await clientExec("run login burst script", ["sh", "-c", burstScript]);
      const codes = (await clientExec("read burst status codes", ["cat", "/tmp/rl-codes.txt"]))
        .trim()
        .split("\n")
        .map((line) => Number(line.split(":")[1]));
      assert(codes.length === 20, "burst did not record 20 responses");
      const bodies = await Promise.all(
        codes.map(async (_, index) =>
          JSON.parse(await clientExec("read burst response body", ["cat", `/tmp/rl-${index + 1}.json`])),
        ),
      );
      const classify = (index) => {
        if (codes[index] === 401) return "app401";
        if (codes[index] === 429 && bodies[index]?.error?.code === "login_temporarily_blocked") {
          return "app429";
        }
        if (codes[index] === 429 && bodies[index]?.error?.code === "auth_entry_rate_limited") {
          return "nginx429";
        }
        return "unexpected";
      };
      const kinds = codes.map((_, index) => classify(index));
      assert(!kinds.includes("unexpected"), `unexpected burst response kinds: ${kinds}`);
      const throughCount = kinds.filter((kind) => kind !== "nginx429").length;
      const entryBlocked = kinds.filter((kind) => kind === "nginx429").length;
      assert(entryBlocked >= 1, "entry rate limiter never engaged");
      const auditAfter = await auditWriteCount();
      assert(
        auditAfter - auditBefore === throughCount,
        `entry-blocked requests wrote audit rows: delta ${auditAfter - auditBefore}, through ${throughCount}`,
      );
      const finalCodes = (
        await clientExec("read final burst status codes", ["cat", "/tmp/rl-final-codes.txt"])
      )
        .trim()
        .split("\n")
        .map((line) => Number(line.split(":")[1]));
      const limitedAttempt = finalCodes.findIndex((code) => code === 429);
      assert(limitedAttempt >= 0, "post-burst requests should still be entry limited");
      const finalHeaders = await clientExec("read final burst headers", [
        "cat",
        `/tmp/rl-headers-${limitedAttempt + 1}.txt`,
      ]);
      assert(/retry-after:/i.test(finalHeaders), "429 response lacks Retry-After");
      assert(/cache-control:\s*no-store/i.test(finalHeaders), "429 response lacks no-store");
      const finalBody = JSON.parse(
        await clientExec("read final burst body", [
          "cat",
          `/tmp/rl-final-${limitedAttempt + 1}.json`,
        ]),
      );
      assert(
        finalBody?.error?.code === "auth_entry_rate_limited"
          && typeof finalBody?.error?.message === "string"
          && typeof finalBody?.error?.details === "object",
        "429 response must keep the stable JSON error structure",
      );
    });

    await chainCriterion(110, async () => {
      const challengesBefore = await challengeRowCount();
      const burstScript = [
        "rm -f /tmp/pk-*.json /tmp/pk-codes.txt",
        "for i in $(seq 1 12); do",
        '  code=$(curl -sS -o "/tmp/pk-$i.json" -w "%{http_code}" -X POST -H "Origin: http://edge:8080" http://edge:8080/api/v1/auth/passkeys/authentication/options)',
        '  echo "$i:$code" >> /tmp/pk-codes.txt',
        "done",
      ].join("\n");
      await clientExec("run passkey options burst script", ["sh", "-c", burstScript]);
      const codes = (await clientExec("read options burst status codes", ["cat", "/tmp/pk-codes.txt"]))
        .trim()
        .split("\n")
        .map((line) => Number(line.split(":")[1]));
      assert(codes.length === 12, "options burst did not record 12 responses");
      const bodies = await Promise.all(
        codes.map(async (_, index) =>
          JSON.parse(await clientExec("read options burst body", ["cat", `/tmp/pk-${index + 1}.json`])),
        ),
      );
      const succeeded = codes.filter((code) => code === 200).length;
      const entryBlocked = codes.filter(
        (code, index) =>
          code === 429 && bodies[index]?.error?.code === "auth_entry_rate_limited",
      ).length;
      assert(succeeded >= 1, "no passkey options request reached the application");
      assert(entryBlocked >= 1, "passkey options entry limiter never engaged");
      assert(
        succeeded + entryBlocked === codes.length,
        "unexpected passkey options response mixture",
      );
      const challengesAfter = await challengeRowCount();
      assert(
        challengesAfter - challengesBefore === succeeded,
        `entry-blocked options requests wrote challenge rows: delta ${challengesAfter - challengesBefore}, succeeded ${succeeded}`,
      );
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (chainStarted && process.env.KEEP_ACCEPTANCE_ENV !== "1") {
      try {
        dockerChain("remove v0.8.0 proxy chain stack", ["down", "--volumes", "--remove-orphans"]);
      } catch (cleanupError) {
        console.error(redact(cleanupError instanceof Error ? cleanupError.message : cleanupError));
      }
    }
    const status = failure === null && criteria.every((item) => item.status === "PASS")
      ? "PASS"
      : "FAIL";
    await writeReports(status, core, criteria, failure);
  }
  assert(hardeningCriterionLabels.length === 9, "hardening criterion count changed");
  if (failure !== null) process.exitCode = 1;
}

await main();
