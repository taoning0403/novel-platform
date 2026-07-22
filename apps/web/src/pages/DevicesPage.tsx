import { Alert, Button, Card, Input } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, userFacingError } from "../api/client";
import type { Device } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { DestructiveAction } from "../ui/components/DestructiveAction";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AccountPages.module.css";

export function DevicesPage() {
  const auth = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const loadedRef = useRef(false);

  const load = useCallback(async () => {
    if (!loadedRef.current) setIsLoading(true);
    setError(null);
    try {
      const rows = await api.listDevices();
      setDevices(rows);
      setNames(Object.fromEntries(rows.map((device) => [device.id, device.name])));
      loadedRef.current = true;
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function rename(device: Device) {
    setBusyId(device.id);
    setError(null);
    setMessage(null);
    try {
      await api.renameDevice(device.id, names[device.id] ?? device.name);
      setMessage("设备名称已更新。");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusyId(null);
    }
  }

  async function revoke(device: Device) {
    setBusyId(device.id);
    setError(null);
    setMessage(null);
    try {
      await api.revokeDevice(device.id);
      if (device.is_current) {
        await auth.logout();
        return;
      }
      setMessage("设备及其会话已撤销。");
      await load();
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="账号安全"
        title="设备管理"
        description="设备是一个客户端实例；撤销设备会立即撤销其全部会话。"
        secondaryActions={<Button onClick={() => void load()}>刷新</Button>}
      />
      {isLoading ? <LoadingBlock label="正在读取设备…" /> : null}
      {!isLoading && error ? <ErrorNotice message={error} onRetry={() => void load()} /> : null}
      {!isLoading && !error && devices.length === 0 ? <EmptyState title="没有设备" detail="成功登录后设备会显示在这里。" /> : null}
      <div className={styles.list}>
        {devices.map((device) => (
          <Card className={styles.item} key={device.id}>
            <article className={styles.itemBody}>
              <div className={styles.itemCopy}>
                <div className={styles.itemHeading}>
                  <h2>{device.name}</h2>
                  {device.is_current ? <StatusTag status="current_device" /> : null}
                  {device.revoked_at ? <StatusTag status="revoked" /> : null}
                </div>
                <p className={styles.meta}>
                  {device.platform} · 首次 {formatDate(device.first_seen_at)} · 最近 {formatDate(device.last_seen_at)}
                </p>
                <p className={styles.meta}>{device.active_session_count} 个活跃会话</p>
              </div>
              <div className={styles.itemActions}>
                <Input
                  aria-label={`重命名 ${device.name}`}
                  value={names[device.id] ?? device.name}
                  onChange={(event) => setNames((current) => ({
                    ...current,
                    [device.id]: event.target.value,
                  }))}
                />
                <Button loading={busyId === device.id} onClick={() => void rename(device)}>
                  保存名称
                </Button>
                <DestructiveAction
                  label="撤销设备"
                  title={`撤销设备“${device.name}”？`}
                  description="该设备及其全部登录会话会立即失效；当前设备被撤销后需要重新登录。"
                  disabled={device.revoked_at !== null}
                  loading={busyId === device.id}
                  onConfirm={() => revoke(device)}
                />
              </div>
            </article>
          </Card>
        ))}
      </div>
      {message ? <Alert className={styles.notice} type="success" showIcon title={message} /> : null}
      {!isLoading && error && devices.length > 0 ? (
        <Alert className={styles.notice} type="error" showIcon title={error} />
      ) : null}
    </main>
  );
}
