import {
  Alert,
  Button,
  Checkbox,
  Dropdown,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
} from "antd";
import type { MenuProps } from "antd";
import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";

import { api, userFacingError } from "../api/client";
import type {
  Device,
  IssuedReaderCredential,
  ReaderIdentity,
  SecurityAuditEvent,
} from "../api/types";
import { ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AdminReadersPage.module.css";

type ReaderFilter = "all" | "active" | "restricted";
type DetailTab = "overview" | "devices" | "sessions" | "events";
type ConfirmAction = "reissue" | "revoke" | "revoke-sessions";

function defaultExpiry(): string {
  const date = new Date(Date.now() + 30 * 86_400_000);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function expiryIso(value: string): string {
  return new Date(value).toISOString();
}

function isActiveReader(reader: ReaderIdentity): boolean {
  return reader.status === "active"
    && reader.credential?.effective_status === "active";
}

function readerStatus(reader: ReaderIdentity): string {
  if (reader.status !== "active") return reader.status;
  return reader.credential?.effective_status ?? "missing";
}

function readerInitial(reader: ReaderIdentity): string {
  return reader.display_name.trim().slice(0, 1) || "读";
}

function expirySummary(reader: ReaderIdentity): string {
  if (!reader.credential) return "未签发";
  const milliseconds = new Date(reader.credential.expires_at).getTime() - Date.now();
  const days = Math.ceil(milliseconds / 86_400_000);
  if (days < 0) return "已过期";
  if (days === 0) return "今天";
  return `${days} 天`;
}

function ReaderDetail({
  reader,
  onBack,
  onChanged,
  onIssued,
}: {
  reader: ReaderIdentity;
  onBack: () => void;
  onChanged: () => Promise<void>;
  onIssued: (issued: IssuedReaderCredential) => void;
}) {
  const [displayName, setDisplayName] = useState(reader.display_name);
  const [adminNote, setAdminNote] = useState(reader.admin_note ?? "");
  const [expiresAt, setExpiresAt] = useState(
    reader.credential
      ? new Date(reader.credential.expires_at).toISOString().slice(0, 16)
      : defaultExpiry(),
  );
  const [maxDevices, setMaxDevices] = useState(reader.credential?.max_devices ?? 3);
  const [allowNewDevices, setAllowNewDevices] = useState(
    reader.credential?.allow_new_devices ?? true,
  );
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [events, setEvents] = useState<SecurityAuditEvent[] | null>(null);
  const [isSecurityLoading, setIsSecurityLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const tabRefs = useRef<Record<DetailTab, HTMLButtonElement | null>>({
    overview: null,
    devices: null,
    sessions: null,
    events: null,
  });

  const credential = reader.credential;
  const activeSessionCount = devices === null
    ? null
    : devices.reduce(
      (total, device) => total + (device.revoked_at ? 0 : device.active_session_count),
      0,
    );

  const loadSecurityDetails = useCallback(async () => {
    setIsSecurityLoading(true);
    setError(null);
    try {
      const [nextDevices, nextEvents] = await Promise.all([
        api.listReaderDevices(reader.id),
        api.readerAudit(reader.id),
      ]);
      setDevices(nextDevices);
      setEvents(nextEvents);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSecurityLoading(false);
    }
  }, [reader.id]);

  async function runAction(run: () => Promise<unknown>, successMessage: string): Promise<boolean> {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await run();
      await onChanged();
      if (devices !== null || events !== null) await loadSecurityDetails();
      setMessage(successMessage);
      return true;
    } catch (caught) {
      setError(userFacingError(caught));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(
      () =>
        api.patchReader(reader.id, {
          display_name: displayName,
          admin_note: adminNote.trim() || null,
          expires_at: expiryIso(expiresAt),
          max_devices: maxDevices,
          allow_new_devices: allowNewDevices,
        }),
      "阅读者设置已保存。",
    );
  }

  function selectTab(tab: DetailTab) {
    setActiveTab(tab);
    if (tab !== "overview" && (devices === null || events === null) && !isSecurityLoading) {
      void loadSecurityDetails();
    }
  }

  async function executeConfirmedAction() {
    if (!confirmAction) return;
    let succeeded = false;
    if (confirmAction === "revoke") {
      succeeded = await runAction(
        () => api.revokeReaderCredential(reader.id),
        "凭证已永久撤销。",
      );
    } else if (confirmAction === "revoke-sessions") {
      succeeded = await runAction(
        () => api.revokeReaderSessions(reader.id),
        "已撤销该阅读者的全部会话。",
      );
    } else {
      succeeded = await runAction(async () => {
        const issued = await api.reissueReaderCredential(reader.id, {
          expires_at: expiryIso(expiresAt),
          max_devices: maxDevices,
          allow_new_devices: allowNewDevices,
        });
        onIssued(issued);
      }, "已重新签发访问凭证。");
    }
    if (succeeded) setConfirmAction(null);
  }

  const consequenceCopy = confirmAction === "revoke"
    ? {
        title: "永久撤销这份凭证？",
        description: "旧凭证、设备和会话将永久失效。",
      }
    : confirmAction === "revoke-sessions"
      ? {
          title: "撤销该阅读者的全部会话？",
          description: "所有设备上的活跃会话都需要重新认证。",
        }
      : {
          title: "重新签发访问凭证？",
          description: "旧凭证、设备和全部会话将失效，并生成仅显示一次的新凭证。",
        };

  const actionItems: MenuProps["items"] = [
    ...(credential?.lifecycle_status === "suspended"
      ? [{ key: "resume", label: "恢复凭证" }]
      : credential?.lifecycle_status === "active"
        ? [{ key: "suspend", label: "暂停凭证" }]
        : []),
    { key: "reissue", label: "重新签发", danger: true },
    { key: "revoke-sessions", label: "撤销全部会话", danger: true },
    ...(credential?.lifecycle_status !== "revoked"
      ? [{ key: "revoke", label: "永久撤销", danger: true }]
      : []),
  ];

  function handleMenuAction(key: string) {
    if (key === "suspend") {
      void runAction(() => api.suspendReaderCredential(reader.id), "凭证已暂停。");
    } else if (key === "resume") {
      void runAction(() => api.resumeReaderCredential(reader.id), "凭证已恢复。");
    } else {
      setConfirmAction(key as ConfirmAction);
    }
  }

  const tabItems: Array<{ key: DetailTab; label: string }> = [
    { key: "overview", label: "概览" },
    { key: "devices", label: `设备 ${credential?.active_device_count ?? 0}` },
    {
      key: "sessions",
      label: activeSessionCount === null ? "会话" : `会话 ${activeSessionCount}`,
    },
    { key: "events", label: "安全事件" },
  ];

  function handleTabKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % tabItems.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + tabItems.length) % tabItems.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabItems.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    const nextTab = tabItems[nextIndex].key;
    selectTab(nextTab);
    tabRefs.current[nextTab]?.focus();
  }

  return (
    <section className={styles.detail} aria-labelledby={`reader-title-${reader.id}`}>
      <button
        className={styles.mobileBack}
        type="button"
        data-mobile-back
        onClick={onBack}
        aria-label="返回阅读者列表"
      >
        <span aria-hidden="true">←</span> 返回阅读者列表
      </button>

      <header className={styles.detailHeader}>
        <div className={styles.identity}>
          <span className={styles.avatarLarge} aria-hidden="true">{readerInitial(reader)}</span>
          <div>
            <div className={styles.identityTitle}>
              <h2 id={`reader-title-${reader.id}`}>{reader.display_name}</h2>
              <StatusTag
                status={readerStatus(reader)}
                label={readerStatus(reader) === "missing" ? "无凭证" : undefined}
              />
            </div>
            <p>
              {reader.admin_note ?? "无管理员备注"}
              {credential ? <> · <code>{credential.hint}</code></> : null}
            </p>
          </div>
        </div>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: actionItems,
            onClick: ({ key }) => handleMenuAction(key),
          }}
        >
          <Button disabled={busy} aria-label="更多阅读者操作">更多操作</Button>
        </Dropdown>
      </header>

      <div className={styles.metrics} aria-label="阅读者访问概况">
        <article>
          <span>凭证有效期</span>
          <strong>{expirySummary(reader)}</strong>
          <small>{credential ? `${formatDate(credential.expires_at)} 到期` : "需要重新签发"}</small>
        </article>
        <article>
          <span>授权设备</span>
          <strong>{credential ? `${credential.active_device_count} / ${credential.max_devices}` : "0 / 0"}</strong>
          <small>{credential?.allow_new_devices ? "允许新增设备" : "不允许新增设备"}</small>
        </article>
        <article>
          <span>活跃会话</span>
          <strong>{activeSessionCount ?? "待读取"}</strong>
          <small>{activeSessionCount === null ? "打开设备或会话页后统计" : "按已授权设备汇总"}</small>
        </article>
      </div>

      <nav className={styles.tabs} aria-label="阅读者详情" role="tablist">
        {tabItems.map((tab, index) => (
          <button
            className={activeTab === tab.key ? styles.activeTab : undefined}
            key={tab.key}
            type="button"
            role="tab"
            id={`reader-tab-${reader.id}-${tab.key}`}
            ref={(element) => {
              tabRefs.current[tab.key] = element;
            }}
            tabIndex={activeTab === tab.key ? 0 : -1}
            aria-selected={activeTab === tab.key}
            aria-controls={`reader-panel-${reader.id}-${tab.key}`}
            onClick={() => selectTab(tab.key)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {message ? <Alert className={styles.notice} type="success" showIcon title={message} role="status" /> : null}
      {error ? <Alert className={styles.notice} type="error" showIcon title={error} /> : null}

      {activeTab === "overview" ? (
        <div
          id={`reader-panel-${reader.id}-overview`}
          role="tabpanel"
          aria-labelledby={`reader-tab-${reader.id}-overview`}
          className={styles.panel}
        >
          <form className={styles.form} onSubmit={(event) => void save(event)}>
            <div className={styles.sectionHeading}>
              <div>
                <h3>身份与凭证</h3>
                <p>保存后只更新这位阅读者的访问设置。</p>
              </div>
            </div>
            <div className={styles.formGrid}>
              <label className={styles.field} htmlFor={`reader-name-${reader.id}`}>
                显示名称
                <Input
                  id={`reader-name-${reader.id}`}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
              <label className={styles.field} htmlFor={`reader-expiry-${reader.id}`}>
                凭证有效期
                <input
                  className={styles.nativeInput}
                  id={`reader-expiry-${reader.id}`}
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(event) => setExpiresAt(event.target.value)}
                />
              </label>
              <label className={`${styles.field} ${styles.fieldWide}`} htmlFor={`reader-note-${reader.id}`}>
                管理员备注
                <Input.TextArea
                  id={`reader-note-${reader.id}`}
                  rows={3}
                  value={adminNote}
                  onChange={(event) => setAdminNote(event.target.value)}
                />
              </label>
            </div>

            <div className={styles.policy}>
              <div>
                <h3>设备策略</h3>
                <p>新设备需要当前有效凭证，并受设备上限约束。</p>
              </div>
              <div className={styles.policyControls}>
                <label className={styles.field} htmlFor={`reader-devices-${reader.id}`}>
                  设备上限
                  <InputNumber
                    id={`reader-devices-${reader.id}`}
                    min={1}
                    max={100}
                    value={maxDevices}
                    onChange={(value) => setMaxDevices(value ?? 1)}
                  />
                </label>
                <div className={styles.switchRow}>
                  <Switch
                    checked={allowNewDevices}
                    onChange={setAllowNewDevices}
                    aria-label={`允许 ${reader.display_name} 新增设备`}
                  />
                  <span>
                    <strong>{allowNewDevices ? "允许新增设备" : "禁止新增设备"}</strong>
                    <small>关闭后，现有设备仍可继续访问。</small>
                  </span>
                </div>
              </div>
            </div>

            <div className={styles.formActions}>
              <Button type="primary" htmlType="submit" loading={busy}>保存阅读者设置</Button>
            </div>
          </form>
        </div>
      ) : null}

      {activeTab === "devices" ? (
        <div
          id={`reader-panel-${reader.id}-devices`}
          role="tabpanel"
          aria-labelledby={`reader-tab-${reader.id}-devices`}
          className={styles.panel}
        >
          <div className={styles.sectionHeading}>
            <div><h3>授权设备</h3><p>撤销设备会同时结束它的活跃会话。</p></div>
            <Button disabled={isSecurityLoading} onClick={() => void loadSecurityDetails()}>刷新</Button>
          </div>
          {isSecurityLoading && devices === null ? <LoadingBlock label="正在读取设备…" /> : null}
          {!isSecurityLoading && devices?.length === 0 ? <p className={styles.emptyPanel}>尚无设备。</p> : null}
          <div className={styles.rows}>
            {devices?.map((device) => (
              <article className={styles.deviceRow} key={device.id}>
                <span className={styles.deviceIcon} aria-hidden="true">器</span>
                <div>
                  <strong>{device.name}</strong>
                  <p>
                    {device.platform} · {device.active_session_count} 个活跃会话 · 最近使用 {formatDate(device.last_seen_at)}
                  </p>
                </div>
                <StatusTag status={device.revoked_at ? "revoked" : "active"} />
                {!device.revoked_at ? (
                  <DestructiveAction
                    label={`撤销设备 ${device.name}`}
                    title="撤销这台设备？"
                    description="该设备的授权和活跃会话将失效。"
                    loading={busy}
                    onConfirm={async () => {
                      await runAction(
                        () => api.revokeReaderDevice(reader.id, device.id),
                        "设备已撤销。",
                      );
                    }}
                    size="small"
                  />
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {activeTab === "sessions" ? (
        <div
          id={`reader-panel-${reader.id}-sessions`}
          role="tabpanel"
          aria-labelledby={`reader-tab-${reader.id}-sessions`}
          className={styles.panel}
        >
          <div className={styles.sectionHeading}>
            <div>
              <h3>会话按设备汇总</h3>
              <p>当前接口只提供每台设备的活跃会话数量，这里不推测单个会话信息。</p>
            </div>
            <Button disabled={isSecurityLoading} onClick={() => void loadSecurityDetails()}>刷新</Button>
          </div>
          {isSecurityLoading && devices === null ? <LoadingBlock label="正在读取会话汇总…" /> : null}
          {!isSecurityLoading && activeSessionCount === 0 ? <p className={styles.emptyPanel}>当前没有活跃会话。</p> : null}
          <div className={styles.rows}>
            {devices
              ?.filter((device) => !device.revoked_at && device.active_session_count > 0)
              .map((device) => (
                <article className={styles.sessionRow} key={device.id}>
                  <div>
                    <strong>{device.name}</strong>
                    <p>{device.platform} · 最近使用 {formatDate(device.last_seen_at)}</p>
                  </div>
                  <strong>{device.active_session_count} 个活跃会话</strong>
                </article>
              ))}
          </div>
        </div>
      ) : null}

      {activeTab === "events" ? (
        <div
          id={`reader-panel-${reader.id}-events`}
          role="tabpanel"
          aria-labelledby={`reader-tab-${reader.id}-events`}
          className={styles.panel}
        >
          <div className={styles.sectionHeading}>
            <div><h3>最近安全事件</h3><p>仅显示不含原始凭证和令牌的必要事件。</p></div>
            <Button disabled={isSecurityLoading} onClick={() => void loadSecurityDetails()}>刷新</Button>
          </div>
          {isSecurityLoading && events === null ? <LoadingBlock label="正在读取安全事件…" /> : null}
          {!isSecurityLoading && events?.length === 0 ? <p className={styles.emptyPanel}>尚无安全事件。</p> : null}
          <div className={styles.rows}>
            {events?.slice(0, 12).map((event) => (
              <article className={styles.eventRow} key={event.id}>
                <div>
                  <strong>{event.event_type}</strong>
                  <p>{formatDate(event.created_at)}</p>
                </div>
                <StatusTag status={event.outcome} label={event.outcome} />
              </article>
            ))}
          </div>
        </div>
      ) : null}

      <Modal
        open={confirmAction !== null}
        title={consequenceCopy.title}
        okText="确认执行"
        cancelText="取消"
        okButtonProps={{ danger: true, "aria-label": "确认执行" }}
        cancelButtonProps={{ "aria-label": "取消" }}
        confirmLoading={busy}
        onCancel={() => setConfirmAction(null)}
        onOk={() => void executeConfirmedAction()}
      >
        <p className={styles.confirmDescription}>{consequenceCopy.description}</p>
      </Modal>
    </section>
  );
}

export function AdminReadersPage() {
  const [readers, setReaders] = useState<ReaderIdentity[]>([]);
  const [selectedReaderId, setSelectedReaderId] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [readerFilter, setReaderFilter] = useState<ReaderFilter>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [adminNote, setAdminNote] = useState("");
  const [expiresAt, setExpiresAt] = useState(defaultExpiry);
  const [maxDevices, setMaxDevices] = useState(3);
  const [allowNewDevices, setAllowNewDevices] = useState(true);
  const [issued, setIssued] = useState<IssuedReaderCredential | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const workbenchRef = useRef<HTMLDivElement | null>(null);
  const selectedReaderTriggerRef = useRef<HTMLButtonElement | null>(null);
  const mobileFocusTargetRef = useRef<"detail" | "list" | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const nextReaders = await api.listReaders();
      setReaders(nextReaders);
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const focusTarget = mobileFocusTargetRef.current;
    if (!focusTarget) return;
    const isMobile = typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 760px)").matches
      : window.innerWidth <= 760;
    if (!isMobile) {
      mobileFocusTargetRef.current = null;
      return;
    }
    const timer = window.setTimeout(() => {
      if (focusTarget === "detail") {
        workbenchRef.current
          ?.querySelector<HTMLButtonElement>("[data-mobile-back]")
          ?.focus();
      } else {
        selectedReaderTriggerRef.current?.focus();
      }
      mobileFocusTargetRef.current = null;
    }, 0);
    return () => window.clearTimeout(timer);
  }, [mobileDetailOpen, selectedReaderId]);

  const counts = useMemo(() => ({
    all: readers.length,
    active: readers.filter(isActiveReader).length,
    restricted: readers.filter((reader) => !isActiveReader(reader)).length,
  }), [readers]);

  const filteredReaders = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
    return readers.filter((reader) => {
      if (readerFilter === "active" && !isActiveReader(reader)) return false;
      if (readerFilter === "restricted" && isActiveReader(reader)) return false;
      if (!normalizedQuery) return true;
      const searchable = [
        reader.display_name,
        reader.admin_note ?? "",
        reader.credential?.hint ?? "",
      ].join(" ").toLocaleLowerCase("zh-CN");
      return searchable.includes(normalizedQuery);
    });
  }, [query, readerFilter, readers]);

  useEffect(() => {
    if (readers.length === 0) {
      setSelectedReaderId(null);
      setMobileDetailOpen(false);
      return;
    }
    if (filteredReaders.length > 0 && !filteredReaders.some((reader) => reader.id === selectedReaderId)) {
      setSelectedReaderId(filteredReaders[0].id);
    }
  }, [filteredReaders, readers.length, selectedReaderId]);

  const selectedReader = filteredReaders.find((reader) => reader.id === selectedReaderId) ?? null;

  function showIssued(nextIssued: IssuedReaderCredential) {
    setCopyStatus(null);
    setIssued(nextIssued);
  }

  function resetCreateForm() {
    setDisplayName("");
    setAdminNote("");
    setExpiresAt(defaultExpiry());
    setMaxDevices(3);
    setAllowNewDevices(true);
    setCreateError(null);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsCreating(true);
    setCreateError(null);
    try {
      const result = await api.createReader({
        display_name: displayName,
        admin_note: adminNote.trim() || null,
        expires_at: expiryIso(expiresAt),
        max_devices: maxDevices,
        allow_new_devices: allowNewDevices,
      });
      setCreateOpen(false);
      setSelectedReaderId(result.reader.id);
      setMobileDetailOpen(true);
      showIssued(result);
      resetCreateForm();
      await load();
    } catch (caught) {
      setCreateError(userFacingError(caught));
    } finally {
      setIsCreating(false);
    }
  }

  async function copyCredential() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.access_credential);
      setCopyStatus("已复制。请通过安全渠道交给阅读者。");
    } catch {
      setCopyStatus("浏览器不允许自动复制，请手动复制。");
    }
  }

  function selectReader(readerId: string, trigger: HTMLButtonElement) {
    selectedReaderTriggerRef.current = trigger;
    mobileFocusTargetRef.current = "detail";
    setSelectedReaderId(readerId);
    setMobileDetailOpen(true);
  }

  function closeMobileDetail() {
    mobileFocusTargetRef.current = "list";
    setMobileDetailOpen(false);
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="身份与访问"
        title="阅读者"
        description="选择一个阅读者，再调整凭证、设备与会话。"
        primaryAction={<Button type="primary" onClick={() => setCreateOpen(true)}>签发凭证</Button>}
      />

      {isLoading ? <LoadingBlock label="正在读取阅读者…" /> : null}
      {!isLoading && error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}

      {!isLoading && !error ? (
        <div
          ref={workbenchRef}
          className={`${styles.workbench}${mobileDetailOpen ? ` ${styles.mobileDetailActive}` : ""}`}
          data-mobile-view={mobileDetailOpen ? "detail" : "list"}
        >
          <aside className={styles.master} aria-label="阅读者列表">
            <div className={styles.masterHeading}>
              <strong>受邀阅读者</strong>
              <span>{readers.length} 位</span>
            </div>
            <Input
              type="search"
              aria-label="搜索阅读者"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索名称或凭证提示"
              allowClear
            />
            <div className={styles.filters} aria-label="阅读者状态筛选">
              {([
                ["all", `全部 ${counts.all}`],
                ["active", `启用 ${counts.active}`],
                ["restricted", `受限 ${counts.restricted}`],
              ] as Array<[ReaderFilter, string]>).map(([key, label]) => (
                <button
                  className={readerFilter === key ? styles.activeFilter : undefined}
                  key={key}
                  type="button"
                  aria-pressed={readerFilter === key}
                  onClick={() => setReaderFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className={styles.readerList}>
              {readers.length === 0 ? (
                <div className={styles.emptyList}>
                  <strong>还没有阅读者</strong>
                  <p>使用页面上方的“签发凭证”创建阅读身份，并通过安全渠道交付凭证。</p>
                </div>
              ) : filteredReaders.length === 0 ? (
                <div className={styles.emptyList}>
                  <strong>没有匹配的阅读者</strong>
                  <p>调整搜索词或状态筛选后重试。</p>
                </div>
              ) : filteredReaders.map((reader) => (
                <button
                  className={`${styles.readerItem}${selectedReaderId === reader.id ? ` ${styles.selectedReader}` : ""}`}
                  key={reader.id}
                  type="button"
                  aria-pressed={selectedReaderId === reader.id}
                  onClick={(event) => selectReader(reader.id, event.currentTarget)}
                >
                  <span className={styles.avatar} aria-hidden="true">{readerInitial(reader)}</span>
                  <span className={styles.readerCopy}>
                    <strong>{reader.display_name}</strong>
                    <small>
                      {reader.credential ? <code>{reader.credential.hint}</code> : "尚未签发凭证"}
                      {reader.credential?.last_used_at ? ` · ${formatDate(reader.credential.last_used_at)}` : ""}
                    </small>
                  </span>
                  <span
                    className={`${styles.statusDot}${isActiveReader(reader) ? ` ${styles.statusActive}` : ""}`}
                    aria-label={isActiveReader(reader) ? "启用" : "受限"}
                  />
                </button>
              ))}
            </div>
            <p className={styles.masterNote}>凭证轮换不会改变阅读者身份与阅读进度。</p>
          </aside>

          {selectedReader ? (
            <ReaderDetail
              key={selectedReader.id}
              reader={selectedReader}
              onBack={closeMobileDetail}
              onChanged={load}
              onIssued={showIssued}
            />
          ) : (
            <section className={styles.emptyDetail}>
              <span aria-hidden="true">读</span>
              <h2>选择或签发阅读者</h2>
              <p>阅读者的身份、凭证策略、设备和安全事件会显示在这里。</p>
            </section>
          )}
        </div>
      ) : null}

      {createOpen ? (
        <Modal
          key="create-reader"
          open
          title="签发初始凭证"
          footer={null}
          onCancel={() => {
            if (!isCreating) {
              setCreateOpen(false);
              resetCreateForm();
            }
          }}
        >
          <form className={styles.createForm} onSubmit={(event) => void create(event)}>
            <p className={styles.formIntro}>创建阅读身份后，完整访问凭证只显示一次。</p>
            <label className={styles.field} htmlFor="new-reader-name">
              显示名称
              <Input
                id="new-reader-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </label>
            <label className={styles.field} htmlFor="new-reader-note">
              管理员备注
              <Input.TextArea
                id="new-reader-note"
                rows={3}
                value={adminNote}
                onChange={(event) => setAdminNote(event.target.value)}
              />
            </label>
            <label className={styles.field} htmlFor="new-reader-expiry">
              有效期
              <input
                className={styles.nativeInput}
                id="new-reader-expiry"
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
                required
              />
            </label>
            <label className={styles.field} htmlFor="new-reader-max-devices">
              设备上限
              <InputNumber
                id="new-reader-max-devices"
                min={1}
                max={100}
                value={maxDevices}
                onChange={(value) => setMaxDevices(value ?? 1)}
              />
            </label>
            <Checkbox
              checked={allowNewDevices}
              onChange={(event) => setAllowNewDevices(event.target.checked)}
            >
              允许新增设备
            </Checkbox>
            {createError ? <Alert type="error" showIcon title={createError} /> : null}
            <div className={styles.modalActions}>
              <Button
                htmlType="button"
                disabled={isCreating}
                onClick={() => {
                  setCreateOpen(false);
                  resetCreateForm();
                }}
              >
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={isCreating}>创建并显示凭证</Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {issued ? (
        <Modal
          key="issued-reader-credential"
          open
          title="保存访问凭证（仅显示一次）"
          closable={false}
          mask={{ closable: false }}
          keyboard={false}
          onCancel={() => undefined}
          footer={
            <Space wrap>
              <Button onClick={() => void copyCredential()}>复制凭证</Button>
              <Button
                type="primary"
                onClick={() => {
                  flushSync(() => {
                    setIssued(null);
                    setCopyStatus(null);
                  });
                }}
              >
                我已安全保存
              </Button>
            </Space>
          }
        >
          <Alert
            type="warning"
            showIcon
            title={`${issued.reader.display_name} 的完整凭证离开此窗口后无法再次取得。`}
          />
          <code className={styles.credentialCode}>{issued.access_credential}</code>
          {copyStatus ? <Alert type="info" showIcon title={copyStatus} role="status" /> : null}
        </Modal>
      ) : null}
    </main>
  );
}
