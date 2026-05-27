import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import CaseDetailPage from './CaseDetailPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
});

const fakeCaseDetail = {
  id: 'CASE-001',
  category: 'bug_regression',
  title: 'Test case title',
  status: 'active',
  destructive: false,
  tags: ['tag-a', 'tag-b'],
  yaml_raw: 'id: CASE-001\ntitle: Test case title\n',
  parsed: {
    description: 'This is a description.',
    procedure: 'Step 1\nStep 2',
    expected: 'All should pass.',
    artifacts: null,
    related_pr: 'https://github.com/example/repo/pull/1',
    related_issue: '',
    links: [
      'https://example.com/link1',
      { url: 'https://example.com/link2', label: 'Label Link 2' },
    ],
  },
  error: null,
};

// Helper: build a CaseRecentRunOut row (no target_version)
function makeRun(
  run_id: number,
  case_status: string,
  started_at: string,
  duration_ms?: number | null,
): object {
  return {
    run_id,
    run_status: 'done',
    started_at,
    finished_at: null,
    case_status,
    duration_ms: duration_ms ?? null,
    target_version: null,
  };
}

// Helper: build a CaseRecentRunOut row WITH target_version
function makeRunV(
  run_id: number,
  case_status: string,
  started_at: string,
  target_version: string | null,
  duration_ms?: number | null,
): object {
  return {
    run_id,
    run_status: 'done',
    started_at,
    finished_at: null,
    case_status,
    duration_ms: duration_ms ?? null,
    target_version,
  };
}

// Two fetches happen: (1) GET /cases/CASE-001, (2) GET /cases/CASE-001/recent-runs
function setupTwoFetches(recentRuns: object[] = []) {
  // First call → case detail
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve(fakeCaseDetail),
  });
  // Second call → recent-runs
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve(recentRuns),
  });
}

function renderWithRoute(path: string, initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path={path} element={<CaseDetailPage />} />
        <Route path="/cases" element={<div data-testid="page-cases">Cases</div>} />
        <Route path="/runs/:id" element={<div data-testid="page-run-detail">Run Detail</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Original tests (preserved)
// ---------------------------------------------------------------------------

describe('CaseDetailPage', () => {
  it('shows loading skeleton initially then renders case detail', async () => {
    setupTwoFetches();

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    // Loading skeleton should appear first
    expect(screen.getByTestId('case-detail-loading')).toBeInTheDocument();

    // Wait for the data to load
    await waitFor(() => {
      expect(screen.getByTestId('page-case-detail')).toBeInTheDocument();
    });

    // Verify fetch was called with path substituted
    const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toContain('/cases/CASE-001');
  });

  it('renders yaml_raw in <pre data-testid="case-yaml-raw">', async () => {
    setupTwoFetches();

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-yaml-raw')).toBeInTheDocument();
    });

    const pre = screen.getByTestId('case-yaml-raw');
    expect(pre.tagName).toBe('PRE');
    expect(pre.textContent).toContain('CASE-001');
  });

  it('renders title, status badge, category, and tags', async () => {
    setupTwoFetches();

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-title')).toHaveTextContent('Test case title');
    });

    expect(screen.getByTestId('case-detail-status-badge')).toHaveTextContent('active');
    expect(screen.getByTestId('case-detail-category')).toHaveTextContent('bug_regression');
    expect(screen.getByTestId('case-detail-tags')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-tag-tag-a')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-tag-tag-b')).toBeInTheDocument();
  });

  it('renders parsed narrative sections when present', async () => {
    setupTwoFetches();

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-section-description')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-section-description')).toHaveTextContent('This is a description.');
    expect(screen.getByTestId('case-detail-section-procedure')).toHaveTextContent('Step 1');
    expect(screen.getByTestId('case-detail-section-expected')).toHaveTextContent('All should pass.');
  });

  it('does not render missing parsed sections', async () => {
    const caseWithoutExpected = {
      ...fakeCaseDetail,
      parsed: {
        description: 'Only description',
        // procedure, expected omitted
      },
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(caseWithoutExpected),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve([]),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-section-description')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('case-detail-section-procedure')).not.toBeInTheDocument();
    expect(screen.queryByTestId('case-detail-section-expected')).not.toBeInTheDocument();
  });

  it('renders related links from parsed.related_pr and parsed.links', async () => {
    setupTwoFetches();

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-link-0')).toBeInTheDocument();
    });

    // related_pr is index 0
    const link0 = screen.getByTestId('case-link-0') as HTMLAnchorElement;
    expect(link0.href).toBe('https://github.com/example/repo/pull/1');
    expect(link0.target).toBe('_blank');
    expect(link0.rel).toContain('noreferrer');

    // links[0] is index 1 (related_issue is empty so skipped)
    expect(screen.getByTestId('case-link-1')).toBeInTheDocument();
    // links[1] with label
    expect(screen.getByTestId('case-link-2')).toHaveTextContent('Label Link 2');
  });

  it('renders 404 not-found UI when fetch returns 404', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ detail: 'Case not found' }),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-MISSING');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-not-found')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-back-link')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-back-link')).toHaveAttribute('href', '/cases');
  });

  it('renders error notice when case has parse error', async () => {
    const invalidCase = {
      ...fakeCaseDetail,
      status: 'invalid',
      error: 'YAML parse failed at line 3',
      parsed: null,
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(invalidCase),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve([]),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-error')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-error')).toHaveTextContent('YAML parse failed at line 3');
  });
});

