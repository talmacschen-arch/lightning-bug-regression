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
    { case_id: 'bug-001', status: 'pass', duration_ms: 1000, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-002', status: 'pass', duration_ms: 1100, skip_reason: null, expect_detail: null, artifacts_path: null },
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
    expect(esInstances[0].url).toBe('/runs/42/stream');
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
});
