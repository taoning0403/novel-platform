import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Input,
  Modal,
  Tag,
  type MenuProps,
} from "antd";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { BookDetail, BookPreference, Edition, TranslationRun } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EditionCard } from "../features/editions/EditionCard";
import { TranslationLaunchModal } from "../features/translations/TranslationLaunchModal";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { ProtectedImage } from "../shared/ProtectedImage";
import styles from "./BookDetailPage.module.css";

export function BookDetailPage() {
  const auth = useAuth();
  const isAdmin = auth.user?.role === "admin";
  const { bookId } = useParams<{ bookId: string }>();
  const navigate = useNavigate();
  const [book, setBook] = useState<BookDetail | null>(null);
  const [preference, setPreference] = useState<BookPreference | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [description, setDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [translationEdition, setTranslationEdition] = useState<Edition | null>(null);
  const loadedRef = useRef(false);

  const loadBook = useCallback(async () => {
    if (!bookId) {
      setError("缺少 Book ID。");
      setIsLoading(false);
      return;
    }
    if (!loadedRef.current) setIsLoading(true);
    setError(null);
    try {
      const [nextBook, nextPreference] = await Promise.all([
        api.getBook(bookId),
        api.getPreferences(bookId),
      ]);
      setBook(nextBook);
      setPreference(nextPreference);
      setTitle(nextBook.canonical_title);
      setAuthor(nextBook.canonical_author ?? "");
      setDescription(nextBook.description ?? "");
      loadedRef.current = true;
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [bookId]);

  async function setPreferred(edition: Edition) {
    if (!bookId) return;
    setPreference(
      await api.patchPreferences(bookId, { preferred_edition_id: edition.id }),
    );
  }

  async function saveBook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!bookId) return;
    setIsSaving(true);
    setActionError(null);
    setMessage(null);
    try {
      await api.patchBook(bookId, {
        canonical_title: title,
        canonical_author: author.trim() || null,
        description: description.trim() || null,
      });
      await loadBook();
      setEditorOpen(false);
      setMessage("图书信息已保存。");
    } catch (caught) {
      setActionError(userFacingError(caught));
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteBook() {
    if (!bookId) return;
    setIsDeleting(true);
    setActionError(null);
    try {
      await api.deleteBook(bookId);
      setDeleteOpen(false);
      navigate("/", { replace: true });
    } catch (caught) {
      setActionError(userFacingError(caught));
      setDeleteOpen(false);
    } finally {
      setIsDeleting(false);
    }
  }

  async function handleEditionDeleted() {
    setMessage("已删除该版本。");
    await loadBook();
  }

  function handleTranslationCreated(run: TranslationRun) {
    setTranslationEdition(null);
    navigate(`/translations?run=${run.id}`);
  }

  useEffect(() => {
    void loadBook();
  }, [loadBook]);

  if (isLoading) {
    return <main className={styles.page}><LoadingBlock label="正在读取作品与版本…" /></main>;
  }
  if (error || !book) {
    return (
      <main className={styles.page}>
        <Link className={styles.backLink} to="/">← 返回书库</Link>
        <ErrorNotice message={error ?? "作品不存在。"} onRetry={() => void loadBook()} />
      </main>
    );
  }

  const hasManagement = book.can_edit || book.can_delete || book.can_upload_edition;
  const preferredEdition = book.editions.find(
    (edition) => edition.id === preference?.preferred_edition_id && edition.reader_available,
  ) ?? book.editions.find((edition) => edition.reader_available);
  const formats = Array.from(new Set(
    book.editions.flatMap((edition) => (
      edition.current_file ? [edition.current_file.file_format.toUpperCase()] : []
    )),
  ));
  const languages = Array.from(new Set(book.editions.map((edition) => edition.language)));
  const managementItems: MenuProps["items"] = [];
  if (book.can_edit) {
    managementItems.push({ key: "edit", label: "编辑图书信息" });
  }
  if (book.can_upload_edition) {
    managementItems.push({
      key: "upload",
      label: <Link to={`/upload?mode=add_edition&bookId=${book.id}`}>上传新版本</Link>,
    });
  }
  if (book.can_delete) {
    if (managementItems.length > 0) managementItems.push({ type: "divider" });
    managementItems.push({ key: "delete", danger: true, label: "删除整本图书" });
  }

  return (
    <main className={styles.page}>
      <Link className={styles.backLink} to="/">← 返回书库</Link>

      <section className={styles.hero} aria-labelledby="book-title">
        {book.cover_url ? (
          <ProtectedImage
            path={book.cover_url}
            alt={`${book.canonical_title} 封面`}
            className={styles.heroCover}
          />
        ) : (
          <div className={`${styles.heroCover} ${styles.heroCoverFallback}`} aria-hidden="true">
            <strong>{book.canonical_title}</strong>
            <small>{book.canonical_author ?? "作者未填写"}</small>
          </div>
        )}
        <div className={styles.heroInfo}>
          <p className={styles.eyebrow}>BOOK · 图书详情</p>
          <h1 id="book-title">{book.canonical_title}</h1>
          <p className={styles.heroAuthor}>{book.canonical_author ?? "作者未填写"}</p>
          <div className={styles.heroTags}>
            {formats.map((format) => <Tag key={format}>{format}</Tag>)}
            {languages.map((language) => <Tag key={language}>{language}</Tag>)}
            <Tag color="success">{book.edition_count} 个版本</Tag>
          </div>
          <p className={styles.heroDescription}>{book.description ?? "暂无简介"}</p>
          <p className={styles.contributor}>上传人：{book.contributor.display_name}</p>
          <div className={styles.heroActions}>
            {preferredEdition ? (
              <Link className={styles.primaryLink} to={`/read/${preferredEdition.id}`}>
                {preferredEdition.reading_status === "not_started" ? "开始阅读" : "继续阅读"}
              </Link>
            ) : null}
            {hasManagement ? (
              <Dropdown
                menu={{
                  items: managementItems,
                  onClick: ({ key }) => {
                    if (key === "edit") setEditorOpen(true);
                    if (key === "delete") setDeleteOpen(true);
                  },
                }}
                trigger={["click"]}
              >
                <Button aria-label="管理操作">管理操作 <span aria-hidden="true">⌄</span></Button>
              </Dropdown>
            ) : null}
          </div>
        </div>
      </section>

      {message ? <Alert className={styles.pageAlert} type="success" showIcon title={message} role="status" /> : null}
      {actionError ? <Alert className={styles.pageAlert} type="error" showIcon title={actionError} /> : null}

      <section aria-labelledby="editions-title">
        <div className={styles.sectionHeading}>
          <h2 id="editions-title">版本 <span>{book.editions.length}</span></h2>
          <Button onClick={() => void loadBook()}>刷新</Button>
        </div>
        {book.editions.length === 0 ? (
          <EmptyState
            title="还没有版本"
            detail={book.can_upload_edition
              ? "上传 EPUB 或 TXT，为作品添加可阅读版本。"
              : "这部作品暂时没有可阅读的版本。"}
          />
        ) : (
          <div className={styles.editionList}>
            {book.editions.map((edition) => (
              <EditionCard
                key={edition.id}
                edition={edition}
                allEditions={book.editions}
                onUpdated={loadBook}
                isPreferred={preference?.preferred_edition_id === edition.id}
                onSetPreferred={setPreferred}
                onDeleted={handleEditionDeleted}
                onTranslate={setTranslationEdition}
                canManage={isAdmin}
              />
            ))}
          </div>
        )}
      </section>

      <Drawer
        title="编辑图书信息"
        placement="right"
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        size={Math.min(440, typeof window === "undefined" ? 440 : window.innerWidth)}
      >
        <form className={styles.form} onSubmit={(event) => void saveBook(event)}>
          <label className={styles.field} htmlFor="book-title-field">
            书名
            <Input
              id="book-title-field"
              required
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className={styles.field} htmlFor="book-author">
            作者
            <Input id="book-author" value={author} onChange={(event) => setAuthor(event.target.value)} />
          </label>
          <label className={styles.field} htmlFor="book-description">
            简介
            <Input.TextArea
              id="book-description"
              rows={6}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          {actionError ? <Alert type="error" showIcon title={actionError} /> : null}
          <Button type="primary" htmlType="submit" loading={isSaving}>保存图书信息</Button>
        </form>
      </Drawer>

      <Modal
        title={`删除《${book.canonical_title}》？`}
        open={deleteOpen}
        confirmLoading={isDeleting}
        okText="确认执行"
        cancelText="取消"
        okButtonProps={{ danger: true, "aria-label": "确认执行" }}
        cancelButtonProps={{ "aria-label": "取消" }}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => void deleteBook()}
      >
        <p className={styles.deleteCopy}>
          全部版本、未引用物理文件，以及所有人的首选版本与阅读进度会被永久清理；此操作不可撤销。
        </p>
      </Modal>

      <TranslationLaunchModal
        book={book}
        edition={translationEdition}
        open={translationEdition !== null}
        onClose={() => setTranslationEdition(null)}
        onCreated={handleTranslationCreated}
      />
    </main>
  );
}
