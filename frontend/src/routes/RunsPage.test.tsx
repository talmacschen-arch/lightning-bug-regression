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

function setupMocks(runs = FAKE_RUNS) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/runs') return runs;
    if (path === '/admin/categories') return FAKE_CATEGORIES;
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

  it('q-search "fail" matches rows with verdict=fail (not literal status text)', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-q')).toBeInTheDocument();
    });
    const input = screen.getByTestId('filter-q') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'fail' } });

    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-41')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
    expect(screen.queryByTestId('runs-page-row-40')).toBeNull();
  });

  it('q-search "running" matches the running run via verdict', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-q')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('filter-q'), { target: { value: 'running' } });
    await waitFor(() => {
      expect(screen.getByTestId('runs-page-row-39')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('runs-page-row-42')).toBeNull();
  });

  it('q-search also still matches version / triggered_by', async () => {
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

  it('honest placeholder mentions verdict (not "status") + has examples', async () => {
    setupMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('filter-q')).toBeInTheDocument();
    });
    const input = screen.getByTestId('filter-q') as HTMLInputElement;
    expect(input.placeholder).toContain('verdict');
    expect(input.placeholder).toContain('fail');
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
});
