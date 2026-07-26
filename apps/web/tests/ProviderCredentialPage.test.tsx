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

async function chooseProvider(title: string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Provider" }));
  fireEvent.click(await screen.findByTitle(title));
}

async function chooseModel(model: string) {
  const modelSelect = screen.getByRole("combobox", { name: "模型" });
  await waitFor(() => expect(modelSelect).toBeEnabled());
  fireEvent.mouseDown(modelSelect);
  fireEvent.click(await screen.findByTitle(model));
}

function expectModelIsEmpty() {
  const modelSelect = screen.getByRole("combobox", { name: "模型" });
  expect(modelSelect).toBeDisabled();
  expect(modelSelect.closest(".ant-select")).toHaveTextContent("先读取模型列表");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProviderCredentialPage", () => {
  it("shows the configured model only in status and requires a fresh catalog selection", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);

    render(<ProviderCredentialPage />);

    expect(await screen.findByRole("heading", { name: "凭据已配置" })).toBeInTheDocument();
    expect(screen.getByText("v4")).toBeInTheDocument();
    expect(screen.getByText("本月请求").nextSibling).toHaveTextContent("3");
    expect(screen.getByText("本月总 Token").nextSibling).toHaveTextContent("900");
    expect(screen.getByText("累计请求").nextSibling).toHaveTextContent("12");
    expect(screen.getByText("累计总 Token").nextSibling).toHaveTextContent("3,456");
    expect(screen.queryByText(/预计|人民币|美元|¥|\$/)).not.toBeInTheDocument();
    expect(screen.getByText("gpt-4.1-mini")).toBeInTheDocument();
    expectModelIsEmpty();

    const keyInput = screen.getByLabelText("OpenAI API Key");
    expect(keyInput).toHaveAttribute("type", "password");
    expect(keyInput).toHaveAttribute("autocomplete", "off");
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "思考模式" })).toBeDisabled();
  });

  it("loads every model with the current key, keeps the key, and clears it before saving", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const listModels = vi.spyOn(api, "listProviderModels").mockResolvedValue({
      provider: "openai_compatible",
      models: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
    });
    let resolveUpdate!: (value: ProviderCredentialStatus) => void;
    const pendingUpdate = new Promise<ProviderCredentialStatus>((resolve) => {
      resolveUpdate = resolve;
    });
    const update = vi.spyOn(api, "updateProviderCredential").mockReturnValue(pendingUpdate);

    render(<ProviderCredentialPage />);
    await screen.findByRole("heading", { name: "凭据已配置" });

    const keyInput = screen.getByLabelText("OpenAI API Key");
    const saveButton = screen.getByRole("button", { name: "保存新版本" });
    fireEvent.change(keyInput, { target: { value: "unit-test-provider-credential" } });
    expect(saveButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));

    await waitFor(() => expect(listModels).toHaveBeenCalledWith({
      provider: "openai_compatible",
      api_key: "unit-test-provider-credential",
    }));
    expect(keyInput).toHaveValue("unit-test-provider-credential");
    expect(await screen.findByText(/已读取 3 个模型/)).toBeInTheDocument();
    const modelSelect = screen.getByRole("combobox", { name: "模型" });
    expect(modelSelect).toBeEnabled();
    expect(modelSelect).toHaveAttribute("aria-autocomplete", "list");

    fireEvent.mouseDown(modelSelect);
    expect(await screen.findByTitle("gpt-4.1")).toBeInTheDocument();
    expect(screen.getByTitle("gpt-4.1-mini")).toBeInTheDocument();
    expect(screen.getByTitle("gpt-4o-mini")).toBeInTheDocument();
    fireEvent.change(modelSelect, { target: { value: "mini" } });
    fireEvent.click(await screen.findByTitle("gpt-4.1-mini"));

    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    expect(update).toHaveBeenCalledWith({
      api_key: "unit-test-provider-credential",
      provider: "openai_compatible",
      model: "gpt-4.1-mini",
      thinking_enabled: false,
    });
    expect(keyInput).toHaveValue("");
    expect(screen.queryByDisplayValue("unit-test-provider-credential")).not.toBeInTheDocument();
    expectModelIsEmpty();

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
    expect(keyInput).toHaveValue("");
  });

  it("uses the normalized custom Base URL for catalog loading and saving", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const listModels = vi.spyOn(api, "listProviderModels").mockResolvedValue({
      provider: "custom",
      models: ["novel-model", "novel-model-pro"],
    });
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
    await chooseProvider("自定义 Provider");

    fireEvent.change(screen.getByLabelText("自定义名称"), {
      target: { value: "我的兼容服务" },
    });
    fireEvent.change(screen.getByLabelText("API Base URL"), {
      target: { value: "https://provider.example.com/v1/" },
    });
    const keyInput = screen.getByLabelText("我的兼容服务 API Key");
    fireEvent.change(keyInput, { target: { value: "custom-provider-key" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));

    await waitFor(() => expect(listModels).toHaveBeenCalledWith({
      provider: "custom",
      api_key: "custom-provider-key",
      base_url: "https://provider.example.com/v1",
    }));
    expect(keyInput).toHaveValue("custom-provider-key");
    await chooseModel("novel-model");
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

  it("invalidates the catalog when the provider, custom URL, or API key changes", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    const listModels = vi.spyOn(api, "listProviderModels").mockResolvedValue({
      provider: "custom",
      models: ["model-for-invalidation"],
    });

    render(<ProviderCredentialPage />);
    await screen.findByRole("heading", { name: "凭据已配置" });
    await chooseProvider("自定义 Provider");
    fireEvent.change(screen.getByLabelText("自定义名称"), {
      target: { value: "测试服务" },
    });
    const baseUrlInput = screen.getByLabelText("API Base URL");
    fireEvent.change(baseUrlInput, {
      target: { value: "https://provider.example.com/v1" },
    });
    const keyInput = screen.getByLabelText("测试服务 API Key");
    fireEvent.change(keyInput, { target: { value: "catalog-key-1" } });

    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    await chooseModel("model-for-invalidation");
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeEnabled();

    fireEvent.change(baseUrlInput, {
      target: { value: "https://provider.example.com/v2" },
    });
    expect(keyInput).toHaveValue("");
    expectModelIsEmpty();
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();

    fireEvent.change(keyInput, { target: { value: "catalog-key-2" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    await chooseModel("model-for-invalidation");
    fireEvent.change(keyInput, { target: { value: "catalog-key-3" } });
    expectModelIsEmpty();

    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    await chooseModel("model-for-invalidation");
    await chooseProvider("DeepSeek");
    expect(screen.getByLabelText("DeepSeek API Key")).toHaveValue("");
    expectModelIsEmpty();
    expect(screen.getByRole("switch", { name: "思考模式" })).not.toBeChecked();
    expect(listModels).toHaveBeenCalledTimes(3);
  });

  it("maps DeepSeek catalog selections and the switch to the matching thinking model", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    vi.spyOn(api, "listProviderModels").mockResolvedValue({
      provider: "deepseek",
      models: ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"],
    });
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
    await chooseProvider("DeepSeek");
    const keyInput = screen.getByLabelText("DeepSeek API Key");
    fireEvent.change(keyInput, { target: { value: "deepseek-provider-key" } });
    const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
    expect(thinkingSwitch).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    await chooseModel("deepseek-reasoner");
    expect(thinkingSwitch).toBeChecked();
    expect(thinkingSwitch).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "模型" })).toBeDisabled();

    fireEvent.click(thinkingSwitch);
    expect(thinkingSwitch).not.toBeChecked();
    expect(screen.getAllByTitle("deepseek-chat").length).toBeGreaterThan(0);
    expect(screen.getByRole("combobox", { name: "模型" })).toBeEnabled();

    fireEvent.click(thinkingSwitch);
    expect(thinkingSwitch).toBeChecked();
    expect(screen.getAllByTitle("deepseek-reasoner").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "deepseek-provider-key",
      provider: "deepseek",
      model: "deepseek-reasoner",
      thinking_enabled: true,
    }));
  });

  it("enables Kimi thinking only for kimi-k2.5", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    vi.spyOn(api, "listProviderModels").mockResolvedValue({
      provider: "kimi",
      models: ["kimi-k2.5", "moonshot-v1-8k"],
    });
    const update = vi.spyOn(api, "updateProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "kimi",
      provider_name: "Kimi",
      base_url: "https://api.moonshot.cn/v1",
      model: "moonshot-v1-8k",
      version: 5,
    });

    render(<ProviderCredentialPage />);
    await screen.findByRole("heading", { name: "凭据已配置" });
    await chooseProvider("Kimi");
    const keyInput = screen.getByLabelText("Kimi API Key");
    fireEvent.change(keyInput, { target: { value: "kimi-provider-key" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));

    await chooseModel("kimi-k2.5");
    const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
    expect(thinkingSwitch).toBeEnabled();
    expect(thinkingSwitch).not.toBeChecked();
    fireEvent.click(thinkingSwitch);
    expect(thinkingSwitch).toBeChecked();

    await chooseModel("moonshot-v1-8k");
    expect(thinkingSwitch).not.toBeChecked();
    expect(thinkingSwitch).toBeDisabled();
    expect(screen.getByText(/Kimi 仅在模型为 kimi-k2.5 时支持思考模式/))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith({
      api_key: "kimi-provider-key",
      provider: "kimi",
      model: "moonshot-v1-8k",
      thinking_enabled: false,
    }));
  });

  it("rejects mismatched, empty, and failed model catalogs without clearing the key", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
    vi.spyOn(api, "listProviderModels")
      .mockResolvedValueOnce({ provider: "deepseek", models: ["deepseek-chat"] })
      .mockResolvedValueOnce({ provider: "openai_compatible", models: [] })
      .mockRejectedValueOnce(new Error("模型目录读取失败"));

    render(<ProviderCredentialPage />);
    await screen.findByRole("heading", { name: "凭据已配置" });
    const keyInput = screen.getByLabelText("OpenAI API Key");
    const saveButton = screen.getByRole("button", { name: "保存新版本" });

    fireEvent.change(keyInput, { target: { value: "catalog-key-1" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    expect(await screen.findByText(/模型目录与当前 Provider 不一致/)).toBeInTheDocument();
    expect(keyInput).toHaveValue("catalog-key-1");
    expect(saveButton).toBeDisabled();

    fireEvent.change(keyInput, { target: { value: "catalog-key-2" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    expect(await screen.findByText(/未返回可用模型/)).toBeInTheDocument();
    expect(keyInput).toHaveValue("catalog-key-2");
    expect(saveButton).toBeDisabled();

    fireEvent.change(keyInput, { target: { value: "catalog-key-3" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
    expect(await screen.findByText(/模型目录读取失败/)).toBeInTheDocument();
    expect(keyInput).toHaveValue("catalog-key-3");
    expect(saveButton).toBeDisabled();
    expectModelIsEmpty();
  });

  it("revokes with confirmation and leaves an unconfigured form without a model", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      ...configuredCredential,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-reasoner",
      thinking_enabled: true,
    });
    const remove = vi.spyOn(api, "deleteProviderCredential").mockResolvedValue();

    render(<ProviderCredentialPage />);

    await screen.findByRole("heading", { name: "凭据已配置" });
    expect(screen.getByText("deepseek-reasoner")).toBeInTheDocument();
    expect(screen.getByText("开启")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "思考模式" })).not.toBeChecked();
    expectModelIsEmpty();
    expect(screen.getByText(/Token 费用计入你的 Provider 账户/)).toBeInTheDocument();
    expect(screen.getByText(/已创建的任务继续使用创建时绑定的旧版本/))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除 Provider 凭据" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "尚未配置凭据" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "思考模式" })).not.toBeChecked();
    expectModelIsEmpty();
    expect(screen.getByText(/Provider 凭据已撤销/)).toBeInTheDocument();
  });

  it("keeps a clear zero state when the Relay has no usage or historical model", async () => {
    vi.spyOn(api, "getProviderCredential").mockResolvedValue({
      configured: false,
      provider: "deepseek",
      provider_name: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: null,
      thinking_enabled: false,
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
    expectModelIsEmpty();
  });
});
