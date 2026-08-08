import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Input,
  Modal,
  Progress,
  Select,
  Tag,
  type MenuProps,
} from "antd";
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
import { StatusTag } from "../../ui/components/StatusTag";
import styles from "./EditionCard.module.css";

interface EditionCardProps {
  edition: Edition;
  allEditions: Edition[];
  onUpdated: (edition: Edition) => void | Promise<void>;
  isPreferred?: boolean;
  onSetPreferred?: (edition: Edition) => void | Promise<void>;
  onDeleted?: () => void | Promise<void>;
  onTranslate?: (edition: Edition) => void;
  canManage?: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

const readingStatusLabels = {
  not_started: "尚未开始",
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
  onTranslate,
  canManage = false,
}: EditionCardProps) {
  const [title, setTitle] = useState(edition.title);
  const [sourceId, setSourceId] = useState(edition.source_edition_id ?? "");
  const [supersedesId, setSupersedesId] = useState(edition.supersedes_edition_id ?? "");
  const [status, setStatus] = useState<EditionStatus>(edition.status);
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
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
      await onUpdated(updated);
      setEditorOpen(false);
      setMessage("版本信息已保存。");
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
      setMessage("已设为首选版本。");
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
      setDeleteOpen(false);
      await onDeleted?.();
    } catch (caught) {
      setError(userFacingError(caught));
      setDeleteOpen(false);
    } finally {
      setIsDeleting(false);
    }
  }

  const menuItems: MenuProps["items"] = [];
  if (edition.can_edit) {
    menuItems.push({ key: "edit", label: "编辑版本信息" });
  }
  if (edition.status === "ready" && !isPreferred) {
    menuItems.push({ key: "preferred", label: "设为首选" });
  }
  if (canManage && edition.current_file?.download_url) {
    menuItems.push({ key: "download", label: `下载 ${edition.current_file.original_filename}` });
  }
  if (edition.can_edit && edition.current_file) {
    menuItems.push({
      key: "replace",
      label: (
        <Link to={`/upload?mode=replace_edition_file&bookId=${edition.book_id}&editionId=${edition.id}`}>
          替换文件
        </Link>
      ),
    });
  }
  if (edition.can_translate && onTranslate) {
    menuItems.push({
      key: "translate",
      label: edition.creation_method === "generated" ? "重新翻译" : "发起翻译",
    });
  }
  if (edition.can_delete) {
    if (menuItems.length > 0) menuItems.push({ type: "divider" });
    menuItems.push({ key: "delete", danger: true, label: "删除版本" });
  }

  return (
    <article className={styles.card}>
      {menuItems.length > 0 ? (
        <Dropdown
          menu={{
            items: menuItems,
            onClick: ({ key }) => {
              if (key === "edit") setEditorOpen(true);
              if (key === "preferred") void selectPreferred();
              if (key === "download") void downloadFile();
              if (key === "translate") onTranslate?.(edition);
              if (key === "delete") setDeleteOpen(true);
            },
          }}
          trigger={["click"]}
        >
          <Button
            className={styles.moreButton}
            type="text"
            aria-label={`版本操作：${edition.title}`}
            loading={isDownloading}
          >
            •••
          </Button>
        </Dropdown>
      ) : null}

      <div className={styles.header}>
        <div className={styles.tagRow}>
          {edition.current_file ? <Tag>{edition.current_file.file_format.toUpperCase()}</Tag> : null}
          <Tag>{editionRoleLabel(edition)}</Tag>
          {isPreferred ? <Tag color="success">首选</Tag> : null}
          <StatusTag status={edition.status} label={editionStatusLabels[edition.status]} />
        </div>
        <h3>{edition.title} <span>{edition.language}</span></h3>
      </div>

      <div className={styles.meta}>
        <span>修订 {edition.revision}</span>
        {edition.current_file ? <span>{formatFileSize(edition.current_file.size_bytes)}</span> : null}
        {edition.current_file ? <span>{edition.current_file.original_filename}</span> : null}
        <span>{creationMethodLabels[edition.creation_method]}</span>
        <span>{edition.contributor.display_name}</span>
        <span>{formatDate(edition.created_at)}</span>
      </div>

      <div className={styles.progressRow}>
        <span>阅读进度</span>
        {edition.reading_progress > 0 ? (
          <>
            <Progress
              className={styles.progress}
              percent={Math.round(edition.reading_progress * 100)}
              size="small"
              showInfo={false}
            />
            <strong>{Math.round(edition.reading_progress * 100)}%</strong>
          </>
        ) : <small>{readingStatusLabels[edition.reading_status]}</small>}
      </div>

      <div className={styles.footer}>
        {edition.current_file && edition.reader_available ? (
          <Link className={styles.readLink} to={`/read/${edition.id}`}>
            {edition.reading_status === "not_started" ? "开始阅读" : "继续阅读"}
          </Link>
        ) : null}
        {edition.status === "ready" && !isPreferred ? (
          <Button type="link" loading={isSelecting} onClick={() => void selectPreferred()}>
            设为首选
          </Button>
        ) : null}
        {edition.status === "ready" ? (
          <span className={styles.preferenceHint}>
            首选只影响打开顺序，不会覆盖、归档或删除其他版本。
          </span>
        ) : null}
      </div>

      {!edition.current_file ? (
        <div className={styles.note}>
          <strong>文件不可用</strong>
          <span>该版本当前无法阅读，请联系管理员检查馆藏完整性。</span>
        </div>
      ) : null}
      {edition.content_role === "translation" && !source ? (
        <div className={styles.note}>
          <strong>未关联原文</strong>
          <span>该版本可以独立使用。后续获得原文后，可以再建立关联。</span>
        </div>
      ) : null}
      {source ? <p className={styles.relationship}>关联原文：<strong>{source.title}</strong></p> : null}
      {superseded ? <p className={styles.relationship}>替代版本：<strong>{superseded.title}</strong></p> : null}
      {edition.status !== "ready" && edition.creation_method === "generated" ? (
        <div className={styles.note}>
          <strong>仅创建者预览</strong>
          <span>生成草稿不会自动成为首选；管理员审核发布后，其他阅读者才可看到。</span>
        </div>
      ) : null}
      {error ? <Alert className={styles.alert} type="error" showIcon title={error} /> : null}
      {message ? <Alert className={styles.alert} type="success" showIcon title={message} role="status" /> : null}

      <Drawer
        title="编辑版本信息"
        placement="right"
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        size={Math.min(460, typeof window === "undefined" ? 460 : window.innerWidth)}
      >
        <form className={styles.form} onSubmit={(event) => void submit(event)} aria-busy={isSubmitting}>
          <label className={styles.field} htmlFor={`edition-title-${edition.id}`}>
            Edition 名称
            <Input
              id={`edition-title-${edition.id}`}
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
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
                  ...sourceEditions.map((item) => ({
                    value: item.id,
                    label: `${item.title} · ${item.language}`,
                  })),
                ]}
              />
            </label>
          ) : null}
          {canManage ? (
            <label className={styles.field}>
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
            </label>
          ) : null}
          {canManage ? (
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
          ) : null}
          {error ? <Alert type="error" showIcon title={error} /> : null}
          <Button type="primary" htmlType="submit" loading={isSubmitting}>
            {canManage ? "保存关系与状态" : "保存版本信息"}
          </Button>
        </form>
      </Drawer>

      <Modal
        title={`删除版本“${edition.title}”？`}
        open={deleteOpen}
        confirmLoading={isDeleting}
        okText="确认执行"
        cancelText="取消"
        okButtonProps={{ danger: true, "aria-label": "确认执行" }}
        cancelButtonProps={{ "aria-label": "取消" }}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => void deleteEdition()}
      >
        <p className={styles.deleteCopy}>
          该版本和未引用文件会被删除，并清除所有人指向它的首选版本与阅读进度；存在依赖或活动任务时服务器会拒绝。
        </p>
      </Modal>
    </article>
  );
}
