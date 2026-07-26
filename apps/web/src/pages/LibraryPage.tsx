import { Button, Drawer, Input, Select, Tag } from "antd";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { BookFilters } from "../api/client";
import type { BookListItem, FileFormat, RecentReading } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { ProtectedImage } from "../shared/ProtectedImage";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./LibraryPage.module.css";

type AppliedFilter = "query" | "format" | "language" | "editionType";
const coverTones = [
  styles.coverBlue,
  styles.coverPlum,
  styles.coverTeal,
  styles.coverAmber,
  styles.coverSlate,
];

export function LibraryPage() {
  const auth = useAuth();
  const canUpload = auth.user?.capabilities.includes("library.upload") ?? false;
  const [books, setBooks] = useState<BookListItem[]>([]);
  const [recent, setRecent] = useState<RecentReading[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [fileFormat, setFileFormat] = useState<FileFormat | "">("");
  const [language, setLanguage] = useState("");
  const [editionType, setEditionType] = useState<"source" | "translation" | "">("");
  const [sort, setSort] = useState<BookFilters["sort"]>("updated_desc");
  const [filters, setFilters] = useState<BookFilters>({ sort: "updated_desc" });
  const [filterOpen, setFilterOpen] = useState(false);

  const appliedFilters = useMemo(() => {
    const next: Array<{ key: AppliedFilter; label: string }> = [];
    if (filters.query) next.push({ key: "query", label: `搜索：${filters.query}` });
    if (filters.format) next.push({ key: "format", label: filters.format.toUpperCase() });
    if (filters.language) next.push({ key: "language", label: `语言：${filters.language}` });
    if (filters.editionType) {
      next.push({
        key: "editionType",
        label: filters.editionType === "source" ? "原文" : "译文",
      });
    }
    return next;
  }, [filters]);

  const loadBooks = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [nextBooks, nextRecent] = await Promise.all([
        api.listBooks(filters),
        api.recentReading(8).catch(() => []),
      ]);
      setBooks(nextBooks);
      setRecent(nextRecent);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadBooks();
  }, [loadBooks]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters({
      query: query.trim(),
      format: fileFormat,
      language: language.trim(),
      editionType,
      sort,
    });
    setFilterOpen(false);
  }

  function resetSearch() {
    setQuery("");
    setFileFormat("");
    setLanguage("");
    setEditionType("");
    setSort("updated_desc");
    setFilters({ sort: "updated_desc" });
    setFilterOpen(false);
  }

  function removeFilter(key: AppliedFilter) {
    if (key === "query") setQuery("");
    if (key === "format") setFileFormat("");
    if (key === "language") setLanguage("");
    if (key === "editionType") setEditionType("");
    setFilters((current) => ({ ...current, [key]: "" }));
  }

  const primaryRecent = recent[0];
  const hasActiveFilters = appliedFilters.length > 0;

  return (
    <main className={styles.libraryPage}>
      <PageHeader
        eyebrow="LIBRARY · 书库"
        title="书库"
        description={`共 ${books.length} 本藏书 · 每个版本独立保留阅读进度`}
      />

      {primaryRecent ? (
        <section className={styles.continueStrip} aria-labelledby="recent-title">
          {primaryRecent.book_cover_thumbnail_url ? (
            <ProtectedImage
              path={primaryRecent.book_cover_thumbnail_url}
              alt={`${primaryRecent.book_title} 封面`}
              className={styles.continueCover}
            />
          ) : (
            <div
              className={`${styles.continueCoverFallback} ${styles.coverBlue}`}
              data-title={primaryRecent.book_title}
              aria-hidden="true"
            />
          )}
          <div className={styles.continueCopy}>
            <h2 className={styles.continueLabel} id="recent-title">最近阅读</h2>
            <div className={styles.continueTitleRow}>
              <h3>{primaryRecent.book_title}</h3>
              <p>
                {primaryRecent.edition_title} · {primaryRecent.edition_language} ·{" "}
                {primaryRecent.file_format.toUpperCase()}
              </p>
            </div>
            <div className={styles.continueProgress}>
              <div className={styles.traceProgress} aria-hidden="true">
                <span style={{ width: `${Math.round(primaryRecent.progress * 100)}%` }} />
              </div>
              <strong>{Math.round(primaryRecent.progress * 100)}%</strong>
            </div>
            <div className={styles.continueProgressMeta}>
              <span>{formatDate(primaryRecent.last_read_at)}</span>
              <StatusTag status={primaryRecent.status} />
            </div>
          </div>
          <Link className={styles.continueAction} to={primaryRecent.continue_url}>
            继续阅读 <span aria-hidden="true">→</span>
          </Link>
        </section>
      ) : null}

      <section className={styles.catalogue} aria-labelledby="library-title">
        <h2 className="sr-only" id="library-title">全部作品</h2>
        <form className={styles.searchTools} onSubmit={submitSearch}>
          <Input
            type="search"
            aria-label="搜索书名或作者"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索书名或作者"
            allowClear
          />
          <Button
            htmlType="button"
            aria-label="打开筛选"
            onClick={() => setFilterOpen(true)}
          >
            筛选
            {appliedFilters.length > 0 ? (
              <span className={styles.filterCount}>{appliedFilters.length}</span>
            ) : null}
          </Button>
        </form>

        {hasActiveFilters ? (
          <div className={styles.activeFilters} aria-label="已应用筛选">
            {appliedFilters.map((filter) => (
              <button type="button" key={filter.key} onClick={() => removeFilter(filter.key)}>
                {filter.label}<span aria-hidden="true">×</span>
              </button>
            ))}
            <span>{books.length} 个结果</span>
            <button type="button" onClick={resetSearch}>清除全部</button>
          </div>
        ) : null}

        {isLoading ? <LoadingBlock label="正在读取书库…" /> : null}
        {!isLoading && error ? <ErrorNotice message={error} onRetry={() => void loadBooks()} /> : null}
        {!isLoading && !error && books.length === 0 ? (
          <EmptyState
            title={hasActiveFilters ? "没有匹配的作品" : "书库还是空的"}
            detail={hasActiveFilters
              ? "调整筛选条件后重试。"
              : canUpload
                ? "上传 EPUB 或 TXT，创建第一本带文件的作品。"
                : "管理员尚未发布可读馆藏。"}
          />
        ) : null}
        {!isLoading && !error && books.length > 0 ? (
          <div className={styles.bookGrid}>
            {books.map((book, index) => (
              <article className={styles.catalogueBook} key={book.id}>
                <Link
                  className={styles.cardOverlay}
                  to={`/books/${book.id}`}
                  aria-label="查看详情"
                />
                <div className={styles.catalogueCoverWrap}>
                  {book.cover_thumbnail_url ? (
                    <ProtectedImage
                      path={book.cover_thumbnail_url}
                      alt={`${book.canonical_title} 封面`}
                      className={styles.catalogueCover}
                    />
                  ) : (
                    <div
                      className={`${styles.catalogueCoverFallback} ${coverTones[index % coverTones.length]}`}
                      data-title={book.canonical_title}
                      data-author={book.canonical_author ?? "作者未填写"}
                      aria-hidden="true"
                    >
                      <span>{book.series_name ?? "漫读馆藏"}</span>
                    </div>
                  )}
                </div>
                <div className={styles.catalogueCopy}>
                  <h3>{book.canonical_title}</h3>
                  <p className={styles.catalogueAuthor}>{book.canonical_author ?? "作者未填写"}</p>
                  <div className={styles.bookTags}>
                    {book.file_formats.map((format) => <Tag key={format}>{format.toUpperCase()}</Tag>)}
                    {book.languages.map((item) => <Tag key={item}>{item}</Tag>)}
                  </div>
                  {book.reading_progress > 0 ? (
                    <div className={styles.bookProgress}>
                      <div className={styles.traceProgress} aria-hidden="true">
                        <span style={{ width: `${Math.round(book.reading_progress * 100)}%` }} />
                      </div>
                      <span>{Math.round(book.reading_progress * 100)}%</span>
                    </div>
                  ) : <p className={styles.notStarted}>尚未开始</p>}
                  <div className={styles.bookUtilityRow}>
                    <span>{book.edition_count} 个版本</span>
                    <StatusTag status={book.reading_status} />
                  </div>
                  <p className={styles.preferredEdition}>首选：{book.preferred_edition_title ?? "未设置"}</p>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      <Drawer
        title="筛选作品"
        placement="right"
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        size={Math.min(420, typeof window === "undefined" ? 420 : window.innerWidth)}
      >
        <form className={styles.filterDrawer} onSubmit={submitSearch}>
          <label>
            <span>文件格式</span>
            <Select
              aria-label="文件格式"
              value={fileFormat}
              onChange={setFileFormat}
              options={[
                { value: "", label: "全部格式" },
                { value: "epub", label: "EPUB" },
                { value: "txt", label: "TXT" },
              ]}
            />
          </label>
          <label>
            <span>语言</span>
            <Input
              aria-label="语言"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              placeholder="如 zh-CN"
            />
          </label>
          <label>
            <span>版本类型</span>
            <Select
              aria-label="版本类型"
              value={editionType}
              onChange={setEditionType}
              options={[
                { value: "", label: "全部版本" },
                { value: "source", label: "原文" },
                { value: "translation", label: "译文" },
              ]}
            />
          </label>
          <label>
            <span>排序</span>
            <Select
              aria-label="排序"
              value={sort}
              onChange={(value) => setSort(value as BookFilters["sort"])}
              options={[
                { value: "updated_desc", label: "最近更新" },
                { value: "created_desc", label: "最近创建" },
                { value: "title_asc", label: "书名 A–Z" },
              ]}
            />
          </label>
          <div className={styles.filterActions}>
            <Button htmlType="button" onClick={resetSearch}>清除</Button>
            <Button aria-label="筛选" type="primary" htmlType="submit">应用筛选</Button>
          </div>
        </form>
      </Drawer>
    </main>
  );
}
