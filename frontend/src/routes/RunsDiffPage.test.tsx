/**
 * RunsDiffPage unit tests (M6-3).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import RunsDiffPage from './RunsDiffPage';

const apiFetchMock = vi.fn();
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

function makeRun(id: number, case_results: object[]) {
  return {
    id,
    status: 'done',
    started_at: '2026-01-01T00:00:00Z',
    finished_at: '2026-01-01T00:01:00Z',
    total: case_results.length,
    passed: 0,
    failed: 0,
    skipped: 0,
    target_version: null,
    triggered_by: null,
    case_results,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/runs/diff" element={<RunsDiffPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RunsDiffPage', () => {
  it('shows empty hint when query params missing', () => {
    renderAt('/runs/diff');
    expect(screen.getByTestId('runs-diff-empty')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('shows empty hint when only one query param', () => {
    renderAt('/runs/diff?a=5');
    expect(screen.getByTestId('runs-diff-empty')).toBeInTheDocument();
  });

  it('shows error state when fetch fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('boom'));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('runs-diff-error')).toBeInTheDocument();
    });
  });

  it('classifies pass_to_fail as regression', async () => {
    const runA = makeRun(1, [
      { case_id: 'c1', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null },
    ]);
    const runB = makeRun(2, [
      { case_id: 'c1', status: 'fail', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null },
    ]);
    apiFetchMock.mockResolvedValueOnce(runA).mockResolvedValueOnce(runB);
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('page-runs-diff')).toBeInTheDocument();
    });
    expect(screen.getByTestId('diff-row-c1')).toBeInTheDocument();
    expect(screen.getByTestId('diff-kind-c1')).toHaveTextContent('Regression');
  });

  it('classifies fail_to_pass as fixed', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeRun(1, [{ case_id: 'c2', status: 'fail', duration_ms: 50, skip_reason: null, expect_detail: null, artifacts_path: null }]))
      .mockResolvedValueOnce(makeRun(2, [{ case_id: 'c2', status: 'pass', duration_ms: 50, skip_reason: null, expect_detail: null, artifacts_path: null }]));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('diff-kind-c2')).toHaveTextContent('Fixed');
    });
  });

  it('classifies new case (only in b)', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeRun(1, []))
      .mockResolvedValueOnce(makeRun(2, [{ case_id: 'c3', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null }]));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('diff-kind-c3')).toHaveTextContent('New case');
    });
  });

  it('classifies removed case (only in a)', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeRun(1, [{ case_id: 'c4', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null }]))
      .mockResolvedValueOnce(makeRun(2, []));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('diff-kind-c4')).toHaveTextContent('Removed');
    });
  });

  it('classifies duration_jump when pass→pass but duration > 1.5×', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeRun(1, [{ case_id: 'c5', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null }]))
      .mockResolvedValueOnce(makeRun(2, [{ case_id: 'c5', status: 'pass', duration_ms: 200, skip_reason: null, expect_detail: null, artifacts_path: null }]));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('diff-kind-c5')).toHaveTextContent('Duration jump');
    });
  });

  it('hides unchanged rows by default; checkbox toggle shows them', async () => {
    apiFetchMock
      .mockResolvedValueOnce(makeRun(1, [{ case_id: 'c-same', status: 'pass', duration_ms: 100, skip_reason: null, expect_detail: null, artifacts_path: null }]))
      .mockResolvedValueOnce(makeRun(2, [{ case_id: 'c-same', status: 'pass', duration_ms: 105, skip_reason: null, expect_detail: null, artifacts_path: null }]));
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('page-runs-diff')).toBeInTheDocument();
    });
    // Hidden by default
    expect(screen.queryByTestId('diff-row-c-same')).toBeNull();
    expect(screen.getByTestId('diff-no-changes')).toBeInTheDocument();

    // Toggle on
    fireEvent.click(screen.getByTestId('diff-show-unchanged'));
    await waitFor(() => {
      expect(screen.getByTestId('diff-row-c-same')).toBeInTheDocument();
    });
    expect(screen.getByTestId('diff-kind-c-same')).toHaveTextContent('Unchanged');
  });

  it('sorts regressions first, then fixes/new/removed/duration_jump', async () => {
    const runA = makeRun(1, [
      { case_id: 'fix-me', status: 'fail', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
      { case_id: 'regress', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
      { case_id: 'gone', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
    ]);
    const runB = makeRun(2, [
      { case_id: 'regress', status: 'fail', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
      { case_id: 'fix-me', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
      { case_id: 'new-c', status: 'pass', duration_ms: 10, skip_reason: null, expect_detail: null, artifacts_path: null },
    ]);
    apiFetchMock.mockResolvedValueOnce(runA).mockResolvedValueOnce(runB);
    renderAt('/runs/diff?a=1&b=2');
    await waitFor(() => {
      expect(screen.getByTestId('diff-table')).toBeInTheDocument();
    });
    const rows = screen.getByTestId('diff-table').querySelectorAll('tbody tr');
    const order = Array.from(rows).map((r) => r.getAttribute('data-testid'));
    expect(order).toEqual([
      'diff-row-regress', // regression (rank 0)
      'diff-row-fix-me', // fixed (rank 1)
      'diff-row-new-c', // new (rank 2)
      'diff-row-gone', // removed (rank 3)
    ]);
  });
});
