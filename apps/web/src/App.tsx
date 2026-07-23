import { lazy, Suspense, type ReactNode } from "react";
import { Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "./auth/ProtectedRoute";
import type { CredentialCapability } from "./api/types";
import { AppShell } from "./layouts/AppShell";
import { LoadingBlock } from "./shared/AsyncState";
import { PageHeader } from "./ui/components/PageHeader";
import styles from "./App.module.css";

const AdminAuditPage = lazy(() => import("./pages/AdminAuditPage").then((module) => ({ default: module.AdminAuditPage })));
const AdminDashboardPage = lazy(() => import("./pages/AdminDashboardPage").then((module) => ({ default: module.AdminDashboardPage })));
const AdminReadersPage = lazy(() => import("./pages/AdminReadersPage").then((module) => ({ default: module.AdminReadersPage })));
const AdminSecurityPage = lazy(() => import("./pages/AdminSecurityPage").then((module) => ({ default: module.AdminSecurityPage })));
const AdminSitePage = lazy(() => import("./pages/AdminSitePage").then((module) => ({ default: module.AdminSitePage })));
const BookDetailPage = lazy(() => import("./pages/BookDetailPage").then((module) => ({ default: module.BookDetailPage })));
const DevicesPage = lazy(() => import("./pages/DevicesPage").then((module) => ({ default: module.DevicesPage })));
const LibraryPage = lazy(() => import("./pages/LibraryPage").then((module) => ({ default: module.LibraryPage })));
const LoginPage = lazy(() => import("./pages/LoginPage").then((module) => ({ default: module.LoginPage })));
const ProfilePage = lazy(() => import("./pages/ProfilePage").then((module) => ({ default: module.ProfilePage })));
const ReaderPage = lazy(() => import("./pages/ReaderPage").then((module) => ({ default: module.ReaderPage })));
const SeriesDetailPage = lazy(() => import("./pages/SeriesDetailPage").then((module) => ({ default: module.SeriesDetailPage })));
const SeriesPage = lazy(() => import("./pages/SeriesPage").then((module) => ({ default: module.SeriesPage })));
const SeriesUploadPage = lazy(() => import("./pages/SeriesUploadPage").then((module) => ({ default: module.SeriesUploadPage })));
const SessionsPage = lazy(() => import("./pages/SessionsPage").then((module) => ({ default: module.SessionsPage })));
const StatusPage = lazy(() => import("./pages/StatusPage").then((module) => ({ default: module.StatusPage })));
const UploadPage = lazy(() => import("./pages/UploadPage").then((module) => ({ default: module.UploadPage })));

function Protected({
  children,
  admin = false,
  recovery = false,
  capability,
}: {
  children: ReactNode;
  admin?: boolean;
  recovery?: boolean;
  capability?: CredentialCapability;
}) {
  return (
    <ProtectedRoute admin={admin} recovery={recovery} capability={capability}>
      {children}
    </ProtectedRoute>
  );
}

export function RouteFallback() {
  return (
    <main className={styles.routePage}>
      <LoadingBlock label="正在加载页面…" />
    </main>
  );
}

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<Protected><LibraryPage /></Protected>} />
          <Route path="/books/:bookId" element={<Protected><BookDetailPage /></Protected>} />
          <Route path="/series" element={<Protected><SeriesPage /></Protected>} />
          <Route path="/series/:seriesId" element={<Protected><SeriesDetailPage /></Protected>} />
          <Route path="/series/:seriesId/upload" element={<Protected admin><SeriesUploadPage /></Protected>} />
          <Route path="/read/:editionId" element={<Protected><ReaderPage /></Protected>} />
          <Route
            path="/upload"
            element={<Protected capability="library.upload"><UploadPage /></Protected>}
          />
          <Route path="/settings/profile" element={<Protected><ProfilePage /></Protected>} />
          <Route path="/settings/devices" element={<Protected><DevicesPage /></Protected>} />
          <Route path="/settings/sessions" element={<Protected><SessionsPage /></Protected>} />
          <Route path="/admin" element={<Protected admin><AdminDashboardPage /></Protected>} />
          <Route path="/admin/readers" element={<Protected admin><AdminReadersPage /></Protected>} />
          <Route path="/admin/security" element={<Protected admin recovery><AdminSecurityPage /></Protected>} />
          <Route path="/admin/site" element={<Protected admin><AdminSitePage /></Protected>} />
          <Route path="/admin/audit" element={<Protected admin><AdminAuditPage /></Protected>} />
          <Route path="/status" element={<Protected admin><StatusPage /></Protected>} />
          <Route path="*" element={<main className={styles.routePage}><PageHeader eyebrow="404" title="页面不存在" description="请返回书库或使用主导航继续。" /></main>} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
