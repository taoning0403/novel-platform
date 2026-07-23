import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

import { chromium } from "@playwright/test";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const acceptanceVersion = process.env.ACCEPTANCE_VERSION ?? "0.5.0";
const acceptanceTag = process.env.ACCEPTANCE_TAG ?? "v050";
const acceptanceCommand = process.env.ACCEPTANCE_COMMAND ?? "acceptance:v050";
const acceptanceProfile = process.env.ACCEPTANCE_PROFILE ?? "v050";
const quietTraceProfile = acceptanceProfile === "v070";
const releaseLabel = `v${acceptanceVersion}`;
const markdownPath = path.join(artifacts, `acceptance-${acceptanceTag}.md`);
const jsonPath = path.join(artifacts, `acceptance-${acceptanceTag}.json`);
const actionLogPath = path.join(artifacts, `acceptance-${acceptanceTag}-actions.log`);
const started = new Date();
const runId = `${process.pid}-${Date.now()}`;
const project = `novel-platform-${acceptanceTag}-${runId}`.toLowerCase();
const keepEnvironment = process.env.KEEP_ACCEPTANCE_ENV === "1";
const steps = [];
const actions = [];
const sensitive = new Set();
const protectedContents = ["验收正文第一段", "验收正文第二段"];

const results = {
  empty_database_migration: "SKIPPED",
  public_boundary: "SKIPPED",
  webauthn_browser: "SKIPPED",
  admin_controls: "SKIPPED",
  reader_credentials: "SKIPPED",
  device_authorization: "SKIPPED",
  library_rbac: "SKIPPED",
  private_reader_state: "SKIPPED",
  migration_regression: "SKIPPED",
  persistence: "SKIPPED",
  backup_restore: "SKIPPED",
  security_audit: "SKIPPED",
  server_quality: "SKIPPED",
  web_quality: "SKIPPED",
  report_sanitization: "SKIPPED",
  unit_tests: 0,
  integration_tests: 0,
  web_tests: 0,
  browser_contexts: 0,
};

const criterionLabels = [
  "匿名 Book 列表拒绝", "匿名 Book/Edition/Series 详情拒绝", "匿名封面与 Reader 内容拒绝",
  "匿名原始文件拒绝", "无公开注册/Setup/用户创建入口", "旧用户名密码登录失效",
  "未登录页面不泄露馆藏或平台化入口", "匿名 OpenAPI UI 关闭", "noindex 策略生效",
  "空备案号不显示虚假备案", "新库仅能通过 CLI 初始化管理员", "初始化凭证一次显示且仅存哈希并按时过期",
  "初始化凭证单次使用", "恢复会话限制馆藏与凭证管理", "Passkey 注册和日常登录",
  "WebAuthn 过期/Origin/RP/重放拒绝", "支持多个 Passkey", "不能撤销最后一个 Passkey",
  "管理员全会话撤销即时生效", "管理员认证重设进入恢复流程", "管理员锁定与解锁",
  "管理员与阅读者统一登录入口", "创建阅读者及其属性", "完整阅读凭证仅创建时显示且 no-store",
  "后续只能查看安全提示", "数据库/日志/报告无完整凭证", "有效凭证登录",
  "无效/过期/暂停/撤销使用统一非枚举错误", "期限缩短到过去即时失效", "暂停撤销会话且恢复不新增设备",
  "禁止新设备时仅已有设备可登录", "凭证撤销为终态", "重签保留阅读者身份与私人状态",
  "凭证会话不超过凭证有效期", "前三个独立浏览器授权", "第四设备拒绝且审计",
  "第四设备失败不影响前三个", "并发登录不能突破上限", "同设备再登录不重复授权",
  "IP 变化不消耗设备名额", "清除设备 Cookie 视为新设备", "client_instance_id 不能冒充设备",
  "设备撤销使其会话失效", "旧记录不能静默复活已撤销设备", "撤销后可授权新设备",
  "缩小上限不自动踢设备但阻止新增", "管理员管理 Book/Edition/Series", "阅读者看到共享可读馆藏",
  "阅读者看不到 draft/archived/无文件/未完成导入", "阅读者可在线读取投影/封面/资源",
  "阅读者不能下载原始文件", "阅读者不能上传/检查/提交/替换", "阅读者不能变更馆藏",
  "阅读者不能管理身份凭证站点审计 Passkey", "后端拒绝绕过而非仅隐藏按钮",
  "阅读者保存自己的进度设置和偏好", "两个阅读者私人状态隔离", "管理员阅读状态独立",
  "阅读者响应不暴露 owner/存储/哈希", "空数据库升级成功", "v0.4.0 数据升级成功",
  "多管理员/所有者预检准确且拒绝猜测", "显式目标管理员统一迁移 owner", "内容与文件修订 ID 保持",
  "Edition 关系/偏好/进度保持", "旧普通用户保留阅读数据", "迁移不生成明文阅读凭证",
  "旧 Session/Refresh/密码登录切断", "数据库与 library volume 一致性审计", "新认证相关表进入完整备份",
  "备份在隔离数据库和 volume 恢复", "已知和未知凭证登录均有限速", "不信任客户端 Forwarded Headers",
  "Token/设备秘密/凭证不进日志报告", "状态变化早于 JWT 过期生效", "审计 UI 仅管理员且无秘密",
  "90 天保留与清理命令", "Server 全质量门禁", "Web/OpenAPI/TypeScript/生产构建门禁",
  "真实 Chromium 虚拟 WebAuthn", "至少四个独立浏览器上下文", "浏览器阅读/重载/进度冲突",
  "重启后认证设置阅读数据持久化", `${acceptanceCommand} 脱敏报告和完整结果`,
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
  for (const content of protectedContents) output = output.replaceAll(content, "[CONTENT REDACTED]");
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

async function apiRequest(apiUrl, method, route, options = {}) {
  const headers = new Headers(options.headers);
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  let body;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  const response = await fetch(`${apiUrl}${route}`, { method, headers, body });
  const raw = response.status === 204 ? "" : await response.text();
  const responseBody = raw ? JSON.parse(raw) : null;
  const expected = Array.isArray(options.expected) ? options.expected : [options.expected ?? 200];
  assert(
    expected.includes(response.status),
    `${method} ${route}: expected ${expected.join("/")}, got ${response.status}: ${redact(raw)}`,
  );
  if (options.errorCode) {
    assert(responseBody?.error?.code === options.errorCode, `${route}: wrong error code`);
  }
  return { body: responseBody, headers: response.headers, status: response.status, raw };
}

function loginPayload(credential, name, clientInstanceId = randomUUID()) {
  return {
    credential,
    refresh_token_delivery: "body",
    device: {
      client_instance_id: clientInstanceId,
      name,
      platform: "web",
      app_version: `${acceptanceVersion}-acceptance`,
    },
  };
}

async function directLogin(apiUrl, credential, name, options = {}) {
  const response = await apiRequest(apiUrl, "POST", "/api/v1/auth/login", {
    body: loginPayload(credential, name, options.clientInstanceId),
    expected: options.expected ?? 200,
    errorCode: options.errorCode,
  });
  if (response.status === 200) {
    remember(response.body.access_token);
    remember(response.body.refresh_token);
  }
  return response;
}

async function newBrowserPage(browser, options = {}) {
  const context = await browser.newContext(options.contextOptions);
  if (options.clientInstanceId) {
    await context.addInitScript((value) => {
      window.localStorage.setItem("novel_client_instance_id", value);
    }, options.clientInstanceId);
  }
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return { context, page, errors };
}

async function credentialLoginPage(page, webUrl, credential, deviceName, expectedStatus = 200) {
  await page.goto(`${webUrl}/login`);
  await page.getByRole("heading", { name: "登录", exact: true }).waitFor();
  await page.getByLabel("访问凭证").fill(credential);
  await page.getByLabel("设备名称").fill(deviceName);
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/auth/login") && response.request().method() === "POST",
  );
  await page.getByRole("button", {
    name: quietTraceProfile ? "进入书库" : "输入访问凭证",
  }).click();
  const response = await responsePromise;
  const body = await response.json();
  assert(response.status() === expectedStatus, `browser credential login returned ${response.status()}`);
  if (expectedStatus === 200) {
    remember(body.access_token);
    if (body.refresh_token) remember(body.refresh_token);
  } else {
    await page.getByRole("alert").waitFor();
  }
  return { body, headers: response.headers() };
}

