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
import type { components } from '@/api/types';

type StatusDriftResp = components['schemas']['StatusDriftResponse'];

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
    id_prefix: 'bug-',
    dir_path: 'bug-regression',
    status_whitelist: ['open', 'fixed', 'wontfix', 'stub'],
    default_status: 'open',
    display_order: 10,
  },
  {
    name: 'extension',
    display_name: 'Extension 集成测试',
    description: null,
    id_prefix: 'ext-',
    dir_path: 'extension',
    status_whitelist: ['stable', 'experimental', 'deprecated', 'stub'],
    default_status: 'stable',
    display_order: 20,
  },
  {
    name: 'external_systems',
    display_name: '外部系统集成测试',
    description: null,
    id_prefix: 'xs-',
    dir_path: 'external-systems',
    status_whitelist: ['open', 'fixed', 'wontfix', 'stub', 'awaiting_env'],
    default_status: 'open',
    display_order: 30,
  },
];

const FAKE_BUG_CASES = [
  { id: 'bug-0001', category: 'bug_regression', title: 'A', status: 'fixed', destructive: false, tags: null, error: null },
  { id: 'bug-0002', category: 'bug_regression', title: 'B', status: 'fixed', destructive: false, tags: null, error: null },
  { id: 'bug-0009', category: 'bug_regression', title: 'C', status: 'open', destructive: false, tags: null, error: null },
];

