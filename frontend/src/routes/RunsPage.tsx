/**
 * M5-4 RunsPage — list of runs with global FilterBar (URL-persistent).
 *
 * Replaces the M2-8 placeholder. Lists /runs with filtering by
 * verdict + since (time range) + free-text q + **case_id** (post-M6
 * UX, 2026-05-25 — "which runs touched a specific case").
 *
 * Category chips are hidden via showCategoryFilter={false} — runs
 * don't carry a category directly, so chips would render interactively
 * but never affect results (user reported the rendered-but-no-op chips
 * after PR #108).
 *
 * The filter chip is labeled "Status:" in FilterBar (shared UI), but
 * the values are VERDICTS ('pass' / 'fail' / 'running' / 'aborted')
 * derived from backend lifecycle status + failed count — see
 * @/lib/runVerdict. URL key remains `status` for filter-state continuity
 * via useFilters() — semantics is "what the user wants to filter on".
 *
 * The case_id filter is server-side (`GET /runs?case_id=X`): the
 * backend JOINs case_results so we don't have to load the full case
 * graph client-side. UI = CaseIdCombobox (reused from Skip List).
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';
import { FilterBar } from '@/components/FilterBar';
import { CaseIdCombobox } from '@/components/CaseIdCombobox';
import { useFilters } from '@/lib/useFilters';
import { runVerdict, verdictToBadgeClass, VERDICT_OPTIONS } from '@/lib/runVerdict';

type RunSummary = components['schemas']['RunSummary'];

function formatRelative(dateStr: string): string {
  // Backend serializes datetime.utcnow() as a naive ISO string (no `Z`
  // / `+00:00` suffix). `new Date(<naive>)` interprets that as LOCAL
  // time on the browser — for users in UTC+8 the result is off by 8h
  // (dogfood 2026-05-26 user-visible bug "just-triggered run shows
  // 8h ago"). Treat tz-less strings as UTC by appending Z; preserves
  // correct parsing for any future tz-aware backend output.
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(dateStr);
  const ms = new Date(hasTz ? dateStr : dateStr + 'Z').getTime();
  const diffMs = Date.now() - ms;
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

  // Re-fetch when case_id filter changes (server-side filter via query
  // param; other filters are client-side over the fetched list).
  useEffect(() => {
    let cancelled = false;
    setRuns(null);
    setError(null);
    const query: Record<string, string | number> = {};
    if (filters.case_id) query.case_id = filters.case_id;
    apiFetch('/runs', 'get', Object.keys(query).length > 0 ? { query } : undefined)
      .then((data) => {
        if (!cancelled) setRuns(data as RunSummary[]);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [filters.case_id]);

  const cutoffMs = sinceToCutoffMs(filters.since);
  const filtered = (runs ?? []).filter((r) => {
    if (filters.status.length > 0 && !filters.status.includes(runVerdict(r))) {
      return false;
    }
    if (cutoffMs !== null && new Date(r.started_at).getTime() < cutoffMs) {
      return false;
    }
    if (filters.q) {
      // Search hay = id + version + triggered_by (post-2026-05-25,
      // user re-added id per UX feedback — "搜索框太单调"). Verdict
      // still excluded: chip filter is more precise.
      const q = filters.q.toLowerCase();
      const hay = `${r.id} ${r.target_version ?? ''} ${r.triggered_by ?? ''}`.toLowerCase();
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
        showCategoryFilter={false}
        qPlaceholder="搜索 id / version / triggered_by — e.g. 42, 4.5.0, admin"
      />

      <div
        data-testid="runs-page-case-filter"
        className="runs-page-case-filter flex items-center gap-2"
      >
        <span className="text-sm text-gray-600 shrink-0">Includes case:</span>
        <div className="flex-1 max-w-[640px]">
          <CaseIdCombobox
            value={filters.case_id}
            onChange={(v) => setFilter('case_id', v)}
            placeholder="所有 run (点击选 case 过滤)"
            testid="runs-page-case-picker"
          />
        </div>
        {filters.case_id && (
          <button
            type="button"
            data-testid="runs-page-case-clear"
            onClick={() => setFilter('case_id', '')}
            className="text-xs text-blue-700 hover:underline"
          >
            Clear
          </button>
        )}
      </div>

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
                {r.passed ?? 0} pass / {r.failed ?? 0} fail / {r.skipped ?? 0} skip / {((r as { errored?: number | null }).errored) ?? 0} error / {r.total ?? 0} total
              </span>
              <span
                data-testid={`runs-page-triggered-by-${r.id}`}
                className="text-xs text-gray-500"
                title="Triggered by"
              >
                👤 {r.triggered_by ?? '—'}
              </span>
              <span
                data-testid={`runs-page-version-${r.id}`}
                className="text-xs text-gray-500"
                title="Target version"
              >
                🏷️ {r.target_version ?? '—'}
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
