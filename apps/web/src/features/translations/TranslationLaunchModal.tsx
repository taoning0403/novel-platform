import { Alert, Button, Descriptions, Input, Modal, Spin, Tag } from "antd";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { api, userFacingError } from "../../api/client";
import type {
  BookDetail,
  Edition,
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
  const [service, setService] = useState<TranslationServiceStatus | null>(null);
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
    setIsChecking(true);
    void api.translationServiceStatus()
      .then((nextService) => {
        if (!cancelled) setService(nextService);
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
  }, [book.canonical_title, edition, isRetranslation, open]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (source === null || clientRequestId === "" || service?.available !== true) return;
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
            {isRetranslation
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
              <span>私有翻译服务</span>
              {isChecking ? <Spin size="small" /> : (
                <Tag color={service?.available ? "success" : "default"}>{serviceLabel}</Tag>
              )}
            </div>
            {service?.available ? (
              <small>
                LinguaSpindle {service.version ?? "未知版本"} · {service.pipeline_key}
                {service.pipeline_version ? ` ${service.pipeline_version}` : ""}
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
            title="正文会发送到管理员配置的私有翻译服务，并可能产生 Provider 费用。"
            description="此处不能更改 Provider、模型、Profile、服务地址或下载地址。提交前请确认你有权处理该正文。"
          />
          {error ? <Alert type="error" showIcon title={error} role="alert" /> : null}

          <div className={styles.actions}>
            <Button onClick={onClose} disabled={isSubmitting}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={isSubmitting}
              disabled={source === null || service?.available !== true}
            >
              {isRetranslation ? "创建重译任务" : "创建翻译任务"}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
