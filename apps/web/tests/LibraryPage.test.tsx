import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../src/api/client";
import { LibraryPage } from "../src/pages/LibraryPage";

vi.mock("../src/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { display_name: "测试用户", role: "admin" } }),
}));

afterEach(() => vi.restoreAllMocks());

describe("LibraryPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "recentReading").mockResolvedValue([]);
  });

  it("shows the EPUB/TXT empty-library state", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    expect(await screen.findByText("书库还是空的")).toBeInTheDocument();
    expect(screen.getByText("上传 EPUB 或 TXT，创建第一本带文件的作品。")).toBeInTheDocument();
  });

  it("renders covers, formats, languages and preferred edition, then applies filters", async () => {
    const list = vi.spyOn(api, "listBooks").mockResolvedValue([
      {
        id: "00000000-0000-0000-0000-000000000001",
        canonical_title: "测试 EPUB",
        canonical_author: "测试作者",
        description: "简介",
        edition_count: 2,
        languages: ["ja", "zh-CN"],
        file_formats: ["epub", "txt"],
        preferred_edition_id: "00000000-0000-0000-0000-000000000003",
        preferred_edition_title: "人工译文",
        reading_status: "reading",
        reading_progress: 0.42,
        cover_thumbnail_url: null,
        created_at: "2026-07-13T00:00:00Z",
        updated_at: "2026-07-13T01:00:00Z",
      },
    ]);
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    expect(await screen.findByText("测试 EPUB")).toBeInTheDocument();
    expect(screen.getAllByText("EPUB").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TXT").length).toBeGreaterThan(0);
    expect(screen.getByText("首选：人工译文")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("搜索书名或作者"), {
      target: { value: "作者" },
    });
    fireEvent.click(screen.getByRole("button", { name: "打开筛选" }));
    const drawer = await screen.findByRole("dialog", { name: "筛选作品" });
    fireEvent.mouseDown(within(drawer).getByLabelText("文件格式"));
    fireEvent.click(await screen.findByTitle("EPUB"));
    fireEvent.change(within(drawer).getByLabelText("语言"), { target: { value: "ja" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "筛选" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.objectContaining({
      query: "作者",
      format: "epub",
      language: "ja",
    })));
  });

  it("shows the latest Edition as a direct continuation target", async () => {
    vi.spyOn(api, "listBooks").mockResolvedValue([]);
    vi.mocked(api.recentReading).mockResolvedValue([{
      book_id: "00000000-0000-4000-8000-000000000501",
      book_title: "最近读过的书",
      book_cover_thumbnail_url: null,
      edition_id: "00000000-0000-4000-8000-000000000502",
      edition_title: "人工译文",
      edition_language: "zh-CN",
      file_format: "txt",
      series_id: "00000000-0000-4000-8000-000000000503",
      series_name: "长篇系列",
      status: "reading",
      progress: 0.37,
      last_read_at: "2026-07-14T01:00:00Z",
      continue_url: "/read/00000000-0000-4000-8000-000000000502",
    }]);

    render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "最近阅读" })).toBeInTheDocument();
    expect(screen.getByText("最近读过的书")).toBeInTheDocument();
    expect(screen.getByText("37%")).toBeInTheDocument();
    expect(screen.getByText(/2026年7月14日/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "继续阅读" })).toHaveAttribute(
      "href",
      "/read/00000000-0000-4000-8000-000000000502",
    );
  });

  it("shows a recoverable API error", async () => {
    vi.spyOn(api, "listBooks").mockRejectedValue(
      new ApiError("书库暂时不可用", "library_unavailable", 503),
    );
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("书库暂时不可用");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});
