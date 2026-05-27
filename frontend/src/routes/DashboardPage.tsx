/**
 * M5-2 Dashboard `/` landing page.
 *
 * Replaces "/" → "/cases" redirect with a real overview page covering:
 *   1. KPI: cases-by-category counts (one tile per active category, data
 *      driven from GET /admin/categories — §14 R4b no hardcoded names)
 *   2. KPI: BUG status pie (proportions of open/fixed/wontfix/stub)
 *   3. KPI: Extension stability (proportions of stable/experimental/etc)
 *   4. KPI: Recent runs (count + pass/fail tally of last 10 runs)
 *   5. Recent activity list (last 10 runs, click → /runs/:id)
 *   6. Quick actions row (preset "Run all <category> <status>" buttons →
 *      /runs/new?category=X&status=Y; M5-5 will read these query params)
 *
 * Deliberately minimal (same path as M5-1):
 *   - No chart library (counts shown as numbers + percent bar)
 *   - Vitest unit tests only, no playwright
 *   - All aggregation is client-side over the existing endpoints
 *   - apiFetch via the shared client (R27: no inline URLs)
 */
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { runVerdict, verdictToBadgeClass } from '@/lib/runVerdict';
import { Button } from '@/components/ui/button';

type CategoryOut = components['schemas']['CategoryOut'];
type CaseSummary = components['schemas']['CaseSummary'];
type RunSummary = components['schemas']['RunSummary'];

interface DashboardData {
  categories: CategoryOut[];
  casesByCategory: Record<string, CaseSummary[]>;
  recentRuns: RunSummary[];
}

