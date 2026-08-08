import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

import { chromium } from "@playwright/test";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const isV040 = process.env.NOVEL_ACCEPTANCE_VERSION === "0.4.0";
const acceptanceVersion = isV040 ? "0.4.0" : "0.3.0";
const acceptanceSlug = isV040 ? "v040" : "v030";
const markdownPath = path.join(artifacts, `acceptance-${acceptanceSlug}.md`);
const jsonPath = path.join(artifacts, `acceptance-${acceptanceSlug}.json`);
const commandLogPath = path.join(artifacts, `acceptance-${acceptanceSlug}-command.log`);
const started = new Date();
const runId = `${process.pid}-${Date.now()}`;
const project = `novel-platform-${acceptanceSlug}-${runId}`.toLowerCase();
const maxUploadBytes = 64 * 1024;
const keepEnvironment = process.env.KEEP_ACCEPTANCE_ENV === "1";
const steps = [];
const commandLog = [];
const sensitive = new Set();
const observedBodies = [];
const protectedContents = [
  "第一章\n独立 AI 译文",
  "第一章\n后补原文",
  "第一章\n替换后的独立 AI 译文",
  "第一章\n日本語の本文",
  "<html><body>acceptance fixture</body></html>",
];
const results = {
  migration: "SKIPPED",
  v020_regression: "SKIPPED",
  unit_tests: 0,
  integration_tests: 0,
  web_tests: 0,
  playwright: "SKIPPED",
  upload_persistence: "SKIPPED",
  backup_restore: "SKIPPED",
  secret_leak_scan: "SKIPPED",
  storage_leak_scan: "SKIPPED",
  ...(isV040 ? {
    v030_regression: "SKIPPED",
    reader_api: "SKIPPED",
    reader_browser: "SKIPPED",
    responsive_reader: "SKIPPED",
    progress_conflict: "SKIPPED",
    series_browser: "SKIPPED",
    reader_series_persistence: "SKIPPED",
  } : {}),
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertNoSkippedTests(output, label) {
  assert(
    !/\b(?:skipped|xfailed|xpassed)\b/i.test(output),
    `${label} reported a skipped or expected-failure result`,
  );
}

function secret(bytes = 32) {
  const value = randomBytes(bytes).toString("base64url");
  sensitive.add(value);
  return value;
}

function redact(value) {
  let output = String(value ?? "");
  for (const value of sensitive) output = output.replaceAll(value, "[REDACTED]");
  for (const content of protectedContents) {
    output = output
      .replaceAll(content, "[CONTENT REDACTED]")
      .replaceAll(JSON.stringify(content).slice(1, -1), "[CONTENT REDACTED]");
  }
  return output
    .replaceAll(/Bearer\s+[A-Za-z0-9._~-]+/g, "Bearer [REDACTED]")
    .replaceAll(/novel_refresh=[^;\s]+/g, "novel_refresh=[REDACTED]")
    .replaceAll(/\b[0-9a-f]{64}\b/g, "[HEX REDACTED]")
    .replaceAll("/data/library", "[STORAGE ROOT]");
}

function run(label, executable, args, options = {}) {
  commandLog.push(`$ ${label}`);
  try {
    const output = execFileSync(executable, args, {
      cwd: options.cwd ?? root,
      env: options.env ?? process.env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 40 * 1024 * 1024,
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

async function waitFor(url, timeoutMs = 180_000) {
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

async function request(apiUrl, method, route, options = {}) {
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
  const responseBody = response.status === 204
    ? null
    : await response.json().catch(() => null);
  observedBodies.push(JSON.stringify(responseBody));
  const expected = options.expected ?? 200;
  assert(
    response.status === expected,
    `${method} ${route}: expected ${expected}, got ${response.status}: ${redact(JSON.stringify(responseBody))}`,
  );
  if (options.errorCode) {
    assert(responseBody?.error?.code === options.errorCode, `${route}: wrong error code`);
  }
  return { body: responseBody, headers: response.headers };
}

async function login(apiUrl, username, password, name) {
  const response = await request(apiUrl, "POST", "/api/v1/auth/login", {
    body: {
      username,
      password,
      refresh_token_delivery: "body",
      device: {
        client_instance_id: randomUUID(),
        name,
        platform: "web",
        app_version: acceptanceVersion,
      },
    },
  });
  sensitive.add(response.body.access_token);
  sensitive.add(response.body.refresh_token);
  return response.body;
}

async function inspect(apiUrl, token, filename, filePath, operation, targets = {}) {
  const form = new FormData();
  form.set("operation", operation);
  form.set("text_encoding", targets.encoding ?? "auto");
  if (targets.bookId) form.set("target_book_id", targets.bookId);
  if (targets.editionId) form.set("target_edition_id", targets.editionId);
  form.set("file", new Blob([await readFile(filePath)]), filename);
  return (await request(apiUrl, "POST", "/api/v1/imports/inspect", {
    token,
    form,
    expected: targets.expected ?? 201,
    errorCode: targets.errorCode,
  })).body;
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

async function browserFlow({ webUrl, apiUrl, fixtureDirectory, setupToken, passwords }) {
  const browser = await chromium.launch({ headless: process.env.HEADED !== "1" });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(webUrl);
    await page.getByLabel("Setup Token").fill(setupToken);
    await page.getByLabel("管理员用户名").fill("admin");
    await page.getByLabel("显示名称").fill("验收管理员");
    await page.getByLabel("密码", { exact: true }).fill(passwords.admin);
    await page.getByLabel("确认密码").fill(passwords.admin);
    await page.getByRole("button", { name: "安全初始化" }).click();
    await page.getByRole("heading", { name: "登录" }).waitFor();

    const admin = await login(apiUrl, "admin", passwords.admin, "验收管理 API");
    for (const [username, displayName, password] of [
      ["user-a", "用户 A", passwords.userA],
      ["user-b", "用户 B", passwords.userB],
    ]) {
      await request(apiUrl, "POST", "/api/v1/users", {
        token: admin.access_token,
        expected: 201,
        body: { username, display_name: displayName, password, role: "member" },
      });
    }

    await page.getByLabel("用户名").fill("user-a");
    await page.getByLabel("密码").fill(passwords.userA);
    await page.getByLabel("设备名称").fill("用户 A 浏览器");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByRole("heading", { name: /整理你的书/ }).waitFor();
    await page.getByRole("link", { name: "上传", exact: true }).click();
    await page.getByText("单文件上限 64 KiB", { exact: false }).waitFor();
    await page.getByLabel("选择 EPUB 或 TXT 文件").setInputFiles(
      path.join(fixtureDirectory, "acceptance.epub"),
    );
    await page.getByRole("button", { name: "上传并预览" }).click();
    await page.getByRole("heading", { name: "确认导入" }).waitFor();
    await page.getByLabel("书名").fill("用户 A EPUB 图书");
    await page.getByLabel("Edition 名称").fill("EPUB 初始版本");
    await page.getByRole("button", { name: "确认导入" }).click();
    await page.getByRole("heading", { name: "用户 A EPUB 图书" }).waitFor();
    await page.getByAltText("用户 A EPUB 图书 封面").waitFor();
    await page.getByText("Fixture Author", { exact: true }).first().waitFor();
    const bookId = new URL(page.url()).pathname.split("/").at(-1);

    async function uploadEdition(file, preset, title, language) {
      await page.getByRole("link", { name: "上传新版本" }).click();
      await page.getByLabel("选择 EPUB 或 TXT 文件").setInputFiles(
        path.join(fixtureDirectory, file),
      );
      await page.getByRole("button", { name: "上传并预览" }).click();
      await page.getByRole("heading", { name: "确认导入" }).waitFor();
      await page.getByLabel(preset).check();
      await page.getByLabel("Edition 名称").fill(title);
      await page.getByLabel("语言").fill(language);
      const commitResponse = page.waitForResponse(
        (response) => response.url().includes("/imports/") && response.url().endsWith("/commit"),
      );
      await page.getByRole("button", { name: "确认导入" }).click();
      const payload = await (await commitResponse).json();
      await page.getByRole("heading", { name: title }).waitFor();
      return payload.edition;
    }

    const translation = await uploadEdition(
      "independent-ai.txt", "AI 译文", "独立 AI 译文", "zh-CN",
    );
    const source = await uploadEdition("source.txt", "原文", "后补原文", "ja");
    const translationCard = page.locator("article.edition-card", {
      has: page.getByRole("heading", { name: "独立 AI 译文", exact: true }),
    });
    await translationCard.getByLabel("原文关联").selectOption(source.id);
    await translationCard.getByRole("button", { name: "保存关系与状态" }).click();
    await translationCard.getByText("关联原文：后补原文", { exact: true }).waitFor();
    await translationCard.getByRole("button", { name: "设为首选" }).click();
    await translationCard.getByRole("button", { name: "当前首选" }).waitFor();

    await translationCard.getByRole("link", { name: "替换文件" }).click();
    await page.getByLabel("选择 EPUB 或 TXT 文件").setInputFiles(
      path.join(fixtureDirectory, "replacement.txt"),
    );
    await page.getByRole("button", { name: "上传并预览" }).click();
    await page.getByRole("heading", { name: "确认导入" }).waitFor();
    page.once("dialog", (dialog) => dialog.accept());
    const replacementResponse = page.waitForResponse(
      (response) => response.url().includes("/imports/") && response.url().endsWith("/commit"),
    );
    await page.getByRole("button", { name: "确认替换文件" }).click();
    const replacement = await (await replacementResponse).json();
    assert(replacement.edition.id === translation.id, "replacement changed Edition ID");
    assert(replacement.edition.source_edition_id === source.id, "replacement lost source link");

    await page.waitForURL(new RegExp(`/books/${bookId}$`));
    await page.getByRole("heading", { name: "独立 AI 译文" }).waitFor();
    await page.reload();
    await page.getByRole("heading", { name: "独立 AI 译文" }).waitFor();
    await page.getByRole("button", { name: "退出" }).click();
    await page.getByRole("heading", { name: "登录" }).waitFor();
    await page.getByLabel("用户名").fill("user-b");
    await page.getByLabel("密码").fill(passwords.userB);
    await page.getByLabel("设备名称").fill("用户 B 浏览器");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByText("书库还是空的").waitFor();
    await page.goto(`${webUrl}/books/${bookId}`);
    await page.getByRole("alert").waitFor();

    await page.getByRole("button", { name: "退出" }).click();
    await page.getByRole("heading", { name: "登录" }).waitFor();
    await page.getByLabel("用户名").fill("user-a");
    await page.getByLabel("密码").fill(passwords.userA);
    await page.getByLabel("设备名称").fill("用户 A 禁用浏览器");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByText("用户 A EPUB 图书").waitFor();
    const deviceAdmin = await login(apiUrl, "user-a", passwords.userA, "用户 A 设备管理 API");
    const devices = await request(apiUrl, "GET", "/api/v1/devices", {
      token: deviceAdmin.access_token,
    });
    const browserDevice = devices.body.find((device) => device.name === "用户 A 禁用浏览器");
    assert(browserDevice, "user A browser device was not found");
    await request(apiUrl, "POST", `/api/v1/devices/${browserDevice.id}/revoke`, {
      token: deviceAdmin.access_token,
      expected: 204,
    });
    await page.goto(`${webUrl}/upload`);
    await page.getByRole("heading", { name: "登录" }).waitFor();
    assert(errors.length === 0, `browser errors: ${errors.join("; ")}`);
    results.playwright = "PASS";
    return {
      bookId,
      translationId: translation.id,
      sourceId: source.id,
      disabledDeviceRejected: true,
    };
  } finally {
    await context.close();
    await browser.close();
  }
}

async function browserV040Flow({ webUrl, apiUrl, fixtureDirectory, passwords, browserState }) {
  const apiAuth = await login(apiUrl, "user-a", passwords.userA, "v0.4 浏览器准备 API");
  const detail = await request(apiUrl, "GET", `/api/v1/books/${browserState.bookId}`, {
    token: apiAuth.access_token,
  });
  const epubEdition = detail.body.editions.find((edition) => edition.title === "EPUB 初始版本");
  assert(epubEdition, "initial EPUB Edition was not found");

  const browser = await chromium.launch({ headless: process.env.HEADED !== "1" });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(`${webUrl}/login`);
    await page.getByRole("heading", { name: "登录" }).waitFor();
    await page.getByLabel("用户名").fill("user-a");
    await page.getByLabel("密码").fill(passwords.userA);
    await page.getByLabel("设备名称").fill("v0.4 阅读验收浏览器");
    await page.getByRole("button", { name: "登录书库" }).click();
    await page.getByRole("heading", { name: /整理你的书/ }).waitFor();

    await page.goto(`${webUrl}/read/${epubEdition.id}`);
    await page.getByText("acceptance fixture", { exact: true }).waitFor();
    await page.getByRole("button", { name: "目录" }).click();
    const toc = page.locator('aside[aria-label="目录"]');
    await toc.getByRole("button", { name: "第 1 节" }).waitFor();
    await toc.getByRole("button", { name: "关闭" }).click();

    const settingsRequest = page.waitForResponse((response) => (
      response.url().endsWith("/api/v1/reader/settings")
      && response.request().method() === "PATCH"
    ));
    await page.getByRole("button", { name: "阅读设置" }).click();
    await page.getByLabel("主题").selectOption("dark");
    await settingsRequest;
    await page.locator("main.reader--dark").waitFor();
    await page.getByRole("button", { name: "关闭" }).click();

    for (const viewport of [
      { width: 1024, height: 768 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      const layout = await page.evaluate(() => ({
        viewport: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        readerWidth: document.querySelector("main.reader")?.getBoundingClientRect().width ?? 0,
      }));
      assert(
        layout.documentWidth <= layout.viewport + 1 && layout.readerWidth <= layout.viewport + 1,
        `reader overflowed at ${viewport.width}x${viewport.height}`,
      );
      await page.getByRole("button", { name: "目录" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "阅读设置" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "下一节 →" }).waitFor({ state: "visible" });
    }
    results.responsive_reader = "PASS";

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByLabel("切换 Edition").selectOption(browserState.translationId);
    await page.waitForURL(new RegExp(`/read/${browserState.translationId}$`));
    await page.getByText("替换后的独立 AI 译文", { exact: false }).waitFor();
    await page.getByLabel("切换 Edition").selectOption(epubEdition.id);
    await page.waitForURL(new RegExp(`/read/${epubEdition.id}$`));
    await page.getByText("acceptance fixture", { exact: true }).waitFor();
    await page.getByLabel("返回图书详情").click();
    await page.getByRole("heading", { name: "用户 A EPUB 图书" }).waitFor();
    results.reader_browser = "PASS";

    await page.goto(`${webUrl}/series`);
    await page.getByRole("heading", { name: "自定义图书系列" }).waitFor();
    await page.getByLabel("系列名称").fill("验收系列");
    await page.getByLabel("简介（可选）").fill("验证稳定顺序与批量上传");
    await page.getByRole("button", { name: "创建系列" }).click();
    const seriesCard = page.locator("article.series-card", {
      has: page.getByRole("heading", { name: "验收系列", exact: true }),
    });
    await seriesCard.getByRole("link", { name: "打开系列 →" }).click();
    await page.getByRole("heading", { name: "验收系列", exact: true }).waitFor();
    const seriesId = new URL(page.url()).pathname.split("/").at(-1);
    assert(seriesId, "series id was not present in the browser URL");

    await page.getByLabel("选择未归入系列的图书").selectOption({
      label: "用户 A EPUB 图书",
    });
    await page.getByRole("button", { name: "加入当前系列" }).click();
    await page.locator("article.series-book", { hasText: "用户 A EPUB 图书" }).waitFor();
    await page.getByRole("link", { name: "在系列中上传 EPUB / TXT" }).click();
    await page.getByLabel("选择一个或多个 EPUB 或 TXT 文件").setInputFiles([
      path.join(fixtureDirectory, "source.txt"),
      path.join(fixtureDirectory, "fake.epub"),
      path.join(fixtureDirectory, "independent-ai.txt"),
    ]);
    await page.getByRole("button", { name: "批量上传 3 本" }).click();
    await page.waitForFunction(() => (
      document.querySelectorAll("article.batch-result--succeeded").length === 2
      && document.querySelectorAll("article.batch-result--failed").length === 1
    ));
    assert(
      await page.locator("article.batch-result--succeeded").count() === 2,
      "two valid files were not retained after batch upload",
    );
    assert(
      await page.locator("article.batch-result--failed").count() === 1,
      "invalid batch item did not show an independent failure",
    );
    await page.getByRole("link", { name: "返回系列查看已成功图书" }).click();
    await page.getByRole("heading", { name: "验收系列", exact: true }).waitFor();
    assert(await page.locator("article.series-book").count() === 3, "series order lost a book");
    await page.setViewportSize({ width: 390, height: 844 });
    const seriesLayout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
    }));
    assert(
      seriesLayout.documentWidth <= seriesLayout.viewport + 1,
      "series detail overflowed on a phone viewport",
    );
    await page.getByRole("link", { name: "在系列中上传 EPUB / TXT" }).waitFor({
      state: "visible",
    });
    results.series_browser = "PASS";
    assert(errors.length === 0, `v0.4 browser errors: ${errors.join("; ")}`);
    return { seriesId, epubEditionId: epubEdition.id };
  } finally {
    await context.close();
    await browser.close();
  }
}

async function readerSeriesApiFlow({
  apiUrl,
  passwords,
  userA,
  browserState,
  v040BrowserState,
}) {
  const openedA = await request(
    apiUrl,
    "POST",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/open`,
    { token: userA.access_token },
  );
  assert(openedA.body.publication.file_format === "epub", "EPUB reader format was wrong");
  assert(openedA.body.publication.sections.length > 0, "EPUB reader had no navigation");
  const section = openedA.body.publication.sections[0];
  const content = await request(
    apiUrl,
    "GET",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/sections/${section.id}`,
    { token: userA.access_token },
  );
  assert(content.body.html.includes("acceptance fixture"), "EPUB body was not readable");

  const secondDevice = await login(apiUrl, "user-a", passwords.userA, "v0.4 第二阅读设备");
  const openedB = await request(
    apiUrl,
    "POST",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/open`,
    { token: secondDevice.access_token },
  );
  const expectedVersion = openedB.body.progress.version;
  const savedA = await request(
    apiUrl,
    "PATCH",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/progress`,
    {
      token: userA.access_token,
      body: {
        expected_version: expectedVersion,
        section_id: section.id,
        block_id: null,
        section_progress: 0.75,
        overall_progress: 0.75,
        edition_file_revision: openedA.body.publication.file_revision,
      },
    },
  );
  const stale = await request(
    apiUrl,
    "PATCH",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/progress`,
    {
      token: secondDevice.access_token,
      expected: 409,
      errorCode: "reading_progress_conflict",
      body: {
        expected_version: expectedVersion,
        section_id: section.id,
        block_id: null,
        section_progress: 0.9,
        overall_progress: 0.9,
        edition_file_revision: openedA.body.publication.file_revision,
      },
    },
  );
  assert(
    stale.body.error.details.current_version === savedA.body.version,
    "stale progress response did not expose the current version",
  );
  const movedBackward = await request(
    apiUrl,
    "PATCH",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/progress`,
    {
      token: secondDevice.access_token,
      body: {
        expected_version: savedA.body.version,
        section_id: section.id,
        block_id: null,
        section_progress: 0.1,
        overall_progress: 0.1,
        edition_file_revision: openedA.body.publication.file_revision,
        status: "reading",
      },
    },
  );
  assert(movedBackward.body.overall_progress === 0.1, "intentional backward progress failed");
  results.progress_conflict = "PASS";

  await request(apiUrl, "PATCH", "/api/v1/reader/settings", {
    token: userA.access_token,
    body: {
      font_size: 23,
      line_height: 2,
      content_width: 840,
      font_family: "sans",
      theme: "sepia",
    },
  });
  const settingsB = await request(apiUrl, "GET", "/api/v1/reader/settings", {
    token: secondDevice.access_token,
  });
  assert(settingsB.body.font_size === 23 && settingsB.body.theme === "sepia", "settings did not sync");

  const txtReader = await request(
    apiUrl,
    "POST",
    `/api/v1/editions/${browserState.translationId}/reader/open`,
    { token: secondDevice.access_token },
  );
  assert(txtReader.body.publication.file_format === "txt", "TXT reader format was wrong");
  const txtSection = txtReader.body.publication.sections[0];
  const txtContent = await request(
    apiUrl,
    "GET",
    `/api/v1/editions/${browserState.translationId}/reader/sections/${txtSection.id}`,
    { token: secondDevice.access_token },
  );
  assert(txtContent.body.html.includes("替换后的独立 AI 译文"), "TXT body was not readable");
  const recent = await request(apiUrl, "GET", "/api/v1/reader/recent", {
    token: secondDevice.access_token,
  });
  assert(recent.body.some((item) => item.edition_id === browserState.translationId), "recent reading missed TXT");

  const userB = await login(apiUrl, "user-b", passwords.userB, "v0.4 隔离验证设备");
  await request(
    apiUrl,
    "POST",
    `/api/v1/editions/${v040BrowserState.epubEditionId}/reader/open`,
    { token: userB.access_token, expected: 404, errorCode: "edition_not_found" },
  );
  await request(apiUrl, "GET", `/api/v1/series/${v040BrowserState.seriesId}`, {
    token: userB.access_token,
    expected: 404,
    errorCode: "series_not_found",
  });
  const series = await request(apiUrl, "GET", `/api/v1/series/${v040BrowserState.seriesId}`, {
    token: userA.access_token,
  });
  assert(series.body.books.length === 3, "series did not retain all successful books");
  assert(
    series.body.books.every((book, index) => book.series_position === index + 1),
    "series positions were not stable",
  );
  results.reader_api = "PASS";
  return {
    editionId: v040BrowserState.epubEditionId,
    seriesId: v040BrowserState.seriesId,
    expectedProgress: movedBackward.body.overall_progress,
    expectedProgressVersion: movedBackward.body.version,
    sectionId: section.id,
    fileRevision: openedA.body.publication.file_revision,
  };
}

async function writeReports(status, environment, failure) {
  await mkdir(artifacts, { recursive: true });
  const gitCommit = run("git rev-parse HEAD", "git", ["rev-parse", "HEAD"]).trim();
  const report = {
    version: acceptanceVersion,
    status,
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: gitCommit,
    environment,
    results,
    steps,
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await writeFile(jsonPath, `${redact(JSON.stringify(report, null, 2))}\n`);
  const markdown = [
    `# Novel Platform v${acceptanceVersion} acceptance`,
    "",
    `- Status: **${status}**`,
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${gitCommit}`,
    `- Compose project: ${environment.compose_project}`,
    `- Isolated ports: PostgreSQL ${environment.postgres_port}, API ${environment.server_port}, Web ${environment.web_port}`,
    `- Migration result: ${results.migration}`,
    `- v0.2.0 regression result: ${results.v020_regression}`,
    `- Unit tests: ${results.unit_tests}`,
    `- PostgreSQL integration tests: ${results.integration_tests}`,
    `- Web tests: ${results.web_tests}`,
    `- Playwright result: ${results.playwright}`,
    `- Upload persistence result: ${results.upload_persistence}`,
    `- Backup/restore result: ${results.backup_restore}`,
    `- Secret leak scan result: ${results.secret_leak_scan}`,
    `- Storage leak scan result: ${results.storage_leak_scan}`,
    ...(isV040 ? [
      `- v0.3.0 regression result: ${results.v030_regression}`,
      `- Reader API result: ${results.reader_api}`,
      `- Reader browser result: ${results.reader_browser}`,
      `- Responsive reader result: ${results.responsive_reader}`,
      `- Progress conflict result: ${results.progress_conflict}`,
      `- Series browser result: ${results.series_browser}`,
      `- Reader/series restart persistence result: ${results.reader_series_persistence}`,
    ] : []),
    "",
    "## Steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...steps.map((item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail ?? ""} |`),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required checks.",
    "",
  ].join("\n");
  await writeFile(markdownPath, redact(markdown));
  await writeFile(commandLogPath, `${commandLog.map(redact).join("\n")}\n`);
}

async function main() {
  await mkdir(artifacts, { recursive: true });
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), `novel-${acceptanceSlug}-`));
  sensitive.add(temporaryRoot);
  const fixtureDirectory = path.join(temporaryRoot, "fixtures");
  const backupDirectory = path.join(temporaryRoot, "backups");
  const restoreReport = path.join(temporaryRoot, "restore-report.md");
  const stagingEnvFile = path.join(temporaryRoot, ".env.acceptance");
  const [postgresPort, serverPort, webPort] = await Promise.all([
    freePort(), freePort(), freePort(),
  ]);
  const passwords = { admin: secret(24), userA: secret(24), userB: secret(24) };
  const setupToken = secret();
  const postgresPassword = secret(24);
  const composeEnvironment = {
    ...process.env,
    COMPOSE_PROJECT_NAME: project,
    POSTGRES_PASSWORD: postgresPassword,
    POSTGRES_PORT: String(postgresPort),
    SERVER_PORT: String(serverPort),
    WEB_PORT: String(webPort),
    ENVIRONMENT: "staging",
    CORS_ORIGINS: `["http://localhost:${webPort}"]`,
    TRUSTED_HOSTS: '["localhost","127.0.0.1","server"]',
    AUTH_SETUP_TOKEN: setupToken,
    AUTH_JWT_SECRET: secret(),
    AUTH_HASH_SECRET: secret(),
    AUTH_COOKIE_SECURE: "false",
    MAX_UPLOAD_BYTES: String(maxUploadBytes),
  };
  const environment = {
    compose_project: project,
    postgres_port: postgresPort,
    server_port: serverPort,
    web_port: webPort,
    postgres_volume: `${project}_postgres_data`,
    library_volume: `${project}_library_data`,
  };
  const apiUrl = `http://localhost:${serverPort}`;
  const webUrl = `http://localhost:${webPort}`;
  const docker = (label, args) => run(label, "docker", ["compose", "-p", project, ...args], {
    env: composeEnvironment,
  });
  let failure = null;
  let composeStarted = false;
  let v040State = null;

  try {
    await step("Docker and Compose check", async () => {
      run("docker --version", "docker", ["--version"]);
      run("docker compose version", "docker", ["compose", "version"]);
    });
    await step("v0.2.0 regression acceptance", async () => {
      run("v0.2.0 acceptance", process.execPath, ["scripts/acceptance/gates/v020.mjs"]);
      results.v020_regression = "PASS";
    });
    await step("Generate copyright-free EPUB/TXT fixtures", async () => {
      run(
        "generate fixtures",
        "python3",
        ["apps/server/tests/fixtures/generate_library_fixtures.py", fixtureDirectory],
      );
      await writeFile(
        path.join(fixtureDirectory, "application-too-large.txt"),
        Buffer.alloc(maxUploadBytes + 1, 0x61),
      );
      await writeFile(
        path.join(fixtureDirectory, "proxy-too-large.txt"),
        Buffer.alloc(maxUploadBytes + 1024 * 1024 + 1024, 0x61),
      );
    });
    await step(`Start isolated v${acceptanceVersion} Compose environment and migrate`, async () => {
      composeStarted = true;
      docker("docker compose up --build --detach", ["up", "--build", "--detach"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await waitFor(webUrl);
      const revision = docker("read Alembic revision", [
        "exec", "-T", "postgres", "psql", "-U", "novel_platform", "-d", "novel_platform",
        "-Atc", "SELECT version_num FROM alembic_version",
      ]).trim();
      assert(revision === "20260714_0004", `unexpected migration revision ${revision}`);
      results.migration = "PASS";
    });
    const browserState = await step(
      "Playwright upload, independent translation, source link, replacement, and user isolation",
      () => browserFlow({ webUrl, apiUrl, fixtureDirectory, setupToken, passwords }),
    );
    const userA = await login(apiUrl, "user-a", passwords.userA, "用户 A 验收 API");
    await step("Unsafe EPUB/TXT validation and owner-scoped API isolation", async () => {
      await inspect(
        apiUrl, userA.access_token, "fake.epub",
        path.join(fixtureDirectory, "fake.epub"), "create_book",
        { expected: 422, errorCode: "invalid_epub" },
      );
      await inspect(
        apiUrl, userA.access_token, "unsafe.epub",
        path.join(fixtureDirectory, "unsafe.epub"), "create_book",
        { expected: 422, errorCode: "unsafe_archive_path" },
      );
      const applicationOversize = await inspect(
        apiUrl, userA.access_token, "application-too-large.txt",
        path.join(fixtureDirectory, "application-too-large.txt"), "create_book",
        { expected: 413, errorCode: "upload_too_large" },
      );
      if (applicationOversize.error.details.import_id) {
        await request(
          apiUrl,
          "DELETE",
          `/api/v1/imports/${applicationOversize.error.details.import_id}`,
          { token: userA.access_token, expected: 204 },
        );
      }
      const proxyOversizeForm = new FormData();
      proxyOversizeForm.set("operation", "create_book");
      proxyOversizeForm.set("text_encoding", "auto");
      proxyOversizeForm.set(
        "file",
        new Blob([await readFile(path.join(fixtureDirectory, "proxy-too-large.txt"))]),
        "proxy-too-large.txt",
      );
      const proxyOversizeResponse = await fetch(`${webUrl}/api/v1/imports/inspect`, {
        method: "POST",
        headers: { Authorization: `Bearer ${userA.access_token}` },
        body: proxyOversizeForm,
      });
      const proxyOversizeBody = await proxyOversizeResponse.json();
      observedBodies.push(JSON.stringify(proxyOversizeBody));
      assert(proxyOversizeResponse.status === 413, "Nginx did not reject an oversized upload");
      assert(
        proxyOversizeBody.error?.code === "upload_too_large",
        "Nginx oversized response did not use the stable error envelope",
      );
      const userB = await login(apiUrl, "user-b", passwords.userB, "用户 B 验收 API");
      await request(apiUrl, "GET", `/api/v1/books/${browserState.bookId}`, {
        token: userB.access_token, expected: 404, errorCode: "book_not_found",
      });
      await request(apiUrl, "GET", `/api/v1/editions/${browserState.translationId}/file`, {
        token: userB.access_token, expected: 404, errorCode: "edition_not_found",
      });
    });
    if (isV040) {
      const v040BrowserState = await step(
        "Playwright reader, responsive layouts, Edition switching, series, and partial batch upload",
        () => browserV040Flow({
          webUrl,
          apiUrl,
          fixtureDirectory,
          passwords,
          browserState,
        }),
      );
      v040State = await step(
        "Reader API, TXT/EPUB content, settings sync, conflict, backward move, and isolation",
        () => readerSeriesApiFlow({
          apiUrl,
          passwords,
          userA,
          browserState,
          v040BrowserState,
        }),
      );
    }
    await step("API, Web, and PostgreSQL restart persistence", async () => {
      docker("restart all durable services", ["restart", "postgres", "server", "web"]);
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      await waitFor(webUrl);
      const download = await fetch(
        `${apiUrl}/api/v1/editions/${browserState.translationId}/file`,
        { headers: { Authorization: `Bearer ${userA.access_token}` } },
      );
      assert(download.ok, "file download failed after restart");
      const content = await download.text();
      assert(content.includes("替换后的"), "replacement content was not durable");
      const preference = await request(
        apiUrl, "GET", `/api/v1/books/${browserState.bookId}/preferences`,
        { token: userA.access_token },
      );
      assert(
        preference.body.preferred_edition_id === browserState.translationId,
        "preferred Edition changed during replacement or restart",
      );
      results.upload_persistence = "PASS";
      if (isV040) {
        assert(v040State, "v0.4 acceptance state was not created before restart");
        const series = await request(apiUrl, "GET", `/api/v1/series/${v040State.seriesId}`, {
          token: userA.access_token,
        });
        assert(series.body.books.length === 3, "series data was lost after restart");
        const reader = await request(
          apiUrl,
          "POST",
          `/api/v1/editions/${v040State.editionId}/reader/open`,
          { token: userA.access_token },
        );
        assert(
          reader.body.progress.version === v040State.expectedProgressVersion
          && reader.body.progress.overall_progress === v040State.expectedProgress,
          "reading progress was lost after restart",
        );
        const readerSettings = await request(apiUrl, "GET", "/api/v1/reader/settings", {
          token: userA.access_token,
        });
        assert(
          readerSettings.body.font_size === 23 && readerSettings.body.theme === "sepia",
          "reader settings were lost after restart",
        );
        results.reader_series_persistence = "PASS";
      }
    });
    await step("Explicit CP932 TXT create, Book deletion, and physical file cleanup", async () => {
      const inspected = await inspect(
        apiUrl, userA.access_token, "encoded-cp932.txt",
        path.join(fixtureDirectory, "encoded-cp932.txt"), "create_book",
        { encoding: "cp932" },
      );
      assert(inspected.text_encoding === "cp932", "explicit CP932 encoding was not retained");
      const committed = await request(
        apiUrl, "POST", `/api/v1/imports/${inspected.id}/commit`,
        {
          token: userA.access_token,
          body: {
            canonical_title: "待删除的 CP932 图书",
            edition_title: "CP932 原文",
            language: "ja",
            content_role: "source",
          },
        },
      );
      const databaseBefore = Number(docker("stored file count before delete", [
        "exec", "-T", "postgres", "psql", "-U", "novel_platform", "-d", "novel_platform",
        "-Atc", "SELECT count(*) FROM stored_files",
      ]).trim());
      const physicalBefore = Number(docker("physical file count before delete", [
        "exec", "-T", "server", "python", "-c",
        "from novel_platform.api.dependencies.storage import get_file_storage; print(len(get_file_storage().list_storage_keys()))",
      ]).trim());
      await request(apiUrl, "DELETE", `/api/v1/books/${committed.body.book.id}`, {
        token: userA.access_token,
        expected: 204,
      });
      const databaseAfter = Number(docker("stored file count after delete", [
        "exec", "-T", "postgres", "psql", "-U", "novel_platform", "-d", "novel_platform",
        "-Atc", "SELECT count(*) FROM stored_files",
      ]).trim());
      const physicalAfter = Number(docker("physical file count after delete", [
        "exec", "-T", "server", "python", "-c",
        "from novel_platform.api.dependencies.storage import get_file_storage; print(len(get_file_storage().list_storage_keys()))",
      ]).trim());
      assert(databaseBefore - databaseAfter === 2, "TXT StoredFile rows were not cleaned");
      assert(physicalBefore - physicalAfter === 2, "TXT physical files were not cleaned");
    });
    await step("Disabled user A device rejects further browser upload access", async () => {
      assert(browserState.disabledDeviceRejected, "disabled device remained authenticated");
    });
    await step("Revoked API device rejects upload and protected download", async () => {
      const blocked = await login(apiUrl, "user-a", passwords.userA, "用户 A 待禁用 API");
      const manager = await login(apiUrl, "user-a", passwords.userA, "用户 A 设备管理二号 API");
      const devices = await request(apiUrl, "GET", "/api/v1/devices", {
        token: manager.access_token,
      });
      const blockedDevice = devices.body.find((device) => device.name === "用户 A 待禁用 API");
      assert(blockedDevice, "revocation target device was not found");
      await request(apiUrl, "POST", `/api/v1/devices/${blockedDevice.id}/revoke`, {
        token: manager.access_token,
        expected: 204,
      });
      const blockedUpload = await inspect(
        apiUrl, blocked.access_token, "blocked.txt",
        path.join(fixtureDirectory, "source.txt"), "create_book",
        { expected: 401 },
      );
      assert(
        ["device_revoked", "session_revoked"].includes(blockedUpload.error.code),
        "revoked device upload returned the wrong error",
      );
      const blockedDownload = await request(
        apiUrl, "GET", `/api/v1/editions/${browserState.translationId}/file`,
        { token: blocked.access_token, expected: 401 },
      );
      assert(
        ["device_revoked", "session_revoked"].includes(blockedDownload.body.error.code),
        "revoked device download returned the wrong error",
      );
      if (isV040 && v040State) {
        const blockedReader = await request(
          apiUrl,
          "POST",
          `/api/v1/editions/${v040State.editionId}/reader/open`,
          { token: blocked.access_token, expected: 401 },
        );
        assert(
          ["device_revoked", "session_revoked"].includes(blockedReader.body.error.code),
          "revoked device reader returned the wrong error",
        );
      }
    });
    await step("Manual complete backup and isolated restore round trip", async () => {
      const envLines = [
        `COMPOSE_PROJECT_NAME=${project}`,
        `PUBLIC_BASE_URL=http://localhost:${webPort}`,
        "POSTGRES_DB=novel_platform",
        "POSTGRES_USER=novel_platform",
        `POSTGRES_PASSWORD=${postgresPassword}`,
        "ENVIRONMENT=staging",
        `CORS_ORIGINS='["http://localhost:${webPort}"]'`,
        "TRUSTED_HOSTS='[" + '"localhost","127.0.0.1","server"' + "]'",
        `AUTH_SETUP_TOKEN=${setupToken}`,
        `AUTH_JWT_SECRET=${composeEnvironment.AUTH_JWT_SECRET}`,
        `AUTH_HASH_SECRET=${composeEnvironment.AUTH_HASH_SECRET}`,
        "AUTH_COOKIE_SECURE=false",
        "STAGING_ADMIN_EMAIL=acceptance@example.invalid",
        `STAGING_ADMIN_PASSWORD=${passwords.admin}`,
        `POSTGRES_PORT=${postgresPort}`,
        `SERVER_PORT=${serverPort}`,
        `WEB_PORT=${webPort}`,
        `MAX_UPLOAD_BYTES=${maxUploadBytes}`,
      ];
      await writeFile(stagingEnvFile, `${envLines.join("\n")}\n`);
      await chmod(stagingEnvFile, 0o600);
      const operationsEnvironment = {
        ...process.env,
        STAGING_ROOT: temporaryRoot,
        STAGING_ENV_FILE: stagingEnvFile,
        STAGING_COMPOSE_FILE: path.join(root, "compose.yaml"),
      };
      const backupOutput = run(
        "complete library backup", "bash", [
          "scripts/staging/data/backup-library.sh",
          backupDirectory,
        ],
        { env: operationsEnvironment },
      );
      const backupPath = backupOutput.match(/^backup=(.+)$/m)?.[1];
      assert(backupPath, "backup script did not report its output directory");
      run(
        "isolated complete restore test",
        "bash",
        ["scripts/staging/data/restore-library.sh", "--test", backupPath, restoreReport],
        { env: operationsEnvironment },
      );
      const restoreText = await readFile(restoreReport, "utf8");
      assert(restoreText.includes("PASS"), "restore report failed");
      if (isV040) {
        for (const label of [
          "Series present",
          "Series memberships present",
          "Reading progresses present",
          "Reader settings present",
        ]) {
          const count = Number(restoreText.match(new RegExp(`- ${label}: (\\d+)`))?.[1] ?? 0);
          assert(count > 0, `${label} was not restored`);
        }
      }
      await waitFor(`${apiUrl}/api/v1/health/ready`);
      results.backup_restore = "PASS";
    });
    await step("Python, PostgreSQL, Web, OpenAPI, and production build gates", async () => {
      docker("create integration database", [
        "exec", "-T", "postgres", "createdb", "-U", "novel_platform", "novel_platform_test",
      ]);
      const uv = findUv();
      const serverDirectory = path.join(root, "apps", "server");
      const testEnvironment = {
        ...process.env,
        TEST_DATABASE_URL: `postgresql+psycopg://novel_platform:${postgresPassword}@127.0.0.1:${postgresPort}/novel_platform_test`,
      };
      run("ruff check", uv, ["run", "ruff", "check", "."], { cwd: serverDirectory });
      run("ruff format check", uv, ["run", "ruff", "format", "--check", "."], { cwd: serverDirectory });
      run("mypy", uv, ["run", "mypy"], { cwd: serverDirectory });
      const unit = run("Python unit tests", uv, ["run", "pytest", "tests/unit", "-q"], {
        cwd: serverDirectory,
      });
      const integration = run(
        "PostgreSQL integration tests", uv, ["run", "pytest", "tests/integration", "-q"],
        { cwd: serverDirectory, env: testEnvironment },
      );
      assertNoSkippedTests(unit, "Python unit tests");
      assertNoSkippedTests(integration, "PostgreSQL integration tests");
      results.unit_tests = Number(unit.match(/(\d+) passed/)?.[1] ?? 0);
      results.integration_tests = Number(integration.match(/(\d+) passed/)?.[1] ?? 0);
      run("Web lint", "pnpm", ["lint"]);
      const web = run("Web tests", "pnpm", ["test"]);
      assertNoSkippedTests(web, "Web tests");
      results.web_tests = Number(web.match(/Tests\s+(\d+) passed/)?.[1] ?? 0);
      run("Web production build", "pnpm", ["build"]);
      const generatedApiPaths = [
        path.join(root, "packages", "api-client", "openapi.json"),
        path.join(root, "packages", "api-client", "src", "schema.d.ts"),
      ];
      const generatedApiBefore = await Promise.all(generatedApiPaths.map((file) => readFile(file)));
      run("OpenAPI generated client check", "pnpm", ["api:generate"]);
      const generatedApiAfter = await Promise.all(generatedApiPaths.map((file) => readFile(file)));
      assert(
        generatedApiBefore.every((content, index) => content.equals(generatedApiAfter[index])),
        "OpenAPI generated client was stale before acceptance",
      );
      assert(
        results.unit_tests > 0 && results.integration_tests > 0 && results.web_tests > 0,
        "test counts were not captured",
      );
    });
    await step("Secret, token, cookie, content, and storage-path leak scan", async () => {
      const logs = docker("docker compose logs", ["logs", "--no-color"]);
      for (const value of sensitive) assert(!logs.includes(value), "secret appeared in logs");
      assert(!/novel_refresh=|authorization:\s*bearer/i.test(logs), "cookie or bearer token appeared in logs");
      assert(!logs.includes("/data/library"), "storage root appeared in logs");
      assert(
        !/\/api\/v1\/(?:editions\/[0-9a-f-]+\/file|books\/[0-9a-f-]+\/cover|imports\/[0-9a-f-]+\/cover)/i.test(logs),
        "protected file URL appeared in logs",
      );
      for (const content of protectedContents) {
        assert(
          !logs.includes(content) && !logs.includes(JSON.stringify(content).slice(1, -1)),
          "novel content appeared in logs",
        );
      }
      const bodies = observedBodies.join("\n");
      for (const marker of ["/data/library", "storage_key", "sha256"]) {
        assert(!bodies.includes(marker), `${marker} appeared in an API response`);
      }
      const artifactText = `${commandLog.map(redact).join("\n")}\n${steps.map((item) => JSON.stringify(item)).join("\n")}`;
      for (const content of protectedContents) {
        assert(!artifactText.includes(content), "novel content appeared in reports");
      }
      results.secret_leak_scan = "PASS";
      results.storage_leak_scan = "PASS";
      if (isV040) results.v030_regression = "PASS";
    });
    await step("No required acceptance result is failed or skipped", async () => {
      for (const [name, value] of Object.entries(results)) {
        if (typeof value === "number") {
          assert(value > 0, `${name} did not report a passing test count`);
        } else {
          assert(value === "PASS", `${name} remained ${value}`);
        }
      }
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (composeStarted && !keepEnvironment) {
      try {
        await step("Clean isolated containers, networks, and volumes", async () => {
          docker("docker compose down --volumes", ["down", "--volumes", "--remove-orphans"]);
        });
      } catch (cleanupError) {
        failure ??= cleanupError instanceof Error ? cleanupError : new Error(String(cleanupError));
      }
    }
    if (!keepEnvironment) await rm(temporaryRoot, { recursive: true, force: true });
    let status = failure ? "FAIL" : "PASS";
    await writeReports(status, environment, failure);
    const reportText = `${await readFile(markdownPath, "utf8")}${await readFile(jsonPath, "utf8")}${await readFile(commandLogPath, "utf8")}`;
    for (const value of sensitive) {
      if (reportText.includes(value)) failure ??= new Error("secret appeared in acceptance report");
    }
    if (failure && status !== "FAIL") {
      status = "FAIL";
      await writeReports(status, environment, failure);
    }
    if (failure) {
      process.stderr.write(`${redact(failure.message)}\n`);
      process.exitCode = 1;
    } else {
      process.stdout.write(`v${acceptanceVersion} acceptance passed: ${markdownPath}\n`);
    }
  }
}

await main();
