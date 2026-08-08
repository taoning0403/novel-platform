import { Alert, Button, Descriptions, Input, Modal, Spin, Tag } from "antd";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError, api, userFacingError } from "../../api/client";
import type {
  BookDetail,
  Edition,
  ProviderCredentialStatus,
  TranslationRun,
  TranslationServiceStatus,
} from "../../api/types";
import { randomUuid } from "../../shared/uuid";
import styles from "./TranslationLaunchModal.module.css";

interface TranslationLaunchModalProps {
  book: BookDetail;
  edition: Edition | null;
  open: boolean;
  onClose: () => void;
  onCreated: (run: TranslationRun) => void | Promise<void>;
}

const emptyUsage: ProviderCredentialStatus["usage"] = {
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

export function TranslationLaunchModal({
  book,
  edition,
  open,
  onClose,
  onCreated,
}: TranslationLaunchModalProps) {
  const source = useMemo(() => {
    if (edition?.content_role === "source") return edition;
    return book.editions.find((item) => item.id === edition?.source_edition_id) ?? null;
  }, [book.editions, edition]);
  const isRetranslation = edition?.creation_method === "generated";
  const isEpub = source?.current_file?.file_format === "epub";
  const [service, setService] = useState<TranslationServiceStatus | null>(null);
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [editionTitle, setEditionTitle] = useState("");
  const [clientRequestId, setClientRequestId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || edition === null) return;
    let cancelled = false;
    setTargetLanguage("en");
    setEditionTitle(
      isRetranslation
        ? `${edition.title} · 重译`
        : `${book.canonical_title} · 英文译本`,
    );
    setClientRequestId(randomUuid());
    setError(null);
    setService(null);
    setCredential(null);
    setIsChecking(true);
    const sourceFormat = source?.current_file?.file_format;
    if (sourceFormat !== "epub" && sourceFormat !== "txt") {
      setError("找不到可翻译的 EPUB 或 TXT 原文文件。");
      setIsChecking(false);
      return;
    }
    void Promise.all([
      api.translationServiceStatus(sourceFormat),
      api.getProviderCredential(),
    ])
      .then(([nextService, nextCredential]) => {
        if (!cancelled) {
          setService(nextService);
          setCredential(nextCredential);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(userFacingError(caught));
      })
      .finally(() => {
        if (!cancelled) setIsChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [book.canonical_title, edition, isRetranslation, open, source]);

  const usableCredential = credential?.configured === true
    && typeof credential.model === "string"
    && credential.model.trim() !== ""
    ? {
        providerName: credential.provider_name,
        model: credential.model,
        thinkingEnabled: credential.thinking_enabled,
        version: credential.version,
      }
    : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      source === null
      || clientRequestId === ""
      || service?.available !== true
      || usableCredential === null
    ) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const run = await api.createTranslationRun(book.id, source.id, {
        target_language: targetLanguage.trim(),
        edition_title: editionTitle.trim(),
        client_request_id: clientRequestId,
        ...(isRetranslation && edition
          ? { supersedes_edition_id: edition.id }
          : {}),
      });
      await onCreated(run);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "provider_credential_required") {
        setCredential({
          configured: false,
          provider: "openai_compatible",
          provider_name: "OpenAI",
          base_url: "https://api.openai.com/v1",
          model: null,
          thinking_enabled: false,
          version: null,
          updated_at: null,
          usage: credential?.usage ?? emptyUsage,
        });
      }
      setError(userFacingError(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  const serviceLabel = service?.available
    ? `${service.provider_name ?? service.provider_id}${service.provider_model ? ` · ${service.provider_model}` : ""}`
    : "服务尚未就绪";

  return (
    <Modal
      className={styles.modal}
      title={isRetranslation ? "重新翻译小说" : "翻译小说"}
      open={open}
      onCancel={isSubmitting ? undefined : onClose}
      footer={null}
      width={680}
      destroyOnHidden
    >
      {edition === null ? null : (
        <form className={styles.form} onSubmit={(event) => void submit(event)}>
          <p className={styles.intro}>
            {isEpub
              ? "翻译会保留 EPUB 的章节顺序、目录、链接、图片与样式，并生成独立 EPUB 草稿；现有版本和阅读进度不会被覆盖。"
              : isRetranslation
              ? "新译本会作为独立草稿保留，现有版本、阅读进度和首选设置不会被覆盖。"
              : "翻译完成后会生成独立草稿；只有管理员审核后，其他阅读者才能看到。"}
          </p>

          {source ? (
            <Descriptions
              className={styles.snapshot}
              size="small"
              column={{ xs: 1, sm: 2 }}
              items={[
                { key: "book", label: "作品", children: book.canonical_title },
                { key: "source", label: "原文版本", children: source.title },
                { key: "book-contributor", label: "作品上传人", children: book.contributor.display_name },
                { key: "source-contributor", label: "原文上传人", children: source.contributor.display_name },
                {
                  key: "file",
                  label: "固定文件快照",
                  children: source.current_file
                    ? `f${source.current_file.revision} · ${source.current_file.file_format.toUpperCase()}`
                    : "文件不可用",
                },
                { key: "language", label: "原文语言", children: source.language },
              ]}
            />
          ) : (
            <Alert type="error" showIcon title="找不到可翻译的原文版本。" />
          )}

          <section className={styles.service} aria-live="polite">
            <div>
              <span>私有翻译 Relay</span>
              {isChecking ? <Spin size="small" /> : (
                <Tag color={service?.available ? "success" : "default"}>{serviceLabel}</Tag>
              )}
            </div>
            {service?.available ? (
              <small>
                LinguaSpindle {service.version ?? "未知版本"} · {service.source_format.toUpperCase()} · {service.pipeline_key}
                {service.pipeline_version ? ` ${service.pipeline_version}` : ""}
                {usableCredential
                  ? ` · ${usableCredential.providerName} · ${usableCredential.model}${usableCredential.thinkingEnabled ? " · 思考模式" : ""} · 个人凭据 v${usableCredential.version ?? "—"}`
                  : ""}
              </small>
            ) : null}
          </section>

          {service && !service.available ? (
            <Alert
              type="warning"
              showIcon
              title={service.error_message ?? "小说翻译服务暂不可用。"}
            />
          ) : null}

          {!isChecking && credential !== null && usableCredential === null ? (
            <Alert
              type="warning"
              showIcon
              title="先配置你的 Provider 凭据"
              description="漫读不会改用管理员 Key。选择 Provider、模型并配置自己的 API Key 后，新任务产生的 Token 费用计入你的 Provider 账户。"
              action={(
                <Button href="/settings/provider-credential">
                  去配置
                </Button>
              )}
            />
          ) : null}

          <div className={styles.fields}>
            <label className={styles.field} htmlFor="translation-target-language">
              目标语言
              <Input
                id="translation-target-language"
                required
                maxLength={100}
                autoComplete="off"
                placeholder="例如 en、ja、zh-TW"
                value={targetLanguage}
                onChange={(event) => setTargetLanguage(event.target.value)}
              />
            </label>
            <label className={styles.field} htmlFor="translation-edition-title">
              输出 Edition 名称
              <Input
                id="translation-edition-title"
                required
                maxLength={500}
                value={editionTitle}
                onChange={(event) => setEditionTitle(event.target.value)}
              />
            </label>
          </div>

          <Alert
            type="warning"
            showIcon
            title="正文会经私有 Relay 发送给 Provider，并使用你加密保存的 API Key。"
            description="Token 费用由你的 Provider 账户承担。任务会使用凭据设置中的 Provider、模型与服务地址；提交前请确认你有权处理该正文。"
          />
          {error ? <Alert type="error" showIcon title={error} role="alert" /> : null}

          <div className={styles.actions}>
            <Button onClick={onClose} disabled={isSubmitting}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={isSubmitting}
              disabled={(
                source === null
                || service?.available !== true
                || usableCredential === null
              )}
            >
              {isRetranslation ? "创建重译任务" : "创建翻译任务"}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
