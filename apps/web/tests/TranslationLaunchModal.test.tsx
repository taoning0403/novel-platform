import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import type {
  BookDetail,
  Edition,
  TranslationRun,
  TranslationServiceStatus,
} from "../src/api/types";
import { TranslationLaunchModal } from "../src/features/translations/TranslationLaunchModal";

const source: Edition = {
  id: "00000000-0000-4000-8000-000000000101",
  book_id: "00000000-0000-4000-8000-000000000100",
  title: "测试原文",
  language: "zh-CN",
  content_role: "source",
  translation_origin: null,
  creation_method: "uploaded",
  contributor: { display_name: "原文上传者" },
  can_edit: false,
  can_delete: false,
  can_upload_edition: false,
  can_translate: true,
  source_edition_id: null,
  supersedes_edition_id: null,
  status: "ready",
  revision: 1,
  metadata: {},
  current_file: {
    revision: 2,
    file_format: "txt",
    original_filename: "source.txt",
    media_type: "text/plain",
    size_bytes: 100,
    text_encoding: "utf-8",
    content_item_count: 1,
    uploaded_at: "2026-07-23T01:00:00Z",
    download_url: null,
  },
  reader_available: true,
  reading_status: "not_started",
  reading_progress: 0,
  last_read_at: null,
  created_at: "2026-07-23T01:00:00Z",
  updated_at: "2026-07-23T01:00:00Z",
};

const book = {
  id: source.book_id,
  canonical_title: "测试小说",
  canonical_author: "作者",
  description: null,
  contributor: { display_name: "作品上传者" },
  can_edit: false,
  can_delete: false,
  can_upload_edition: false,
  can_translate: true,
  metadata: {},
  cover_url: null,
  cover_thumbnail_url: null,
  edition_count: 1,
  editions: [source],
  created_at: "2026-07-23T01:00:00Z",
  updated_at: "2026-07-23T01:00:00Z",
} as BookDetail;

const service: TranslationServiceStatus = {
  enabled: true,
  available: true,
  version: "0.3.1",
  pipeline_key: "novel_txt_v1",
  pipeline_version: "1",
  provider_id: "mock",
  provider_name: "Mock Provider",
  provider_model: "mock-v1",
  provider_offline: true,
  idempotency_required: true,
  error_code: null,
  error_message: null,
};

const createdRun = {
  id: "00000000-0000-4000-8000-000000000201",
} as TranslationRun;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("TranslationLaunchModal", () => {
  it("submits only the narrow translation request and keeps service choices server-owned", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "00000000-0000-4000-8000-000000000301",
      getRandomValues: window.crypto.getRandomValues.bind(window.crypto),
    });
    vi.spyOn(api, "translationServiceStatus").mockResolvedValue(service);
    const create = vi.spyOn(api, "createTranslationRun").mockResolvedValue(createdRun);
    const onCreated = vi.fn();

    render(
      <TranslationLaunchModal
        book={book}
        edition={source}
        open
        onClose={vi.fn()}
        onCreated={onCreated}
      />,
    );

    expect(await screen.findByText(/Mock Provider · mock-v1/)).toBeInTheDocument();
    expect(screen.getByText(/正文会发送到管理员配置的私有翻译服务/)).toBeInTheDocument();
    expect(screen.getByText("f2 · TXT")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("目标语言"), { target: { value: "ja" } });
    fireEvent.change(screen.getByLabelText("输出 Edition 名称"), {
      target: { value: "日文机器译本" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建翻译任务" }));

    await waitFor(() => expect(create).toHaveBeenCalledWith(
      book.id,
      source.id,
      {
        target_language: "ja",
        edition_title: "日文机器译本",
        client_request_id: "00000000-0000-4000-8000-000000000301",
      },
    ));
    const payload = create.mock.calls[0][2] as Record<string, unknown>;
    expect(payload).not.toHaveProperty("provider_id");
    expect(payload).not.toHaveProperty("profile_id");
    expect(payload).not.toHaveProperty("base_url");
    expect(payload).not.toHaveProperty("download_url");
    expect(onCreated).toHaveBeenCalledWith(createdRun);
  });
});
