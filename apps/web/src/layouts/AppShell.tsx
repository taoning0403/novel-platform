import { Avatar, Button, Drawer } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { BrandMark } from "../ui/components/BrandMark";
import {
  InterfaceIcon,
  type InterfaceIconName,
} from "../ui/components/InterfaceIcon";
import styles from "./AppShell.module.css";

interface NavigationItem {
  label: string;
  to: string;
  icon: InterfaceIconName;
  end?: boolean;
}

interface NavigationGroup {
  label: string;
  items: NavigationItem[];
}

function NavigationLink({ item, mobile = false }: { item: NavigationItem; mobile?: boolean }) {
  return (
    <NavLink
      className={({ isActive }) => (
        `${styles.navLink}${mobile ? ` ${styles.drawerLink}` : ""}${isActive ? ` ${styles.active}` : ""}`
      )}
      to={item.to}
      end={item.end}
    >
      <span className={styles.navIcon}><InterfaceIcon name={item.icon} /></span>
      <span>{item.label}</span>
    </NavLink>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const authenticated = auth.phase === "authenticated" && auth.user !== null;
  const isAdmin = auth.user?.role === "admin";
  const canUpload = auth.user?.capabilities.includes("library.upload") ?? false;
  const canTranslate = auth.user?.capabilities.includes("translation.use") ?? false;
  const recoveryMode = auth.session?.recovery_mode === true;
  const readerRoute = location.pathname.startsWith("/read/");
  const loginRoute = location.pathname === "/login";
  const siteName = auth.site?.site_name ?? "漫读";

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  async function logout() {
    await auth.logout();
    navigate("/login", { replace: true, state: null });
  }

  if (readerRoute || loginRoute) return <>{children}</>;

  const groups: NavigationGroup[] = recoveryMode
    ? [{
        label: "账户恢复",
        items: [{ label: "登记 Passkey", to: "/admin/security", icon: "security" }],
      }]
    : [
        {
          label: "阅读",
          items: [
            { label: "书库", to: "/", icon: "library", end: true },
            { label: "系列", to: "/series", icon: "series" },
          ],
        },
        ...(isAdmin || canUpload || canTranslate ? [{
          label: "贡献与管理",
          items: [
            ...(canUpload
              ? [{ label: "上传", to: "/upload", icon: "upload" as const }]
              : []),
            ...(canTranslate
              ? [{ label: "小说翻译", to: "/translations", icon: "translation" as const }]
              : []),
            ...(isAdmin
              ? [
                  { label: "管理", to: "/admin", icon: "manage" as const, end: true },
                  { label: "阅读者", to: "/admin/readers", icon: "readers" as const },
                  { label: "安全", to: "/admin/security", icon: "security" as const },
                  { label: "站点", to: "/admin/site", icon: "site" as const },
                  { label: "审计", to: "/admin/audit", icon: "audit" as const },
                ]
              : []),
          ],
        }] : []),
        {
          label: "个人",
          items: [
            { label: "身份", to: "/settings/profile", icon: "profile" },
            ...(canTranslate
              ? [{
                  label: "翻译凭据",
                  to: "/settings/provider-credential",
                  icon: "security" as const,
                }]
              : []),
            { label: "设备", to: "/settings/devices", icon: "devices" },
            { label: "会话", to: "/settings/sessions", icon: "sessions" },
            ...(isAdmin ? [{ label: "状态", to: "/status", icon: "status" as const }] : []),
          ],
        },
      ];
  const allItems = groups.flatMap((group) => group.items);
  const quickItems = recoveryMode
    ? allItems
    : isAdmin
      ? allItems.filter((item) => ["/", "/series", "/admin"].includes(item.to))
      : allItems.filter((item) => ["/", "/series", "/settings/profile"].includes(item.to));
  const identityLabel = recoveryMode
    ? "恢复会话"
    : isAdmin
      ? "站点管理员"
      : canUpload || canTranslate
        ? "受邀贡献者"
        : "受邀阅读者";

  return (
    <div className={styles.shell}>
      {authenticated ? (
        <aside className={styles.sidebar}>
          <NavLink
            className={styles.brand}
            to={recoveryMode ? "/admin/security" : "/"}
            aria-label={`${siteName} 首页`}
          >
            <BrandMark />
            <span className={styles.brandCopy}>
              <strong>{siteName}</strong>
              <small>私人阅读空间</small>
            </span>
          </NavLink>

          <nav className={styles.desktopNav} aria-label="主导航">
            {groups.map((group) => (
              <section className={styles.navGroup} key={group.label}>
                <p>{group.label}</p>
                {group.items.map((item) => <NavigationLink item={item} key={item.to} />)}
              </section>
            ))}
          </nav>

          <div className={styles.sidebarFooter}>
            <div className={styles.account}>
              <Avatar className={styles.avatar}>{auth.user?.display_name.slice(0, 1)}</Avatar>
              <span className={styles.accountCopy}>
                <strong>{auth.user?.display_name}</strong>
                <span>{identityLabel}</span>
              </span>
            </div>
            <Button type="text" size="small" onClick={() => void logout()}>退出</Button>
            <span className={styles.version}>漫读 v0.10.0</span>
          </div>
        </aside>
      ) : null}

      <section className={`${styles.workspace}${authenticated ? "" : ` ${styles.workspacePublic}`}`}>
        {authenticated ? (
          <header className={styles.mobileHeader}>
            <NavLink
              className={styles.mobileBrand}
              to={recoveryMode ? "/admin/security" : "/"}
              aria-label={`${siteName} 首页`}
            >
              <BrandMark compact />
              <strong>{siteName}</strong>
            </NavLink>
            <Button
              className={styles.mobileTrigger}
              type="text"
              icon={<InterfaceIcon name="more" />}
              aria-label="打开主导航"
              onClick={() => setMobileOpen(true)}
            />
          </header>
        ) : null}

        <div className={styles.content}>{children}</div>

        {authenticated ? (
          <nav className={styles.bottomNav} aria-label="快捷导航">
            {quickItems.map((item) => (
              <NavLink
                key={item.to}
                className={({ isActive }) => `${styles.bottomLink}${isActive ? ` ${styles.bottomActive}` : ""}`}
                to={item.to}
                end={item.end}
              >
                <InterfaceIcon name={item.icon} />
                <span>{item.label}</span>
              </NavLink>
            ))}
            <button className={styles.bottomLink} type="button" onClick={() => setMobileOpen(true)}>
              <InterfaceIcon name="more" />
              <span>更多</span>
            </button>
          </nav>
        ) : null}
      </section>

      <Drawer
        title={(
          <span className={styles.drawerTitle}>
            <BrandMark compact />
            <span><strong>{siteName}</strong><small>全部导航</small></span>
          </span>
        )}
        placement="right"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        size={Math.min(380, typeof window === "undefined" ? 380 : window.innerWidth)}
      >
        <nav className={styles.drawerNav} aria-label="移动主导航">
          {groups.map((group) => (
            <section className={styles.drawerGroup} key={group.label}>
              <p>{group.label}</p>
              {group.items.map((item) => <NavigationLink item={item} mobile key={item.to} />)}
            </section>
          ))}
        </nav>
        <div className={styles.drawerAccount}>
          <div className={styles.account}>
            <Avatar className={styles.avatar}>{auth.user?.display_name.slice(0, 1)}</Avatar>
            <span className={styles.accountCopy}>
              <strong>{auth.user?.display_name}</strong>
              <span>{identityLabel}</span>
            </span>
          </div>
          <Button danger block onClick={() => void logout()}>退出</Button>
        </div>
      </Drawer>
    </div>
  );
}
