import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../src/api/client";
import type { BookDetail, ImportRecord } from "../src/api/types";
import { UploadPage } from "../src/pages/UploadPage";

const contributor = {
  display_name: "测试用户",
};

const resourcePermissions = {
  can_edit: true,
  can_delete: true,
  can_upload_edition: true,
  can_translate: true,
};

const book: BookDetail = {
  id: "00000000-0000-0000-0000-000000000010",
  canonical_title: "目标图书",
  canonical_author: null,
  description: null,
  contributor,
  ...resourcePermissions,
  metadata: {},
  cover_url: null,
  cover_thumbnail_url: null,
  edition_count: 0,
  editions: [],
  created_at: "2026-07-13T00:00:00Z",
  updated_at: "2026-07-13T00:00:00Z",
};

const inspection: ImportRecord = {
  id: "00000000-0000-0000-0000-000000000030",
  status: "ready",
  operation: "add_edition",
  original_filename: "独立译文.txt",
  file_format: "txt",
  size_bytes: 32,
  target_book_id: book.id,
  target_edition_id: null,
  text_encoding: "cp932",
  content_item_count: 1,
  metadata_preview: { title: "自动标题" },
  warnings: [],
  cover_available: false,
  cover_preview_url: null,
  error_code: null,
  error_message: null,
  created_at: "2026-07-13T00:00:00Z",
  started_at: "2026-07-13T00:00:00Z",
  completed_at: "2026-07-13T00:00:01Z",
};

afterEach(() => vi.restoreAllMocks());

