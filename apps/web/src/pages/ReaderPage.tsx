import { Drawer, Select, Slider } from "antd";
import {
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, userFacingError } from "../api/client";
import type {
  ReaderOpen,
  ReaderSection,
  ReaderSettings,
  ReadingProgress,
  ReadingProgressPayload,
} from "../api/types";
import { ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import styles from "./ReaderPage.module.css";

interface ReaderLocation {
  sectionId: string;
  blockId: string | null;
  sectionProgress: number;
  overallProgress: number;
}

interface ConflictState {
  currentVersion: number;
  message: string;
}

const statusLabels = {
  not_started: "未开始",
  reading: "阅读中",
  finished: "已读完",
} as const;

const THEME_HINT_KEY = "reader-theme-hint";

function readThemeHint(): ReaderSettings["theme"] | null {
  try {
    const hint = window.localStorage.getItem(THEME_HINT_KEY);
    return hint === "dark" || hint === "sepia" || hint === "light" ? hint : null;
  } catch {
    return null;
  }
}

function writeThemeHint(theme: ReaderSettings["theme"]) {
  try {
    window.localStorage.setItem(THEME_HINT_KEY, theme);
  } catch {
    // Private browsing or storage denial: the hint is an enhancement only.
  }
}

function initialSectionIndex(opened: ReaderOpen): number {
  const exact = opened.publication.sections.findIndex(
    (section) => section.id === opened.progress.section_id,
  );
  if (exact >= 0) return exact;
  return Math.min(
    opened.publication.sections.length - 1,
    Math.max(0, Math.floor(opened.progress.overall_progress * opened.publication.sections.length)),
  );
}

export function ReaderPage() {
  const { editionId } = useParams<{ editionId: string }>();
  const navigate = useNavigate();
  const [opened, setOpened] = useState<ReaderOpen | null>(null);
  const [settings, setSettings] = useState<ReaderSettings | null>(null);
  const [section, setSection] = useState<ReaderSection | null>(null);
  const [sectionIndex, setSectionIndex] = useState(0);
  const [isOpening, setIsOpening] = useState(true);
  const [isLoadingSection, setIsLoadingSection] = useState(false);
  const [sectionAttempt, setSectionAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [tocOpen, setTocOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [visualProgress, setVisualProgress] = useState(0);
  const [syncState, setSyncState] = useState("已从云端恢复");
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [chromeVisible, setChromeVisible] = useState(true);
  // Remembered only to keep the opening/error screens on the reader's theme,
  // so dark-theme readers never see a full-screen light flash on entry.
  const [themeHint] = useState(readThemeHint);
  const conflictRef = useRef<ConflictState | null>(null);
  const chromeTimerRef = useRef<number | null>(null);
  const tocRailRef = useRef<HTMLElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const progressRef = useRef<ReadingProgress | null>(null);
  const locationRef = useRef<ReaderLocation | null>(null);
  const restoreRef = useRef<ReaderLocation | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const settingsTimerRef = useRef<number | null>(null);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const readerReady = opened !== null;

  const clearChromeTimer = useCallback(() => {
    if (chromeTimerRef.current === null) return;
    window.clearTimeout(chromeTimerRef.current);
    chromeTimerRef.current = null;
  }, []);

  const scheduleChromeHide = useCallback(() => {
    clearChromeTimer();
    if (tocOpen || settingsOpen || conflict) return;
    chromeTimerRef.current = window.setTimeout(() => {
      setChromeVisible(false);
      chromeTimerRef.current = null;
    }, 2400);
  }, [clearChromeTimer, conflict, settingsOpen, tocOpen]);

  const revealChrome = useCallback(() => {
    setChromeVisible(true);
    scheduleChromeHide();
  }, [scheduleChromeHide]);

  useEffect(() => {
    if (!readerReady) return clearChromeTimer;
    setChromeVisible(true);
    scheduleChromeHide();
    return clearChromeTimer;
  }, [clearChromeTimer, readerReady, scheduleChromeHide]);

  const loadReader = useCallback(async () => {
    if (!editionId) {
      setError("缺少 Edition ID。");
      setIsOpening(false);
      return;
    }
    setIsOpening(true);
    setError(null);
    setOpened(null);
    setSection(null);
    setConflict(null);
    conflictRef.current = null;
    progressRef.current = null;
    locationRef.current = null;
    restoreRef.current = null;
    try {
      const result = await api.openReader(editionId);
      const index = initialSectionIndex(result);
      const selected = result.publication.sections[index];
      const exactLocation = (
        result.progress.edition_file_revision === result.publication.file_revision
        && result.progress.section_id === selected.id
      );
      const restored: ReaderLocation = {
        sectionId: selected.id,
        blockId: exactLocation ? result.progress.block_id : null,
        sectionProgress: result.progress.section_progress,
        overallProgress: result.progress.overall_progress,
      };
      progressRef.current = result.progress;
      locationRef.current = restored;
      restoreRef.current = restored;
      setOpened(result);
      setSettings(result.settings);
      writeThemeHint(result.settings.theme);
      setSectionIndex(index);
      setVisualProgress(result.progress.overall_progress);
      setSyncState("已从云端恢复");
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsOpening(false);
    }
  }, [editionId]);

  useEffect(() => {
    void loadReader();
  }, [loadReader]);

  useEffect(() => {
    if (!opened || !editionId) return;
    const descriptor = opened.publication.sections[sectionIndex];
    if (!descriptor) return;
    let cancelled = false;
    setIsLoadingSection(true);
    setSectionError(null);
    void api.getReaderSection(editionId, descriptor.id)
      .then((result) => {
        if (!cancelled) setSection(result);
      })
      .catch((caught) => {
        if (!cancelled) setSectionError(userFacingError(caught));
      })
      .finally(() => {
        if (!cancelled) setIsLoadingSection(false);
      });
    return () => {
      cancelled = true;
    };
  }, [editionId, opened, sectionAttempt, sectionIndex]);

  useEffect(() => {
    if (!section || !editionId) return;
    let cancelled = false;
    const objectUrls: string[] = [];
    const frame = window.requestAnimationFrame(() => {
      const scroller = scrollRef.current;
      const restore = restoreRef.current;
      if (scroller && restore?.sectionId === section.id) {
        const blocks = Array.from(
          contentRef.current?.querySelectorAll<HTMLElement>("[data-reader-block]") ?? [],
        );
        const target = blocks.find((block) => (
          block.getAttribute("data-reader-block") === restore.blockId
        ));
        if (target) {
          target.scrollIntoView({ block: "start" });
        } else {
          const maximum = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
          scroller.scrollTop = maximum * restore.sectionProgress;
        }
        restoreRef.current = null;
      } else if (scroller) {
        scroller.scrollTop = 0;
      }
    });
    const images = Array.from(
      contentRef.current?.querySelectorAll<HTMLImageElement>("img[data-reader-resource]") ?? [],
    );
    for (const image of images) {
      const resourceId = image.dataset.readerResource;
      if (!resourceId) continue;
      void api.getReaderResource(editionId, resourceId)
        .then((blob) => {
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          objectUrls.push(url);
          image.src = url;
        })
        .catch(() => {
          image.alt = image.alt || "书内图片无法加载";
          image.classList.add(styles.imageError);
        });
    }
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [editionId, section]);

  const persist = useCallback((
    keepalive = false,
    status?: ReadingProgressPayload["status"],
    overrideVersion?: number,
    overrideLocation?: ReaderLocation,
  ): Promise<void> => {
    if (!editionId || !opened) return Promise.resolve();
    const snapshot = overrideLocation ?? locationRef.current;
    if (!snapshot) return Promise.resolve();
    const task = async () => {
      const progress = progressRef.current;
      if (!progress) return;
      setSyncState("正在同步…");
      try {
        const saved = await api.saveReadingProgress(
          editionId,
          {
            expected_version: overrideVersion ?? progress.version,
            section_id: snapshot.sectionId,
            block_id: snapshot.blockId,
            section_progress: snapshot.sectionProgress,
            overall_progress: snapshot.overallProgress,
            edition_file_revision: opened.publication.file_revision,
            status,
          },
          keepalive,
        );
        progressRef.current = saved;
        setOpened((current) => current ? { ...current, progress: saved } : current);
        setConflict(null);
        conflictRef.current = null;
        setSyncState("已同步");
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === "reading_progress_conflict") {
          const currentVersion = Number(caught.details.current_version);
          const nextConflict = {
            currentVersion: Number.isFinite(currentVersion) ? currentVersion : progress.version,
            message: caught.message,
          };
          conflictRef.current = nextConflict;
          setConflict(nextConflict);
          setSyncState("发现另一处更新");
          return;
        }
        setSyncState("同步失败，将在下次操作重试");
      }
    };
    saveQueueRef.current = saveQueueRef.current.catch(() => undefined).then(task);
    return saveQueueRef.current;
  }, [editionId, opened]);

  const persistRef = useRef(persist);
  useEffect(() => {
    persistRef.current = persist;
  }, [persist]);

  useEffect(() => () => {
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    void persistRef.current(true);
  }, [editionId]);

  useEffect(() => {
    function saveWhenHidden() {
      if (document.visibilityState === "hidden") void persist(true);
    }
    function saveBeforeUnload() {
      void persist(true);
    }
    document.addEventListener("visibilitychange", saveWhenHidden);
    window.addEventListener("beforeunload", saveBeforeUnload);
    return () => {
      document.removeEventListener("visibilitychange", saveWhenHidden);
      window.removeEventListener("beforeunload", saveBeforeUnload);
    };
  }, [persist]);

  function handleScroll() {
    if (!opened || !section) return;
    const scroller = scrollRef.current;
    if (!scroller) return;
    clearChromeTimer();
    setChromeVisible(false);
    const maximum = Math.max(1, scroller.scrollHeight - scroller.clientHeight);
    const sectionProgress = Math.min(1, Math.max(0, scroller.scrollTop / maximum));
    const blocks = Array.from(
      contentRef.current?.querySelectorAll<HTMLElement>("[data-reader-block]") ?? [],
    );
    const scrollerTop = scroller.getBoundingClientRect().top;
    const visible = blocks.find((block) => block.getBoundingClientRect().bottom >= scrollerTop + 12);
    const overallProgress = Math.min(
      1,
      Math.max(0, (sectionIndex + sectionProgress) / opened.publication.sections.length),
    );
    locationRef.current = {
      sectionId: section.id,
      blockId: visible?.dataset.readerBlock ?? null,
      sectionProgress,
      overallProgress,
    };
    setVisualProgress(overallProgress);
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => void persist(), 1000);
  }

  function openTableOfContents() {
    revealChrome();
    if (typeof window !== "undefined" && window.innerWidth <= 760) {
      setTocOpen(true);
      return;
    }
    const current = tocRailRef.current?.querySelector<HTMLElement>(
      '[aria-current="location"]',
    );
    (current ?? tocRailRef.current)?.focus();
  }

  async function goToSection(nextIndex: number) {
    if (!opened || nextIndex < 0 || nextIndex >= opened.publication.sections.length) return;
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    await persist();
    const descriptor = opened.publication.sections[nextIndex];
    const nextLocation: ReaderLocation = {
      sectionId: descriptor.id,
      blockId: null,
      sectionProgress: 0,
      overallProgress: nextIndex / opened.publication.sections.length,
    };
    locationRef.current = nextLocation;
    restoreRef.current = null;
    setVisualProgress(nextLocation.overallProgress);
    setSection(null);
    setSectionIndex(nextIndex);
    setTocOpen(false);
  }

  async function switchEdition(nextEditionId: string) {
    if (nextEditionId === opened?.edition.id) return;
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    await persist();
    if (conflictRef.current === null) navigate(`/read/${nextEditionId}`);
  }

  async function leaveReader(event: ReactMouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    await persist();
    if (conflictRef.current === null && opened) navigate(`/books/${opened.book.id}`);
  }

  function changeSettings(changes: Partial<ReaderSettings>) {
    if (!settings) return;
    const next = { ...settings, ...changes };
    setSettings(next);
    writeThemeHint(next.theme);
    if (settingsTimerRef.current !== null) window.clearTimeout(settingsTimerRef.current);
    settingsTimerRef.current = window.setTimeout(() => {
      void api.patchReaderSettings({
        font_size: next.font_size,
        line_height: next.line_height,
        content_width: next.content_width,
        font_family: next.font_family,
        theme: next.theme,
      }).then(setSettings).catch(() => setSyncState("阅读设置同步失败"));
    }, 350);
  }

  async function markFinished() {
    const current = locationRef.current;
    if (!current) return;
    const finished = { ...current, overallProgress: 1 };
    locationRef.current = finished;
    await persist(false, "finished", undefined, finished);
    setVisualProgress(1);
  }

  async function restartReading() {
    if (!opened) return;
    const first = opened.publication.sections[0];
    const start: ReaderLocation = {
      sectionId: first.id,
      blockId: null,
      sectionProgress: 0,
      overallProgress: 0,
    };
    locationRef.current = start;
    restoreRef.current = start;
    await persist(false, "reading", undefined, start);
    setSection(null);
    setSectionIndex(0);
    setVisualProgress(0);
  }

  const openingThemeClass =
    themeHint === "dark" ? styles.dark : themeHint === "sepia" ? styles.sepia : "";

  if (isOpening) {
    return (
      <main className={`${styles.loading} ${openingThemeClass}`}>
        <LoadingBlock label="正在打开 Edition 并恢复阅读位置…" />
      </main>
    );
  }
  if (error || !opened || !settings) {
    return (
      <main className={`${styles.error} ${openingThemeClass}`}>
        <ErrorNotice
          message={error ?? "阅读器无法打开。"}
          onRetry={() => void loadReader()}
        />
      </main>
    );
  }

  const currentDescriptor = opened.publication.sections[sectionIndex];
  const themeClass =
    settings.theme === "dark"
      ? styles.dark
      : settings.theme === "sepia"
        ? styles.sepia
        : "";
  const drawerThemeClass =
    settings.theme === "dark"
      ? styles.drawerDark
      : settings.theme === "sepia"
        ? styles.drawerSepia
        : "";
  const fontClass =
    settings.font_family === "serif"
      ? styles.fontSerif
      : settings.font_family === "sans"
        ? styles.fontSans
        : styles.fontSystem;
  const readerStyle = {
    "--reader-font-size": `${settings.font_size}px`,
    "--reader-line-height": String(settings.line_height),
    "--reader-content-width": `${settings.content_width}px`,
  } as CSSProperties;
  const chromeHiddenClass = chromeVisible ? "" : ` ${styles.chromeHidden}`;
  const progressPercent = visualProgress * 100;

  return (
    <main
      className={`${styles.reader} ${themeClass} ${fontClass}`}
      style={readerStyle}
      onFocusCapture={() => revealChrome()}
      onKeyDownCapture={() => revealChrome()}
      onPointerDownCapture={() => revealChrome()}
      onPointerMove={(event) => {
        // Moving the cursor mid-page is part of reading, not a request for
        // chrome: only the top/bottom edges (where the bars live) reveal it.
        if (event.clientY < 96 || event.clientY > window.innerHeight - 132) {
          revealChrome();
        }
      }}
    >
      <header className={`${styles.toolbar} ${styles.chrome}${chromeHiddenClass}`}>
        <div className={styles.toolbarLeft}>
          <Link
            className={styles.tool}
            to={`/books/${opened.book.id}`}
            aria-label="返回图书详情"
            onClick={(event) => void leaveReader(event)}
          >
            <span aria-hidden="true">←</span>
            <span className={styles.toolLabel}>返回</span>
          </Link>
          <button
            className={styles.tool}
            type="button"
            aria-label="目录"
            onClick={openTableOfContents}
          >
            <span className={styles.toolLabel}>目录</span>
            <span className={styles.mobileToolLabel} aria-hidden="true">目</span>
          </button>
        </div>
        <div className={styles.title}>
          <strong>{opened.book.canonical_title}</strong>
          <span>
            {opened.edition.title} · {opened.edition.language} ·{" "}
            {opened.edition.file_format.toUpperCase()}
          </span>
        </div>
        <div className={styles.toolbarRight}>
          <Select
            className={styles.editionSelect}
            aria-label="切换 Edition"
            value={opened.edition.id}
            popupMatchSelectWidth={false}
            onChange={(value) => void switchEdition(value)}
            options={opened.available_editions.map((edition) => ({
              value: edition.id,
              label: `${edition.title} · ${edition.language} · ${Math.round(edition.reading_progress * 100)}%`,
              title: `${edition.title} · ${edition.language} · ${Math.round(edition.reading_progress * 100)}%`,
            }))}
          />
          <button
            className={styles.tool}
            type="button"
            aria-label="阅读设置"
            onClick={() => setSettingsOpen(true)}
          >
            Aa
          </button>
        </div>
      </header>

      <div
        className={styles.progressTrace}
        role="progressbar"
        aria-label={`阅读进度 ${Math.round(visualProgress * 100)}%`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progressPercent)}
      >
        <span style={{ height: `${progressPercent}%` }} />
        <i aria-hidden="true" style={{ top: `${progressPercent}%` }} />
      </div>

      <aside
        className={styles.tocRail}
        id="reader-toc-rail"
        ref={tocRailRef}
        tabIndex={-1}
        aria-label="目录"
      >
        <span className={styles.tocRailTitle}>目录</span>
        <nav aria-label="章节目录">
          {opened.publication.toc.map((item) => {
            const index = opened.publication.sections.findIndex(
              (entry) => entry.id === item.section_id,
            );
            return (
              <button
                className={index === sectionIndex ? styles.tocRailCurrent : undefined}
                type="button"
                key={`${item.section_id}-${item.title}`}
                disabled={index < 0}
                aria-current={index === sectionIndex ? "location" : undefined}
                onClick={() => void goToSection(index)}
              >
                <i aria-hidden="true" />
                <span>
                  <small>{String(index + 1).padStart(2, "0")}</small>
                  {item.title}
                </span>
              </button>
            );
          })}
        </nav>
        <span className={styles.tocRailPosition}>
          {sectionIndex + 1} / {opened.publication.sections.length}
        </span>
      </aside>

      <Drawer
        title="目录"
        placement="left"
        open={tocOpen}
        onClose={() => setTocOpen(false)}
        rootClassName={`${styles.drawerRoot} ${drawerThemeClass}`}
        size={Math.min(
          390,
          typeof window === "undefined" ? 390 : window.innerWidth * 0.9,
        )}
      >
        <nav className={styles.tocNav} aria-label="目录">
          {opened.publication.toc.map((item) => {
            const index = opened.publication.sections.findIndex(
              (entry) => entry.id === item.section_id,
            );
            return (
              <button
                className={index === sectionIndex ? styles.current : undefined}
                type="button"
                key={`${item.section_id}-${item.title}`}
                onClick={() => void goToSection(index)}
              >
                {item.title}
              </button>
            );
          })}
        </nav>
      </Drawer>

      <Drawer
        title="阅读设置"
        placement="right"
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        rootClassName={`${styles.drawerRoot} ${drawerThemeClass}`}
        size={Math.min(
          390,
          typeof window === "undefined" ? 390 : window.innerWidth * 0.9,
        )}
      >
        <div className={styles.settings}>
          <label className={styles.settingRow}>
            字号
            <Slider
              ariaLabelForHandle="字号"
              min={12}
              max={36}
              value={settings.font_size}
              onChange={(value) => changeSettings({ font_size: value })}
            />
            <output>{settings.font_size}px</output>
          </label>
          <label className={styles.settingRow}>
            行高
            <Slider
              ariaLabelForHandle="行高"
              min={1.2}
              max={2.8}
              step={0.1}
              value={settings.line_height}
              onChange={(value) => changeSettings({ line_height: value })}
            />
            <output>{settings.line_height.toFixed(1)}</output>
          </label>
          <label className={styles.settingRow}>
            正文宽度
            <Slider
              ariaLabelForHandle="正文宽度"
              min={480}
              max={1200}
              step={20}
              value={settings.content_width}
              onChange={(value) => changeSettings({ content_width: value })}
            />
            <output>{settings.content_width}px</output>
          </label>
          <label className={styles.settingRow}>
            字体
            <Select
              aria-label="字体"
              value={settings.font_family}
              onChange={(value: ReaderSettings["font_family"]) =>
                changeSettings({ font_family: value })
              }
              options={[
                { value: "serif", label: "衬线", title: "衬线" },
                { value: "sans", label: "无衬线", title: "无衬线" },
                { value: "system", label: "系统字体", title: "系统字体" },
              ]}
            />
          </label>
          <label className={styles.settingRow}>
            主题
            <Select
              aria-label="主题"
              value={settings.theme}
              onChange={(value: ReaderSettings["theme"]) =>
                changeSettings({ theme: value })
              }
              options={[
                { value: "light", label: "浅色", title: "浅色" },
                { value: "dark", label: "深色", title: "深色" },
                { value: "sepia", label: "护眼", title: "护眼" },
              ]}
            />
          </label>
          <div className={styles.drawerActions}>
            <button type="button" onClick={() => void restartReading()}>
              重新阅读
            </button>
            <button type="button" onClick={() => void markFinished()}>
              标记已读
            </button>
          </div>
        </div>
      </Drawer>

      {conflict ? (
        <div className={styles.conflict} role="status">
          <span>{conflict.message}</span>
          <button type="button" onClick={() => void loadReader()}>
            使用云端位置
          </button>
          <button
            type="button"
            onClick={() =>
              void persist(false, undefined, conflict.currentVersion)
            }
          >
            用当前位置覆盖
          </button>
        </div>
      ) : null}

      <div className={styles.scroll} ref={scrollRef} onScroll={handleScroll}>
        <article className={styles.paper} aria-busy={isLoadingSection}>
          <header className={styles.sectionHeading}>
            <p>
              <span>{String(sectionIndex + 1).padStart(2, "0")}</span>
              <span>{sectionIndex + 1} / {opened.publication.sections.length}</span>
            </p>
            <h1>{currentDescriptor.title}</h1>
          </header>
          {isLoadingSection ? (
            <LoadingBlock label="正在加载这一节…" />
          ) : null}
          {sectionError ? (
            <ErrorNotice
              message={sectionError}
              onRetry={() => setSectionAttempt((value) => value + 1)}
            />
          ) : null}
          {section ? (
            <>
              {/* The API returns allow-listed, server-sanitized markup with no active content. */}
              <div
                className={styles.content}
                ref={contentRef}
                dangerouslySetInnerHTML={{ __html: section.html }}
              />
            </>
          ) : null}
        </article>
      </div>

      <footer className={`${styles.footer} ${styles.chrome}${chromeHiddenClass}`}>
        <button
          className={styles.navButton}
          type="button"
          disabled={sectionIndex === 0}
          onClick={() => void goToSection(sectionIndex - 1)}
        >
          ← 上一节
        </button>
        <div className={styles.readerPosition}>
          <strong>{Math.round(visualProgress * 100)}%</strong>
          <span>
            {statusLabels[progressRef.current?.status ?? "not_started"]} ·{" "}
            {syncState}
          </span>
        </div>
        <div className={styles.footerActions}>
          <button
            className={styles.secondaryAction}
            type="button"
            onClick={() => void restartReading()}
          >
            重新阅读
          </button>
          <button
            className={styles.finishAction}
            type="button"
            onClick={() => void markFinished()}
          >
            标记已读
          </button>
          <button
            className={`${styles.navButton} ${styles.nextButton}`}
            type="button"
            disabled={
              sectionIndex === opened.publication.sections.length - 1
            }
            onClick={() => void goToSection(sectionIndex + 1)}
          >
            下一节 →
          </button>
        </div>
      </footer>
    </main>
  );
}
