import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Input,
  Modal,
  Progress,
  Radio,
  Select,
  Steps,
  Tag,
  Upload,
} from "antd";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api, userFacingError } from "../api/client";
import type {
  BookDetail,
  BookListItem,
  ImportOperation,
  ImportRecord,
  TranslationOrigin,
} from "../api/types";
import { ProtectedImage } from "../shared/ProtectedImage";
import { formattedByteLimit, maxUploadBytes } from "../shared/format";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./UploadPages.module.css";

const { Dragger } = Upload;

type EditionPreset = "source" | TranslationOrigin;

interface FailedImport {
  id: string;
  filename: string;
}

const modeLabels: Record<ImportOperation, string> = {
  create_book: "创建新图书",
  add_edition: "向已有图书添加版本",
  replace_edition_file: "替换已有版本文件",
};

const presetLabels: Record<EditionPreset, string> = {
  source: "原文",
  ai: "AI 译文",
  human: "人工译文",
  mixed: "混合版本",
  unknown: "来源未知译文",
};

function initialMode(value: string | null): ImportOperation {
  if (value === "add_edition" || value === "replace_edition_file") return value;
  return "create_book";
}

function previewString(preview: Record<string, unknown>, key: string): string {
  const value = preview[key];
  return typeof value === "string" ? value : "";
}

