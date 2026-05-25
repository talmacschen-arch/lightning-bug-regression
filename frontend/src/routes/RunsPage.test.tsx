/**
 * RunsPage unit tests.
 *
 * Covers the post-PR-#107 fix: filter + badge use verdict (pass/fail/
 * running/aborted) derived from runVerdict(), not raw backend lifecycle
 * status ('done'/'running'/'aborted').
 *
 * Pre-fix, status filter chips were ['pass','fail','running','error',
 * 'completed'] and filter logic compared `r.status` directly — `'pass'`
 * never matched any real run because backend writes `'done'`. After fix,
 * chips show 4 verdict options and the filter compares `runVerdict(r)`.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import RunsPage from './RunsPage';
import type { components } from '@/api/client';

type RunSummary = components['schemas']['RunSummary'];

const apiFetchMock = vi.fn();
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

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
];

// Mirrors REAL backend: run.status is 'done' / 'running' / 'aborted'
// lifecycle phase, not verdict. Verdict derives from `failed` count.
const FAKE_RUNS = [
  // id=42: done + failed=0 + passed=9  → verdict=pass
  { id: 42, status: 'done',    started_at: new Date(Date.now() - 4 * 3_600_000).toISOString(),  finished_at: null, total: 10, passed: 9,  failed: 0, skipped: 0, target_version: '4.5.0', triggered_by: 'gpadmin' },
  // id=41: done + failed=5             → verdict=fail
  { id: 41, status: 'done',    started_at: new Date(Date.now() - 24 * 3_600_000).toISOString(), finished_at: null, total: 10, passed: 5,  failed: 5, skipped: 0, target_version: '4.5.0', triggered_by: 'alice' },
  // id=40: done + failed=0 + passed=10 → verdict=pass
  { id: 40, status: 'done',    started_at: new Date(Date.now() - 48 * 3_600_000).toISOString(), finished_at: null, total: 10, passed: 10, failed: 0, skipped: 0, target_version: '4.4.0', triggered_by: 'gpadmin' },
  // id=39: running                     → verdict=running
  { id: 39, status: 'running', started_at: new Date(Date.now() - 5 * 60_000).toISOString(),     finished_at: null, total: 0,  passed: 0,  failed: 0, skipped: 0, target_version: '4.5.0', triggered_by: 'bob' },
  // id=38: aborted                     → verdict=aborted
  { id: 38, status: 'aborted', started_at: new Date(Date.now() - 100 * 3_600_000).toISOString(), finished_at: null, total: 0, passed: 0, failed: 0, skipped: 0, target_version: '4.5.0', triggered_by: null },
];

const FAKE_CASES = [
  { id: 'lg-bug-0001-hashjoin-right-table', category: 'bug_regression', title: 'hashjoin right table', status: 'fixed', destructive: false, tags: null, error: null },
  { id: 'lg-bug-0009-union-all-const-distributed-row-order', category: 'bug_regression', title: 'UNION ALL const row order', status: 'open', destructive: false, tags: null, error: null },
];

function setupMocks(runs: RunSummary[] = FAKE_RUNS) {
  apiFetchMock.mockImplementation(async (path: string, _method: string, init?: { query?: Record<string, string> }) => {
    if (path === '/runs') {
      // case_id filter is server-side: when present, only return runs
      // that "touched" the filtered case. Tests below seed the fake
      // backend to mirror this — return the FAKE_RUNS subset matching.
      const cid = init?.query?.case_id;
      if (cid === 'lg-bug-0009-union-all-const-distributed-row-order') {
        return [runs[1], runs[2]]; // id=41, id=40
      }
      if (cid && !FAKE_CASES.find((c) => c.id === cid)) {
        return [];
      }
      return runs;
    }
    if (path === '/admin/categories') return FAKE_CATEGORIES;
    if (path === '/cases') return FAKE_CASES;
    throw new Error(`unmocked: ${path}`);
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

function renderPage(initialPath = '/runs') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <RunsPage />
    </MemoryRouter>,
  );
}

describe('RunsPage', () => {
  it('renders all runs by default + uses derived verdict for badge', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-list')).toBeInTheDocument();
    });
    expect(screen.getByTestId('runs-page-row-42')).toBeInTheDocument();
    expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();
    expect(screen.getByTestId('runs-page-row-40')).toBeInTheDocument();
    expect(screen.getByTestId('runs-page-row-39')).toBeInTheDocument();
    expect(screen.getByTestId('runs-page-row-38')).toBeInTheDocument();

    // Verdict badges, NOT raw status. Pre-fix all would say "DONE".
    expect(screen.getByTestId('runs-page-status-42')).toHaveTextContent('PASS');
    expect(screen.getByTestId('runs-page-status-41')).toHaveTextContent('FAIL');
    expect(screen.getByTestId('runs-page-status-40')).toHaveTextContent('PASS');
    expect(screen.getByTestId('runs-page-status-39')).toHaveTextContent('RUNNING');
    expect(screen.getByTestId('runs-page-status-38')).toHaveTextContent('ABORTED');
  });

  it('chip "pass" filters by verdict=pass (not raw status) — regression for pre-fix bug', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-list')).toBeInTheDocument();
    });
    // Find the verdict chip — FilterBar renders it under filter-status-<verdict>
    await waitFor(() => {
      expect(screen.getByTestId('filter-status-pass')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('filter-status-pass'));

    // After clicking "pass" chip, only verdict=pass rows remain (42 + 40).
    // Pre-fix this would yield 0 rows because filter compared raw status
    // ('done') against chip value ('pass') which never matched.
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-42')).toBeInTheDocument();
    });
    expect(screen.getByTestId('runs-page-row-40')).toBeInTheDocument();
    expect(screen.queryByTestId('runs-page-row-41')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-39')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-38')).toBeNull();
  });

  it('chip "fail" filters to verdict=fail rows', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-status-fail')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('filter-status-fail'));
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-40')).toBeNull();
  });

  it('renders verdict chip options (not legacy raw-status set)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-status-pass')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-status-fail')).toBeInTheDocument();
    expect(screen.getByTestId('filter-status-running')).toBeInTheDocument();
    expect(screen.getByTestId('filter-status-aborted')).toBeInTheDocument();
    // Pre-fix legacy chip values that don't exist in backend → must NOT render
    expect(screen.queryByTestId('filter-status-error')).toBeNull();
    expect(screen.queryByTestId('filter-status-completed')).toBeNull();
    expect(screen.queryByTestId('filter-status-done')).toBeNull();
  });

  it('q-search matches version (target_version)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-q')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: '4.4.0' } });
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-40')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
  });

  it('q-search matches triggered_by', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('filter-q')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: 'alice' } });
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
  });

  it('q-search "42" matches run id=42 (id re-added to hay 2026-05-25 user feedback)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('filter-q')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: '42' } });
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-42')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-41')).toBeNull();
  });

  it('q-search "fail" does NOT match verdict (chip filter is the canonical path)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('filter-q')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: 'fail' } });
    await waitFor(() => {
      // version/triggered_by hay doesn't contain "fail" → empty state
      expect(screen.getByTestId('runs-page-empty')).toBeInTheDocument();
    });
  });

  it('placeholder reflects current search scope (id + version + triggered_by)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('filter-q')).toBeInTheDocument());
    const input = screen.getByTestId('filter-q') as HTMLInputElement;
    expect(input.placeholder).toContain('id');
    expect(input.placeholder).toContain('version');
    expect(input.placeholder).toContain('triggered_by');
    // verdict explicitly excluded — chip filter is canonical
    expect(input.placeholder).not.toContain('verdict');
  });

  it('row renders triggered_by column with 👤 prefix', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('runs-page-list')).toBeInTheDocument());
    // id=42 fixture has triggered_by='gpadmin'
    const tb42 = screen.getByTestId('runs-page-triggered-by-42');
    expect(tb42.textContent).toContain('gpadmin');
    // id=38 fixture has triggered_by=null → "—"
    const tb38 = screen.getByTestId('runs-page-triggered-by-38');
    expect(tb38.textContent).toContain('—');
  });

  it('case-id picker triggers server-side filter via /runs?case_id=X', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('runs-page-list')).toBeInTheDocument());

    // Initially all 5 runs render (no case_id filter)
    expect(screen.getByTestId('runs-page-row-42')).toBeInTheDocument();
    expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();

    // Open combobox + pick a case
    fireEvent.click(screen.getByTestId('runs-page-case-picker-trigger'));
    await waitFor(() => {
      expect(
        screen.getByTestId('runs-page-case-picker-item-lg-bug-0009-union-all-const-distributed-row-order'),
      ).toBeInTheDocument();
    });
    fireEvent.click(
      screen.getByTestId('runs-page-case-picker-item-lg-bug-0009-union-all-const-distributed-row-order'),
    );

    // Mock setup returns only runs 41 + 40 for that case_id
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();
    });
    expect(screen.getByTestId('runs-page-row-40')).toBeInTheDocument();
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-39')).toBeNull();

    // Clear button is now visible
    expect(screen.getByTestId('runs-page-case-clear')).toBeInTheDocument();

    // Verify the apiFetch call carried the case_id query
    const fetchedWithCaseId = apiFetchMock.mock.calls.some(
      (call) =>
        call[0] === '/runs' &&
        call[2]?.query?.case_id === 'lg-bug-0009-union-all-const-distributed-row-order',
    );
    expect(fetchedWithCaseId).toBe(true);
  });

  it('case-id Clear button removes filter + restores all runs', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('runs-page-list')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('runs-page-case-picker-trigger'));
    await waitFor(() => {
      expect(
        screen.getByTestId('runs-page-case-picker-item-lg-bug-0009-union-all-const-distributed-row-order'),
      ).toBeInTheDocument();
    });
    fireEvent.click(
      screen.getByTestId('runs-page-case-picker-item-lg-bug-0009-union-all-const-distributed-row-order'),
    );
    await waitFor(() => expect(screen.getByTestId('runs-page-case-clear')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('runs-page-case-clear'));
    await waitFor(() => {
      // All 5 rows back
      expect(screen.getByTestId('runs-page-row-42')).toBeInTheDocument();
      expect(screen.getByTestId('runs-page-row-38')).toBeInTheDocument();
    });
    // Clear button hidden again
    expect(screen.queryByTestId('runs-page-case-clear')).toBeNull();
  });

  it('hides category chips (RunsPage has no category filter logic)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-list')).toBeInTheDocument();
    });
    // Filter bar present + verdict chips present, but NO category row
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument();
    expect(screen.getByTestId('filter-status-pass')).toBeInTheDocument();
    expect(screen.queryByTestId('filter-categories')).toBeNull();
    expect(screen.queryByTestId('filter-category-bug_regression')).toBeNull();
  });

  it('empty state when no runs from API', async () => {
    setupMocks([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-empty')).toBeInTheDocument();
    });
  });

  it('error state on API failure', async () => {
    apiFetchMock.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-error')).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Version column tests
  // ---------------------------------------------------------------------------

  it('version column renders named target_version for each run', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('runs-page-list')).toBeInTheDocument());
    // id=42 fixture has target_version='4.5.0'
    const v42 = screen.getByTestId('runs-page-version-42');
    expect(v42.textContent).toContain('4.5.0');
    // id=40 fixture has target_version='4.4.0'
    const v40 = screen.getByTestId('runs-page-version-40');
    expect(v40.textContent).toContain('4.4.0');
  });

  it('version column shows em-dash for null target_version', async () => {
    const runsWithNull: RunSummary[] = [
      { id: 55, status: 'done', started_at: new Date().toISOString(), finished_at: null, total: 1, passed: 1, failed: 0, skipped: 0, target_version: null, triggered_by: 'tester' },
    ];
    setupMocks(runsWithNull);
    renderPage();
    await waitFor(() => expect(screen.getByTestId('runs-page-list')).toBeInTheDocument());
    const v55 = screen.getByTestId('runs-page-version-55');
    expect(v55.textContent).toContain('—');
  });

  it('q-search on version substring shows matching rows only (regression guard)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => expect(screen.getByTestId('filter-q')).toBeInTheDocument());
    // id=40 has target_version='4.4.0'; others are '4.5.0' or no match on '4.4.0'
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: '4.4.0' } });
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-40')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-41')).toBeNull();
  });
});
