import { Alert, Button, Card, Input, Segmented, Select } from "antd";
import { type FormEvent, useMemo, useState } from "react";

import { api, userFacingError } from "../../api/client";
import type {
  BookDetail,
  CreationMethod,
  Edition,
  EditionStatus,
  TranslationOrigin,
} from "../../api/types";
import { creationMethodLabels, editionRoleLabel } from "../../shared/labels";
import styles from "../ManagedForms.module.css";

type EditionPreset = "source" | TranslationOrigin;

const presetLabels: Record<EditionPreset, string> = {
  source: "原文",
  ai: "AI 译文",
  human: "人工译文",
  mixed: "混合译文",
  unknown: "来源未知译文",
};

const defaultMethods: Record<EditionPreset, CreationMethod> = {
  source: "uploaded",
  ai: "generated",
  human: "uploaded",
  mixed: "edited",
  unknown: "uploaded",
};

interface EditionCreateFormProps {
  book: BookDetail;
  onCreated: (edition: Edition) => void | Promise<void>;
}

export function EditionCreateForm({ book, onCreated }: EditionCreateFormProps) {
  const [preset, setPreset] = useState<EditionPreset>("source");
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("");
  const [method, setMethod] = useState<CreationMethod>("uploaded");
  const [sourceId, setSourceId] = useState("");
  const [supersedesId, setSupersedesId] = useState("");
  const [status, setStatus] = useState<EditionStatus>("ready");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sourceEditions = useMemo(
    () => book.editions.filter((edition) => edition.content_role === "source"),
    [book.editions],
  );
  const isTranslation = preset !== "source";

  function choosePreset(nextPreset: EditionPreset) {
    setPreset(nextPreset);
    setMethod(defaultMethods[nextPreset]);
    if (nextPreset === "source") {
      setSourceId("");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const edition = await api.createEdition(book.id, {
        title,
        language,
        content_role: isTranslation ? "translation" : "source",
        translation_origin: preset === "source" ? null : preset,
        creation_method: method,
        source_edition_id: isTranslation ? sourceId || null : null,
        supersedes_edition_id: supersedesId || null,
        status,
        revision: 1,
      });
      setTitle("");
      setLanguage("");
      setSourceId("");
      setSupersedesId("");
      await onCreated(edition);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className={styles.card} title={<h2 className={styles.title}>创建 Edition</h2>}>
      <form className={styles.form} onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
        <label className={styles.field}>
          版本类型
          <Segmented<EditionPreset>
            aria-label="版本类型"
            block
            value={preset}
            options={(Object.keys(presetLabels) as EditionPreset[]).map((value) => ({
              value,
              label: presetLabels[value],
            }))}
            onChange={choosePreset}
          />
        </label>

        <div className={styles.grid}>
          <label className={styles.field} htmlFor="legacy-edition-title">
            版本标题
            <Input id="legacy-edition-title" required value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className={styles.field} htmlFor="legacy-edition-language">
            语言
            <Input
              id="legacy-edition-language"
              required
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="例如：ja、zh-CN"
            />
          </label>
          <label className={styles.field}>
            创建方式
            <Select
              aria-label="创建方式"
              value={method}
              onChange={setMethod}
              options={(Object.entries(creationMethodLabels) as [CreationMethod, string][]).map(([value, label]) => ({
                value,
                label,
              }))}
            />
            {preset === "ai" && method === "uploaded" ? (
              <span className={styles.hint}>这将创建“用户上传的外部 AI 译文”。</span>
            ) : null}
          </label>
          <label className={styles.field}>
            状态
            <Select
              aria-label="状态"
              value={status}
              onChange={setStatus}
              options={[
                { value: "draft", label: "草稿" },
                { value: "ready", label: "可用" },
                { value: "archived", label: "已归档" },
              ]}
            />
          </label>
        </div>

        {isTranslation ? (
          <label className={styles.field}>
            关联原文（可选）
            <Select
              aria-label="关联原文（可选）"
              value={sourceId}
              onChange={setSourceId}
              options={[
                { value: "", label: "不选择原文，作为独立译文" },
                ...sourceEditions.map((edition) => ({
                  value: edition.id,
                  label: `${edition.title} · ${edition.language}`,
                })),
              ]}
            />
            <span className={styles.hint}>没有原文也可正常创建，之后可以补充关联。</span>
          </label>
        ) : null}

        <label className={styles.field}>
          替代已有版本（可选）
          <Select
            aria-label="替代已有版本（可选）"
            value={supersedesId}
            onChange={setSupersedesId}
            options={[
              { value: "", label: "不替代其他版本" },
              ...book.editions.map((edition) => ({
                value: edition.id,
                label: `${edition.title} · ${editionRoleLabel(edition)}`,
              })),
            ]}
          />
        </label>

        {error ? <Alert type="error" showIcon title={error} /> : null}
        <Button type="primary" htmlType="submit" loading={isSubmitting}>
          {`创建${presetLabels[preset]}`}
        </Button>
      </form>
    </Card>
  );
}
