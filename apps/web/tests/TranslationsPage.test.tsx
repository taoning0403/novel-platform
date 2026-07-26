import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import type {
  TranslationRun,
  TranslationServiceStatus,
} from "../src/api/types";
import { TranslationsPage } from "../src/pages/TranslationsPage";

const service: TranslationServiceStatus = {
  enabled: true,
  available: true,
  version: "0.3.2",
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

const baseRun: TranslationRun = {
  id: "00000000-0000-4000-8000-000000000401",
  book_id: "00000000-0000-4000-8000-000000000402",
  book_title: "长篇测试小说",
  source_edition_id: "00000000-0000-4000-8000-000000000403",
  source_edition_title: "原文",
  source_revision: 2,
  source_sha256: "a".repeat(64),
  source_format: "txt",
  target_language: "en",
  edition_title: "英文机器译本",
  supersedes_edition_id: null,
  configuration: {
    service_version: "0.3.2",
    pipeline_key: "novel_txt_v1",
    pipeline_version: "1",
    provider_id: "mock",
    provider_model: "gpt-4.1-mini",
    credential_provider: "openai_compatible",
    credential_provider_name: "OpenAI",
    credential_base_url: "https://api.openai.com/v1",
    thinking_enabled: false,
  },
  creator: { display_name: "翻译者" },
  status: "running",
  progress: 0.4,
  generated_edition_id: null,
  generated_edition_title: null,
  remote_project_id: "project-1",
  remote_job_id: "job-1",
  remote_artifact_id: null,
  remote_request_id: "request-1",
  remote_status: "running",
  error_code: null,
  error_message: null,
  error_details: {},
  retry_count: 0,
  cleanup_status: "not_required",
  cleanup_error: null,
  available_actions: ["pause", "cancel", "sync"],
  can_preview_draft: false,
  can_publish: false,
  created_at: "2026-07-23T01:00:00Z",
  updated_at: "2026-07-23T01:02:00Z",
  started_at: "2026-07-23T01:01:00Z",
  completed_at: null,
  last_synced_at: "2026-07-23T01:02:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const zeroUsage = {
  all_time: {
    request_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  },
  current_month: {
    request_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  },
};

describe("TranslationsPage", () => {
  it("polls only while the selected active task is visible and stops at terminal state", async () => {
    vi.useFakeTimers();
    let visibility: DocumentVisibilityState = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    vi.spyOn(api, "translationServiceStatus").mockResolvedValue(service);
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      configured: true,
      provider: "openai_compatible",
      provider_name: "OpenAI",
      base_url: "https://api.openai.com/v1",
      model: "gpt-4.1-mini",
      thinking_enabled: false,
      version: 2,
      updated_at: "2026-07-23T01:00:00Z",
      usage: zeroUsage,
    });
    vi.spyOn(api, "listTranslationRuns").mockResolvedValue([baseRun]);
    const completed: TranslationRun = {
      ...baseRun,
      status: "succeeded",
      progress: 1,
      generated_edition_id: "00000000-0000-4000-8000-000000000404",
      generated_edition_title: baseRun.edition_title,
      remote_status: "succeeded",
      available_actions: [],
      can_preview_draft: true,
      completed_at: "2026-07-23T01:03:00Z",
    };
    const sync = vi.spyOn(api, "runTranslationAction").mockResolvedValue(completed);

    render(
      <MemoryRouter initialEntries={[`/translations?run=${baseRun.id}`]}>
        <TranslationsPage />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: baseRun.edition_title })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(sync).not.toHaveBeenCalled();

    await act(async () => {
      visibility = "visible";
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(sync).toHaveBeenCalledTimes(1);
    expect(sync).toHaveBeenCalledWith(baseRun.id, "sync");
    expect(screen.getAllByText("草稿已生成")).toHaveLength(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("requires confirmation before an admin publishes the generated draft", async () => {
    const generatedId = "00000000-0000-4000-8000-000000000405";
    const generated: TranslationRun = {
      ...baseRun,
      status: "succeeded",
      progress: 1,
      generated_edition_id: generatedId,
      generated_edition_title: baseRun.edition_title,
      available_actions: [],
      can_preview_draft: true,
      can_publish: true,
      completed_at: "2026-07-23T01:03:00Z",
    };
    const published = { ...generated, can_preview_draft: false, can_publish: false };
    vi.spyOn(api, "translationServiceStatus").mockResolvedValue(service);
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      configured: true,
      provider: "kimi",
      provider_name: "Kimi",
      base_url: "https://api.moonshot.cn/v1",
      model: "kimi-k2.5",
      thinking_enabled: true,
      version: 2,
      updated_at: "2026-07-23T01:00:00Z",
      usage: zeroUsage,
    });
    vi.spyOn(api, "listTranslationRuns").mockResolvedValue([generated]);
    const patch = vi.spyOn(api, "patchEdition").mockResolvedValue({} as never);
    vi.spyOn(api, "getTranslationRun").mockResolvedValue(published);

    render(
      <MemoryRouter initialEntries={[`/translations?run=${generated.id}`]}>
        <TranslationsPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "审核并发布" }));
    expect(screen.getByText(/新任务使用 Kimi · kimi-k2.5 · 思考模式 · 凭据 v2/))
      .toBeInTheDocument();
    expect(screen.getByText("绑定 Provider").closest(".ant-descriptions-item"))
      .toHaveTextContent("OpenAI");
    expect(screen.getByText("思考模式", { selector: "span" }).closest(".ant-descriptions-item"))
      .toHaveTextContent("关闭");
    expect(screen.getByText("API Base URL").closest(".ant-descriptions-item"))
      .toHaveTextContent("https://api.openai.com/v1");
    expect(patch).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      generated.book_id,
      generatedId,
      { status: "ready" },
    ));
    expect(screen.getByRole("link", { name: "管理我的凭据" })).toHaveAttribute(
      "href",
      "/settings/provider-credential",
    );
    expect(api.getTranslationRun).toHaveBeenCalledWith(generated.id);
    expect(await screen.findAllByText("译本已发布")).toHaveLength(2);
  });
});
