import { Alert, Button, Card, Progress, Select, Upload } from "antd";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, userFacingError } from "../api/client";
import type { Series } from "../api/types";
import { formattedByteLimit, maxUploadBytes } from "../shared/format";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./UploadPages.module.css";

const { Dragger } = Upload;

interface UploadResult {
  filename: string;
  status: "waiting" | "inspecting" | "committing" | "succeeded" | "failed";
  progress: number;
  message: string;
  bookId?: string;
}

function previewString(preview: Record<string, unknown>, key: string): string {
  const value = preview[key];
  return typeof value === "string" ? value : "";
}

function inferredTitle(filename: string): string {
  return filename.replace(/\.[^.]+$/, "").trim() || filename;
}

export function SeriesUploadPage() {
  const { seriesId } = useParams<{ seriesId: string }>();
  const [series, setSeries] = useState<Series | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [encoding, setEncoding] = useState("auto");
  const [results, setResults] = useState<UploadResult[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!seriesId) return;
    void api.getSeries(seriesId)
      .then((detail) => setSeries(detail))
      .catch((caught) => setError(userFacingError(caught)));
  }, [seriesId]);

  function chooseFiles(selected: File[]) {
    setFiles(selected);
    setResults(selected.map((file) => ({
      filename: file.name,
      status: "waiting",
      progress: 0,
      message: "等待上传",
    })));
    setError(null);
  }

  function update(index: number, changes: Partial<UploadResult>) {
    setResults((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, ...changes } : item
    )));
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!seriesId || files.length === 0) {
      setError("请至少选择一个 EPUB 或 TXT 文件。");
      return;
    }
    setIsUploading(true);
    setError(null);
    for (const [index, file] of files.entries()) {
      if (file.size > maxUploadBytes) {
        update(index, { status: "failed", message: `超过 ${formattedByteLimit(maxUploadBytes)} 单文件上限` });
        continue;
      }
      try {
        update(index, { status: "inspecting", message: "正在上传并安全解析" });
        const inspection = await api.inspectImport({
          file,
          operation: "create_book",
          textEncoding: encoding,
          onProgress: (progress) => update(index, { progress }),
        });
        const title = previewString(inspection.metadata_preview, "title") || inferredTitle(file.name);
        const language = previewString(inspection.metadata_preview, "language") || "und";
        update(index, { status: "committing", progress: 100, message: "正在创建 Book 与 Edition" });
        const committed = await api.commitImport(inspection.id, {
          series_id: seriesId,
          canonical_title: title,
          canonical_author: null,
          description: null,
          edition_title: title,
          language,
          content_role: "source",
          translation_origin: null,
          set_preferred: true,
          use_extracted_cover: inspection.cover_available,
        });
        update(index, {
          status: "succeeded",
          message: "已上传并加入系列",
          bookId: committed.book.id,
        });
      } catch (caught) {
        const message = caught instanceof ApiError ? `${caught.message}（${caught.code}）` : userFacingError(caught);
        update(index, { status: "failed", message });
      }
    }
    setIsUploading(false);
  }

  return (
    <main className={styles.page}>
      <Link className={styles.backLink} to={seriesId ? `/series/${seriesId}` : "/series"}>← 返回系列</Link>
      <PageHeader
        eyebrow="系列内上传 · 每个文件创建一本 Book"
        title={series ? `上传到「${series.name}」` : "系列内上传"}
        description="可选择单个或多个 EPUB/TXT。每项独立提交；一个文件失败不会回滚其他成功图书。"
      />
      <div className={styles.layout}>
        <Card className={styles.panel}>
        <form className={styles.form} onSubmit={(event) => void upload(event)}>
          <Dragger
            className={styles.dragger}
            multiple
            accept=".epub,.txt,application/epub+zip,text/plain"
            openFileDialogOnClick={false}
            beforeUpload={() => false}
            onChange={({ fileList }) => chooseFiles(
              fileList
                .map((item) => item.originFileObj)
                .filter((item): item is NonNullable<typeof item> => item !== undefined),
            )}
          >
            <p className={styles.draggerTitle}>选择 EPUB / TXT 文件（可多选）</p>
            <p className={styles.draggerHint}>每个文件会独立执行安全解析与提交，不会由 antd 自动上传。</p>
            <input
              className={styles.nativeFileInput}
              aria-label="选择一个或多个 EPUB 或 TXT 文件"
              type="file"
              multiple
              accept=".epub,.txt,application/epub+zip,text/plain"
              onChange={(event) => chooseFiles(Array.from(event.target.files ?? []))}
            />
          </Dragger>
          <p className={styles.fieldHint}>已选择 {files.length} 个文件；单文件上限 {formattedByteLimit(maxUploadBytes)}。</p>
          <label className={styles.field}>
            TXT 编码
            <Select
              aria-label="TXT 编码"
              value={encoding}
              onChange={setEncoding}
              options={[
                { value: "auto", label: "自动检测" },
                { value: "utf-8", label: "UTF-8" },
                { value: "cp932", label: "Shift-JIS / CP932" },
                { value: "gb18030", label: "GB18030" },
              ]}
            />
          </label>
          {error ? <Alert type="error" showIcon title={error} /> : null}
          <Button type="primary" htmlType="submit" loading={isUploading} disabled={files.length === 0}>
            {files.length > 1 ? `批量上传 ${files.length} 本` : "上传这本图书"}
          </Button>
        </form>
        </Card>
        <Card className={styles.preview}>
        <section aria-live="polite">
          <div className={styles.previewHeader}><div><p className={styles.eyebrow}>逐项结果</p><h2>上传队列</h2></div></div>
          {results.length === 0 ? <Alert role="status" type="info" showIcon title="等待文件" description="选择文件后，每一项都会显示自己的处理结果。" /> : null}
          <div className={styles.queue}>
          {results.map((result, index) => (
            <Card className={styles.queueItem} key={`${result.filename}-${index}`}>
              <article className={styles.queueBody}>
                <div className={styles.queueHeading}>
                  <div><strong>{result.filename}</strong><p className={styles.queueMessage}>{result.message}</p></div>
                  <StatusTag status={result.status} />
                </div>
                {result.status === "inspecting" ? <Progress percent={result.progress} status="active" /> : null}
                {result.bookId ? <Link className={styles.textLink} to={`/books/${result.bookId}`}>打开图书 →</Link> : null}
              </article>
            </Card>
          ))}
          </div>
          {results.some((result) => result.status === "succeeded") && seriesId ? (
            <Link className={styles.defaultLink} to={`/series/${seriesId}`}>返回系列查看已成功图书</Link>
          ) : null}
        </section>
        </Card>
      </div>
    </main>
  );
}
