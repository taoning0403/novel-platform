import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

import { chromium } from "@playwright/test";

const root = process.cwd();
const artifactsDirectory = path.join(root, "artifacts");
const reportJsonPath = path.join(artifactsDirectory, "acceptance-v020.json");
const reportMarkdownPath = path.join(artifactsDirectory, "acceptance-v020.md");
const commandLogPath = path.join(artifactsDirectory, "acceptance-v020-command.log");
const startedAt = new Date();
const runId = startedAt.toISOString().replaceAll(/[:.]/g, "-").toLowerCase();
const projectName = `novel-platform-v020-${process.pid}-${Date.now()}`.toLowerCase();
const keepEnvironment = process.env.KEEP_ACCEPTANCE_ENV === "1";
const steps = [];
const commandLog = [];
const sensitiveValues = new Set();
const results = {
  unit_tests: 0,
  integration_tests: 0,
  web_tests: 0,
  playwright: "SKIPPED",
  migrations: "SKIPPED",
  persistence: "SKIPPED",
  leak_scan: "SKIPPED",
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function secret(bytes = 32) {
  const value = randomBytes(bytes).toString("base64url");
  sensitiveValues.add(value);
  return value;
}

function redact(value) {
  let text = String(value ?? "");
  for (const sensitive of sensitiveValues) {
    if (sensitive) text = text.replaceAll(sensitive, "[REDACTED]");
  }
  text = text.replaceAll(/Bearer\s+[A-Za-z0-9._~-]+/g, "Bearer [REDACTED]");
  text = text.replaceAll(/novel_refresh=[^;\s]+/g, "novel_refresh=[REDACTED]");
  return text;
}

function runCommand(label, executable, args, options = {}) {
  commandLog.push(`$ ${label}`);
  try {
    const output = execFileSync(executable, args, {
      cwd: options.cwd ?? root,
      env: options.env ?? process.env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 30 * 1024 * 1024,
    });
    commandLog.push(redact(output));
    return output;
  } catch (error) {
    commandLog.push(redact(error.stdout ?? ""));
    commandLog.push(redact(error.stderr ?? error.message));
    throw new Error(`${label} failed`);
  }
}

async function step(name, action) {
  const started = Date.now();
  try {
    const value = await action();
    steps.push({ name, status: "PASS", duration_ms: Date.now() - started });
    return value;
  } catch (error) {
    steps.push({
      name,
      status: "FAIL",
      duration_ms: Date.now() - started,
      detail: redact(error instanceof Error ? error.message : error),
    });
    throw error;
  }
}

async function freePort() {
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

async function waitFor(url, timeoutMs = 150_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Services can be between container and socket readiness.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`${url} did not become ready within ${timeoutMs}ms`);
}

async function request(baseUrl, method, route, options = {}) {
  const headers = new Headers(options.headers);
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  if (options.cookie) headers.set("Cookie", options.cookie);
  if (options.origin) headers.set("Origin", options.origin);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  const expected = options.expected ?? 200;
  assert(
    response.status === expected,
    `${method} ${route}: expected ${expected}, got ${response.status}: ${redact(JSON.stringify(body))}`,
  );
  if (options.errorCode) {
    assert(body?.error?.code === options.errorCode, `${route}: expected ${options.errorCode}`);
  }
  return { body, headers: response.headers, status: response.status };
}

function cookieFrom(headers) {
  const header = headers.get("set-cookie");
  assert(header?.includes("HttpOnly"), "refresh cookie must be HttpOnly");
  assert(header?.includes("Path=/api/v1/auth"), "refresh cookie path is incorrect");
  return header.split(";", 1)[0];
}

function addToken(token) {
  if (token) sensitiveValues.add(token);
  return token;
}

function findUv() {
  const candidates = [
    process.env.UV_BIN,
    "uv",
    path.join(os.homedir(), ".local", "bin", "uv"),
    path.join(os.homedir(), "Library", "Python", "3.9", "bin", "uv"),
    "/opt/homebrew/bin/uv",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate === "uv") {
      try {
        execFileSync("uv", ["--version"], { stdio: "ignore" });
        return "uv";
      } catch {
        continue;
      }
    }
    try {
      accessSync(candidate, constants.X_OK);
      return candidate;
    } catch {
      // Try the next conventional installation location.
    }
  }
  throw new Error("uv is required for server quality checks");
}

