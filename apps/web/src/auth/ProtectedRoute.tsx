import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { LoadingBlock } from "../shared/AsyncState";
import { useAuth } from "./AuthProvider";
import styles from "./ProtectedRoute.module.css";

export function ProtectedRoute({
  children,
  admin = false,
  recovery = false,
}: {
  children: ReactNode;
  admin?: boolean;
  recovery?: boolean;
}) {
  const auth = useAuth();
  const location = useLocation();
  if (auth.phase === "loading") {
    return (
      <main className={styles.loading}>
        <LoadingBlock label="正在恢复登录状态…" />
      </main>
    );
  }
  if (auth.phase !== "authenticated" || auth.user === null) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (admin && auth.user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  if (auth.session?.recovery_mode && !recovery) {
    return <Navigate to="/admin/security" replace />;
  }
  return children;
}
