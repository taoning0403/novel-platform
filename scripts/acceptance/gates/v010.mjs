import { execFileSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const baseUrlArgument = process.argv.find((argument) => argument.startsWith("--base-url="));
const baseUrl = (
  baseUrlArgument?.slice("--base-url=".length) ??
  process.env.API_BASE_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");
const skipRestart = process.argv.includes("--skip-restart");
const runId = new Date().toISOString().replaceAll(/[:.]/g, "-");
let accessToken = null;

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function request(method, route, body, expectedStatus = 200) {
  const headers = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (accessToken !== null) headers.authorization = `Bearer ${accessToken}`;
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  assert(
    response.status === expectedStatus,
    `${method} ${route}: expected ${expectedStatus}, got ${response.status}: ${JSON.stringify(payload)}`,
  );
  return payload;
}

async function expectError(method, route, body, status, code) {
  const payload = await request(method, route, body, status);
  assert(payload?.error?.code === code, `${route}: expected error code ${code}`);
  assert(typeof payload.error.message === "string", `${route}: missing safe error message`);
  assert(payload.error.details && typeof payload.error.details === "object", `${route}: missing details`);
}

async function waitUntilReady(timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/health/ready`);
      if (response.ok) return;
    } catch {
      // Containers may be between process start and socket readiness.
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(`API did not become ready within ${timeoutMs} ms`);
}

async function createEdition(bookId, body) {
  return request("POST", `/api/v1/books/${bookId}/editions`, body, 201);
}

async function main() {
  await waitUntilReady();
  assert((await request("GET", "/api/v1/health/live")).status === "ok", "live probe failed");
  assert((await request("GET", "/api/v1/health/ready")).status === "ok", "ready probe failed");

  const username = process.env.ACCEPTANCE_USERNAME ?? "v010-admin";
  let password = process.env.ACCEPTANCE_PASSWORD;
  const setup = await request("GET", "/api/v1/setup/status");
  if (setup.setup_required) {
    password ??= randomBytes(24).toString("base64url");
    await request(
      "POST",
      "/api/v1/setup/initialize",
      {
        setup_token:
          process.env.AUTH_SETUP_TOKEN ?? "development-setup-token-change-me",
        username,
        display_name: "v0.1.0 回归管理员",
        password,
      },
      201,
    );
  } else {
    assert(password, "ACCEPTANCE_PASSWORD is required for an initialized v0.2.0 stack");
  }
  const login = await request("POST", "/api/v1/auth/login", {
    username,
    password,
    refresh_token_delivery: "body",
    device: {
      client_instance_id: randomUUID(),
      name: "v0.1.0 回归验收",
      platform: "web",
      app_version: "0.2.0",
    },
  });
  accessToken = login.access_token;

  const book = await request(
    "POST",
    "/api/v1/books",
    {
      canonical_title: `v0.1.0 验收小说 ${runId}`,
      canonical_author: "Codex Acceptance",
      description: "持久化与版本关系自动验收",
    },
    201,
  );
  const otherBook = await request(
    "POST",
    "/api/v1/books",
    { canonical_title: `交叉引用对照 ${runId}` },
    201,
  );

  const source = await createEdition(book.id, {
    title: "日文原版",
    language: "ja",
    content_role: "source",
    translation_origin: null,
    creation_method: "uploaded",
    status: "ready",
    revision: 1,
  });
  const generatedAi = await createEdition(book.id, {
    title: "中文 AI 译文",
    language: "zh-CN",
    content_role: "translation",
    translation_origin: "ai",
    creation_method: "generated",
    source_edition_id: source.id,
    status: "ready",
    revision: 1,
  });
  const externalAi = await createEdition(book.id, {
    title: "外部 AI 中文译文",
    language: "zh-CN",
    content_role: "translation",
    translation_origin: "ai",
    creation_method: "uploaded",
    source_edition_id: null,
    status: "ready",
    revision: 1,
  });
  const human = await createEdition(book.id, {
    title: "中文人工译文",
    language: "zh-CN",
    content_role: "translation",
    translation_origin: "human",
    creation_method: "uploaded",
    source_edition_id: null,
    status: "ready",
    revision: 1,
  });
  const mixed = await createEdition(book.id, {
    title: "中文校订版",
    language: "zh-CN",
    content_role: "translation",
    translation_origin: "mixed",
    creation_method: "edited",
    source_edition_id: source.id,
    supersedes_edition_id: generatedAi.id,
    status: "ready",
    revision: 1,
  });
  const otherSource = await createEdition(otherBook.id, {
    title: "英文原版",
    language: "en",
    content_role: "source",
    translation_origin: null,
    creation_method: "uploaded",
    status: "ready",
    revision: 1,
  });

  assert(externalAi.source_edition_id === null, "external AI translation must be independent");
  assert(human.source_edition_id === null, "human translation must be independent");

  const attached = await request(
    "PATCH",
    `/api/v1/books/${book.id}/editions/${externalAi.id}`,
    { source_edition_id: source.id },
  );
  assert(attached.source_edition_id === source.id, "late source attachment failed");
  const detached = await request(
    "PATCH",
    `/api/v1/books/${book.id}/editions/${externalAi.id}`,
    { source_edition_id: null, status: "archived" },
  );
  assert(detached.source_edition_id === null, "source detachment failed");
  assert(detached.status === "archived", "archive update failed");

  await expectError(
    "POST",
    `/api/v1/books/${book.id}/editions`,
    {
      title: "错误原文",
      language: "ja",
      content_role: "source",
      translation_origin: "ai",
      creation_method: "uploaded",
    },
    400,
    "invalid_translation_origin",
  );
  await expectError(
    "POST",
    `/api/v1/books/${book.id}/editions`,
    {
      title: "缺少来源类型",
      language: "zh-CN",
      content_role: "translation",
      translation_origin: null,
      creation_method: "uploaded",
    },
    400,
    "invalid_translation_origin",
  );
  await expectError(
    "PATCH",
    `/api/v1/books/${book.id}/editions/${human.id}`,
    { source_edition_id: generatedAi.id },
    409,
    "source_edition_must_be_source",
  );
  await expectError(
    "PATCH",
    `/api/v1/books/${book.id}/editions/${human.id}`,
    { source_edition_id: otherSource.id },
    409,
    "cross_book_edition_reference",
  );
  await expectError(
    "PATCH",
    `/api/v1/books/${book.id}/editions/${human.id}`,
    { supersedes_edition_id: human.id },
    400,
    "edition_cannot_reference_itself",
  );

  const edition = await request("GET", `/api/v1/books/${book.id}/editions/${mixed.id}`);
  assert(edition.supersedes_edition_id === generatedAi.id, "supersedes relationship was lost");
  const detail = await request("GET", `/api/v1/books/${book.id}`);
  assert(detail.edition_count === 5, `expected 5 editions, got ${detail.edition_count}`);
  assert(detail.editions[0].content_role === "source", "source edition must sort first");

  if (!skipRestart) {
    console.log("Restarting PostgreSQL and API to verify named-volume persistence…");
    execFileSync("docker", ["compose", "restart", "postgres", "server"], { stdio: "inherit" });
    await waitUntilReady();
    const persisted = await request("GET", `/api/v1/books/${book.id}`);
    const persistedIds = new Set(persisted.editions.map((item) => item.id));
    for (const id of [source.id, generatedAi.id, externalAi.id, human.id, mixed.id]) {
      assert(persistedIds.has(id), `edition ${id} was not persisted across restart`);
    }
  }

  const report = {
    version: "0.1.0",
    completed_at: new Date().toISOString(),
    base_url: baseUrl,
    restart_verified: !skipRestart,
    book_id: book.id,
    edition_ids: [source.id, generatedAi.id, externalAi.id, human.id, mixed.id],
    checks: {
      independent_translations: true,
      late_source_attachment: true,
      source_detachment: true,
      mixed_supersedes_ai: true,
      invalid_relationships_rejected: true,
      persistence: !skipRestart,
    },
  };
  await mkdir(path.resolve("artifacts"), { recursive: true });
  await writeFile(
    path.resolve("artifacts", "acceptance-v010.json"),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  console.log(`v0.1.0 acceptance passed for Book ${book.id}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
