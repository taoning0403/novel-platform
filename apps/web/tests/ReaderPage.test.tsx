import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../src/api/client";
import type { ReaderOpen, ReaderSection, ReadingProgress } from "../src/api/types";
import { ReaderPage } from "../src/pages/ReaderPage";

const editionId = "00000000-0000-4000-8000-000000000101";
const secondEditionId = "00000000-0000-4000-8000-000000000102";

const progress: ReadingProgress = {
  edition_id: editionId,
  status: "reading",
  section_id: "section-2",
  block_id: null,
  section_progress: 0.25,
  overall_progress: 0.625,
  edition_file_revision: 1,
  version: 3,
  last_read_at: "2026-07-14T01:00:00Z",
};

const opened: ReaderOpen = {
  book: {
    id: "00000000-0000-4000-8000-000000000201",
    canonical_title: "跨设备测试书",
    canonical_author: "作者",
    description: null,
    metadata: {},
    cover_url: null,
    cover_thumbnail_url: null,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
  },
  edition: {
    id: editionId,
    book_id: "00000000-0000-4000-8000-000000000201",
    title: "原文",
    language: "ja",
    content_role: "source",
    translation_origin: null,
    file_format: "epub",
    reading_status: "reading",
    reading_progress: 0.625,
    last_read_at: "2026-07-14T01:00:00Z",
  },
  available_editions: [
    {
      id: editionId,
      book_id: "00000000-0000-4000-8000-000000000201",
      title: "原文",
      language: "ja",
      content_role: "source",
      translation_origin: null,
      file_format: "epub",
      reading_status: "reading",
      reading_progress: 0.625,
      last_read_at: "2026-07-14T01:00:00Z",
    },
    {
      id: secondEditionId,
      book_id: "00000000-0000-4000-8000-000000000201",
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
    file_revision: 1,
    sections: [
      { id: "section-1", index: 0, title: "第一节" },
      { id: "section-2", index: 1, title: "第二节" },
    ],
    toc: [
      { title: "第一节", section_id: "section-1" },
      { title: "第二节", section_id: "section-2" },
    ],
  },
  progress,
  settings: {
    font_size: 18,
    line_height: 1.8,
    content_width: 760,
    font_family: "serif",
    theme: "sepia",
    updated_at: "2026-07-14T01:00:00Z",
  },
};

const section: ReaderSection = {
  id: "section-2",
  index: 1,
  title: "第二节",
  html: '<p data-reader-block="block-2">正文第二节</p>',
  resource_ids: [],
};

function renderReader() {
  return render(
    <MemoryRouter
      initialEntries={[`/read/${editionId}`]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes><Route path="/read/:editionId" element={<ReaderPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe("ReaderPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "openReader").mockResolvedValue(opened);
    vi.spyOn(api, "getReaderSection").mockResolvedValue(section);
    vi.spyOn(api, "getReaderResource").mockRejectedValue(new Error("not used"));
    vi.spyOn(api, "patchReaderSettings").mockImplementation((payload) => Promise.resolve({
      font_size: payload.font_size ?? opened.settings.font_size,
      line_height: payload.line_height ?? opened.settings.line_height,
      content_width: payload.content_width ?? opened.settings.content_width,
      font_family: payload.font_family ?? opened.settings.font_family,
      theme: payload.theme ?? opened.settings.theme,
      updated_at: "2026-07-14T02:00:00Z",
    }));
  });

  afterEach(() => vi.restoreAllMocks());

  it("restores an Edition location, syncs settings and allows an explicit finished state", async () => {
    const save = vi.spyOn(api, "saveReadingProgress").mockResolvedValue({
      ...progress,
      status: "finished",
      overall_progress: 1,
      version: 4,
    });

    renderReader();

    expect(await screen.findByText("正文第二节")).toBeInTheDocument();
    expect(api.getReaderSection).toHaveBeenCalledWith(editionId, "section-2");
    expect(
      screen.getByRole("progressbar", { name: "阅读进度 63%" }),
    ).toHaveAttribute("aria-valuenow", "63");
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "切换 Edition" }),
    );
    expect(
      await screen.findByTitle("人工译文 · zh-CN · 0%"),
    ).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });

    fireEvent.click(screen.getByRole("button", { name: "阅读设置" }));
    expect(screen.getByRole("slider", { name: "字号" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "行高" })).toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: "正文宽度" }),
    ).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "主题" }));
    fireEvent.click(await screen.findByTitle("深色"));
    await waitFor(() => expect(api.patchReaderSettings).toHaveBeenCalledWith(
      expect.objectContaining({ theme: "dark" }),
    ));

    fireEvent.click(screen.getAllByRole("button", { name: "标记已读" })[0]);
    await waitFor(() => expect(save).toHaveBeenCalledWith(
      editionId,
      expect.objectContaining({
        expected_version: 3,
        section_id: "section-2",
        overall_progress: 1,
        status: "finished",
      }),
      false,
    ));
    expect(
      screen.getByRole("progressbar", { name: "阅读进度 100%" }),
    ).toHaveAttribute("aria-valuenow", "100");
  });

  it("surfaces a stale multi-device save without losing the intentional local override", async () => {
    const save = vi.spyOn(api, "saveReadingProgress")
      .mockRejectedValueOnce(new ApiError(
        "阅读位置已在另一台设备更新。",
        "reading_progress_conflict",
        409,
        { current_version: 7 },
      ))
      .mockResolvedValueOnce({
        ...progress,
        status: "finished",
        overall_progress: 1,
        version: 8,
      });

    renderReader();
    await screen.findByText("正文第二节");
    fireEvent.click(screen.getByRole("button", { name: "标记已读" }));

    expect(await screen.findByRole("status")).toHaveTextContent("阅读位置已在另一台设备更新");
    fireEvent.click(screen.getByRole("button", { name: "用当前位置覆盖" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][1]).toEqual(expect.objectContaining({
      expected_version: 7,
      section_id: "section-2",
      overall_progress: 1,
    }));
    expect(await screen.findByText(/已同步/)).toBeInTheDocument();
  });

  it("keeps the current scroll position after a debounced progress save", async () => {
    const getSection = vi.mocked(api.getReaderSection);
    getSection.mockImplementation(() => Promise.resolve({ ...section }));
    const save = vi.spyOn(api, "saveReadingProgress").mockResolvedValue({
      ...progress,
      block_id: null,
      section_progress: 0.5,
      overall_progress: 0.75,
      version: 4,
    });

    const { container } = renderReader();
    expect(await screen.findByText("正文第二节")).toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 20));

    const scroller = container.querySelector("article")?.parentElement as HTMLDivElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 400 },
    });
    scroller.scrollTop = 300;
    fireEvent.scroll(scroller);

    await waitFor(() => expect(save).toHaveBeenCalledWith(
      editionId,
      expect.objectContaining({
        section_id: "section-2",
        section_progress: 0.5,
        overall_progress: 0.75,
      }),
      false,
    ), { timeout: 1600 });
    await waitFor(() => expect(screen.getByText(/已同步/)).toBeInTheDocument());
    await new Promise((resolve) => window.setTimeout(resolve, 20));

    expect(getSection).toHaveBeenCalledTimes(1);
    expect(scroller.scrollTop).toBe(300);
  });

  it("does not repeat a matching heading supplied by the publication", async () => {
    vi.mocked(api.getReaderSection).mockResolvedValue({
      ...section,
      html: '<div><h1 data-reader-block="block-1">第二节</h1>'
        + '<p data-reader-block="block-2">正文第二节</p></div>',
    });

    renderReader();

    expect(await screen.findByText("正文第二节")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "第二节" })).toHaveLength(1);
  });
});
