/**
 * M5-4 — FilterBar global filter component.
 *
 * Used by /cases and /runs to provide consistent filtering UI:
 *   - q: free-text search
 *   - category: multi-select chips (data-driven from /admin/categories)
 *   - status: multi-select chips (derived from selected categories'
 *     status_whitelist, OR a custom list for runs page)
 *   - since: time range (7d / 30d / 90d / all)
 *
 * Filter state is owned by the parent page via useFilters() hook (URL
 * persistent). FilterBar is a controlled component — render-only over
 * the state passed via props.
 *
 * §14 R4b: category options come from props (parent fetches API), NOT
 * hardcoded inside FilterBar.
 */
import { useEffect, useState } from 'react';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import type { FilterState } from '@/lib/useFilters';

type CategoryOut = components['schemas']['CategoryOut'];

interface FilterBarProps {
  filters: FilterState;
  setFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  clear: () => void;
  /**
   * Status options to show. If omitted, derived from selected categories'
   * status_whitelist (union across selections); if no category selected,
   * shows union of all categories' status_whitelist.
   */
  statusOptions?: string[];
  /**
   * Whether to show the time-range filter (relevant for /runs, not /cases).
   */
  showSinceFilter?: boolean;
  /**
   * Whether to show the category chips. Default true (CasesPage uses them
   * as the primary axis). RunsPage doesn't apply category to its filter
   * logic — runs don't carry a category directly — so it sets this to
   * false to avoid rendering chips that look interactive but no-op.
   */
  showCategoryFilter?: boolean;
  /**
   * Placeholder text for the search input. Must reflect what the consuming
   * page ACTUALLY searches in its filter logic. Default is the case-page
   * shape ("id / title / tags"); /runs which doesn't have title/tags
   * should override (it searches id / status / version / triggered_by).
   * Honest placeholder = no user confusion when typed terms don't match.
   */
  qPlaceholder?: string;
}

function toggleInList(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function FilterBar({
  filters,
  setFilter,
  clear,
  statusOptions,
  showSinceFilter = false,
  showCategoryFilter = true,
  qPlaceholder = 'Search id / title / tags…',
}: FilterBarProps) {
  const [categories, setCategories] = useState<CategoryOut[]>([]);

  // Fetch categories once for the multi-select chips.
  useEffect(() => {
    let cancelled = false;
    apiFetch('/admin/categories', 'get')
      .then((data) => {
        if (cancelled) return;
        const cats = (data as CategoryOut[])
          .slice()
          .sort((a, b) => a.display_order - b.display_order);
        setCategories(cats);
      })
      .catch(() => {
        // silently fail; FilterBar shows empty category list
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Compute status options if not provided.
  const computedStatusOptions =
    statusOptions ??
    (() => {
      const seen = new Set<string>();
      const target =
        filters.category.length > 0
          ? categories.filter((c) => filters.category.includes(c.name))
          : categories;
      for (const cat of target) {
        for (const s of cat.status_whitelist) seen.add(s);
      }
      return Array.from(seen).sort();
    })();

  const hasAnyFilter =
    filters.q !== '' ||
    filters.category.length > 0 ||
    filters.status.length > 0 ||
    filters.tag.length > 0 ||
    filters.since !== 'all';

  return (
    <div data-testid="filter-bar" className="filter-bar">
      <input
        type="text"
        data-testid="filter-q"
        className="filter-q-input"
        placeholder={qPlaceholder}
        value={filters.q}
        onChange={(e) => setFilter('q', e.target.value)}
      />

      {showCategoryFilter && (
        <div data-testid="filter-categories" className="filter-chip-row">
          <span className="filter-label">Category:</span>
          {categories.map((cat) => (
            <button
              key={cat.name}
              type="button"
              data-testid={`filter-category-${cat.name}`}
              className={
                filters.category.includes(cat.name)
                  ? 'filter-chip filter-chip--active'
                  : 'filter-chip'
              }
              onClick={() =>
                setFilter('category', toggleInList(filters.category, cat.name))
              }
            >
              {cat.display_name}
            </button>
          ))}
        </div>
      )}

      {computedStatusOptions.length > 0 && (
        <div data-testid="filter-statuses" className="filter-chip-row">
          <span className="filter-label">Status:</span>
          {computedStatusOptions.map((status) => (
            <button
              key={status}
              type="button"
              data-testid={`filter-status-${status}`}
              className={
                filters.status.includes(status)
                  ? 'filter-chip filter-chip--active'
                  : 'filter-chip'
              }
              onClick={() =>
                setFilter('status', toggleInList(filters.status, status))
              }
            >
              {status}
            </button>
          ))}
        </div>
      )}

      {showSinceFilter && (
        <div data-testid="filter-since" className="filter-chip-row">
          <span className="filter-label">Since:</span>
          {['7d', '30d', '90d', 'all'].map((opt) => (
            <button
              key={opt}
              type="button"
              data-testid={`filter-since-${opt}`}
              className={
                filters.since === opt ? 'filter-chip filter-chip--active' : 'filter-chip'
              }
              onClick={() => setFilter('since', opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {hasAnyFilter && (
        <button
          type="button"
          data-testid="filter-clear"
          className="filter-clear-btn"
          onClick={clear}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
