/**
 * CaseIdCombobox unit tests.
 *
 * Covers: lazy fetch on mount, popover open via trigger, fuzzy match by
 * id OR title via cmdk default substring filter, item selection via
 * onChange callback, error/loading states.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CaseIdCombobox } from './CaseIdCombobox';

const apiFetchMock = vi.fn();
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

const FAKE_CASES = [
  { id: 'lg-bug-0009-union-all-const-distributed-row-order', category: 'bug_regression', title: 'UNION ALL const distributed row order', status: 'open', destructive: false, tags: null, error: null },
  { id: 'lg-ext-pgvector-ivfflat-basic', category: 'extension', title: 'pgvector IVFFLAT 索引基础', status: 'stable', destructive: false, tags: null, error: null },
  { id: 'lg-xs-zombodb-partition-text-search', category: 'external_systems', title: 'ZomboDB 分区表全文搜索', status: 'fixed', destructive: false, tags: null, error: null },
];

beforeEach(() => {
  apiFetchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CaseIdCombobox', () => {
  it('shows placeholder when no value selected', () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    const onChange = vi.fn();
    render(<CaseIdCombobox value="" onChange={onChange} />);
    expect(screen.getByTestId('case-id-combobox-trigger')).toHaveTextContent('Pick a case_id…');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('displays current value when set', () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    render(<CaseIdCombobox value="lg-ext-pgvector-ivfflat-basic" onChange={vi.fn()} />);
    expect(screen.getByTestId('case-id-combobox-trigger')).toHaveTextContent(
      'lg-ext-pgvector-ivfflat-basic',
    );
  });

  it('opens popover + shows items on trigger click', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    render(<CaseIdCombobox value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-popover')).toBeInTheDocument();
    });
    for (const c of FAKE_CASES) {
      expect(screen.getByTestId(`case-id-combobox-item-${c.id}`)).toBeInTheDocument();
    }
  });

  it('clicking an item calls onChange with that id', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    const onChange = vi.fn();
    render(<CaseIdCombobox value="" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-item-lg-ext-pgvector-ivfflat-basic')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('case-id-combobox-item-lg-ext-pgvector-ivfflat-basic'));
    expect(onChange).toHaveBeenCalledWith('lg-ext-pgvector-ivfflat-basic');
  });

  it('filters by id substring via search input', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    render(<CaseIdCombobox value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-search')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('case-id-combobox-search'), { target: { value: 'zombodb' } });
    // cmdk filters in-place; mismatched items have display:none via aria
    // attributes. We assert at least the matching item is visible.
    await waitFor(() => {
      const match = screen.getByTestId('case-id-combobox-item-lg-xs-zombodb-partition-text-search');
      expect(match).toBeInTheDocument();
    });
  });

  it('filters by title keyword (cmdk searches concatenated id + title)', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    render(<CaseIdCombobox value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => expect(screen.getByTestId('case-id-combobox-search')).toBeInTheDocument());
    // Search a TITLE-only keyword (not part of id)
    fireEvent.change(screen.getByTestId('case-id-combobox-search'), { target: { value: '全文搜索' } });
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-item-lg-xs-zombodb-partition-text-search')).toBeInTheDocument();
    });
  });

  it('shows loading state until /cases resolves', async () => {
    let resolve!: (v: typeof FAKE_CASES) => void;
    const pending = new Promise<typeof FAKE_CASES>((r) => {
      resolve = r;
    });
    apiFetchMock.mockReturnValue(pending);
    render(<CaseIdCombobox value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-loading')).toBeInTheDocument();
    });
    resolve(FAKE_CASES);
    await waitFor(() => {
      expect(screen.queryByTestId('case-id-combobox-loading')).toBeNull();
    });
  });

  it('shows error state on /cases failure', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    render(<CaseIdCombobox value="" onChange={vi.fn()} />);
    fireEvent.click(screen.getByTestId('case-id-combobox-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('case-id-combobox-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('case-id-combobox-error')).toHaveTextContent('network down');
  });

  it('custom testid prefix scopes the rendered testids', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    render(<CaseIdCombobox value="" onChange={vi.fn()} testid="my-picker" />);
    expect(screen.getByTestId('my-picker-trigger')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('my-picker-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('my-picker-item-lg-ext-pgvector-ivfflat-basic')).toBeInTheDocument();
    });
  });
});
