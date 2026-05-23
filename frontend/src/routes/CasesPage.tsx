import { useEffect, useState, useCallback } from 'react';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';

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
}

function CasesList({ category, cases }: CasesListProps) {
  if (cases.length === 0) {
    return (
      <div
        data-testid={`cases-empty-${category.name}`}
        className="pt-8 text-center text-sm text-muted-foreground"
      >
        No cases found in this category.
      </div>
    );
  }

  return (
    <div
      data-testid={`cases-list-${category.name}`}
      className="space-y-3 pt-4"
    >
      {cases.map((c) => (
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
  const [categories, setCategories] = useState<CategoryOut[] | null>(null);
  const [activeTab, setActiveTab] = useState<string>('');
  const [catLoading, setCatLoading] = useState(true);
  const [catError, setCatError] = useState<string | null>(null);

  // Per-category fetch state keyed by category name
  const [tabStates, setTabStates] = useState<Record<string, TabPanelState>>({});

  const fetchCasesForCategory = useCallback(
    (categoryName: string) => {
      // Only fetch if not already loading/loaded
      setTabStates((prev) => {
        if (prev[categoryName]?.cases !== null && prev[categoryName]?.cases !== undefined) {
          return prev; // already loaded
        }
        return {
          ...prev,
          [categoryName]: { loading: true, error: null, cases: null },
        };
      });

      apiFetch('/cases', 'get', { query: { category: categoryName } })
        .then((data) => {
          setTabStates((prev) => ({
            ...prev,
            [categoryName]: { loading: false, error: null, cases: data as CaseSummary[] },
          }));
        })
        .catch((err: unknown) => {
          setTabStates((prev) => ({
            ...prev,
            [categoryName]: {
              loading: false,
              error: err instanceof Error ? err.message : String(err),
              cases: null,
            },
          }));
        });
    },
    [],
  );

  const retryCasesForCategory = useCallback(
    (categoryName: string) => {
      setTabStates((prev) => ({
        ...prev,
        [categoryName]: { loading: true, error: null, cases: null },
      }));

      apiFetch('/cases', 'get', { query: { category: categoryName } })
        .then((data) => {
          setTabStates((prev) => ({
            ...prev,
            [categoryName]: { loading: false, error: null, cases: data as CaseSummary[] },
          }));
        })
        .catch((err: unknown) => {
          setTabStates((prev) => ({
            ...prev,
            [categoryName]: {
              loading: false,
              error: err instanceof Error ? err.message : String(err),
              cases: null,
            },
          }));
        });
    },
    [],
  );

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
          fetchCasesForCategory(first);
        }
      })
      .catch((err: unknown) => {
        setCatError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setCatLoading(false);
      });
  }, [fetchCasesForCategory]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const handleTabChange = useCallback(
    (value: string) => {
      setActiveTab(value);
      fetchCasesForCategory(value);
    },
    [fetchCasesForCategory],
  );

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
          const state = tabStates[cat.name];
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
                    onClick={() => retryCasesForCategory(cat.name)}
                    data-testid={`cases-retry-${cat.name}`}
                  >
                    Retry
                  </Button>
                </div>
              ) : (
                <CasesList category={cat} cases={state.cases ?? []} />
              )}
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
