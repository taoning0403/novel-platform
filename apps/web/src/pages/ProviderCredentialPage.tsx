import { Alert, Button, Input, Select, Switch, Tag } from "antd";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { api, userFacingError } from "../api/client";
import type {
  ProviderCredentialStatus,
  ProviderCredentialUpdate,
  ProviderKind,
} from "../api/types";
import { ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./ProviderCredentialPage.module.css";

const emptyUsage = {
  all_time: {
    request_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  },
  current_month: {
    request_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  },
};

const providerPresets: Record<
  Exclude<ProviderKind, "custom">,
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

const providerOptions = [
  ...Object.entries(providerPresets).map(([value, preset]) => ({
    value: value as Exclude<ProviderKind, "custom">,
    label: preset.label,
    title: preset.label,
  })),
  {
    value: "custom" as const,
    label: "自定义 Provider",
    title: "自定义 Provider",
  },
];

const emptyCredential: ProviderCredentialStatus = {
  configured: false,
  provider: "openai_compatible",
  provider_name: providerPresets.openai_compatible.label,
  base_url: providerPresets.openai_compatible.baseUrl,
  model: null,
  thinking_enabled: false,
  version: null,
  updated_at: null,
  usage: emptyUsage,
};

function formatUsageCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
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

function supportsThinking(provider: ProviderKind, model: string): boolean {
  return (
    provider === "deepseek"
    || (provider === "kimi" && model.trim() === "kimi-k2.5")
  );
}

function normalizeThinkingEnabled(
  provider: ProviderKind,
  model: string,
  enabled: boolean,
): boolean {
  if (provider === "deepseek" && model.trim() === "deepseek-reasoner") {
    return true;
  }
  return supportsThinking(provider, model) && enabled;
}

export function ProviderCredentialPage() {
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null);
  const [provider, setProvider] = useState<ProviderKind>("openai_compatible");
  const [model, setModel] = useState("");
  const [modelCatalog, setModelCatalog] = useState<string[]>([]);
  const [customName, setCustomName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const catalogRequestId = useRef(0);

  const invalidateModelCatalog = useCallback(() => {
    catalogRequestId.current += 1;
    setModelCatalog([]);
    setModel("");
    setThinkingEnabled(false);
    setIsLoadingModels(false);
    setCatalogError(null);
  }, []);

  const syncFormWithCredential = useCallback((next: ProviderCredentialStatus) => {
    setProvider(next.provider);
    invalidateModelCatalog();
    if (next.provider === "custom") {
      setCustomName(next.provider_name);
      setBaseUrl(next.base_url);
    }
  }, [invalidateModelCatalog]);

  const loadCredential = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const nextCredential = await api.getProviderCredential();
      setCredential(nextCredential);
      syncFormWithCredential(nextCredential);
    } catch (caught) {
      setLoadError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [syncFormWithCredential]);

  useEffect(() => {
    void loadCredential();
  }, [loadCredential]);

  async function loadModelCatalog() {
    const submittedApiKey = apiKey;
    const submittedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
    if (submittedApiKey.trim() === "") {
      setCatalogError("请先输入 API Key。");
      return;
    }
    if (provider === "custom" && !isSafeCustomBaseUrl(submittedBaseUrl)) {
      setCatalogError(
        "自定义 Base URL 必须是 HTTPS 地址，且不能包含用户名、密码、查询参数或片段。",
      );
      return;
    }

    const requestProvider = provider;
    const requestId = catalogRequestId.current + 1;
    catalogRequestId.current = requestId;
    setModelCatalog([]);
    setModel("");
    setThinkingEnabled(false);
    setIsLoadingModels(true);
    setCatalogError(null);
    setError(null);
    setMessage(null);

    try {
      const result = await api.listProviderModels(
        requestProvider === "custom"
          ? {
              provider: requestProvider,
              api_key: submittedApiKey,
              base_url: submittedBaseUrl,
            }
          : {
              provider: requestProvider,
              api_key: submittedApiKey,
            },
      );
      if (catalogRequestId.current !== requestId) return;
      if (result.provider !== requestProvider) {
        setCatalogError("返回的模型目录与当前 Provider 不一致，请检查配置后重试。");
        return;
      }
      if (result.models.length === 0) {
        setCatalogError("该 Provider 未返回可用模型，请检查 API Key 和地址。");
        return;
      }
      setModelCatalog(result.models);
    } catch (caught) {
      if (catalogRequestId.current !== requestId) return;
      setCatalogError(`${userFacingError(caught)} API Key 仍保留在当前页面，可修改后重试。`);
    } finally {
      if (catalogRequestId.current === requestId) {
        setIsLoadingModels(false);
      }
    }
  }

  async function saveCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedApiKey = apiKey;
    const submittedModel = model;
    const submittedCustomName = customName.trim();
    const submittedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
    if (
      submittedApiKey.trim() === ""
      || submittedModel === ""
      || !modelCatalog.includes(submittedModel)
    ) return;
    if (provider === "custom") {
      if (submittedCustomName === "") {
        setError("请为自定义 Provider 输入一个名称。");
        return;
      }
      if (!isSafeCustomBaseUrl(submittedBaseUrl)) {
        setError("自定义 Base URL 必须是 HTTPS 地址，且不能包含用户名、密码、查询参数或片段。");
        return;
      }
    }

    const payload: ProviderCredentialUpdate = provider === "custom"
      ? {
          api_key: submittedApiKey,
          provider,
          model: submittedModel,
          base_url: submittedBaseUrl,
          custom_name: submittedCustomName,
          thinking_enabled: normalizeThinkingEnabled(
            provider,
            submittedModel,
            thinkingEnabled,
          ),
        }
      : {
          api_key: submittedApiKey,
          provider,
          model: submittedModel,
          thinking_enabled: normalizeThinkingEnabled(
            provider,
            submittedModel,
            thinkingEnabled,
          ),
        };

    // Clear the only React copy before the request begins. It is never restored on failure.
    setApiKey("");
    invalidateModelCatalog();
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const nextCredential = await api.updateProviderCredential(payload);
      setCredential(nextCredential);
      syncFormWithCredential(nextCredential);
      setMessage(
        credential?.configured
          ? `新的 ${nextCredential.provider_name} 凭据版本已加密保存；新任务将使用它。`
          : `${nextCredential.provider_name} 凭据已加密保存，可以发起翻译任务。`,
      );
    } catch (caught) {
      setError(`${userFacingError(caught)} 输入内容已从页面清除，请重新输入。`);
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteCredential() {
    setApiKey("");
    invalidateModelCatalog();
    setIsDeleting(true);
    setError(null);
    setMessage(null);
    try {
      await api.deleteProviderCredential();
      setCredential((current) => current
        ? {
            ...current,
            configured: false,
            model: null,
            thinking_enabled: false,
            version: null,
            updated_at: new Date().toISOString(),
          }
        : emptyCredential);
      setMessage("Provider 凭据已撤销。新任务和未完成任务都不能再使用已删除的版本。");
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsDeleting(false);
    }
  }

  if (isLoading) {
    return (
      <main className={styles.page}>
        <LoadingBlock label="正在读取 Provider 凭据状态…" />
      </main>
    );
  }

  if (loadError || credential === null) {
    return (
      <main className={styles.page}>
        <ErrorNotice
          message={loadError ?? "无法读取 Provider 凭据状态。"}
          onRetry={() => void loadCredential()}
        />
      </main>
    );
  }

  const usage = credential.usage;
  const hasCurrentMonthUsage = (
    usage.current_month.request_count > 0 || usage.current_month.total_tokens > 0
  );
  const selectedProviderName = provider === "custom"
    ? customName.trim() || "自定义 Provider"
    : providerPresets[provider].label;
  const selectedBaseUrl = provider === "custom"
    ? baseUrl
    : providerPresets[provider].baseUrl;
  const keyLabel = `${selectedProviderName} API Key`;
  const selectedModelAvailable = model !== "" && modelCatalog.includes(model);
  const deepSeekThinkingModelsAvailable = (
    modelCatalog.includes("deepseek-chat")
    && modelCatalog.includes("deepseek-reasoner")
  );
  const thinkingSupported = selectedModelAvailable && supportsThinking(provider, model);
  const thinkingHelp = model === ""
    ? "先读取模型列表并选择模型；支持时可在这里开启思考模式。"
    : provider === "deepseek"
      ? deepSeekThinkingModelsAvailable
        ? "默认关闭。开启后模型会切换为 deepseek-reasoner，可能需要更多响应时间和 Token。"
        : "当前模型目录未同时提供 deepseek-chat 和 deepseek-reasoner，无法切换思考模式。"
    : provider === "kimi"
      ? thinkingSupported
        ? "默认关闭。开启后 Kimi 可能需要更多响应时间，并产生更多 Token 消耗。"
        : "Kimi 仅在模型为 kimi-k2.5 时支持思考模式；当前模型会保持关闭。"
      : "当前 Provider 没有可验证的统一开关，思考模式保持关闭。";
  const thinkingControlDisabled = (
    isSaving
    || isDeleting
    || isLoadingModels
    || !thinkingSupported
    || (provider === "deepseek" && !deepSeekThinkingModelsAvailable)
  );
  const canLoadModels = (
    apiKey.trim() !== ""
    && (provider !== "custom" || baseUrl.trim() !== "")
  );

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="翻译设置"
        title="我的 Provider 凭据"
        description="选择 OpenAI、DeepSeek、Kimi 或自定义兼容服务，为小说翻译配置自己的 API Key；实际 Token 费用由你的 Provider 账户承担。"
        secondaryActions={<Button href="/translations">返回翻译任务</Button>}
      />

      <section className={styles.status} aria-labelledby="credential-status-heading">
        <div className={styles.statusCopy}>
          <p className={styles.sectionLabel}>当前状态</p>
          <h2 id="credential-status-heading">
            {credential.configured ? "凭据已配置" : "尚未配置凭据"}
          </h2>
          <p>
            {credential.configured
              ? "漫读只显示非秘密配置、状态与版本，不会显示、回填或提供找回原始 API Key。"
              : "配置后才能创建翻译任务；缺少凭据时不会改用管理员 Key。"}
          </p>
        </div>
        <dl className={styles.statusMeta}>
          <div>
            <dt>Provider</dt>
            <dd>{credential.configured ? credential.provider_name : "—"}</dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd>{credential.configured ? credential.model ?? "—" : "—"}</dd>
          </div>
          <div className={styles.endpointMeta}>
            <dt>API Base URL</dt>
            <dd>{credential.configured ? credential.base_url : "—"}</dd>
          </div>
          <div>
            <dt>思考模式</dt>
            <dd>
              {credential.configured
                ? credential.thinking_enabled ? "开启" : "关闭"
                : "—"}
            </dd>
          </div>
          <div>
            <dt>凭据版本</dt>
            <dd>{credential.version === null ? "—" : `v${credential.version}`}</dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{credential.updated_at ? formatDate(credential.updated_at) : "—"}</dd>
          </div>
          <div>
            <dt>可用状态</dt>
            <dd>
              <Tag color={credential.configured ? "success" : "default"}>
                {credential.configured ? "可用于新任务" : "需要配置"}
              </Tag>
            </dd>
          </div>
        </dl>
      </section>

      <section className={styles.usage} aria-labelledby="provider-usage-heading">
        <div className={styles.usageCopy}>
          <p className={styles.sectionLabel}>Relay 用量</p>
          <h2 id="provider-usage-heading">Provider 调用记录</h2>
          <p>
            {hasCurrentMonthUsage
              ? "这里只统计经漫读 Relay 完成的请求与 Token；最终费用以 Provider 账单为准。"
              : "本月还没有通过漫读 Relay 发起的 Provider 请求。"}
          </p>
        </div>
        <dl className={styles.usageTotals}>
          <div>
            <dt>本月请求</dt>
            <dd>{formatUsageCount(usage.current_month.request_count)}</dd>
          </div>
          <div>
            <dt>本月总 Token</dt>
            <dd>{formatUsageCount(usage.current_month.total_tokens)}</dd>
          </div>
          <div>
            <dt>累计请求</dt>
            <dd>{formatUsageCount(usage.all_time.request_count)}</dd>
          </div>
          <div>
            <dt>累计总 Token</dt>
            <dd>{formatUsageCount(usage.all_time.total_tokens)}</dd>
          </div>
        </dl>
      </section>

      <div className={styles.workspace}>
        <section className={styles.formSurface} aria-labelledby="credential-form-heading">
          <p className={styles.sectionLabel}>
            {credential.configured ? "轮换凭据" : "添加凭据"}
          </p>
          <h2 id="credential-form-heading">
            {credential.configured ? "保存新的 Provider 配置" : "配置你的 Provider"}
          </h2>
          <p className={styles.supportingCopy} id="provider-key-help">
            API Key 只提交给漫读 Server 加密保存。Provider、模型和地址会作为非秘密配置显示，
            但保存后本页不会再次展示 API Key。
          </p>

          <form
            className={styles.form}
            autoComplete="off"
            onSubmit={(event) => void saveCredential(event)}
          >
            <div className={styles.configurationFields}>
              <label className={styles.field} htmlFor="provider-kind">
                Provider
                <Select
                  id="provider-kind"
                  aria-label="Provider"
                  aria-describedby="provider-choice-help"
                  options={providerOptions}
                  value={provider}
                  onChange={(value: ProviderKind) => {
                    setProvider(value);
                    setApiKey("");
                    invalidateModelCatalog();
                    setError(null);
                    setMessage(null);
                  }}
                  disabled={isSaving || isDeleting}
                />
                <span className={styles.fieldHelp} id="provider-choice-help">
                  预设 Provider 使用固定官方地址；自定义服务必须兼容 OpenAI Chat Completions。
                </span>
              </label>

              {provider === "custom" ? (
                <>
                  <label className={styles.field} htmlFor="provider-custom-name">
                    自定义名称
                    <Input
                      id="provider-custom-name"
                      name="provider-custom-name"
                      autoComplete="off"
                      maxLength={120}
                      placeholder="例如 我的兼容服务"
                      value={customName}
                      onChange={(event) => setCustomName(event.target.value)}
                      disabled={isSaving || isDeleting}
                      required
                    />
                  </label>
                  <label
                    className={`${styles.field} ${styles.customEndpointField}`}
                    htmlFor="provider-base-url"
                  >
                    API Base URL
                    <Input
                      className={styles.technicalInput}
                      id="provider-base-url"
                      name="provider-base-url"
                      type="url"
                      inputMode="url"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      maxLength={2048}
                      placeholder="https://provider.example.com/v1"
                      aria-label="API Base URL"
                      aria-describedby="provider-base-url-help"
                      value={baseUrl}
                      onChange={(event) => {
                        setBaseUrl(event.target.value);
                        setApiKey("");
                        invalidateModelCatalog();
                        setError(null);
                        setMessage(null);
                      }}
                      disabled={isSaving || isDeleting}
                      required
                    />
                    <span className={styles.fieldHelp} id="provider-base-url-help">
                      仅接受管理员已允许，且不含凭据、查询参数或片段的 HTTPS 地址。
                    </span>
                  </label>
                </>
              ) : (
                <div className={styles.presetEndpoint} aria-live="polite">
                  <span>API Base URL</span>
                  <code>{selectedBaseUrl}</code>
                </div>
              )}
            </div>

            <div className={styles.secretRow}>
              <label className={styles.field} htmlFor="provider-api-key">
                {keyLabel}
                <Input
                  className={styles.technicalInput}
                  id="provider-api-key"
                  name="provider-api-key"
                  type="password"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={8192}
                  aria-describedby="provider-key-help"
                  value={apiKey}
                  onChange={(event) => {
                    setApiKey(event.target.value);
                    invalidateModelCatalog();
                    setError(null);
                    setMessage(null);
                  }}
                  disabled={isSaving || isDeleting}
                  required
                />
              </label>
              <Button
                htmlType="button"
                loading={isLoadingModels}
                disabled={!canLoadModels || isSaving || isDeleting}
                onClick={() => void loadModelCatalog()}
              >
                读取模型列表
              </Button>
            </div>

            {catalogError ? (
              <Alert
                className={styles.catalogNotice}
                type="error"
                showIcon
                title={catalogError}
                role="alert"
              />
            ) : null}

            <div className={styles.modelSettings}>
              <label className={styles.field} htmlFor="provider-model">
                模型
                <Select
                  id="provider-model"
                  aria-label="模型"
                  aria-describedby="provider-model-help"
                  className={styles.technicalSelect}
                  showSearch
                  allowClear
                  optionFilterProp="label"
                  options={modelCatalog.map((modelId) => ({
                    value: modelId,
                    label: modelId,
                    title: modelId,
                  }))}
                  placeholder="先读取模型列表"
                  notFoundContent={
                    modelCatalog.length === 0 ? "请先读取模型列表" : "没有匹配的模型"
                  }
                  value={model || undefined}
                  onChange={(nextModel: string | undefined) => {
                    const selectedModel = nextModel ?? "";
                    setModel(selectedModel);
                    setThinkingEnabled(
                      provider === "deepseek"
                      && selectedModel === "deepseek-reasoner",
                    );
                    setError(null);
                    setMessage(null);
                  }}
                  disabled={(
                    isSaving
                    || isDeleting
                    || isLoadingModels
                    || modelCatalog.length === 0
                    || (provider === "deepseek" && thinkingEnabled)
                  )}
                />
                <span className={styles.fieldHelp} id="provider-model-help" role="status">
                  {modelCatalog.length > 0
                    ? `已读取 ${modelCatalog.length} 个模型；只能保存当前列表中的模型。`
                    : "输入当前 Provider 的 API Key，读取列表后再选择模型。"}
                </span>
              </label>

              <div className={styles.thinkingSetting}>
                <div>
                  <span className={styles.thinkingLabel} id="provider-thinking-label">
                    思考模式
                  </span>
                  <span className={styles.thinkingHelp} id="provider-thinking-help">
                    {thinkingHelp}
                  </span>
                </div>
                <label
                  className={styles.switchTarget}
                  htmlFor="provider-thinking-enabled"
                  data-disabled={thinkingControlDisabled}
                >
                  <Switch
                    id="provider-thinking-enabled"
                    aria-labelledby="provider-thinking-label"
                    aria-describedby="provider-thinking-help"
                    checked={thinkingSupported && thinkingEnabled}
                    onChange={(checked) => {
                      setThinkingEnabled(checked);
                      if (provider === "deepseek") {
                        const nextModel = checked
                          ? "deepseek-reasoner"
                          : "deepseek-chat";
                        if (modelCatalog.includes(nextModel)) {
                          setModel(nextModel);
                        }
                      }
                    }}
                    disabled={thinkingControlDisabled}
                  />
                </label>
              </div>
            </div>

            <div className={styles.saveRow}>
              <Button
                type="primary"
                htmlType="submit"
                loading={isSaving}
                disabled={(
                  apiKey.trim() === ""
                  || !selectedModelAvailable
                  || (
                    provider === "custom"
                    && (customName.trim() === "" || baseUrl.trim() === "")
                  )
                  || isLoadingModels
                  || isDeleting
                )}
              >
                {credential.configured ? "保存新版本" : "保存并启用"}
              </Button>
            </div>
          </form>

          {message ? (
            <Alert
              className={styles.notice}
              type="success"
              showIcon
              title={message}
              role="status"
            />
          ) : null}
          {error ? (
            <Alert
              className={styles.notice}
              type="error"
              showIcon
              title={error}
              role="alert"
            />
          ) : null}
        </section>

        <aside className={styles.impact} aria-labelledby="credential-impact-heading">
          <p className={styles.sectionLabel}>费用与变更</p>
          <h2 id="credential-impact-heading">变更前先确认影响</h2>
          <ul>
            <li>
              <strong>费用归属</strong>
              <span>
                你发起的请求使用所选 {selectedProviderName} 配置，
                Token 费用计入你的 Provider 账户。
              </span>
            </li>
            <li>
              <strong>轮换</strong>
              <span>
                保存新版本后，新任务使用新的 Provider、模型和 Key；
                已创建的任务继续使用创建时绑定的旧版本。
              </span>
            </li>
            <li>
              <strong>删除</strong>
              <span>所有版本会立即撤销。未完成任务的后续 Provider 调用将失败，已生成的本地译本不受影响。</span>
            </li>
          </ul>
          <DestructiveAction
            label="删除 Provider 凭据"
            title="删除全部 Provider 凭据？"
            description="所有版本都会撤销；未完成任务无法继续调用 Provider，且此操作不能恢复原始 API Key。"
            onConfirm={deleteCredential}
            loading={isDeleting}
            disabled={!credential.configured || isSaving}
          />
        </aside>
      </div>
    </main>
  );
}
