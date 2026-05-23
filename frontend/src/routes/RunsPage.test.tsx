import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RunsPage from './RunsPage';
import type { components } from '@/api/types';

type RunSummary = components['schemas']['RunSummary'];

// Mock the apiFetch module
vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/api/client';

const mockApiFetch = vi.mocked(apiFetch);

function makeRun(id: number, overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id,
    status: 'passed',
    started_at: '2024-01-15T10:00:00Z',
    finished_at: '2024-01-15T10:05:00Z',
    total: 5,
    passed: 5,
    failed: 0,
    skipped: 0,
    target_version: '5.1.0',
    triggered_by: 'ci',
    ...overrides,
  };
}

function renderRunsPage(initialPath = '/runs') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <RunsPage />
    </MemoryRouter>,
  );
}

describe('RunsPage', () => {
  beforeEach(() => {
    mockApiFetch.mockReset();
  });

  it('shows loading skeleton while fetching', () => {
    // Never resolves
    mockApiFetch.mockReturnValue(new Promise(() => undefined));
    renderRunsPage();
    expect(screen.getByTestId('runs-loading')).toBeInTheDocument();
  });

  it('renders a table of runs after successful fetch', async () => {
    const runs = [makeRun(1), makeRun(2), makeRun(3)];
    mockApiFetch.mockResolvedValueOnce(runs);

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('run-row-1')).toBeInTheDocument();
    });

    expect(screen.getByTestId('run-row-2')).toBeInTheDocument();
    expect(screen.getByTestId('run-row-3')).toBeInTheDocument();
  });

  it('shows empty state when no runs returned', async () => {
    mockApiFetch.mockResolvedValueOnce([]);

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('runs-empty')).toBeInTheDocument();
    });
  });

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'));

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('runs-error')).toBeInTheDocument();
    });

    expect(screen.getByTestId('runs-error')).toHaveTextContent('Network error');
  });

  it('each run row links to /runs/:id', async () => {
    const runs = [makeRun(42)];
    mockApiFetch.mockResolvedValueOnce(runs);

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('run-row-42')).toBeInTheDocument();
    });

    const link = screen.getByTestId('run-row-42');
    expect(link).toHaveAttribute('href', '/runs/42');
  });

  it('shows Load more button when list length equals the limit (not reached end)', async () => {
    // 50 runs = exactly the initial limit → backend may have more
    const runs = Array.from({ length: 50 }, (_, i) => makeRun(i + 1));
    mockApiFetch.mockResolvedValueOnce(runs);

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('btn-load-more')).toBeInTheDocument();
    });
  });

  it('hides Load more button when last fetch returned fewer than limit', async () => {
    // Only 10 runs returned → reached the end
    const runs = Array.from({ length: 10 }, (_, i) => makeRun(i + 1));
    mockApiFetch.mockResolvedValueOnce(runs);

    renderRunsPage();

    await waitFor(() => {
      // Table rows are present
      expect(screen.getByTestId('run-row-1')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('btn-load-more')).not.toBeInTheDocument();
  });

  it('Load more button increments limit and refetches', async () => {
    // First fetch: exactly 50 runs
    const firstBatch = Array.from({ length: 50 }, (_, i) => makeRun(i + 1));
    // Second fetch: 60 runs (limit=100, got 60 → end)
    const secondBatch = Array.from({ length: 60 }, (_, i) => makeRun(i + 1));

    mockApiFetch.mockResolvedValueOnce(firstBatch).mockResolvedValueOnce(secondBatch);

    renderRunsPage();

    // Wait for first load
    await waitFor(() => {
      expect(screen.getByTestId('btn-load-more')).toBeInTheDocument();
    });

    // First call should have limit=50
    expect(mockApiFetch).toHaveBeenNthCalledWith(1, '/runs', 'get', { query: { limit: 50 } });

    // Click load more
    fireEvent.click(screen.getByTestId('btn-load-more'));

    // Second call should have limit=100
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenNthCalledWith(2, '/runs', 'get', { query: { limit: 100 } });
    });

    // After second fetch with 60 < 100, load more button disappears
    await waitFor(() => {
      expect(screen.queryByTestId('btn-load-more')).not.toBeInTheDocument();
    });
  });

  it('displays run status badges', async () => {
    const runs = [makeRun(1, { status: 'failed' })];
    mockApiFetch.mockResolvedValueOnce(runs);

    renderRunsPage();

    await waitFor(() => {
      expect(screen.getByTestId('status-badge-failed')).toBeInTheDocument();
    });
  });
});
