import { Alert, Button, Input, Tag } from "antd";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";

import { api, userFacingError } from "../api/client";
import type { ProviderCredentialStatus } from "../api/types";
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

const emptyCredential: ProviderCredentialStatus = {
  configured: false,
  provider: "openai_compatible",
  version: null,
  updated_at: null,
  usage: emptyUsage,
};

function formatUsageCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function ProviderCredentialPage() {
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadCredential = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      setCredential(await api.getProviderCredential());
    } catch (caught) {
      setLoadError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCredential();
  }, [loadCredential]);

  async function saveCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedApiKey = apiKey;
    if (submittedApiKey.trim() === "") return;

    // Clear the only React copy before the request begins. It is never restored on failure.
    setApiKey("");
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const nextCredential = await api.updateProviderCredential({
        api_key: submittedApiKey,
      });
      setCredential(nextCredential);
      setMessage(
        credential?.configured
          ? "新的凭据版本已加密保存；新任务将使用它。"
          : "Provider 凭据已加密保存，可以发起翻译任务。",
      );
    } catch (caught) {
      setError(`${userFacingError(caught)} 输入内容已从页面清除，请重新输入。`);
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteCredential() {
    setApiKey("");
    setIsDeleting(true);
    setError(null);
    setMessage(null);
    try {
      await api.deleteProviderCredential();
      setCredential((current) => ({
        ...emptyCredential,
        updated_at: new Date().toISOString(),
        usage: current?.usage ?? emptyUsage,
      }));
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

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="翻译设置"
        title="我的 Provider 凭据"
        description="为你发起的小说翻译配置自己的 OpenAI-compatible API Key；实际 Token 费用由你的 Provider 账户承担。"
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
              ? "漫读只显示状态与版本，不会显示、回填或提供找回原始 API Key。"
              : "配置后才能创建翻译任务；缺少凭据时不会改用管理员 Key。"}
          </p>
        </div>
        <dl className={styles.statusMeta}>
          <div>
            <dt>Provider</dt>
            <dd>OpenAI-compatible</dd>
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
            {credential.configured ? "保存新的 API Key" : "输入你的 API Key"}
          </h2>
          <p className={styles.supportingCopy} id="provider-key-help">
            API Key 只提交给漫读 Server 加密保存。保存完成后，本页不会再次展示它。
          </p>

          <form
            className={styles.form}
            autoComplete="off"
            onSubmit={(event) => void saveCredential(event)}
          >
            <label className={styles.field} htmlFor="provider-api-key">
              OpenAI-compatible API Key
              <Input
                id="provider-api-key"
                name="provider-api-key"
                type="password"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={8192}
                aria-describedby="provider-key-help"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                disabled={isSaving || isDeleting}
                required
              />
            </label>
            <Button
              type="primary"
              htmlType="submit"
              loading={isSaving}
              disabled={apiKey.trim() === "" || isDeleting}
            >
              {credential.configured ? "保存新版本" : "保存并启用"}
            </Button>
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
              <span>你发起的 Provider 请求使用这把 Key，Token 费用计入你的 Provider 账户。</span>
            </li>
            <li>
              <strong>轮换</strong>
              <span>保存新版本后，新任务使用新版本；已创建的任务继续使用创建时绑定的旧版本。</span>
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