async function browserAcceptance(webUrl, setupToken, adminPassword, memberPassword) {
  const browser = await chromium.launch({ headless: process.env.HEADED !== "1" });
  const context = await browser.newContext();
  const page = await context.newPage();
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  try {
    async function logoutThroughHeader() {
      const response = page.waitForResponse(
        (candidate) =>
          candidate.url().endsWith("/api/v1/auth/logout") && candidate.status() === 204,
      );
      await page.getByRole("button", { name: "退出" }).click();
      await response;
      await page.getByRole("heading", { name: "登录" }).waitFor();
    }

    await page.goto(webUrl, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "创建第一个管理员" }).waitFor();
    await page.getByLabel("Setup Token").fill(setupToken);
    await page.getByLabel("管理员用户名").fill("admin");
    await page.getByLabel("显示名称").fill("验收管理员");
    await page.getByLabel("密码", { exact: true }).fill(adminPassword);
    await page.getByLabel("确认密码").fill(adminPassword);
    await page.getByRole("button", { name: "安全初始化" }).click();
    await page.getByRole("heading", { name: "登录" }).waitFor();
    await page.getByLabel("用户名").fill("admin");
    await page.getByLabel("密码").fill(adminPassword);
    await page.getByLabel("设备名称").fill("Playwright 管理端");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByRole("heading", { name: /整理你的书/ }).waitFor();

    const adminBookTitle = `浏览器管理员书籍 ${runId}`;
    await page.getByText("仅创建空 Book（兼容旧流程）").click();
    await page.getByLabel("书名", { exact: true }).fill(adminBookTitle);
    await page.getByRole("button", { name: "创建作品" }).click();
    const bookRow = page.locator("article.book-row", { hasText: adminBookTitle });
    await bookRow.getByRole("link", { name: /打开详情/ }).click();
    await page.getByRole("heading", { name: adminBookTitle }).waitFor();
    await page.getByText("仅添加无文件 Edition（兼容旧流程）").click();
    const adminBookPath = new URL(page.url()).pathname;

    async function createEdition(preset, title, language, sourceLabel) {
      await page.getByLabel(preset).check();
      await page.getByLabel("版本标题").fill(title);
      await page.getByLabel("语言").fill(language);
      if (sourceLabel) await page.getByLabel("关联原文（可选）").selectOption({ label: sourceLabel });
      await page.getByRole("button", { name: `创建${preset}` }).click();
      await page.getByRole("heading", { name: title }).waitFor();
    }

    await createEdition("原文", "浏览器原文", "ja");
    await createEdition("AI 译文", "浏览器 AI 译文", "zh-CN", "浏览器原文 · ja");
    await createEdition("人工译文", "浏览器人工译文", "zh-CN");
    const humanCard = page.locator("article.edition-card", {
      has: page.getByRole("heading", { name: "浏览器人工译文", exact: true }),
    });
    await humanCard.getByRole("button", { name: "设为首选" }).click();
    await humanCard.getByRole("button", { name: "当前首选" }).waitFor();
    await page.getByRole("heading", { name: "浏览器 AI 译文" }).waitFor();

    await page.getByRole("link", { name: "用户管理" }).click();
    const createPanel = page.locator("section.panel", { hasText: "创建用户" });
    await createPanel.getByLabel("用户名").fill("browser-member");
    await createPanel.getByLabel("显示名称").fill("浏览器成员");
    await createPanel.getByLabel("初始密码").fill(memberPassword);
    await createPanel.getByRole("button", { name: "创建用户" }).click();
    await page.getByText("browser-member", { exact: true }).waitFor();
    await logoutThroughHeader();

    await page.getByLabel("用户名").fill("browser-member");
    await page.getByLabel("密码").fill(memberPassword);
    await page.getByLabel("设备名称").fill("Playwright 成员端");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByText("书库还是空的").waitFor();
    await page.goto(`${webUrl}${adminBookPath}`);
    await page.getByRole("alert").waitFor();
    await page.goto(webUrl);
    await page.getByText("书库还是空的").waitFor();

    const memberBookTitle = `浏览器成员书籍 ${runId}`;
    await page.getByText("仅创建空 Book（兼容旧流程）").click();
    await page.getByLabel("书名", { exact: true }).fill(memberBookTitle);
    await page.getByRole("button", { name: "创建作品" }).click();
    await page.getByText(memberBookTitle, { exact: true }).waitFor();
    await page.getByRole("link", { name: "设备" }).click();
    const currentDevice = page.locator("article.management-row", { hasText: "当前设备" });
    await currentDevice.getByRole("textbox").fill("已重命名的浏览器设备");
    await currentDevice.getByRole("button", { name: "保存名称" }).click();
    await page.getByText("设备名称已更新。").waitFor();
    await page.getByRole("link", { name: "会话" }).click();
    await page.getByText("当前会话").waitFor();
    await logoutThroughHeader();
    await page.reload();
    await page.getByRole("heading", { name: "登录" }).waitFor();
    assert(browserErrors.length === 0, `browser page errors: ${browserErrors.join("; ")}`);
    return { adminBookTitle, memberBookTitle };
  } finally {
    await context.close();
    await browser.close();
  }
}

