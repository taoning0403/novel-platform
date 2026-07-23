import { Alert, Button, Card, Descriptions, Input, Progress, Select, Tag } from "antd";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, userFacingError } from "../../api/client";
import type { Edition, EditionStatus } from "../../api/types";
import { formatDate } from "../../shared/format";
import {
  creationMethodLabels,
  editionRoleLabel,
  editionStatusLabels,
} from "../../shared/labels";
import { DestructiveAction } from "../../ui/components/DestructiveAction";
import { StatusTag } from "../../ui/components/StatusTag";
import styles from "./EditionCard.module.css";

interface EditionCardProps {
  edition: Edition;
  allEditions: Edition[];
  onUpdated: (edition: Edition) => void | Promise<void>;
  isPreferred?: boolean;
  onSetPreferred?: (edition: Edition) => void | Promise<void>;
  onDeleted?: () => void | Promise<void>;
  canManage?: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

const readingStatusLabels = {
  not_started: "未开始",
  reading: "阅读中",
  finished: "已读完",
} as const;

export function EditionCard({
  edition,
  allEditions,
  onUpdated,
  isPreferred = false,
  onSetPreferred,
  onDeleted,
  canManage = false,
}: EditionCardProps) {
  const [title, setTitle] = useState(edition.title);
  const [sourceId, setSourceId] = useState(edition.source_edition_id ?? "");
  const [supersedesId, setSupersedesId] = useState(edition.supersedes_edition_id ?? "");
  const [status, setStatus] = useState<EditionStatus>(edition.status);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSelecting, setIsSelecting] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const sourceEditions = allEditions.filter((item) => item.content_role === "source");
  const source = allEditions.find((item) => item.id === edition.source_edition_id);
  const superseded = allEditions.find((item) => item.id === edition.supersedes_edition_id);

