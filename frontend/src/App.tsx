import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { CardSkeleton } from "@/components/common";
import { AppShell } from "@/components/layout/AppShell";
import { ANALYST_ADMIN, STAFF, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/schemas";
import AdminPage from "@/pages/AdminPage";
import AuditPage from "@/pages/AuditPage";
import CreateIncidentPage from "@/pages/CreateIncidentPage";
import IncidentDetailPage from "@/pages/IncidentDetailPage";
import IncidentsPage from "@/pages/IncidentsPage";
import LoginPage from "@/pages/LoginPage";
import QueuesPage from "@/pages/QueuesPage";

// Chart-heavy pages are split out so the recharts bundle loads only when needed.
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));

function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="p-8"><CardSkeleton rows={4} /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

// Route guard for convenience; the API rejects unauthorized calls regardless.
export function RequireRole({ roles }: { roles: Role[] }) {
  const { hasRole } = useAuth();
  if (!hasRole(...roles)) {
    return (
      <div role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
        <p className="font-medium">Access restricted</p>
        <p>Your role does not have access to this page.</p>
      </div>
    );
  }
  return <Outlet />;
}

function Home() {
  const { hasRole } = useAuth();
  return hasRole(...ANALYST_ADMIN) ? (
    <Suspense fallback={<CardSkeleton rows={4} />}>
      <DashboardPage />
    </Suspense>
  ) : (
    <Navigate to="/incidents" replace />
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="incidents" element={<IncidentsPage />} />
          <Route path="incidents/new" element={<CreateIncidentPage />} />
          <Route path="incidents/:id" element={<IncidentDetailPage />} />
          <Route path="incidents/:id/audit" element={<AuditPage />} />
          <Route element={<RequireRole roles={STAFF} />}>
            <Route path="queues" element={<QueuesPage />} />
          </Route>
          <Route element={<RequireRole roles={ANALYST_ADMIN} />}>
            <Route path="analytics" element={<Suspense fallback={<CardSkeleton rows={4} />}><AnalyticsPage /></Suspense>} />
            <Route path="admin" element={<AdminPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