describe("UploadPage", () => {
  it("inspects an explicitly encoded TXT and commits an independent AI translation", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([{
      id: book.id,
      canonical_title: book.canonical_title,
      canonical_author: null,
      description: null,
      contributor,
      ...resourcePermissions,
      edition_count: 0,
      languages: [],
      file_formats: [],
      preferred_edition_id: null,
      preferred_edition_title: null,
      reading_status: "not_started",
      reading_progress: 0,
      cover_thumbnail_url: null,
      created_at: book.created_at,
      updated_at: book.updated_at,
    }]);
    vi.spyOn(api, "getBook").mockResolvedValue(book);
    const inspect = vi.spyOn(api, "inspectImport").mockImplementation((options) => {
      options.onProgress?.(100);
      return Promise.resolve(inspection);
    });
    const commit = vi.spyOn(api, "commitImport").mockResolvedValue({
      upload: { ...inspection, status: "succeeded" },
      book,
      edition: {
        id: "00000000-0000-0000-0000-000000000040",
        book_id: book.id,
        title: "AI 日译中",
        language: "zh-CN",
        content_role: "translation",
        translation_origin: "ai",
        creation_method: "uploaded",
        contributor,
        ...resourcePermissions,
        source_edition_id: null,
        supersedes_edition_id: null,
        status: "ready",
        revision: 1,
        metadata: {},
        current_file: null,
        reader_available: false,
        reading_status: "not_started",
        reading_progress: 0,
        last_read_at: null,
        created_at: "2026-07-13T00:00:00Z",
        updated_at: "2026-07-13T00:00:00Z",
      },
    });

    render(
      <MemoryRouter initialEntries={[`/upload?mode=add_edition&bookId=${book.id}`]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/books/:bookId" element={<p>导入完成</p>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTitle("目标图书");
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [new File(["本文"], "独立译文.txt", { type: "text/plain" })] },
    });
    expect(inspect).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByLabelText("TXT 编码"));
    fireEvent.click(screen.getByTitle("Shift-JIS / CP932"));
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    expect(await screen.findByRole("heading", { name: "确认导入" })).toBeInTheDocument();
    expect(inspect).toHaveBeenCalledWith(expect.objectContaining({
      operation: "add_edition",
      textEncoding: "cp932",
      targetBookId: book.id,
    }));

    fireEvent.click(screen.getByLabelText("AI 译文"));
    fireEvent.change(screen.getByLabelText("Edition 名称"), { target: { value: "AI 日译中" } });
    fireEvent.change(screen.getByLabelText("语言"), { target: { value: "zh-CN" } });
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
    await waitFor(() => expect(commit).toHaveBeenCalledWith(
      inspection.id,
      expect.objectContaining({
        content_role: "translation",
        translation_origin: "ai",
        source_edition_id: null,
        edition_title: "AI 日译中",
      }),
    ));
    expect(await screen.findByText("导入完成")).toBeInTheDocument();
  });

  it("warns explicitly before replacing an EPUB Edition with TXT", async () => {
    const edition = {
      id: "00000000-0000-0000-0000-000000000050",
      book_id: book.id,
      title: "现有 EPUB",
      language: "ja",
      content_role: "source" as const,
      translation_origin: null,
      creation_method: "uploaded" as const,
      contributor,
      ...resourcePermissions,
      source_edition_id: null,
      supersedes_edition_id: null,
      status: "ready" as const,
      revision: 1,
      metadata: {},
      current_file: {
        revision: 1,
        file_format: "epub" as const,
        original_filename: "old.epub",
        media_type: "application/epub+zip",
        size_bytes: 100,
        text_encoding: null,
        content_item_count: 1,
        uploaded_at: "2026-07-13T00:00:00Z",
        download_url: `/api/v1/editions/00000000-0000-0000-0000-000000000050/file`,
      },
      reader_available: true,
      reading_status: "not_started" as const,
      reading_progress: 0,
      last_read_at: null,
      created_at: "2026-07-13T00:00:00Z",
      updated_at: "2026-07-13T00:00:00Z",
    };
    const replacementBook = { ...book, edition_count: 1, editions: [edition] };
    vi.spyOn(api, "listBooks").mockResolvedValue([{
      id: book.id,
      canonical_title: book.canonical_title,
      canonical_author: null,
      description: null,
      contributor,
      ...resourcePermissions,
      edition_count: 1,
      languages: ["ja"],
      file_formats: ["epub"],
      preferred_edition_id: edition.id,
      preferred_edition_title: edition.title,
      reading_status: "not_started",
      reading_progress: 0,
      cover_thumbnail_url: null,
      created_at: book.created_at,
      updated_at: book.updated_at,
    }]);
    vi.spyOn(api, "getBook").mockResolvedValue(replacementBook);
    vi.spyOn(api, "inspectImport").mockResolvedValue({
      ...inspection,
      operation: "replace_edition_file",
      target_edition_id: edition.id,
    });
    const commit = vi.spyOn(api, "commitImport").mockResolvedValue({
      upload: {
        ...inspection,
        operation: "replace_edition_file",
        target_edition_id: edition.id,
        status: "succeeded",
      },
      book,
      edition: {
        ...edition,
        current_file: {
          ...edition.current_file,
          revision: 2,
          file_format: "txt",
          original_filename: "new.txt",
          media_type: "text/plain",
        },
      },
    });
    render(
      <MemoryRouter initialEntries={[
        `/upload?mode=replace_edition_file&bookId=${book.id}&editionId=${edition.id}`,
      ]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/books/:bookId" element={<p>替换完成</p>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTitle("现有 EPUB · EPUB");
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [new File(["正文"], "new.txt", { type: "text/plain" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    expect(await screen.findByText(/格式将从 EPUB 改为 TXT/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认替换文件" }));
    fireEvent.click(screen.getByRole("button", { name: "确认替换" }));
    await waitFor(() => expect(commit).toHaveBeenCalledWith(
      inspection.id,
      { use_extracted_cover: false },
    ));
    expect(await screen.findByText("替换完成")).toBeInTheDocument();
  });

  it("lets the user delete a failed inspection record and its temporary file", async () => {
    const failedImportId = "00000000-0000-0000-0000-000000000060";
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    vi.spyOn(api, "inspectImport").mockRejectedValue(new ApiError(
      "EPUB 文件结构无效。",
      "invalid_epub",
      422,
      { import_id: failedImportId },
    ));
    const deleteImport = vi.spyOn(api, "deleteImport").mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [new File(["not a zip"], "损坏.epub", { type: "application/epub+zip" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("EPUB 文件结构无效");
    fireEvent.click(screen.getByRole("button", {
      name: "删除 损坏.epub 的失败上传记录与临时文件",
    }));

    await waitFor(() => expect(deleteImport).toHaveBeenCalledWith(failedImportId));
    expect(
      await screen.findByText(
        "已删除 损坏.epub 的失败上传记录和临时文件。",
      ),
    ).toBeInTheDocument();
  });

  it("retains the selected file and explains the configured upload limit", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    const inspect = vi.spyOn(api, "inspectImport");
    const oversized = new File(["x"], "oversized.txt", { type: "text/plain" });
    Object.defineProperty(oversized, "size", { value: 100 * 1024 * 1024 + 1 });

    render(
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [oversized] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "所选文件超过 100 MiB 的单文件上限",
    );
    expect(screen.getByText("oversized.txt")).toBeInTheDocument();
    expect(inspect).not.toHaveBeenCalled();
  });

  it("invalidates an inspected preview when its target Book changes", async () => {
    const otherBook: BookDetail = {
      ...book,
      id: "00000000-0000-0000-0000-000000000011",
      canonical_title: "另一本目标图书",
    };
    vi.spyOn(api, "listBooks").mockResolvedValue([book, otherBook].map((item) => ({
      id: item.id,
      canonical_title: item.canonical_title,
      canonical_author: item.canonical_author,
      description: item.description,
      contributor,
      ...resourcePermissions,
      edition_count: item.edition_count,
      languages: [],
      file_formats: [],
      preferred_edition_id: null,
      preferred_edition_title: null,
      reading_status: "not_started" as const,
      reading_progress: 0,
      cover_thumbnail_url: null,
      created_at: item.created_at,
      updated_at: item.updated_at,
    })));
    vi.spyOn(api, "getBook").mockImplementation((bookId) => Promise.resolve(
      bookId === otherBook.id ? otherBook : book,
    ));
    const inspect = vi.spyOn(api, "inspectImport").mockResolvedValue(inspection);

    render(
      <MemoryRouter initialEntries={[`/upload?mode=add_edition&bookId=${book.id}`]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTitle("目标图书");
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [new File(["本文"], "独立译文.txt", { type: "text/plain" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    expect(await screen.findByRole("heading", { name: "确认导入" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("目标 Book"));
    fireEvent.click(screen.getByTitle("另一本目标图书"));
    expect(screen.queryByRole("heading", { name: "确认导入" })).not.toBeInTheDocument();
    expect(screen.getByText("独立译文.txt")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    await waitFor(() => expect(inspect).toHaveBeenLastCalledWith(expect.objectContaining({
      targetBookId: otherBook.id,
    })));
  });

  it("requires a fresh inspection after the TXT encoding changes", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    const inspect = vi.spyOn(api, "inspectImport").mockResolvedValue({
      ...inspection,
      operation: "create_book",
      target_book_id: null,
      text_encoding: "utf-8",
    });

    render(
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: { files: [new File(["本文"], "正文.txt", { type: "text/plain" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    expect(await screen.findByRole("heading", { name: "确认导入" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("TXT 编码"));
    fireEvent.click(screen.getByTitle("Shift-JIS / CP932"));
    expect(screen.queryByRole("heading", { name: "确认导入" })).not.toBeInTheDocument();
    expect(screen.getByText("正文.txt")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    await waitFor(() => expect(inspect).toHaveBeenLastCalledWith(expect.objectContaining({
      textEncoding: "cp932",
    })));
  });

  it("invalidates an inspected preview when the selected file changes", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    vi.spyOn(api, "inspectImport").mockResolvedValue({
      ...inspection,
      operation: "create_book",
      target_book_id: null,
    });

    render(
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: {
        files: [new File(["正文"], "第一版.txt", { type: "text/plain" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    expect(
      await screen.findByRole("heading", { name: "确认导入" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: {
        files: [new File(["新正文"], "第二版.txt", { type: "text/plain" })],
      },
    });
    expect(
      screen.queryByRole("heading", { name: "确认导入" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("第二版.txt")).toBeInTheDocument();
  });

  it("preserves inspected metadata and the selected file after commit failure", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    vi.spyOn(api, "inspectImport").mockResolvedValue({
      ...inspection,
      operation: "create_book",
      target_book_id: null,
      original_filename: "待重试.txt",
      metadata_preview: { title: "自动标题", language: "zh-CN" },
    });
    vi.spyOn(api, "commitImport").mockRejectedValue(
      new ApiError("暂时无法保存，请重试。", "temporary_failure", 500),
    );

    render(
      <MemoryRouter initialEntries={["/upload"]}>
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("选择 EPUB 或 TXT 文件"), {
      target: {
        files: [new File(["正文"], "待重试.txt", { type: "text/plain" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "上传并预览" }));
    const title = await screen.findByLabelText("书名");
    fireEvent.change(title, { target: { value: "保留的人工书名" } });
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时无法保存，请重试。",
    );
    expect(title).toHaveValue("保留的人工书名");
    expect(screen.getAllByText("待重试.txt").length).toBeGreaterThan(0);
  });
});
