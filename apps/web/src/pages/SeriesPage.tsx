import { Alert, Button, Card, Input } from "antd";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { Series } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./LibraryPages.module.css";

export function SeriesPage() {
  const auth = useAuth();
  const canManage = auth.user?.role === "admin";
  const [series, setSeries] = useState<Series[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setSeries(await api.listSeries());
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsCreating(true);
    setError(null);
    try {
      await api.createSeries({ name, description: description.trim() || null });
      setName("");
      setDescription("");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="共享馆藏 · v0.7.0"
        title="图书系列"
        description={canManage
          ? "按加入先后稳定整理图书；删除系列不会删除 Book、Edition 或上传文件。"
          : "按管理员维护的系列顺序浏览可读作品。"}
      />

      <div className={`${styles.contentGrid}${canManage ? "" : ` ${styles.contentGridSingle}`}`}>
        {canManage ? <aside>
          <Card className={styles.surface} title={<h2 className={styles.cardTitle}>创建系列</h2>}>
            <form className={styles.form} onSubmit={(event) => void create(event)}>
              <label className={styles.field} htmlFor="series-name">
                系列名称
                <Input id="series-name" required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className={styles.field} htmlFor="series-description">
                简介（可选）
                <Input.TextArea id="series-description" rows={5} maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <Button type="primary" htmlType="submit" loading={isCreating}>创建系列</Button>
              {error ? <Alert type="error" showIcon title={error} /> : null}
            </form>
          </Card>
        </aside> : null}
        <section aria-labelledby="series-title">
          <div className={styles.sectionHeader}>
            <div><p className={styles.eyebrow}>馆藏系列</p><h2 id="series-title">系列列表</h2></div>
            <Button onClick={() => void load()}>刷新</Button>
          </div>
          {isLoading ? <LoadingBlock label="正在读取系列…" /> : null}
          {!isLoading && error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}
          {!isLoading && !error && series.length === 0 ? (
            <EmptyState title="还没有系列" detail={canManage ? "创建一个系列，再加入已有 Book 或直接批量上传。" : "管理员尚未发布包含可读作品的系列。"} />
          ) : null}
          {!isLoading && !error ? (
            <div className={styles.seriesList}>
              {series.map((item) => (
                <Card className={styles.seriesCard} key={item.id}>
                  <article>
                    <p className={styles.eyebrow}>{item.book_count} 本图书</p>
                    <h3>{item.name}</h3>
                    <p className={styles.muted}>{item.description ?? "暂无简介"}</p>
                  <div className={styles.seriesMeta}>
                    <time dateTime={item.updated_at}>更新于 {formatDate(item.updated_at)}</time>
                    <Link className={styles.textLink} to={`/series/${item.id}`}>打开系列 →</Link>
                  </div>
                  </article>
                </Card>
              ))}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