// ---------------------------------------------------------------------------
// M6-D3 T1 — CaseTimeline tests (verify wiring + intent)
// ---------------------------------------------------------------------------

describe('CaseTimeline — cell colors and order (oldest→newest)', () => {
  it('renders cells with correct color classes for pass/fail/skip/error in oldest→newest order', async () => {
    // API returns newest-first; oldest is the LAST item in the array.
    // So: run 10=fail (newest), run 9=pass, run 8=skip, run 7=error (oldest)
    const recentRuns = [
      makeRun(10, 'fail', '2026-05-28T10:00:00'),
      makeRun(9, 'pass', '2026-05-28T09:00:00'),
      makeRun(8, 'skip', '2026-05-28T08:00:00'),
      makeRun(7, 'error', '2026-05-28T07:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline')).toBeInTheDocument();
    });

    // Cells should exist for each run
    const cell7 = screen.getByTestId('case-timeline-cell-7');
    const cell8 = screen.getByTestId('case-timeline-cell-8');
    const cell9 = screen.getByTestId('case-timeline-cell-9');
    const cell10 = screen.getByTestId('case-timeline-cell-10');

    // Data-driven color map: error=orange, skip=gray, pass=green, fail=red
    expect(cell7.className).toContain('bg-orange-500'); // error
    expect(cell8.className).toContain('bg-gray-400');   // skip
    expect(cell9.className).toContain('bg-green-500');  // pass
    expect(cell10.className).toContain('bg-red-500');   // fail

    // Order: oldest→newest — cell 7 should appear before cell 10 in the DOM
    const allCells = screen.getAllByTestId(/^case-timeline-cell-/);
    const ids = allCells.map((el) => el.getAttribute('data-testid'));
    expect(ids).toEqual([
      'case-timeline-cell-7',
      'case-timeline-cell-8',
      'case-timeline-cell-9',
      'case-timeline-cell-10',
    ]);
  });

  it('uses data-driven color map — unknown status falls back to gray-300', async () => {
    const recentRuns = [makeRun(1, 'unknown_status', '2026-05-28T10:00:00')];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-cell-1')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-timeline-cell-1').className).toContain('bg-gray-300');
  });
});

describe('CaseTimeline — summary counts and last-failure', () => {
  it('summary shows correct pass/fail/skip counts', async () => {
    const recentRuns = [
      makeRun(3, 'pass', '2026-05-28T10:00:00'),
      makeRun(2, 'fail', '2026-05-28T09:00:00'),
      makeRun(1, 'skip', '2026-05-28T08:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-summary')).toBeInTheDocument();
    });

    const summary = screen.getByTestId('case-timeline-summary');
    expect(summary.textContent).toContain('最近 3 次');
    expect(summary.textContent).toContain('1 pass');
    expect(summary.textContent).toContain('1 fail');
    expect(summary.textContent).toContain('1 skip');
  });

  it('summary "上次失败" points to the most recent fail run (not oldest)', async () => {
    // Newest (run 5) = fail, run 3 = fail (older). The "last failure" should be run 5.
    const recentRuns = [
      makeRun(5, 'fail', '2026-05-28T10:00:00'),
      makeRun(4, 'pass', '2026-05-28T09:00:00'),
      makeRun(3, 'fail', '2026-05-28T08:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-summary')).toBeInTheDocument();
    });

    const summary = screen.getByTestId('case-timeline-summary');
    expect(summary.textContent).toContain('上次失败：Run #5');
  });

  it('summary "上次失败" also matches "error" case_status', async () => {
    const recentRuns = [
      makeRun(2, 'error', '2026-05-28T10:00:00'),
      makeRun(1, 'pass', '2026-05-28T09:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-summary')).toBeInTheDocument();
    });

    const summary = screen.getByTestId('case-timeline-summary');
    expect(summary.textContent).toContain('上次失败：Run #2');
  });

  it('summary omits "上次失败" when there are no failures', async () => {
    const recentRuns = [
      makeRun(2, 'pass', '2026-05-28T10:00:00'),
      makeRun(1, 'pass', '2026-05-28T09:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-summary')).toBeInTheDocument();
    });

    const summary = screen.getByTestId('case-timeline-summary');
    expect(summary.textContent).not.toContain('上次失败');
  });
});

