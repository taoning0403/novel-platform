import { Alert, Card } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, userFacingError } from "../api/client";
import type { Session } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AccountPages.module.css";

export function SessionsPage() {
  const auth = useAuth();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRevokingOthers, setIsRevokingOthers] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const loadedRef = useRef(false);

  const load = useCallback(async () => {
    if (!loadedRef.current) setIsLoading(true);
    setError(null);
    try {
      setSessions(await api.listSessions());
      loadedRef.current = true;
    }
    catch (caught) { setError(userFacingError(caught)); }
    finally { setIsLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function revoke(session: Session) {
    setBusyId(session.id);
    setError(null);
    try {
      await api.revokeSession(session.id);
      if (session.is_current) { await auth.logout(); return; }
      setMessage("会话已撤销。");
      await load();
    } catch (caught) { setError(userFacingError(caught)); }
    finally { setBusyId(null); }
  }

  async function revokeOthers() {
    setIsRevokingOthers(true);
    setError(null);
    try {
      const result = await api.revokeOtherSessions();
      setMessage(`已撤销 ${result.revoked_count} 个其他会话。`);
      await load();
    } catch (caught) { setError(userFacingError(caught)); }
    finally { setIsRevokingOthers(false); }
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="账号安全"
        title="登录会话"
        description="查看当前身份的登录会话；撤销操作会在下一次请求前生效。"
        primaryAction={(
          <DestructiveAction
            label="撤销其他全部会话"
            title="撤销当前会话以外的全部会话？"
            description="其他设备上的会话会立即失效，当前会话保持可用。"
            loading={isRevokingOthers}
            onConfirm={revokeOthers}
          />
        )}
      />
      {isLoading ? <LoadingBlock label="正在读取会话…" /> : null}
      {!isLoading && error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}
      {!isLoading && !error && sessions.length === 0 ? <EmptyState title="没有会话" detail="当前没有可显示的登录会话。" /> : null}
      <div className={styles.list}>
        {sessions.map((session) => (
          <Card className={styles.item} key={session.id}>
            <article className={styles.itemBody}>
              <div className={styles.itemCopy}>
                <div className={styles.itemHeading}>
                  <h2>{session.device_name}</h2>
                  {session.is_current ? <StatusTag status="current_session" /> : null}
                  {session.recovery_mode ? <StatusTag status="recovery_session" /> : null}
                  {session.revoked ? <StatusTag status="revoked" /> : null}
                </div>
                <p className={styles.meta}>
                  {session.platform} · 登录 {formatDate(session.created_at)} · 最近 {formatDate(session.last_seen_at)}
                </p>
                <p className={styles.meta}>到期 {formatDate(session.expires_at)}</p>
              </div>
              <DestructiveAction
                label="撤销"
                title={`撤销“${session.device_name}”上的会话？`}
                description={session.is_current
                  ? "当前会话会立即失效，你将返回登录页。"
                  : "该设备上的这个会话会立即失效，其他会话不受影响。"}
                disabled={session.revoked}
                loading={busyId === session.id}
                onConfirm={() => revoke(session)}
              />
            </article>
          </Card>
        ))}
      </div>
      {message ? <Alert className={styles.notice} type="success" showIcon title={message} /> : null}
      {!isLoading && error && sessions.length > 0 ? (
        <Alert className={styles.notice} type="error" showIcon title={error} />
      ) : null}
    </main>
  );
}
