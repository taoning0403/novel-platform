import { Tag } from "antd";

const statusPresentation: Record<string, { color: string; label: string }> = {
  active: { color: "success", label: "启用" },
  suspended: { color: "warning", label: "已暂停" },
  expired: { color: "orange", label: "已过期" },
  revoked: { color: "error", label: "已撤销" },
  ready: { color: "success", label: "可用" },
  draft: { color: "default", label: "草稿" },
  archived: { color: "default", label: "已归档" },
  not_started: { color: "default", label: "未开始" },
  reading: { color: "processing", label: "阅读中" },
  finished: { color: "success", label: "已读完" },
  current_device: { color: "processing", label: "当前设备" },
  current_session: { color: "processing", label: "当前会话" },
  recovery_session: { color: "warning", label: "恢复会话" },
  normal_session: { color: "success", label: "正常会话" },
  succeeded: { color: "success", label: "成功" },
  failed: { color: "error", label: "失败" },
  waiting: { color: "default", label: "等待" },
  inspecting: { color: "processing", label: "解析中" },
  committing: { color: "processing", label: "提交中" },
};

export function StatusTag({ status, label }: { status: string; label?: string }) {
  const presentation = statusPresentation[status] ?? {
    color: "default",
    label: status,
  };
  return <Tag color={presentation.color}>{label ?? presentation.label}</Tag>;
}
