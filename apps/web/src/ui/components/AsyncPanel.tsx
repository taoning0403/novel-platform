import { Alert, Button, Empty, Flex, Spin, Typography } from "antd";

import styles from "./AsyncPanel.module.css";

interface AsyncPanelProps {
  kind: "loading" | "empty" | "error" | "success" | "status";
  title?: string;
  detail: string;
  onRetry?: () => void;
}

export function AsyncPanel({ kind, title, detail, onRetry }: AsyncPanelProps) {
  if (kind === "loading") {
    return (
      <div
        className={`${styles.panel} ${styles.loading}`}
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <Flex vertical align="center" gap={14}>
          <Spin />
          <Typography.Text type="secondary">{detail}</Typography.Text>
        </Flex>
      </div>
    );
  }

  if (kind === "error") {
    return (
      <div className={`${styles.panel} ${styles.error}`}>
        <Alert
          type="error"
          showIcon
          title={title ?? "加载失败"}
          description={detail}
          action={onRetry ? (
            <Button type="text" onClick={onRetry}>重试</Button>
          ) : undefined}
        />
      </div>
    );
  }

  if (kind === "empty") {
    return (
      <div className={styles.panel} role="status">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={(
            <Flex vertical gap={6}>
              <Typography.Text strong>{title}</Typography.Text>
              <Typography.Text type="secondary">{detail}</Typography.Text>
            </Flex>
          )}
        />
      </div>
    );
  }

  return (
    <div className={`${styles.panel} ${styles.status}`} role="status" aria-live="polite">
      <Alert
        type={kind === "success" ? "success" : "info"}
        showIcon
        title={title}
        description={detail}
      />
    </div>
  );
}
