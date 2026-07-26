import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import type { ProviderCredentialStatus } from "../src/api/types";
import { ProviderCredentialPage } from "../src/pages/ProviderCredentialPage";

const configuredCredential: ProviderCredentialStatus = {
  configured: true,
  provider: "openai_compatible",
  version: 4,
  updated_at: "2026-07-25T09:30:00Z",
  usage: {
    current_month: {
      request_count: 3,
      prompt_tokens: 620,
      completion_tokens: 280,
      total_tokens: 900,
    },
    all_time: {
      request_count: 12,
      prompt_tokens: 2_400,
      completion_tokens: 1_056,
      total_tokens: 3_456,
    },
  },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProviderCredentialPage", () => {
  it("shows only safe status metadata and clears the key before a rotation completes", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    let resolveUpdate!: (value: ProviderCredentialStatus) => void;
    const pendingUpdate = new Promise<ProviderCredentialStatus>((resolve) => {
      resolveUpdate = resolve;
    });
    const update = vi.spyOn(api, "updateProviderCredential").mockReturnValue(pendingUpdate);

    render(<ProviderCredentialPage />);

    expect(await screen.findByRole("heading", { name: "凭据已配置" })).toBeInTheDocument();
    expect(screen.getByText("v4")).toBeInTheDocument();
    expect(screen.getByText("本月请求").nextSibling).toHaveTextContent("3");
    expect(screen.getByText("本月总 Token").nextSibling).toHaveTextContent("900");
    expect(screen.getByText("累计请求").nextSibling).toHaveTextContent("12");
    expect(screen.getByText("累计总 Token").nextSibling).toHaveTextContent("3,456");
    expect(screen.queryByText(/预计|人民币|美元|¥|\$/)).not.toBeInTheDocument();
    const input = screen.getByLabelText("OpenAI-compatible API Key");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");

    fireEvent.change(input, { target: { value: "unit-test-provider-credential" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    expect(update).toHaveBeenCalledWith({ api_key: "unit-test-provider-credential" });
    expect(input).toHaveValue("");
    expect(
      screen.queryByDisplayValue("unit-test-provider-credential"),
    ).not.toBeInTheDocument();

    await act(async () => {
      resolveUpdate({
        ...configuredCredential,
        version: 5,
        updated_at: "2026-07-25T09:40:00Z",
      });
      await pendingUpdate;
    });
    expect(await screen.findByText(/新的凭据版本已加密保存/)).toBeInTheDocument();
    expect(screen.getByText("v5")).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("explains destructive impact and requires confirmation before revoking every version", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const remove = vi.spyOn(api, "deleteProviderCredential").mockResolvedValue();

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    expect(screen.getByText(/Token 费用计入你的 Provider 账户/)).toBeInTheDocument();
    expect(screen.getByText(/已创建的任务继续使用创建时绑定的旧版本/)).toBeInTheDocument();
    expect(screen.getByText(/未完成任务的后续 Provider 调用将失败/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除 Provider 凭据" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "尚未配置凭据" })).toBeInTheDocument();
    expect(screen.getByText(/Provider 凭据已撤销/)).toBeInTheDocument();
  });

  it("keeps a clear zero state when the Relay has recorded no usage", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      configured: false,
      provider: "openai_compatible",
      version: null,
      updated_at: null,
      usage: {
        current_month: {
          request_count: 0,
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
        },
        all_time: {
          request_count: 0,
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
        },
      },
    });

    render(<ProviderCredentialPage />);

    expect(
      await screen.findByText("本月还没有通过漫读 Relay 发起的 Provider 请求。"),
    ).toBeInTheDocument();
    expect(screen.getByText("本月请求").nextSibling).toHaveTextContent("0");
    expect(screen.getByText("累计总 Token").nextSibling).toHaveTextContent("0");
  });
});
