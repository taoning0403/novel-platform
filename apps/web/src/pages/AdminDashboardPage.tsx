import { Alert, Card, Statistic } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, userFacingError } from "../api/client";
import type { ReaderIdentity, SiteSettings } from "../api/types";
import { ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./AdminPages.module.css";

const adminLinks = [
  {
    title: "阅读者与凭证",
    detail: "创建身份、调整期限与设备上限、撤销设备和会话。",
    to: "/admin/readers",
  },
  {
    title: "管理员安全",
    detail: "注册和管理 Passkey，查看管理员会话与恢复说明。",
    to: "/admin/security",
  },
  {
    title: "公开站点设置",
    detail: "维护用途、隐私、备案展示和默认安全参数。",
    to: "/admin/site",
  },
  {
    title: "安全审计",
    detail: "按事件、阅读者、结果和时间筛选必要事件。",
    to: "/admin/audit",
  },
];

export function AdminDashboardPage() {
  const [site, setSite] = useState<SiteSettings | null>(null);
  const [readers, setReaders] = useState<ReaderIdentity[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.getAdminSite(), api.listReaders()])
      .then(([nextSite, nextReaders]) => {
        setSite(nextSite);
        setReaders(nextReaders);
      })
      .catch((caught: unknown) => setError(userFacingError(caught)));
  }, []);

  if (error) {
    return (
      <main className={styles.page}>
        <ErrorNotice message={error} />
      </main>
    );
  }
  if (!site) {
    return (
      <main className={styles.page}>
        <LoadingBlock label="正在读取管理状态…" />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.dashboardHeader}>
        <PageHeader
          eyebrow="站点管理"
          title={site.site_name}
          description="维护共享馆藏、受邀阅读者、Passkey 和最小必要安全设置。"
          compact
        />
        <Card className={styles.readerCount}>
          <Statistic title="受邀阅读者" value={readers.length} suffix="位" />
        </Card>
      </div>

      <section className={styles.dashboardGrid} aria-label="管理功能">
        {adminLinks.map((item) => (
          <Link className={styles.dashboardLink} to={item.to} key={item.to}>
            <Card className={styles.dashboardCard} hoverable>
              <h2>{item.title}</h2>
              <p className={styles.muted}>{item.detail}</p>
            </Card>
          </Link>
        ))}
      </section>

      {site.admin_locked ? (
        <Alert
          className={styles.notice}
          type="error"
          showIcon
          title="管理员入口已被服务器紧急锁定。"
        />
      ) : null}
    </main>
  );
}
