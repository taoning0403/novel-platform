import { Alert, Button, Card, Descriptions, Input, InputNumber } from "antd";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, userFacingError } from "../api/client";
import type { SiteSettings } from "../api/types";
import { ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AdminPages.module.css";

export function AdminSitePage() {
  const [site, setSite] = useState<SiteSettings | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setSite(await api.getAdminSite());
    } catch (caught) {
      setError(userFacingError(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function update<K extends keyof SiteSettings>(
    key: K,
    value: SiteSettings[K],
  ) {
    setSite((current) =>
      current ? { ...current, [key]: value } : current,
    );
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!site) return;
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await api.patchAdminSite({
        site_name: site.site_name,
        purpose_statement: site.purpose_statement,
        privacy_statement: site.privacy_statement,
        icp_registration_number:
          site.icp_registration_number?.trim() || null,
        icp_registration_url: site.icp_registration_url?.trim() || null,
        default_reader_max_devices: site.default_reader_max_devices,
        audit_retention_days: site.audit_retention_days,
      });
      setSite(updated);
      setMessage("站点设置已保存；公开登录页会使用这些内容。");
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSaving(false);
    }
  }

  if (!site && !error) {
    return (
      <main className={styles.page}>
        <LoadingBlock label="正在读取站点设置…" />
      </main>
    );
  }
  if (!site) {
    return (
      <main className={styles.page}>
        <ErrorNotice
          message={error ?? "无法读取站点设置。"}
          onRetry={() => void load()}
        />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="备案友好化"
        title="公开站点设置"
        description="只展示真实填写的备案信息；未备案时保持为空，不伪造备案号或链接。"
      />

      <form className={styles.siteSections} onSubmit={(event) => void save(event)}>
        <Card className={styles.siteCard} title="公开身份与说明">
          <div className={styles.form}>
            <label className={styles.field} htmlFor="site-name">
              站点名称
              <Input
                id="site-name"
                required
                maxLength={200}
                value={site.site_name}
                onChange={(event) => update("site_name", event.target.value)}
              />
            </label>
            <label className={styles.field} htmlFor="site-purpose">
              用途说明
              <Input.TextArea
                id="site-purpose"
                required
                rows={4}
                maxLength={2000}
                showCount
                value={site.purpose_statement}
                onChange={(event) =>
                  update("purpose_statement", event.target.value)
                }
              />
            </label>
            <label className={styles.field} htmlFor="site-privacy">
              隐私说明
              <Input.TextArea
                id="site-privacy"
                required
                rows={5}
                maxLength={4000}
                showCount
                value={site.privacy_statement}
                onChange={(event) =>
                  update("privacy_statement", event.target.value)
                }
              />
            </label>
          </div>
        </Card>

        <Card className={styles.siteCard} title="备案展示">
          <p className={styles.muted}>
            备案号和链接必须同时来自真实备案信息；两项均可留空。
          </p>
          <div className={styles.siteGrid}>
            <label className={styles.field} htmlFor="site-icp-number">
              备案号（可留空）
              <Input
                id="site-icp-number"
                value={site.icp_registration_number ?? ""}
                onChange={(event) =>
                  update(
                    "icp_registration_number",
                    event.target.value || null,
                  )
                }
              />
            </label>
            <label className={styles.field} htmlFor="site-icp-url">
              备案链接（可留空）
              <Input
                id="site-icp-url"
                type="url"
                value={site.icp_registration_url ?? ""}
                onChange={(event) =>
                  update("icp_registration_url", event.target.value || null)
                }
              />
            </label>
          </div>
        </Card>

        <Card className={styles.siteCard} title="默认安全参数">
          <div className={styles.siteGrid}>
            <label
              className={styles.field}
              htmlFor="site-default-max-devices"
            >
              阅读者默认设备上限
              <InputNumber
                id="site-default-max-devices"
                min={1}
                max={100}
                value={site.default_reader_max_devices}
                onChange={(value) =>
                  update("default_reader_max_devices", value ?? 1)
                }
              />
            </label>
            <label
              className={styles.field}
              htmlFor="site-audit-retention"
            >
              安全审计保留天数
              <InputNumber
                id="site-audit-retention"
                min={1}
                max={3650}
                value={site.audit_retention_days}
                onChange={(value) =>
                  update("audit_retention_days", value ?? 1)
                }
              />
            </label>
          </div>
          <Descriptions
            className={styles.siteStatus}
            column={{ xs: 1, sm: 2 }}
            items={[
              {
                key: "migration",
                label: "认证迁移",
                children: (
                  <StatusTag
                    status={site.migration_completed ? "succeeded" : "waiting"}
                    label={site.migration_completed ? "已完成" : "待完成"}
                  />
                ),
              },
              {
                key: "lock",
                label: "管理员紧急锁",
                children: (
                  <StatusTag
                    status={site.admin_locked ? "revoked" : "active"}
                    label={site.admin_locked ? "已锁定" : "未锁定"}
                  />
                ),
              },
            ]}
          />
        </Card>

        <Button type="primary" htmlType="submit" loading={isSaving}>
          {isSaving ? "正在保存…" : "保存设置"}
        </Button>
      </form>

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
        <Alert
          className={styles.notice}
          type="error"
          showIcon
          title={error}
        />
      ) : null}
    </main>
  );
}
