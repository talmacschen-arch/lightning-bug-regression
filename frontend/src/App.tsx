import { Routes, Route, Navigate } from 'react-router-dom';
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
import NotFoundPage from './routes/NotFoundPage';

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/new" element={<CaseNewPage />} />
          <Route path="/cases/:id" element={<CaseDetailPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<RunNewPage />} />
          <Route path="/runs/diff" element={<RunsDiffPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