describe('CaseTimeline — single request wiring', () => {
  it('recent-runs endpoint is requested exactly ONCE even though both CaseTimeline and CaseRecentRuns consume the data', async () => {
    const recentRuns = [
      makeRun(1, 'pass', '2026-05-28T10:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId('case-recent-runs')).toBeInTheDocument();
    });

    // Count how many times the recent-runs endpoint was fetched
    const recentRunsCalls = mockFetch.mock.calls.filter(([url]: [string]) =>
      url.includes('recent-runs'),
    );
    expect(recentRunsCalls).toHaveLength(1);
  });
});

describe('CaseTimeline — timezone regression', () => {
  it('CaseTimeline uses parseUtc so a naive-UTC started_at is parsed as UTC (not local time)', async () => {
    // Use a started_at that is ~5 minutes before "now" in UTC.
    const fiveMinsAgo = new Date(Date.now() - 5 * 60_000);
    // Format as naive-UTC (no Z suffix) — same as what the backend sends
    const naiveUtc = fiveMinsAgo.toISOString().replace('Z', '');

    const recentRuns = [makeRun(1, 'pass', naiveUtc)];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-cell-1')).toBeInTheDocument();
    });

    // The tooltip on the cell should say "5m ago", not "8h 5m ago" (which would
    // happen if new Date() treated the naive string as local UTC+8 time).
    const cell = screen.getByTestId('case-timeline-cell-1');
    const tooltip = cell.getAttribute('title') ?? '';
    expect(tooltip).toContain('5m ago');
    // Ensure it does NOT contain an hours-scale offset (which would indicate the ~8h bug)
    expect(tooltip).not.toMatch(/\d{1,2}h ago/);
  });

  it('CaseRecentRuns uses formatRelativeUtc so naive-UTC started_at is parsed correctly', async () => {
    const twoMinsAgo = new Date(Date.now() - 2 * 60_000);
    const naiveUtc = twoMinsAgo.toISOString().replace('Z', '');

    const recentRuns = [makeRun(99, 'pass', naiveUtc)];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-recent-run-99')).toBeInTheDocument();
    });

    const row = screen.getByTestId('case-recent-run-99');
    // The relative time shown in the row should be "2m ago"
    expect(row.textContent).toContain('2m ago');
  });
});

describe('CaseTimeline — timeline hidden when runs are loading', () => {
  it('does not render case-timeline card while recent-runs are still loading', async () => {
    // Only mock the case detail; recent-runs will never resolve in this test
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });
    // recent-runs hangs (never resolves)
    mockFetch.mockReturnValueOnce(new Promise(() => {}));

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('page-case-detail')).toBeInTheDocument();
    });

    // CaseTimeline should not be visible yet (runs === null)
    expect(screen.queryByTestId('case-timeline')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// M6-D3 T2 — tooltip version number + per-version pass rate (verify wiring)
// ---------------------------------------------------------------------------

describe('CaseTimeline — T2 version number in tooltip', () => {
  it('tooltip contains target_version when present', async () => {
    const recentRuns = [makeRunV(10, 'pass', '2026-05-28T10:00:00', 'v4.5.0')];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-cell-10')).toBeInTheDocument();
    });

    const cell = screen.getByTestId('case-timeline-cell-10');
    const tooltip = cell.getAttribute('title') ?? '';
    expect(tooltip).toContain('v4.5.0');
    // Ensure literal "null" is not rendered
    expect(tooltip).not.toContain('null');
  });

  it('tooltip does NOT contain "null" or version segment when target_version is null', async () => {
    // makeRun uses null target_version
    const recentRuns = [makeRun(5, 'pass', '2026-05-28T10:00:00')];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-cell-5')).toBeInTheDocument();
    });

    const cell = screen.getByTestId('case-timeline-cell-5');
    const tooltip = cell.getAttribute('title') ?? '';
    expect(tooltip).not.toContain('null');
    // Should not end with "· " (trailing separator without version)
    expect(tooltip).not.toMatch(/· $/);
  });

  it('tooltip includes version for versioned run but omits version segment for null-version run', async () => {
    const recentRuns = [
      makeRunV(2, 'pass', '2026-05-28T10:00:00', 'v4.6.0'),
      makeRunV(1, 'fail', '2026-05-28T09:00:00', null),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-cell-2')).toBeInTheDocument();
    });

    const cell2 = screen.getByTestId('case-timeline-cell-2');
    expect(cell2.getAttribute('title')).toContain('v4.6.0');

    const cell1 = screen.getByTestId('case-timeline-cell-1');
    expect(cell1.getAttribute('title')).not.toContain('null');
  });
});

