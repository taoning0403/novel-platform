import { Alert, Button, Card, Descriptions, Input } from "antd";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { userFacingError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { formatDate } from "../shared/format";
import { credentialCapabilityLabels } from "../shared/labels";
import { PageHeader } from "../ui/components/PageHeader";
import { StatusTag } from "../ui/components/StatusTag";
import styles from "./AccountPages.module.css";

export function ProfilePage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth.user;
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (user === null) return null;

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      await auth.updateDisplayName(displayName);
      setMessage("显示名称已更新。");
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <main className={styles.page}>
      <PageHeader
        eyebrow="身份设置"
        title="我的身份"
        description="登录凭证与阅读身份相互独立；管理员轮换访问凭证不会清除你的进度和偏好。"
      />
      <div className={styles.grid}>
        <Card className={styles.card} title={<h2 className={styles.cardTitle}>身份信息</h2>}>
          <Descriptions
            column={1}
            items={[
              { key: "name", label: "显示名称", children: user.display_name },
              { key: "role", label: "身份类型", children: user.role === "admin" ? "站点管理员" : "受邀阅读者" },
              { key: "status", label: "状态", children: <StatusTag status={user.status} /> },
              {
                key: "capabilities",
                label: "有效权限",
                children: user.capabilities.map(
                  (capability) => credentialCapabilityLabels[capability],
                ).join("、") || "无馆藏权限",
              },
              { key: "created", label: "创建时间", children: formatDate(user.created_at) },
              { key: "login", label: "上次登录", children: user.last_login_at ? formatDate(user.last_login_at) : "尚无记录" },
            ]}
          />
          <form className={styles.form} onSubmit={(event) => void saveProfile(event)}>
            <label className={styles.field} htmlFor="profile-display-name">
              显示名称
              <Input
                id="profile-display-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </label>
            <Button type="primary" htmlType="submit" loading={isSaving}>
              保存显示名称
            </Button>
          </form>
        </Card>
        <Card
          className={styles.card}
          title={<h2 className={styles.cardTitle}>{user.role === "admin" ? "管理员认证" : "访问凭证"}</h2>}
        >
          <p>
            {user.role === "admin"
              ? "管理员使用 Passkey 登录；恢复凭证仅用于登记新的 Passkey，不是日常登录方式。"
              : "完整访问凭证只在签发时显示一次。本站不会向你展示或恢复原始凭证。"}
          </p>
          <div className={styles.actions}>
            {user.role === "admin" ? (
              <Button type="primary" onClick={() => navigate("/admin/security")}>管理 Passkey</Button>
            ) : null}
            <Button onClick={() => navigate("/settings/devices")}>管理设备</Button>
            <Button onClick={() => navigate("/settings/sessions")}>管理会话</Button>
          </div>
        </Card>
      </div>
      {message ? <Alert className={styles.notice} type="success" showIcon title={message} /> : null}
      {error ? <Alert className={styles.notice} type="error" showIcon title={error} /> : null}
    </main>
  );
}
