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
  (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL ??
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

const VIEW_SIZE_LIMIT = 512 * 1024; // 512 KB

interface ArtifactViewState {
  // filename → fetched text content
  contentCache: Map<string, string>;
  // filenames currently being fetched
  loadingSet: Set<string>;
  // filename → error message
  errorCache: Map<string, string>;
  // filenames whose inline view is expanded
  expandedSet: Set<string>;
}

function CaseArtifacts({ runId, caseId }: { runId: number; caseId: string }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ArtifactInfo[] | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<ArtifactViewState>(() => ({
    contentCache: new Map(),
    loadingSet: new Set(),
    errorCache: new Map(),
    expandedSet: new Set(),
  }));

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

  function handleViewToggle(artifact: ArtifactInfo) {
    const { filename, size_bytes } = artifact;

    // Large file guard: never fetch, just toggle expanded to show the guard message
    if (size_bytes > VIEW_SIZE_LIMIT) {
      setViewState((prev) => {
        const expandedSet = new Set(prev.expandedSet);
        if (expandedSet.has(filename)) {
          expandedSet.delete(filename);
        } else {
          expandedSet.add(filename);
        }
        return { ...prev, expandedSet };
      });
      return;
    }

    // Toggle collapse
    if (viewState.expandedSet.has(filename)) {
      setViewState((prev) => {
        const expandedSet = new Set(prev.expandedSet);
        expandedSet.delete(filename);
        return { ...prev, expandedSet };
      });
      return;
    }

    // Expand: if already cached or loading, just expand
    if (viewState.contentCache.has(filename) || viewState.loadingSet.has(filename)) {
      setViewState((prev) => {
        const expandedSet = new Set(prev.expandedSet);
        expandedSet.add(filename);
        return { ...prev, expandedSet };
      });
      return;
    }

    // First expand: mark loading + expanded, then fetch
    setViewState((prev) => {
      const loadingSet = new Set(prev.loadingSet);
      loadingSet.add(filename);
      const expandedSet = new Set(prev.expandedSet);
      expandedSet.add(filename);
      return { ...prev, loadingSet, expandedSet };
    });

    const url = `${API_BASE}/runs/${runId}/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(filename)}`;
    void fetch(url)
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.text();
      })
      .then((text) => {
        setViewState((prev) => {
          const contentCache = new Map(prev.contentCache);
          contentCache.set(filename, text);
          const loadingSet = new Set(prev.loadingSet);
          loadingSet.delete(filename);
          return { ...prev, contentCache, loadingSet };
        });
      })
      .catch((e: unknown) => {
        setViewState((prev) => {
          const errorCache = new Map(prev.errorCache);
          errorCache.set(filename, e instanceof Error ? e.message : String(e));
          const loadingSet = new Set(prev.loadingSet);
          loadingSet.delete(filename);
          return { ...prev, errorCache, loadingSet };
        });
      });
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
            <div data-testid={`artifacts-error-${caseId}`} className="text-xs text-red-600">
              Failed to load: {artifactsError}
            </div>
          )}
          {items !== null && items.length === 0 && (
            <div data-testid={`artifacts-empty-${caseId}`} className="text-xs text-gray-500">
              No artifact files (steps produced empty stdout/stderr).
            </div>
          )}
          {items !== null && items.length > 0 && (
            <ul data-testid={`artifacts-list-${caseId}`} className="space-y-1">
              {items.map((a) => {
                const downloadUrl = `${API_BASE}/runs/${runId}/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(a.filename)}`;
                const isExpanded = viewState.expandedSet.has(a.filename);
                const isLoading = viewState.loadingSet.has(a.filename);
                const content = viewState.contentCache.get(a.filename);
                const contentError = viewState.errorCache.get(a.filename);
                const isTooLarge = a.size_bytes > VIEW_SIZE_LIMIT;

                return (
                  <li
                    key={a.filename}
                    data-testid={`artifact-item-${caseId}-${a.filename}`}
                    className="text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono">{a.filename}</span>
                      <span className="text-gray-500">{formatBytes(a.size_bytes)}</span>
                      {a.kind !== 'other' && (
                        <span className="px-1 py-px rounded bg-gray-100 text-gray-600 text-[10px]">
                          {a.kind}
                        </span>
                      )}
                      <a
                        href={downloadUrl}
                        download={a.filename}
                        data-testid={`artifact-download-${caseId}-${a.filename}`}
                        className="text-blue-700 hover:underline"
                      >
                        Download
                      </a>
                      <button
                        type="button"
                        data-testid={`artifact-view-${caseId}-${a.filename}`}
                        onClick={() => handleViewToggle(a)}
                        className="text-blue-700 hover:underline"
                      >
                        {isExpanded ? 'Hide' : 'View'}
                      </button>
                    </div>
                    {isExpanded && isTooLarge && (
                      <div
                        data-testid={`artifact-too-large-${caseId}-${a.filename}`}
                        className="mt-1 text-gray-500"
                      >
                        Large file ({formatBytes(a.size_bytes)}) — Download instead
                      </div>
                    )}
                    {isExpanded && !isTooLarge && isLoading && (
                      <div
                        data-testid={`artifact-view-loading-${caseId}-${a.filename}`}
                        className="mt-1 text-gray-500"
                      >
                        Loading…
                      </div>
                    )}
                    {isExpanded && !isTooLarge && contentError !== undefined && (
                      <div
                        data-testid={`artifact-view-error-${caseId}-${a.filename}`}
                        className="mt-1 text-red-600"
                      >
                        Failed to load: {contentError}
                      </div>
                    )}
                    {isExpanded && !isTooLarge && content !== undefined && (
                      <pre
                        data-testid={`artifact-content-${caseId}-${a.filename}`}
                        className="mt-1 font-mono text-xs whitespace-pre max-h-96 overflow-auto bg-gray-50 p-2 rounded border border-gray-200"
                      >
                        {content}
                      </pre>
                    )}
                  </li>
                );
              })}
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
  // `run.total` is now written at create_run() time (post-2026-05-26 fix); for
  // older / migrated rows where it's still None, fall back to case_results
  // length so we degrade to "N / N" instead of "N / null".
  const total = run.total ?? run.case_results.length;
  if (total <= 0) return null;

  // Derive done + per-bucket counts from case_results, not from the run row's
  // top-level passed/failed/skipped/errored — those are only written by
  // finish_run() at terminal time. During a running run, the run row's
  // counters stay at NULL/0 while case_results grows row-by-row as each case
  // completes; deriving from case_results gives the live "done/total" UX.
  let passed = 0;
  let failed = 0;
  let skipped = 0;
  let errored = 0;
  for (const cr of run.case_results) {
    const s = (cr.status ?? '').toLowerCase();
    if (s === 'pass') passed++;
    else if (s === 'fail') failed++;
    else if (s === 'skip') skipped++;
    else if (s === 'error') errored++;
  }
  const done = passed + failed + skipped + errored;
  const pending = Math.max(0, total - done);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  // ETA = avg-per-done × pending (only when running, ≥1 done, parseable started_at)
  let eta: string | null = null;
  if (!isTerminal && done > 0 && pending > 0 && run.started_at) {
    // Same naive-ISO-as-UTC parse as formatRelative — backend's
    // datetime.utcnow() ships without tz suffix; default JS parsing
    // treats it as local time and yields ~8h skew on UTC+8 clients.
    const ts = run.started_at;
    const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(ts);
    const elapsedMs = Date.now() - new Date(hasTz ? ts : ts + 'Z').getTime();
    if (elapsedMs > 0) {
      const avgPerCase = elapsedMs / done;
      const etaMs = avgPerCase * pending;
      eta = etaMs < 60_000 ? `${Math.round(etaMs / 1000)}s` : `${(etaMs / 60_000).toFixed(1)}m`;
    }
  }

  return (
    <div data-testid="run-progress" className="space-y-1">
      <progress data-testid="run-progress-bar" value={done} max={total} className="w-full h-2" />
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
      {result.artifacts_path && <CaseArtifacts runId={runId} caseId={result.case_id} />}
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
          <span data-testid="run-target-version" className="font-mono text-sm">
            {run.target_version}
          </span>
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
