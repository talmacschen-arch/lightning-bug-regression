/**
 * RunDetailPage tests — initial GET + SSE live progress (M6-1).
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import RunDetailPage from './RunDetailPage';

// --- mock useNavigate for M6-D1 rerun button navigation ------------------
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockFetch = vi.fn();

// --- mock EventSource --------------------------------------------------------

interface MockESInstance {
  url: string;
  readyState: number;
  onmessage: ((e: { data: string }) => void) | null;
  onerror: (() => void) | null;
  close(): void;
  // test helpers
  __emit(event: object): void;
  __fail(): void;
}

const esInstances: MockESInstance[] = [];

class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  url: string;
  readyState = MockEventSource.OPEN;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) {
    this.url = url;
    esInstances.push(this as unknown as MockESInstance);
    Object.assign(this, {
      __emit: (ev: object) => {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(ev) });
      },
      __fail: () => {
        this.readyState = MockEventSource.CLOSED;
        if (this.onerror) this.onerror();
      },
    });
  }
  close() {
    this.readyState = MockEventSource.CLOSED;
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('EventSource', MockEventSource);
  mockFetch.mockReset();
  mockNavigate.mockReset();
  esInstances.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- fixtures ---------------------------------------------------------------

// status='done' = real backend lifecycle terminal (NOT 'pass' verdict)
const fakeRunDone = {
  id: 99,
  status: 'done',
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:01:00Z',
  total: 3,
  passed: 3,
  failed: 0,
  skipped: 0,
  target_version: '5.1.0',
  triggered_by: null,
  case_results: [
    {
      case_id: 'bug-001',
      status: 'pass',
      duration_ms: 1000,
      skip_reason: null,
      expect_detail: null,
      artifacts_path: '/tmp/art/99/bug-001',
    },
    {
      case_id: 'bug-002',
      status: 'pass',
      duration_ms: 1100,
      skip_reason: null,
      expect_detail: null,
      artifacts_path: '/tmp/art/99/bug-002',
    },
    {
      case_id: 'bug-003',
      status: 'pass',
      duration_ms: 1050,
      skip_reason: null,
      expect_detail: null,
      artifacts_path: null,
    },
  ],
};

const fakeRunRunning = {
  id: 42,
  status: 'running',
  started_at: '2026-01-01T00:00:00Z',
  finished_at: null,
  total: 2,
  passed: 0,
  failed: 0,
  skipped: 0,
  target_version: null,
  triggered_by: null,
  case_results: [],
};

const fakeRunRunningWithOneCase = {
  ...fakeRunRunning,
  passed: 1,
  case_results: [
    {
      case_id: 'bug-001',
      status: 'pass',
      duration_ms: 500,
      skip_reason: null,
      expect_detail: null,
      artifacts_path: null,
    },
  ],
};

function mockJsonResponse(body: object) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve(body),
  };
}

function renderWithRoute(runId: string) {
  return render(
    <MemoryRouter initialEntries={[`/runs/${runId}`]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RunDetailPage', () => {
  it('terminal run renders without opening SSE', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunDone));
    renderWithRoute('99');
    expect(screen.getByTestId('run-detail-loading')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toBeInTheDocument();
    });
    expect(screen.getByTestId('run-status-badge')).toHaveTextContent('DONE');
    expect(screen.getByTestId('run-case-row-bug-001')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-002')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-003')).toBeInTheDocument();
    // Stream indicator hidden for terminal runs
    expect(screen.queryByTestId('run-stream-mode')).toBeNull();
    // No EventSource opened (run was already terminal)
    expect(esInstances.length).toBe(0);
  });

  it('highlights failed and errored case rows, leaves pass/skip plain', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunMixed));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('run-case-row-bug-fail-1')).toBeInTheDocument();
    });

    const failRow = screen.getByTestId('run-case-row-bug-fail-1');
    const errorRow = screen.getByTestId('run-case-row-bug-error-1');
    const passRow = screen.getByTestId('run-case-row-bug-pass');
    const skipRow = screen.getByTestId('run-case-row-bug-skip');

    // fail + error rows flagged + tinted; pass + skip stay plain.
    expect(failRow).toHaveAttribute('data-problem', 'true');
    expect(failRow.className).toContain('bg-red-50');
    expect(failRow.className).toContain('border-l-red-500');

    expect(errorRow).toHaveAttribute('data-problem', 'true');
    expect(errorRow.className).toContain('bg-orange-50');
    expect(errorRow.className).toContain('border-l-orange-500');

    expect(passRow).not.toHaveAttribute('data-problem');
    expect(passRow.className).not.toContain('bg-red-50');
    expect(skipRow).not.toHaveAttribute('data-problem');

    // status badge picks up its hue
    expect(screen.getByTestId('run-case-status-bug-fail-1').className).toContain('bg-red-100');
    expect(screen.getByTestId('run-case-status-bug-error-1').className).toContain('bg-orange-100');
    expect(screen.getByTestId('run-case-status-bug-pass').className).toContain('bg-green-100');
  });

  it('"Only failed/errored" toggle filters the case list to problem rows', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunMixed));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('run-case-row-bug-pass')).toBeInTheDocument();
    });

    // Off by default: all rows visible, toggle labels the problem count (3).
    const toggle = screen.getByTestId('btn-filter-failed');
    expect(toggle).toHaveTextContent('Only failed/errored (3)');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('run-case-row-bug-skip')).toBeInTheDocument();

    // Turn on: pass + skip rows drop, only fail/error remain.
    act(() => toggle.click());
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(toggle).toHaveTextContent('Show all');
    expect(screen.queryByTestId('run-case-row-bug-pass')).toBeNull();
    expect(screen.queryByTestId('run-case-row-bug-skip')).toBeNull();
    expect(screen.getByTestId('run-case-row-bug-fail-1')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-fail-2')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-error-1')).toBeInTheDocument();

    // Toggle back off: everything returns.
    act(() => toggle.click());
    expect(screen.getByTestId('run-case-row-bug-pass')).toBeInTheDocument();
  });

  it('filter toggle is absent when the run has no failed/errored cases', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunDone));
    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('run-case-row-bug-001')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('btn-filter-failed')).toBeNull();
  });

  it('running run opens SSE and indicator shows "live"', async () => {
    mockFetch.mockResolvedValue(mockJsonResponse(fakeRunRunning));
    renderWithRoute('42');
    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toBeInTheDocument();
    });
    expect(screen.getByTestId('run-status-badge')).toHaveTextContent('RUNNING');
    await waitFor(() => {
      expect(esInstances.length).toBe(1);
    });
    expect(esInstances[0].url).toBe('http://127.0.0.1:8000/runs/42/stream');
    expect(screen.getByTestId('run-stream-mode')).toHaveAttribute('data-mode', 'sse');
    expect(screen.getByTestId('run-stream-mode')).toHaveTextContent('live');
  });

  it('case_done event triggers refetch + new case row appears', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunRunning)) // initial GET
      .mockResolvedValueOnce(mockJsonResponse(fakeRunRunningWithOneCase)); // refetch after case_done

    renderWithRoute('42');

    await waitFor(() => expect(esInstances.length).toBe(1));
    // Initial render: no case rows yet
    expect(screen.queryByTestId('run-case-row-bug-001')).toBeNull();

    // Backend emits case_done
    act(() => esInstances[0].__emit({ type: 'case_done', case_id: 'bug-001', status: 'pass' }));

    await waitFor(() => {
      expect(screen.getByTestId('run-case-row-bug-001')).toBeInTheDocument();
    });
  });

  it('run_done event closes stream + final refetch shows terminal state', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunRunning))
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone));

    renderWithRoute('42');
    await waitFor(() => expect(esInstances.length).toBe(1));
    act(() =>
      esInstances[0].__emit({
        type: 'run_done',
        run_id: 42,
        summary: { total: 3, passed: 3, failed: 0, skipped: 0 },
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toHaveTextContent('DONE');
    });
    // Stream indicator hidden after terminal
    await waitFor(() => {
      expect(screen.queryByTestId('run-stream-mode')).toBeNull();
    });
  });

  it('EventSource error before terminal falls back to polling', async () => {
    mockFetch.mockResolvedValue(mockJsonResponse(fakeRunRunning));
    renderWithRoute('42');
    await waitFor(() => expect(esInstances.length).toBe(1));
    expect(screen.getByTestId('run-stream-mode')).toHaveAttribute('data-mode', 'sse');

    act(() => esInstances[0].__fail());

    await waitFor(() => {
      expect(screen.getByTestId('run-stream-mode')).toHaveAttribute('data-mode', 'polling');
    });
  });

  it('initial fetch error shows error state and no stream is opened', async () => {
    mockFetch.mockRejectedValueOnce(new Error('boom'));
    renderWithRoute('999');
    await waitFor(() => {
      expect(screen.getByTestId('run-detail-error')).toBeInTheDocument();
    });
    expect(esInstances.length).toBe(0);
  });

  // ---- M6-2 artifacts -----------------------------------------------------

  it('artifacts toggle is hidden for cases without artifacts_path', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunDone));
    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('run-case-row-bug-003')).toBeInTheDocument();
    });
    // bug-001 + bug-002 have artifacts_path; bug-003 doesn't
    expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    expect(screen.getByTestId('artifacts-toggle-bug-002')).toBeInTheDocument();
    expect(screen.queryByTestId('artifacts-toggle-bug-003')).toBeNull();
  });

  it('clicking artifacts toggle lazy-fetches + shows file list', async () => {
    // First call: initial GET for run. Second call: artifacts list for bug-001.
    const FAKE_ARTIFACTS = [
      {
        filename: 'step-00-setup.stdout.txt',
        size_bytes: 1024,
        kind: 'stdout',
        step_idx: 0,
        step_id: 'setup',
      },
      {
        filename: 'step-01-main.stderr.txt',
        size_bytes: 32,
        kind: 'stderr',
        step_idx: 1,
        step_id: 'main',
      },
      { filename: 'summary.json', size_bytes: 50, kind: 'other', step_idx: null, step_id: null },
    ];
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone))
      .mockResolvedValueOnce(mockJsonResponse(FAKE_ARTIFACTS));

    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });

    // Pre-toggle: no panel
    expect(screen.queryByTestId('artifacts-panel-bug-001')).toBeNull();

    act(() => {
      screen.getByTestId('artifacts-toggle-bug-001').click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('artifacts-list-bug-001')).toBeInTheDocument();
    });

    // All 3 files render
    expect(
      screen.getByTestId('artifact-item-bug-001-step-00-setup.stdout.txt'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('artifact-item-bug-001-step-01-main.stderr.txt')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-item-bug-001-summary.json')).toBeInTheDocument();

    // Download links point to backend endpoint
    const dl = screen.getByTestId('artifact-download-bug-001-step-00-setup.stdout.txt');
    expect(dl.tagName).toBe('A');
    expect(dl.getAttribute('href')).toContain(
      '/runs/99/cases/bug-001/artifacts/step-00-setup.stdout.txt',
    );
    expect(dl.getAttribute('download')).toBe('step-00-setup.stdout.txt');
  });

  it('empty artifacts list renders the empty hint', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone))
      .mockResolvedValueOnce(mockJsonResponse([]));
    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-empty-bug-001')).toBeInTheDocument();
    });
  });

  it('artifacts fetch error shows inline error', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunDone)).mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      json: () => Promise.resolve({}),
    });
    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-error-bug-001')).toBeInTheDocument();
    });
  });

  // ---- M6-D2 artifact inline view -----------------------------------------

  const FAKE_ARTIFACTS_FOR_VIEW = [
    {
      filename: 'step-00-setup.stdout.txt',
      size_bytes: 1024,
      kind: 'stdout',
      step_idx: 0,
      step_id: 'setup',
    },
    {
      filename: 'step-01-main.stderr.txt',
      size_bytes: 32,
      kind: 'stderr',
      step_idx: 1,
      step_id: 'main',
    },
  ];

  it('View button renders file text on first click; re-expand does NOT re-fetch', async () => {
    // Call order: [0] initial run GET, [1] artifacts list, [2] file text fetch
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone)) // run detail
      .mockResolvedValueOnce(mockJsonResponse(FAKE_ARTIFACTS_FOR_VIEW)) // artifacts list
      .mockResolvedValueOnce({
        // file text
        ok: true,
        status: 200,
        text: () => Promise.resolve('hello world\nline2'),
        json: () => {
          throw new Error('should not call json');
        },
      });

    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });

    // Open artifacts panel
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-list-bug-001')).toBeInTheDocument();
    });

    // View button present
    const viewBtn = screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt');
    expect(viewBtn).toBeInTheDocument();
    // Content not visible yet
    expect(screen.queryByTestId('artifact-content-bug-001-step-00-setup.stdout.txt')).toBeNull();

    // Click View → fetch fires, content appears
    act(() => viewBtn.click());
    await waitFor(() => {
      expect(
        screen.getByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
    ).toHaveTextContent('hello world');

    // Collapse by clicking Hide
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(screen.queryByTestId('artifact-content-bug-001-step-00-setup.stdout.txt')).toBeNull();
    });

    // Re-expand — should NOT trigger a second fetch (cache hit)
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(
        screen.getByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
      ).toBeInTheDocument();
    });

    // Total fetch calls: [0] run, [1] artifacts list, [2] file text — no 4th call
    // The file text fetch (call index 2) must have been called exactly once
    const allCalls = mockFetch.mock.calls;
    const fileTextCalls = allCalls.filter((args: unknown[]) => {
      const url = args[0] as string;
      return typeof url === 'string' && url.includes('/artifacts/step-00-setup.stdout.txt');
    });
    expect(fileTextCalls).toHaveLength(1);
  });

  it('fetch failure on View shows error; Download link still works', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone)) // run detail
      .mockResolvedValueOnce(mockJsonResponse(FAKE_ARTIFACTS_FOR_VIEW)) // artifacts list
      .mockResolvedValueOnce({
        // file text → error
        ok: false,
        status: 500,
        text: () => Promise.resolve(''),
        json: () => Promise.resolve({}),
      });

    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-list-bug-001')).toBeInTheDocument();
    });

    // Click View
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(
        screen.getByTestId('artifact-view-error-bug-001-step-00-setup.stdout.txt'),
      ).toBeInTheDocument();
    });
    // Content must NOT appear
    expect(screen.queryByTestId('artifact-content-bug-001-step-00-setup.stdout.txt')).toBeNull();
    // Download link must still be present and functional
    const dlLink = screen.getByTestId('artifact-download-bug-001-step-00-setup.stdout.txt');
    expect(dlLink).toBeInTheDocument();
    expect(dlLink.getAttribute('href')).toContain('/artifacts/step-00-setup.stdout.txt');
  });

  it('retry after error: collapse then re-expand with successful fetch renders content (error div gone)', async () => {
    // Call order: [0] run, [1] artifacts list, [2] file text → 500 error,
    // [3] file text → success on retry.
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone)) // run detail
      .mockResolvedValueOnce(mockJsonResponse(FAKE_ARTIFACTS_FOR_VIEW)) // artifacts list
      .mockResolvedValueOnce({
        // first fetch: server error
        ok: false,
        status: 500,
        text: () => Promise.resolve(''),
        json: () => Promise.resolve({}),
      })
      .mockResolvedValueOnce({
        // second fetch on retry: success
        ok: true,
        status: 200,
        text: () => Promise.resolve('retry content line'),
        json: () => {
          throw new Error('should not call json');
        },
      });

    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });

    // Open artifacts panel
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-list-bug-001')).toBeInTheDocument();
    });

    // First View click → fetch fails → error div shown
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(
        screen.getByTestId('artifact-view-error-bug-001-step-00-setup.stdout.txt'),
      ).toBeInTheDocument();
    });
    // Content must not be shown on failure
    expect(
      screen.queryByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
    ).toBeNull();

    // Collapse by clicking Hide
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(
        screen.queryByTestId('artifact-view-error-bug-001-step-00-setup.stdout.txt'),
      ).toBeNull();
    });

    // Re-expand → triggers retry fetch which succeeds
    act(() => screen.getByTestId('artifact-view-bug-001-step-00-setup.stdout.txt').click());
    await waitFor(() => {
      expect(
        screen.getByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
      ).toBeInTheDocument();
    });
    // Content correct
    expect(
      screen.getByTestId('artifact-content-bug-001-step-00-setup.stdout.txt'),
    ).toHaveTextContent('retry content line');
    // Error div must be gone (stale errorCache was cleared)
    expect(
      screen.queryByTestId('artifact-view-error-bug-001-step-00-setup.stdout.txt'),
    ).toBeNull();
  });

  it('size_bytes > 512KB shows "Download instead" instead of fetching content', async () => {
    const LARGE_ARTIFACT = [
      {
        filename: 'big-stdout.txt',
        size_bytes: 600 * 1024,
        kind: 'stdout',
        step_idx: 0,
        step_id: 'run',
      },
    ];
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone)) // run detail
      .mockResolvedValueOnce(mockJsonResponse(LARGE_ARTIFACT)); // artifacts list (no 3rd call expected)

    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-toggle-bug-001')).toBeInTheDocument();
    });
    act(() => screen.getByTestId('artifacts-toggle-bug-001').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifacts-list-bug-001')).toBeInTheDocument();
    });

    // Click View on the large file
    act(() => screen.getByTestId('artifact-view-bug-001-big-stdout.txt').click());
    await waitFor(() => {
      expect(screen.getByTestId('artifact-too-large-bug-001-big-stdout.txt')).toBeInTheDocument();
    });
    expect(screen.getByTestId('artifact-too-large-bug-001-big-stdout.txt')).toHaveTextContent(
      'Download instead',
    );
    // No content pre rendered
    expect(screen.queryByTestId('artifact-content-bug-001-big-stdout.txt')).toBeNull();

    // No fetch call for the file text — only 2 calls total (run + artifacts list)
    const allCalls = mockFetch.mock.calls;
    const fileTextCalls = allCalls.filter((args: unknown[]) => {
      const url = args[0] as string;
      return typeof url === 'string' && url.includes('/artifacts/big-stdout.txt');
    });
    expect(fileTextCalls).toHaveLength(0);
  });

  // ---- M6-1 finishing touch: progress bar (2026-05-26) -------------------

  it('progress bar renders during running run with partial completion (derived from case_results)', async () => {
    // Post-2026-05-26 fix: progress bar reads case_results.length (not
    // run.passed/failed/skipped/errored — those are NULL during run).
    // Simulate 11 pass + 1 skip = 12 done out of 17 total.
    const partial = {
      ...fakeRunRunning,
      total: 17,
      // run.passed/etc deliberately left at 0 — backend doesn't update
      // them during a running run; only finish_run() writes them.
      case_results: [
        ...Array.from({ length: 11 }, (_, i) => ({
          case_id: `bug-${100 + i}`,
          status: 'pass',
          duration_ms: 100,
          skip_reason: null,
          expect_detail: null,
          artifacts_path: null,
        })),
        {
          case_id: 'bug-skipped',
          status: 'skip',
          duration_ms: 0,
          skip_reason: 'placeholder',
          expect_detail: null,
          artifacts_path: null,
        },
      ],
    };
    mockFetch.mockResolvedValue(mockJsonResponse(partial));
    renderWithRoute('42');
    await waitFor(() => {
      expect(screen.getByTestId('run-progress')).toBeInTheDocument();
    });
    const bar = screen.getByTestId('run-progress-bar') as HTMLProgressElement;
    expect(bar.value).toBe(12); // 11 pass + 1 skip
    expect(bar.max).toBe(17);
    expect(screen.getByTestId('run-progress-counts')).toHaveTextContent('12 / 17 cases (71%)');
  });

  it('progress bar shows ETA only while running with done>0 and pending>0', async () => {
    const ts = new Date(Date.now() - 10_000).toISOString();
    const partial = {
      ...fakeRunRunning,
      started_at: ts,
      total: 17,
      case_results: Array.from({ length: 5 }, (_, i) => ({
        case_id: `bug-${i}`,
        status: 'pass',
        duration_ms: 1000,
        skip_reason: null,
        expect_detail: null,
        artifacts_path: null,
      })),
    };
    mockFetch.mockResolvedValue(mockJsonResponse(partial));
    renderWithRoute('42');
    await waitFor(() => {
      expect(screen.getByTestId('run-progress-eta')).toBeInTheDocument();
    });
    expect(screen.getByTestId('run-progress-eta').textContent).toMatch(/ETA ~\d+[sm]/);
  });

  it('progress bar hides ETA when run is terminal', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunDone));
    renderWithRoute('99');
    await waitFor(() => {
      expect(screen.getByTestId('run-progress')).toBeInTheDocument();
    });
    // Terminal run shows progress (3/3) but no ETA.
    expect(screen.queryByTestId('run-progress-eta')).toBeNull();
    const bar = screen.getByTestId('run-progress-bar') as HTMLProgressElement;
    expect(bar.value).toBe(3);
    expect(bar.max).toBe(3);
  });

  it('progress bar hidden when total is 0 (run not started populating counters)', async () => {
    const empty = { ...fakeRunRunning, total: 0, case_results: [] };
    mockFetch.mockResolvedValue(mockJsonResponse(empty));
    renderWithRoute('42');
    // Status badge present but progress not rendered
    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('run-progress')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// M6-D1 — Re-run buttons (btn-rerun-all / btn-rerun-failed)
// ---------------------------------------------------------------------------

// A run fixture with pass/fail/error/skip results to test the exact wiring.
// This asserts "covers fail/error" claim: only fail+error go into failed URL,
// not pass or skip.
const fakeRunMixed = {
  id: 77,
  status: 'done',
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:05:00Z',
  total: 5,
  passed: 1,
  failed: 2,
  skipped: 1,
  target_version: 'v5.2.0',
  triggered_by: null,
  case_results: [
    { case_id: 'bug-pass', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-fail-1', status: 'fail', duration_ms: 200, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-error-1', status: 'error', duration_ms: 300, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-skip', status: 'skip', duration_ms: 0, skip_reason: 'skipped', expect_detail: null, artifacts_path: null },
    { case_id: 'bug-fail-2', status: 'fail', duration_ms: 150, skip_reason: null, expect_detail: null, artifacts_path: null },
  ],
};

describe('RunDetailPage M6-D1 — Re-run buttons', () => {
  it('btn-rerun-all and btn-rerun-failed are rendered for a terminal run', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunMixed));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('btn-rerun-all')).toBeInTheDocument();
    });
    expect(screen.getByTestId('btn-rerun-failed')).toBeInTheDocument();
  });

  it('Re-run all navigates with ALL case_ids (wiring: every case in run.case_results)', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunMixed));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('btn-rerun-all')).toBeInTheDocument();
    });

    screen.getByTestId('btn-rerun-all').click();

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const url = mockNavigate.mock.calls[0][0] as string;
    const params = new URLSearchParams(url.split('?')[1]);

    const caseIds = params.get('case_ids')!.split(',').sort();
    expect(caseIds).toEqual(
      ['bug-pass', 'bug-fail-1', 'bug-error-1', 'bug-skip', 'bug-fail-2'].sort(),
    );
    expect(params.get('from_run')).toBe('77');
    expect(params.get('target_version')).toBe('v5.2.0');
  });

  it('Re-run failed navigates with EXACTLY fail+error ids (not pass, not skip — covers wiring claim)', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse(fakeRunMixed));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('btn-rerun-failed')).toBeInTheDocument();
    });

    screen.getByTestId('btn-rerun-failed').click();

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const url = mockNavigate.mock.calls[0][0] as string;
    const params = new URLSearchParams(url.split('?')[1]);

    const caseIds = params.get('case_ids')!.split(',').sort();
    // Must contain bug-fail-1, bug-error-1, bug-fail-2 — NOT bug-pass, NOT bug-skip
    expect(caseIds).toEqual(['bug-error-1', 'bug-fail-1', 'bug-fail-2'].sort());
    expect(params.get('from_run')).toBe('77');
    expect(params.get('target_version')).toBe('v5.2.0');
  });

  it('Re-run failed is disabled when there are zero failures', async () => {
    // A run with all-pass results → failedCaseIds is empty
    const allPassRun = {
      ...fakeRunMixed,
      failed: 0,
      case_results: [
        { case_id: 'bug-a', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null },
        { case_id: 'bug-b', status: 'pass', duration_ms: 120, skip_reason: null, expect_detail: null, artifacts_path: null },
      ],
    };
    mockFetch.mockResolvedValueOnce(mockJsonResponse(allPassRun));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('btn-rerun-failed')).toBeInTheDocument();
    });

    const btn = screen.getByTestId('btn-rerun-failed') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    // Should not navigate when disabled
    btn.click();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('Re-run all is not disabled even when no failures', async () => {
    const allPassRun = {
      ...fakeRunMixed,
      failed: 0,
      case_results: [
        { case_id: 'bug-a', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null },
      ],
    };
    mockFetch.mockResolvedValueOnce(mockJsonResponse(allPassRun));
    renderWithRoute('77');
    await waitFor(() => {
      expect(screen.getByTestId('btn-rerun-all')).toBeInTheDocument();
    });
    const btn = screen.getByTestId('btn-rerun-all') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });
});
