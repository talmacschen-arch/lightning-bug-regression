import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';

type RunDetail = components['schemas']['RunDetail'];
type CaseResultOut = components['schemas']['CaseResultOut'];

const TERMINAL_STATUSES = new Set(['pass', 'fail', 'error', 'completed']);

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status.toLowerCase());
}

function CaseResultRow({ result }: { result: CaseResultOut }) {
  return (
    <div data-testid={`run-case-row-${result.case_id}`} className="flex items-center gap-4 py-2 border-b last:border-0">
      {/* M5-3 cross-page link: case_id is now a Link to /cases/:id */}
      <Link
        to={`/cases/${result.case_id}`}
        data-testid={`run-case-link-${result.case_id}`}
        className="font-mono text-sm text-blue-700 hover:underline"
      >
        {result.case_id}
      </Link>
      <span
        data-testid={`run-case-status-${result.case_id}`}
        className="text-xs font-medium px-2 py-0.5 rounded"
      >
        {(result.status ?? '').toUpperCase()}
      </span>
      {result.duration_ms !== undefined && result.duration_ms !== null && (
        <span className="text-xs text-gray-500">{result.duration_ms}ms</span>
      )}
    </div>
  );
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function clearPolling() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function fetchRun() {
      try {
        const data = (await apiFetch('/runs/{run_id}', 'get', {
          path: { run_id: Number(id) },
        })) as RunDetail;
        if (cancelled) return;
        setRun(data);
        setLoading(false);
        if (isTerminal(data.status)) {
          clearPolling();
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
        clearPolling();
      }
    }

    void fetchRun();

    // Start 3s polling for non-terminal status
    intervalRef.current = setInterval(() => {
      void fetchRun();
    }, 3000);

    return () => {
      cancelled = true;
      clearPolling();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading) {
    return <div data-testid="run-detail-loading">Loading run…</div>;
  }

  if (error !== null || run === null) {
    return <div data-testid="run-detail-error">Error: {error ?? 'Run not found'}</div>;
  }

  return (
    <div data-testid="page-run-detail" className="p-6 space-y-4">
      <h1 data-testid="run-detail-title">Run #{run.id}</h1>
      <span
        data-testid="run-status-badge"
        data-status={run.status}
        className="inline-block px-3 py-1 rounded text-sm font-semibold"
      >
        {run.status.toUpperCase()}
      </span>
      {run.target_version && (
        <div>
          <span className="text-sm text-gray-500">Version: </span>
          <span data-testid="run-target-version" className="font-mono text-sm">{run.target_version}</span>
        </div>
      )}
      <div className="mt-4">
        {run.case_results.map((result) => (
          <CaseResultRow key={result.case_id} result={result} />
        ))}
      </div>
    </div>
  );
}
