import { Alert, Button, Card, Input, Space } from "antd";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, userFacingError } from "../api/client";
import type { Passkey, Session, SiteSettings } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AdminPages.module.css";

export function AdminSecurityPage() {
  const auth = useAuth();
  const recoveryMode = auth.session?.recovery_mode === true;
  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [site, setSite] = useState<SiteSettings | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [newName, setNewName] = useState("我的 Passkey");
  const [isLoading, setIsLoading] = useState(!recoveryMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (recoveryMode) return;
    setIsLoading(true);
    setError(null);
    try {
      const [nextPasskeys, nextSessions, nextSite] = await Promise.all([
        api.listPasskeys(),
        api.listSessions(),
        api.getAdminSite(),
      ]);
      setPasskeys(nextPasskeys);
      setSessions(nextSessions);
      setSite(nextSite);
      setNames(
        Object.fromEntries(
          nextPasskeys.map((passkey) => [passkey.id, passkey.name]),
        ),
      );
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, [recoveryMode]);

  useEffect(() => {
    void load();
  }, [load]);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await auth.registerPasskey(newName);
      setNewName("我的 Passkey");
      setMessage(
        recoveryMode
          ? "新 Passkey 已登记；恢复会话已作废并升级为正常管理员会话。"
          : "新 Passkey 已登记。",
      );
      if (!recoveryMode) await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function rename(passkey: Passkey) {
    setBusy(true);
    setError(null);
    try {
      await api.renamePasskey(
        passkey.id,
        names[passkey.id] ?? passkey.name,
      );
      setMessage("Passkey 名称已更新。");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(passkey: Passkey) {
    setBusy(true);
    setError(null);
    try {
      await api.revokePasskey(passkey.id);
      setMessage("Passkey 已撤销。");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function revokeSession(session: Session) {
    setBusy(true);
    setError(null);
    try {
      await api.revokeSession(session.id);
      if (session.is_current) {
        await auth.logout();
        return;
      }
      setMessage("管理员会话已撤销。");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="无密码管理员认证"
        title="Passkey 与管理员会话"
        description={
          recoveryMode
            ? "这是一次受限恢复会话。登记新 Passkey 后，本恢复会话和其他旧管理员会话都会失效。"
            : "Passkey 由浏览器和系统认证器保护；服务器不保存密码，也不展示恢复凭证原文。"
        }
      />

      <Card className={styles.securityCard}>
        <form className={styles.form} onSubmit={(event) => void register(event)}>
          <div>
            <p className={styles.readerHint}>
              {recoveryMode ? "必须完成" : "添加认证器"}
            </p>
            <h2>
              {recoveryMode ? "登记新的 Passkey" : "登记 Passkey"}
            </h2>
          </div>
          <label className={styles.field} htmlFor="new-passkey-name">
            名称
            <Input
              id="new-passkey-name"
              required
              maxLength={200}
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
            />
          </label>
          <Button type="primary" htmlType="submit" loading={busy}>
            {busy ? "正在等待认证器…" : "开始登记"}
          </Button>
          <span className={styles.fieldHint}>
            需要支持用户验证和驻留凭证的 WebAuthn 认证器。
          </span>
        </form>
      </Card>

      {message ? (
        <Alert
          className={styles.notice}
          type="success"
          showIcon
          title={message}
          role="status"
        />
      ) : null}
      {error ? (
        <div className={styles.notice}>
          <ErrorNotice
            message={error}
            onRetry={recoveryMode ? undefined : () => void load()}
          />
        </div>
      ) : null}

      {recoveryMode ? null : isLoading ? (
        <LoadingBlock label="正在读取管理员安全状态…" />
      ) : (
        <>
          <Alert
            className={styles.notice}
            type={site?.admin_locked ? "error" : "info"}
            showIcon
            title={`管理员紧急锁：${site?.admin_locked ? "已锁定" : "未锁定"}`}
            description="初始化、恢复、认证重设、全会话撤销及锁定/解锁只能通过服务器 CLI 完成；网页不会生成恢复凭证。"
          />
          <div className={styles.settingsGrid}>
            <Card
              className={styles.securityCard}
              title="已登记 Passkey"
            >
              {passkeys.length === 0 ? (
                <EmptyState
                  title="没有 Passkey"
                  detail="请立即登记一个 Passkey。"
                />
              ) : null}
              <div className={styles.managementList}>
                {passkeys.map((passkey) => (
                  <Card
                    className={styles.managementItem}
                    size="small"
                    key={passkey.id}
                  >
                    <div className={styles.itemBody}>
                      <div className={styles.itemCopy}>
                        <div className={styles.itemHeading}>
                          <strong>{passkey.name}</strong>
                          {passkey.revoked_at ? (
                            <StatusTag status="revoked" />
                          ) : (
                            <StatusTag status="active" />
                          )}
                        </div>
                        <p className={styles.itemMeta}>
                          创建 {formatDate(passkey.created_at)} · 最近使用{" "}
                          {passkey.last_used_at
                            ? formatDate(passkey.last_used_at)
                            : "尚未使用"}
                        </p>
                        <p className={styles.itemMeta}>
                          {passkey.backed_up
                            ? "已同步或备份"
                            : "单设备认证器"}
                        </p>
                      </div>
                      <div className={styles.itemActions}>
                        <Input
                          aria-label={`重命名 ${passkey.name}`}
                          value={names[passkey.id] ?? passkey.name}
                          disabled={passkey.revoked_at !== null}
                          onChange={(event) =>
                            setNames((current) => ({
                              ...current,
                              [passkey.id]: event.target.value,
                            }))
                          }
                        />
                        <Button
                          disabled={busy || passkey.revoked_at !== null}
                          onClick={() => void rename(passkey)}
                        >
                          保存名称
                        </Button>
                        <DestructiveAction
                          label={`撤销 Passkey ${passkey.name}`}
                          title={`撤销 Passkey“${passkey.name}”？`}
                          description="至少要保留一个可用 Passkey；撤销后不能恢复。"
                          loading={busy}
                          disabled={passkey.revoked_at !== null}
                          onConfirm={() => revoke(passkey)}
                        />
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </Card>

            <Card className={styles.securityCard} title="管理员会话">
              <div className={styles.managementList}>
                {sessions.map((session) => (
                  <Card
                    className={styles.managementItem}
                    size="small"
                    key={session.id}
                  >
                    <div className={styles.itemBody}>
                      <div className={styles.itemCopy}>
                        <Space wrap>
                          <strong>{session.device_name}</strong>
                          {session.is_current ? (
                            <StatusTag status="current_session" />
                          ) : null}
                          <StatusTag
                            status={
                              session.revoked
                                ? "revoked"
                                : session.recovery_mode
                                  ? "recovery_session"
                                  : "normal_session"
                            }
                          />
                        </Space>
                        <p className={styles.itemMeta}>
                          {session.platform} · 最近{" "}
                          {formatDate(session.last_seen_at)} · 到期{" "}
                          {formatDate(session.expires_at)}
                        </p>
                      </div>
                      <DestructiveAction
                        label={`撤销 ${session.device_name} 上的管理员会话`}
                        title={`撤销“${session.device_name}”上的管理员会话？`}
                        description={
                          session.is_current
                            ? "当前会话将立即退出，且私有返回路径会被清除。"
                            : "该设备需要重新完成管理员认证。"
                        }
                        loading={busy}
                        disabled={session.revoked}
                        onConfirm={() => revokeSession(session)}
                      />
                    </div>
                  </Card>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </main>
  );
}
