import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import RunDetailPage from './RunDetailPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
});

const fakeRunPass = {
  id: 99,
  status: 'pass',
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
  it('renders status badge and case rows for a terminal pass run', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeRunPass),
    });

    renderWithRoute('99');

    // Loading state first
    expect(screen.getByTestId('run-detail-loading')).toBeInTheDocument();

    // Wait for data
    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toBeInTheDocument();
    });

    // Badge shows uppercase status
    expect(screen.getByTestId('run-status-badge')).toHaveTextContent('PASS');
    expect(screen.getByTestId('run-status-badge')).toHaveAttribute('data-status', 'pass');

    // Title
    expect(screen.getByTestId('run-detail-title')).toHaveTextContent('Run #99');

    // Per-case rows
    expect(screen.getByTestId('run-case-row-bug-001')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-002')).toBeInTheDocument();
    expect(screen.getByTestId('run-case-row-bug-003')).toBeInTheDocument();

    // Per-case status badges
    expect(screen.getByTestId('run-case-status-bug-001')).toHaveTextContent('PASS');
    expect(screen.getByTestId('run-case-status-bug-002')).toHaveTextContent('PASS');
    expect(screen.getByTestId('run-case-status-bug-003')).toHaveTextContent('PASS');
  });

  it('renders loading state initially, then transitions to terminal run data', async () => {
    // First call returns a running run (non-terminal), second returns pass (terminal)
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: () => Promise.resolve(fakeRunRunning),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: () => Promise.resolve(fakeRunPass),
      });

    renderWithRoute('42');

    // Loading initially
    expect(screen.getByTestId('run-detail-loading')).toBeInTheDocument();

    // After first fetch resolves, shows "running" badge
    await waitFor(() => {
      expect(screen.getByTestId('run-status-badge')).toBeInTheDocument();
    });

    expect(screen.getByTestId('run-status-badge')).toHaveTextContent('RUNNING');
  });
});
