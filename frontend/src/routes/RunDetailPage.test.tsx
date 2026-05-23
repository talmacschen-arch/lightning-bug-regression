import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import RunDetailPage from './RunDetailPage';
import type { components } from '@/api/types';

type RunDetail = components['schemas']['RunDetail'];
type CaseResultOut = components['schemas']['CaseResultOut'];

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/api/client';

const mockApiFetch = vi.mocked(apiFetch);

function makeRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 7,
    status: 'running',
    started_at: '2024-02-10T12:00:00Z',
    finished_at: null,
    total: 3,
    passed: 1,
    failed: 1,
    skipped: 1,
    target_version: '6.0.0',
    triggered_by: 'manual',
    case_results: [],
    ...overrides,
  };
}

function makeCaseResult(caseId: string, overrides: Partial<CaseResultOut> = {}): CaseResultOut {
  return {
    case_id: caseId,
    status: 'passed',
    duration_ms: 1234,
    skip_reason: null,
    expect_detail: null,
    artifacts_path: null,
    ...overrides,
  };
}

function renderRunDetailPage(runId = '7') {
  return render(
    <MemoryRouter initialEntries={[`/runs/${runId}`]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RunDetailPage', () => {
  beforeEach(() => {
    mockApiFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows loading skeleton initially', () => {
    // Never resolves during this test
    mockApiFetch.mockReturnValue(new Promise(() => undefined));
    renderRunDetailPage();
    expect(screen.getByTestId('run-detail-loading')).toBeInTheDocument();
  });

  it('renders run summary after successful fetch', async () => {
    const run = makeRunDetail({ status: 'passed' });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('page-run-detail')).toBeInTheDocument();
    });

    expect(screen.getByTestId('run-id')).toHaveTextContent('Run #7');
    expect(screen.getByTestId('run-total')).toHaveTextContent('3');
    expect(screen.getByTestId('run-passed')).toHaveTextContent('1');
    expect(screen.getByTestId('run-failed')).toHaveTextContent('1');
    expect(screen.getByTestId('run-skipped')).toHaveTextContent('1');
  });

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Run not found'));

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('run-detail-error')).toBeInTheDocument();
    });

    expect(screen.getByTestId('run-detail-error')).toHaveTextContent('Run not found');
  });

  it('renders case results list', async () => {
    const caseResults = [
      makeCaseResult('case-001', { status: 'passed', duration_ms: 500 }),
      makeCaseResult('case-002', { status: 'failed', duration_ms: 1200 }),
      makeCaseResult('case-003', {
        status: 'skipped',
        skip_reason: 'not applicable',
      }),
    ];
    const run = makeRunDetail({ status: 'passed', case_results: caseResults });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('case-results-list')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-result-case-001')).toBeInTheDocument();
    expect(screen.getByTestId('case-result-case-002')).toBeInTheDocument();
    expect(screen.getByTestId('case-result-case-003')).toBeInTheDocument();
  });

  it('renders artifacts link when artifacts_path is present', async () => {
    const caseResults = [
      makeCaseResult('case-010', {
        status: 'failed',
        artifacts_path: '/artifacts/case-010/run-7',
      }),
    ];
    const run = makeRunDetail({ status: 'failed', case_results: caseResults });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('artifacts-link-case-010')).toBeInTheDocument();
    });

    expect(screen.getByTestId('artifacts-link-case-010')).toHaveAttribute(
      'href',
      '/artifacts/case-010/run-7',
    );
    expect(screen.getByTestId('artifacts-link-case-010')).toHaveAttribute('target', '_blank');
  });

  it('truncates expect_detail to 200 chars with show more toggle', async () => {
    const longText = 'A'.repeat(300);
    const caseResults = [
      makeCaseResult('case-020', {
        status: 'failed',
        expect_detail: longText,
      }),
    ];
    const run = makeRunDetail({ status: 'failed', case_results: caseResults });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('expect-detail-case-020')).toBeInTheDocument();
    });

    const detailEl = screen.getByTestId('expect-detail-case-020');
    // Should be truncated: 200 chars + '…'
    expect(detailEl.textContent?.length).toBeLessThanOrEqual(201);
    expect(screen.getByTestId('expect-detail-case-020-toggle')).toBeInTheDocument();
  });

  it('shows empty case results state', async () => {
    const run = makeRunDetail({ status: 'running', case_results: [] });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId('case-results-empty')).toBeInTheDocument();
    });
  });

  it('polls every 3s while status is non-terminal', async () => {
    // Use fake timers only for setInterval/clearInterval; keep setTimeout real
    // so that waitFor's internal retry mechanism still works
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });

    const runningRun = makeRunDetail({ status: 'running' });
    mockApiFetch.mockResolvedValue(runningRun);

    renderRunDetailPage();

    // Wait for initial render to complete (real setTimeout still works for waitFor)
    await waitFor(() => {
      expect(screen.getByTestId('page-run-detail')).toBeInTheDocument();
    });

    const callsAfterMount = mockApiFetch.mock.calls.length;
    expect(callsAfterMount).toBe(1);

    // Advance the fake setInterval by 3 seconds to trigger polling
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(mockApiFetch.mock.calls.length).toBeGreaterThan(callsAfterMount);
    });
  });

  it('stops polling once status becomes terminal', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });

    const runningRun = makeRunDetail({ status: 'running' });
    const finishedRun = makeRunDetail({ status: 'passed' });

    // First call (mount) returns running, second call (poll tick) returns passed
    mockApiFetch
      .mockResolvedValueOnce(runningRun)
      .mockResolvedValueOnce(finishedRun);

    renderRunDetailPage();

    // Wait for initial fetch (running)
    await waitFor(() => {
      expect(screen.getByTestId('page-run-detail')).toBeInTheDocument();
    });

    const callsAfterMount = mockApiFetch.mock.calls.length;

    // Advance 3s — interval fires, fetch returns finishedRun → clears interval
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(mockApiFetch.mock.calls.length).toBe(callsAfterMount + 1);
    });

    const callsAfterFirstPoll = mockApiFetch.mock.calls.length;

    // Advance another 3s — interval should have been cleared, no new call
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    // Give any pending microtasks a chance to settle
    await waitFor(() => {
      expect(mockApiFetch.mock.calls.length).toBe(callsAfterFirstPoll);
    });
  });

  it('all fetch calls use the correct run_id path param', async () => {
    const run = makeRunDetail({ status: 'passed' });
    mockApiFetch.mockResolvedValue(run);

    renderRunDetailPage('7');

    await waitFor(() => {
      expect(screen.getByTestId('page-run-detail')).toBeInTheDocument();
    });

    expect(mockApiFetch).toHaveBeenCalledWith('/runs/{run_id}', 'get', {
      pathParams: { run_id: 7 },
    });
  });
});
