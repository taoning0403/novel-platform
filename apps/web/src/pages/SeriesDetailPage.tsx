import { Alert, Button, Card, Input, Select } from "antd";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { BookListItem, SeriesDetail } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { ProtectedImage } from "../shared/ProtectedImage";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./LibraryPages.module.css";

const statusLabels = {
  not_started: "未开始",
  reading: "阅读中",
  finished: "已读完",
} as const;

export function SeriesDetailPage() {
  const auth = useAuth();
  const canManage = auth.user?.role === "admin";
  const { seriesId } = useParams<{ seriesId: string }>();
  const navigate = useNavigate();
  const [series, setSeries] = useState<SeriesDetail | null>(null);
  const [library, setLibrary] = useState<BookListItem[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [bookId, setBookId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!seriesId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [nextSeries, books] = await Promise.all([
        api.getSeries(seriesId),
        canManage ? api.listBooks({}, 100, 0) : Promise.resolve([]),
      ]);
      setSeries(nextSeries);
      setLibrary(books);
      setName(nextSeries.name);
      setDescription(nextSeries.description ?? "");
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [canManage, seriesId]);

  useEffect(() => {
    void load();
  }, [load]);

  const availableBooks = useMemo(
    () => library.filter((book) => book.series_id === null),
    [library],
  );

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!seriesId) return;
    setIsSaving(true);
    setError(null);
    try {
      await api.patchSeries(seriesId, { name, description: description.trim() || null });
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSaving(false);
    }
  }

  async function addBook() {
    if (!seriesId || !bookId) return;
    setError(null);
    try {
      await api.addBookToSeries(seriesId, bookId);
      setBookId("");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    }
  }

  async function removeBook(id: string) {
    if (!seriesId) return;
    setError(null);
    try {
      await api.removeBookFromSeries(seriesId, id);
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    }
  }

  async function deleteSeries() {
    if (!seriesId) return;
    setError(null);
    try {
      await api.deleteSeries(seriesId);
      navigate("/series", { replace: true });
    } catch (caught) {
      setError(userFacingError(caught));
    }
  }

  if (isLoading) return <main className={styles.page}><LoadingBlock label="正在读取系列…" /></main>;
  if (error && !series) {
    return <main className={styles.page}><Link className={styles.backLink} to="/series">← 返回系列</Link><ErrorNotice message={error} onRetry={() => void load()} /></main>;
  }
  if (!series) return null;

  return (
    <main className={styles.page}>
      <Link className={styles.backLink} to="/series">← 返回系列</Link>
      <PageHeader
        eyebrow={`${series.book_count} 本图书`}
        title={series.name}
        description={series.description ?? "暂无简介"}
        primaryAction={canManage ? (
          <Link className={styles.primaryLink} to={`/series/${series.id}/upload`}>在系列中上传 EPUB / TXT</Link>
        ) : undefined}
      />
      {error ? <Alert type="error" showIcon title={error} /> : null}
      <div className={`${styles.contentGrid}${canManage ? "" : ` ${styles.contentGridSingle}`}`}>
        {canManage ? <aside className={`${styles.sidebar} ${styles.sidebarStack}`}>
          <Card className={styles.surface} title={<h2 className={styles.cardTitle}>系列信息</h2>}>
            <form className={styles.form} onSubmit={(event) => void save(event)}>
              <label className={styles.field} htmlFor="series-detail-name">
                名称
                <Input id="series-detail-name" required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className={styles.field} htmlFor="series-detail-description">
                简介
                <Input.TextArea id="series-detail-description" rows={5} maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <Button type="primary" htmlType="submit" loading={isSaving}>保存系列信息</Button>
              <DestructiveAction
                label="删除系列（保留图书）"
                title={`删除系列“${series.name}”？`}
                description="只删除系列与归属关系；其中的 Book、Edition、文件、偏好和阅读进度全部保留。"
                onConfirm={deleteSeries}
              />
            </form>
          </Card>
          <Card className={styles.surface} title={<h2 className={styles.cardTitle}>加入已有 Book</h2>}>
            <div className={styles.form}>
              <Select
                aria-label="选择未归入系列的图书"
                value={bookId}
                onChange={setBookId}
                options={[
                  { value: "", label: "选择未归入系列的图书" },
                  ...availableBooks.map((book) => ({ value: book.id, label: book.canonical_title })),
                ]}
              />
              <Button type="primary" disabled={!bookId} onClick={() => void addBook()}>加入当前系列</Button>
            </div>
          </Card>
        </aside> : null}
        <section aria-labelledby="series-books-title">
          <div className={styles.sectionHeader}><div><p className={styles.eyebrow}>稳定加入顺序</p><h2 id="series-books-title">系列图书</h2></div></div>
          {series.books.length === 0 ? <EmptyState title="系列还是空的" detail="加入已有 Book，或在这个系列中单本/批量上传。" /> : null}
          <div className={styles.seriesBooks}>
            {series.books.map((book) => (
              <article className={styles.seriesBook} key={book.id}>
                <span className={styles.position}>{book.series_position}</span>
                {book.cover_thumbnail_url ? <ProtectedImage path={book.cover_thumbnail_url} alt={`${book.canonical_title} 封面`} className={styles.seriesBookCover} /> : <div className={styles.seriesBookCover}>书</div>}
                <div>
                  <h3>{book.canonical_title}</h3>
                  <p className={styles.muted}>{book.canonical_author ?? "作者未填写"} · {book.edition_count} 个 Edition</p>
                  <p className={styles.muted}><StatusTag status={book.reading_status} label={statusLabels[book.reading_status]} /> {Math.round(book.reading_progress * 100)}%{book.last_read_at ? ` · ${formatDate(book.last_read_at)}` : ""}</p>
                  <div className={styles.actions}>
                    <Link className={styles.textLink} to={`/books/${book.id}`}>详情</Link>
                    {book.continue_url ? <Link className={styles.textLink} to={book.continue_url}>继续阅读</Link> : null}
                  </div>
                </div>
                {canManage ? (
                  <DestructiveAction
                    type="link"
                    label="移出系列"
                    title={`将《${book.canonical_title}》移出系列？`}
                    description="只移除系列归属；图书、Edition、文件与阅读状态会继续保留。"
                    onConfirm={() => removeBook(book.id)}
                  />
                ) : null}
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
