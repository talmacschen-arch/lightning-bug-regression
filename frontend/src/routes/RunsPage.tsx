/**
 * M5-4 RunsPage — list of runs with global FilterBar (URL-persistent).
 *
 * Replaces the M2-8 placeholder. Lists /runs with simple filtering by
 * verdict + since (time range). Click a row → /runs/:id.
 *
 * Category / tag / q filters live in the FilterBar UI but DON'T apply
 * to runs in this minimal version — runs don't carry tags or categories
 * directly. Verdict + since are the practical filters here.
 *
 * The filter chip is labeled "Status:" in FilterBar (shared UI), but
 * the values are VERDICTS ('pass' / 'fail' / 'running' / 'aborted')
 * derived from backend lifecycle status + failed count — see
 * @/lib/runVerdict. URL key remains `status` for filter-state continuity
 * via useFilters() — semantics is "what the user wants to filter on".
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';
import { FilterBar } from '@/components/FilterBar';
import { useFilters } from '@/lib/useFilters';
import { runVerdict, verdictToBadgeClass, VERDICT_OPTIONS } from '@/lib/runVerdict';

type RunSummary = components['schemas']['RunSummary'];

function formatRelative(dateStr: string): string {
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const diffM = Math.floor(diffMs / 60_000);
  if (diffM < 1) return 'just now';
  if (diffM < 60) return `${diffM}m ago`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}

function sinceToCutoffMs(since: string): number | null {
  if (since === '7d') return Date.now() - 7 * 86_400_000;
  if (since === '30d') return Date.now() - 30 * 86_400_000;
  if (since === '90d') return Date.now() - 90 * 86_400_000;
  return null; // 'all'
}

export default function RunsPage() {
  const { filters, setFilter, clear } = useFilters();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/runs', 'get')
      .then((data) => {
        if (!cancelled) setRuns(data as RunSummary[]);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cutoffMs = sinceToCutoffMs(filters.since);
  const filtered = (runs ?? []).filter((r) => {
    if (filters.status.length > 0 && !filters.status.includes(runVerdict(r))) {
      return false;
    }
    if (cutoffMs !== null && new Date(r.started_at).getTime() < cutoffMs) {
      return false;
    }
    if (filters.q) {
      const q = filters.q.toLowerCase();
      const hay = `${r.id} ${runVerdict(r)} ${r.target_version ?? ''} ${r.triggered_by ?? ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return (
    <div data-testid="page-runs" className="runs-page">
      <h1 className="runs-page-title">Runs</h1>

      <FilterBar
        filters={filters}
        setFilter={setFilter}
        clear={clear}
        statusOptions={VERDICT_OPTIONS}
        showSinceFilter
        qPlaceholder="搜索 id / verdict / version / triggered_by — e.g. 42, fail, 4.5.0, gpadmin"
      />

      {error && (
        <div data-testid="runs-page-error" className="runs-page-empty">
          Failed to load: {error}
        </div>
      )}

      {!error && runs === null && (
        <div data-testid="runs-page-loading" className="runs-page-empty">
          Loading runs…
        </div>
      )}

      {!error && runs !== null && filtered.length === 0 && (
        <div data-testid="runs-page-empty" className="runs-page-empty">
          {runs.length === 0
            ? 'No runs yet. Trigger one from /runs/new.'
            : 'No runs match current filters.'}
        </div>
      )}

      {!error && runs !== null && filtered.length > 0 && (
        <div data-testid="runs-page-list" className="runs-page-list">
          {filtered.map((r) => (
            <Link
              key={r.id}
              to={`/runs/${r.id}`}
              data-testid={`runs-page-row-${r.id}`}
              className="runs-page-row"
            >
              <span className="font-mono text-sm">#{r.id}</span>
              <span
                data-testid={`runs-page-status-${r.id}`}
                className={`badge ${verdictToBadgeClass(runVerdict(r))}`}
              >
                {runVerdict(r).toUpperCase()}
              </span>
              <span className="text-xs text-gray-500">
                {r.passed ?? 0} pass / {r.failed ?? 0} fail / {r.total ?? 0} total
              </span>
              <span className="text-xs text-gray-500 text-right">
                {formatRelative(r.started_at)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
