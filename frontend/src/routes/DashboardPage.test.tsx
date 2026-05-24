/**
 * M5-2 DashboardPage unit tests (vitest + jsdom).
 *
 * Covers data-driven KPI rendering, recent activity, quick actions, and
 * §14 R4b (no hardcoded category names in component logic).
 */
import { render, screen, waitFor, act, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import DashboardPage from './DashboardPage';

// ---- mock apiFetch ---------------------------------------------------------

const apiFetchMock = vi.fn();
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

// ---- fixtures --------------------------------------------------------------

const FAKE_CATEGORIES = [
  {
    name: 'bug_regression',
    display_name: 'BUG 回归',
    description: null,
    id_prefix: 'lg-bug-',
    dir_path: 'bug-regression',
    status_whitelist: ['open', 'fixed', 'wontfix', 'stub'],
    default_status: 'open',
    display_order: 10,
  },
  {
    name: 'extension',
    display_name: 'Extension 集成测试',
    description: null,
    id_prefix: 'lg-ext-',
    dir_path: 'extension',
    status_whitelist: ['stable', 'experimental', 'deprecated', 'stub'],
    default_status: 'stable',
    display_order: 20,
  },
  {
    name: 'external_systems',
    display_name: '外部系统集成测试',
    description: null,
    id_prefix: 'lg-xs-',
    dir_path: 'external-systems',
    status_whitelist: ['stable', 'awaiting_env', 'deprecated', 'stub'],
    default_status: 'awaiting_env',
    display_order: 30,
  },
];

const FAKE_BUG_CASES = [
  { id: 'lg-bug-0001', category: 'bug_regression', title: 'A', status: 'fixed', destructive: false, tags: null, error: null },
  { id: 'lg-bug-0002', category: 'bug_regression', title: 'B', status: 'fixed', destructive: false, tags: null, error: null },
  { id: 'lg-bug-0009', category: 'bug_regression', title: 'C', status: 'open', destructive: false, tags: null, error: null },
];

const FAKE_EXT_CASES = [
  { id: 'lg-ext-pgvector', category: 'extension', title: 'pgvector', status: 'stable', destructive: false, tags: null, error: null },
  { id: 'lg-ext-postgis', category: 'extension', title: 'postgis', status: 'stable', destructive: false, tags: null, error: null },
];

// Fixture mirrors REAL backend behavior: run.status is 'done' lifecycle
// phase (not verdict 'pass'/'fail'). Verdict is derived from `failed`
// count via runVerdict():
//   id=42: done + failed=0 + passed=9  → verdict=pass
//   id=41: done + failed=5             → verdict=fail
//   id=40: done + failed=0 + passed=10 → verdict=pass
// → 2 pass / 1 fail (counts match REAL backend after bug fix).
const FAKE_RUNS = [
  { id: 42, status: 'done', started_at: new Date(Date.now() - 4 * 3_600_000).toISOString(), finished_at: null, total: 10, passed: 9, failed: 0, skipped: 0, target_version: null, triggered_by: null },
  { id: 41, status: 'done', started_at: new Date(Date.now() - 24 * 3_600_000).toISOString(), finished_at: null, total: 10, passed: 5, failed: 5, skipped: 0, target_version: null, triggered_by: null },
  { id: 40, status: 'done', started_at: new Date(Date.now() - 48 * 3_600_000).toISOString(), finished_at: null, total: 10, passed: 10, failed: 0, skipped: 0, target_version: null, triggered_by: null },
];

function setupMocks(opts?: {
  categories?: typeof FAKE_CATEGORIES;
  cases?: Record<string, typeof FAKE_BUG_CASES>;
  runs?: typeof FAKE_RUNS;
}) {
  const cats = opts?.categories ?? FAKE_CATEGORIES;
  const casesByCategory = opts?.cases ?? {
    bug_regression: FAKE_BUG_CASES,
    extension: FAKE_EXT_CASES,
    external_systems: [],
  };
  const runs = opts?.runs ?? FAKE_RUNS;

  apiFetchMock.mockImplementation(async (path: string, method: string, init?: { query?: { category?: string } }) => {
    if (path === '/admin/categories' && method === 'get') return cats;
    if (path === '/cases' && method === 'get') {
      const cat = init?.query?.category;
      return casesByCategory[cat ?? ''] ?? [];
    }
    if (path === '/runs' && method === 'get') return runs;
    throw new Error(`unmocked: ${method} ${path}`);
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

// ---- tests -----------------------------------------------------------------

describe('DashboardPage (M5-2)', () => {
  describe('loading + error states', () => {
    it('shows loading state initially', () => {
      setupMocks();
      renderPage();
      expect(screen.getByTestId('page-dashboard-loading')).toBeInTheDocument();
    });

    it('shows error state when /admin/categories fails', async () => {
      apiFetchMock.mockRejectedValueOnce(new Error('boom'));
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard-error')).toBeInTheDocument();
      });
    });
  });

  describe('KPI tiles — data-driven from /admin/categories (§14 R4b)', () => {
    it('renders one tile per active category with case count', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      });
      // One tile per category, NOT hardcoded
      expect(screen.getByTestId('dashboard-kpi-category-bug_regression')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-category-extension')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-category-external_systems')).toBeInTheDocument();
      // Counts reflect mock data
      expect(within(screen.getByTestId('dashboard-kpi-category-bug_regression')).getByText('3')).toBeInTheDocument();
      expect(within(screen.getByTestId('dashboard-kpi-category-extension')).getByText('2')).toBeInTheDocument();
      expect(within(screen.getByTestId('dashboard-kpi-category-external_systems')).getByText('0')).toBeInTheDocument();
    });

    it('renders new categories automatically (5 categories scenario)', async () => {
      const extraCats = [
        ...FAKE_CATEGORIES,
        {
          name: 'perf_smoke',
          display_name: 'Performance Smoke',
          description: null,
          id_prefix: 'lg-perf-',
          dir_path: 'perf',
          status_whitelist: ['baseline', 'regression'],
          default_status: 'baseline',
          display_order: 40,
        },
        {
          name: 'upgrade_compat',
          display_name: 'Upgrade Compat',
          description: null,
          id_prefix: 'lg-upg-',
          dir_path: 'upgrade',
          status_whitelist: ['compatible', 'broken'],
          default_status: 'compatible',
          display_order: 50,
        },
      ];
      setupMocks({
        categories: extraCats,
        cases: {
          bug_regression: [],
          extension: [],
          external_systems: [],
          perf_smoke: [],
          upgrade_compat: [],
        },
        runs: [],
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      });
      // Should render tiles for all 5 categories automatically
      expect(screen.getByTestId('dashboard-kpi-category-perf_smoke')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-category-upgrade_compat')).toBeInTheDocument();
    });
  });

  describe('Status breakdown tiles (BUG + Extension)', () => {
    it('renders BUG status breakdown with whitelist rows', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-bug-status')).toBeInTheDocument();
      });
      // 4 status rows for bug_regression
      expect(screen.getByTestId('dashboard-kpi-bug-status-row-open')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-bug-status-row-fixed')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-bug-status-row-wontfix')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-bug-status-row-stub')).toBeInTheDocument();
    });

    it('renders extension status breakdown', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-extension-stability')).toBeInTheDocument();
      });
      expect(screen.getByTestId('dashboard-kpi-extension-stability-row-stable')).toBeInTheDocument();
    });
  });

  describe('Recent runs', () => {
    it('shows recent runs tile with pass/fail tally', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-recent-runs')).toBeInTheDocument();
      });
      const tile = screen.getByTestId('dashboard-kpi-recent-runs');
      // 2 pass, 1 fail, 0 running via verdict-derived counting (NOT raw
      // status — backend writes 'done' not 'pass'/'fail'. Bug pre-fix
      // would show 0/0/0 for any data with status='done').
      expect(within(tile).getByText('2 pass')).toBeInTheDocument();
      expect(within(tile).getByText('1 fail')).toBeInTheDocument();
    });

    it('counts verdict (not raw status) — handles real backend status="done"', async () => {
      // Real-world fixture: 3 done runs, mix of pass/fail by failed count;
      // 1 running run; 1 aborted run.
      setupMocks({
        runs: [
          { id: 100, status: 'done',    started_at: new Date().toISOString(), finished_at: null, total: 5, passed: 5, failed: 0, skipped: 0, target_version: null, triggered_by: null },
          { id: 101, status: 'done',    started_at: new Date().toISOString(), finished_at: null, total: 5, passed: 3, failed: 2, skipped: 0, target_version: null, triggered_by: null },
          { id: 102, status: 'done',    started_at: new Date().toISOString(), finished_at: null, total: 5, passed: 5, failed: 0, skipped: 0, target_version: null, triggered_by: null },
          { id: 103, status: 'running', started_at: new Date().toISOString(), finished_at: null, total: 0, passed: 0, failed: 0, skipped: 0, target_version: null, triggered_by: null },
          { id: 104, status: 'aborted', started_at: new Date().toISOString(), finished_at: null, total: 0, passed: 0, failed: 0, skipped: 0, target_version: null, triggered_by: null },
        ],
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-recent-runs')).toBeInTheDocument();
      });
      const tile = screen.getByTestId('dashboard-kpi-recent-runs');
      // verdict: id=100 pass, 101 fail, 102 pass, 103 running, 104 aborted
      expect(within(tile).getByText('2 pass')).toBeInTheDocument();
      expect(within(tile).getByText('1 fail')).toBeInTheDocument();
      expect(within(tile).getByText('1 running')).toBeInTheDocument();
      expect(within(tile).getByText('1 aborted')).toBeInTheDocument();
    });

    it('shows recent activity list with up to 10 runs', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-recent-activity')).toBeInTheDocument();
      });
      expect(screen.getByTestId('dashboard-recent-run-42')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-recent-run-41')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-recent-run-40')).toBeInTheDocument();
    });

    it('shows empty state when no runs', async () => {
      setupMocks({ runs: [] });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-recent-activity-empty')).toBeInTheDocument();
      });
    });
  });

  describe('Quick actions — data-driven from categories', () => {
    it('renders one preset per category using default_status', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-quick-actions')).toBeInTheDocument();
      });
      // Each category gets a quick-action button keyed by default_status
      expect(screen.getByTestId('dashboard-quick-action-bug_regression-open')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-quick-action-extension-stable')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-quick-action-external_systems-awaiting_env')).toBeInTheDocument();
      // "+ New case" was removed in favor of the Cases page header CTA
      // (PR #111). Dashboard quick-actions should NOT have it.
      expect(screen.queryByTestId('dashboard-quick-action-new-case')).toBeNull();
    });
  });

  describe('§14 R4b — no hardcoded category in component logic', () => {
    it('extra category is rendered without any code change', async () => {
      // If component had `if (cat.name === "bug_regression")` style code,
      // a new category like `perf_smoke` wouldn't get a quick-action button.
      const cats = [
        ...FAKE_CATEGORIES,
        {
          name: 'perf_smoke',
          display_name: 'Performance Smoke',
          description: null,
          id_prefix: 'lg-perf-',
          dir_path: 'perf',
          status_whitelist: ['baseline', 'regression'],
          default_status: 'baseline',
          display_order: 40,
        },
      ];
      setupMocks({
        categories: cats,
        cases: { bug_regression: [], extension: [], external_systems: [], perf_smoke: [] },
        runs: [],
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-quick-action-perf_smoke-baseline')).toBeInTheDocument();
      });
    });
  });

  // Suppress unused-import warning for `act`
  void act;
});
