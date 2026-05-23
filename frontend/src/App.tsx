import { Routes, Route, Navigate } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Layout } from './components/Layout';
import CasesPage from './routes/CasesPage';
import CaseDetailPage from './routes/CaseDetailPage';
import RunsPage from './routes/RunsPage';
import RunNewPage from './routes/RunNewPage';
import RunDetailPage from './routes/RunDetailPage';
import CaseNewPage from './routes/CaseNewPage';
import NotFoundPage from './routes/NotFoundPage';

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/cases" replace />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/new" element={<CaseNewPage />} />
          <Route path="/cases/:id" element={<CaseDetailPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<RunNewPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
