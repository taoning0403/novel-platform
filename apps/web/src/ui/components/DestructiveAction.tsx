import { Button, Popconfirm } from "antd";
import type { ButtonProps } from "antd";

interface DestructiveActionProps {
  label: string;
  title: string;
  description: string;
  onConfirm: () => void | Promise<void>;
  loading?: boolean;
  disabled?: boolean;
  block?: boolean;
  size?: ButtonProps["size"];
  type?: ButtonProps["type"];
}

export function DestructiveAction({
  label,
  title,
  description,
  onConfirm,
  loading = false,
  disabled = false,
  block = false,
  size,
  type = "default",
}: DestructiveActionProps) {
  return (
    <Popconfirm
      title={title}
      description={description}
      okText={<span>确认执行</span>}
      cancelText={<span>取消</span>}
      okButtonProps={{ danger: true, "aria-label": "确认执行" }}
      cancelButtonProps={{ "aria-label": "取消" }}
      onConfirm={() => void onConfirm()}
      disabled={disabled || loading}
    >
      <Button
        danger
        type={type}
        loading={loading}
        disabled={disabled}
        block={block}
        size={size}
        aria-label={label}
      >
        {label}
      </Button>
    </Popconfirm>
  );
}
