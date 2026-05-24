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

function CaseResultRow({ result }: { result: CaseResultOut }) {
  return (
    <div data-testid={`run-case-row-${result.case_id}`} className="flex items-center gap-4 py-2 border-b last:border-0">
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
      const es = new EventSource(`/runs/${runId}/stream`);
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
      <div className="mt-4">
        {run.case_results.map((result) => (
          <CaseResultRow key={result.case_id} result={result} />
        ))}
      </div>
    </div>
  );
}