const FAKE_EXT_CASES = [
  { id: 'ext-pgvector', category: 'extension', title: 'pgvector', status: 'stable', destructive: false, tags: null, error: null },
  { id: 'ext-postgis', category: 'extension', title: 'postgis', status: 'stable', destructive: false, tags: null, error: null },
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

const FAKE_DRIFT_EMPTY: StatusDriftResp = {
  rounds: 3,
  run_ids: [42, 41, 40],
  latest_target: 'BUILD-1',
  regression_count: 0,
  candidate_count: 0,
  thin_evidence_count: 0,
  items: [
    { id: 'bug-ok', category: 'bug_regression', title: 't', status: 'fixed', drift: 'OK', detail: '一致', verdicts: ['pass'], suggestion: null },
  ],
};

const FAKE_DRIFT_WITH_ITEMS: StatusDriftResp = {
  rounds: 3,
  run_ids: [42, 41, 40],
  latest_target: 'BUILD-1',
  regression_count: 1,
  candidate_count: 1,
  thin_evidence_count: 0,
  items: [
    { id: 'bug-9001', category: 'bug_regression', title: 't', status: 'fixed', drift: 'REGRESSION', detail: '最近有 fail', verdicts: ['fail', 'pass', 'pass'], suggestion: '查回归，勿盲目改 status' },
    { id: 'bug-9002', category: 'bug_regression', title: 't', status: 'open', drift: 'CANDIDATE', detail: '连续 3 次 pass', verdicts: ['pass', 'pass', 'pass'], suggestion: "人核后 flip fixed + 回填 fixed_version='BUILD-1'" },
    { id: 'bug-9003', category: 'bug_regression', title: 't', status: 'fixed', drift: 'OK', detail: '一致', verdicts: ['pass'], suggestion: null },
  ],
};

function setupMocks(opts?: {
  categories?: typeof FAKE_CATEGORIES;
  cases?: Record<string, typeof FAKE_BUG_CASES>;
  runs?: typeof FAKE_RUNS;
  drift?: StatusDriftResp;
  driftFails?: boolean;
}) {
  const cats = opts?.categories ?? FAKE_CATEGORIES;
  const casesByCategory = opts?.cases ?? {
    bug_regression: FAKE_BUG_CASES,
    extension: FAKE_EXT_CASES,
    external_systems: [],
  };
  const runs = opts?.runs ?? FAKE_RUNS;
  const drift = opts?.drift ?? FAKE_DRIFT_EMPTY;

  apiFetchMock.mockImplementation(async (path: string, method: string, init?: { query?: { category?: string } }) => {
    if (path === '/admin/categories' && method === 'get') return cats;
    if (path === '/cases/status-drift' && method === 'get') {
      if (opts?.driftFails) throw new Error('404 Not Found');
      return drift;
    }
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

  describe('Status breakdown tiles (data-driven across ALL categories)', () => {
    it('renders status breakdown for every active category (post-2026-05-25)', async () => {
      setupMocks();
      renderPage();
      // Row 2 container is testid'd
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-row-status')).toBeInTheDocument();
      });
      // All 3 categories (from FAKE_CATEGORIES) get a status tile —
      // including external_systems, which was missed by the pre-fix
      // hardcoded `bugCategory()` / `extensionCategory()` helpers.
      expect(screen.getByTestId('dashboard-kpi-status-bug_regression')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-extension')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-external_systems')).toBeInTheDocument();
    });

    it('BUG status tile lists all 4 statuses from whitelist', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-status-bug_regression')).toBeInTheDocument();
      });
      expect(screen.getByTestId('dashboard-kpi-status-bug_regression-row-open')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-bug_regression-row-fixed')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-bug_regression-row-wontfix')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-bug_regression-row-stub')).toBeInTheDocument();
    });

    it('external_systems status tile shows BOTH BUG-fix axis (open/fixed/wontfix/stub) AND awaiting_env lifecycle value', async () => {
      // v1.21: external_systems whitelist 加入 BUG 修复维度（open/fixed/wontfix/stub），
      // 与 bug_regression 对齐；awaiting_env 保留作辅助 lifecycle 占位（外部服务未部署）。
      // 5 行 status row 全部数据驱动渲染。
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-status-external_systems')).toBeInTheDocument();
      });
      // status_whitelist = [open, fixed, wontfix, stub, awaiting_env]
      expect(screen.getByTestId('dashboard-kpi-status-external_systems-row-open')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-external_systems-row-fixed')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-external_systems-row-wontfix')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-external_systems-row-stub')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-external_systems-row-awaiting_env')).toBeInTheDocument();
      // 旧 'stable' 值已从白名单移除，不应再渲染
      expect(screen.queryByTestId('dashboard-kpi-status-external_systems-row-stable')).toBeNull();
    });

    it('new category gets a status tile without code change (§14 R4b)', async () => {
      // Add a 4th category; row 2 should render its tile too.
      const extra = [
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
        categories: extra,
        cases: {
          bug_regression: FAKE_BUG_CASES,
          extension: FAKE_EXT_CASES,
          external_systems: [],
          perf_smoke: [],
        },
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-status-perf_smoke')).toBeInTheDocument();
      });
      // its own whitelist rows
      expect(screen.getByTestId('dashboard-kpi-status-perf_smoke-row-baseline')).toBeInTheDocument();
      expect(screen.getByTestId('dashboard-kpi-status-perf_smoke-row-regression')).toBeInTheDocument();
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

    it('shows error badge in tile when a run has errored cases (dogfood run #25)', async () => {
      // Run #25 scenario: 15 pass, 0 fail, 1 errored → verdict=error, not pass.
      // Pre-fix the tile showed PASS (errored was invisible).
      // Cast via unknown so the `errored` field (pre-PR-D type extension)
      // attaches without conflicting with the strict RunSummary fixture type.
      setupMocks({
        runs: [
          // id=25: errored=1 → verdict=error
          Object.assign(
            { id: 25, status: 'done', started_at: new Date().toISOString(), finished_at: null, total: 17, passed: 15, failed: 0, skipped: 1, target_version: null, triggered_by: null },
            { errored: 1 },
          ) as (typeof FAKE_RUNS)[number],
          // id=24: no errored field → verdict=pass
          { id: 24, status: 'done', started_at: new Date().toISOString(), finished_at: null, total: 10, passed: 10, failed: 0, skipped: 0, target_version: null, triggered_by: null },
        ],
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-kpi-recent-runs')).toBeInTheDocument();
      });
      const tile = screen.getByTestId('dashboard-kpi-recent-runs');
      // id=25 → verdict=error, id=24 → verdict=pass
      expect(within(tile).getByText('1 pass')).toBeInTheDocument();
      expect(within(tile).getByText('1 error')).toBeInTheDocument();
      // fail badge still shows 0 fail
      expect(within(tile).getByText('0 fail')).toBeInTheDocument();
    });

    it('shows "Compare last 2 runs" CTA when ≥2 runs exist', async () => {
      // FAKE_RUNS has 3 runs (id 42 newest, 41, 40 oldest)
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-compare-previous')).toBeInTheDocument();
      });
      const link = screen.getByTestId('dashboard-compare-previous');
      expect(link.tagName).toBe('A');
      // a=older (runs[1]=41), b=newer (runs[0]=42)
      expect(link.getAttribute('href')).toBe('/runs/diff?a=41&b=42');
    });

    it('hides Compare CTA when fewer than 2 runs', async () => {
      setupMocks({
        runs: [
          { id: 42, status: 'done', started_at: new Date().toISOString(), finished_at: null, total: 1, passed: 1, failed: 0, skipped: 0, target_version: null, triggered_by: null },
        ],
      });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-recent-activity')).toBeInTheDocument();
      });
      expect(screen.queryByTestId('dashboard-compare-previous')).toBeNull();
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
      expect(screen.getByTestId('dashboard-quick-action-external_systems-open')).toBeInTheDocument();
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

  describe('Dashboard header CTA (dashboard-new-run)', () => {
    it('renders dashboard-new-run button that links to /runs/new', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      });
      const btn = screen.getByTestId('dashboard-new-run');
      expect(btn).toBeInTheDocument();
      // Button renders as <a> (asChild + Link) with correct href
      expect(btn.tagName.toLowerCase()).toBe('a');
      expect(btn).toHaveAttribute('href', '/runs/new');
    });

    it('QuickActions section renders before KPI row (correct DOM order)', async () => {
      setupMocks();
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      });
      const page = screen.getByTestId('page-dashboard');
      const children = Array.from(page.children);
      const quickActionsIdx = children.findIndex(
        (el) => el.getAttribute('data-testid') === 'dashboard-quick-actions',
      );
      const kpiRowIdx = children.findIndex(
        (el) => el.getAttribute('data-testid') === 'dashboard-kpi-row',
      );
      // Quick start section must appear before the first KPI row
      expect(quickActionsIdx).toBeGreaterThanOrEqual(0);
      expect(kpiRowIdx).toBeGreaterThanOrEqual(0);
      expect(quickActionsIdx).toBeLessThan(kpiRowIdx);
    });
  });

  describe('Status drift card (只读对账)', () => {
    it('shows empty state + zero summary when no drift', async () => {
      setupMocks(); // default FAKE_DRIFT_EMPTY (all OK)
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-status-drift')).toBeInTheDocument();
      });
      expect(
        screen.getByTestId('dashboard-status-drift-empty'),
      ).toBeInTheDocument();
      // no actionable rows rendered
      expect(
        screen.queryByTestId('dashboard-status-drift-row-bug-ok'),
      ).toBeNull();
    });

    it('degrades gracefully when drift endpoint fails (dashboard still opens)', async () => {
      // 回归 2026-07-19：旧后端无 /cases/status-drift → 404 曾让整个 dashboard
      // 报错打不开。drift 是增强卡片，失败必须降级、不拖垮主页面。
      setupMocks({ driftFails: true });
      renderPage();
      await waitFor(() => {
        expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      });
      // 绝不能进整页 error
      expect(screen.queryByTestId('page-dashboard-error')).toBeNull();
      // drift 卡片降级为 unavailable，其余 KPI 正常
      expect(
        screen.getByTestId('dashboard-status-drift-unavailable'),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('dashboard-kpi-category-bug_regression'),
      ).toBeInTheDocument();
    });

    it('lists REGRESSION + CANDIDATE rows, hides OK, surfaces suggestion', async () => {
      setupMocks({ drift: FAKE_DRIFT_WITH_ITEMS });
      renderPage();
      await waitFor(() => {
        expect(
          screen.getByTestId('dashboard-status-drift-row-bug-9001'),
        ).toBeInTheDocument();
      });
      // CANDIDATE row present
      expect(
        screen.getByTestId('dashboard-status-drift-row-bug-9002'),
      ).toBeInTheDocument();
      // OK row must NOT be shown — only actionable categories are listed
      expect(
        screen.queryByTestId('dashboard-status-drift-row-bug-9003'),
      ).toBeNull();
      // summary shows counts (🔴 1 · 🟢 1 · ⏳ 0)
      expect(
        screen.getByTestId('dashboard-status-drift-summary'),
      ).toHaveTextContent('1');
      // candidate row surfaces the fixed_version backfill suggestion
      const candRow = screen.getByTestId('dashboard-status-drift-row-bug-9002');
      expect(within(candRow).getByText(/BUILD-1/)).toBeInTheDocument();
    });
  });

  // Suppress unused-import warning for `act`
  void act;
});
