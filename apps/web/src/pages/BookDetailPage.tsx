import { Alert, Button, Card, Input } from "antd";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { BookDetail, BookPreference, Edition } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EditionCard } from "../features/editions/EditionCard";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { ProtectedImage } from "../shared/ProtectedImage";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./LibraryPages.module.css";

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
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
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
      setMessage("图书信息已保存。");
      await loadBook();
    } catch (caught) {
      setActionError(userFacingError(caught));
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteBook() {
    if (!bookId) return;
    setActionError(null);
    try {
      await api.deleteBook(bookId);
      navigate("/", { replace: true });
    } catch (caught) {
      setActionError(userFacingError(caught));
    }
  }

  async function handleEditionDeleted() {
    setMessage("已删除该版本。");
    await loadBook();
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

  return (
    <main className={styles.page}>
      <Link className={styles.backLink} to="/">← 返回书库</Link>
      <div className={styles.detailHero}>
        <div>
          {book.cover_url ? (
            <ProtectedImage path={book.cover_url} alt={`${book.canonical_title} 封面`} className={styles.detailCover} />
          ) : <div className={styles.detailCover} aria-hidden="true">书</div>}
        </div>
        <div>
          <PageHeader
            className={styles.detailHeader}
            eyebrow={`作品详情 · ${book.edition_count} 个版本`}
            title={book.canonical_title}
            description={book.canonical_author ?? "作者未填写"}
            primaryAction={book.can_upload_edition ? (
              <Link className={styles.primaryLink} to={`/upload?mode=add_edition&bookId=${book.id}`}>
                上传新版本
              </Link>
            ) : undefined}
          />
          <p className={styles.detailDescription}>{book.description ?? "暂无简介"}</p>
          <p className={styles.detailDescription}>上传人：{book.contributor.display_name}</p>
          <p className={styles.detailDescription}>每个 Edition 独立保存阅读状态和位置；切换版本不会覆盖其他版本的进度。</p>
        </div>
      </div>

      {message ? <Alert type="success" showIcon title={message} role="status" /> : null}

      <div className={`${styles.contentGrid}${hasManagement ? "" : ` ${styles.contentGridSingle}`}`}>
        {hasManagement ? <aside className={`${styles.sidebar} ${styles.sidebarStack}`}>
          <Card className={styles.surface} title={<h2 className={styles.cardTitle}>馆藏操作</h2>}>
            <div className={styles.actions}>
              {book.can_upload_edition ? (
                <Link className={styles.primaryLink} to={`/upload?mode=add_edition&bookId=${book.id}`}>
                  上传新版本
                </Link>
              ) : null}
              {book.can_delete ? (
                <DestructiveAction
                  label="删除整本图书"
                  title={`删除《${book.canonical_title}》？`}
                  description="全部版本、未引用物理文件，以及所有人的首选版本与阅读进度会被永久清理；此操作不可撤销。"
                  onConfirm={deleteBook}
                />
              ) : null}
            </div>
            {!book.can_delete ? (
              <p className={styles.detailDescription}>
                当前不能整本删除。请先处理其他贡献者版本、依赖、上传或翻译任务，或联系管理员。
              </p>
            ) : null}
            {actionError ? <Alert type="error" showIcon title={actionError} /> : null}
          </Card>
          {book.can_edit ? <Card className={styles.surface} title={<h2 className={styles.cardTitle}>图书元数据</h2>}>
            <form className={styles.form} onSubmit={(event) => void saveBook(event)}>
              <label className={styles.field} htmlFor="book-title">
                书名
                <Input id="book-title" required value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label className={styles.field} htmlFor="book-author">
                作者
                <Input id="book-author" value={author} onChange={(event) => setAuthor(event.target.value)} />
              </label>
              <label className={styles.field} htmlFor="book-description">
                简介
                <Input.TextArea id="book-description" rows={5} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <Button type="primary" htmlType="submit" loading={isSaving}>保存图书信息</Button>
            </form>
          </Card> : null}
        </aside> : null}
        <section aria-labelledby="editions-title">
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>全部可读版本</p>
              <h2 id="editions-title">Edition 列表</h2>
            </div>
            <Button onClick={() => void loadBook()}>刷新</Button>
          </div>
          {book.editions.length === 0 ? (
            <EmptyState
              title="还没有版本"
              detail={book.can_upload_edition ? "上传 EPUB 或 TXT，为作品添加可阅读版本。" : "这部作品暂时没有可阅读的版本。"}
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
                  canManage={isAdmin}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
