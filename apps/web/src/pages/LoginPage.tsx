import { Alert, Button, Card, Divider, Input } from "antd";
import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { userFacingError } from "../api/client";
import { defaultDeviceName, useAuth } from "../auth/AuthProvider";
import { LoadingBlock } from "../shared/AsyncState";
import { BrandMark } from "../ui/components/BrandMark";
import styles from "./AuthPages.module.css";

interface LoginLocationState {
  from?: string;
}

export function LoginPage() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as LoginLocationState | null;
  const [credential, setCredential] = useState("");
  const [deviceName, setDeviceName] = useState(defaultDeviceName);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPasskeySubmitting, setIsPasskeySubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (auth.phase === "loading") {
    return <main className={styles.loadingPage}><LoadingBlock label="正在读取站点配置…" /></main>;
  }
  if (auth.phase === "authenticated") {
    if (auth.session?.recovery_mode) return <Navigate to="/admin/security" replace />;
    return <Navigate to={auth.user?.role === "admin" ? "/admin" : "/"} replace />;
  }

  async function submitCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const user = await auth.login(credential, deviceName);
      setCredential("");
      navigate(user.role === "admin" ? "/admin" : (state?.from ?? "/"), { replace: true });
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitPasskey() {
    setIsPasskeySubmitting(true);
    setError(null);
    try {
      await auth.loginWithPasskey(deviceName);
      navigate("/admin", { replace: true });
    } catch (caught) {
      setError(userFacingError(caught));
    } finally {
      setIsPasskeySubmitting(false);
    }
  }

  const siteName = auth.site?.site_name ?? "漫读";
  const purpose = auth.site?.purpose_statement ?? "本站仅供站点所有者和少量受邀阅读者使用。";
  const privacy = auth.site?.privacy_statement ?? "系统仅处理登录与设备安全所需的最少信息。";

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.brand}>
          <BrandMark />
          <span>
            <h1 id="site-title">{siteName}</h1>
            <small>私人阅读空间</small>
          </span>
        </header>

        <Card className={styles.loginCard}>
          <section aria-labelledby="login-title">
            <h2 className={styles.loginTitle} id="login-title">登录</h2>
            <p className={styles.formIntro}>使用访问凭证进入{siteName}。</p>
            {auth.siteError ? (
              <Alert
                className={styles.siteAlert}
                type="warning"
                showIcon
                title="站点信息暂时不可用；你仍可继续登录。"
              />
            ) : null}
            <form className={styles.form} onSubmit={(event) => void submitCredential(event)}>
              <label className={styles.field} htmlFor="access-credential">
                访问凭证
                <Input.Password
                  id="access-credential"
                  type="password"
                  autoComplete="one-time-code"
                  value={credential}
                  onChange={(event) => setCredential(event.target.value)}
                  required
                />
              </label>
              <label className={styles.field} htmlFor="device-name">
                设备名称
                <Input
                  id="device-name"
                  value={deviceName}
                  maxLength={100}
                  onChange={(event) => setDeviceName(event.target.value)}
                  required
                />
              </label>
              {error ? <Alert type="error" showIcon title={error} /> : null}
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={isSubmitting}
                disabled={isPasskeySubmitting}
              >
                进入书库
              </Button>
              <Divider plain>管理员</Divider>
              <Button
                block
                loading={isPasskeySubmitting}
                disabled={isSubmitting}
                onClick={() => void submitPasskey()}
              >
                <span className={styles.passkeyDot} aria-hidden="true" />
                使用安全设备登录
              </Button>
            </form>
          </section>
        </Card>

        <footer className={styles.footer}>
          <span>个人非经营性站点</span>
          <details className={styles.disclosure}>
            <summary>站点与隐私说明</summary>
            <div className={styles.disclosurePanel}>
              <strong>站点用途</strong>
              <p>{purpose}</p>
              <strong>隐私说明</strong>
              <p>{privacy}</p>
            </div>
          </details>
          {auth.site?.icp_registration_number ? (
            auth.site.icp_registration_url ? (
              <a href={auth.site.icp_registration_url} rel="noreferrer">
                {auth.site.icp_registration_number}
              </a>
            ) : <span>{auth.site.icp_registration_number}</span>
          ) : null}
        </footer>
      </div>
    </main>
  );
}
