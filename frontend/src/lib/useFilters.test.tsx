/**
 * M5-4 useFilters hook unit tests.
 *
 * Verifies URL-encoded filter state read + write + clear contract.
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { useFilters } from './useFilters';

function withRouter(initial: string) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="*" element={<>{children}</>} />
        </Routes>
      </MemoryRouter>
    );
  };
}

describe('useFilters (M5-4)', () => {
  describe('read from URL', () => {
    it('returns empty filters when URL has no params', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/'),
      });
      expect(result.current.filters.q).toBe('');
      expect(result.current.filters.category).toEqual([]);
      expect(result.current.filters.status).toEqual([]);
      expect(result.current.filters.tag).toEqual([]);
      expect(result.current.filters.since).toBe('all');
    });

    it('parses comma-joined category list', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?category=bug_regression,extension'),
      });
      expect(result.current.filters.category).toEqual([
        'bug_regression',
        'extension',
      ]);
    });

    it('parses q string', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?q=hashjoin'),
      });
      expect(result.current.filters.q).toBe('hashjoin');
    });

    it('parses since (7d / 30d / 90d) and defaults to all', () => {
      for (const v of ['7d', '30d', '90d']) {
        const { result } = renderHook(() => useFilters(), {
          wrapper: withRouter(`/?since=${v}`),
        });
        expect(result.current.filters.since).toBe(v);
      }
      const { result: defaultResult } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?since=garbage'),
      });
      expect(defaultResult.current.filters.since).toBe('all');
    });

    it('handles whitespace + empty items in list params', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?status=open, fixed ,'),
      });
      expect(result.current.filters.status).toEqual(['open', 'fixed']);
    });
  });

  describe('setFilter', () => {
    it('toggles a category list value', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?category=bug_regression'),
      });
      act(() => {
        result.current.setFilter('category', ['bug_regression', 'extension']);
      });
      expect(result.current.filters.category).toEqual([
        'bug_regression',
        'extension',
      ]);
    });

    it('removes key when list set to empty', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?category=bug_regression'),
      });
      act(() => {
        result.current.setFilter('category', []);
      });
      expect(result.current.filters.category).toEqual([]);
    });

    it('sets q to empty string removes the key', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?q=hashjoin'),
      });
      act(() => {
        result.current.setFilter('q', '');
      });
      expect(result.current.filters.q).toBe('');
    });

    it('sets since to "all" removes the key (default)', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?since=7d'),
      });
      act(() => {
        result.current.setFilter('since', 'all');
      });
      expect(result.current.filters.since).toBe('all');
    });
  });

  describe('clear', () => {
    it('removes all filters', () => {
      const { result } = renderHook(() => useFilters(), {
        wrapper: withRouter('/?q=x&category=bug_regression&status=open&since=7d'),
      });
      expect(result.current.filters.q).toBe('x');
      act(() => {
        result.current.clear();
      });
      expect(result.current.filters.q).toBe('');
      expect(result.current.filters.category).toEqual([]);
      expect(result.current.filters.status).toEqual([]);
      expect(result.current.filters.since).toBe('all');
    });
  });
});
