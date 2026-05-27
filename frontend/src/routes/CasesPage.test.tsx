import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
} from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CasesPage from './CasesPage';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const CATEGORIES = [
  {
    name: 'cat_alpha',
    display_name: 'Alpha',
    description: null,
    id_prefix: 'ALPHA',
    dir_path: 'cases/alpha',
    status_whitelist: ['active', 'draft', 'deprecated'],
    default_status: 'active',
    display_order: 1,
  },
  {
    name: 'cat_beta',
    display_name: 'Beta',
    description: null,
    id_prefix: 'BETA',
    dir_path: 'cases/beta',
    status_whitelist: ['active', 'inactive'],
    default_status: 'active',
    display_order: 2,
  },
];

const CASES_ALPHA = [
  {
    id: 'ALPHA-001',
    category: 'cat_alpha',
    title: 'First alpha case',
    status: 'active',
    destructive: false,
    tags: ['smoke', 'fast'],
    error: null,
  },
  {
    id: 'ALPHA-002',
    category: 'cat_alpha',
    title: 'Second alpha case',
    status: 'draft',
    destructive: false,
    tags: [],
    error: null,
  },
];

const CASES_BETA = [
  {
    id: 'BETA-001',
    category: 'cat_beta',
    title: 'First beta case',
    status: 'inactive',
    destructive: false,
    tags: ['regression'],
    error: null,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setupFetch(
  categoriesPayload: unknown = CATEGORIES,
  casesPayload: unknown = CASES_ALPHA,
) {
  const spy = vi.spyOn(global, 'fetch').mockImplementation(
    (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes('/admin/categories')) {
        return Promise.resolve(makeJsonResponse(categoriesPayload));
      }
      if (url.includes('/cases')) {
        // Return per-category payload based on query string
        if (url.includes('category=cat_beta')) {
          return Promise.resolve(makeJsonResponse(CASES_BETA));
        }
        return Promise.resolve(makeJsonResponse(casesPayload));
      }
      return Promise.resolve(makeJsonResponse({}));
    },
  );
  return spy;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CasesPage', () => {
  let fetchSpy: ReturnType<typeof setupFetch>;

  beforeEach(() => {
    fetchSpy = setupFetch();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  // -------------------------------------------------------------------------
  // Existing tests (preserved)
  // -------------------------------------------------------------------------

  it('shows loading skeleton while categories are being fetched', () => {
    // Don't resolve yet — keep pending
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('categories-loading')).toBeInTheDocument();
  });

  it('renders tabs from API response — not hardcoded', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    // Both category tabs must appear (sourced from API)
    await waitFor(() => {
      expect(screen.getByTestId('tab-cat_alpha')).toBeInTheDocument();
      expect(screen.getByTestId('tab-cat_beta')).toBeInTheDocument();
    });

    expect(screen.getByTestId('tab-cat_alpha').textContent).toBe('Alpha');
    expect(screen.getByTestId('tab-cat_beta').textContent).toBe('Beta');
  });

  it('tabs are ordered by display_order from API', async () => {
    // Return categories in reverse order to test defensive sort
    const reversed = [...CATEGORIES].reverse();
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(reversed));
        }
        return Promise.resolve(makeJsonResponse(CASES_ALPHA));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('categories-tablist')).toBeInTheDocument();
    });

    const tablist = screen.getByTestId('categories-tablist');
    const triggers = tablist.querySelectorAll('[data-testid^="tab-"]');
    expect(triggers[0].getAttribute('data-testid')).toBe('tab-cat_alpha');
    expect(triggers[1].getAttribute('data-testid')).toBe('tab-cat_beta');
  });

  it('fetches cases for the first category on mount', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    // Verify fetch was called with category query
    const callUrls = fetchSpy.mock.calls.map((c) => String(c[0]));
    expect(callUrls.some((u) => u.includes('category=cat_alpha'))).toBe(true);
  });

  it('renders case cards with correct data-testid attributes', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
    });

    // id label
    expect(screen.getByTestId('case-id-ALPHA-001')).toBeInTheDocument();
    // status badge
    expect(screen.getByTestId('case-status-ALPHA-001')).toBeInTheDocument();
    // title
    expect(screen.getByTestId('case-title-ALPHA-001')).toBeInTheDocument();
    expect(screen.getByTestId('case-title-ALPHA-001').textContent).toBe(
      'First alpha case',
    );
    // tags
    expect(screen.getByTestId('case-tags-ALPHA-001')).toBeInTheDocument();
    // latest-run placeholder
    expect(
      screen.getByTestId('case-latest-run-ALPHA-001'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('case-latest-run-ALPHA-002'),
    ).toBeInTheDocument();
  });

  it('fetches cases for the second tab when it is selected', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    // Wait for tabs to render
    await waitFor(() => {
      expect(screen.getByTestId('tab-cat_beta')).toBeInTheDocument();
    });

    // Radix Tabs@1.x activates on onMouseDown with button=0, ctrlKey=false.
    const betaTab = screen.getByTestId('tab-cat_beta');
    fireEvent.mouseDown(betaTab, { button: 0, ctrlKey: false });

    // After selecting beta tab, fetch should be triggered for cat_beta
    await waitFor(() => {
      const callUrls = fetchSpy.mock.calls.map((c) => String(c[0]));
      expect(callUrls.some((u) => u.includes('category=cat_beta'))).toBe(true);
    });

    // Cases for beta should appear after fetch completes
    await waitFor(() => {
      expect(screen.getByTestId('case-card-BETA-001')).toBeInTheDocument();
    });
  });

  it('shows empty state when category has no cases', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          return Promise.resolve(makeJsonResponse([]));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-empty')).toBeInTheDocument();
    });
  });

  it('shows inline error with retry button when cases fetch fails', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          return Promise.resolve(
            new Response(null, { status: 500, statusText: 'Internal Server Error' }),
          );
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId('cases-error-cat_alpha'),
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId('cases-retry-cat_alpha')).toBeInTheDocument();
    // Does not crash to ErrorBoundary — page-cases is still present
    expect(screen.getByTestId('page-cases')).toBeInTheDocument();
  });

  it('shows inline error with retry button when categories fetch fails', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(
        new Response(null, { status: 503, statusText: 'Service Unavailable' }),
      ),
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('categories-error')).toBeInTheDocument();
    });

    expect(screen.getByTestId('categories-retry')).toBeInTheDocument();
    expect(screen.getByTestId('page-cases')).toBeInTheDocument();
  });

  it('shows empty state when categories API returns empty list', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(makeJsonResponse([])),
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('categories-empty')).toBeInTheDocument();
    });
  });

  it('renders "+ New Case" header CTA linking to /cases/new', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('cases-page-new-case')).toBeInTheDocument();
    });
    // shadcn `<Button asChild>` puts the testid on the rendered <a> Link
    // itself, so we assert against the element directly.
    const cta = screen.getByTestId('cases-page-new-case');
    expect(cta.tagName).toBe('A');
    expect(cta.getAttribute('href')).toBe('/cases/new');
    expect(cta.textContent).toContain('New Case');
  });

  // -------------------------------------------------------------------------
  // M6-D4 search tests — verify wiring, not just rendering
  // -------------------------------------------------------------------------

  it('renders search input with testid cases-search-input', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });
  });

  it('typing into search input debounces ~300ms then re-requests /cases with ?q=', async () => {
    // Capture all /cases fetch URLs so we can assert the ?q= param
    const casesFetchUrls: string[] = [];
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          casesFetchUrls.push(url);
          if (url.includes('q=hash')) {
            return Promise.resolve(makeJsonResponse([CASES_ALPHA[0]]));
          }
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    // Wait for initial load with real timers
    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    const initialFetchCount = casesFetchUrls.length;

    // Switch to fake timers AFTER the initial async loads are done
    vi.useFakeTimers();

    // Type "hash" into the search input
    const input = screen.getByTestId('cases-search-input');
    fireEvent.change(input, { target: { value: 'hash' } });

    // Before debounce fires, no new /cases request should have been made
    expect(casesFetchUrls.length).toBe(initialFetchCount);

    // Advance timers by 300ms to trigger debounce — this fires the setTimeout
    // and React state update; wrap in act() to flush React rendering
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Switch back to real timers so waitFor polling works
    vi.useRealTimers();

    // Now the URL q should be updated and a new /cases fetch triggered
    await waitFor(() => {
      expect(casesFetchUrls.length).toBeGreaterThan(initialFetchCount);
    });

    // The new fetch must include ?q=hash
    const searchFetches = casesFetchUrls.filter((u) => u.includes('q=hash'));
    expect(searchFetches.length).toBeGreaterThan(0);
    // The first category must also be included
    expect(searchFetches[0]).toContain('category=cat_alpha');
  });

  it('search input value reflects debounced input (stays in sync)', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });

    const input = screen.getByTestId('cases-search-input') as HTMLInputElement;

    vi.useFakeTimers();

    // Type "smoke"
    fireEvent.change(input, { target: { value: 'smoke' } });

    // Input value reflects typed text immediately (before debounce)
    expect(input.value).toBe('smoke');

    // After debounce fires, input value remains
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    vi.useRealTimers();

    // Input value should still be 'smoke'
    expect(input.value).toBe('smoke');
  });

  it('switching category keeps q in effect — new category request includes q', async () => {
    const casesFetchUrls: string[] = [];
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          casesFetchUrls.push(url);
          if (url.includes('category=cat_beta')) {
            return Promise.resolve(makeJsonResponse(CASES_BETA));
          }
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });

    // Type a search query and wait for debounce
    const input = screen.getByTestId('cases-search-input');
    fireEvent.change(input, { target: { value: 'foo' } });

    vi.useFakeTimers();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    vi.useRealTimers();

    // Wait for the q-based fetch to complete
    await waitFor(() => {
      expect(casesFetchUrls.some((u) => u.includes('q=foo'))).toBe(true);
    });

    // Now switch to beta tab
    await waitFor(() => {
      expect(screen.getByTestId('tab-cat_beta')).toBeInTheDocument();
    });

    const betaTab = screen.getByTestId('tab-cat_beta');
    fireEvent.mouseDown(betaTab, { button: 0, ctrlKey: false });

    // The beta fetch must ALSO include q=foo (q persists across tab switch)
    await waitFor(() => {
      const betaFetches = casesFetchUrls.filter(
        (u) => u.includes('category=cat_beta'),
      );
      expect(betaFetches.length).toBeGreaterThan(0);
      expect(betaFetches[0]).toContain('q=foo');
    });
  });

  it('q changes invalidate the cache: same category refetches on new q', async () => {
    const casesFetchUrls: string[] = [];
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          casesFetchUrls.push(url);
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    const alphaFetchesBefore = casesFetchUrls.filter((u) =>
      u.includes('category=cat_alpha'),
    ).length;
    expect(alphaFetchesBefore).toBeGreaterThan(0);

    // Type a new search query — the cache key changes, triggering re-fetch
    const input = screen.getByTestId('cases-search-input');
    fireEvent.change(input, { target: { value: 'newterm' } });

    vi.useFakeTimers();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    vi.useRealTimers();

    await waitFor(() => {
      const alphaFetchesAfter = casesFetchUrls.filter((u) =>
        u.includes('category=cat_alpha'),
      ).length;
      expect(alphaFetchesAfter).toBeGreaterThan(alphaFetchesBefore);
    });

    // The new fetch must include q=newterm
    expect(
      casesFetchUrls.some((u) => u.includes('q=newterm') && u.includes('category=cat_alpha')),
    ).toBe(true);
  });

  it('does NOT re-fetch when q has not changed (cache hit)', async () => {
    const casesFetchUrls: string[] = [];
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          casesFetchUrls.push(url);
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    const alphaFetchCountAfterLoad = casesFetchUrls.filter((u) =>
      u.includes('category=cat_alpha'),
    ).length;

    // Switch to beta
    await waitFor(() => {
      expect(screen.getByTestId('tab-cat_beta')).toBeInTheDocument();
    });

    fireEvent.mouseDown(screen.getByTestId('tab-cat_beta'), { button: 0, ctrlKey: false });
    await waitFor(() => {
      expect(casesFetchUrls.some((u) => u.includes('category=cat_beta'))).toBe(true);
    });

    // Switch back to alpha — should NOT trigger a new /cases fetch
    // because alpha::'' is already in the cache
    fireEvent.mouseDown(screen.getByTestId('tab-cat_alpha'), { button: 0, ctrlKey: false });

    // Give it a moment and check fetch count didn't increase for alpha
    await new Promise((r) => setTimeout(r, 50));

    const alphaFetchCountAfterSwitch = casesFetchUrls.filter((u) =>
      u.includes('category=cat_alpha'),
    ).length;
    expect(alphaFetchCountAfterSwitch).toBe(alphaFetchCountAfterLoad);
  });

  // -------------------------------------------------------------------------
  // Tag filter tests
  // -------------------------------------------------------------------------

  it('renders tag chips for tags on loaded cases', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    // ALPHA-001 has tags ['smoke', 'fast']
    expect(screen.getByTestId('cases-tag-filter-smoke')).toBeInTheDocument();
    expect(screen.getByTestId('cases-tag-filter-fast')).toBeInTheDocument();
  });

  it('tag chip multi-select: OR filter hides cases that do not match any selected tag', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
    });

    // Select "smoke" tag — only ALPHA-001 has it; ALPHA-002 has no tags
    const smokeChip = screen.getByTestId('cases-tag-filter-smoke');
    fireEvent.click(smokeChip);

    await waitFor(() => {
      // ALPHA-001 (has 'smoke') should be visible
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      // ALPHA-002 (no tags) should be hidden
      expect(screen.queryByTestId('case-card-ALPHA-002')).not.toBeInTheDocument();
    });
  });

  it('tag chip OR: selecting two tags shows cases matching either tag', async () => {
    // Use a fixture where two cases have different tags
    const casesWithDifferentTags = [
      {
        id: 'ALPHA-001',
        category: 'cat_alpha',
        title: 'Case with smoke tag',
        status: 'active',
        destructive: false,
        tags: ['smoke'],
        error: null,
      },
      {
        id: 'ALPHA-002',
        category: 'cat_alpha',
        title: 'Case with fast tag',
        status: 'active',
        destructive: false,
        tags: ['fast'],
        error: null,
      },
      {
        id: 'ALPHA-003',
        category: 'cat_alpha',
        title: 'Case with no tags',
        status: 'active',
        destructive: false,
        tags: [],
        error: null,
      },
    ];

    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          return Promise.resolve(makeJsonResponse(casesWithDifferentTags));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-003')).toBeInTheDocument();
    });

    // Select both 'smoke' and 'fast' tags (OR)
    fireEvent.click(screen.getByTestId('cases-tag-filter-smoke'));
    fireEvent.click(screen.getByTestId('cases-tag-filter-fast'));

    await waitFor(() => {
      // ALPHA-001 (smoke) and ALPHA-002 (fast) should be visible
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
      // ALPHA-003 (no tags) should be hidden (doesn't match either tag)
      expect(screen.queryByTestId('case-card-ALPHA-003')).not.toBeInTheDocument();
    });
  });

  it('tag filter AND server q: q narrows first, tags filter the result', async () => {
    // q returns only ALPHA-001 (server-side); then tag chip appears for 'smoke'
    vi.restoreAllMocks();
    const casesFetchUrls: string[] = [];
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          casesFetchUrls.push(url);
          if (url.includes('q=first')) {
            // Server returns only ALPHA-001 when q=first
            return Promise.resolve(makeJsonResponse([CASES_ALPHA[0]]));
          }
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });

    // Type search query — triggers server-side filter
    const input = screen.getByTestId('cases-search-input');
    fireEvent.change(input, { target: { value: 'first' } });

    vi.useFakeTimers();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    vi.useRealTimers();

    // Wait for q-filtered result (only ALPHA-001 returned by server)
    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.queryByTestId('case-card-ALPHA-002')).not.toBeInTheDocument();
    });

    // ALPHA-001 has tag 'smoke' — the chip should be rendered
    expect(screen.getByTestId('cases-tag-filter-smoke')).toBeInTheDocument();

    // Select 'smoke' tag — ALPHA-001 still shown (it has the tag)
    fireEvent.click(screen.getByTestId('cases-tag-filter-smoke'));

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    // Wiring assertion: server was requested with q=first
    expect(casesFetchUrls.some((u) => u.includes('q=first'))).toBe(true);
  });

  it('shows cases-search-empty when no cases match the search query', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          if (url.includes('q=nomatch')) {
            return Promise.resolve(makeJsonResponse([]));
          }
          return Promise.resolve(makeJsonResponse(CASES_ALPHA));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-input')).toBeInTheDocument();
    });

    const input = screen.getByTestId('cases-search-input');
    fireEvent.change(input, { target: { value: 'nomatch' } });

    vi.useFakeTimers();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByTestId('cases-search-empty')).toBeInTheDocument();
    });

    expect(screen.getByTestId('cases-search-empty').textContent).toContain(
      'nomatch',
    );
  });

  it('shows cases-search-empty message contains the search query', async () => {
    vi.restoreAllMocks();
    vi.spyOn(global, 'fetch').mockImplementation(
      (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes('/admin/categories')) {
          return Promise.resolve(makeJsonResponse(CATEGORIES));
        }
        if (url.includes('/cases')) {
          return Promise.resolve(makeJsonResponse([]));
        }
        return Promise.resolve(makeJsonResponse({}));
      },
    );

    render(
      <MemoryRouter initialEntries={['/?q=myquery']}>
        <CasesPage />
      </MemoryRouter>,
    );

    // With q preset in URL, initial fetch should return []
    // The input should be pre-populated from URL
    await waitFor(() => {
      expect(screen.getByTestId('cases-search-empty')).toBeInTheDocument();
    });

    const emptyEl = screen.getByTestId('cases-search-empty');
    expect(emptyEl.textContent).toContain('myquery');
  });

  it('tag chip multi-select: toggling off re-shows the hidden case', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
    });

    const smokeChip = screen.getByTestId('cases-tag-filter-smoke');

    // Select 'smoke' — ALPHA-002 hidden
    fireEvent.click(smokeChip);
    await waitFor(() => {
      expect(screen.queryByTestId('case-card-ALPHA-002')).not.toBeInTheDocument();
    });

    // De-select 'smoke' — ALPHA-002 should reappear
    fireEvent.click(smokeChip);
    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
    });
  });

  it('tag selection resets when switching category', async () => {
    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
    });

    // Select 'smoke' tag on alpha tab — ALPHA-002 (no tags) hidden
    fireEvent.click(screen.getByTestId('cases-tag-filter-smoke'));

    await waitFor(() => {
      expect(screen.queryByTestId('case-card-ALPHA-002')).not.toBeInTheDocument();
    });

    // Switch to beta tab
    fireEvent.mouseDown(screen.getByTestId('tab-cat_beta'), { button: 0, ctrlKey: false });

    await waitFor(() => {
      expect(screen.getByTestId('case-card-BETA-001')).toBeInTheDocument();
    });

    // Switch back to alpha — tag selection should be reset, both cases visible
    fireEvent.mouseDown(screen.getByTestId('tab-cat_alpha'), { button: 0, ctrlKey: false });

    await waitFor(() => {
      // After tab switch back, selection reset — ALPHA-002 should be visible again
      expect(screen.getByTestId('case-card-ALPHA-001')).toBeInTheDocument();
      expect(screen.getByTestId('case-card-ALPHA-002')).toBeInTheDocument();
    });
  });
});
