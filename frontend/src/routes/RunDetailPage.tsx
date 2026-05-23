import { useEffect, useState, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { Skeleton } from '@/components/ui/skeleton';

type RunDetail = components['schemas']['RunDetail'];
type CaseResultOut = components['schemas']['CaseResultOut'];

const TERMINAL_STATUSES = new Set(['passed', 'failed', 'partial', 'error', 'cancelled']);
const POLL_INTERVAL_MS = 3000;
const EXPECT_DETAIL_MAX = 200;

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const colorMap: Record<string, string> = {
    passed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    partial: 'bg-yellow-100 text-yellow-800',
    error: 'bg-red-200 text-red-900',
    running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-700',
    cancelled: 'bg-gray-200 text-gray-600',
    skipped: 'bg-purple-100 text-purple-700',
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

function TruncatedText({
  text,
  maxLen = EXPECT_DETAIL_MAX,
  testId,
}: {
  text: string | null | undefined;
  maxLen?: number;
  testId?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const needsTrunc = text.length > maxLen;
  const display = !expanded && needsTrunc ? text.slice(0, maxLen) + '…' : text;

  return (
    <span>
      <span data-testid={testId}>{display}</span>
      {needsTrunc && (
        <button
          className="ml-2 text-blue-500 hover:underline text-xs"
          onClick={() => setExpanded((e) => !e)}
          data-testid={testId ? `${testId}-toggle` : undefined}
        >
          {expanded ? 'show less' : 'show more'}
        </button>
      )}
    </span>
  );
}

function CaseResultRow({ cr }: { cr: CaseResultOut }) {
  return (
    <div
      data-testid={`case-result-${cr.case_id}`}
      className="border rounded p-3 space-y-1"
    >
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-medium text-gray-800">{cr.case_id}</span>
        <StatusBadge status={cr.status} />
        <span className="text-xs text-gray-500">{formatDuration(cr.duration_ms)}</span>
      </div>
      {cr.skip_reason && (
        <div className="text-xs text-purple-700">
          <span className="font-semibold">Skip reason: </span>
          {cr.skip_reason}
        </div>
      )}
      {cr.expect_detail && (
        <div className="text-xs text-gray-600">
          <span className="font-semibold">Detail: </span>
          <TruncatedText
            text={cr.expect_detail}
            maxLen={EXPECT_DETAIL_MAX}
            testId={`expect-detail-${cr.case_id}`}
          />
        </div>
      )}
      {cr.artifacts_path && (
        <div className="text-xs">
          <a
            href={cr.artifacts_path}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`artifacts-link-${cr.case_id}`}
            className="text-blue-600 hover:underline"
          >
            Artifacts
          </a>
        </div>
      )}
    </div>
  );
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPolling = () => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const fetchRun = (isInitial: boolean) => {
    if (isInitial) setLoading(true);

    apiFetch('/runs/{run_id}', 'get', { pathParams: { run_id: runId } })
      .then((data) => {
        const detail = data as RunDetail;
        setRun(detail);
        if (isInitial) setLoading(false);
        if (isTerminal(detail.status)) {
          clearPolling();
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load run');
        if (isInitial) setLoading(false);
        clearPolling();
      });
  };

  useEffect(() => {
    if (isNaN(runId)) {
      setError('Invalid run ID');
      setLoading(false);
      return;
    }

    fetchRun(true);

    intervalRef.current = setInterval(() => {
      fetchRun(false);
    }, POLL_INTERVAL_MS);

    return () => {
      clearPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  if (loading) {
    return (
      <div data-testid="run-detail-loading" className="p-6 space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-3/4" />
      </div>
    );
  }

  if (error) {
    return (
      <div data-testid="run-detail-error" className="p-6 text-red-600">
        <p>Error: {error}</p>
      </div>
    );
  }

  if (!run) {
    return (
      <div data-testid="run-detail-empty" className="p-6 text-gray-500">
        <p>Run not found.</p>
      </div>
    );
  }

  return (
    <div data-testid="page-run-detail" className="p-6 space-y-6">
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold" data-testid="run-id">
            Run #{run.id}
          </h1>
          <StatusBadge status={run.status} />
        </div>
        <div className="text-sm text-gray-600 grid grid-cols-2 gap-x-8 gap-y-1 mt-2">
          <div>
            <span className="font-medium">Started:</span> {formatDate(run.started_at)}
          </div>
          {run.finished_at && (
            <div>
              <span className="font-medium">Finished:</span> {formatDate(run.finished_at)}
            </div>
          )}
          <div>
            <span className="font-medium">Total:</span>{' '}
            <span data-testid="run-total">{run.total ?? '—'}</span>
          </div>
          <div>
            <span className="font-medium">Passed:</span>{' '}
            <span data-testid="run-passed" className="text-green-700">
              {run.passed ?? '—'}
            </span>
          </div>
          <div>
            <span className="font-medium">Failed:</span>{' '}
            <span data-testid="run-failed" className="text-red-700">
              {run.failed ?? '—'}
            </span>
          </div>
          <div>
            <span className="font-medium">Skipped:</span>{' '}
            <span data-testid="run-skipped">{run.skipped ?? '—'}</span>
          </div>
          {run.target_version && (
            <div>
              <span className="font-medium">Version:</span>{' '}
              <span className="font-mono">{run.target_version}</span>
            </div>
          )}
          {run.triggered_by && (
            <div>
              <span className="font-medium">Triggered by:</span> {run.triggered_by}
            </div>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Case Results</h2>
        {run.case_results.length === 0 ? (
          <p data-testid="case-results-empty" className="text-gray-500 text-sm">
            No case results yet.
          </p>
        ) : (
          <div data-testid="case-results-list" className="space-y-2">
            {run.case_results.map((cr) => (
              <CaseResultRow key={cr.case_id} cr={cr} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
