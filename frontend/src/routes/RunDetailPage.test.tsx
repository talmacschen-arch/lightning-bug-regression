/**
 * RunDetailPage tests — initial GET + SSE live progress (M6-1).
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import RunDetailPage from './RunDetailPage';

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
    { case_id: 'bug-001', status: 'pass', duration_ms: 1000, skip_reason: null, expect_detail: null, artifacts_path: '/tmp/art/99/bug-001' },
    { case_id: 'bug-002', status: 'pass', duration_ms: 1100, skip_reason: null, expect_detail: null, artifacts_path: '/tmp/art/99/bug-002' },
    { case_id: 'bug-003', status: 'pass', duration_ms: 1050, skip_reason: null, expect_detail: null, artifacts_path: null },
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
    { case_id: 'bug-001', status: 'pass', duration_ms: 500, skip_reason: null, expect_detail: null, artifacts_path: null },
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
    act(() => esInstances[0].__emit({ type: 'run_done', run_id: 42, summary: { total: 3, passed: 3, failed: 0, skipped: 0 } }));

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
      { filename: 'step-00-setup.stdout.txt', size_bytes: 1024, kind: 'stdout', step_idx: 0, step_id: 'setup' },
      { filename: 'step-01-main.stderr.txt', size_bytes: 32, kind: 'stderr', step_idx: 1, step_id: 'main' },
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
    expect(screen.getByTestId('artifact-item-bug-001-step-00-setup.stdout.txt')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-item-bug-001-step-01-main.stderr.txt')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-item-bug-001-summary.json')).toBeInTheDocument();

    // Download links point to backend endpoint
    const dl = screen.getByTestId('artifact-download-bug-001-step-00-setup.stdout.txt');
    expect(dl.tagName).toBe('A');
    expect(dl.getAttribute('href')).toContain('/runs/99/cases/bug-001/artifacts/step-00-setup.stdout.txt');
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
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(fakeRunDone))
      .mockResolvedValueOnce({
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

  // ---- M6-1 finishing touch: progress bar (2026-05-26) -------------------

  it('progress bar renders during running run with partial completion', async () => {
    const partial = {
      ...fakeRunRunning,
      total: 17,
      passed: 11,
      failed: 0,
      skipped: 1,
      errored: 0,
      case_results: [],
    };
    mockFetch.mockResolvedValue(mockJsonResponse(partial));
    renderWithRoute('42');
    await waitFor(() => {
      expect(screen.getByTestId('run-progress')).toBeInTheDocument();
    });
    const bar = screen.getByTestId('run-progress-bar') as HTMLProgressElement;
    expect(bar.value).toBe(12); // 11 pass + 0 fail + 1 skip + 0 error
    expect(bar.max).toBe(17);
    expect(screen.getByTestId('run-progress-counts')).toHaveTextContent('12 / 17 cases (71%)');
  });

  it('progress bar shows ETA only while running with done>0 and pending>0', async () => {
    // started_at = 10s ago, 5 done out of 17 total → avg 2s/case × 12 pending = ~24s ETA
    const ts = new Date(Date.now() - 10_000).toISOString();
    const partial = {
      ...fakeRunRunning,
      started_at: ts,
      total: 17,
      passed: 5,
      failed: 0,
      skipped: 0,
      errored: 0,
      case_results: [],
    };
    mockFetch.mockResolvedValue(mockJsonResponse(partial));
    renderWithRoute('42');
    await waitFor(() => {
      expect(screen.getByTestId('run-progress-eta')).toBeInTheDocument();
    });
    // Don't pin exact value — just assert ETA is shown and uses ~Xs format.
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
