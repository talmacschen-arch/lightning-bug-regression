import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { useFilters } from '@/lib/useFilters';

type CategoryOut = components['schemas']['CategoryOut'];
type CaseSummary = components['schemas']['CaseSummary'];

// Derive a badge variant from the position of a status in the category's
// status_whitelist. This is intentionally data-driven — no literal string
// comparison against status names (§14 R4b).
function statusVariant(
  status: string,
  category: CategoryOut,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  const idx = category.status_whitelist.indexOf(status);
  if (idx === -1) return 'outline'; // unknown / not in whitelist
  // Map position to a fixed palette. The exact visual is less important than
  // the rule: colour is derived from the category config, never from the
  // status string itself.
  const palette: ('default' | 'secondary' | 'destructive' | 'outline')[] = [
    'default',
    'secondary',
    'destructive',
    'outline',
  ];
  return palette[idx % palette.length];
}

// ---- cases list for one category -------------------------------------------

interface CasesListProps {
  category: CategoryOut;
  cases: CaseSummary[];
  /** Currently selected status filters (client-side OR multi-select) */
  selectedStatuses: string[];
  onStatusToggle: (status: string) => void;
  /** Currently selected tag filters (client-side OR multi-select) */
  selectedTags: string[];
  /** All available tags for this category's loaded cases */
  availableTags: string[];
  onTagToggle: (tag: string) => void;
  /** The current search query, for the empty state message */
  q: string;
}

