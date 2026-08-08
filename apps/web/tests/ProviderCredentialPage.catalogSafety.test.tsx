import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("rejects an unsafe custom Base URL before catalog or save requests", async () => {
  vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
  const listModels = vi.spyOn(api, "listProviderModels");
  const update = vi.spyOn(api, "updateProviderCredential");

  render(<ProviderCredentialPage />);
  await screen.findByRole("heading", { name: "凭据已配置" });
  await chooseProvider("自定义 Provider");
  fireEvent.change(screen.getByLabelText("自定义名称"), {
    target: { value: "不安全地址" },
  });
  fireEvent.change(screen.getByLabelText("API Base URL"), {
    target: { value: "https://user:password@provider.example.com/v1?token=x#fragment" },
  });
  fireEvent.change(screen.getByLabelText("不安全地址 API Key"), {
    target: { value: "unsafe-custom-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "自定义 Base URL 必须是 HTTPS 地址，且不能包含用户名、密码、查询参数或片段。",
  );
  expect(listModels).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
  expect(update).not.toHaveBeenCalled();
});

it("never restores the API Key when saving the credential fails", async () => {
  vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
  vi.spyOn(api, "listProviderModels").mockResolvedValue({
    provider: "openai_compatible",
    models: ["gpt-4.1-mini"],
  });
  const update = vi.spyOn(api, "updateProviderCredential")
    .mockRejectedValue(new Error("凭据保存失败"));

  render(<ProviderCredentialPage />);
  await screen.findByRole("heading", { name: "凭据已配置" });
  const keyInput = screen.getByLabelText("OpenAI API Key");
  fireEvent.change(keyInput, { target: { value: "failed-save-provider-key" } });
  fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
  await chooseModel("gpt-4.1-mini");
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

  await waitFor(() => expect(update).toHaveBeenCalledWith({
    api_key: "failed-save-provider-key",
    provider: "openai_compatible",
    model: "gpt-4.1-mini",
    thinking_enabled: false,
  }));
  expect(keyInput).toHaveValue("");
  expect(screen.queryByDisplayValue("failed-save-provider-key")).not.toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "凭据保存失败 输入内容已从页面清除，请重新输入。",
  );
  expect(keyInput).toHaveValue("");
});

it("saves enabled Kimi k2.5 thinking as true", async () => {
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
    model: "kimi-k2.5",
    thinking_enabled: true,
    version: 5,
  });

  render(<ProviderCredentialPage />);
  await screen.findByRole("heading", { name: "凭据已配置" });
  await chooseProvider("Kimi");
  fireEvent.change(screen.getByLabelText("Kimi API Key"), {
    target: { value: "kimi-thinking-provider-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
  await chooseModel("kimi-k2.5");
  const thinkingSwitch = screen.getByRole("switch", { name: "思考模式" });
  fireEvent.click(thinkingSwitch);
  expect(thinkingSwitch).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

  await waitFor(() => expect(update).toHaveBeenCalledWith({
    api_key: "kimi-thinking-provider-key",
    provider: "kimi",
    model: "kimi-k2.5",
    thinking_enabled: true,
  }));
});

it("ignores an older catalog response after the Provider and key change", async () => {
  vi.spyOn(api, "getProviderCredential").mockResolvedValue(configuredCredential);
  const olderCatalog = deferred<{
    provider: "openai_compatible";
    models: string[];
  }>();
  const listModels = vi.spyOn(api, "listProviderModels")
    .mockReturnValueOnce(olderCatalog.promise)
    .mockResolvedValueOnce({
      provider: "deepseek",
      models: ["deepseek-chat", "deepseek-reasoner"],
    });

  render(<ProviderCredentialPage />);
  await screen.findByRole("heading", { name: "凭据已配置" });
  fireEvent.change(screen.getByLabelText("OpenAI API Key"), {
    target: { value: "older-openai-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
  await waitFor(() => expect(listModels).toHaveBeenCalledTimes(1));
  await chooseProvider("DeepSeek");
  fireEvent.change(screen.getByLabelText("DeepSeek API Key"), {
    target: { value: "current-deepseek-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取模型列表" }));
  expect(await screen.findByText(/已读取 2 个模型/)).toBeInTheDocument();
  await chooseModel("deepseek-chat");

  await act(async () => {
    olderCatalog.resolve({
      provider: "openai_compatible",
      models: ["stale-openai-model"],
    });
    await olderCatalog.promise;
  });

  expect(screen.getByText(/已读取 2 个模型/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存新版本" })).toBeEnabled();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "模型" }));
  expect(await screen.findByTitle("deepseek-reasoner")).toBeInTheDocument();
  expect(screen.queryByTitle("stale-openai-model")).not.toBeInTheDocument();
  expect(listModels).toHaveBeenNthCalledWith(1, {
    provider: "openai_compatible",
    api_key: "older-openai-key",
  });
  expect(listModels).toHaveBeenNthCalledWith(2, {
    provider: "deepseek",
    api_key: "current-deepseek-key",
  });
});