describe('CaseTimeline — T2 per-version pass rate table', () => {
  it('shows correct pass/total for each version', async () => {
    // v4.5.0: 3 pass / 3 total; v4.6.0: 2 pass / 3 total
    // API returns newest-first, so we put newest first:
    const recentRuns = [
      makeRunV(9, 'fail', '2026-05-28T09:00:00', 'v4.6.0'),
      makeRunV(8, 'pass', '2026-05-28T08:00:00', 'v4.6.0'),
      makeRunV(7, 'pass', '2026-05-28T07:00:00', 'v4.6.0'),
      makeRunV(6, 'pass', '2026-05-28T06:00:00', 'v4.5.0'),
      makeRunV(5, 'pass', '2026-05-28T05:00:00', 'v4.5.0'),
      makeRunV(4, 'pass', '2026-05-28T04:00:00', 'v4.5.0'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('version-pass-rate')).toBeInTheDocument();
    });

    // v4.5.0: 3/3
    const v450 = screen.getByTestId('version-pass-rate-v4.5.0');
    expect(v450.textContent).toContain('3/3');

    // v4.6.0: 2/3
    const v460 = screen.getByTestId('version-pass-rate-v4.6.0');
    expect(v460.textContent).toContain('2/3');
  });

  it('groups null target_version under "(no version)" label (not as "null")', async () => {
    const recentRuns = [
      makeRunV(3, 'pass', '2026-05-28T09:00:00', 'v4.5.0'),
      makeRunV(2, 'fail', '2026-05-28T08:00:00', null),
      makeRunV(1, 'pass', '2026-05-28T07:00:00', null),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('version-pass-rate')).toBeInTheDocument();
    });

    // The "(no version)" bucket should exist and show 1/2 (1 pass, 1 fail)
    const noVer = screen.getByTestId('version-pass-rate-(no version)');
    expect(noVer.textContent).toContain('1/2');
    // Must not render literal "null" anywhere in the table
    expect(screen.getByTestId('version-pass-rate').textContent).not.toContain('null');
  });

  it('does not render version table when all runs have null target_version', async () => {
    // Only null versions → no versioned data → table should be hidden
    const recentRuns = [
      makeRun(2, 'pass', '2026-05-28T09:00:00'),
      makeRun(1, 'fail', '2026-05-28T08:00:00'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline')).toBeInTheDocument();
    });

    // Table should not render when there is no actual version data
    expect(screen.queryByTestId('version-pass-rate')).not.toBeInTheDocument();
  });

  it('per-version counts cover both "covers multiple versions" claim per version', async () => {
    // 3 versions, each asserting correct individual counts (not just "table renders")
    const recentRuns = [
      makeRunV(6, 'fail', '2026-05-28T06:00:00', 'v3.0'),
      makeRunV(5, 'pass', '2026-05-28T05:00:00', 'v3.0'),
      makeRunV(4, 'fail', '2026-05-28T04:00:00', 'v2.0'),
      makeRunV(3, 'fail', '2026-05-28T03:00:00', 'v2.0'),
      makeRunV(2, 'pass', '2026-05-28T02:00:00', 'v1.0'),
      makeRunV(1, 'pass', '2026-05-28T01:00:00', 'v1.0'),
    ];
    setupTwoFetches(recentRuns);
    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('version-pass-rate')).toBeInTheDocument();
    });

    // v1.0: 2 pass / 2 total
    expect(screen.getByTestId('version-pass-rate-v1.0').textContent).toContain('2/2');
    // v2.0: 0 pass / 2 total
    expect(screen.getByTestId('version-pass-rate-v2.0').textContent).toContain('0/2');
    // v3.0: 1 pass / 2 total
    expect(screen.getByTestId('version-pass-rate-v3.0').textContent).toContain('1/2');
  });
});
