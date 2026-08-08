import { execFileSync, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";

import { chromium } from "@playwright/test";

const root = process.cwd();
const artifacts = path.join(root, "artifacts");
const screenshotsDirectory = path.join(artifacts, "visual-v060");
const markdownPath = path.join(artifacts, "acceptance-v060.md");
const jsonPath = path.join(artifacts, "acceptance-v060.json");
const actionLogPath = path.join(artifacts, "acceptance-v060-actions.log");
const coreJsonPath = path.join(artifacts, "acceptance-v060-core.json");
const started = new Date();
const actions = [];
const uiSteps = [];
const screenshots = [];
const responsiveChecks = [];
const consoleErrors = [];

const uiCriterionLabels = [
  "桌面登录页无横向溢出",
  "390px 移动登录页无横向溢出",
  "移动端主导航通过 Drawer 可用",
  "管理员和阅读者导航项正确",
  "恢复会话导航受限",
  "主要页面存在唯一主标题",
  "登录、Upload、凭证和 Reader 关键可访问名称保持",
  "管理员危险操作提供可访问确认",
  "一次性凭证确认后从 DOM 移除",
  "Upload 使用 inspect 流程且 antd 不自动请求",
  "Reader light/dark/sepia 三主题可切换",
  "390px Reader 可完成目录、设置、上一节和下一节",
  "管理审计表在窄屏下不破坏整页布局",
  "关键页面无浏览器控制台错误",
  "生产 build chunk 和 gzip 大小写入脱敏报告",
  "部署 CSP 允许 Ant Design 运行时样式且仍禁止内联脚本",
];

const ids = {
  admin: "00000000-0000-4000-8000-000000000001",
  reader: "00000000-0000-4000-8000-000000000002",
  book: "00000000-0000-4000-8000-000000000101",
  edition: "00000000-0000-4000-8000-000000000102",
  editionTwo: "00000000-0000-4000-8000-000000000103",
  series: "00000000-0000-4000-8000-000000000104",
  readerIdentity: "00000000-0000-4000-8000-000000000105",
};
const timestamp = "2026-07-16T08:00:00Z";
const publicSite = {
  site_name: "林间阅读室",
  purpose_statement: "供站点所有者与少量受邀阅读者非经营性使用。",
  privacy_statement: "仅处理登录、设备授权和阅读同步所需的最少信息。",
  icp_registration_number: null,
  icp_registration_url: null,
};
const site = {
  ...publicSite,
  default_reader_max_devices: 3,
  audit_retention_days: 90,
  admin_locked: false,
  migration_completed: true,
  updated_at: timestamp,
};
const users = {
  admin: {
    id: ids.admin,
    display_name: "馆藏管理员",
    role: "admin",
    status: "active",
    last_login_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
  },
  reader: {
    id: ids.reader,
    display_name: "受邀阅读者",
    role: "reader",
    status: "active",
    last_login_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
  },
};
const edition = {
  id: ids.edition,
  book_id: ids.book,
  title: "原文版",
  language: "ja",
  content_role: "source",
  translation_origin: null,
  creation_method: "uploaded",
  source_edition_id: null,
  supersedes_edition_id: null,
  status: "ready",
  revision: 2,
  metadata: {},
  current_file: {
    revision: 2,
    file_format: "epub",
    original_filename: "sample.epub",
    media_type: "application/epub+zip",
    size_bytes: 2048,
    text_encoding: null,
    content_item_count: 2,
    uploaded_at: timestamp,
    download_url: `/api/v1/editions/${ids.edition}/file`,
  },
  reader_available: true,
  reading_status: "reading",
  reading_progress: 0.42,
  last_read_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
};
const editionTwo = {
  ...edition,
  id: ids.editionTwo,
  title: "人工译文",
  language: "zh-CN",
  content_role: "translation",
  translation_origin: "human",
  source_edition_id: ids.edition,
  current_file: {
    ...edition.current_file,
    revision: 1,
    file_format: "txt",
    original_filename: "translation.txt",
    media_type: "text/plain",
    text_encoding: "utf-8",
  },
  reading_status: "not_started",
  reading_progress: 0,
  last_read_at: null,
};
const bookDetail = {
  id: ids.book,
  canonical_title: "长标题视觉验收示例：一座安静的私人数字阅读馆",
  canonical_author: "测试作者",
  description: "这是脱敏的界面布局说明，用于验证长中文、层级和换行。",
  metadata: {},
  cover_url: null,
  cover_thumbnail_url: null,
  edition_count: 2,
  editions: [edition, editionTwo],
  created_at: timestamp,
  updated_at: timestamp,
};
const bookListItem = {
  id: ids.book,
  canonical_title: bookDetail.canonical_title,
  canonical_author: bookDetail.canonical_author,
  description: bookDetail.description,
  edition_count: 2,
  languages: ["ja", "zh-CN"],
  file_formats: ["epub", "txt"],
  preferred_edition_id: ids.editionTwo,
  preferred_edition_title: "人工译文",
  reading_status: "reading",
  reading_progress: 0.42,
  last_read_at: timestamp,
  continue_edition_id: ids.edition,
  continue_edition_title: "原文版",
  continue_url: `/read/${ids.edition}`,
  series_id: ids.series,
  series_name: "林间三部曲",
  series_position: 1,
  cover_thumbnail_url: null,
  created_at: timestamp,
  updated_at: timestamp,
};
const readerIdentity = {
  id: ids.readerIdentity,
  display_name: "家庭阅读者",
  admin_note: "仅用于本地视觉验收",
  status: "active",
  created_at: timestamp,
  updated_at: timestamp,
  credential: {
    id: "00000000-0000-4000-8000-000000000201",
    hint: "npa_…demo",
    lifecycle_status: "active",
    effective_status: "active",
    expires_at: "2026-08-16T08:00:00Z",
    max_devices: 3,
    allow_new_devices: true,
    active_device_count: 1,
    last_used_at: timestamp,
    created_at: timestamp,
    reissued_at: null,
    revoked_at: null,
    suspended_at: null,
  },
};
const auditEvent = {
  id: "00000000-0000-4000-8000-000000000301",
  event_type: "reader_login_succeeded",
  outcome: "success",
  subject_user_id: ids.readerIdentity,
  actor_user_id: ids.readerIdentity,
  access_credential_id: null,
  device_id: null,
  session_id: null,
  passkey_id: null,
  client_ip: "198.51.100.0",
  user_agent_summary: "脱敏浏览器",
  metadata: {
    reason: "visual_acceptance",
    long_value: "用于验证长 metadata 的折叠、复制和受控换行。".repeat(8),
  },
  created_at: timestamp,
};
const readerOpen = {
  book: {
    id: ids.book,
    canonical_title: "脱敏阅读示例",
    canonical_author: "测试作者",
    description: null,
    metadata: {},
    cover_url: null,
    cover_thumbnail_url: null,
    created_at: timestamp,
    updated_at: timestamp,
  },
  edition: {
    id: ids.edition,
    book_id: ids.book,
    title: "原文版",
    language: "ja",
    content_role: "source",
    translation_origin: null,
    file_format: "epub",
    reading_status: "reading",
    reading_progress: 0.2,
    last_read_at: timestamp,
  },
  available_editions: [
    {
      id: ids.edition,
      book_id: ids.book,
      title: "原文版",
      language: "ja",
      content_role: "source",
      translation_origin: null,
      file_format: "epub",
      reading_status: "reading",
      reading_progress: 0.2,
      last_read_at: timestamp,
    },
    {
      id: ids.editionTwo,
      book_id: ids.book,
      title: "人工译文",
      language: "zh-CN",
      content_role: "translation",
      translation_origin: "human",
      file_format: "txt",
      reading_status: "not_started",
      reading_progress: 0,
      last_read_at: null,
    },
  ],
  publication: {
    file_format: "epub",
    file_revision: 2,
    sections: [
      { id: "section-1", index: 0, title: "第一章" },
      { id: "section-2", index: 1, title: "第二章" },
    ],
    toc: [
      { title: "第一章", section_id: "section-1" },
      { title: "第二章", section_id: "section-2" },
    ],
  },
  progress: {
    edition_id: ids.edition,
    status: "reading",
    section_id: "section-1",
    block_id: null,
    section_progress: 0.2,
    overall_progress: 0.1,
    edition_file_revision: 2,
    version: 3,
    last_read_at: timestamp,
  },
  settings: {
    font_size: 18,
    line_height: 1.8,
    content_width: 760,
    font_family: "serif",
    theme: "light",
    updated_at: timestamp,
  },
};
const importRecord = {
  id: "00000000-0000-4000-8000-000000000401",
  status: "ready",
  operation: "create_book",
  original_filename: "ui-sample.txt",
  file_format: "txt",
  size_bytes: 64,
  target_book_id: null,
  target_edition_id: null,
  text_encoding: "utf-8",
  content_item_count: 2,
  metadata_preview: {
    title: "脱敏上传示例",
    language: "zh-CN",
    creators: ["测试作者"],
    description: "用于验证 inspect 后的元数据校对布局。",
  },
  warnings: [],
  cover_available: false,
  cover_preview_url: null,
  error_code: null,
  error_message: null,
  created_at: timestamp,
  started_at: timestamp,
  completed_at: timestamp,
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function redact(value) {
  return String(value ?? "")
    .replace(/\bnpa_[A-Za-z0-9_-]{20,}\b/g, "npa_[REDACTED]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[JWT REDACTED]")
    .replace(/(?:novel_refresh|novel_device)=[^;\s]+/g, "[COOKIE REDACTED]")
    .replace(/postgres(?:ql)?(?:\+\w+)?:\/\/\S+/gi, "[DATABASE URL REDACTED]")
    .replaceAll(root, "[REPOSITORY]");
}

function run(label, executable, args, options = {}) {
  actions.push(label);
  try {
    return execFileSync(executable, args, {
      cwd: root,
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
    const result = await action();
    uiSteps.push({
      name,
      status: "PASS",
      duration_ms: Date.now() - stepStarted,
      detail: "completed",
    });
    return result;
  } catch (error) {
    uiSteps.push({
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

async function waitForUrl(url) {
  const deadline = Date.now() + 30_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw lastError ?? new Error("Vite preview did not become ready.");
}

function tokenResponse(role, recoveryMode = false) {
  const user = role === "reader" ? users.reader : users.admin;
  return {
    access_token: "ui-acceptance-memory-token",
    token_type: "bearer",
    expires_in: 900,
    user,
    device: {
      id: "00000000-0000-4000-8000-000000000501",
      name: "UI acceptance browser",
      platform: "web",
    },
    session: {
      id: "00000000-0000-4000-8000-000000000502",
      created_at: timestamp,
      expires_at: "2026-08-16T08:00:00Z",
      recovery_mode: recoveryMode,
    },
  };
}

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installMockApi(page, role, state) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const method = request.method();

    if (pathname === "/api/v1/site") return json(route, publicSite);
    if (pathname === "/api/v1/auth/refresh") {
      if (role === "public") {
        return json(route, {
          error: {
            code: "invalid_refresh_token",
            message: "not authenticated",
            details: {},
          },
        }, 401);
      }
      return json(route, tokenResponse(role, role === "recovery"));
    }
    if (pathname === "/api/v1/auth/logout") {
      return route.fulfill({ status: 204, body: "" });
    }
    if (pathname === "/api/v1/books" && method === "GET") {
      return json(route, [bookListItem]);
    }
    if (pathname === "/api/v1/reader/recent") {
      return json(route, [{
        book_id: ids.book,
        book_title: bookDetail.canonical_title,
        book_cover_thumbnail_url: null,
        edition_id: ids.edition,
        edition_title: "原文版",
        edition_language: "ja",
        file_format: "epub",
        status: "reading",
        progress: 0.42,
        last_read_at: timestamp,
        continue_url: `/read/${ids.edition}`,
        series_id: ids.series,
        series_name: "林间三部曲",
      }]);
    }
    if (pathname === `/api/v1/books/${ids.book}`) {
      return json(route, bookDetail);
    }
    if (pathname === `/api/v1/books/${ids.book}/preferences`) {
      return json(route, {
        preferred_edition_id: ids.editionTwo,
        last_opened_edition_id: ids.edition,
      });
    }
    if (pathname === "/api/v1/series") {
      return json(route, [{
        id: ids.series,
        name: "林间三部曲",
        description: "脱敏系列说明，用于检查移动布局和稳定排序。",
        book_count: 1,
        created_at: timestamp,
        updated_at: timestamp,
      }]);
    }
    if (pathname === `/api/v1/series/${ids.series}`) {
      return json(route, {
        id: ids.series,
        name: "林间三部曲",
        description: "脱敏系列说明，用于检查移动布局和稳定排序。",
        book_count: 1,
        books: [bookListItem],
        created_at: timestamp,
        updated_at: timestamp,
      });
    }
    if (pathname === "/api/v1/admin/site") {
      if (method === "PATCH") {
        return json(route, { ...site, ...request.postDataJSON() });
      }
      return json(route, site);
    }
    if (pathname === "/api/v1/admin/readers") {
      if (method === "POST") {
        const created = {
          ...readerIdentity,
          id: randomUUID(),
          display_name: request.postDataJSON().display_name,
        };
        state.readers.push(created);
        return json(route, {
          reader: created,
          access_credential: state.oneTimeCredential,
        }, 201);
      }
      return json(route, state.readers);
    }
    if (pathname.startsWith("/api/v1/admin/readers/")) {
      if (pathname.endsWith("/devices")) return json(route, []);
      if (pathname.endsWith("/audit")) return json(route, [auditEvent]);
      if (pathname.endsWith("/credential/reissue")) {
        return json(route, {
          reader: readerIdentity,
          access_credential: state.oneTimeCredential,
        });
      }
      if (method === "PATCH") return json(route, readerIdentity);
      return route.fulfill({ status: 204, body: "" });
    }
    if (pathname === "/api/v1/admin/audit") {
      return json(route, [auditEvent]);
    }
    if (pathname === "/api/v1/auth/passkeys") {
      return json(route, [{
        id: "00000000-0000-4000-8000-000000000601",
        name: "主安全设备",
        backed_up: true,
        device_type: "multi_device",
        created_at: timestamp,
        last_used_at: timestamp,
        revoked_at: null,
      }]);
    }
    if (pathname === "/api/v1/auth/sessions") {
      return json(route, [{
        id: "00000000-0000-4000-8000-000000000602",
        device_id: "00000000-0000-4000-8000-000000000603",
        device_name: "UI acceptance browser",
        platform: "web",
        is_current: true,
        recovery_mode: false,
        revoked: false,
        created_at: timestamp,
        last_seen_at: timestamp,
        expires_at: "2026-08-16T08:00:00Z",
      }]);
    }
    if (pathname === `/api/v1/editions/${ids.edition}/reader/open`) {
      return json(route, {
        ...readerOpen,
        settings: state.readerSettings,
        progress: state.readerProgress,
      });
    }
    if (pathname.includes(`/api/v1/editions/${ids.edition}/reader/sections/`)) {
      const sectionId = decodeURIComponent(pathname.split("/").at(-1));
      const second = sectionId === "section-2";
      return json(route, {
        id: sectionId,
        index: second ? 1 : 0,
        title: second ? "第二章" : "第一章",
        html: `<p data-reader-block="placeholder">${second ? "第二章" : "第一章"} · 脱敏阅读内容占位</p>`,
        resource_ids: [],
      });
    }
    if (pathname === `/api/v1/editions/${ids.edition}/reader/progress`) {
      const payload = request.postDataJSON();
      state.readerProgress = {
        ...state.readerProgress,
        ...payload,
        status: payload.status ?? state.readerProgress.status,
        version: state.readerProgress.version + 1,
        last_read_at: timestamp,
      };
      return json(route, state.readerProgress);
    }
    if (pathname === "/api/v1/reader/settings") {
      const payload = request.postDataJSON();
      state.readerSettings = {
        ...state.readerSettings,
        ...payload,
        updated_at: timestamp,
      };
      return json(route, state.readerSettings);
    }
    if (pathname === "/api/v1/imports/inspect") {
      state.inspectRequests += 1;
      return json(route, importRecord, 201);
    }
    if (pathname.startsWith("/api/v1/imports/")) {
      return json(route, {
        upload: { ...importRecord, status: "succeeded" },
        book: bookDetail,
        edition,
      });
    }
    if (pathname === "/api/v1/health/live" || pathname === "/api/v1/health/ready") {
      return json(route, { status: "ok" });
    }
    return json(route, {
      error: {
        code: "unhandled_ui_acceptance_route",
        message: `Unhandled UI acceptance route: ${method} ${pathname}`,
        details: {},
      },
    }, 500);
  });
}

async function createPage(browser, baseUrl, role, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const state = {
    inspectRequests: 0,
    oneTimeCredential: "ui-once-credential-removed-after-confirmation",
    readers: [readerIdentity],
    readerSettings: { ...readerOpen.settings },
    readerProgress: { ...readerOpen.progress },
  };
  const errors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const location = message.location().url;
    const expectedAnonymousRefreshDenial = (
      role === "public"
      && location.endsWith("/api/v1/auth/refresh")
      && message.text().includes("401")
    );
    if (!expectedAnonymousRefreshDenial) errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await installMockApi(page, role, state);
  return { context, page, state, errors, baseUrl };
}

async function openReady(session, pathname, heading) {
  await session.page.goto(`${session.baseUrl}${pathname}`);
  await session.page.getByRole("heading", { level: 1, name: heading }).waitFor();
  await session.page.waitForTimeout(80);
}

async function assertLayout(session, label) {
  const metrics = await session.page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    h1Count: document.querySelectorAll("main h1").length,
    overflowing: Array.from(document.querySelectorAll("body *"))
      .filter((element) => {
        if (!(element instanceof HTMLElement)) return false;
        const rect = element.getBoundingClientRect();
        return (
          rect.right > document.documentElement.clientWidth + 1
          || element.scrollWidth > element.clientWidth + 1
        );
      })
      .slice(0, 8)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        class_name: element.className,
        text: element.textContent?.trim().slice(0, 80) ?? "",
        client_width: element.clientWidth,
        scroll_width: element.scrollWidth,
        right: Math.round(element.getBoundingClientRect().right),
      })),
  }));
  assert(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label} has horizontal overflow (${metrics.scrollWidth}/${metrics.clientWidth}): ${JSON.stringify(metrics.overflowing)}`,
  );
  assert(metrics.h1Count === 1, `${label} must have exactly one main h1`);
  responsiveChecks.push({
    label,
    viewport: session.page.viewportSize(),
    client_width: metrics.clientWidth,
    scroll_width: metrics.scrollWidth,
    h1_count: metrics.h1Count,
  });
}

async function finishPage(session, label) {
  if (session.errors.length > 0) {
    consoleErrors.push(...session.errors.map((error) => `${label}: ${redact(error)}`));
  }
  await session.context.close();
}

async function capture(browser, baseUrl, item, viewport, suffix, setup) {
  const session = await createPage(browser, baseUrl, item.role, viewport);
  try {
    await openReady(session, item.pathname, item.heading);
    if (setup) await setup(session);
    await assertLayout(session, `${item.slug}-${suffix}`);
    const filename = `${item.slug}-${suffix}.png`;
    await session.page.screenshot({
      path: path.join(screenshotsDirectory, filename),
      fullPage: true,
    });
    screenshots.push(`artifacts/visual-v060/${filename}`);
  } finally {
    await finishPage(session, `${item.slug}-${suffix}`);
  }
}

async function chooseReaderTheme(page, label) {
  await page.getByRole("button", { name: "阅读设置" }).click();
  await page.getByRole("combobox", { name: "主题" }).click();
  await page.getByTitle(label).click();
  await page.getByRole("button", { name: /Close|关闭/i }).click();
  await page.waitForTimeout(420);
}

async function readerVisuals(browser, baseUrl, viewport, suffix) {
  const session = await createPage(browser, baseUrl, "reader", viewport);
  try {
    await openReady(session, `/read/${ids.edition}`, "第一章");
    const backgrounds = [];
    backgrounds.push(
      await session.page.locator("main").evaluate((element) =>
        getComputedStyle(element).backgroundColor),
    );
    await assertLayout(session, `reader-light-${suffix}`);
    await session.page.screenshot({
      path: path.join(screenshotsDirectory, `reader-light-${suffix}.png`),
      fullPage: true,
    });
    screenshots.push(`artifacts/visual-v060/reader-light-${suffix}.png`);

    await chooseReaderTheme(session.page, "深色");
    backgrounds.push(
      await session.page.locator("main").evaluate((element) =>
        getComputedStyle(element).backgroundColor),
    );
    await assertLayout(session, `reader-dark-${suffix}`);
    await session.page.screenshot({
      path: path.join(screenshotsDirectory, `reader-dark-${suffix}.png`),
      fullPage: true,
    });
    screenshots.push(`artifacts/visual-v060/reader-dark-${suffix}.png`);

    await chooseReaderTheme(session.page, "护眼");
    backgrounds.push(
      await session.page.locator("main").evaluate((element) =>
        getComputedStyle(element).backgroundColor),
    );
    assert(new Set(backgrounds).size === 3, "Reader themes did not produce three distinct surfaces");
    await assertLayout(session, `reader-sepia-${suffix}`);
    await session.page.screenshot({
      path: path.join(screenshotsDirectory, `reader-sepia-${suffix}.png`),
      fullPage: true,
    });
    screenshots.push(`artifacts/visual-v060/reader-sepia-${suffix}.png`);

    if (suffix === "mobile") {
      await session.page.getByRole("button", { name: "目录" }).click();
      const toc = session.page.getByRole("dialog", { name: "目录" });
      await toc.getByRole("button", { name: "第二章" }).click();
      await session.page.getByRole("heading", { level: 1, name: "第二章" }).waitFor();
      await toc.waitFor({ state: "hidden" });
      await session.page.getByRole("button", { name: "阅读设置" }).click();
      const settingsDrawer = session.page.getByRole("dialog", { name: "阅读设置" });
      await settingsDrawer.getByRole("slider", { name: "字号" }).waitFor();
      await settingsDrawer.getByRole("button", { name: /Close|关闭/i }).click();
      await session.page.getByRole("button", { name: "← 上一节" }).click();
      await session.page.getByRole("heading", { level: 1, name: "第一章" }).waitFor();
      await session.page.getByRole("button", { name: "下一节 →" }).click();
      await session.page.getByRole("heading", { level: 1, name: "第二章" }).waitFor();
    }
  } finally {
    await finishPage(session, `reader-${suffix}`);
  }
}

async function runRoleAndInteractionChecks(browser, baseUrl) {
  const adminSession = await createPage(
    browser,
    baseUrl,
    "admin",
    { width: 1440, height: 900 },
  );
  try {
    await openReady(
      adminSession,
      "/",
      "整理馆藏，也继续上次的阅读。",
    );
    const adminNav = adminSession.page.getByRole("navigation", { name: "主导航" });
    await adminNav.getByRole("link", { name: "上传" }).waitFor();
    await adminNav.getByRole("link", { name: "管理" }).waitFor();
    await adminNav.getByRole("link", { name: "状态" }).waitFor();
  } finally {
    await finishPage(adminSession, "admin-navigation");
  }

  const readerSession = await createPage(
    browser,
    baseUrl,
    "reader",
    { width: 1440, height: 900 },
  );
  try {
    await openReady(
      readerSession,
      "/",
      "安静阅读，也继续上次的位置。",
    );
    const readerNav = readerSession.page.getByRole("navigation", { name: "主导航" });
    assert(await readerNav.getByRole("link", { name: "上传" }).count() === 0, "Reader navigation exposed Upload");
    assert(await readerNav.getByRole("link", { name: "管理" }).count() === 0, "Reader navigation exposed Admin");
    assert(await readerNav.getByRole("link", { name: "状态" }).count() === 0, "Reader navigation exposed Status");
  } finally {
    await finishPage(readerSession, "reader-navigation");
  }

  const recoverySession = await createPage(
    browser,
    baseUrl,
    "recovery",
    { width: 1440, height: 900 },
  );
  try {
    await openReady(recoverySession, "/admin/security", "Passkey 与管理员会话");
    const labels = await recoverySession.page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link")
      .allTextContents();
    assert(
      labels.length === 1 && labels[0] === "登记 Passkey",
      `Recovery navigation was not confined: ${labels.join(", ")}`,
    );
  } finally {
    await finishPage(recoverySession, "recovery-navigation");
  }

  const mobileSession = await createPage(
    browser,
    baseUrl,
    "admin",
    { width: 390, height: 844 },
  );
  try {
    await openReady(
      mobileSession,
      "/",
      "整理馆藏，也继续上次的阅读。",
    );
    const trigger = mobileSession.page.getByRole("button", { name: "打开主导航" });
    const box = await trigger.boundingBox();
    assert(box && box.width >= 40 && box.height >= 40, "Mobile navigation trigger is too small");
    await trigger.click();
    const drawer = mobileSession.page.getByRole("dialog", { name: "林间阅读室" });
    await drawer.getByRole("link", { name: "管理" }).waitFor();
    await mobileSession.page.keyboard.press("Escape");
    await drawer.waitFor({ state: "hidden" });
  } finally {
    await finishPage(mobileSession, "mobile-navigation");
  }

  const adminReaders = await createPage(
    browser,
    baseUrl,
    "admin",
    { width: 1280, height: 800 },
  );
  try {
    await openReady(adminReaders, "/admin/readers", "受邀阅读者");
    await adminReaders.page.getByRole("button", { name: "永久撤销" }).click();
    await adminReaders.page.getByText("永久撤销这份凭证？").waitFor();
    await adminReaders.page.getByRole("button", { name: "取消" }).click();

    await adminReaders.page.getByLabel("显示名称").first().fill("新阅读者");
    await adminReaders.page.getByRole("button", { name: "创建并显示凭证" }).click();
    const dialog = adminReaders.page.getByRole("dialog");
    await dialog.getByText(adminReaders.state.oneTimeCredential).waitFor();
    await adminReaders.page.keyboard.press("Escape");
    assert(await dialog.count() === 1, "One-time credential modal closed on Escape");
    await dialog.getByRole("button", { name: "我已安全保存" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert(
      await adminReaders.page.getByText(adminReaders.state.oneTimeCredential).count() === 0,
      "One-time credential remained in the DOM",
    );
  } finally {
    await finishPage(adminReaders, "admin-reader-security");
  }

  const uploadSession = await createPage(
    browser,
    baseUrl,
    "admin",
    { width: 1280, height: 800 },
  );
  try {
    await openReady(uploadSession, "/upload", "上传与版本管理");
    await uploadSession.page
      .getByLabel("选择 EPUB 或 TXT 文件")
      .setInputFiles({
        name: "ui-sample.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("sanitized ui fixture"),
      });
    await uploadSession.page.waitForTimeout(200);
    assert(uploadSession.state.inspectRequests === 0, "antd Upload sent an automatic request");
    await uploadSession.page.getByRole("button", { name: "上传并预览" }).click();
    await uploadSession.page.getByRole("heading", { name: "确认导入" }).waitFor();
    assert(uploadSession.state.inspectRequests === 1, "Upload inspect request count was incorrect");
  } finally {
    await finishPage(uploadSession, "upload-inspect-flow");
  }
}

async function writeReports(status, core, bundle, failure) {
  const uiCriteria = uiCriterionLabels.map((label, index) => ({
    number: 85 + index,
    label,
    status: status === "PASS" ? "PASS" : "FAIL",
    evidence: "v060_ui_browser",
  }));
  const report = {
    version: "0.6.0",
    status,
    started_at: started.toISOString(),
    completed_at: new Date().toISOString(),
    git_commit: run("read Git commit", "git", ["rev-parse", "HEAD"]).trim(),
    inherited_v050: {
      status: core?.status ?? "NOT_RUN",
      criteria_count: core?.criteria?.length ?? 0,
      artifact: "artifacts/acceptance-v060-core.json",
    },
    ui: {
      criteria: uiCriteria,
      steps: uiSteps,
      responsive_checks: responsiveChecks,
      screenshots,
      console_errors: consoleErrors,
    },
    bundle: bundle
      ? {
          entry: bundle.entry,
          initial_css: bundle.initial_css,
          entry_budget: bundle.entry_budget,
          artifact: "artifacts/bundle-v060.json",
        }
      : null,
    criteria: [...(core?.criteria ?? []), ...uiCriteria],
    failure: failure ? redact(failure.message ?? failure) : null,
  };
  await mkdir(artifacts, { recursive: true });
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  const markdown = [
    "# Novel Platform v0.6.0 acceptance",
    "",
    `- Status: **${status}**`,
    `- Started: ${report.started_at}`,
    `- Completed: ${report.completed_at}`,
    `- Git commit: ${report.git_commit}`,
    `- Inherited v0.5.0 criteria: ${report.inherited_v050.criteria_count} (${report.inherited_v050.status})`,
    `- v0.6.0 UI criteria: ${uiCriteria.length}`,
    `- Responsive layout checks: ${responsiveChecks.length}`,
    `- Sanitized screenshots: ${screenshots.length}`,
    `- Initial entry: ${bundle ? `${(bundle.entry.raw_bytes / 1000).toFixed(2)} kB raw / ${(bundle.entry.gzip_bytes / 1000).toFixed(2)} kB gzip` : "not available"}`,
    `- Initial entry 200 kB gzip budget: ${bundle?.entry_budget.status ?? "NOT_RUN"}`,
    "",
    "## v0.6.0 UI criteria",
    "",
    "| # | Status | Criterion |",
    "| ---: | --- | --- |",
    ...uiCriteria.map((item) => `| ${item.number} | ${item.status} | ${item.label} |`),
    "",
    "## Browser and build steps",
    "",
    "| Status | Step | Duration (ms) | Detail |",
    "| --- | --- | ---: | --- |",
    ...uiSteps.map((item) => `| ${item.status} | ${item.name} | ${item.duration_ms} | ${item.detail} |`),
    "",
    "## Screenshot index",
    "",
    ...screenshots.map((item) => `- \`${item}\``),
    "",
    failure ? `Failure: ${redact(failure.message ?? failure)}` : "No failed or skipped required checks.",
    "",
    "Reports and screenshots use synthetic, sanitized UI data. Credentials, tokens, Cookies, Passkey challenges, database URLs, host paths, and real book contents are excluded.",
    "",
  ].join("\n");
  await writeFile(markdownPath, markdown, { mode: 0o600 });
  await writeFile(
    actionLogPath,
    [
      "Novel Platform v0.6.0 sanitized acceptance action log",
      "No command arguments, command output, credentials, tokens, Cookies, request bodies, or host paths are recorded.",
      "",
      ...actions.map((label) => `[ACTION] ${label}`),
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
}

async function main() {
  await mkdir(screenshotsDirectory, { recursive: true });
  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "novel-v060-ui-"));
  let preview;
  let browser;
  let core;
  let bundle;
  let failure;

  try {
    await step("Replay all 84 v0.5.0 criteria against v0.6.0", async () => {
      run("run inherited v0.5.0 acceptance core", process.execPath, [
        "scripts/acceptance/gates/v050.mjs",
      ], {
        env: {
          ...process.env,
          ACCEPTANCE_VERSION: "0.6.0",
          ACCEPTANCE_TAG: "v060-core",
          ACCEPTANCE_COMMAND: "pnpm acceptance -- v060",
        },
      });
      core = JSON.parse(await readFile(coreJsonPath, "utf8"));
      assert(core.status === "PASS", "Inherited v0.5.0 acceptance core did not pass");
      assert(core.criteria.length === 84, "Inherited criterion count changed");
      assert(core.criteria.every((item) => item.status === "PASS"), "Inherited criteria contain a failure");
    });

    await step("Generate v0.6.0 bundle evidence", async () => {
      run("build Web production bundle", "pnpm", ["build"]);
      run("write Web bundle report", process.execPath, ["scripts/reports/report-web-bundle.mjs"]);
      bundle = JSON.parse(
        await readFile(path.join(artifacts, "bundle-v060.json"), "utf8"),
      );
      assert(bundle.entry_budget.status === "PASS", "Initial entry exceeds the 200 kB gzip budget");
    });

    await step("Verify staging CSP supports Ant Design runtime styles", async () => {
      const nginxConfig = await readFile(
        path.join(root, "apps", "web", "nginx.staging.conf"),
        "utf8",
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

    const port = await freePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    await step("Start isolated Vite production preview", async () => {
      actions.push("start isolated Vite production preview");
      preview = spawn(
        "pnpm",
        [
          "--filter",
          "@novel-platform/web",
          "exec",
          "vite",
          "preview",
          "--host",
          "127.0.0.1",
          "--port",
          String(port),
        ],
        {
          cwd: root,
          env: process.env,
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
      await waitForUrl(baseUrl);
    });

    browser = await chromium.launch({ headless: true });
    const visualPages = [
      { slug: "login", role: "public", pathname: "/login", heading: "林间阅读室" },
      { slug: "library-admin", role: "admin", pathname: "/", heading: "整理馆藏，也继续上次的阅读。" },
      { slug: "library-reader", role: "reader", pathname: "/", heading: "安静阅读，也继续上次的位置。" },
      { slug: "book-detail", role: "admin", pathname: `/books/${ids.book}`, heading: bookDetail.canonical_title },
      { slug: "series", role: "admin", pathname: "/series", heading: "图书系列" },
      { slug: "upload-before", role: "admin", pathname: "/upload", heading: "上传与版本管理" },
      {
        slug: "upload-after",
        role: "admin",
        pathname: "/upload",
        heading: "上传与版本管理",
        setup: async (session) => {
          await session.page.getByLabel("选择 EPUB 或 TXT 文件").setInputFiles({
            name: "ui-sample.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("sanitized ui fixture"),
          });
          assert(session.state.inspectRequests === 0, "antd Upload automatically requested inspect");
          await session.page.getByRole("button", { name: "上传并预览" }).click();
          await session.page.getByRole("heading", { name: "确认导入" }).waitFor();
        },
      },
      { slug: "admin-dashboard", role: "admin", pathname: "/admin", heading: "林间阅读室" },
      { slug: "admin-readers", role: "admin", pathname: "/admin/readers", heading: "受邀阅读者" },
      { slug: "admin-security", role: "admin", pathname: "/admin/security", heading: "Passkey 与管理员会话" },
      { slug: "admin-site", role: "admin", pathname: "/admin/site", heading: "公开站点设置" },
      {
        slug: "admin-audit",
        role: "admin",
        pathname: "/admin/audit",
        heading: "安全审计",
        setup: async (session) => {
          if ((session.page.viewportSize()?.width ?? 0) <= 720) {
            assert(
              await session.page
                .getByText("表格可左右滑动，查看完整事件、来源和元数据。")
                .isVisible(),
              "Mobile audit table did not explain its controlled horizontal scroll",
            );
          }
        },
      },
    ];

    await step("Capture desktop and mobile sanitized visual evidence", async () => {
      for (const item of visualPages) {
        await capture(
          browser,
          baseUrl,
          item,
          { width: 1440, height: 900 },
          "desktop",
          item.setup,
        );
        await capture(
          browser,
          baseUrl,
          item,
          { width: 390, height: 844 },
          "mobile",
          item.setup,
        );
      }
      await readerVisuals(
        browser,
        baseUrl,
        { width: 1440, height: 900 },
        "desktop",
      );
      await readerVisuals(
        browser,
        baseUrl,
        { width: 390, height: 844 },
        "mobile",
      );
      assert(screenshots.length === 30, `Expected 30 screenshots, received ${screenshots.length}`);
    });

    await step("Verify 320, 768, and 1280 responsive layouts", async () => {
      for (const item of visualPages) {
        const session = await createPage(
          browser,
          baseUrl,
          item.role,
          { width: 320, height: 568 },
        );
        try {
          await openReady(session, item.pathname, item.heading);
          await assertLayout(session, `${item.slug}-320`);
        } finally {
          await finishPage(session, `${item.slug}-320`);
        }
      }
      for (const viewport of [
        { width: 768, height: 1024 },
        { width: 1280, height: 800 },
      ]) {
        for (const item of [
          visualPages[0],
          visualPages[1],
          visualPages[10],
        ]) {
          const session = await createPage(browser, baseUrl, item.role, viewport);
          try {
            await openReady(session, item.pathname, item.heading);
            await assertLayout(session, `${item.slug}-${viewport.width}`);
          } finally {
            await finishPage(session, `${item.slug}-${viewport.width}`);
          }
        }
      }
    });

    await step("Verify role navigation, confirmations, secrets, Upload and Reader interactions", async () => {
      await runRoleAndInteractionChecks(browser, baseUrl);
    });

    await step("Verify key accessible names and clean browser console", async () => {
      const login = await createPage(
        browser,
        baseUrl,
        "public",
        { width: 390, height: 844 },
      );
      try {
        await openReady(login, "/login", "林间阅读室");
        await login.page.getByRole("heading", { name: "登录" }).waitFor();
        await login.page.getByLabel("访问凭证").waitFor();
        await login.page.getByLabel("设备名称").waitFor();
        await login.page.getByRole("button", { name: "输入访问凭证" }).waitFor();
        await login.page.getByRole("button", { name: "使用安全设备登录" }).waitFor();
      } finally {
        await finishPage(login, "accessible-login");
      }
      assert(consoleErrors.length === 0, `Browser console errors: ${consoleErrors.join(" | ")}`);
    });
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  } finally {
    if (browser) await browser.close().catch(() => undefined);
    if (preview && !preview.killed) preview.kill("SIGTERM");
    await rm(temporaryRoot, { recursive: true, force: true });
  }

  const status = failure ? "FAIL" : "PASS";
  await writeReports(status, core, bundle, failure);
  const reportContents = [
    await readFile(markdownPath, "utf8"),
    await readFile(jsonPath, "utf8"),
    await readFile(actionLogPath, "utf8"),
  ].join("\n");
  if (
    /\bnpa_[A-Za-z0-9_-]{20,}\b/.test(reportContents)
    || /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/.test(reportContents)
    || reportContents.includes(root)
  ) {
    failure = new Error("A secret or host path appeared in the v0.6.0 reports");
    await writeReports("FAIL", core, bundle, failure);
  }
  if (failure) {
    process.stderr.write(`${redact(failure.message)}\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write(`v0.6.0 acceptance passed: ${markdownPath}\n`);
  }
}

await main();
