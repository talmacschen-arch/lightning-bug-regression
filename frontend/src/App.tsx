import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Layout } from './components/Layout';
import DashboardPage from './routes/DashboardPage';
import CasesPage from './routes/CasesPage';
import CaseDetailPage from './routes/CaseDetailPage';
import CaseNewPage from './routes/CaseNewPage';
import RunsPage from './routes/RunsPage';
import RunNewPage from './routes/RunNewPage';
import RunDetailPage from './routes/RunDetailPage';
import RunsDiffPage from './routes/RunsDiffPage';
import AdminPage from './routes/AdminPage';
import AdminSkipListPage from './routes/AdminSkipListPage';
import AdminExternalServicesPage from './routes/AdminExternalServicesPage';
import AdminCasesPage from './routes/AdminCasesPage';
import LoginPage from './routes/LoginPage';
import NotFoundPage from './routes/NotFoundPage';
import { getAuthToken } from './lib/auth';

/**
 * v1.17: gate all protected routes on the localStorage token. Soft check
 * (presence, not validity) — on first API call, an invalid token will
 * trigger 401 → automatic redirect via api/client.ts. This keeps the
 * router fast (no API call needed just to navigate) while still being
 * secure (real check happens server-side on each request).
 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  if (!getAuthToken()) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/new" element={<CaseNewPage />} />
          <Route path="/cases/:id" element={<CaseDetailPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<RunNewPage />} />
          <Route path="/runs/diff" element={<RunsDiffPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/admin/skip-list" element={<AdminSkipListPage />} />
          <Route path="/admin/external-services" element={<AdminExternalServicesPage />} />
          <Route path="/admin/cases" element={<AdminCasesPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
