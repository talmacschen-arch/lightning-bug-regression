/**
 * M5-4 — `useFilters` hook: URL-persistent global filter state.
 *
 * Provides a get/set pair backed by `react-router-dom` useSearchParams.
 * Filter state is encoded as URL query params so:
 *   - browser refresh preserves filters
 *   - shared link gives someone else the same filtered view
 *   - back/forward navigation works as expected
 *
 * Supported filter fields (all optional):
 *   - q: string (free-text search)
 *   - category: string[] (multi-select category names)
 *   - status: string[] (multi-select status names)
 *   - tag: string[] (multi-select tags)
 *   - since: string ('7d' / '30d' / '90d' / 'all'; default 'all')
 *   - case_id: string ("which runs touched this case", RunsPage post-M6 UX)
 *
 * URL encoding: each list is comma-joined (e.g. `?category=bug_regression,extension`).
 * Empty list / empty string means "not filtered" and is omitted from URL.
 *
 * §14 R4b: this hook DOES NOT enumerate categories or statuses — it just
 * passes whatever strings the caller supplies. The caller (FilterBar) is
 * responsible for getting the option lists from /admin/categories etc.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export interface FilterState {
  q: string;
  category: string[];
  status: string[];
  tag: string[];
  since: string; // '7d' | '30d' | '90d' | 'all'
  case_id: string;
}

const EMPTY: FilterState = {
  q: '',
  category: [],
  status: [],
  tag: [],
  since: 'all',
  case_id: '',
};

function readList(params: URLSearchParams, key: string): string[] {
  const raw = params.get(key);
  if (!raw) return [];
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function readSince(params: URLSearchParams): string {
  const v = params.get('since');
  if (v === '7d' || v === '30d' || v === '90d') return v;
  return 'all';
}

function writeList(params: URLSearchParams, key: string, list: string[]): void {
  if (list.length === 0) {
    params.delete(key);
  } else {
    params.set(key, list.join(','));
  }
}

export interface UseFiltersResult {
  filters: FilterState;
  setFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  clear: () => void;
}

export function useFilters(): UseFiltersResult {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<FilterState>(
    () => ({
      q: params.get('q') ?? '',
      category: readList(params, 'category'),
      status: readList(params, 'status'),
      tag: readList(params, 'tag'),
      since: readSince(params),
      case_id: params.get('case_id') ?? '',
    }),
    [params],
  );

  const setFilter = useCallback(
    <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
      const next = new URLSearchParams(params);
      if (key === 'q' || key === 'case_id') {
        const v = value as string;
        if (v) next.set(key, v);
        else next.delete(key);
      } else if (key === 'since') {
        const v = value as string;
        if (v && v !== 'all') next.set('since', v);
        else next.delete('since');
      } else {
        writeList(next, key, value as string[]);
      }
      setParams(next, { replace: false });
    },
    [params, setParams],
  );

  const clear = useCallback(() => {
    setParams(new URLSearchParams(), { replace: false });
  }, [setParams]);

  return { filters, setFilter, clear };
}

export { EMPTY as EMPTY_FILTERS };
