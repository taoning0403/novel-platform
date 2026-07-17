import { AsyncPanel } from "../ui/components/AsyncPanel";

interface ErrorNoticeProps {
  message: string;
  onRetry?: () => void;
}

export function LoadingBlock({ label = "正在加载…" }: { label?: string }) {
  return <AsyncPanel kind="loading" detail={label} />;
}

export function ErrorNotice({ message, onRetry }: ErrorNoticeProps) {
  return <AsyncPanel kind="error" title="加载失败" detail={message} onRetry={onRetry} />;
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <AsyncPanel kind="empty" title={title} detail={detail} />;
}
