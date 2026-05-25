/**
 * RunDetailPage — Run detail view with live SSE progress (M6-1).
 *
 * Strategy (pre-M6-1 was 3s polling that never stopped due to a stale
 * TERMINAL_STATUSES set checking case-result values not run lifecycle):
 *   1. Initial GET /runs/{id} for full RunDetail (started_at, version,
 *      etc — fields SSE snapshot doesn't carry).
 *   2. If status is non-terminal, open EventSource /runs/{id}/stream.
 *   3. Each `case_done` event refetches GET (simple + authoritative;
 *      avoids client-side state merge bugs).
 *   4. `run_done` / `run_aborted` event → final GET + close stream.
 *   5. EventSource error before terminal → fallback to 3s polling.
 *
 * Why refetch on every event instead of merging from event payload?
 * Run-level counters (passed/failed/skipped) come from DB on each
 * GET, so a single fetch keeps them in sync with case_results. Network
 * cost is bounded (≤1 fetch per case completion).
 */
import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';

type RunDetail = components['schemas']['RunDetail'];
type CaseResultOut = components['schemas']['CaseResultOut'];

const TERMINAL_RUN_STATUSES = new Set(['done', 'aborted']);

function isRunTerminal(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status.toLowerCase());
}

// --- M6-2 artifacts -------------------------------------------------------

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

interface ArtifactInfo {
  filename: string;
  size_bytes: number;
  kind: string;
  step_idx: number | null;
  step_id: string | null;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function CaseArtifacts({ runId, caseId }: { runId: number; caseId: string }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ArtifactInfo[] | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);

  async function loadOnce() {
    if (items !== null || loadingArtifacts) return;
    setLoadingArtifacts(true);
    setArtifactsError(null);
    try {
      const resp = await fetch(
        `${API_BASE}/runs/${runId}/cases/${encodeURIComponent(caseId)}/artifacts`,
      );
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as ArtifactInfo[];
      setItems(data);
    } catch (e) {
      setArtifactsError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingArtifacts(false);
    }
  }

  function handleToggle() {
    const next = !open;
    setOpen(next);
    if (next) void loadOnce();
  }