function formatRelative(dateStr: string): string {
  // Backend serializes datetime.utcnow() as a naive ISO string (no `Z`
  // / `+00:00` suffix). `new Date(<naive>)` interprets that as LOCAL
  // time on the browser — for users in UTC+8 the result is off by 8h.
  // Treat tz-less strings as UTC by appending Z; preserves correct
  // parsing for any future tz-aware backend output.
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

function statusToBadgeClass(status: string): string {
  // Simple semantic mapping (not tied to specific category names; covers
  // common keywords across all 3 categories per design.md §16)
  if (status === 'pass' || status === 'fixed' || status === 'stable') {
    return 'badge-success';
  }
  if (status === 'fail' || status === 'open') {
    return 'badge-danger';
  }
  if (status === 'running') return 'badge-warning';
  return 'badge-muted';
}

// ---- KPI tiles --------------------------------------------------------------

interface CategoryCountTileProps {
  category: CategoryOut;
  cases: CaseSummary[];
}

function CategoryCountTile({ category, cases }: CategoryCountTileProps) {
  return (
    <div
      data-testid={`dashboard-kpi-category-${category.name}`}
      className="kpi-tile"
    >
      <div className="kpi-tile-label">{category.display_name}</div>
      <div className="kpi-tile-value">{cases.length}</div>
      <Link to={`/cases?category=${category.name}`} className="kpi-tile-link">
        View →
      </Link>
    </div>
  );
}

interface StatusBreakdownTileProps {
  testid: string;
  title: string;
  cases: CaseSummary[];
  statusWhitelist: string[];
}

function StatusBreakdownTile({
  testid,
  title,
  cases,
  statusWhitelist,
}: StatusBreakdownTileProps) {
  const counts: Record<string, number> = {};
  for (const s of statusWhitelist) counts[s] = 0;
  for (const c of cases) {
    if (c.status in counts) counts[c.status] += 1;
  }
  const total = cases.length || 1;
  return (
    <div data-testid={testid} className="kpi-tile kpi-tile-wide">
      <div className="kpi-tile-label">{title}</div>
      <div className="kpi-tile-rows">
        {statusWhitelist.map((status) => {
          const n = counts[status];
          const pct = Math.round((n / total) * 100);
          return (
            <div
              key={status}
              data-testid={`${testid}-row-${status}`}
              className="kpi-row"
            >
              <span className={`badge ${statusToBadgeClass(status)}`}>
                {status}
              </span>
              <span className="kpi-row-count">{n}</span>
              <span className="kpi-row-bar">
                <span
                  className="kpi-row-bar-fill"
                  style={{ width: `${pct}%` }}
                />
              </span>
              <span className="kpi-row-pct">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface RecentRunsTileProps {
  runs: RunSummary[];
}

function RecentRunsTile({ runs }: RecentRunsTileProps) {
  // Count by derived verdict, not raw lifecycle status (backend writes
  // 'done', not 'pass'/'fail'). See runVerdict() doc.
  const verdicts = runs.map(runVerdict);
  const pass = verdicts.filter((v) => v === 'pass').length;
  const fail = verdicts.filter((v) => v === 'fail').length;
  const error = verdicts.filter((v) => v === 'error').length;
  const running = verdicts.filter((v) => v === 'running').length;
  const aborted = verdicts.filter((v) => v === 'aborted').length;
  return (
    <div data-testid="dashboard-kpi-recent-runs" className="kpi-tile">
      <div className="kpi-tile-label">Recent runs (last {runs.length})</div>
      <div className="kpi-tile-value">{runs.length}</div>
      <div className="kpi-tile-sub">
        <span className="badge badge-success">{pass} pass</span>{' '}
        <span className="badge badge-danger">{fail} fail</span>{' '}
        <span className="badge badge-warning">{running} running</span>
        {error > 0 && (
          <>
            {' '}
            <span className="badge badge-danger">{error} error</span>
          </>
        )}
        {aborted > 0 && (
          <>
            {' '}
            <span className="badge badge-danger">{aborted} aborted</span>
          </>
        )}
      </div>
      <Link to="/runs" className="kpi-tile-link">
        View →
      </Link>
    </div>
  );
}

// ---- Recent activity list ---------------------------------------------------

interface RecentActivityProps {
  runs: RunSummary[];
}

function RecentActivity({ runs }: RecentActivityProps) {
  if (runs.length === 0) {
    return (
      <div
        data-testid="dashboard-recent-activity-empty"
        className="dashboard-recent-empty"
      >
        No runs yet. Start one from{' '}
        <Link to="/runs/new">/runs/new</Link>.
      </div>
    );
  }
  // M6-3: when ≥2 runs exist, show "Compare with previous run" deep link
  // to /runs/diff?a=<older>&b=<latest>. runs[] is newest-first from API.
  const compareCta =
    runs.length >= 2 ? (
      <Link
        to={`/runs/diff?a=${runs[1].id}&b=${runs[0].id}`}
        data-testid="dashboard-compare-previous"
        className="dashboard-section-link"
      >
        Compare last 2 runs →
      </Link>
    ) : null;

  return (
    <div data-testid="dashboard-recent-activity" className="dashboard-section">
      <div className="dashboard-section-title flex items-baseline justify-between">
        <span>Recent activity</span>
        {compareCta}
      </div>
      <ul className="dashboard-activity-list">
        {runs.slice(0, 10).map((r) => (
          <li
            key={r.id}
            data-testid={`dashboard-recent-run-${r.id}`}
            className="dashboard-activity-item"
          >
            <Link to={`/runs/${r.id}`}>
              <span className={`badge ${verdictToBadgeClass(runVerdict(r))}`}>
                {runVerdict(r)}
              </span>
              <span className="run-id">Run #{r.id}</span>
              <span className="run-summary">
                {r.passed ?? 0} pass / {r.failed ?? 0} fail /{' '}
                {r.skipped ?? 0} skip / {r.errored ?? 0} error /{' '}
                {r.total ?? 0} total
              </span>
              <span className="run-time">{formatRelative(r.started_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- Quick actions ---------------------------------------------------------

interface QuickActionsProps {
  categories: CategoryOut[];
}

function QuickActions({ categories }: QuickActionsProps) {
  const navigate = useNavigate();
  const presets = categories
    .map((cat) => ({
      cat,
      // Use the category's default_status as the "interesting" preset target
      // (open BUGs, stable extensions, open external_systems — v1.21 aligned).
      status: cat.default_status,
    }))
    // Hide categories without a sensible default (defensive)
    .filter((p) => p.status);

  return (
    <div data-testid="dashboard-quick-actions" className="dashboard-section">
      <div className="dashboard-section-title">Quick start</div>
      <div className="dashboard-quick-actions-row">
        {presets.map(({ cat, status }) => (
          <button
            key={cat.name}
            data-testid={`dashboard-quick-action-${cat.name}-${status}`}
            className="dashboard-quick-action"
            onClick={() =>
              navigate(`/runs/new?category=${cat.name}&status=${status}`)
            }
          >
            Run all {cat.display_name} (status: {status})
          </button>
        ))}
      </div>
    </div>
  );
}

// ---- Page ------------------------------------------------------------------

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const cats = (await apiFetch(
          '/admin/categories',
          'get',
        )) as CategoryOut[];
        if (cancelled) return;
        const catsSorted = cats
          .slice()
          .sort((a, b) => a.display_order - b.display_order);

        // Fetch cases per category in parallel.
        const casesByCategory: Record<string, CaseSummary[]> = {};
        await Promise.all(
          catsSorted.map(async (cat) => {
            const cases = (await apiFetch('/cases', 'get', {
              query: { category: cat.name },
            })) as CaseSummary[];
            casesByCategory[cat.name] = cases;
          }),
        );
        if (cancelled) return;

        const runs = (await apiFetch('/runs', 'get')) as RunSummary[];
        if (cancelled) return;

        setData({
          categories: catsSorted,
          casesByCategory,
          recentRuns: runs,
        });
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div data-testid="page-dashboard-error" className="dashboard-error">
        Failed to load dashboard: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div data-testid="page-dashboard-loading" className="dashboard-loading">
        Loading dashboard…
      </div>
    );
  }

  return (
    <div data-testid="page-dashboard" className="dashboard">
      <div className="dashboard-header">
        <h1 className="dashboard-title">Dashboard</h1>
        <Button asChild data-testid="dashboard-new-run">
          <Link to="/runs/new">
            <span aria-hidden="true">▶</span>{' '}New Run
          </Link>
        </Button>
      </div>

      <QuickActions categories={data.categories} />

      {/* KPI tiles row 1: per-category counts + recent runs */}
      <div
        data-testid="dashboard-kpi-row"
        className="dashboard-kpi-row"
      >
        {data.categories.map((cat) => (
          <CategoryCountTile
            key={cat.name}
            category={cat}
            cases={data.casesByCategory[cat.name] ?? []}
          />
        ))}
        <RecentRunsTile runs={data.recentRuns} />
      </div>

      {/* KPI tiles row 2: status breakdown for EVERY active category.
         Pre-fix (2026-05-25) only hardcoded bug + extension via
         id_prefix matching — violated §14 R4b and dropped external_systems
         entirely. Now data-driven across all categories. */}
      <div data-testid="dashboard-kpi-row-status" className="dashboard-kpi-row">
        {data.categories.map((cat) => (
          <StatusBreakdownTile
            key={cat.name}
            testid={`dashboard-kpi-status-${cat.name}`}
            title={`${cat.display_name} — status breakdown`}
            cases={data.casesByCategory[cat.name] ?? []}
            statusWhitelist={cat.status_whitelist}
          />
        ))}
      </div>

      <RecentActivity runs={data.recentRuns} />
    </div>
  );
}
