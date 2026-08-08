import type {
  ProviderCredentialStatus,
  ProviderCredentialUpdate,
  ProviderKind,
  ProviderModelCatalogRequest,
} from "../../api/types";

type PresetProviderKind = Exclude<ProviderKind, "custom">;

const invalidCustomBaseUrlMessage =
  "自定义 Base URL 必须是 HTTPS 地址，且不能包含用户名、密码、查询参数或片段。";

export const providerPresets: Record<
  PresetProviderKind,
  { label: string; baseUrl: string }
> = {
  openai_compatible: {
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
  },
  deepseek: {
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
  },
  kimi: {
    label: "Kimi",
    baseUrl: "https://api.moonshot.cn/v1",
  },
};

export const providerOptions = [
  ...Object.entries(providerPresets).map(([value, preset]) => ({
    value: value as PresetProviderKind,
    label: preset.label,
    title: preset.label,
  })),
  {
    value: "custom" as const,
    label: "自定义 Provider",
    title: "自定义 Provider",
  },
];

export interface CredentialFormState {
  provider: ProviderKind;
  model: string;
  modelCatalog: string[];
  customName: string;
  baseUrl: string;
  thinkingEnabled: boolean;
}

export const initialCredentialFormState: CredentialFormState = {
  provider: "openai_compatible",
  model: "",
  modelCatalog: [],
  customName: "",
  baseUrl: "",
  thinkingEnabled: false,
};

export type CredentialFormEvent =
  | { type: "credentialSynced"; credential: ProviderCredentialStatus }
  | { type: "providerChanged"; provider: ProviderKind }
  | { type: "customNameChanged"; customName: string }
  | { type: "baseUrlChanged"; baseUrl: string }
  | { type: "catalogInvalidated" }
  | { type: "catalogLoaded"; models: string[] }
  | { type: "modelSelected"; model: string }
  | { type: "thinkingToggled"; enabled: boolean };

function withoutCatalog(state: CredentialFormState): CredentialFormState {
  return {
    ...state,
    model: "",
    modelCatalog: [],
    thinkingEnabled: false,
  };
}

function withCredential(
  state: CredentialFormState,
  credential: ProviderCredentialStatus,
): CredentialFormState {
  const reset = withoutCatalog(state);
  if (credential.provider !== "custom") {
    return { ...reset, provider: credential.provider };
  }
  return {
    ...reset,
    provider: credential.provider,
    customName: credential.provider_name,
    baseUrl: credential.base_url,
  };
}

function withSelectedModel(
  state: CredentialFormState,
  model: string,
): CredentialFormState {
  return {
    ...state,
    model,
    thinkingEnabled: state.provider === "deepseek" && model === "deepseek-reasoner",
  };
}

function withThinking(
  state: CredentialFormState,
  enabled: boolean,
): CredentialFormState {
  if (state.provider !== "deepseek") {
    return { ...state, thinkingEnabled: enabled };
  }
  const model = enabled ? "deepseek-reasoner" : "deepseek-chat";
  return {
    ...state,
    thinkingEnabled: enabled,
    model: state.modelCatalog.includes(model) ? model : state.model,
  };
}

export function credentialFormReducer(
  state: CredentialFormState,
  event: CredentialFormEvent,
): CredentialFormState {
  switch (event.type) {
    case "credentialSynced":
      return withCredential(state, event.credential);
    case "providerChanged":
      return { ...withoutCatalog(state), provider: event.provider };
    case "customNameChanged":
      return { ...state, customName: event.customName };
    case "baseUrlChanged":
      return { ...withoutCatalog(state), baseUrl: event.baseUrl };
    case "catalogInvalidated":
      return withoutCatalog(state);
    case "catalogLoaded":
      return { ...state, modelCatalog: event.models };
    case "modelSelected":
      return withSelectedModel(state, event.model);
    case "thinkingToggled":
      return withThinking(state, event.enabled);
  }
}

function isSafeCustomBaseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:"
      && url.username === ""
      && url.password === ""
      && url.search === ""
      && url.hash === ""
    );
  } catch {
    return false;
  }
}

function normalizedBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function supportsThinking(provider: ProviderKind, model: string): boolean {
  return (
    provider === "deepseek"
    || (provider === "kimi" && model.trim() === "kimi-k2.5")
  );
}

function normalizedThinkingEnabled(state: CredentialFormState): boolean {
  if (state.provider === "deepseek" && state.model.trim() === "deepseek-reasoner") {
    return true;
  }
  return supportsThinking(state.provider, state.model) && state.thinkingEnabled;
}

