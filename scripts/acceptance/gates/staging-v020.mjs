import { randomBytes, randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const verifyPersistenceOnly = process.argv.includes("--verify-persistence");
const baseUrl = (process.env.STAGING_BASE_URL ?? process.env.PUBLIC_BASE_URL ?? "").replace(/\/$/, "");
const adminLogin = process.env.STAGING_ADMIN_USERNAME ?? process.env.STAGING_ADMIN_EMAIL ?? "";
const adminPassword = process.env.STAGING_ADMIN_PASSWORD ?? "";
const setupToken = process.env.STAGING_SETUP_TOKEN ?? process.env.AUTH_SETUP_TOKEN ?? "";
const expectedSecureCookie = process.env.STAGING_EXPECT_SECURE_COOKIE === "true";
const expectedCookieDomain = process.env.AUTH_COOKIE_DOMAIN ?? "";
const cookieName = process.env.AUTH_COOKIE_NAME ?? "novel_refresh";
const reportDirectory = path.resolve(process.env.STAGING_REPORT_DIR ?? "artifacts");
const reportJsonPath = path.join(reportDirectory, "staging-acceptance-v020.json");
const reportMarkdownPath = path.join(reportDirectory, "staging-acceptance-v020.md");
const stateFile = path.resolve(
  process.env.STAGING_STATE_FILE ?? path.join(reportDirectory, ".staging-acceptance-state.json"),
);
const startedAt = new Date();
const runId = `stg-v020-${Date.now().toString(36)}-${randomBytes(3).toString("hex")}`;
const steps = [];
const sensitiveValues = new Set();
const retainedTestData = [];
const results = {
  api: "SKIPPED",
  playwright: "SKIPPED",
  cookies: "SKIPPED",
  refresh_replay: "SKIPPED",
  isolation: "SKIPPED",
  devices_sessions: "SKIPPED",
  persistence_state: "SKIPPED",
  https: expectedSecureCookie ? "PASS" : "PENDING",
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function requireValue(name, value) {
  assert(value, `${name} is required`);
}

function secret(bytes = 24) {
  const value = randomBytes(bytes).toString("base64url");
  sensitiveValues.add(value);
  return value;
}

function rememberSecret(value) {
  if (value) sensitiveValues.add(value);
  return value;
}

function redact(value) {
  let text = String(value ?? "");
  for (const sensitive of sensitiveValues) {
    if (sensitive) text = text.replaceAll(sensitive, "[REDACTED]");
  }
  text = text.replaceAll(/Bearer\s+[A-Za-z0-9._~-]+/g, "Bearer [REDACTED]");
  text = text.replaceAll(new RegExp(`${cookieName}=[^;\\s]+`, "g"), `${cookieName}=[REDACTED]`);
  text = text.replaceAll(/postgresql(?:\+psycopg)?:\/\/([^:\s]+):([^@\s]+)@/g, "postgresql://$1:[REDACTED]@");
  text = text.replaceAll(/\u001b\[[0-9;]*m/g, "");
  return text;
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

async function request(method, route, options = {}) {
  const headers = new Headers(options.headers);
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  if (options.cookie) headers.set("Cookie", options.cookie);
  if (options.origin) headers.set("Origin", options.origin);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    redirect: "manual",
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  const expected = Array.isArray(options.expected)
    ? options.expected
    : [options.expected ?? 200];
  assert(
    expected.includes(response.status),
    `${method} ${route}: expected ${expected.join("/")}, got ${response.status}: ${redact(JSON.stringify(body))}`,
  );
  if (options.errorCode) {
    assert(body?.error?.code === options.errorCode, `${route}: expected ${options.errorCode}`);
  }
  return { body, headers: response.headers, status: response.status };
}

function cookiePair(headers) {
  const raw = headers.get("set-cookie");
  assert(raw, "response did not set a refresh cookie");
  const pair = raw.split(";", 1)[0];
  const value = pair.slice(pair.indexOf("=") + 1);
  rememberSecret(value);
  return { pair, raw };
}

function assertCookieAttributes(raw, { clearing = false } = {}) {
  const lower = raw.toLowerCase();
  assert(lower.includes("httponly"), "refresh cookie must be HttpOnly");
  assert(lower.includes("path=/api/v1/auth"), "refresh cookie Path is incorrect");
  assert(lower.includes("samesite=lax"), "refresh cookie SameSite must be Lax");
  assert(lower.includes("secure") === expectedSecureCookie, "refresh cookie Secure flag mismatch");
  if (expectedCookieDomain) {
    assert(lower.includes(`domain=${expectedCookieDomain.toLowerCase()}`), "cookie Domain mismatch");
  } else {
    assert(!lower.includes("domain="), "refresh cookie must be host-only when Domain is empty");
  }
  if (clearing) assert(lower.includes("max-age=0"), "logout did not expire the refresh cookie");
}

function device(name) {
  return {
    client_instance_id: randomUUID(),
    name,
    platform: "web",
    app_version: "0.2.0",
  };
}

async function loginBody(username, password, name) {
  const response = await request("POST", "/api/v1/auth/login", {
    body: {
      username,
      password,
      refresh_token_delivery: "body",
      device: device(name),
    },
  });
  rememberSecret(response.body.access_token);
  rememberSecret(response.body.refresh_token);
  return response.body;
}

async function loginCookie(username, password, name) {
  const response = await request("POST", "/api/v1/auth/login", {
    body: {
      username,
      password,
      refresh_token_delivery: "cookie",
      device: device(name),
    },
  });
  assert(response.body.refresh_token === undefined, "cookie login exposed a refresh token");
  rememberSecret(response.body.access_token);
  return { body: response.body, cookie: cookiePair(response.headers) };
}

async function createUser(adminToken, username, displayName, password) {
  return (
    await request("POST", "/api/v1/users", {
      token: adminToken,
      expected: 201,
      body: { username, display_name: displayName, password, role: "member" },
    })
  ).body;
}

async function createBook(token, title) {
  return (
    await request("POST", "/api/v1/books", {
      token,
      expected: 201,
      body: { canonical_title: title, canonical_author: "Staging Acceptance" },
    })
  ).body;
}

async function createEdition(token, bookId, body) {
  return (
    await request("POST", `/api/v1/books/${bookId}/editions`, {
      token,
      expected: 201,
      body: {
        status: "ready",
        revision: 1,
        ...body,
      },
    })
  ).body;
}

async function verifyPersistenceState() {
  requireValue("STAGING_BASE_URL or PUBLIC_BASE_URL", baseUrl);
  const state = JSON.parse(await readFile(stateFile, "utf8"));
  rememberSecret(state.password);
  const loggedIn = await loginBody(state.username, state.password, "Persistence verifier");
  const detail = await request("GET", `/api/v1/books/${state.book_id}`, {
    token: loggedIn.access_token,
  });
  const present = new Set(detail.body.editions.map((edition) => edition.id));
  for (const editionId of state.edition_ids) {
    assert(present.has(editionId), `persisted edition is missing: ${editionId}`);
  }
  const preference = await request("GET", `/api/v1/books/${state.book_id}/preferences`, {
    token: loggedIn.access_token,
  });
  assert(
    preference.body.preferred_edition_id === state.preferred_edition_id,
    "persisted preferred Edition changed",
  );
  process.stdout.write("staging persistence state PASS\n");
}

async function browserAcceptance({
  browserUser,
  browserPassword,
  browserApiToken,
  memberB,
  memberBPassword,
  adminToken,
}) {
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch({ headless: process.env.HEADED !== "1" });
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const adminContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const problems = [];

  function watch(page, label) {
    page.on("pageerror", (error) => problems.push(`${label} pageerror: ${error.message}`));
    page.on("console", (message) => {
      const text = message.text();
      const expectedNegativeRequest = /Failed to load resource:.*status of (401|404)/.test(text);
      if (message.type() === "error" && !expectedNegativeRequest) {
        problems.push(`${label} console: ${text}`);
      }
    });
    page.on("requestfailed", (request_) => {
      const errorText = request_.failure()?.errorText ?? "unknown";
      if (errorText !== "net::ERR_ABORTED") {
        problems.push(
          `${label} requestfailed: ${request_.method()} ${new URL(request_.url()).pathname} (${errorText})`,
        );
      }
    });
    page.on("response", (response) => {
      const pathname = new URL(response.url()).pathname;
      const status = response.status();
      const expectedNegativeRequest =
        (status === 401 && ["/api/v1/auth/refresh", "/api/v1/auth/login"].includes(pathname)) ||
        (status === 404 && pathname.startsWith("/api/v1/books/"));
      if (status >= 400 && !expectedNegativeRequest) {
        problems.push(`${label} HTTP ${status}: ${pathname}`);
      }
    });
  }

  async function loginThroughUi(page, username, password, deviceName) {
    await page.getByLabel("用户名").fill(username);
    await page.getByLabel("密码").fill(password);
    await page.getByLabel("设备名称").fill(deviceName);
    const loginResponse = page.waitForResponse(
      (candidate) => candidate.url().endsWith("/api/v1/auth/login") && candidate.status() === 200,
    );
    await page.getByRole("button", { name: "登录书库" }).click();
    const response = await loginResponse;
    const payload = await response.json();
    rememberSecret(payload.access_token);
    await page.getByRole("link", { name: "书库" }).waitFor();
    return payload;
  }

  try {
    const desktopPage = await desktop.newPage();
    watch(desktopPage, "desktop");
    await desktopPage.route(
      "**/api/v1/setup/status",
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 350));
        await route.continue();
      },
      { times: 1 },
    );
    const initialNavigation = desktopPage.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await desktopPage.getByRole("status").waitFor({ timeout: 3_000 });
    await initialNavigation;
    await desktopPage.getByRole("heading", { name: "登录" }).waitFor();

    await desktopPage.getByLabel("用户名").fill(browserUser.username);
    await desktopPage.getByLabel("密码").fill("deliberately-wrong-password");
    await desktopPage.getByLabel("设备名称").fill("Staging rejected-login browser");
    const rejectedLogin = desktopPage.waitForResponse(
      (candidate) => candidate.url().endsWith("/api/v1/auth/login") && candidate.status() === 401,
    );
    await desktopPage.getByRole("button", { name: "登录书库" }).click();
    await rejectedLogin;
    await desktopPage.getByRole("alert").waitFor();

    const firstDesktopLogin = await loginThroughUi(
      desktopPage,
      browserUser.username,
      browserPassword,
      "Staging desktop browser",
    );
    await desktopPage.getByText("书库还是空的").waitFor();
    await desktopPage.reload({ waitUntil: "networkidle" });
    await desktopPage.getByRole("heading", { name: /把每一种文本版本/ }).waitFor();

    const browserBookTitle = `${runId}-browser-book`;
    await desktopPage.getByLabel("书名").fill(browserBookTitle);
    await desktopPage.getByRole("button", { name: "创建作品" }).click();
    const browserBookRow = desktopPage.locator("article.book-row", { hasText: browserBookTitle });
    await browserBookRow.getByRole("link", { name: /打开详情/ }).click();
    await desktopPage.getByRole("heading", { name: browserBookTitle }).waitFor();
    const browserBookPath = new URL(desktopPage.url()).pathname;
    await desktopPage.getByLabel("原文").check();
    await desktopPage.getByLabel("版本标题").fill(`${runId}-browser-source`);
    await desktopPage.getByLabel("语言").fill("ja");
    await desktopPage.getByRole("button", { name: "创建原文" }).click();
    await desktopPage.getByRole("heading", { name: `${runId}-browser-source` }).waitFor();

    await desktopPage.getByRole("link", { name: "设备" }).click();
    await desktopPage.getByText("当前设备").waitFor();
    await desktopPage.getByRole("link", { name: "会话" }).click();
    await desktopPage.getByText("当前会话").waitFor();

    const mobilePage = await mobile.newPage();
    watch(mobilePage, "mobile");
    await mobilePage.goto(baseUrl, { waitUntil: "networkidle" });
    await mobilePage.getByRole("heading", { name: "登录" }).waitFor();
    const mobileLogin = await loginThroughUi(
      mobilePage,
      memberB.username,
      memberBPassword,
      "Staging mobile browser",
    );
    assert(firstDesktopLogin.user.id !== mobileLogin.user.id, "browser contexts share an identity");
    const desktopCookies = await desktop.cookies();
    const mobileCookies = await mobile.cookies();
    const desktopRefresh = desktopCookies.find((cookie) => cookie.name === cookieName);
    const mobileRefresh = mobileCookies.find((cookie) => cookie.name === cookieName);
    assert(desktopRefresh && mobileRefresh, "browser refresh cookies are missing");
    rememberSecret(desktopRefresh.value);
    rememberSecret(mobileRefresh.value);
    assert(desktopRefresh.value !== mobileRefresh.value, "browser contexts share a refresh cookie");
    for (const cookie of [desktopRefresh, mobileRefresh]) {
      assert(cookie.httpOnly, "browser refresh cookie is not HttpOnly");
      assert(cookie.secure === expectedSecureCookie, "browser Secure cookie flag mismatch");
      assert(cookie.sameSite === "Lax", "browser SameSite cookie flag mismatch");
      assert(cookie.path === "/api/v1/auth", "browser cookie Path mismatch");
      if (!expectedCookieDomain) assert(!cookie.domain.startsWith("."), "browser cookie is not host-only");
    }
    await mobilePage.goto(`${baseUrl}${browserBookPath}`, { waitUntil: "networkidle" });
    await mobilePage.getByRole("alert").waitFor();
    await mobilePage.goto(`${baseUrl}/admin/users`, { waitUntil: "networkidle" });
    assert(new URL(mobilePage.url()).pathname === "/", "member reached the administrator page");

    const adminPage = await adminContext.newPage();
    watch(adminPage, "admin");
    await adminPage.goto(baseUrl, { waitUntil: "networkidle" });
    await loginThroughUi(adminPage, adminLogin, adminPassword, "Staging admin browser");
    await adminPage.getByRole("link", { name: "用户管理" }).click();
    await adminPage.getByRole("heading", { name: "用户管理" }).waitFor();
    await adminPage.getByText(browserUser.username, { exact: true }).waitFor();

    const logoutResponse = desktopPage.waitForResponse(
      (candidate) => candidate.url().endsWith("/api/v1/auth/logout") && candidate.status() === 204,
    );
    await desktopPage.getByRole("button", { name: "退出" }).click();
    await logoutResponse;
    await desktopPage.getByRole("heading", { name: "登录" }).waitFor();
    const expiringLogin = await loginThroughUi(
      desktopPage,
      browserUser.username,
      browserPassword,
      "Staging expiring browser",
    );
    await request("DELETE", `/api/v1/auth/sessions/${expiringLogin.session.id}`, {
      token: browserApiToken,
      expected: 204,
    });
    await desktopPage.goto(`${baseUrl}/settings/devices`, { waitUntil: "networkidle" });
    await desktopPage.getByRole("heading", { name: "登录" }).waitFor();

    await request("GET", "/api/v1/users?limit=100&offset=0", { token: adminToken });
    assert(problems.length === 0, problems.join("; "));
    retainedTestData.push({ type: "browser-book", name: browserBookTitle });
    return {
      desktop_viewport: "1440x900",
      mobile_viewport: "390x844",
      browser_book_path: browserBookPath,
      screenshots_saved: false,
      traces_saved: false,
    };
  } finally {
    await desktop.close();
    await mobile.close();
    await adminContext.close();
    await browser.close();
  }
}

async function writeReports(status, failure, browserResult) {
  await mkdir(reportDirectory, { recursive: true });
  const report = {
    version: "0.2.0",
    environment: "staging",
    status,
    started_at: startedAt.toISOString(),
    completed_at: new Date().toISOString(),
    base_url: baseUrl,
    run_id: runId,
    results,
    browser: browserResult,
    retained_test_data: retainedTestData,
    steps,
    failure: failure ? redact(failure.message ?? failure) : null,
    notes: expectedSecureCookie
      ? ["HTTPS Secure Cookie validation completed."]
      : [
          "HTTP staging validation completed.",
          "HTTPS and Secure Cookie validation remain pending; HTTP does not replace that gate.",
        ],
  };
  await writeFile(reportJsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  const markdown = [
    "# Novel Platform v0.2.0 staging acceptance",
    "",
    `- Status: **${status}**`,
    "- Environment: **staging**",
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Base URL: ${baseUrl}`,
    `- Run ID: ${runId}`,
    `- API: ${results.api}`,
    `- Playwright: ${results.playwright}`,
    `- Cookie flags and rotation: ${results.cookies}`,
    `- Refresh replay detection: ${results.refresh_replay}`,
    `- User/Book/Edition isolation: ${results.isolation}`,
    `- Devices and sessions: ${results.devices_sessions}`,
    `- Persistence verification state: ${results.persistence_state}`,
    `- HTTPS: ${results.https}`,
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map(
      (item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail ?? ""} |`,
    ),
    "",
    "## Retained acceptance data",
    "",
    "v0.2.0 has no safe physical-delete API. Unique test users and data are retained instead of touching personal data:",
    "",
    ...retainedTestData.map((item) => `- ${item.type}: ${item.name}`),
    "",
    expectedSecureCookie
      ? "HTTPS and Secure Cookie acceptance passed."
      : "HTTPS and Secure Cookie acceptance is pending; this run used explicit HTTP staging settings.",
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No required HTTP staging check failed.",
    "",
  ].join("\n");
  await writeFile(reportMarkdownPath, markdown, { mode: 0o600 });

  const combined = `${await readFile(reportJsonPath, "utf8")}\n${await readFile(reportMarkdownPath, "utf8")}`;
  for (const sensitive of sensitiveValues) {
    assert(!sensitive || !combined.includes(sensitive), "sensitive value appeared in staging reports");
  }
  assert(!/Bearer\s+[A-Za-z0-9._~-]+/.test(combined), "Bearer credential appeared in reports");
  assert(!new RegExp(`${cookieName}=[^;\\s]+`).test(combined), "Cookie value appeared in reports");
}

async function main() {
  requireValue("STAGING_BASE_URL or PUBLIC_BASE_URL", baseUrl);
  requireValue("STAGING_ADMIN_EMAIL", adminLogin);
  requireValue("STAGING_ADMIN_PASSWORD", adminPassword);
  assert(/^https?:\/\//.test(baseUrl), "staging base URL must be HTTP or HTTPS");
  assert(/^[\p{L}\p{N}_-]{3,64}$/u.test(adminLogin), "admin login does not match v0.2.0 username rules");
  rememberSecret(adminPassword);
  rememberSecret(setupToken);

  let failure = null;
  let browserResult = null;
  try {
    await step("Health and setup state", async () => {
      await request("GET", "/api/v1/health/live");
      await request("GET", "/api/v1/health/ready");
      const setup = await request("GET", "/api/v1/setup/status");
      if (setup.body.setup_required) {
        requireValue("STAGING_SETUP_TOKEN", setupToken);
        await request("POST", "/api/v1/setup/initialize", {
          expected: 201,
          body: {
            setup_token: setupToken,
            username: adminLogin,
            display_name: process.env.STAGING_ADMIN_DISPLAY_NAME ?? "Staging Administrator",
            password: adminPassword,
          },
        });
      }
      const closed = await request("GET", "/api/v1/setup/status");
      assert(closed.body.setup_required === false, "setup is still open");
      await request("POST", "/api/v1/setup/initialize", {
        expected: 409,
        errorCode: "setup_not_required",
        body: {
          setup_token: setupToken || "closed-setup-check",
          username: `${runId}-second-admin`,
          display_name: "Should not exist",
          password: secret(),
        },
      });
    });

    const admin = await step("Administrator login and authentication boundaries", async () => {
      const value = await loginBody(adminLogin, adminPassword, "Staging acceptance administrator");
      assert(value.user.role === "admin", "configured staging account is not an administrator");
      await request("GET", "/api/v1/auth/me", {
        token: "invalid.staging.token",
        expected: 401,
      });
      await request("GET", "/api/v1/books", { expected: 401 });
      return value;
    });

    const passwords = {
      a: secret(),
      b: secret(),
      browser: secret(),
      reset: secret(),
    };
    const usernames = {
      a: `${runId}-a`,
      b: `${runId}-b`,
      browser: `${runId}-browser`,
    };
    const users = await step("Create unique non-personal acceptance users", async () => {
      const a = await createUser(admin.access_token, usernames.a, `${runId} A`, passwords.a);
      const b = await createUser(admin.access_token, usernames.b, `${runId} B`, passwords.b);
      const browser = await createUser(
        admin.access_token,
        usernames.browser,
        `${runId} Browser`,
        passwords.browser,
      );
      for (const user of [a, b, browser]) retainedTestData.push({ type: "user", name: user.username });
      await request("POST", "/api/v1/auth/login", {
        expected: 401,
        errorCode: "invalid_credentials",
        body: {
          username: a.username,
          password: "deliberately-wrong-password",
          refresh_token_delivery: "body",
          device: device("Rejected staging login"),
        },
      });
      return { a, b, browser };
    });

    const loginA = await loginBody(users.a.username, passwords.a, "Staging member A");
    const loginB = await loginBody(users.b.username, passwords.b, "Staging member B");

    await step("Cookie login, rotation, flags, logout, and replay", async () => {
      const first = await loginCookie(users.a.username, passwords.a, "Staging cookie rotation");
      assertCookieAttributes(first.cookie.raw);
      const refreshed = await request("POST", "/api/v1/auth/refresh", {
        cookie: first.cookie.pair,
        origin: baseUrl,
      });
      rememberSecret(refreshed.body.access_token);
      const replacement = cookiePair(refreshed.headers);
      assertCookieAttributes(replacement.raw);
      assert(first.cookie.pair !== replacement.pair, "cookie refresh token did not rotate");
      await request("POST", "/api/v1/auth/refresh", {
        cookie: first.cookie.pair,
        origin: baseUrl,
        expected: 401,
        errorCode: "refresh_token_reused",
      });

      const logoutLogin = await loginCookie(users.a.username, passwords.a, "Staging cookie logout");
      const logout = await request("POST", "/api/v1/auth/logout", {
        token: logoutLogin.body.access_token,
        cookie: logoutLogin.cookie.pair,
        expected: 204,
      });
      const clearingCookie = logout.headers.get("set-cookie") ?? "";
      assertCookieAttributes(clearingCookie, { clearing: true });
      await request("GET", "/api/v1/auth/me", {
        token: logoutLogin.body.access_token,
        expected: 401,
      });
      results.cookies = "PASS";
    });

    await step("Body refresh rotation and replay detection", async () => {
      const replayLogin = await loginBody(users.a.username, passwords.a, "Staging replay session");
      const rotated = await request("POST", "/api/v1/auth/refresh", {
        body: { refresh_token: replayLogin.refresh_token },
      });
      rememberSecret(rotated.body.access_token);
      rememberSecret(rotated.body.refresh_token);
      await request("POST", "/api/v1/auth/refresh", {
        body: { refresh_token: replayLogin.refresh_token },
        expected: 401,
        errorCode: "refresh_token_reused",
      });
      await request("GET", "/api/v1/auth/me", {
        token: rotated.body.access_token,
        expected: 401,
        errorCode: "session_revoked",
      });
      results.refresh_replay = "PASS";
    });

    const durable = await step("Private Books, Editions, preferences, and isolation", async () => {
      const bookA = await createBook(loginA.access_token, `${runId}-book-a`);
      const bookB = await createBook(loginB.access_token, `${runId}-book-b`);
      retainedTestData.push({ type: "book", name: bookA.canonical_title });
      retainedTestData.push({ type: "book", name: bookB.canonical_title });
      const sourceA = await createEdition(loginA.access_token, bookA.id, {
        title: `${runId}-source-a`,
        language: "ja",
        content_role: "source",
        translation_origin: null,
        creation_method: "uploaded",
      });
      const aiA = await createEdition(loginA.access_token, bookA.id, {
        title: `${runId}-ai-a`,
        language: "zh-CN",
        content_role: "translation",
        translation_origin: "ai",
        creation_method: "generated",
        source_edition_id: sourceA.id,
      });
      const humanA = await createEdition(loginA.access_token, bookA.id, {
        title: `${runId}-human-a`,
        language: "zh-CN",
        content_role: "translation",
        translation_origin: "human",
        creation_method: "uploaded",
      });
      const sourceB = await createEdition(loginB.access_token, bookB.id, {
        title: `${runId}-source-b`,
        language: "en",
        content_role: "source",
        translation_origin: null,
        creation_method: "uploaded",
      });
      await request("PATCH", `/api/v1/books/${bookA.id}/preferences`, {
        token: loginA.access_token,
        body: { preferred_edition_id: humanA.id },
      });
      const detail = await request("GET", `/api/v1/books/${bookA.id}`, { token: loginA.access_token });
      const ids = new Set(detail.body.editions.map((edition) => edition.id));
      assert(ids.has(aiA.id) && ids.has(humanA.id), "preferred Edition removed another version");
      for (const [token, bookId] of [
        [loginB.access_token, bookA.id],
        [loginA.access_token, bookB.id],
        [admin.access_token, bookA.id],
      ]) {
        await request("GET", `/api/v1/books/${bookId}`, {
          token,
          expected: 404,
          errorCode: "book_not_found",
        });
      }
      await request("GET", `/api/v1/books/${bookA.id}/editions/${sourceA.id}`, {
        token: loginB.access_token,
        expected: 404,
        errorCode: "book_not_found",
      });
      await request("POST", `/api/v1/books/${bookA.id}/editions`, {
        token: loginA.access_token,
        expected: 404,
        errorCode: "edition_not_found",
        body: {
          title: `${runId}-cross-user-edition`,
          language: "zh-CN",
          content_role: "translation",
          translation_origin: "ai",
          creation_method: "generated",
          source_edition_id: sourceB.id,
        },
      });
      await request("PATCH", `/api/v1/books/${bookA.id}/preferences`, {
        token: loginA.access_token,
        expected: 409,
        errorCode: "invalid_preferred_edition",
        body: { preferred_edition_id: sourceB.id },
      });
      results.isolation = "PASS";
      return { bookA, sourceA, aiA, humanA };
    });

    await step("Devices, sessions, and cross-user management boundaries", async () => {
      const devicesA = await request("GET", "/api/v1/devices", { token: loginA.access_token });
      const currentDevice = devicesA.body.find((item) => item.is_current);
      assert(currentDevice, "current device is missing");
      await request("PATCH", `/api/v1/devices/${currentDevice.id}`, {
        token: loginA.access_token,
        body: { name: `${runId}-renamed-device` },
      });
      const sessionsA = await request("GET", "/api/v1/auth/sessions", { token: loginA.access_token });
      assert(sessionsA.body.some((item) => item.is_current), "current session is missing");
      await request("DELETE", `/api/v1/auth/sessions/${loginB.session.id}`, {
        token: loginA.access_token,
        expected: 404,
        errorCode: "session_not_found",
      });
      await request("POST", `/api/v1/devices/${loginB.device.id}/revoke`, {
        token: loginA.access_token,
        expected: 404,
        errorCode: "device_not_found",
      });
      await request("GET", "/api/v1/users?limit=100&offset=0", {
        token: loginB.access_token,
        expected: 403,
        errorCode: "admin_required",
      });
      const secondA = await loginBody(users.a.username, passwords.a, "Staging member A second");
      await request("POST", "/api/v1/auth/sessions/revoke-others", { token: secondA.access_token });
      await request("GET", "/api/v1/auth/me", { token: loginA.access_token, expected: 401 });
      results.devices_sessions = "PASS";
    });

    const finalA = await step("Disable, enable, password reset, and old-session invalidation", async () => {
      const activeA = await loginBody(users.a.username, passwords.a, "Staging lifecycle A");
      await request("PATCH", `/api/v1/users/${users.a.id}`, {
        token: admin.access_token,
        body: { status: "disabled" },
      });
      await request("GET", "/api/v1/auth/me", {
        token: activeA.access_token,
        expected: 401,
        errorCode: "user_disabled",
      });
      await request("PATCH", `/api/v1/users/${users.a.id}`, {
        token: admin.access_token,
        body: { status: "active" },
      });
      await request("POST", `/api/v1/users/${users.a.id}/reset-password`, {
        token: admin.access_token,
        expected: 204,
        body: { new_password: passwords.reset },
      });
      await request("POST", "/api/v1/auth/login", {
        expected: 401,
        errorCode: "invalid_credentials",
        body: {
          username: users.a.username,
          password: passwords.a,
          refresh_token_delivery: "body",
          device: device("Old password rejection"),
        },
      });
      const newLogin = await loginBody(users.a.username, passwords.reset, "Staging reset password");
      await request("GET", "/api/v1/auth/me", { token: activeA.access_token, expected: 401 });
      const usersPage = await request("GET", "/api/v1/users?limit=100&offset=0", {
        token: admin.access_token,
      });
      assert(usersPage.body.some((item) => item.id === users.a.id), "test user disappeared");
      return newLogin;
    });

    await step("Write private persistence verification state", async () => {
      await mkdir(path.dirname(stateFile), { recursive: true });
      const state = {
        version: "0.2.0",
        created_at: new Date().toISOString(),
        username: users.a.username,
        password: passwords.reset,
        user_id: users.a.id,
        book_id: durable.bookA.id,
        edition_ids: [durable.sourceA.id, durable.aiA.id, durable.humanA.id],
        preferred_edition_id: durable.humanA.id,
      };
      await writeFile(stateFile, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
      await chmod(stateFile, 0o600);
      await request("GET", `/api/v1/books/${durable.bookA.id}`, { token: finalA.access_token });
      results.persistence_state = "PASS";
    });

    const browserApi = await loginBody(
      users.browser.username,
      passwords.browser,
      "Staging browser API controller",
    );
    browserResult = await step("Playwright real-browser desktop/mobile acceptance", async () => {
      const value = await browserAcceptance({
        browserUser: users.browser,
        browserPassword: passwords.browser,
        browserApiToken: browserApi.access_token,
        memberB: users.b,
        memberBPassword: passwords.b,
        adminToken: admin.access_token,
      });
      results.playwright = "PASS";
      return value;
    });

    results.api = "PASS";
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  }

  const status = failure ? "FAIL" : expectedSecureCookie ? "PASS" : "PASS_WITH_HTTPS_PENDING";
  await writeReports(status, failure, browserResult);
  if (failure) throw failure;
  process.stdout.write(`staging v0.2.0 acceptance ${status}: ${reportMarkdownPath}\n`);
}

if (verifyPersistenceOnly) {
  await verifyPersistenceState();
} else {
  await main();
}