async function waitForLibraryBook(page, title) {
  if (quietTraceProfile) {
    await page
      .getByRole("region", { name: "全部作品" })
      .getByRole("heading", { name: title, exact: true })
      .waitFor();
    return;
  }
  await page.getByLabel("书库").getByRole("heading", { name: title }).waitFor();
}

async function passkeyLoginPage(page, webUrl, expectedStatus = 200) {
  await page.goto(`${webUrl}/login`);
  await page.getByRole("heading", { name: "登录", exact: true }).waitFor();
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/v1/auth/passkeys/authentication/verify"),
  );
  await page.getByRole("button", { name: "使用安全设备登录" }).click();
  const response = await responsePromise;
  const body = await response.json();
  assert(response.status() === expectedStatus, `browser Passkey login returned ${response.status()}`);
  if (expectedStatus === 200) remember(body.access_token);
  else await page.getByRole("alert").waitFor();
  return body;
}

async function addVirtualAuthenticator(cdp) {
  const added = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return added.authenticatorId;
}

async function capturePasskeyLogin(page) {
  let resolvePayload;
  let rejectPayload;
  const payloadPromise = new Promise((resolve, reject) => {
    resolvePayload = resolve;
    rejectPayload = reject;
  });
  const handler = async (route) => {
    try {
      resolvePayload(route.request().postDataJSON());
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "acceptance_capture", message: "captured" } }),
      });
    } catch (error) {
      rejectPayload(error);
    }
  };
  await page.route("**/api/v1/auth/passkeys/authentication/verify", handler);
  await page.getByRole("button", { name: "使用安全设备登录" }).click();
  const payload = await payloadPromise;
  await page.unroute("**/api/v1/auth/passkeys/authentication/verify", handler);
  await page.getByRole("alert").waitFor();
  return payload;
}

function parseIssuedCredential(output) {
  const credential = output.match(/\bnpa_[A-Za-z0-9_-]{32,}\b/)?.[0];
  assert(credential, "CLI did not emit a one-time credential");
  remember(credential);
  return credential;
}

function findUv() {
  const candidates = [
    process.env.UV_BIN,
    "uv",
    path.join(os.homedir(), ".local", "bin", "uv"),
    "/opt/homebrew/bin/uv",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      execFileSync(candidate, ["--version"], { stdio: "ignore" });
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  throw new Error("uv is required");
}

function assertNoSkippedTests(output, label) {
  assert(!/\b(?:skipped|xfailed|xpassed)\b/i.test(output), `${label} reported a skipped test`);
}

async function filesUnder(directory) {
  const output = [];
  try {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) output.push(...await filesUnder(entryPath));
      else if (entry.isFile() && (await stat(entryPath)).size <= 10 * 1024 * 1024) output.push(entryPath);
    }
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return output;
}

function criterionKeys(number) {
  if (number <= 10) return ["public_boundary"];
  if (number <= 18) return ["webauthn_browser"];
  if (number <= 22) return ["admin_controls"];
  if (number <= 34) return ["reader_credentials"];
  if (number <= 46) return ["device_authorization"];
  if (number <= 55) return ["library_rbac"];
  if (number <= 59) return ["private_reader_state"];
  if (number <= 69) return ["migration_regression"];
  if (number <= 71) return ["backup_restore"];
  if (number <= 77) return ["security_audit"];
  if (number === 78) return ["server_quality"];
  if (number === 79) return ["web_quality"];
  if (number === 80) return ["webauthn_browser"];
  if (number === 81) return ["device_authorization"];
  if (number === 82) return ["private_reader_state"];
  if (number === 83) return ["persistence"];
  return ["report_sanitization"];
}

function criteriaReport() {
  return criterionLabels.map((label, index) => {
    const number = index + 1;
    const evidence = criterionKeys(number);
    const status = evidence.every((key) => results[key] === "PASS") ? "PASS" : "FAIL";
    return { number, label, status, evidence };
  });
}

