import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import type { Edition } from "../src/api/types";
import { EditionCard } from "../src/features/editions/EditionCard";

const independentTranslation: Edition = {
  id: "7e2a8a22-61f3-482f-b910-d715c652d3a2",
  book_id: "18b48347-8d9d-4910-a9e2-3efdf360a9d1",
  title: "外部 AI 中文译文",
  language: "zh-CN",
  content_role: "translation",
  translation_origin: "ai",
  creation_method: "uploaded",
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
  created_at: "2026-07-10T08:00:00Z",
  updated_at: "2026-07-10T08:00:00Z",
};

const aiEdition: Edition = {
  ...independentTranslation,
  id: "8e2a8a22-61f3-482f-b910-d715c652d3a3",
  title: "机器初译",
  creation_method: "generated",
};

const humanEdition: Edition = {
  ...independentTranslation,
  id: "9e2a8a22-61f3-482f-b910-d715c652d3a4",
  title: "人工精译",
  translation_origin: "human",
};

afterEach(() => vi.restoreAllMocks());

describe("EditionCard", () => {
  it("presents an unlinked translation as usable rather than erroneous", () => {
    render(
      <MemoryRouter>
        <EditionCard
          edition={independentTranslation}
          allEditions={[independentTranslation]}
          onUpdated={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("未关联原文")).toBeInTheDocument();
    expect(
      screen.getByText("该版本可以独立使用。后续获得原文后，可以再建立关联。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/错误/)).not.toBeInTheDocument();
  });

  it("marks a human translation preferred without hiding the AI edition", async () => {
    const onSetPreferred = vi.fn();
    render(
      <MemoryRouter>
        <EditionCard
          edition={humanEdition}
          allEditions={[humanEdition, aiEdition]}
          onUpdated={vi.fn()}
          onSetPreferred={onSetPreferred}
        />
        <EditionCard
          edition={aiEdition}
          allEditions={[humanEdition, aiEdition]}
          onUpdated={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "设为首选" })[0]);
    await waitFor(() => expect(onSetPreferred).toHaveBeenCalledWith(humanEdition));
    expect(screen.getAllByText("人工译文").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AI 译文").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/不会覆盖、归档或删除其他版本/)).toHaveLength(2);
  });

  it("requires explicit confirmation before deleting an Edition", async () => {
    const remove = vi.spyOn(api, "deleteEdition").mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    render(
      <MemoryRouter>
        <EditionCard
          edition={independentTranslation}
          allEditions={[independentTranslation]}
          onUpdated={vi.fn()}
          onDeleted={onDeleted}
          canManage
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除 Edition" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "删除 Edition" }));
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(
      independentTranslation.book_id,
      independentTranslation.id,
    ));
    expect(onDeleted).toHaveBeenCalled();
  });

  it("edits the Edition title and supersedes relationship", async () => {
    const updated = {
      ...independentTranslation,
      title: "修订后的译文",
      supersedes_edition_id: aiEdition.id,
    };
    const patch = vi.spyOn(api, "patchEdition").mockResolvedValue(updated);
    const onUpdated = vi.fn();
    render(
      <MemoryRouter>
        <EditionCard
          edition={independentTranslation}
          allEditions={[independentTranslation, aiEdition]}
          onUpdated={onUpdated}
          canManage
        />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText("Edition 名称"), {
      target: { value: "修订后的译文" },
    });
    fireEvent.mouseDown(screen.getByLabelText("替代关系"));
    fireEvent.click(screen.getByTitle(`${aiEdition.title} · ${aiEdition.language}`));
    fireEvent.click(screen.getByRole("button", { name: "保存关系与状态" }));

    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      independentTranslation.book_id,
      independentTranslation.id,
      {
        title: "修订后的译文",
        source_edition_id: null,
        supersedes_edition_id: aiEdition.id,
        status: "ready",
      },
    ));
    expect(onUpdated).toHaveBeenCalledWith(updated);
  });
});