export function UploadPage() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [mode, setMode] = useState<ImportOperation>(() => initialMode(search.get("mode")));
  const [books, setBooks] = useState<BookListItem[]>([]);
  const [bookId, setBookId] = useState(search.get("bookId") ?? "");
  const [editionId, setEditionId] = useState(search.get("editionId") ?? "");
  const [book, setBook] = useState<BookDetail | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState("auto");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [inspection, setInspection] = useState<ImportRecord | null>(null);
  const [bookTitle, setBookTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [description, setDescription] = useState("");
  const [editionTitle, setEditionTitle] = useState("");
  const [language, setLanguage] = useState("");
  const [preset, setPreset] = useState<EditionPreset>("source");
  const [sourceId, setSourceId] = useState("");
  const [supersedesId, setSupersedesId] = useState("");
  const [setPreferred, setSetPreferred] = useState(mode === "create_book");
  const [useCover, setUseCover] = useState(mode === "create_book");
  const [isInspecting, setIsInspecting] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [failedImports, setFailedImports] = useState<FailedImport[]>([]);
  const [deletingImportId, setDeletingImportId] = useState<string | null>(null);
  const [cleanupNotice, setCleanupNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replacementConfirmOpen, setReplacementConfirmOpen] = useState(false);

  useEffect(() => {
    void api.listBooks().then(setBooks).catch((caught) => setError(userFacingError(caught)));
  }, []);

  useEffect(() => {
    setBook(null);
    setSourceId("");
    setSupersedesId("");
    if (!bookId) return;
    void api.getBook(bookId).then(setBook).catch((caught) => setError(userFacingError(caught)));
  }, [bookId]);

  const sourceEditions = useMemo(
    () => book?.editions.filter((edition) => edition.content_role === "source") ?? [],
    [book],
  );
  const replaceableEditions = book?.editions.filter(
    (edition) => edition.can_edit && edition.current_file !== null,
  ) ?? [];
  const replacementTarget = replaceableEditions.find((edition) => edition.id === editionId);
  const replacementFormatChanged = Boolean(
    mode === "replace_edition_file"
    && inspection?.file_format
    && replacementTarget?.current_file?.file_format
    && inspection.file_format !== replacementTarget.current_file.file_format,
  );
  const isTranslation = preset !== "source";

  function chooseMode(next: ImportOperation) {
    setMode(next);
    setInspection(null);
    setUploadProgress(0);
    setError(null);
    setSupersedesId("");
    setSetPreferred(next === "create_book");
    setUseCover(next === "create_book");
    if (next === "create_book") {
      setBookId("");
      setEditionId("");
    }
  }

  function chooseFile(next: File | null) {
    setFile(next);
    setInspection(null);
    setUploadProgress(0);
    setError(null);
  }

  function chooseTargetBook(nextBookId: string) {
    setBookId(nextBookId);
    setEditionId("");
    setInspection(null);
    setUploadProgress(0);
    setError(null);
  }

  function chooseTargetEdition(nextEditionId: string) {
    setEditionId(nextEditionId);
    setInspection(null);
    setUploadProgress(0);
    setError(null);
  }

  function chooseEncoding(nextEncoding: string) {
    setEncoding(nextEncoding);
    setInspection(null);
    setUploadProgress(0);
    setError(null);
  }

  async function inspect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("请先选择 EPUB 或 TXT 文件。");
      return;
    }
    if (file.size > maxUploadBytes) {
      setError(`所选文件超过 ${formattedByteLimit(maxUploadBytes)} 的单文件上限。`);
      return;
    }
    if (mode !== "create_book" && !bookId) {
      setError("请先选择目标 Book。");
      return;
    }
    if (mode === "replace_edition_file" && !editionId) {
      setError("请先选择要替换文件的 Edition。");
      return;
    }
    setIsInspecting(true);
    setError(null);
    setCleanupNotice(null);
    setUploadProgress(0);
    try {
      const result = await api.inspectImport({
        file,
        operation: mode,
        textEncoding: encoding,
        targetBookId: bookId || undefined,
        targetEditionId: editionId || undefined,
        onProgress: setUploadProgress,
      });
      setInspection(result);
      setUploadProgress(0);
      const preview = result.metadata_preview;
      const extractedTitle = previewString(preview, "title");
      const extractedLanguage = previewString(preview, "language");
      const extractedDescription = previewString(preview, "description");
      const creators = Array.isArray(preview.creators)
        ? preview.creators.filter((item): item is string => typeof item === "string").join("、")
        : "";
      setBookTitle((current) => current || extractedTitle || file.name.replace(/\.[^.]+$/, ""));
      setAuthor((current) => current || creators);
      setDescription((current) => current || extractedDescription);
      setEditionTitle((current) => current || extractedTitle || file.name);
      setLanguage((current) => current || extractedLanguage);
      setUseCover(mode === "create_book" && result.cover_available);
    } catch (caught) {
      setError(userFacingError(caught));
      const failedImportId = caught instanceof ApiError
        && typeof caught.details.import_id === "string"
        ? caught.details.import_id
        : null;
      if (failedImportId !== null) {
        setFailedImports((current) => current.some((item) => item.id === failedImportId)
          ? current
          : [...current, { id: failedImportId, filename: file.name }]);
      }
    } finally {
      setIsInspecting(false);
    }
  }

  async function deleteFailedImport(failedImport: FailedImport) {
    setDeletingImportId(failedImport.id);
    setError(null);
    setCleanupNotice(null);
    try {
      await api.deleteImport(failedImport.id);
      setFailedImports((current) => current.filter((item) => item.id !== failedImport.id));
      setCleanupNotice(`已删除 ${failedImport.filename} 的失败上传记录和临时文件。`);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setDeletingImportId(null);
    }
  }

  async function commit(replacementConfirmed = false) {
    if (!inspection) return;
    if (mode === "create_book" && !bookTitle.trim()) {
      setError("请填写书名后再导入。");
      return;
    }
    if (mode !== "replace_edition_file" && (!editionTitle.trim() || !language.trim())) {
      setError("请填写 Edition 名称和语言后再导入。");
      return;
    }
    if (mode === "replace_edition_file" && !replacementConfirmed) {
      setReplacementConfirmOpen(true);
      return;
    }
    setIsCommitting(true);
    setError(null);
    try {
      const result = await api.commitImport(
        inspection.id,
        mode === "replace_edition_file"
          ? { use_extracted_cover: false }
          : {
              canonical_title: mode === "create_book" ? bookTitle : null,
              canonical_author: mode === "create_book" ? author.trim() || null : null,
              description: mode === "create_book" ? description.trim() || null : null,
              edition_title: editionTitle,
              language,
              content_role: isTranslation ? "translation" : "source",
              translation_origin: preset === "source" ? null : preset,
              source_edition_id: isTranslation ? sourceId || null : null,
              supersedes_edition_id: mode === "add_edition" ? supersedesId || null : null,
              edition_status: "ready",
              set_preferred: setPreferred,
              use_extracted_cover: useCover,
            },
      );
      setReplacementConfirmOpen(false);
      navigate(`/books/${result.book.id}`, { replace: true });
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsCommitting(false);
    }
  }

  const currentStep = isCommitting
    ? 3
    : inspection
      ? 2
      : isInspecting
        ? 1
        : 0;

  return (
    <main className={styles.page}>
      <Link className={styles.backLink} to={bookId ? `/books/${bookId}` : "/"}>← 返回书库</Link>
      <PageHeader
        eyebrow="EPUB / TXT · 安全导入"
        title="上传与版本管理"
        description="先安全解析并预览元数据，确认后再把文件与 Book、Edition 一次性提交。"
      />
      <Steps
        className={styles.steps}
        current={currentStep}
        responsive
        items={[
          { title: "选择操作与文件" },
          { title: "安全解析" },
          { title: "校对元数据" },
          { title: "确认提交" },
          { title: "完成" },
        ]}
      />

      <div className={styles.layout}>
        <Card className={styles.panel}>
        <form className={styles.form} onSubmit={(event) => void inspect(event)}>
          <label className={styles.field}>
            操作模式
            <Radio.Group
              className={styles.modeGroup}
              value={mode}
              onChange={(event) => chooseMode(event.target.value as ImportOperation)}
            >
              {(Object.entries(modeLabels) as [ImportOperation, string][]).map(([value, label]) => (
                <Radio.Button key={value} value={value}>{label}</Radio.Button>
              ))}
            </Radio.Group>
          </label>

          {mode !== "create_book" ? (
            <label className={styles.field}>
              目标 Book
              <Select
                aria-label="目标 Book"
                value={bookId}
                onChange={chooseTargetBook}
                options={[
                  { value: "", label: "请选择可见图书" },
                  ...books
                    .filter((item) => item.can_upload_edition)
                    .map((item) => ({ value: item.id, label: item.canonical_title })),
                ]}
              />
              {book ? (
                <span className={styles.fieldHint}>
                  作品上传人：{book.contributor.display_name}；
                  {mode === "replace_edition_file"
                    ? "替换只更新物理文件，不改变版本上传人。"
                    : "提交后，你将记录为新版本上传人。"}
                </span>
              ) : null}
            </label>
          ) : null}
          {mode === "replace_edition_file" ? (
            <label className={styles.field}>
              目标 Edition
              <Select
                aria-label="目标 Edition"
                value={editionId}
                onChange={chooseTargetEdition}
                options={[
                  { value: "", label: "请选择目标 Edition" },
                  ...replaceableEditions.map((edition) => ({
                    value: edition.id,
                    label: `${edition.title} · ${edition.current_file?.file_format.toUpperCase() ?? "文件不可用"}`,
                  })),
                ]}
              />
            </label>
          ) : null}

          <Dragger
            className={styles.dragger}
            accept=".epub,.txt,application/epub+zip,text/plain"
            maxCount={1}
            showUploadList={false}
            beforeUpload={(nextFile) => {
              chooseFile(nextFile);
              return false;
            }}
            onChange={({ file: nextFile }) => {
              if (nextFile.originFileObj) chooseFile(nextFile.originFileObj);
            }}
          >
            <p className={styles.draggerTitle}>拖放 EPUB / TXT 到这里</p>
            <p className={styles.draggerHint}>或点击选择本地文件；文件不会由 antd 自动上传。</p>
            <input
              className={styles.nativeFileInput}
              aria-label="选择 EPUB 或 TXT 文件"
              type="file"
              accept=".epub,.txt,application/epub+zip,text/plain"
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
            />
          </Dragger>
          {file ? (
            <div className={styles.selectedFile}>
              <strong>{file.name}</strong>
              <span>{(file.size / 1024 / 1024).toFixed(2)} MiB</span>
            </div>
          ) : null}
          <p className={styles.fieldHint}>
            单文件上限 {formattedByteLimit(maxUploadBytes)}。DRM EPUB、危险 ZIP 和二进制 TXT 会被拒绝。
          </p>
          <label className={styles.field}>
            TXT 编码
            <Select
              aria-label="TXT 编码"
              value={encoding}
              onChange={chooseEncoding}
              options={[
                { value: "auto", label: "自动检测" },
                { value: "utf-8", label: "UTF-8" },
                { value: "utf-16-le", label: "UTF-16 LE" },
                { value: "utf-16-be", label: "UTF-16 BE" },
                { value: "gb18030", label: "GB18030" },
                { value: "cp932", label: "Shift-JIS / CP932" },
                { value: "euc-kr", label: "EUC-KR" },
              ]}
            />
          </label>
          {isInspecting || uploadProgress > 0 ? (
            <Progress percent={uploadProgress} status={isInspecting ? "active" : "normal"} />
          ) : null}
          {error ? <Alert type="error" showIcon title={error} /> : null}
          {cleanupNotice ? <Alert role="status" type="success" showIcon title={cleanupNotice} /> : null}
          {failedImports.map((failedImport) => (
            <Button
              key={failedImport.id}
              htmlType="button"
              disabled={deletingImportId === failedImport.id}
              onClick={() => void deleteFailedImport(failedImport)}
            >
              {deletingImportId === failedImport.id
                ? "正在删除失败记录…"
                : `删除 ${failedImport.filename} 的失败上传记录与临时文件`}
            </Button>
          ))}
          <Button type="primary" htmlType="submit" loading={isInspecting}>上传并预览</Button>
        </form>
        </Card>

        <Card className={styles.preview}>
        <section aria-live="polite">
          {!inspection ? (
            <Alert role="status" type="info" showIcon title="等待文件" description="解析完成后可在这里校对元数据。" />
          ) : (
            <>
              <div className={styles.previewHeader}>
                <div><p className={styles.eyebrow}>解析成功</p><h2>确认导入</h2></div>
                <Tag color="success">{inspection.file_format?.toUpperCase()}</Tag>
              </div>
              <div className={styles.previewSummary}>
                <ProtectedImage path={inspection.cover_preview_url} alt="提取出的 EPUB 封面" className={styles.previewCover} />
                <Descriptions
                  column={1}
                  items={[
                    { key: "file", label: "文件", children: inspection.original_filename },
                    { key: "size", label: "大小", children: `${(Number(inspection.size_bytes ?? 0) / 1024).toFixed(1)} KiB` },
                    { key: "encoding", label: "编码", children: inspection.text_encoding ?? "不适用" },
                    { key: "items", label: "内容项", children: inspection.content_item_count ?? "未统计" },
                  ]}
                />
              </div>
              {inspection.warnings.map((warning) => <Alert type="warning" showIcon title={warning} key={warning} />)}

              {mode !== "replace_edition_file" ? (
                <div className={styles.metadata}>
                  {mode === "create_book" ? (
                    <>
                      <label className={styles.field} htmlFor="import-book-title">书名<Input id="import-book-title" required value={bookTitle} onChange={(event) => setBookTitle(event.target.value)} /></label>
                      <label className={styles.field} htmlFor="import-author">作者<Input id="import-author" value={author} onChange={(event) => setAuthor(event.target.value)} /></label>
                      <label className={styles.field} htmlFor="import-description">简介<Input.TextArea id="import-description" rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
                    </>
                  ) : null}
                  <label className={styles.field}>
                    Edition 类型
                    <Radio.Group value={preset}>
                      {(Object.entries(presetLabels) as [EditionPreset, string][]).map(([value, label]) => (
                        <Radio.Button key={value} value={value} onChange={() => { setPreset(value); if (value === "source") setSourceId(""); }}>
                          {label}
                        </Radio.Button>
                      ))}
                    </Radio.Group>
                  </label>
                  <div className={styles.grid}>
                    <label className={styles.field} htmlFor="import-edition-title">Edition 名称<Input id="import-edition-title" required value={editionTitle} onChange={(event) => setEditionTitle(event.target.value)} /></label>
                    <label className={styles.field} htmlFor="import-language">语言<Input id="import-language" required value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="如 ja、zh-CN" /></label>
                  </div>
                  {isTranslation && mode === "add_edition" ? (
                    <label className={styles.field}>
                      关联原文（可选）
                      <Select
                        aria-label="关联原文（可选）"
                        value={sourceId}
                        onChange={setSourceId}
                        options={[
                          { value: "", label: "暂不关联，作为独立译文" },
                          ...sourceEditions.map((edition) => ({ value: edition.id, label: edition.title })),
                        ]}
                      />
                    </label>
                  ) : null}
                  {mode === "add_edition" ? (
                    <label className={styles.field}>
                      替代已有 Edition（可选）
                      <Select
                        aria-label="替代已有 Edition（可选）"
                        value={supersedesId}
                        onChange={setSupersedesId}
                        options={[
                          { value: "", label: "不替代其他 Edition" },
                          ...replaceableEditions.map((edition) => ({
                            value: edition.id,
                            label: `${edition.title} · ${edition.language}`,
                          })),
                        ]}
                      />
                    </label>
                  ) : null}
                  <div className={styles.checkList}>
                    <Checkbox checked={setPreferred} onChange={(event) => setSetPreferred(event.target.checked)}>设为首选 Edition（不会删除其他版本）</Checkbox>
                    {inspection.cover_available ? (
                      <Checkbox checked={useCover} onChange={(event) => setUseCover(event.target.checked)}>使用提取出的封面{mode === "add_edition" ? "（将明确替换 Book 封面）" : ""}</Checkbox>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className={styles.note}>
                  <strong>替换只切换文件修订</strong>
                  {replacementFormatChanged ? (
                    <span>
                      格式将从 {replacementTarget?.current_file?.file_format.toUpperCase()} 改为 {inspection.file_format?.toUpperCase()}；新文件元数据已经重新提取，但不会覆盖用户编辑过的 Book 信息。
                    </span>
                  ) : null}
                  <span>Edition ID、source/supersedes 关系和首选状态保持不变；失败时旧文件继续可用。</span>
                </div>
              )}
              <Button className={styles.commit} type="primary" block loading={isCommitting} onClick={() => void commit()}>
                {mode === "replace_edition_file" ? "确认替换文件" : "确认导入"}
              </Button>
            </>
          )}
        </section>
        </Card>
      </div>
      <Modal
        title="确认替换 Edition 文件"
        open={replacementConfirmOpen}
        confirmLoading={isCommitting}
        okText="确认替换"
        cancelText="取消"
        okButtonProps={{ "aria-label": "确认替换" }}
        cancelButtonProps={{ "aria-label": "取消" }}
        onCancel={() => setReplacementConfirmOpen(false)}
        onOk={() => void commit(true)}
      >
        {replacementFormatChanged ? (
          <Alert
            type="warning"
            showIcon
            title={`文件格式将从 ${replacementTarget?.current_file?.file_format.toUpperCase()} 改为 ${inspection?.file_format?.toUpperCase()}`}
            description="新文件元数据已经重新提取，但不会覆盖用户编辑过的 Book 信息。"
          />
        ) : null}
        <p>将原子切换当前文件修订。Edition 身份、原文关联、替代关系和首选状态均保持不变。</p>
      </Modal>
    </main>
  );
}