export function providerPresentation(state: CredentialFormState): {
  name: string;
  baseUrl: string;
  keyLabel: string;
} {
  const name = state.provider === "custom"
    ? state.customName.trim() || "自定义 Provider"
    : providerPresets[state.provider].label;
  const baseUrl = state.provider === "custom"
    ? state.baseUrl
    : providerPresets[state.provider].baseUrl;
  return { name, baseUrl, keyLabel: `${name} API Key` };
}

export function selectedModelIsAvailable(state: CredentialFormState): boolean {
  return state.model !== "" && state.modelCatalog.includes(state.model);
}

export function thinkingPresentation(state: CredentialFormState): {
  supported: boolean;
  deepSeekModelsAvailable: boolean;
  help: string;
} {
  const supported = selectedModelIsAvailable(state)
    && supportsThinking(state.provider, state.model);
  const deepSeekModelsAvailable = (
    state.modelCatalog.includes("deepseek-chat")
    && state.modelCatalog.includes("deepseek-reasoner")
  );
  if (state.model === "") {
    return {
      supported,
      deepSeekModelsAvailable,
      help: "先读取模型列表并选择模型；支持时可在这里开启思考模式。",
    };
  }
  if (state.provider === "deepseek") {
    return {
      supported,
      deepSeekModelsAvailable,
      help: deepSeekModelsAvailable
        ? "默认关闭。开启后模型会切换为 deepseek-reasoner，可能需要更多响应时间和 Token。"
        : "当前模型目录未同时提供 deepseek-chat 和 deepseek-reasoner，无法切换思考模式。",
    };
  }
  if (state.provider === "kimi") {
    return {
      supported,
      deepSeekModelsAvailable,
      help: supported
        ? "默认关闭。开启后 Kimi 可能需要更多响应时间，并产生更多 Token 消耗。"
        : "Kimi 仅在模型为 kimi-k2.5 时支持思考模式；当前模型会保持关闭。",
    };
  }
  return {
    supported,
    deepSeekModelsAvailable,
    help: "当前 Provider 没有可验证的统一开关，思考模式保持关闭。",
  };
}

export function canLoadModelCatalog(
  state: CredentialFormState,
  apiKey: string,
): boolean {
  return (
    apiKey.trim() !== ""
    && (state.provider !== "custom" || state.baseUrl.trim() !== "")
  );
}

export function canSubmitCredential(
  state: CredentialFormState,
  apiKey: string,
): boolean {
  if (apiKey.trim() === "" || !selectedModelIsAvailable(state)) return false;
  return state.provider !== "custom"
    || (state.customName.trim() !== "" && state.baseUrl.trim() !== "");
}

export type ModelCatalogRequestDecision =
  | { kind: "ready"; provider: ProviderKind; request: ProviderModelCatalogRequest }
  | { kind: "error"; message: string };

export function modelCatalogRequest(
  state: CredentialFormState,
  apiKey: string,
): ModelCatalogRequestDecision {
  if (apiKey.trim() === "") {
    return { kind: "error", message: "请先输入 API Key。" };
  }
  const baseUrl = normalizedBaseUrl(state.baseUrl);
  if (state.provider === "custom" && !isSafeCustomBaseUrl(baseUrl)) {
    return {
      kind: "error",
      message: invalidCustomBaseUrlMessage,
    };
  }
  const request: ProviderModelCatalogRequest = state.provider === "custom"
    ? { provider: state.provider, api_key: apiKey, base_url: baseUrl }
    : { provider: state.provider, api_key: apiKey };
  return { kind: "ready", provider: state.provider, request };
}

export type CredentialUpdateDecision =
  | { kind: "incomplete" }
  | { kind: "error"; message: string }
  | { kind: "ready"; payload: ProviderCredentialUpdate };

export function credentialUpdate(
  state: CredentialFormState,
  apiKey: string,
): CredentialUpdateDecision {
  if (apiKey.trim() === "" || !selectedModelIsAvailable(state)) {
    return { kind: "incomplete" };
  }
  const customName = state.customName.trim();
  const baseUrl = normalizedBaseUrl(state.baseUrl);
  if (state.provider === "custom" && customName === "") {
    return { kind: "error", message: "请为自定义 Provider 输入一个名称。" };
  }
  if (state.provider === "custom" && !isSafeCustomBaseUrl(baseUrl)) {
    return {
      kind: "error",
      message: invalidCustomBaseUrlMessage,
    };
  }
  const common = {
    api_key: apiKey,
    provider: state.provider,
    model: state.model,
    thinking_enabled: normalizedThinkingEnabled(state),
  };
  const payload: ProviderCredentialUpdate = state.provider === "custom"
    ? { ...common, base_url: baseUrl, custom_name: customName }
    : common;
  return { kind: "ready", payload };
}
