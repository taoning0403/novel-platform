import { Button, Card, Input, Select, Table, Tag, Typography } from "antd";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api, userFacingError } from "../api/client";
import type { ReaderIdentity, SecurityAuditEvent } from "../api/types";
import { EmptyState, ErrorNotice, LoadingBlock } from "../shared/AsyncState";
import { formatDate } from "../shared/format";
import { PageHeader } from "../ui/components/PageHeader";
import styles from "./AdminPages.module.css";

function localIso(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined;
}

export function AdminAuditPage() {
  const [events, setEvents] = useState<SecurityAuditEvent[]>([]);
  const [readers, setReaders] = useState<ReaderIdentity[]>([]);
  const [eventType, setEventType] = useState("");
  const [subjectUserId, setSubjectUserId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (filters = {}) => {
    setIsLoading(true);
    setError(null);
    try {
      setEvents(await api.listAudit(filters));
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([load(), api.listReaders().then(setReaders)]).catch(
      (caught: unknown) => setError(userFacingError(caught)),
    );
  }, [load]);

  const readerNames = useMemo(
    () => new Map(readers.map((reader) => [reader.id, reader.display_name])),
    [readers],
  );

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load({
      eventType: eventType.trim() || undefined,
      subjectUserId: subjectUserId || undefined,
      outcome: outcome.trim() || undefined,
      createdFrom: localIso(createdFrom),
      createdTo: localIso(createdTo),
    });
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="最小必要留痕"
        title="安全审计"
        description="记录认证、凭证、设备、会话、Passkey 与恢复操作；不记录原始访问凭证、恢复凭证或令牌。"
      />

      <Card className={styles.filterCard}>
        <form className={styles.filterGrid} onSubmit={filter}>
          <label className={styles.field} htmlFor="audit-event-type">
            事件类型
            <Input
              id="audit-event-type"
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
              placeholder="例如 login_succeeded"
            />
          </label>
          <label className={styles.field} htmlFor="audit-reader">
            阅读者
            <Select
              id="audit-reader"
              value={subjectUserId}
              onChange={setSubjectUserId}
              options={[
                { value: "", label: "全部身份" },
                ...readers.map((reader) => ({
                  value: reader.id,
                  label: reader.display_name,
                })),
              ]}
            />
          </label>
          <label className={styles.field} htmlFor="audit-outcome">
            结果
            <Input
              id="audit-outcome"
              value={outcome}
              onChange={(event) => setOutcome(event.target.value)}
              placeholder="success / denied"
            />
          </label>
          <label className={styles.field} htmlFor="audit-created-from">
            起始时间
            <input
              className={styles.nativeInput}
              id="audit-created-from"
              type="datetime-local"
              value={createdFrom}
              onChange={(event) => setCreatedFrom(event.target.value)}
            />
          </label>
          <label className={styles.field} htmlFor="audit-created-to">
            结束时间
            <input
              className={styles.nativeInput}
              id="audit-created-to"
              type="datetime-local"
              value={createdTo}
              onChange={(event) => setCreatedTo(event.target.value)}
            />
          </label>
          <Button type="primary" htmlType="submit" loading={isLoading}>
            筛选
          </Button>
        </form>
      </Card>

      {isLoading ? <LoadingBlock label="正在读取安全事件…" /> : null}
      {error ? (
        <ErrorNotice message={error} onRetry={() => void load()} />
      ) : null}
      {!isLoading && !error && events.length === 0 ? (
        <EmptyState title="没有匹配事件" detail="调整筛选条件后重试。" />
      ) : null}
      {!isLoading && !error && events.length > 0 ? (
        <Card className={styles.tableCard} styles={{ body: { padding: 0 } }}>
          <p className={styles.tableScrollHint}>
            表格可左右滑动，查看完整事件、来源和元数据。
          </p>
          <Table<SecurityAuditEvent>
            rowKey="id"
            dataSource={events}
            pagination={false}
            scroll={{ x: 1080 }}
            columns={[
              {
                title: "时间",
                dataIndex: "created_at",
                key: "created_at",
                width: 180,
                render: (value: string) => formatDate(value),
              },
              {
                title: "事件",
                dataIndex: "event_type",
                key: "event_type",
                width: 190,
                render: (value: string) => <code>{value}</code>,
              },
              {
                title: "结果",
                dataIndex: "outcome",
                key: "outcome",
                width: 100,
                render: (value: string) => (
                  <Tag color={value === "success" ? "success" : "warning"}>
                    {value}
                  </Tag>
                ),
              },
              {
                title: "身份",
                dataIndex: "subject_user_id",
                key: "subject_user_id",
                width: 150,
                render: (value: string | null) =>
                  (value && readerNames.get(value)) ??
                  value?.slice(0, 8) ??
                  "系统",
              },
              {
                title: "来源",
                key: "source",
                width: 230,
                render: (_, item) => (
                  <>
                    {item.client_ip ?? "—"}
                    <br />
                    <small>{item.user_agent_summary ?? "—"}</small>
                  </>
                ),
              },
              {
                title: "元数据",
                dataIndex: "metadata",
                key: "metadata",
                render: (value: unknown) => {
                  const metadata = JSON.stringify(value);
                  return (
                    <Typography.Paragraph
                      className={styles.metadata}
                      code
                      copyable={{ text: metadata, tooltips: ["复制元数据", "已复制"] }}
                      ellipsis={{
                        rows: 3,
                        expandable: "collapsible",
                        symbol: (expanded) => (expanded ? "收起" : "展开"),
                      }}
                    >
                      {metadata}
                    </Typography.Paragraph>
                  );
                },
              },
            ]}
          />
        </Card>
      ) : null}
    </main>
  );
}
