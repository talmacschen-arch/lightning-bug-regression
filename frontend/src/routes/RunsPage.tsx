import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { Skeleton } from '@/components/ui/skeleton';

type RunSummary = components['schemas']['RunSummary'];

const INITIAL_LIMIT = 50;
const INCREMENT = 50;

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    passed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    partial: 'bg-yellow-100 text-yellow-800',
    error: 'bg-red-200 text-red-900',
    running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-700',
    cancelled: 'bg-gray-200 text-gray-600',
  };
  const cls = colorMap[status] ?? 'bg-gray-100 text-gray-700';
  return (
    <span
      data-testid={`status-badge-${status}`}
      className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${cls}`}
    >
      {status}
    </span>
  );
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [limit, setLimit] = useState(INITIAL_LIMIT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reachedEnd, setReachedEnd] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch('/runs', 'get', { query: { limit } })
      .then((data) => {
        if (cancelled) return;
        const list = data as RunSummary[];
        setRuns(list);
        setReachedEnd(list.length < limit);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load runs');
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [limit]);

  const handleLoadMore = () => {
    setLimit((prev) => prev + INCREMENT);
  };

  if (loading) {
    return (
      <div data-testid="runs-loading" className="p-6 space-y-3">
        {[1, 2, 3, 4].map((n) => (
          <Skeleton key={n} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div data-testid="runs-error" className="p-6 text-red-600">
        <p>Error loading runs: {error}</p>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div data-testid="runs-empty" className="p-6 text-gray-500">
        <p>No runs found.</p>
      </div>
    );
  }

  return (
    <div data-testid="page-runs" className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Runs</h1>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="px-3 py-2 text-left font-medium text-gray-600">ID</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Status</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Started</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Finished</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Total</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Passed</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Failed</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Version</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Triggered By</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b hover:bg-gray-50 transition-colors">
                <td className="px-3 py-2">
                  <Link
                    to={`/runs/${run.id}`}
                    data-testid={`run-row-${run.id}`}
                    className="text-blue-600 hover:underline font-mono"
                  >
                    #{run.id}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-3 py-2 text-gray-700">{formatDate(run.started_at)}</td>
                <td className="px-3 py-2 text-gray-700">{formatDate(run.finished_at)}</td>
                <td className="px-3 py-2 text-right text-gray-700">{run.total ?? '—'}</td>
                <td className="px-3 py-2 text-right text-green-700">{run.passed ?? '—'}</td>
                <td className="px-3 py-2 text-right text-red-700">{run.failed ?? '—'}</td>
                <td className="px-3 py-2 text-gray-700 font-mono text-xs">{run.target_version ?? '—'}</td>
                <td className="px-3 py-2 text-gray-700">{run.triggered_by ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!reachedEnd && (
        <div className="mt-4">
          <button
            data-testid="btn-load-more"
            onClick={handleLoadMore}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            disabled={loading}
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
