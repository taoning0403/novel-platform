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
  provider_name: "OpenAI",
  base_url: "https://api.openai.com/v1",
  model: "gpt-4.1-mini",
  thinking_enabled: false,
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
    expect(screen.getAllByText("https://api.openai.com/v1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("gpt-4.1-mini").length).toBeGreaterThan(0);
    expect(screen.getByText("关闭")).toBeInTheDocument();
    const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
    expect(thinkingSwitch).not.toBeChecked();
    expect(thinkingSwitch).toBeDisabled();
    expect(thinkingSwitch.closest("label")).toHaveAttribute("data-disabled", "true");
    expect(screen.getByText(/当前 Provider 没有可验证的统一开关/))
      .toBeInTheDocument();
    const input = screen.getByLabelText("OpenAI API Key");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");

    fireEvent.change(input, { target: { value: "unit-test-provider-credential" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    expect(update).toHaveBeenCalledWith({
      api_key: "unit-test-provider-credential",
      provider: "openai_compatible",
      model: "gpt-4.1-mini",
      thinking_enabled: false,
    });
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
    expect(await screen.findByText(/新的 OpenAI 凭据版本已加密保存/)).toBeInTheDocument();
    expect(screen.getByText("v5")).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("restores an enabled DeepSeek thinking configuration in status and form", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-reasoner",
      thinking_enabled: true,
    });

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    expect(screen.getByText("开启")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "思考模式" })).toBeChecked();
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-reasoner");
    expect(screen.getByLabelText("模型")).toBeDisabled();
  });

  it("offers preset providers and submits custom configuration only for custom", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const customCredential: ProviderCredentialStatus = {
      ...configuredCredential,
      provider: "custom",
      provider_name: "我的兼容服务",
      base_url: "https://provider.example.com/v1",
      model: "novel-model",
      version: 5,
    };
    const update = vi.spyOn(api, "updateProviderCredential").mockResolvedValue(customCredential);

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
    expect(await screen.findByText("DeepSeek")).toBeInTheDocument();
    expect(screen.getByText("Kimi")).toBeInTheDocument();
    fireEvent.click(await screen.findByTitle("DeepSeek"));
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");
    expect(screen.getByLabelText("DeepSeek API Key")).toBeInTheDocument();
    const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
    expect(thinkingSwitch).toBeEnabled();
    const thinkingTarget = thinkingSwitch.closest("label");
    expect(thinkingTarget).toHaveAttribute("data-disabled", "false");
    fireEvent.click(thinkingTarget as HTMLLabelElement);
    expect(thinkingSwitch).toBeChecked();
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-reasoner");
    expect(screen.getByLabelText("模型")).toBeDisabled();
    fireEvent.click(thinkingSwitch);
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "deepseek-reasoner" },
    });
    expect(thinkingSwitch).toBeChecked();
    expect(screen.getByLabelText("模型")).toBeDisabled();
    fireEvent.click(thinkingSwitch);
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
    fireEvent.click(await screen.findByTitle("Kimi"));
    expect(screen.getByLabelText("模型")).toHaveValue("kimi-k2.5");
    expect(screen.getByLabelText("Kimi API Key")).toBeInTheDocument();
    expect(screen.getAllByText("https://api.moonshot.cn/v1").length).toBeGreaterThan(0);
    fireEvent.click(thinkingSwitch);
    expect(thinkingSwitch).toBeChecked();
    expect(screen.getByLabelText("模型")).toHaveValue("kimi-k2.5");
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "moonshot-v1-8k" },
    });
    expect(thinkingSwitch).not.toBeChecked();
    expect(thinkingSwitch).toBeDisabled();
    expect(screen.getByText(/Kimi 仅在模型为 kimi-k2.5 时支持思考模式/))
      .toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
    fireEvent.click(await screen.findByTitle("自定义 Provider"));
    expect(thinkingSwitch).not.toBeChecked();
    expect(thinkingSwitch).toBeDisabled();

    expect(screen.getByLabelText(/^API Base URL/)).toHaveAttribute("type", "url");
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "novel-model" },
    });
    fireEvent.change(screen.getByLabelText("自定义名称"), {
      target: { value: "我的兼容服务" },
    });
    fireEvent.change(screen.getByLabelText(/^API Base URL/), {
      target: { value: "https://provider.example.com/v1/" },
    });
    const keyInput = screen.getByLabelText("我的兼容服务 API Key");
    fireEvent.change(keyInput, { target: { value: "custom-provider-key" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "custom-provider-key",
      provider: "custom",
      model: "novel-model",
      base_url: "https://provider.example.com/v1",
      custom_name: "我的兼容服务",
      thinking_enabled: false,
    }));
    expect(keyInput).toHaveValue("");
    expect(await screen.findByText(/新的 我的兼容服务 凭据版本已加密保存/))
      .toBeInTheDocument();
  });

  it("normalizes a typed DeepSeek reasoner model to thinking mode", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const update = vi.spyOn(api, "updateProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-reasoner",
      thinking_enabled: true,
      version: 5,
    });

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
    fireEvent.click(await screen.findByTitle("DeepSeek"));
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "deepseek-reasoner" },
    });
    expect(screen.getByRole("switch", { name: "思考模式" })).toBeChecked();

    fireEvent.change(screen.getByLabelText("DeepSeek API Key"), {
      target: { value: "deepseek-provider-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "deepseek-provider-key",
      provider: "deepseek",
      model: "deepseek-reasoner",
      thinking_enabled: true,
    }));
  });

  it("never submits thinking mode for another Kimi model", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const update = vi.spyOn(api, "updateProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "kimi",
      provider_name: "Kimi",
      base_url: "https://api.moonshot.cn/v1",
      model: "moonshot-v1-8k",
      thinking_enabled: false,
      version: 5,
    });

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
    fireEvent.click(await screen.findByTitle("Kimi"));
    const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
    fireEvent.click(thinkingSwitch);
    expect(thinkingSwitch).toBeChecked();
    fireEvent.change(screen.getByLabelText("模型"), {
      target: { value: "moonshot-v1-8k" },
    });
    expect(thinkingSwitch).not.toBeChecked();
    expect(thinkingSwitch).toBeDisabled();

    const keyInput = screen.getByLabelText("Kimi API Key");
    fireEvent.change(keyInput, { target: { value: "kimi-provider-key" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "kimi-provider-key",
      provider: "kimi",
      model: "moonshot-v1-8k",
      thinking_enabled: false,
    }));
  });

  it("revokes with confirmation and resets DeepSeek reasoner before a new save", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-reasoner",
      thinking_enabled: true,
    });
    const remove = vi.spyOn(api, "deleteProviderCredential").mockResolvedValue();
    const update = vi.spyOn(api, "updateProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      thinking_enabled: false,
      version: 5,
    });

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    expect(screen.getByRole("switch", { name: "思考模式" })).toBeChecked();
    expect(screen.getByText(/Token 费用计入你的 Provider 账户/)).toBeInTheDocument();
    expect(screen.getByText(/已创建的任务继续使用创建时绑定的旧版本/)).toBeInTheDocument();
    expect(screen.getByText(/未完成任务的后续 Provider 调用将失败/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除 Provider 凭据" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "尚未配置凭据" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "思考模式" })).not.toBeChecked();
    });
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");
    expect(screen.getByText(/Provider 凭据已撤销/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("DeepSeek API Key"), {
      target: { value: "new-deepseek-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并启用" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "new-deepseek-key",
      provider: "deepseek",
      model: "deepseek-chat",
      thinking_enabled: false,
    }));
  });

  it("keeps a clear zero state when the Relay has recorded no usage", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      configured: false,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-reasoner",
      thinking_enabled: true,
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
    expect(screen.getByRole("switch", { name: "思考模式" })).not.toBeChecked();
    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");
  });
});
