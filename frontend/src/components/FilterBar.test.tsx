/**
 * M5-4 FilterBar unit tests.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { FilterBar } from './FilterBar';
import type { FilterState } from '@/lib/useFilters';

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
  {
    name: 'extension',
    display_name: 'Extension',
    description: null,
    id_prefix: 'lg-ext-',
    dir_path: 'extension',
    status_whitelist: ['stable', 'experimental', 'deprecated', 'stub'],
    default_status: 'stable',
    display_order: 20,
  },
];

const EMPTY_FILTERS: FilterState = {
  q: '',
  category: [],
  status: [],
  tag: [],
  since: 'all',
};

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue(FAKE_CATEGORIES);
});

function renderBar(props: Partial<Parameters<typeof FilterBar>[0]> = {}) {
  const setFilter = vi.fn();
  const clear = vi.fn();
  const utils = render(
    <MemoryRouter>
      <FilterBar
        filters={EMPTY_FILTERS}
        setFilter={setFilter}
        clear={clear}
        {...props}
      />
    </MemoryRouter>,
  );
  return { ...utils, setFilter, clear };
}

describe('FilterBar (M5-4)', () => {
  it('renders search input + categories chips (data-driven, §14 R4b)', async () => {
    renderBar();
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument();
    expect(screen.getByTestId('filter-q')).toBeInTheDocument();
    // Categories load async from API mock
    await waitFor(() => {
      expect(screen.getByTestId('filter-category-bug_regression')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-category-extension')).toBeInTheDocument();
  });

  it('does NOT hardcode category names — extra category renders automatically', async () => {
    apiFetchMock.mockResolvedValue([
      ...FAKE_CATEGORIES,
      {
        name: 'external_systems',
        display_name: '外部系统',
        description: null,
        id_prefix: 'lg-xs-',
        dir_path: 'external-systems',
        status_whitelist: ['stable', 'awaiting_env', 'deprecated', 'stub'],
        default_status: 'awaiting_env',
        display_order: 30,
      },
    ]);
    renderBar();
    await waitFor(() => {
      expect(screen.getByTestId('filter-category-external_systems')).toBeInTheDocument();
    });
  });

  it('toggles category on chip click via setFilter', async () => {
    const { setFilter } = renderBar();
    await waitFor(() => {
      expect(screen.getByTestId('filter-category-bug_regression')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('filter-category-bug_regression'));
    expect(setFilter).toHaveBeenCalledWith('category', ['bug_regression']);
  });

  it('shows status options from union of selected categories', async () => {
    renderBar({
      filters: { ...EMPTY_FILTERS, category: ['bug_regression'] },
    });
    await waitFor(() => {
      expect(screen.getByTestId('filter-status-open')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-status-fixed')).toBeInTheDocument();
    // Extension-only status should NOT show when bug_regression alone selected
    expect(screen.queryByTestId('filter-status-stable')).toBeNull();
  });

  it('shows union of all category statuses when no category selected', async () => {
    renderBar();
    await waitFor(() => {
      // Both categories' statuses present
      expect(screen.getByTestId('filter-status-open')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-status-stable')).toBeInTheDocument();
  });

  it('uses explicit statusOptions prop when provided (override)', async () => {
    renderBar({ statusOptions: ['pass', 'fail', 'running'] });
    await waitFor(() => {
      expect(screen.getByTestId('filter-status-pass')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-status-fail')).toBeInTheDocument();
    // Category-based status should NOT show
    expect(screen.queryByTestId('filter-status-open')).toBeNull();
  });

  it('shows since filter when showSinceFilter=true', async () => {
    renderBar({ showSinceFilter: true });
    await waitFor(() => {
      expect(screen.getByTestId('filter-since-7d')).toBeInTheDocument();
    });
    expect(screen.getByTestId('filter-since-all')).toBeInTheDocument();
  });

  it('hides since filter by default (showSinceFilter undefined/false)', async () => {
    renderBar();
    await waitFor(() => {
      expect(screen.getByTestId('filter-category-bug_regression')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('filter-since-7d')).toBeNull();
  });

  it('shows Clear filters button only when filters non-empty', async () => {
    const { rerender, setFilter, clear } = renderBar();
    await waitFor(() => {
      expect(screen.getByTestId('filter-category-bug_regression')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('filter-clear')).toBeNull();

    rerender(
      <MemoryRouter>
        <FilterBar
          filters={{ ...EMPTY_FILTERS, q: 'foo' }}
          setFilter={setFilter}
          clear={clear}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('filter-clear')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('filter-clear'));
    expect(clear).toHaveBeenCalled();
  });

  it('updates q via input change', async () => {
    const { setFilter } = renderBar();
    const input = screen.getByTestId('filter-q') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hashjoin' } });
    expect(setFilter).toHaveBeenCalledWith('q', 'hashjoin');
  });
});
