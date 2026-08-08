import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Popconfirm,
  Progress,
  Tag,
} from "antd";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type {
  ProviderCredentialStatus,
  TranslationAction,
  TranslationRun,
  TranslationRunStatus,
  TranslationServiceStatus,
} from "../api/types";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./TranslationsPage.module.css";

const statusLabels: Record<TranslationRunStatus, string> = {
  preparing: "准备中",
  queued: "排队中",
  running: "翻译中",
  paused: "已暂停",
  cancelling: "取消中",
  cancelled: "已取消",
  partially_succeeded: "部分成功",
  failed: "失败",
  ingesting: "导入译本",
  succeeded: "草稿已生成",
  attention_required: "需要确认",
};

const activeStatuses = new Set<TranslationRunStatus>([
  "preparing",
  "queued",
  "running",
  "paused",
  "cancelling",
  "ingesting",
  "attention_required",
]);

const actionLabels: Record<TranslationAction, string> = {
  pause: "暂停",
  resume: "继续",
  cancel: "取消任务",
  retry: "重试",
  sync: "立即同步",
  cleanup: "清理远端项目",
};

const cleanupStatusLabels: Record<string, string> = {
  not_required: "无需清理",
  pending: "清理中",
  succeeded: "已清理",
  failed: "清理失败",
};

function runStatusLabel(run: TranslationRun): string {
  if (
    run.status === "succeeded"
    && run.generated_edition_id
    && !run.can_preview_draft
    && !run.can_publish
  ) {
    return "译本已发布";
  }
  return statusLabels[run.status];
}

function replaceRun(runs: TranslationRun[], next: TranslationRun): TranslationRun[] {
  const found = runs.some((run) => run.id === next.id);
  if (!found) return [next, ...runs];
  return runs.map((run) => run.id === next.id ? next : run);
}

function configurationValue(run: TranslationRun, key: string): string {
  const value = run.configuration[key];
  return typeof value === "string" && value !== "" ? value : "未配置";
}

function firstConfigurationValue(run: TranslationRun, keys: string[]): string {
  for (const key of keys) {
    const value = run.configuration[key];
    if (typeof value === "string" && value !== "") return value;
  }
  return "未配置";
}

function configurationBooleanLabel(run: TranslationRun, key: string): string {
  const value = run.configuration[key];
  if (value === true) return "开启";
  if (value === false) return "关闭";
  return "未记录";
}

function ActionControl({
  action,
  activeAction,
  onAction,
}: {
  action: TranslationAction;
  activeAction: string | null;
  onAction: (action: TranslationAction) => void;
}) {
  const requiresConfirmation = (["cancel", "retry", "cleanup"] as TranslationAction[])
    .includes(action);
  const button = (
    <Button
      danger={action === "cancel" || action === "cleanup"}
      loading={activeAction === action}
      disabled={activeAction !== null}
      onClick={requiresConfirmation ? undefined : () => onAction(action)}
    >
      {actionLabels[action]}
    </Button>
  );
  if (!requiresConfirmation) return button;
  const descriptions: Partial<Record<TranslationAction, string>> = {
    cancel: "确定取消这个翻译任务？已产生的 Provider 费用不会撤销。",
    retry: "确定重试？任务会继续向当前 Provider 发起处理，并可能产生费用。",
    cleanup: "只会删除此任务记录的精确 LinguaSpindle Project，不会删除本地译本。",
  };
  return (
    <Popconfirm
      title={actionLabels[action]}
      description={descriptions[action]}
      okText="确认"
      cancelText="返回"
      onConfirm={() => onAction(action)}
    >
      {button}
    </Popconfirm>
  );
}