  return (
    <div className="ml-6 mt-1 mb-2">
      <button
        type="button"
        data-testid={`artifacts-toggle-${caseId}`}
        onClick={handleToggle}
        className="text-xs text-gray-600 hover:underline"
      >
        {open ? '▾' : '▸'} Artifacts
      </button>
      {open && (
        <div
          data-testid={`artifacts-panel-${caseId}`}
          className="mt-1 pl-4 border-l border-gray-200"
        >
          {loadingArtifacts && (
            <div data-testid={`artifacts-loading-${caseId}`} className="text-xs text-gray-500">
              Loading artifacts…
            </div>
          )}
          {artifactsError !== null && (
            <div
              data-testid={`artifacts-error-${caseId}`}
              className="text-xs text-red-600"
            >
              Failed to load: {artifactsError}
            </div>
          )}
          {items !== null && items.length === 0 && (
            <div
              data-testid={`artifacts-empty-${caseId}`}
              className="text-xs text-gray-500"
            >
              No artifact files (steps produced empty stdout/stderr).
            </div>
          )}
          {items !== null && items.length > 0 && (
            <ul data-testid={`artifacts-list-${caseId}`} className="space-y-0.5">
              {items.map((a) => (
                <li
                  key={a.filename}
                  data-testid={`artifact-item-${caseId}-${a.filename}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="font-mono">{a.filename}</span>
                  <span className="text-gray-500">{formatBytes(a.size_bytes)}</span>
                  {a.kind !== 'other' && (
                    <span className="px-1 py-px rounded bg-gray-100 text-gray-600 text-[10px]">
                      {a.kind}
                    </span>
                  )}
                  <a
                    href={`${API_BASE}/runs/${runId}/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(a.filename)}`}
                    download={a.filename}
                    data-testid={`artifact-download-${caseId}-${a.filename}`}
                    className="text-blue-700 hover:underline"
                  >
                    Download
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// --- M6-1 finishing touch: progress bar -----------------------------------
//
// design.md §13.12 / line 679 specified an SSE 进度条. PR #110 landed the SSE
// stream + per-case row updates but skipped the literal progress bar. Added
// 2026-05-26 after user dogfood feedback "RUNNING live 没看到进度条".

function RunProgressBar({ run }: { run: RunDetail }) {
  const isTerminal = TERMINAL_RUN_STATUSES.has(run.status.toLowerCase());
  const total = run.total ?? run.case_results.length;
  if (total <= 0) return null;

  const passed = run.passed ?? 0;
  const failed = run.failed ?? 0;
  const skipped = run.skipped ?? 0;
  // errored is fresh in openapi types (PR #157); guard for older shape.
  const errored = (run as RunDetail & { errored?: number | null }).errored ?? 0;
  const done = passed + failed + skipped + errored;
  const pending = Math.max(0, total - done);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  // ETA = avg-per-done × pending (only when running, ≥1 done, parseable started_at)
  let eta: string | null = null;
  if (!isTerminal && done > 0 && pending > 0 && run.started_at) {
    const elapsedMs = Date.now() - new Date(run.started_at).getTime();
    if (elapsedMs > 0) {
      const avgPerCase = elapsedMs / done;
      const etaMs = avgPerCase * pending;
      eta = etaMs < 60_000 ? `${Math.round(etaMs / 1000)}s` : `${(etaMs / 60_000).toFixed(1)}m`;
    }
  }

  return (
    <div data-testid="run-progress" className="space-y-1">
      <progress
        data-testid="run-progress-bar"
        value={done}
        max={total}
        className="w-full h-2"
      />
      <div className="text-xs text-gray-600 flex flex-wrap items-baseline gap-x-3">
        <span data-testid="run-progress-counts" className="font-mono">
          {done} / {total} cases ({pct}%)
        </span>
        <span className="text-gray-500">
          {passed} pass · {failed} fail · {skipped} skip · {errored} error · {pending} pending
        </span>
        {eta !== null && (
          <span data-testid="run-progress-eta" className="text-gray-500">
            ETA ~{eta}
          </span>
        )}
      </div>
    </div>
  );
}

function CaseResultRow({ runId, result }: { runId: number; result: CaseResultOut }) {
  return (
    <div data-testid={`run-case-row-${result.case_id}`} className="py-2 border-b last:border-0">
      <div className="flex items-center gap-4">
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
      {result.artifacts_path && (
        <CaseArtifacts runId={runId} caseId={result.case_id} />
      )}
    </div>
  );
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamMode, setStreamMode] = useState<'sse' | 'polling' | 'idle'>('idle');
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function closeStream() {
    if (esRef.current !== null) {
      esRef.current.close();
      esRef.current = null;
    }
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const runId = Number(id);

    async function fetchOnce(): Promise<RunDetail | null> {
      try {
        const data = (await apiFetch('/runs/{run_id}', 'get', {
          path: { run_id: runId },
        })) as RunDetail;
        if (cancelled) return null;
        setRun(data);
        setLoading(false);
        return data;
      } catch (err) {
        if (cancelled) return null;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
        closeStream();
        return null;
      }
    }

    function startPollingFallback() {
      if (pollRef.current !== null) return;
      setStreamMode('polling');
      pollRef.current = setInterval(() => {
        void (async () => {
          const data = await fetchOnce();
          if (data && isRunTerminal(data.status)) {
            closeStream();
            setStreamMode('idle');
          }
        })();
      }, 3000);
    }

    function startSSE() {
      setStreamMode('sse');
      // Absolute URL: vite dev server (port 5173) doesn't proxy /runs
      // → relative path 404s → EventSource onerror → fallback polling.
      // Same API_BASE used for M6-2 artifact downloads above.
      const es = new EventSource(`${API_BASE}/runs/${runId}/stream`);
      esRef.current = es;
      es.onmessage = (e) => {
        if (cancelled) return;
        let event: { type: string };
        try {
          event = JSON.parse(e.data);
        } catch {
          return;
        }
        if (event.type === 'error') {
          // Backend signaled logical error (unknown run, etc.)
          closeStream();
          setStreamMode('idle');
          return;
        }
        // For snapshot / case_done / run_done / run_aborted, refetch.
        void (async () => {
          const data = await fetchOnce();
          if (event.type === 'run_done' || event.type === 'run_aborted') {
            closeStream();
            setStreamMode('idle');
            // Final state already fetched above.
            void data;
          }
        })();
      };
      es.onerror = () => {
        // EventSource closed by browser (e.g., server terminated stream
        // after terminal event). If we haven't already cleaned up, the
        // stream died unexpectedly — fall back to polling so the user
        // still sees progress.
        if (es.readyState === EventSource.CLOSED && esRef.current === es) {
          esRef.current = null;
          // Only start polling fallback if the run is still non-terminal
          // (otherwise the prior terminal event already closed us cleanly).
          void (async () => {
            const data = await fetchOnce();
            if (data && !isRunTerminal(data.status) && !cancelled) {
              startPollingFallback();
            } else {
              setStreamMode('idle');
            }
          })();
        }
      };
    }

    // Initial load → decide whether to open SSE
    void (async () => {
      const data = await fetchOnce();
      if (data === null || cancelled) return;
      if (isRunTerminal(data.status)) {
        setStreamMode('idle');
        return;
      }
      // EventSource may not exist in the test environment (jsdom). Fall
      // back to polling if so.
      if (typeof EventSource === 'undefined') {
        startPollingFallback();
        return;
      }
      startSSE();
    })();

    return () => {
      cancelled = true;
      closeStream();
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
      {streamMode !== 'idle' && (
        <span
          data-testid="run-stream-mode"
          data-mode={streamMode}
          className="ml-2 text-xs text-gray-500"
        >
          {streamMode === 'sse' ? 'live' : 'polling'}
        </span>
      )}
      {run.target_version && (
        <div>
          <span className="text-sm text-gray-500">Version: </span>
          <span data-testid="run-target-version" className="font-mono text-sm">{run.target_version}</span>
        </div>
      )}
      <RunProgressBar run={run} />
      <div className="mt-4">
        {run.case_results.map((result) => (
          <CaseResultRow key={result.case_id} runId={run.id} result={result} />
        ))}
      </div>
    </div>
  );
}