function CasesList({
  category,
  cases,
  selectedStatuses,
  onStatusToggle,
  selectedTags,
  availableTags,
  onTagToggle,
  q,
}: CasesListProps) {
  // Status options actually present in this category's loaded cases, ordered
  // by the category's status_whitelist. Data-driven (§14 R4b): status names
  // like "open" come from the category config, never hardcoded here.
  const availableStatuses = useMemo(() => {
    const present = new Set(cases.map((c) => c.status));
    return category.status_whitelist.filter((s) => present.has(s));
  }, [cases, category.status_whitelist]);

  // Client-side status filter (OR across selected), then tag filter (OR across
  // selected). The two dimensions compose with AND, both after the server q.
  const afterStatus =
    selectedStatuses.length === 0
      ? cases
      : cases.filter((c) => selectedStatuses.includes(c.status));
  const filtered =
    selectedTags.length === 0
      ? afterStatus
      : afterStatus.filter(
          (c) =>
            c.tags !== null &&
            c.tags !== undefined &&
            c.tags.some((t) => selectedTags.includes(t)),
        );

  const isEmpty = filtered.length === 0;

  // Build empty message
  let emptyMsg = 'No cases found in this category.';
  if (q || selectedStatuses.length > 0 || selectedTags.length > 0) {
    const parts: string[] = [];
    if (q) parts.push(`"${q}"`);
    if (selectedStatuses.length > 0) parts.push(`status: ${selectedStatuses.join(', ')}`);
    if (selectedTags.length > 0) parts.push(`tags: ${selectedTags.join(', ')}`);
    emptyMsg = `No cases match ${parts.join(' + ')}`;
  }

  return (
    <div>
      {/* Status chips — rendered only when the loaded cases carry ≥1 status */}
      {availableStatuses.length > 0 && (
        <div
          data-testid={`cases-status-filters-${category.name}`}
          className="mt-4 flex flex-wrap items-center gap-1"
        >
          <span className="mr-1 text-xs text-muted-foreground">Status:</span>
          {availableStatuses.map((status) => (
            <button
              key={status}
              type="button"
              data-testid={`cases-status-filter-${status}`}
              onClick={() => onStatusToggle(status)}
              className={[
                'inline-flex items-center rounded-sm px-2 py-0.5 text-xs transition-colors',
                selectedStatuses.includes(status)
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80',
              ].join(' ')}
            >
              {status}
            </button>
          ))}
        </div>
      )}

      {/* Tag chips — rendered only when there are tags available */}
      {availableTags.length > 0 && (
        <div
          data-testid={`cases-tag-filters-${category.name}`}
          className="mt-2 flex flex-wrap items-center gap-1"
        >
          <span className="mr-1 text-xs text-muted-foreground">Tags:</span>
          {availableTags.map((tag) => (
            <button
              key={tag}
              type="button"
              data-testid={`cases-tag-filter-${tag}`}
              onClick={() => onTagToggle(tag)}
              className={[
                'inline-flex items-center rounded-sm px-2 py-0.5 text-xs transition-colors',
                selectedTags.includes(tag)
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80',
              ].join(' ')}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      {isEmpty ? (
        <div
          data-testid="cases-search-empty"
          className="pt-8 text-center text-sm text-muted-foreground"
        >
          {emptyMsg}
        </div>
      ) : (
        <div
          data-testid={`cases-list-${category.name}`}
          className="space-y-3 pt-4"
        >
          {filtered.map((c) => (
            <Card key={c.id} data-testid={`case-card-${c.id}`}>
              <CardContent className="pt-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        data-testid={`case-id-${c.id}`}
                        className="text-xs font-mono text-muted-foreground"
                      >
                        {c.id}
                      </span>
                      <Badge
                        variant={statusVariant(c.status, category)}
                        data-testid={`case-status-${c.id}`}
                      >
                        {c.status}
                      </Badge>
                    </div>
                    {c.title !== null && c.title !== undefined && (
                      <p
                        data-testid={`case-title-${c.id}`}
                        className="mt-1 text-sm font-medium truncate"
                      >
                        {c.title}
                      </p>
                    )}
                    {c.tags !== null && c.tags !== undefined && c.tags.length > 0 && (
                      <div
                        data-testid={`case-tags-${c.id}`}
                        className="mt-2 flex flex-wrap gap-1"
                      >
                        {c.tags.map((tag) => (
                          <span
                            key={tag}
                            className="inline-flex items-center rounded-sm bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {/* Latest run result placeholder — to be filled by M2-8 detail */}
                  <div
                    data-testid={`case-latest-run-${c.id}`}
                    className="text-xs text-muted-foreground shrink-0"
                  />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- per-tab content panel -------------------------------------------------

interface TabPanelState {
  loading: boolean;
  error: string | null;
  cases: CaseSummary[] | null;
}

// ---- page ------------------------------------------------------------------

export default function CasesPage() {
  const { filters, setFilter } = useFilters();

  // Local input value (debounced before writing to URL via setFilter)
  const [inputQ, setInputQ] = useState(filters.q);

  // Keep inputQ in sync when `filters.q` changes externally (e.g. browser
  // back/forward navigation). Use a ref to detect "external" changes only.
  const prevUrlQ = useRef(filters.q);
  useEffect(() => {
    if (filters.q !== prevUrlQ.current) {
      setInputQ(filters.q);
      prevUrlQ.current = filters.q;
    }
  }, [filters.q]);

  // Debounce: after 300ms of no typing, push inputQ to URL
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleInputChange = useCallback(
    (value: string) => {
      setInputQ(value);
      if (debounceRef.current !== null) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        prevUrlQ.current = value;
        setFilter('q', value);
      }, 300);
    },
    [setFilter],
  );

  // The "committed" q used for server requests is always filters.q (URL-synced)
  const serverQ = filters.q;

  const [categories, setCategories] = useState<CategoryOut[] | null>(null);
  const [activeTab, setActiveTab] = useState<string>('');
  const [catLoading, setCatLoading] = useState(true);
  const [catError, setCatError] = useState<string | null>(null);

  // Per-category+q fetch state keyed by "${categoryName}::${q}"
  // q participates in the cache key so that changing q invalidates loaded
  // data and triggers a re-fetch (design: §M6-D4).
  const [tabStates, setTabStates] = useState<Record<string, TabPanelState>>({});

  // Mirror tabStates in a ref for synchronous cache-hit checks inside
  // fetchCasesForCategory. setTabStates is async-batched, so we cannot
  // use prev inside the updater to gate the apiFetch call — the fetch
  // would already have been issued before React processes the updater.
  const tabStatesRef = useRef<Record<string, TabPanelState>>({});
  // Keep ref in sync whenever state updates.
  useEffect(() => {
    tabStatesRef.current = tabStates;
  });

  // Client-side status + tag selection state (per-tab, OR multi-select)
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // Reset status/tag selection when the active tab or server q changes
  useEffect(() => {
    setSelectedStatuses([]);
    setSelectedTags([]);
  }, [activeTab, serverQ]);

  const cacheKey = useCallback(
    (categoryName: string, q: string) => `${categoryName}::${q}`,
    [],
  );

  const fetchCasesForCategory = useCallback(
    (categoryName: string, q: string) => {
      const key = `${categoryName}::${q}`;
      // Synchronous cache-hit check via ref — skip fetch if already loaded.
      const cached = tabStatesRef.current[key];
      if (cached?.cases !== null && cached?.cases !== undefined) {
        return; // already loaded for this category+q combo
      }

      // Mark as loading immediately so the UI shows the spinner.
      setTabStates((prev) => ({
        ...prev,
        [key]: { loading: true, error: null, cases: null },
      }));
      // Also update ref synchronously so rapid double-calls don't double-fetch.
      tabStatesRef.current = {
        ...tabStatesRef.current,
        [key]: { loading: true, error: null, cases: null },
      };

      const query: Record<string, string> = { category: categoryName };
      if (q) query.q = q;

      apiFetch('/cases', 'get', { query })
        .then((data) => {
          const loaded: TabPanelState = { loading: false, error: null, cases: data as CaseSummary[] };
          setTabStates((prev) => ({ ...prev, [key]: loaded }));
          tabStatesRef.current = { ...tabStatesRef.current, [key]: loaded };
        })
        .catch((err: unknown) => {
          const errState: TabPanelState = {
            loading: false,
            error: err instanceof Error ? err.message : String(err),
            cases: null,
          };
          setTabStates((prev) => ({ ...prev, [key]: errState }));
          tabStatesRef.current = { ...tabStatesRef.current, [key]: errState };
        });
    },
    [],
  );

  const retryCasesForCategory = useCallback(
    (categoryName: string, q: string) => {
      const key = `${categoryName}::${q}`;
      const errState0: TabPanelState = { loading: true, error: null, cases: null };
      setTabStates((prev) => ({ ...prev, [key]: errState0 }));
      tabStatesRef.current = { ...tabStatesRef.current, [key]: errState0 };

      const query: Record<string, string> = { category: categoryName };
      if (q) query.q = q;

      apiFetch('/cases', 'get', { query })
        .then((data) => {
          const loaded: TabPanelState = { loading: false, error: null, cases: data as CaseSummary[] };
          setTabStates((prev) => ({ ...prev, [key]: loaded }));
          tabStatesRef.current = { ...tabStatesRef.current, [key]: loaded };
        })
        .catch((err: unknown) => {
          const errState: TabPanelState = {
            loading: false,
            error: err instanceof Error ? err.message : String(err),
            cases: null,
          };
          setTabStates((prev) => ({ ...prev, [key]: errState }));
          tabStatesRef.current = { ...tabStatesRef.current, [key]: errState };
        });
    },
    [],
  );

  // Re-fetch active tab whenever serverQ changes (and we have a tab selected)
  useEffect(() => {
    if (activeTab) {
      fetchCasesForCategory(activeTab, serverQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverQ]);

  const fetchCategories = useCallback(() => {
    setCatLoading(true);
    setCatError(null);
    apiFetch('/admin/categories', 'get')
      .then((data) => {
        const cats = (data as CategoryOut[]).slice().sort(
          (a, b) => a.display_order - b.display_order,
        );
        setCategories(cats);
        if (cats.length > 0) {
          const first = cats[0].name;
          setActiveTab(first);
          fetchCasesForCategory(first, serverQ);
        }
      })
      .catch((err: unknown) => {
        setCatError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setCatLoading(false);
      });
    // fetchCasesForCategory is stable (no deps that change); serverQ is read
    // at call time and passed explicitly — no need to re-run fetchCategories
    // when serverQ changes (the serverQ effect above handles tab re-fetch).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchCasesForCategory]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const handleTabChange = useCallback(
    (value: string) => {
      setActiveTab(value);
      fetchCasesForCategory(value, serverQ);
    },
    [fetchCasesForCategory, serverQ],
  );

  // Collect unique tags for the current tab's loaded cases (for the chip bar)
  const activeState = activeTab ? tabStates[cacheKey(activeTab, serverQ)] : undefined;
  const availableTags = useMemo(() => {
    const cases = activeState?.cases ?? [];
    const seen = new Set<string>();
    for (const c of cases) {
      if (c.tags) {
        for (const t of c.tags) seen.add(t);
      }
    }
    return Array.from(seen).sort();
  }, [activeState]);

  const handleStatusToggle = useCallback((status: string) => {
    setSelectedStatuses((prev) =>
      prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status],
    );
  }, []);

  const handleTagToggle = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }, []);

  if (catLoading) {
    return (
      <div data-testid="page-cases" className="p-6 space-y-4">
        <Skeleton
          data-testid="categories-loading"
          className="h-10 w-64"
        />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (catError !== null) {
    return (
      <div data-testid="page-cases" className="p-6 flex flex-col gap-4">
        <p
          data-testid="categories-error"
          className="text-sm text-destructive"
        >
          Failed to load categories: {catError}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchCategories}
          data-testid="categories-retry"
        >
          Retry
        </Button>
      </div>
    );
  }

  if (categories === null || categories.length === 0) {
    return (
      <div data-testid="page-cases" className="p-6">
        <p
          data-testid="categories-empty"
          className="text-sm text-muted-foreground"
        >
          No categories configured.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="page-cases" className="p-6">
      <div
        data-testid="cases-page-header"
        className="flex items-center justify-between mb-4"
      >
        <h1 className="text-xl font-semibold">Cases</h1>
        <Button asChild size="sm" data-testid="cases-page-new-case">
          <Link to="/cases/new">+ New Case</Link>
        </Button>
      </div>

      {/* Search input — debounced ~300ms, synced to URL ?q= */}
      <div className="mb-4">
        <input
          type="search"
          data-testid="cases-search-input"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="Search cases by id, title, description, tags…"
          value={inputQ}
          onChange={(e) => handleInputChange(e.target.value)}
        />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={handleTabChange}
        data-testid="categories-tabs"
      >
        <TabsList data-testid="categories-tablist">
          {categories.map((cat) => (
            <TabsTrigger
              key={cat.name}
              value={cat.name}
              data-testid={`tab-${cat.name}`}
            >
              {cat.display_name}
            </TabsTrigger>
          ))}
        </TabsList>
        {categories.map((cat) => {
          const key = cacheKey(cat.name, serverQ);
          const state = tabStates[key];
          return (
            <TabsContent key={cat.name} value={cat.name}>
              {state === undefined || state.loading ? (
                <div
                  data-testid={`cases-loading-${cat.name}`}
                  className="space-y-3 pt-4"
                >
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : state.error !== null ? (
                <div
                  data-testid={`cases-error-${cat.name}`}
                  className="pt-4 flex flex-col items-start gap-3"
                >
                  <p className="text-sm text-destructive">
                    Failed to load cases: {state.error}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => retryCasesForCategory(cat.name, serverQ)}
                    data-testid={`cases-retry-${cat.name}`}
                  >
                    Retry
                  </Button>
                </div>
              ) : (
                <CasesList
                  category={cat}
                  cases={state.cases ?? []}
                  selectedStatuses={cat.name === activeTab ? selectedStatuses : []}
                  onStatusToggle={handleStatusToggle}
                  selectedTags={cat.name === activeTab ? selectedTags : []}
                  availableTags={cat.name === activeTab ? availableTags : []}
                  onTagToggle={handleTagToggle}
                  q={serverQ}
                />
              )}
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