  useEffect(() => {
    setTitle(edition.title);
    setSourceId(edition.source_edition_id ?? "");
    setSupersedesId(edition.supersedes_edition_id ?? "");
    setStatus(edition.status);
  }, [edition.source_edition_id, edition.status, edition.supersedes_edition_id, edition.title]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await api.patchEdition(
        edition.book_id,
        edition.id,
        canManage
          ? {
              title,
              source_edition_id: sourceId || null,
              supersedes_edition_id: supersedesId || null,
              status,
            }
          : { title },
      );
      setMessage("版本信息已保存。");
      await onUpdated(updated);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function selectPreferred() {
    if (!onSetPreferred) return;
    setIsSelecting(true);
    setError(null);
    try {
      await onSetPreferred(edition);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSelecting(false);
    }
  }

  async function downloadFile() {
    if (!edition.current_file?.download_url) return;
    setIsDownloading(true);
    setError(null);
    try {
      const blob = await api.fetchProtectedFile(edition.current_file.download_url);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = edition.current_file.original_filename;
      link.style.display = "none";
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsDownloading(false);
    }
  }

  async function deleteEdition() {
    setIsDeleting(true);
    setError(null);
    try {
      await api.deleteEdition(edition.book_id, edition.id);
      await onDeleted?.();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <Card className={styles.card}>
      <article>
      <div className={styles.header}>
        <div>
          <div className={styles.titleRow}>
            <Tag>{editionRoleLabel(edition)}</Tag>
            {isPreferred ? <Tag color="processing">首选 Edition</Tag> : null}
          </div>
          <h3>{edition.title}</h3>
        </div>
        <StatusTag status={edition.status} label={editionStatusLabels[edition.status]} />
      </div>

      <Descriptions
        column={{ xs: 1, sm: 2, lg: 3 }}
        items={[
          { key: "language", label: "语言", children: edition.language },
          { key: "role", label: "版本角色", children: edition.content_role === "source" ? "原文" : "翻译" },
          { key: "origin", label: "翻译来源", children: edition.translation_origin ? editionRoleLabel(edition) : "不适用" },
          { key: "method", label: "创建方式", children: creationMethodLabels[edition.creation_method] },
          {
            key: "contributor",
            label: edition.creation_method === "generated" ? "翻译发起人" : "上传人",
            children: edition.contributor.display_name,
          },
          { key: "revision", label: "修订号", children: `r${edition.revision}` },
          { key: "created", label: "创建时间", children: formatDate(edition.created_at) },
          { key: "format", label: "文件格式", children: edition.current_file?.file_format.toUpperCase() ?? "文件不可用" },
          { key: "size", label: "文件大小", children: edition.current_file ? formatFileSize(edition.current_file.size_bytes) : "—" },
          { key: "file-revision", label: "文件修订", children: edition.current_file ? `f${edition.current_file.revision}` : "—" },
          { key: "encoding", label: "采用编码", children: edition.current_file?.text_encoding ?? "不适用" },
          { key: "items", label: "内容项", children: edition.current_file?.content_item_count ?? "未统计" },
          { key: "uploaded", label: "上传时间", children: edition.current_file ? formatDate(edition.current_file.uploaded_at) : "—" },
          { key: "reading-status", label: "阅读状态", children: <StatusTag status={edition.reading_status} label={readingStatusLabels[edition.reading_status]} /> },
          { key: "reading-progress", label: "阅读进度", children: `${Math.round(edition.reading_progress * 100)}%` },
          { key: "last-read", label: "最后阅读", children: edition.last_read_at ? formatDate(edition.last_read_at) : "尚未开始" },
        ]}
      />
      <Progress
        className={styles.progress}
        percent={Math.round(edition.reading_progress * 100)}
        size="small"
      />

      {edition.current_file ? (
        <div className={styles.actions}>
          {edition.reader_available ? <Link className={styles.primaryLink} to={`/read/${edition.id}`}>{edition.reading_status === "not_started" ? "开始阅读" : "继续阅读"}</Link> : null}
          {canManage && edition.current_file.download_url ? <Button loading={isDownloading} onClick={() => void downloadFile()}>
            {`下载 ${edition.current_file.original_filename}`}
          </Button> : null}
          {edition.can_edit ? <Link className={styles.defaultLink} to={`/upload?mode=replace_edition_file&bookId=${edition.book_id}&editionId=${edition.id}`}>替换文件</Link> : null}
        </div>
      ) : (
        <div className={styles.note}>
          <strong>文件不可用</strong>
          <span>该版本当前无法阅读，请联系管理员检查馆藏完整性。</span>
        </div>
      )}

      {edition.content_role === "translation" && !source ? (
        <div className={styles.note}>
          <strong>未关联原文</strong>
          <span>该版本可以独立使用。后续获得原文后，可以再建立关联。</span>
        </div>
      ) : null}
      {source ? <p className={styles.relationship}>关联原文：<strong>{source.title}</strong></p> : null}
      {superseded ? <p className={styles.relationship}>替代版本：<strong>{superseded.title}</strong></p> : null}
      <div className={styles.preference}>
        <p>首选只影响打开顺序，不会覆盖、归档或删除其他版本。</p>
        <Button disabled={isPreferred} loading={isSelecting} onClick={() => void selectPreferred()}>
          {isPreferred ? "当前首选" : "设为首选"}
        </Button>
      </div>

      {edition.can_edit ? <form className={styles.form} onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
        <label className={styles.field} htmlFor={`edition-title-${edition.id}`}>
          Edition 名称
          <Input id={`edition-title-${edition.id}`} required value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        {canManage && edition.content_role === "translation" ? (
          <label className={styles.field}>
            原文关联
            <Select
              aria-label="原文关联"
              value={sourceId}
              onChange={setSourceId}
              options={[
                { value: "", label: "不关联原文" },
                ...sourceEditions.map((item) => ({ value: item.id, label: `${item.title} · ${item.language}` })),
              ]}
            />
          </label>
        ) : null}
        {canManage ? <label className={styles.field}>
          替代关系
          <Select
            aria-label="替代关系"
            value={supersedesId}
            onChange={setSupersedesId}
            options={[
              { value: "", label: "不替代其他 Edition" },
              ...allEditions.filter((item) => item.id !== edition.id).map((item) => ({
                value: item.id,
                label: `${item.title} · ${item.language}`,
              })),
            ]}
          />
        </label> : null}
        {canManage ? <label className={styles.field}>
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
        </label> : null}
        {error ? <Alert className={styles.full} type="error" showIcon title={error} /> : null}
        {message ? <Alert className={styles.full} type="success" showIcon title={message} role="status" /> : null}
        <div className={styles.formActions}>
          <Button type="primary" htmlType="submit" loading={isSubmitting}>
            {canManage ? "保存关系与状态" : "保存版本信息"}
          </Button>
          {edition.can_delete ? <DestructiveAction
            label="删除 Edition"
            title={`删除 Edition“${edition.title}”？`}
            description="该版本和未引用文件会被删除，并清除所有人指向它的首选版本与阅读进度；存在依赖或活动任务时服务器会拒绝。"
            loading={isDeleting}
            onConfirm={deleteEdition}
          /> : null}
        </div>
      </form> : edition.can_delete ? (
        <>
          {error ? <Alert type="error" showIcon title={error} /> : null}
          <div className={styles.actions}>
            <DestructiveAction
              label="删除 Edition"
              title={`删除 Edition“${edition.title}”？`}
              description="该版本和未引用文件会被删除，并清除所有人指向它的首选版本与阅读进度；存在依赖或活动任务时服务器会拒绝。"
              loading={isDeleting}
              onConfirm={deleteEdition}
            />
          </div>
        </>
      ) : error ? <Alert type="error" showIcon title={error} /> : null}
      </article>
    </Card>
  );
}