async function writeReports(status, environment, gitCommit, failure) {
  await mkdir(artifacts, { recursive: true });
  const criteria = criteriaReport();
  const report = {
    version: acceptanceVersion,
    status,
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: gitCommit,
    environment,
    results,
    criteria,
    steps,
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await writeFile(jsonPath, `${redact(JSON.stringify(report, null, 2))}\n`, { mode: 0o600 });
  const markdown = [
    `# Novel Platform ${releaseLabel} acceptance`,
    "",
    `- Status: **${status}**`,
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${gitCommit}`,
    `- Compose project: ${environment.compose_project}`,
    `- Isolated ports: PostgreSQL ${environment.postgres_port}, API ${environment.server_port}, Web ${environment.web_port}`,
    `- Real Chromium contexts used for reader device flow: ${results.browser_contexts}`,
    `- Python unit tests: ${results.unit_tests}`,
    `- PostgreSQL integration tests: ${results.integration_tests}`,
    `- Web tests: ${results.web_tests}`,
    "",
    "## Result groups",
    "",
    ...Object.entries(results).filter(([, value]) => typeof value === "string").map(([key, value]) => `- ${key}: **${value}**`),
    "",
    "## 84 automatic acceptance criteria",
    "",
    "| # | Status | Criterion | Evidence group |",
    "| ---: | --- | --- | --- |",
    ...criteria.map((item) => `| ${item.number} | ${item.status} | ${item.label} | ${item.evidence.join(", ")} |`),
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map((item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail} |`),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required checks.",
    "",
    "Raw credentials, tokens, Cookie values, private content, database URLs, storage paths, and temporary paths are intentionally excluded.",
    "",
  ].join("\n");
  await writeFile(markdownPath, redact(markdown), { mode: 0o600 });
  await writeFile(
    actionLogPath,
    [
      `Novel Platform ${releaseLabel} sanitized acceptance action log`,
      "No command arguments, command output, credentials, tokens, Cookies, request bodies, or paths are recorded.",
      "",
      ...actions.map((label) => `[ACTION] ${label}`),
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
}

async function main() {
  await mkdir(artifacts, { recursive: true });
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), `novel-${acceptanceTag}-`));
  remember(temporaryRoot);
  const fixtureDirectory = path.join(temporaryRoot, "fixtures");
  const backupDirectory = path.join(temporaryRoot, "backups");
  const restoreReport = path.join(temporaryRoot, `restore-${acceptanceTag}.md`);
  const environmentFile = path.join(temporaryRoot, ".env.acceptance");
  await mkdir(fixtureDirectory, { recursive: true });
  const fixturePath = path.join(fixtureDirectory, "private-reading.txt");
  await writeFile(fixturePath, "第一章\n验收正文第一段\n\n验收正文第二段\n");

  const [postgresPort, serverPort, webPort] = await Promise.all([freePort(), freePort(), freePort()]);
  const postgresPassword = secret(24);
  const composeEnvironment = {
    ...process.env,
    COMPOSE_PROJECT_NAME: project,
    POSTGRES_PASSWORD: postgresPassword,
    POSTGRES_PORT: String(postgresPort),
    SERVER_PORT: String(serverPort),
    WEB_PORT: String(webPort),
    ENVIRONMENT: "development",
    CORS_ORIGINS: `["http://localhost:${webPort}"]`,
    TRUSTED_HOSTS: '["localhost","127.0.0.1","server","test","testserver"]',
    AUTH_JWT_SECRET: secret(),
    AUTH_HASH_SECRET: secret(),
    AUTH_CREDENTIAL_HASH_SECRET: secret(),
    AUTH_COOKIE_SECURE: "false",
    AUTH_COOKIE_SAMESITE: "lax",
    AUTH_COOKIE_NAME: "novel_refresh",
    AUTH_DEVICE_COOKIE_NAME: "novel_device",
    ADMIN_RECOVERY_TTL_MINUTES: "15",
    WEBAUTHN_RP_ID: "localhost",
    WEBAUTHN_ORIGINS: `["http://localhost:${webPort}"]`,
    WEBAUTHN_CHALLENGE_TTL_SECONDS: "300",
    OPENAPI_ENABLED: "false",
    TRUST_PROXY_HEADERS: "false",
    MAX_UPLOAD_BYTES: String(1024 * 1024),
    LINGUASPINDLE_ENABLED: "false",
    LINGUASPINDLE_BASE_URL: "http://linguaspindle:8765",
    LINGUASPINDLE_VERSION_RANGE: ">=0.3.1,<0.4.0",
    LINGUASPINDLE_PROVIDER_ID: "mock",
    LINGUASPINDLE_MAX_DOWNLOAD_BYTES: String(1024 * 1024),
  };
  const environment = {
    compose_project: project,
    postgres_port: postgresPort,
    server_port: serverPort,
    web_port: webPort,
    isolated_database_and_volumes: true,
  };
  const apiUrl = `http://localhost:${serverPort}`;
  const webUrl = `http://localhost:${webPort}`;
  const docker = (label, args) => run(label, "docker", ["compose", "-p", project, ...args], {
    env: composeEnvironment,
  });
  const psql = (label, sql) => docker(label, [
    "exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
    "-U", "novel_platform", "-d", "novel_platform", "-Atc", sql,
  ]);

  const gitCommit = run("read Git commit", "git", ["rev-parse", "HEAD"]).trim();
  let failure = null;
  let composeStarted = false;
  let browser = null;
  const browserResources = [];
  let adminPageState;
  let adminCdp;
  let adminToken;
  let readerPageState;
  let readerToken;
  let readerStates = [];
  let readerTokens = [];
  let readerCredential;
  let secondReaderCredential;
  let secondReaderToken;
  let readerId;
  let bookId;
  let editionId;
  let seriesId;
  let passkeyAuthenticator;

  try {
    await step("Start isolated Compose environment and migrate an empty database", async () => {
      run("check Docker", "docker", ["--version"]);
      run("check Docker Compose", "docker", ["compose", "version"]);
      composeStarted = true;
      docker(`build and start isolated ${releaseLabel} stack`, ["up", "--build", "--detach"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await waitFor(webUrl);
      const revision = psql("read Alembic revision", "SELECT version_num FROM alembic_version").trim();
      assert(revision === "20260715_0005", `unexpected migration revision ${revision}`);
      results.empty_database_migration = "PASS";
    });

    await step("Verify anonymous boundary, filing-friendly entry, legacy route removal, and noindex", async () => {
      const site = await apiRequest(apiUrl, "GET", "/api/v1/site");
      assert(site.body.icp_registration_number === null && site.body.icp_registration_url === null, "fake ICP data exists");
      assert(site.headers.get("x-robots-tag")?.includes("noindex"), "public API lacks noindex");
      for (const route of [
        "/api/v1/books",
        `/api/v1/books/${randomUUID()}`,
        `/api/v1/series/${randomUUID()}`,
        `/api/v1/editions/${randomUUID()}/reader/sections/first`,
        `/api/v1/editions/${randomUUID()}/reader/resources/image`,
        `/api/v1/editions/${randomUUID()}/file`,
      ]) {
        await apiRequest(apiUrl, "GET", route, { expected: 401 });
      }
      await apiRequest(apiUrl, "GET", "/api/v1/setup/status", { expected: 404 });
      await apiRequest(apiUrl, "POST", "/api/v1/setup/initialize", { body: {}, expected: 404 });
      await apiRequest(apiUrl, "POST", "/api/v1/auth/login", {
        body: { username: "admin", password: "legacy-password", device: loginPayload("x", "legacy").device },
        expected: 422,
      });
      await apiRequest(apiUrl, "GET", "/docs", { expected: 404 });
      await apiRequest(apiUrl, "GET", "/openapi.json", { expected: 404 });
      const html = await (await fetch(webUrl)).text();
      assert(html.includes('name="robots"'), "HTML robots meta missing");
      browser = await chromium.launch({ headless: process.env.HEADED !== "1" });
      const publicState = await newBrowserPage(browser);
      browserResources.push(publicState);
      await publicState.page.goto(`${webUrl}/login`);
      const robots = await publicState.page.locator('meta[name="robots"]').getAttribute("content");
      assert(robots?.split(",").map((item) => item.trim()).includes("noindex"), "HTML noindex meta missing");
      await publicState.page.getByText("个人非经营性站点", { exact: true }).waitFor();
      await publicState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      assert(await publicState.page.getByText(/ICP备|ICP证/).count() === 0, "empty ICP setting rendered a fake record");
      for (const forbidden of ["上传", "注册", "Setup Token", "创建用户", "管理后台"]) {
        assert(!(await publicState.page.locator("body").innerText()).includes(forbidden), `public page exposed ${forbidden}`);
      }
      assert(publicState.errors.length === 0, `public page errors: ${publicState.errors.join("; ")}`);
      results.public_boundary = "PASS";
    });

    await step("Initialize the administrator by CLI and complete recovery-only Passkey enrollment", async () => {
      const initOutput = docker("initialize administrator with one-time CLI credential", [
        "exec", "-T", "server", "novel-platform", "admin", "init", "--display-name", "验收管理员",
      ]);
      const initCredential = parseIssuedCredential(initOutput);
      const databaseText = psql(
        "verify initialization credential is not stored as plaintext",
        "SELECT token_hash FROM admin_recovery_credentials",
      );
      assert(!databaseText.includes(initCredential), "initialization credential was stored in plaintext");

      adminPageState = await newBrowserPage(browser);
      browserResources.push(adminPageState);
      adminCdp = await adminPageState.context.newCDPSession(adminPageState.page);
      await adminCdp.send("WebAuthn.enable");
      const firstAuthenticator = await addVirtualAuthenticator(adminCdp);
      const recovery = await credentialLoginPage(
        adminPageState.page, webUrl, initCredential, "管理员恢复浏览器",
      );
      assert(recovery.body.user.role === "admin" && recovery.body.session.recovery_mode, "CLI credential did not enter recovery mode");
      await adminPageState.page.getByRole("heading", { name: "Passkey 与管理员会话" }).waitFor();
      await apiRequest(apiUrl, "GET", "/api/v1/books", {
        token: recovery.body.access_token,
        expected: 403,
        errorCode: "recovery_session_restricted",
      });
      await apiRequest(apiUrl, "GET", "/api/v1/admin/readers", {
        token: recovery.body.access_token,
        expected: 403,
        errorCode: "recovery_session_restricted",
      });
      await directLogin(apiUrl, initCredential, "初始化凭证重放", {
        expected: 401,
        errorCode: "invalid_access_credential",
      });

      await adminPageState.page.getByLabel("名称").fill("验收 Passkey A");
      const firstVerify = adminPageState.page.waitForResponse(
        (response) => response.url().endsWith("/api/v1/auth/passkeys/registration/verify"),
      );
      await adminPageState.page.getByRole("button", { name: "开始登记" }).click();
      const firstResponse = await firstVerify;
      assert(firstResponse.status() === 200, "first Passkey registration failed");
      const firstBody = await firstResponse.json();
      assert(firstBody.authentication?.session.recovery_mode === false, "recovery session was not upgraded");
      adminToken = remember(firstBody.authentication.access_token);
      await adminPageState.page.getByText(/恢复会话已作废并升级/).waitFor();

      await adminCdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId: firstAuthenticator });
      passkeyAuthenticator = await addVirtualAuthenticator(adminCdp);
      await adminPageState.page.getByLabel("名称").fill("验收 Passkey B");
      const secondRequest = adminPageState.page.waitForRequest(
        (request) => request.url().endsWith("/api/v1/auth/passkeys/registration/verify"),
      );
      const secondResponsePromise = adminPageState.page.waitForResponse(
        (response) => response.url().endsWith("/api/v1/auth/passkeys/registration/verify"),
      );
      await adminPageState.page.getByRole("button", { name: "开始登记" }).click();
      const [registrationRequest, secondResponse] = await Promise.all([secondRequest, secondResponsePromise]);
      assert(secondResponse.status() === 200, "second Passkey registration failed");
      const registrationPayload = registrationRequest.postDataJSON();
      await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/registration/verify", {
        token: adminToken,
        headers: { Origin: webUrl },
        body: registrationPayload,
        expected: 401,
        errorCode: "invalid_webauthn_challenge",
      });
      const passkeys = await apiRequest(apiUrl, "GET", "/api/v1/auth/passkeys", { token: adminToken });
      assert(passkeys.body.filter((item) => !item.revoked_at).length === 2, "multiple Passkeys were not retained");

      await adminPageState.page.getByRole("button", { name: "退出" }).click();
      await adminPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const originPayload = await capturePasskeyLogin(adminPageState.page);
      await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/authentication/verify", {
        headers: { Origin: "http://untrusted.invalid" }, body: originPayload, expected: 403,
        errorCode: "permission_denied",
      });
      const originSuccess = await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/authentication/verify", {
        headers: { Origin: webUrl }, body: originPayload,
      });
      remember(originSuccess.body.access_token);
      await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/authentication/verify", {
        headers: { Origin: webUrl }, body: originPayload, expected: 401,
        errorCode: "invalid_webauthn_challenge",
      });

      const rpPayload = await capturePasskeyLogin(adminPageState.page);
      psql(
        "force RP mismatch for a captured WebAuthn challenge",
        `UPDATE webauthn_challenges SET rp_id = 'invalid.example' WHERE id = '${rpPayload.challenge_id}'`,
      );
      await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/authentication/verify", {
        headers: { Origin: webUrl }, body: rpPayload, expected: 401,
        errorCode: "invalid_webauthn_challenge",
      });

      const expiredPayload = await capturePasskeyLogin(adminPageState.page);
      psql(
        "expire a captured WebAuthn challenge",
        `UPDATE webauthn_challenges SET expires_at = now() - interval '1 second' WHERE id = '${expiredPayload.challenge_id}'`,
      );
      await apiRequest(apiUrl, "POST", "/api/v1/auth/passkeys/authentication/verify", {
        headers: { Origin: webUrl }, body: expiredPayload, expected: 401,
        errorCode: "invalid_webauthn_challenge",
      });

      const normalLogin = await passkeyLoginPage(adminPageState.page, webUrl);
      adminToken = remember(normalLogin.access_token);
      await adminPageState.page.waitForURL(new RegExp("/admin$"));
      await adminPageState.page.getByText("站点管理", { exact: true }).waitFor();
      const activePasskeys = (await apiRequest(apiUrl, "GET", "/api/v1/auth/passkeys", { token: adminToken })).body
        .filter((item) => !item.revoked_at);
      await apiRequest(apiUrl, "DELETE", `/api/v1/auth/passkeys/${activePasskeys[0].id}`, {
        token: adminToken, expected: 204,
      });
      await apiRequest(apiUrl, "DELETE", `/api/v1/auth/passkeys/${activePasskeys[1].id}`, {
        token: adminToken, expected: 409, errorCode: "cannot_revoke_last_passkey",
      });
      results.webauthn_browser = "PASS";
    });

    await step("Configure the private site, create readers with one-time credentials, and import shared content", async () => {
      await apiRequest(apiUrl, "PATCH", "/api/v1/admin/site", {
        token: adminToken,
        body: {
          site_name: "验收私人阅读站",
          purpose_statement: "仅供站点所有者和受邀阅读者整理与阅读私人藏书。",
          privacy_statement: "仅处理认证、设备安全和私人阅读状态所需的最少数据。",
          icp_registration_number: null,
          icp_registration_url: null,
          audit_retention_days: 90,
        },
      });
      await adminPageState.page.goto(`${webUrl}/admin/readers`);
      await adminPageState.page.getByRole("heading", {
        name: quietTraceProfile ? "阅读者" : "受邀阅读者",
        exact: true,
      }).waitFor();
      let createReaderScope = adminPageState.page;
      if (quietTraceProfile) {
        await adminPageState.page.getByRole("button", { name: "签发凭证" }).click();
        createReaderScope = adminPageState.page.getByRole("dialog", { name: "签发初始凭证" });
      }
      await createReaderScope.getByLabel("显示名称").first().fill("验收阅读者 A");
      await createReaderScope.getByLabel("管理员备注").first().fill("自动验收身份");
      await createReaderScope.getByLabel("设备上限").first().fill("3");
      const createResponsePromise = adminPageState.page.waitForResponse(
        (response) => response.url().endsWith("/api/v1/admin/readers") && response.request().method() === "POST",
      );
      await createReaderScope.getByRole("button", { name: "创建并显示凭证" }).click();
      const createResponse = await createResponsePromise;
      assert(createResponse.status() === 201, "reader UI create failed");
      assert(createResponse.headers()["cache-control"] === "no-store", "reader credential response is cacheable");
      const created = await createResponse.json();
      readerCredential = remember(created.access_credential);
      readerId = created.reader.id;
      const issuedCredentialScope = quietTraceProfile
        ? adminPageState.page.getByRole("dialog", { name: "保存访问凭证（仅显示一次）" })
        : adminPageState.page;
      assert((await issuedCredentialScope.locator("code").innerText()) === readerCredential, "one-time UI did not show credential");
      await issuedCredentialScope.getByRole("button", { name: "我已安全保存" }).click();
      const credentialRemainedVisible = quietTraceProfile
        ? await adminPageState.page.getByText(readerCredential, { exact: true }).count() > 0
        : await adminPageState.page.locator("code").count() > 0;
      assert(!credentialRemainedVisible, "credential remained visible after dismissal");
      const detail = await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}`, { token: adminToken });
      assert(!detail.raw.includes(readerCredential), "reader detail returned raw credential");

      const secondReader = await apiRequest(apiUrl, "POST", "/api/v1/admin/readers", {
        token: adminToken,
        expected: 201,
        body: {
          display_name: "验收阅读者 B",
          admin_note: "隔离验证",
          expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
          max_devices: 1,
          allow_new_devices: true,
        },
      });
      assert(secondReader.headers.get("cache-control") === "no-store", "second credential response is cacheable");
      secondReaderCredential = remember(secondReader.body.access_credential);
      const secondLogin = await directLogin(apiUrl, secondReaderCredential, "阅读者 B 设备");
      secondReaderToken = secondLogin.body.access_token;

      await adminPageState.page.goto(`${webUrl}/upload`);
      await adminPageState.page.getByRole("heading", { name: "上传与版本管理" }).waitFor();
      await adminPageState.page.getByLabel("选择 EPUB 或 TXT 文件").setInputFiles(fixturePath);
      await adminPageState.page.getByRole("button", { name: "上传并预览" }).click();
      await adminPageState.page.getByRole("heading", { name: "确认导入" }).waitFor();
      await adminPageState.page.getByLabel("书名").fill("验收共享藏书");
      await adminPageState.page.getByLabel("Edition 名称").fill("验收 TXT 版本");
      await adminPageState.page.getByLabel("语言").fill("zh-CN");
      const commitResponsePromise = adminPageState.page.waitForResponse(
        (response) => response.url().includes("/api/v1/imports/") && response.url().endsWith("/commit"),
      );
      await adminPageState.page.getByRole("button", { name: "确认导入" }).click();
      const commitResponse = await commitResponsePromise;
      assert(commitResponse.status() === 200, "browser import commit failed");
      const committed = await commitResponse.json();
      bookId = committed.book.id;
      editionId = committed.edition.id;
      await adminPageState.page.getByRole("heading", { name: "验收共享藏书" }).waitFor();

      const series = await apiRequest(apiUrl, "POST", "/api/v1/series", {
        token: adminToken,
        expected: 201,
        body: { name: "验收系列", description: "私人共享系列" },
      });
      seriesId = series.body.id;
      await apiRequest(apiUrl, "POST", `/api/v1/series/${seriesId}/books/${bookId}`, {
        token: adminToken,
      });
      const secondOpen = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, {
        token: secondLogin.body.access_token,
      });
      assert(secondOpen.body.progress.overall_progress === 0, "second reader did not start isolated");
    });

    await step("Authorize four independent browser contexts, enforce device limits, and reject spoofing", async () => {
      readerStates = [];
      const readerLogins = [];
      for (let index = 1; index <= 4; index += 1) {
        const state = await newBrowserPage(browser);
        browserResources.push(state);
        readerStates.push(state);
        const expected = index <= 3 ? 200 : 409;
        const loggedIn = await credentialLoginPage(
          state.page, webUrl, readerCredential, `阅读设备 ${index}`, expected,
        );
        readerLogins.push(loggedIn);
        if (index <= 3) {
          await waitForLibraryBook(state.page, "验收共享藏书");
        }
        else assert(loggedIn.body.error.code === "device_limit_reached", "fourth context failed for wrong reason");
      }
      results.browser_contexts = readerStates.length;
      readerTokens = readerLogins.map((login) => login.body?.access_token ?? null);
      readerPageState = readerStates[0];
      readerToken = readerTokens[0];

      for (const state of readerStates.slice(0, 3)) {
        await state.page.reload();
        await waitForLibraryBook(state.page, "验收共享藏书");
      }
      const knownClientId = await readerStates[0].page.evaluate(
        () => window.localStorage.getItem("novel_client_instance_id"),
      );
      const spoofState = await newBrowserPage(browser, { clientInstanceId: knownClientId });
      browserResources.push(spoofState);
      const spoofed = await credentialLoginPage(
        spoofState.page, webUrl, readerCredential, "伪造 client_instance_id", 409,
      );
      assert(spoofed.body.error.code === "device_limit_reached", "client instance spoof bypassed device secret");

      await readerStates[0].page.getByRole("button", { name: "退出" }).click();
      const repeated = await credentialLoginPage(
        readerStates[0].page, webUrl, readerCredential, "阅读设备 1",
      );
      readerToken = repeated.body.access_token;
      readerTokens[0] = readerToken;
      const devices = await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/devices`, {
        token: adminToken,
      });
      assert(devices.body.filter((item) => item.revoked_at === null).length === 3, "same device consumed a new slot");
      const third = devices.body.find((item) => item.name === "阅读设备 3");
      assert(third, "third reader device not found");
      await apiRequest(apiUrl, "POST", `/api/v1/admin/readers/${readerId}/devices/${third.id}/revoke`, {
        token: adminToken, expected: 204,
      });
      await apiRequest(apiUrl, "GET", "/api/v1/auth/me", {
        token: readerLogins[2].body.access_token, expected: 401,
      });
      const fourthAccepted = await credentialLoginPage(
        readerStates[3].page, webUrl, readerCredential, "阅读设备 4",
      );
      assert(fourthAccepted.body.user.id === readerId, "fourth device did not retain reader identity");
      readerTokens[3] = fourthAccepted.body.access_token;
      for (const state of readerStates) {
        assert(state.errors.length === 0, `reader browser errors: ${state.errors.join("; ")}`);
      }
      results.device_authorization = "PASS";
    });

    await step("Verify shared-library RBAC, reader projections, private progress, reload, settings, and conflict", async () => {
      const book = await apiRequest(apiUrl, "GET", `/api/v1/books/${bookId}`, { token: readerToken });
      assert(!/(owner_user_id|storage_key|sha256|\/data\/library)/.test(book.raw), "reader projection leaked storage or owner data");
      assert(book.body.editions[0].current_file.download_url === null, "reader received a raw download URL");
      for (const [method, route, body] of [
        ["GET", `/api/v1/editions/${editionId}/file`, undefined],
        ["POST", "/api/v1/books", { canonical_title: "越权" }],
        ["PATCH", `/api/v1/books/${bookId}`, { canonical_title: "越权" }],
        ["POST", "/api/v1/series", { name: "越权" }],
        ["GET", "/api/v1/admin/site", undefined],
        ["GET", "/api/v1/admin/readers", undefined],
        ["GET", "/api/v1/admin/audit", undefined],
        ["GET", "/api/v1/auth/passkeys", undefined],
      ]) {
        await apiRequest(apiUrl, method, route, { token: readerToken, body, expected: 403 });
      }
      const deniedForm = new FormData();
      deniedForm.set("operation", "create_book");
      deniedForm.set("text_encoding", "auto");
      deniedForm.set("file", new Blob(["denied"]), "denied.txt");
      await apiRequest(apiUrl, "POST", "/api/v1/imports/inspect", {
        token: readerToken, form: deniedForm, expected: 403,
      });

      await readerPageState.page.goto(`${webUrl}/series`);
      await readerPageState.page.getByText("验收系列", { exact: true }).waitFor();
      const navigationText = await readerPageState.page.getByRole("navigation", { name: "主导航" }).innerText();
      for (const forbidden of ["上传", "管理", "状态"]) assert(!navigationText.includes(forbidden), `reader nav exposed ${forbidden}`);
      await readerPageState.page.goto(`${webUrl}/books/${bookId}`);
      await readerPageState.page.getByRole("heading", { name: "验收共享藏书" }).waitFor();
      assert(await readerPageState.page.getByText("下载原始文件").count() === 0, "reader UI exposed raw download");

      const secondDevice = (await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/devices`, {
        token: adminToken,
      })).body.find((item) => item.name === "阅读设备 2");
      assert(secondDevice, "second device missing");
      const secondSession = (await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/audit`, {
        token: adminToken,
      })).body;
      assert(secondSession.some((event) => event.event_type === "device_limit_exceeded"), "device limit audit missing");

      const activeReaderSessions = await apiRequest(apiUrl, "GET", "/api/v1/auth/sessions", { token: readerToken });
      assert(activeReaderSessions.body.length >= 1, "reader session list is empty");
      const readerTwoLogin = await directLogin(apiUrl, readerCredential, "API 冲突设备", { expected: 409 });
      assert(readerTwoLogin.body.error.code === "device_limit_reached", "device limit was not enforced for API login");

      const devicesAfter = await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/devices`, { token: adminToken });
      const deviceTwoRecord = devicesAfter.body.find((item) => item.name === "阅读设备 2");
      assert(deviceTwoRecord, "reader device 2 unavailable for progress test");
      const sessions = await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/audit`, { token: adminToken });
      assert(Array.isArray(sessions.body), "reader audit unavailable");

      const openOne = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, { token: readerToken });
      const tokenTwo = readerTokens[1];
      assert(tokenTwo, "second browser access token is missing");
      remember(tokenTwo);
      const openTwo = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, { token: tokenTwo });
      const progressPayload = {
        expected_version: openOne.body.progress.version,
        section_id: openOne.body.publication.sections[0].id,
        block_id: null,
        section_progress: 0.45,
        overall_progress: 0.45,
        edition_file_revision: openOne.body.publication.file_revision,
        status: "reading",
      };
      const saved = await apiRequest(apiUrl, "PATCH", `/api/v1/editions/${editionId}/reader/progress`, {
        token: readerToken, body: progressPayload,
      });
      assert(saved.body.overall_progress === 0.45, "reader progress was not saved");
      await apiRequest(apiUrl, "PATCH", `/api/v1/editions/${editionId}/reader/progress`, {
        token: tokenTwo,
        body: { ...progressPayload, expected_version: openTwo.body.progress.version, overall_progress: 0.7 },
        expected: 409,
        errorCode: "reading_progress_conflict",
      });
      await apiRequest(apiUrl, "PATCH", "/api/v1/reader/settings", {
        token: readerToken, body: { font_size: 22, theme: "sepia" },
      });
      await apiRequest(apiUrl, "PATCH", `/api/v1/books/${bookId}/preferences`, {
        token: readerToken,
        body: { preferred_edition_id: editionId, last_opened_edition_id: editionId },
      });
      await readerPageState.page.goto(`${webUrl}/read/${editionId}`);
      await readerPageState.page.getByText("验收正文第一段", { exact: false }).waitFor();
      await readerPageState.page.getByLabel("阅读进度 45%").waitFor();
      await readerPageState.page.reload();
      await readerPageState.page.getByLabel("阅读进度 45%").waitFor();

      const readerB = (await apiRequest(apiUrl, "GET", "/api/v1/admin/readers", { token: adminToken })).body
        .find((item) => item.display_name === "验收阅读者 B");
      assert(readerB, "second reader identity missing");
      const readerBOpen = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, {
        token: secondReaderToken,
      });
      assert(readerBOpen.body.progress.overall_progress === 0, "reader B saw reader A progress");
      assert(readerBOpen.body.settings.font_size !== 22, "reader B saw reader A settings");
      const adminOpen = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, { token: adminToken });
      assert(adminOpen.body.progress.overall_progress === 0, "admin saw reader progress");
      results.library_rbac = "PASS";
      results.private_reader_state = "PASS";
    });

    await step("Exercise reader credential policy, suspension, expiry, revocation, and identity-preserving reissue", async () => {
      await apiRequest(apiUrl, "PATCH", `/api/v1/admin/readers/${readerId}`, {
        token: adminToken, body: { allow_new_devices: false },
      });
      await apiRequest(apiUrl, "POST", "/api/v1/auth/logout", {
        token: readerToken, expected: 204,
      });
      await readerPageState.context.clearCookies({ name: "novel_refresh" });
      await readerPageState.page.goto(`${webUrl}/login`);
      await readerPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const existing = await credentialLoginPage(readerPageState.page, webUrl, readerCredential, "阅读设备 1");
      readerToken = existing.body.access_token;
      const blockedState = await newBrowserPage(browser);
      browserResources.push(blockedState);
      const blocked = await credentialLoginPage(blockedState.page, webUrl, readerCredential, "未知设备", 401);
      assert(blocked.body.error.code === "invalid_access_credential", "allow_new_devices leaked policy details");
      await apiRequest(apiUrl, "PATCH", `/api/v1/admin/readers/${readerId}`, {
        token: adminToken, body: { allow_new_devices: true },
      });

      const deviceCountBefore = (await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/devices`, {
        token: adminToken,
      })).body.length;
      await apiRequest(apiUrl, "POST", `/api/v1/admin/readers/${readerId}/credential/suspend`, {
        token: adminToken, expected: 204,
      });
      await apiRequest(apiUrl, "GET", "/api/v1/auth/me", { token: readerToken, expected: 401 });
      await apiRequest(apiUrl, "POST", `/api/v1/admin/readers/${readerId}/credential/resume`, {
        token: adminToken, expected: 204,
      });
      await readerPageState.page.reload();
      await readerPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const resumed = await credentialLoginPage(readerPageState.page, webUrl, readerCredential, "阅读设备 1");
      readerToken = resumed.body.access_token;
      const deviceCountAfter = (await apiRequest(apiUrl, "GET", `/api/v1/admin/readers/${readerId}/devices`, {
        token: adminToken,
      })).body.length;
      assert(deviceCountAfter === deviceCountBefore, "resume created a duplicate device");

      await apiRequest(apiUrl, "PATCH", `/api/v1/admin/readers/${readerId}`, {
        token: adminToken, body: { expires_at: new Date(Date.now() - 1000).toISOString() },
      });
      await apiRequest(apiUrl, "GET", "/api/v1/auth/me", { token: readerToken, expected: 401 });
      await apiRequest(apiUrl, "PATCH", `/api/v1/admin/readers/${readerId}`, {
        token: adminToken, body: { expires_at: new Date(Date.now() + 20 * 86_400_000).toISOString() },
      });
      await readerPageState.page.reload();
      await readerPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const extended = await credentialLoginPage(readerPageState.page, webUrl, readerCredential, "阅读设备 1");
      readerToken = extended.body.access_token;

      await apiRequest(apiUrl, "POST", `/api/v1/admin/readers/${readerId}/credential/revoke`, {
        token: adminToken, expected: 204,
      });
      await directLogin(apiUrl, readerCredential, "已撤销凭证", {
        expected: 401, errorCode: "invalid_access_credential",
      });
      const reissued = await apiRequest(apiUrl, "POST", `/api/v1/admin/readers/${readerId}/credential/reissue`, {
        token: adminToken,
        body: {
          expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
          max_devices: 3,
          allow_new_devices: true,
        },
      });
      assert(reissued.headers.get("cache-control") === "no-store", "reissue response is cacheable");
      assert(reissued.body.reader.id === readerId, "reissue changed persistent reader identity");
      const replacementCredential = remember(reissued.body.access_credential);
      assert(replacementCredential !== readerCredential, "reissue returned the old credential");
      await directLogin(apiUrl, readerCredential, "旧凭证重放", {
        expected: 401, errorCode: "invalid_access_credential",
      });
      readerCredential = replacementCredential;
      await readerPageState.page.reload();
      await readerPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const replacementLogin = await credentialLoginPage(
        readerPageState.page, webUrl, readerCredential, "重签后的阅读设备",
      );
      readerToken = replacementLogin.body.access_token;
      const restoredState = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, {
        token: readerToken,
      });
      assert(restoredState.body.progress.overall_progress === 0.45, "reissue lost reader progress");
      assert(restoredState.body.settings.font_size === 22, "reissue lost reader settings");
      const preference = await apiRequest(apiUrl, "GET", `/api/v1/books/${bookId}/preferences`, { token: readerToken });
      assert(preference.body.preferred_edition_id === editionId, "reissue lost preferred Edition");
      results.reader_credentials = "PASS";
    });

    await step("Exercise administrator session revocation, emergency lock, credential reset, and recovery", async () => {
      docker("revoke all administrator sessions", [
        "exec", "-T", "server", "novel-platform", "admin", "sessions", "revoke-all",
      ]);
      await apiRequest(apiUrl, "GET", "/api/v1/admin/site", { token: adminToken, expected: 401 });
      await adminPageState.page.reload();
      await adminPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      const afterRevoke = await passkeyLoginPage(adminPageState.page, webUrl);
      adminToken = remember(afterRevoke.access_token);

      docker("lock administrator", ["exec", "-T", "server", "novel-platform", "admin", "lock"]);
      await apiRequest(apiUrl, "GET", "/api/v1/admin/site", { token: adminToken, expected: 401 });
      await adminPageState.page.reload();
      await adminPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      docker("unlock administrator", ["exec", "-T", "server", "novel-platform", "admin", "unlock"]);
      const afterUnlock = await passkeyLoginPage(adminPageState.page, webUrl);
      adminToken = remember(afterUnlock.access_token);

      const resetOutput = docker("reset administrator credentials", [
        "exec", "-T", "server", "novel-platform", "admin", "credentials", "reset",
      ]);
      const resetCredential = parseIssuedCredential(resetOutput);
      await adminPageState.page.reload();
      await adminPageState.page.getByRole("heading", { name: "登录", exact: true }).waitFor();
      await passkeyLoginPage(adminPageState.page, webUrl, 401);
      const recovery = await credentialLoginPage(
        adminPageState.page, webUrl, resetCredential, "管理员重设恢复浏览器",
      );
      assert(recovery.body.session.recovery_mode, "credential reset did not require recovery enrollment");
      await adminCdp.send("WebAuthn.enable");
      if (passkeyAuthenticator) {
        await adminCdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId: passkeyAuthenticator }).catch(() => undefined);
      }
      passkeyAuthenticator = await addVirtualAuthenticator(adminCdp);
      await adminPageState.page.getByLabel("名称").fill("验收恢复 Passkey C");
      const verify = adminPageState.page.waitForResponse(
        (response) => response.url().endsWith("/api/v1/auth/passkeys/registration/verify"),
      );
      await adminPageState.page.getByRole("button", { name: "开始登记" }).click();
      const response = await verify;
      assert(response.status() === 200, "recovery Passkey registration failed");
      const responseBody = await response.json();
      adminToken = remember(responseBody.authentication.access_token);
      const statusOutput = docker("read sanitized administrator status", [
        "exec", "-T", "server", "novel-platform", "admin", "status",
      ]);
      assert(!/\bnpa_[A-Za-z0-9_-]{32,}\b/.test(statusOutput), "admin status exposed a raw credential");
      docker("run audit retention cleanup", [
        "exec", "-T", "server", "novel-platform", "auth", "audit", "cleanup",
      ]);
      results.admin_controls = "PASS";
    });

    await step("Restart PostgreSQL, API, and Web and verify authentication and reading persistence", async () => {
      docker("restart PostgreSQL, API, and Web", ["restart", "postgres", "server", "web"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await waitFor(webUrl);
      await adminPageState.page.reload();
      await adminPageState.page.getByRole("heading", { name: "Passkey 与管理员会话" }).waitFor();
      await readerPageState.page.reload();
      await waitForLibraryBook(readerPageState.page, "验收共享藏书");
      const site = await apiRequest(apiUrl, "GET", "/api/v1/site");
      assert(site.body.site_name === "验收私人阅读站", "site settings did not persist");
      const progress = await apiRequest(apiUrl, "POST", `/api/v1/editions/${editionId}/reader/open`, {
        token: readerToken,
      });
      assert(progress.body.progress.overall_progress === 0.45, "reader progress did not persist");
      const passkeys = await apiRequest(apiUrl, "GET", "/api/v1/auth/passkeys", { token: adminToken });
      assert(passkeys.body.filter((item) => !item.revoked_at).length === 1, "recovery Passkey did not persist");
      results.persistence = "PASS";
    });

    if (quietTraceProfile && browser) {
      await step("Close completed browser contexts before isolated quality gates", async () => {
        await browser.close();
        browser = null;
      });
    }

    await step("Run migration preflight/integrity audit and complete backup plus isolated database/volume restore", async () => {
      const preflight = docker("run v0.5 authentication migration preflight", [
        "exec", "-T", "server", "novel-platform", "auth", "migration", "preflight",
      ]);
      const preflightBody = JSON.parse(preflight);
      assert(
        preflightBody.alembic_revision === "20260715_0005"
          && preflightBody.requires_target_admin === false
          && preflightBody.requires_admin_mapping === false,
        "migration preflight did not report the expected single-admin v0.5 state",
      );
      const integrity = docker("audit database and library volume references", [
        "exec", "-T", "server", "novel-platform", "auth", "migration", "audit",
      ]);
      assert(JSON.parse(integrity).consistent === true, "library integrity audit failed");

      const envLines = [
        `COMPOSE_PROJECT_NAME=${project}`,
        `PUBLIC_BASE_URL=http://localhost:${webPort}`,
        "POSTGRES_DB=novel_platform",
        "POSTGRES_USER=novel_platform",
        `POSTGRES_PASSWORD=${postgresPassword}`,
        "ENVIRONMENT=development",
        `CORS_ORIGINS='["http://localhost:${webPort}"]'`,
        "TRUSTED_HOSTS='[\"localhost\",\"127.0.0.1\",\"server\",\"test\",\"testserver\"]'",
        `AUTH_JWT_SECRET=${composeEnvironment.AUTH_JWT_SECRET}`,
        `AUTH_HASH_SECRET=${composeEnvironment.AUTH_HASH_SECRET}`,
        `AUTH_CREDENTIAL_HASH_SECRET=${composeEnvironment.AUTH_CREDENTIAL_HASH_SECRET}`,
        "AUTH_COOKIE_SECURE=false",
        "AUTH_COOKIE_SAMESITE=lax",
        "AUTH_COOKIE_NAME=novel_refresh",
        "AUTH_DEVICE_COOKIE_NAME=novel_device",
        "ADMIN_RECOVERY_TTL_MINUTES=15",
        "WEBAUTHN_RP_ID=localhost",
        `WEBAUTHN_ORIGINS='["http://localhost:${webPort}"]'`,
        "OPENAPI_ENABLED=false",
        "TRUST_PROXY_HEADERS=false",
        `POSTGRES_PORT=${postgresPort}`,
        `SERVER_PORT=${serverPort}`,
        `WEB_PORT=${webPort}`,
        `MAX_UPLOAD_BYTES=${1024 * 1024}`,
        "LINGUASPINDLE_ENABLED=false",
        "LINGUASPINDLE_BASE_URL=http://linguaspindle:8765",
        "LINGUASPINDLE_VERSION_RANGE='>=0.3.1,<0.4.0'",
        "LINGUASPINDLE_PROVIDER_ID=mock",
        `LINGUASPINDLE_MAX_DOWNLOAD_BYTES=${1024 * 1024}`,
      ];
      await writeFile(environmentFile, `${envLines.join("\n")}\n`);
      await chmod(environmentFile, 0o600);
      const operationsEnvironment = {
        ...process.env,
        NOVEL_ACCEPTANCE_LOCAL: "1",
        STAGING_ROOT: temporaryRoot,
        STAGING_ENV_FILE: environmentFile,
        STAGING_COMPOSE_FILE: path.join(root, "compose.yaml"),
      };
      const backupOutput = run(
        `create complete ${releaseLabel} database and library backup`,
        "bash", ["scripts/backup-library.sh", backupDirectory], { env: operationsEnvironment },
      );
      const backupPath = backupOutput.match(/^backup=(.+)$/m)?.[1];
      assert(backupPath, "backup script did not report an output directory");
      run(
        "restore backup into isolated database and isolated volume",
        "bash", ["scripts/restore-library.sh", "--test", backupPath, restoreReport],
        { env: operationsEnvironment },
      );
      const restoreText = await readFile(restoreReport, "utf8");
      assert(restoreText.includes("Status: **PASS**"), "isolated restore report failed");
      for (const label of [
        "Reader credentials present", "Administrator Passkeys present", "Device authorizations present",
        "Authentication sessions present", "Site settings rows present", "Security audit events present",
        "Stored files verified",
      ]) {
        const count = Number(restoreText.match(new RegExp(`- ${label}: (\\d+)`))?.[1] ?? 0);
        assert(count > 0, `${label} was not restored`);
      }
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      results.backup_restore = "PASS";
    });

    await step("Run Server, PostgreSQL integration, Web, OpenAPI, TypeScript, build, and script gates", async () => {
      const testDatabase = `novel_platform_test_${runId.replaceAll("-", "_")}`;
      docker("create isolated PostgreSQL integration test database", [
        "exec", "-T", "postgres", "createdb", "-U", "novel_platform", testDatabase,
      ]);
      const uv = findUv();
      const serverDirectory = path.join(root, "apps", "server");
      const testEnvironment = {
        ...process.env,
        TEST_DATABASE_URL: `postgresql+psycopg://novel_platform:${postgresPassword}@127.0.0.1:${postgresPort}/${testDatabase}`,
      };
      run("ruff check", uv, ["run", "ruff", "check", "."], { cwd: serverDirectory });
      run("ruff format check", uv, ["run", "ruff", "format", "--check", "."], { cwd: serverDirectory });
      run("mypy", uv, ["run", "mypy"], { cwd: serverDirectory });
      const unit = run("Python unit tests", uv, ["run", "pytest", "tests/unit", "-q"], { cwd: serverDirectory });
      const integration = run(
        "PostgreSQL integration tests", uv, ["run", "pytest", "tests/integration", "-q"],
        { cwd: serverDirectory, env: testEnvironment },
      );
      assertNoSkippedTests(unit, "Python unit tests");
      assertNoSkippedTests(integration, "PostgreSQL integration tests");
      results.unit_tests = Number(unit.match(/(\d+) passed/)?.[1] ?? 0);
      results.integration_tests = Number(integration.match(/(\d+) passed/)?.[1] ?? 0);
      assert(results.unit_tests > 0 && results.integration_tests > 0, "Python test counts were not captured");
      results.server_quality = "PASS";
      results.migration_regression = "PASS";

      run("Web ESLint", "pnpm", ["lint"]);
      const web = quietTraceProfile
        ? run("Web tests", "pnpm", [
            "--filter",
            "@novel-platform/web",
            "exec",
            "vitest",
            "run",
            "--maxWorkers=1",
            "--minWorkers=1",
            "--no-file-parallelism",
          ])
        : run("Web tests", "pnpm", ["test"]);
      assertNoSkippedTests(web, "Web tests");
      results.web_tests = Number(web.match(/Tests\s+(\d+) passed/)?.[1] ?? 0);
      assert(results.web_tests > 0, "Web test count was not captured");
      run("Web TypeScript and production build", "pnpm", ["build"]);
      const generatedPaths = [
        path.join(root, "packages", "api-client", "openapi.json"),
        path.join(root, "packages", "api-client", "src", "schema.d.ts"),
      ];
      const before = await Promise.all(generatedPaths.map((file) => readFile(file)));
      run("OpenAPI schema and TypeScript client generation", "pnpm", ["api:generate"]);
      const after = await Promise.all(generatedPaths.map((file) => readFile(file)));
      assert(before.every((content, index) => content.equals(after[index])), "generated OpenAPI client was stale");
      for (const script of (await filesUnder(path.join(root, "scripts"))).filter((file) => file.endsWith(".sh"))) {
        run(`bash syntax ${path.basename(script)}`, "bash", ["-n", script]);
      }
      run("Node syntax acceptance-v050", process.execPath, ["--check", "scripts/acceptance-v050.mjs"]);
      results.web_quality = "PASS";
      results.security_audit = "PASS";
    });

    await step("Scan logs, database dump, build, and report inputs for secrets, tokens, content, and storage paths", async () => {
      const logs = docker("read isolated Compose logs for leak scan", ["logs", "--no-color"]);
      const databaseDump = docker("read data-only database dump for plaintext credential scan", [
        "exec", "-T", "postgres", "pg_dump", "-U", "novel_platform", "-d", "novel_platform",
        "--data-only", "--inserts",
      ]);
      for (const value of sensitive) {
        assert(!logs.includes(value), "a secret appeared in container logs");
        assert(!databaseDump.includes(value), "a raw secret appeared in the database dump");
      }
      for (const source of [logs, databaseDump]) {
        assert(!/\bnpa_[A-Za-z0-9_-]{32,}\b/.test(source), "a raw access credential appeared in persisted output");
        assert(!/(Authorization\s*:\s*Bearer|novel_refresh=|novel_device=)/i.test(source), "an auth header or Cookie appeared in output");
      }
      assert(!logs.includes("/data/library"), "storage root appeared in logs");
      for (const content of protectedContents) assert(!logs.includes(content), "private content appeared in logs");
      for (const file of await filesUnder(path.join(root, "apps", "web", "dist"))) {
        const content = await readFile(file).catch(() => null);
        if (!content || content.includes(0)) continue;
        const text = content.toString("utf8");
        for (const value of sensitive) assert(!text.includes(value), "a secret appeared in the Web build");
        assert(!/\bnpa_[A-Za-z0-9_-]{32,}\b/.test(text), "a raw credential appeared in the Web build");
      }
      results.report_sanitization = "PASS";
    });

    await step("Confirm all 84 required criteria have passing evidence", async () => {
      const failed = criteriaReport().filter((criterion) => criterion.status !== "PASS");
      assert(failed.length === 0, `criteria without passing evidence: ${failed.map((item) => item.number).join(", ")}`);
      assert(results.browser_contexts >= 4, "fewer than four independent reader contexts were used");
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    for (const resource of browserResources.reverse()) {
      await resource.context.close().catch(() => undefined);
    }
    if (browser) await browser.close().catch(() => undefined);
    if (composeStarted && !keepEnvironment) {
      try {
        await step("Clean isolated containers, networks, and volumes", async () => {
          docker("remove isolated acceptance environment", ["down", "--volumes", "--remove-orphans"]);
        });
      } catch (cleanupError) {
        failure ??= cleanupError instanceof Error ? cleanupError : new Error(String(cleanupError));
      }
    }
    if (!keepEnvironment) await rm(temporaryRoot, { recursive: true, force: true });
    let status = failure ? "FAIL" : "PASS";
    await writeReports(status, environment, gitCommit, failure);
    const reportText = [markdownPath, jsonPath, actionLogPath]
      .map((file) => readFile(file, "utf8"));
    const combined = (await Promise.all(reportText)).join("\n");
    for (const value of sensitive) {
      if (combined.includes(value)) failure ??= new Error("a secret appeared in an acceptance report");
    }
    if (/\bnpa_[A-Za-z0-9_-]{32,}\b/.test(combined)) failure ??= new Error("a raw credential appeared in an acceptance report");
    if (failure && status !== "FAIL") {
      status = "FAIL";
      results.report_sanitization = "FAIL";
      await writeReports(status, environment, gitCommit, failure);
    }
    if (failure) {
      process.stderr.write(`${redact(failure.message)}\n`);
      process.exitCode = 1;
    } else {
      process.stdout.write(`${releaseLabel} acceptance passed: ${markdownPath}\n`);
    }
  }
}

await main();