async function writeReports(overall, environment, failure) {
  await mkdir(artifactsDirectory, { recursive: true });
  const report = {
    version: "0.2.0",
    status: overall,
    started_at: startedAt.toISOString(),
    completed_at: new Date().toISOString(),
    environment,
    results,
    steps,
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await writeFile(reportJsonPath, `${JSON.stringify(report, null, 2)}\n`);
  const markdown = [
    "# Novel Platform v0.2.0 acceptance",
    "",
    `- Status: **${overall}**`,
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Compose project: ${environment.compose_project}`,
    `- Isolated ports: PostgreSQL ${environment.postgres_port}, API ${environment.server_port}, Web ${environment.web_port}`,
    `- Unit tests: ${results.unit_tests}`,
    `- PostgreSQL integration tests: ${results.integration_tests}`,
    `- Web tests: ${results.web_tests}`,
    `- Playwright: ${results.playwright}`,
    `- Persistence: ${results.persistence}`,
    `- Secret and token leak scan: ${results.leak_scan}`,
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map(
      (item) =>
        `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail ?? ""} |`,
    ),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required checks.",
    "",
  ].join("\n");
  await writeFile(reportMarkdownPath, markdown);
  await writeFile(commandLogPath, `${commandLog.map(redact).join("\n")}\n`);
}

async function main() {
  await mkdir(artifactsDirectory, { recursive: true });
  const [postgresPort, serverPort, webPort] = await Promise.all([
    freePort(),
    freePort(),
    freePort(),
  ]);
  const setupToken = secret();
  const jwtSecret = secret();
  const hashSecret = secret();
  const postgresPassword = secret(24);
  const adminPassword = secret(18);
  const memberPassword = secret(18);
  const resetPassword = secret(18);
  const environment = {
    compose_project: projectName,
    postgres_port: postgresPort,
    server_port: serverPort,
    web_port: webPort,
    keep_environment: keepEnvironment,
  };
  const composeEnvironment = {
    ...process.env,
    POSTGRES_PASSWORD: postgresPassword,
    POSTGRES_PORT: String(postgresPort),
    SERVER_PORT: String(serverPort),
    WEB_PORT: String(webPort),
    AUTH_SETUP_TOKEN: setupToken,
    AUTH_JWT_SECRET: jwtSecret,
    AUTH_HASH_SECRET: hashSecret,
    AUTH_COOKIE_SECURE: "false",
  };
  const apiUrl = `http://localhost:${serverPort}`;
  const webUrl = `http://localhost:${webPort}`;
  const docker = (label, args) =>
    runCommand(label, "docker", ["compose", "-p", projectName, ...args], {
      env: composeEnvironment,
    });
  let failure = null;
  let started = false;

  try {
    await step("Docker and Compose available", async () => {
      runCommand("docker --version", "docker", ["--version"]);
      runCommand("docker compose version", "docker", ["compose", "version"]);
    });
    await step("Start isolated Compose environment", async () => {
      started = true;
      docker("docker compose up --build --detach", ["up", "--build", "--detach"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await waitFor(webUrl);
    });
    await step("Setup status and invalid token", async () => {
      const status = await request(apiUrl, "GET", "/api/v1/setup/status");
      assert(status.body.setup_required === true, "fresh environment must require setup");
      await request(apiUrl, "POST", "/api/v1/setup/initialize", {
        body: {
          setup_token: "invalid-setup-token",
          username: "admin",
          display_name: "Admin",
          password: adminPassword,
        },
        expected: 401,
        errorCode: "invalid_setup_token",
      });
    });
    const browserState = await step("Playwright browser setup, login, isolation, and management", async () => {
      const value = await browserAcceptance(webUrl, setupToken, adminPassword, memberPassword);
      results.playwright = "PASS";
      return value;
    });
    await step("Initialization closes after first administrator", async () => {
      const status = await request(apiUrl, "GET", "/api/v1/setup/status");
      assert(status.body.setup_required === false, "setup must be closed");
      await request(apiUrl, "POST", "/api/v1/setup/initialize", {
        body: {
          setup_token: setupToken,
          username: "second-admin",
          display_name: "Second",
          password: adminPassword,
        },
        expected: 409,
        errorCode: "setup_not_required",
      });
    });

    let adminAccess;
    let adminRefresh;
    await step("Cookie/body login and refresh replay detection", async () => {
      const device = {
        client_instance_id: randomUUID(),
        name: "Acceptance API",
        platform: "web",
        app_version: "0.2.0",
      };
      const cookieLogin = await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "ADMIN",
          password: adminPassword,
          refresh_token_delivery: "cookie",
          device,
        },
      });
      assert(cookieLogin.body.refresh_token === undefined, "cookie login exposed refresh token");
      const originalCookie = cookieFrom(cookieLogin.headers);
      sensitiveValues.add(originalCookie.split("=", 2)[1]);
      const cookieRefresh = await request(apiUrl, "POST", "/api/v1/auth/refresh", {
        cookie: originalCookie,
        origin: webUrl,
      });
      addToken(cookieRefresh.body.access_token);
      const replacementCookie = cookieFrom(cookieRefresh.headers);
      assert(originalCookie !== replacementCookie, "cookie refresh token was not rotated");
      await request(apiUrl, "POST", "/api/v1/auth/refresh", {
        cookie: originalCookie,
        origin: webUrl,
        expected: 401,
        errorCode: "refresh_token_reused",
      });

      const bodyLogin = await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "admin",
          password: adminPassword,
          refresh_token_delivery: "body",
          device: { ...device, client_instance_id: randomUUID(), name: "Acceptance primary" },
        },
      });
      adminAccess = addToken(bodyLogin.body.access_token);
      adminRefresh = addToken(bodyLogin.body.refresh_token);
      assert(adminRefresh, "body login did not return a refresh token");
    });

    let member;
    let memberAccess;
    let memberBook;
    let adminBook;
    let humanEdition;
    await step("Users, private books, editions, and preferred edition", async () => {
      const created = await request(apiUrl, "POST", "/api/v1/users", {
        token: adminAccess,
        expected: 201,
        body: {
          username: "api-member",
          display_name: "API Member",
          password: memberPassword,
          role: "member",
        },
      });
      member = created.body;
      const memberLogin = await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "api-member",
          password: memberPassword,
          refresh_token_delivery: "body",
          device: {
            client_instance_id: randomUUID(),
            name: "Member API",
            platform: "web",
            app_version: "0.2.0",
          },
        },
      });
      memberAccess = addToken(memberLogin.body.access_token);
      adminBook = (
        await request(apiUrl, "POST", "/api/v1/books", {
          token: adminAccess,
          expected: 201,
          body: { canonical_title: `API admin book ${runId}` },
        })
      ).body;
      memberBook = (
        await request(apiUrl, "POST", "/api/v1/books", {
          token: memberAccess,
          expected: 201,
          body: { canonical_title: `API member book ${runId}` },
        })
      ).body;
      const memberBooks = await request(apiUrl, "GET", "/api/v1/books", {
        token: memberAccess,
      });
      assert(memberBooks.body.length === 1, "member library is not isolated");
      await request(apiUrl, "GET", `/api/v1/books/${adminBook.id}`, {
        token: memberAccess,
        expected: 404,
        errorCode: "book_not_found",
      });
      const edition = async (body) =>
        (
          await request(apiUrl, "POST", `/api/v1/books/${adminBook.id}/editions`, {
            token: adminAccess,
            expected: 201,
            body,
          })
        ).body;
      const source = await edition({
        title: "API source",
        language: "ja",
        content_role: "source",
        translation_origin: null,
        creation_method: "uploaded",
        status: "ready",
        revision: 1,
      });
      const aiEdition = await edition({
        title: "API AI translation",
        language: "zh-CN",
        content_role: "translation",
        translation_origin: "ai",
        creation_method: "generated",
        source_edition_id: source.id,
        status: "ready",
        revision: 1,
      });
      humanEdition = await edition({
        title: "API human translation",
        language: "zh-CN",
        content_role: "translation",
        translation_origin: "human",
        creation_method: "uploaded",
        status: "ready",
        revision: 1,
      });
      await request(apiUrl, "PATCH", `/api/v1/books/${adminBook.id}/preferences`, {
        token: adminAccess,
        body: { preferred_edition_id: humanEdition.id },
      });
      const detail = await request(apiUrl, "GET", `/api/v1/books/${adminBook.id}`, {
        token: adminAccess,
      });
      assert(detail.body.editions.some((item) => item.id === aiEdition.id), "AI edition was lost");
      assert(
        detail.body.editions.some((item) => item.id === humanEdition.id),
        "human edition was lost",
      );
      assert(browserState.adminBookTitle && browserState.memberBookTitle, "browser books missing");
    });

    let durableAdminAccess;
    let durableMemberAccess;
    await step("Devices, sessions, disable/enable, and password reset", async () => {
      const devices = await request(apiUrl, "GET", "/api/v1/devices", { token: adminAccess });
      assert(devices.body.length >= 1, "admin devices missing");
      await request(apiUrl, "PATCH", `/api/v1/devices/${devices.body[0].id}`, {
        token: adminAccess,
        body: { name: "Renamed API device" },
      });
      const sessions = await request(apiUrl, "GET", "/api/v1/auth/sessions", {
        token: adminAccess,
      });
      assert(sessions.body.some((item) => item.is_current), "current session not identified");
      const secondLogin = await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "admin",
          password: adminPassword,
          refresh_token_delivery: "body",
          device: {
            client_instance_id: randomUUID(),
            name: "Durable admin session",
            platform: "web",
            app_version: "0.2.0",
          },
        },
      });
      durableAdminAccess = addToken(secondLogin.body.access_token);
      await request(apiUrl, "POST", "/api/v1/auth/sessions/revoke-others", {
        token: durableAdminAccess,
      });
      await request(apiUrl, "GET", "/api/v1/auth/me", {
        token: adminAccess,
        expected: 401,
        errorCode: "session_revoked",
      });
      await request(apiUrl, "PATCH", `/api/v1/users/${member.id}`, {
        token: durableAdminAccess,
        body: { status: "disabled" },
      });
      await request(apiUrl, "GET", "/api/v1/auth/me", {
        token: memberAccess,
        expected: 401,
        errorCode: "user_disabled",
      });
      await request(apiUrl, "PATCH", `/api/v1/users/${member.id}`, {
        token: durableAdminAccess,
        body: { status: "active" },
      });
      await request(apiUrl, "POST", `/api/v1/users/${member.id}/reset-password`, {
        token: durableAdminAccess,
        expected: 204,
        body: { new_password: resetPassword },
      });
      await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "api-member",
          password: memberPassword,
          refresh_token_delivery: "body",
          device: {
            client_instance_id: randomUUID(),
            name: "Old password",
            platform: "web",
          },
        },
        expected: 401,
        errorCode: "invalid_credentials",
      });
      const newLogin = await request(apiUrl, "POST", "/api/v1/auth/login", {
        body: {
          username: "api-member",
          password: resetPassword,
          refresh_token_delivery: "body",
          device: {
            client_instance_id: randomUUID(),
            name: "New password",
            platform: "web",
          },
        },
      });
      durableMemberAccess = addToken(newLogin.body.access_token);
    });

    await step("Container restart persistence", async () => {
      docker("docker compose restart server", ["restart", "server"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await request(apiUrl, "GET", "/api/v1/auth/me", { token: durableAdminAccess });
      const preference = await request(
        apiUrl,
        "GET",
        `/api/v1/books/${adminBook.id}/preferences`,
        { token: durableAdminAccess },
      );
      assert(preference.body.preferred_edition_id === humanEdition.id, "preference was not durable");
      const users = await request(apiUrl, "GET", "/api/v1/users", {
        token: durableAdminAccess,
      });
      assert(users.body.some((item) => item.id === member.id), "user was not durable");
      const books = await request(apiUrl, "GET", "/api/v1/books", {
        token: durableAdminAccess,
      });
      assert(books.body.some((item) => item.id === adminBook.id), "book was not durable");
      const memberBooks = await request(apiUrl, "GET", "/api/v1/books", {
        token: durableMemberAccess,
      });
      assert(
        memberBooks.body.some((item) => item.id === memberBook.id),
        "member book was not durable",
      );
      results.persistence = "PASS";
    });

    await step("Alembic, server, and PostgreSQL test gates", async () => {
      docker("create isolated test database", [
        "exec",
        "-T",
        "postgres",
        "createdb",
        "-U",
        "novel_platform",
        "novel_platform_test",
      ]);
      const uv = findUv();
      const serverDirectory = path.join(root, "apps", "server");
      const testEnvironment = {
        ...process.env,
        TEST_DATABASE_URL: `postgresql+psycopg://novel_platform:${postgresPassword}@127.0.0.1:${postgresPort}/novel_platform_test`,
      };
      runCommand("ruff check", uv, ["run", "ruff", "check", "."], { cwd: serverDirectory });
      runCommand("ruff format --check", uv, ["run", "ruff", "format", "--check", "."], {
        cwd: serverDirectory,
      });
      runCommand("mypy", uv, ["run", "mypy"], { cwd: serverDirectory });
      const unitOutput = runCommand(
        "server unit tests",
        uv,
        ["run", "pytest", "tests/unit", "-q"],
        { cwd: serverDirectory },
      );
      const integrationOutput = runCommand(
        "server PostgreSQL integration tests",
        uv,
        ["run", "pytest", "tests/integration", "-q"],
        { cwd: serverDirectory, env: testEnvironment },
      );
      results.unit_tests = Number(unitOutput.match(/(\d+) passed/)?.[1] ?? 0);
      results.integration_tests = Number(integrationOutput.match(/(\d+) passed/)?.[1] ?? 0);
      assert(results.unit_tests > 0 && results.integration_tests > 0, "test counts missing");
      results.migrations = "PASS";
    });

    await step("Web lint, tests, generated API, and production build", async () => {
      runCommand("web ESLint", "pnpm", ["lint"]);
      const webOutput = runCommand("web tests", "pnpm", ["test"]);
      results.web_tests = Number(webOutput.match(/Tests\s+(\d+) passed/)?.[1] ?? 0);
      runCommand("web TypeScript and Vite build", "pnpm", ["build"]);
      const schemaPath = path.join(root, "packages", "api-client", "src", "schema.d.ts");
      const before = await readFile(schemaPath, "utf8");
      const uv = findUv();
      const apiEnvironment = {
        ...process.env,
        PATH: `${path.dirname(uv)}:${process.env.PATH ?? ""}`,
      };
      runCommand("OpenAPI client generation", "pnpm", ["api:generate"], {
        env: apiEnvironment,
      });
      const after = await readFile(schemaPath, "utf8");
      assert(before === after, "generated OpenAPI client was stale");
      assert(results.web_tests > 0, "web test count missing");
    });

    await step("Secret, token, cookie, and report leak scan", async () => {
      const containerLogs = docker("docker compose logs", ["logs", "--no-color"]);
      for (const sensitive of sensitiveValues) {
        assert(!containerLogs.includes(sensitive), "sensitive value appeared in container logs");
      }
      const invalidHashCount = docker("validate refresh token hashes", [
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "novel_platform",
        "-d",
        "novel_platform",
        "-Atc",
        "SELECT count(*) FROM refresh_tokens WHERE token_hash !~ '^[0-9a-f]{64}$'",
      ]).trim();
      assert(invalidHashCount === "0", "refresh token table contains a non-HMAC value");
      results.leak_scan = "PASS";
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (started && !keepEnvironment) {
      try {
        await step("Cleanup isolated containers and volumes", async () => {
          runCommand(
            "docker compose down --volumes",
            "docker",
            ["compose", "-p", projectName, "down", "--volumes", "--remove-orphans"],
            { env: composeEnvironment },
          );
        });
      } catch (cleanupError) {
        failure ??= cleanupError instanceof Error ? cleanupError : new Error(String(cleanupError));
      }
    } else if (keepEnvironment) {
      steps.push({
        name: "Cleanup isolated containers and volumes",
        status: "SKIPPED",
        duration_ms: 0,
        detail: "KEEP_ACCEPTANCE_ENV=1",
      });
    }
    const overall = failure ? "FAIL" : "PASS";
    await writeReports(overall, environment, failure);
    for (const sensitive of sensitiveValues) {
      const reportText = `${await readFile(reportJsonPath, "utf8")}${await readFile(
        reportMarkdownPath,
        "utf8",
      )}${await readFile(commandLogPath, "utf8")}`;
      if (reportText.includes(sensitive)) {
        failure ??= new Error("sensitive value appeared in acceptance artifacts");
      }
    }
    if (failure) {
      process.stderr.write(`${redact(failure.message)}\n`);
      process.exitCode = 1;
    } else {
      process.stdout.write(`v0.2.0 acceptance passed: ${reportMarkdownPath}\n`);
    }
  }
}

await main();