export function TranslationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("run");
  const [runs, setRuns] = useState<TranslationRun[]>([]);
  const [service, setService] = useState<TranslationServiceStatus | null>(null);
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null);
  const [credentialError, setCredentialError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pollMessage, setPollMessage] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(() => selectedId !== null);
  const loadedRef = useRef(false);
  const selectedIdRef = useRef(selectedId);
  const syncFlightsRef = useRef(new Map<string, Promise<TranslationRun>>());
  const backoffRef = useRef(new Map<string, number>());
  const selected = useMemo(
    () => runs.find((run) => run.id === selectedId) ?? null,
    [runs, selectedId],
  );
  selectedIdRef.current = selectedId;

  const selectRun = useCallback((runId: string) => {
    setSearchParams({ run: runId }, { replace: true });
  }, [setSearchParams]);

  const openRun = useCallback((runId: string) => {
    selectRun(runId);
    setDetailOpen(true);
  }, [selectRun]);

  const loadWorkspace = useCallback(async () => {
    if (!loadedRef.current) setIsLoading(true);
    setError(null);
    setCredentialError(null);
    try {
      const [nextCredential, nextRuns] = await Promise.all([
        api.getProviderCredential().catch((caught: unknown) => {
          setCredentialError(userFacingError(caught));
          return null;
        }),
        api.listTranslationRuns(),
      ]);
      const statusRun = nextRuns.find((run) => run.id === selectedIdRef.current)
        ?? nextRuns[0];
      const nextService = await api.translationServiceStatus(
        statusRun?.source_format ?? "txt",
      );
      setService(nextService);
      setCredential(nextCredential);
      setRuns(nextRuns);
      if (
        nextRuns.length > 0
        && (
          selectedIdRef.current === null
          || !nextRuns.some((run) => run.id === selectedIdRef.current)
        )
      ) {
        selectRun(nextRuns[0].id);
      }
      loadedRef.current = true;
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [selectRun]);

  const syncRun = useCallback((runId: string): Promise<TranslationRun> => {
    const existing = syncFlightsRef.current.get(runId);
    if (existing) return existing;
    const flight = api.runTranslationAction(runId, "sync").finally(() => {
      syncFlightsRef.current.delete(runId);
    });
    syncFlightsRef.current.set(runId, flight);
    return flight;
  }, []);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (selected === null || !activeStatuses.has(selected.status)) return;
    let cancelled = false;
    let timer: number | null = null;
    const runId = selected.id;

    function clearTimer() {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    }

    function schedule(delay: number) {
      clearTimer();
      if (!cancelled && document.visibilityState === "visible") {
        timer = window.setTimeout(() => void tick(), delay);
      }
    }

    async function tick() {
      if (cancelled || document.visibilityState !== "visible") return;
      try {
        const updated = await syncRun(runId);
        if (cancelled) return;
        setRuns((current) => replaceRun(current, updated));
        const logicalFailure = updated.status === "attention_required" && updated.error_code;
        const delay = logicalFailure
          ? Math.min((backoffRef.current.get(runId) ?? 4_000) * 2, 30_000)
          : 4_000;
        backoffRef.current.set(runId, delay);
        setPollMessage(logicalFailure ? `自动同步已退避至 ${Math.round(delay / 1000)} 秒。` : null);
        if (activeStatuses.has(updated.status)) schedule(delay);
      } catch (caught) {
        if (cancelled) return;
        const delay = Math.min((backoffRef.current.get(runId) ?? 4_000) * 2, 30_000);
        backoffRef.current.set(runId, delay);
        setPollMessage(`${userFacingError(caught)} 将在 ${Math.round(delay / 1000)} 秒后重试。`);
        schedule(delay);
      }
    }

    function handleVisibility() {
      clearTimer();
      if (document.visibilityState === "visible") schedule(250);
    }

    document.addEventListener("visibilitychange", handleVisibility);
    schedule(backoffRef.current.get(runId) ?? 4_000);
    return () => {
      cancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [selected, syncRun]);

  async function performRunAction(run: TranslationRun, action: TranslationAction) {
    setActiveAction(action);
    setPollMessage(null);
    try {
      const currentSync = syncFlightsRef.current.get(run.id);
      if (currentSync) await currentSync;
      const updated = action === "sync"
        ? await syncRun(run.id)
        : await api.runTranslationAction(run.id, action);
      setRuns((current) => replaceRun(current, updated));
      backoffRef.current.set(run.id, 4_000);
    } catch (caught) {
      setPollMessage(userFacingError(caught));
    } finally {
      setActiveAction(null);
    }
  }

  async function performAction(action: TranslationAction) {
    if (selected === null) return;
    await performRunAction(selected, action);
  }

  async function publishGeneratedEdition() {
    if (selected?.generated_edition_id === null || selected?.generated_edition_id === undefined) {
      return;
    }
    setActiveAction("publish");
    setPollMessage(null);
    try {
      await api.patchEdition(selected.book_id, selected.generated_edition_id, { status: "ready" });
      const updated = await api.getTranslationRun(selected.id);
      setRuns((current) => replaceRun(current, updated));
    } catch (caught) {
      setPollMessage(userFacingError(caught));
    } finally {
      setActiveAction(null);
    }
  }

  if (isLoading) {
    return <main className={styles.page}><LoadingBlock label="正在读取翻译任务…" /></main>;
  }
  if (error) {
    return (
      <main className={styles.page}>
        <ErrorNotice message={error} onRetry={() => void loadWorkspace()} />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="TRANSLATIONS · 小说翻译"
        title="小说翻译"
        description="以固定来源快照发起 AI 翻译，生成译本需审核后发布"
        secondaryActions={(
          <Button href="/settings/provider-credential">
            管理我的凭据
          </Button>
        )}
        primaryAction={<Button onClick={() => void loadWorkspace()}>刷新任务</Button>}
      />

      <section className={styles.serviceBar} aria-live="polite">
        <div>
          <span className={styles.serviceDot} data-available={service?.available ?? false} />
          <div>
            <strong>{service?.available ? "翻译服务可用" : "翻译服务不可用"}</strong>
            <small>
              {service?.available
                ? `${service.provider_name ?? service.provider_id}${service.provider_model ? ` · ${service.provider_model}` : ""} · LinguaSpindle ${service.version ?? "未知"}`
                : service?.error_message ?? "管理员尚未完成私有服务配置。"}
            </small>
          </div>
        </div>
        <Tag color={service?.provider_offline ? "success" : "default"}>
          {service?.provider_offline ? "离线 Provider" : "可能产生费用"}
        </Tag>
      </section>

      <section
        className={styles.credentialBar}
        data-configured={credential?.configured ?? false}
        aria-live="polite"
      >
        <div>
          <strong>
            {credentialError
              ? "无法确认个人凭据状态"
              : credential?.configured
                ? "个人 Provider 凭据已配置"
                : "发起任务前需要个人凭据"}
          </strong>
          <small>
            {credentialError
              ? `${credentialError} 发起新任务前请进入凭据设置重试。`
              : credential?.configured
                ? `新任务使用 ${credential.provider_name} · ${credential.model ?? "未记录"}${credential.thinking_enabled ? " · 思考模式" : ""} · 凭据 v${credential.version ?? "—"}；Token 费用计入你的 Provider 账户。`
                : "漫读不会回退到管理员 Key。请先选择 Provider、模型并加密保存自己的 API Key。"}
          </small>
        </div>
        <Button
          type={credential?.configured && !credentialError ? "default" : "primary"}
          href="/settings/provider-credential"
        >
          {credential?.configured && !credentialError ? "查看与轮换" : "去配置"}
        </Button>
      </section>

      {runs.length === 0 ? (
        <EmptyState
          title="还没有翻译任务"
          detail="请从书籍详情中带当前 TXT 文件的原文版本发起翻译。"
        />
      ) : (
        <div className={styles.runGroups} aria-label="翻译任务列表">
          <section aria-labelledby="active-runs">
            <div className={styles.groupHeading}>
              <h2 id="active-runs">进行中</h2>
              <span>{runs.filter((run) => activeStatuses.has(run.status)).length}</span>
            </div>
            <div className={styles.activeList}>
              {runs.filter((run) => activeStatuses.has(run.status)).length === 0 ? (
                <div className={styles.emptyGroup}>暂无进行中的翻译任务</div>
              ) : runs.filter((run) => activeStatuses.has(run.status)).map((run) => (
                <Card className={styles.runCard} key={run.id}>
                  <article>
                    <div className={styles.runHeading}>
                      <div>
                        <h3>{run.book_title}</h3>
                        <span>{run.source_edition_title} → {run.target_language}</span>
                      </div>
                      <StatusTag status={run.status} label={runStatusLabel(run)} />
                    </div>
                    <div className={styles.runMeta}>
                      <span>译本：{run.edition_title}</span>
                      <span>模型 {configurationValue(run, "provider_model")}</span>
                      <span>发起人 {run.creator.display_name}</span>
                      <span>{formatDate(run.updated_at)}</span>
                    </div>
                    <div className={styles.runProgress}>
                      <Progress
                        percent={Math.round(run.progress * 100)}
                        size="small"
                        showInfo={false}
                      />
                      <strong>{Math.round(run.progress * 100)}%</strong>
                    </div>
                    <div className={styles.runActions}>
                      <Button onClick={() => openRun(run.id)}>查看详情</Button>
                    </div>
                  </article>
                </Card>
              ))}
            </div>
          </section>

          <section aria-labelledby="settled-runs">
            <div className={styles.groupHeading}>
              <h2 id="settled-runs">已完成 / 待处理</h2>
              <span>{runs.filter((run) => !activeStatuses.has(run.status)).length}</span>
            </div>
            <div className={styles.settledList}>
              {runs.filter((run) => !activeStatuses.has(run.status)).length === 0 ? (
                <div className={styles.emptyGroup}>暂无已完成或待处理任务</div>
              ) : runs.filter((run) => !activeStatuses.has(run.status)).map((run) => (
                <article className={styles.runRow} key={run.id}>
                  <div className={styles.runRowMain}>
                    <div className={styles.runHeading}>
                      <div>
                        <h3>{run.book_title}</h3>
                        <span>{run.source_edition_title} → {run.target_language}</span>
                      </div>
                      <StatusTag status={run.status} label={runStatusLabel(run)} />
                    </div>
                    <div className={styles.runMeta}>
                      <span>{run.error_message ?? run.edition_title}</span>
                      <span>模型 {configurationValue(run, "provider_model")}</span>
                      <span>发起人 {run.creator.display_name}</span>
                      <span>{formatDate(run.updated_at)}</span>
                    </div>
                  </div>
                  <Button onClick={() => openRun(run.id)}>查看详情</Button>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}

      <Drawer
        title="翻译任务详情"
        placement="right"
        open={detailOpen && selected !== null}
        onClose={() => setDetailOpen(false)}
        size={Math.min(760, typeof window === "undefined" ? 760 : window.innerWidth)}
      >
        {selected ? (
          <section className={styles.detail} aria-live="polite">
            <Card className={styles.detailCard}>
              <div className={styles.detailHeading}>
                <div>
                  <p className={styles.eyebrow}>任务详情</p>
                  <h2>{selected.edition_title}</h2>
                  <p>{selected.book_title} · {selected.source_edition_title}</p>
                </div>
                <StatusTag status={selected.status} label={runStatusLabel(selected)} />
              </div>
              <Progress
                className={styles.progress}
                percent={Math.round(selected.progress * 100)}
                status={selected.status === "failed" ? "exception" : undefined}
              />

              {selected.error_message ? (
                <Alert
                  type={selected.status === "attention_required" ? "warning" : "error"}
                  showIcon
                  title={selected.error_message}
                  description={selected.error_code ? `错误代码：${selected.error_code}` : undefined}
                />
              ) : null}
              {pollMessage ? <Alert type="info" showIcon title={pollMessage} /> : null}

              <div className={styles.actions}>
                {selected.available_actions.map((action) => (
                  <ActionControl
                    action={action}
                    activeAction={activeAction}
                    key={action}
                    onAction={(nextAction) => void performAction(nextAction)}
                  />
                ))}
                {selected.generated_edition_id ? (
                  <Link className={styles.previewLink} to={`/read/${selected.generated_edition_id}`}>
                    {selected.can_preview_draft ? "预览生成草稿" : "阅读生成译本"}
                  </Link>
                ) : null}
                {selected.can_publish ? (
                  <Popconfirm
                    title="审核并发布生成译本"
                    description="发布为可用版本后，其他阅读者将能看到并阅读该译本。"
                    okText="确认发布"
                    cancelText="返回"
                    onConfirm={() => void publishGeneratedEdition()}
                  >
                    <Button
                      type="primary"
                      loading={activeAction === "publish"}
                      disabled={activeAction !== null}
                    >
                      审核并发布
                    </Button>
                  </Popconfirm>
                ) : null}
              </div>
            </Card>

            <Card className={styles.detailCard} title={<h3>来源快照</h3>}>
              <Descriptions
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: "creator", label: "翻译发起人", children: selected.creator.display_name },
                  { key: "target", label: "目标语言", children: selected.target_language },
                  { key: "source", label: "原文 Edition", children: selected.source_edition_title },
                  { key: "file", label: "固定文件", children: `r${selected.source_revision} · ${selected.source_format.toUpperCase()}` },
                  {
                    key: "output",
                    label: "输出约定",
                    children: selected.source_format === "epub"
                      ? "结构保持 EPUB（章节、目录、链接与资源）"
                      : "UTF-8 TXT",
                  },
                  {
                    key: "sha",
                    label: "SHA-256",
                    children: <code className={styles.hash}>{selected.source_sha256}</code>,
                  },
                  { key: "created", label: "创建时间", children: formatDate(selected.created_at) },
                  { key: "started", label: "开始时间", children: selected.started_at ? formatDate(selected.started_at) : "尚未开始" },
                  { key: "completed", label: "完成时间", children: selected.completed_at ? formatDate(selected.completed_at) : "尚未完成" },
                ]}
              />
            </Card>

            <Card className={styles.detailCard} title={<h3>服务关联</h3>}>
              <Descriptions
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: "service", label: "服务版本", children: configurationValue(selected, "service_version") },
                  { key: "pipeline", label: "Pipeline", children: `${configurationValue(selected, "pipeline_key")} · ${configurationValue(selected, "pipeline_version")}` },
                  {
                    key: "provider",
                    label: "绑定 Provider",
                    children: firstConfigurationValue(
                      selected,
                      ["credential_provider_name", "credential_provider", "provider_id"],
                    ),
                  },
                  { key: "model", label: "模型", children: configurationValue(selected, "provider_model") },
                  {
                    key: "thinking",
                    label: "思考模式",
                    children: configurationBooleanLabel(selected, "thinking_enabled"),
                  },
                  {
                    key: "base-url",
                    label: "API Base URL",
                    children: configurationValue(selected, "credential_base_url"),
                  },
                  { key: "project", label: "Project ID", children: selected.remote_project_id ?? "尚未建立" },
                  { key: "job", label: "Job ID", children: selected.remote_job_id ?? "尚未建立" },
                  { key: "artifact", label: "Artifact ID", children: selected.remote_artifact_id ?? "尚未生成" },
                  { key: "request", label: "远端 Request ID", children: selected.remote_request_id ?? "未返回" },
                  {
                    key: "cleanup",
                    label: "清理状态",
                    children: cleanupStatusLabels[selected.cleanup_status] ?? selected.cleanup_status,
                  },
                  { key: "retry", label: "重试次数", children: selected.retry_count },
                ]}
              />
              {selected.cleanup_error ? (
                <Alert className={styles.cardAlert} type="warning" showIcon title={selected.cleanup_error} />
              ) : null}
            </Card>
          </section>
        ) : null}
      </Drawer>
    </main>
  );
}
