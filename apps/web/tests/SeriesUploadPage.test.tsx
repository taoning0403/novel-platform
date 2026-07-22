import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../src/api/client";
import type { ImportCommitResult, ImportRecord, SeriesDetail } from "../src/api/types";
import { SeriesUploadPage } from "../src/pages/SeriesUploadPage";

const seriesId = "00000000-0000-4000-8000-000000000401";
const importId = "00000000-0000-4000-8000-000000000402";
const bookId = "00000000-0000-4000-8000-000000000403";
const editionId = "00000000-0000-4000-8000-000000000404";

const series: SeriesDetail = {
  id: seriesId,
  name: "测试系列",
  description: null,
  book_count: 0,
  books: [],
  created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z",
};

const inspection: ImportRecord = {
  id: importId,
  status: "ready",
  operation: "create_book",
  original_filename: "第一本.txt",
  file_format: "txt",
  size_bytes: 16,
  target_book_id: null,
  target_edition_id: null,
  text_encoding: "utf-8",
  content_item_count: 1,
  metadata_preview: { title: "第一本", language: "zh-CN" },
  warnings: [],
  cover_available: false,
  cover_preview_url: null,
  error_code: null,
  error_message: null,
  created_at: "2026-07-14T00:00:00Z",
  started_at: "2026-07-14T00:00:00Z",
  completed_at: "2026-07-14T00:00:01Z",
};

const committed: ImportCommitResult = {
  upload: { ...inspection, status: "succeeded" },
  book: {
    id: bookId,
    canonical_title: "第一本",
    canonical_author: null,
    description: null,
    metadata: {},
    cover_url: null,
    cover_thumbnail_url: null,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
  },
  edition: {
    id: editionId,
    book_id: bookId,
    title: "第一本",
    language: "zh-CN",
    content_role: "source",
    translation_origin: null,
    creation_method: "uploaded",
    source_edition_id: null,
    supersedes_edition_id: null,
    status: "ready",
    revision: 1,
    metadata: {},
    current_file: null,
    reader_available: true,
    reading_status: "not_started",
    reading_progress: 0,
    last_read_at: null,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
  },
};

afterEach(() => vi.restoreAllMocks());

describe("SeriesUploadPage", () => {
  it("keeps successful books when another file in the batch fails", async () => {
    vi.spyOn(api, "getSeries").mockResolvedValue(series);
    const inspect = vi.spyOn(api, "inspectImport")
      .mockImplementationOnce((options) => {
        options.onProgress?.(100);
        return Promise.resolve(inspection);
      })
      .mockRejectedValueOnce(new ApiError("第二本解析失败", "invalid_txt", 422));
    const commit = vi.spyOn(api, "commitImport").mockResolvedValue(committed);

    render(
      <MemoryRouter
        initialEntries={[`/series/${seriesId}/upload`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes><Route path="/series/:seriesId/upload" element={<SeriesUploadPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "上传到「测试系列」" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("选择一个或多个 EPUB 或 TXT 文件"), {
      target: {
        files: [
          new File(["第一本"], "第一本.txt", { type: "text/plain" }),
          new File(["第二本"], "第二本.txt", { type: "text/plain" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "批量上传 2 本" }));

    expect(await screen.findByText("已上传并加入系列")).toBeInTheDocument();
    expect(await screen.findByText("第二本解析失败（invalid_txt）")).toBeInTheDocument();
    expect(inspect).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(commit).toHaveBeenCalledWith(
      importId,
      expect.objectContaining({
        series_id: seriesId,
        canonical_title: "第一本",
        language: "zh-CN",
      }),
    ));
    expect(screen.getByRole("link", { name: "打开图书 →" })).toHaveAttribute(
      "href",
      `/books/${bookId}`,
    );
  });

  it("retries only the failed file when its retry button is clicked", async () => {
    vi.spyOn(api, "getSeries").mockResolvedValue(series);
    const inspect = vi.spyOn(api, "inspectImport")
      .mockRejectedValueOnce(new ApiError("解析失败", "invalid_txt", 422))
      .mockImplementationOnce((options) => {
        options.onProgress?.(100);
        return Promise.resolve(inspection);
      });
    const commit = vi.spyOn(api, "commitImport").mockResolvedValue(committed);

    render(
      <MemoryRouter
        initialEntries={[`/series/${seriesId}/upload`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes><Route path="/series/:seriesId/upload" element={<SeriesUploadPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "上传到「测试系列」" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("选择一个或多个 EPUB 或 TXT 文件"), {
      target: { files: [new File(["第一本"], "第一本.txt", { type: "text/plain" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传这本图书" }));
    expect(await screen.findByText("解析失败（invalid_txt）")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("已上传并加入系列")).toBeInTheDocument();
    expect(inspect).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(commit).toHaveBeenCalledWith(
      importId,
      expect.objectContaining({ series_id: seriesId, canonical_title: "第一本" }),
    ));
  });
});
