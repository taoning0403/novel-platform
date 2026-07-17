import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import type {
  Device,
  IssuedReaderCredential,
  ReaderIdentity,
} from "../src/api/types";
import { AdminReadersPage } from "../src/pages/AdminReadersPage";

const reader: ReaderIdentity = {
  id: "10000000-0000-0000-0000-000000000001",
  display_name: "林小姐",
  admin_note: "家庭成员",
  status: "active",
  created_at: "2026-07-16T00:00:00Z",
  updated_at: "2026-07-16T00:00:00Z",
  credential: {
    id: "20000000-0000-0000-0000-000000000001",
    hint: "np_reader_…a1b2",
    lifecycle_status: "active",
    effective_status: "active",
    expires_at: "2026-08-16T00:00:00Z",
    max_devices: 3,
    allow_new_devices: true,
    active_device_count: 1,
    last_used_at: null,
    created_at: "2026-07-16T00:00:00Z",
    reissued_at: null,
    revoked_at: null,
    suspended_at: null,
  },
};

const issued: IssuedReaderCredential = {
  reader,
  access_credential: "np_reader_once_only_secret",
};

const restrictedReader: ReaderIdentity = {
  ...reader,
  id: "10000000-0000-0000-0000-000000000002",
  display_name: "陈先生",
  admin_note: "暂时停用",
  credential: {
    ...reader.credential!,
    id: "20000000-0000-0000-0000-000000000002",
    hint: "np_reader_…c3d4",
    lifecycle_status: "suspended",
    effective_status: "suspended",
    suspended_at: "2026-07-17T00:00:00Z",
  },
};

const device: Device = {
  id: "30000000-0000-0000-0000-000000000001",
  name: "客厅浏览器",
  platform: "web",
  app_version: null,
  first_seen_at: "2026-07-16T00:00:00Z",
  last_seen_at: "2026-07-17T00:00:00Z",
  revoked_at: null,
  is_current: false,
  active_session_count: 2,
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AdminReadersPage", () => {
  it("keeps the one-time credential modal open until the explicit saved action", async () => {
    vi.spyOn(api, "listReaders")
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([reader]);
    vi.spyOn(api, "createReader").mockResolvedValue(issued);

    render(
      <MemoryRouter>
        <AdminReadersPage />
      </MemoryRouter>,
    );

    await screen.findByText("还没有阅读者");
    fireEvent.click(screen.getByRole("button", { name: "签发凭证" }));
    const createDialog = await screen.findByRole("dialog", {
      name: "签发初始凭证",
    });
    fireEvent.change(within(createDialog).getByLabelText("显示名称"), {
      target: { value: "林小姐" },
    });
    fireEvent.click(
      within(createDialog).getByRole("button", { name: "创建并显示凭证" }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: "保存访问凭证（仅显示一次）",
    });
    expect(within(dialog).getByText(issued.access_credential)).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: /关闭|close/i }),
    ).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "我已安全保存" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(issued.access_credential)).not.toBeInTheDocument();
  });

  it("requires explicit confirmation before permanently revoking a credential", async () => {
    vi.spyOn(api, "listReaders").mockResolvedValue([reader]);
    const revoke = vi
      .spyOn(api, "revokeReaderCredential")
      .mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <AdminReadersPage />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "林小姐" });
    fireEvent.click(screen.getByRole("button", { name: "更多阅读者操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "永久撤销" }));
    let dialog = await screen.findByRole("dialog", {
      name: "永久撤销这份凭证？",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(revoke).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "更多阅读者操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "永久撤销" }));
    dialog = await screen.findByRole("dialog", {
      name: "永久撤销这份凭证？",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认执行" }));
    await waitFor(() =>
      expect(revoke).toHaveBeenCalledWith(reader.id),
    );
  });

  it("filters the master list, uses a real mobile detail state, and loads honest session totals lazily", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      media: "(max-width: 760px)",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.spyOn(api, "listReaders").mockResolvedValue([reader, restrictedReader]);
    const listDevices = vi.spyOn(api, "listReaderDevices").mockResolvedValue([device]);
    const listAudit = vi.spyOn(api, "readerAudit").mockResolvedValue([]);

    render(
      <MemoryRouter>
        <AdminReadersPage />
      </MemoryRouter>,
    );

    const master = await screen.findByRole("complementary", { name: "阅读者列表" });
    expect(listDevices).not.toHaveBeenCalled();
    expect(listAudit).not.toHaveBeenCalled();

    fireEvent.click(within(master).getByRole("button", { name: "受限 1" }));
    expect(within(master).queryByText("林小姐")).not.toBeInTheDocument();
    expect(within(master).getByText("陈先生")).toBeInTheDocument();

    fireEvent.click(within(master).getByRole("button", { name: "全部 2" }));
    fireEvent.change(within(master).getByRole("searchbox", { name: "搜索阅读者" }), {
      target: { value: "陈" },
    });
    const readerButton = within(master).getByRole("button", { name: /陈先生/ });
    fireEvent.click(readerButton);
    expect(master.parentElement).toHaveAttribute("data-mobile-view", "detail");

    const backButton = await screen.findByRole("button", { name: "返回阅读者列表" });
    await waitFor(() => expect(backButton).toHaveFocus());
    fireEvent.click(backButton);
    expect(master.parentElement).toHaveAttribute("data-mobile-view", "list");
    await waitFor(() => expect(readerButton).toHaveFocus());

    fireEvent.click(readerButton);
    const overviewTab = await screen.findByRole("tab", { name: "概览" });
    const devicesTab = screen.getByRole("tab", { name: /设备/ });
    expect(overviewTab).toHaveAttribute("tabindex", "0");
    expect(devicesTab).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(overviewTab, { key: "ArrowRight" });
    expect(devicesTab).toHaveFocus();
    expect(devicesTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName(/设备/);

    fireEvent.click(await screen.findByRole("tab", { name: "会话" }));
    await waitFor(() => {
      expect(listDevices).toHaveBeenCalledWith(restrictedReader.id);
      expect(listAudit).toHaveBeenCalledWith(restrictedReader.id);
    });
    expect(await screen.findByText("2 个活跃会话")).toBeInTheDocument();
  });
});
