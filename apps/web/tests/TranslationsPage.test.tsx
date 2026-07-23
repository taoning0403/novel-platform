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
    service_version: "0.3.1",
    pipeline_key: "novel_txt_v1",
    pipeline_version: "1",
    provider_id: "mock",
    provider_model: "mock-v1",
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

describe("TranslationsPage", () => {
  it("polls only while the selected active task is visible and stops at terminal state", async () => {
    vi.useFakeTimers();
    let visibility: DocumentVisibilityState = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    vi.spyOn(api, "translationServiceStatus").mockResolvedValue(service);
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
    vi.spyOn(api, "listTranslationRuns").mockResolvedValue([generated]);
    const patch = vi.spyOn(api, "patchEdition").mockResolvedValue({} as never);
    vi.spyOn(api, "getTranslationRun").mockResolvedValue(published);

    render(
      <MemoryRouter initialEntries={[`/translations?run=${generated.id}`]}>
        <TranslationsPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "审核并发布" }));
    expect(patch).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      generated.book_id,
      generatedId,
      { status: "ready" },
    ));
    expect(api.getTranslationRun).toHaveBeenCalledWith(generated.id);
    expect(await screen.findAllByText("译本已发布")).toHaveLength(2);
  });
});
