import { Button, Card } from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, userFacingError } from "../api/client";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AccountPages.module.css";

type ProbeState = { state: "loading" | "ok" | "error"; detail: string };

const initialState: ProbeState = { state: "loading", detail: "正在检查…" };

export function StatusPage() {
  const [application, setApplication] = useState<ProbeState>(initialState);
  const [database, setDatabase] = useState<ProbeState>(initialState);

  const probe = useCallback(async () => {
    setApplication(initialState);
    setDatabase(initialState);
    const [live, ready] = await Promise.allSettled([api.live(), api.ready()]);
    setApplication(
      live.status === "fulfilled"
        ? { state: "ok", detail: "API 进程正在运行" }
        : { state: "error", detail: userFacingError(live.reason) },
    );
    setDatabase(
      ready.status === "fulfilled"
        ? { state: "ok", detail: "PostgreSQL 连接正常" }
        : { state: "error", detail: userFacingError(ready.reason) },
    );
  }, []);

  useEffect(() => {
    void probe();
  }, [probe]);

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="运行状态"
        title="系统健康检查"
        description="API 存活检查与数据库就绪检查彼此独立；这里只展示真实探测结果。"
        secondaryActions={<Button onClick={() => void probe()}>重新检查</Button>}
      />
      <div className={styles.statusGrid}>
        <StatusCard title="API 进程状态" probe={application} />
        <StatusCard title="数据库连接状态" probe={database} />
      </div>
    </main>
  );
}

function StatusCard({ title, probe }: { title: string; probe: ProbeState }) {
  const label = probe.state === "ok" ? "正常" : probe.state === "error" ? "异常" : "检查中";
  return (
    <Card className={styles.statusCard}>
      <article>
        <div className={styles.statusHeading}>
          <h2>{title}</h2>
          <StatusTag
            status={probe.state === "ok" ? "active" : probe.state === "error" ? "revoked" : "waiting"}
            label={label}
          />
        </div>
        <p className={styles.statusDetail}>{probe.detail}</p>
      </article>
    </Card>
  );
}
