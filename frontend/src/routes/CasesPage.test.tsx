import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
  });

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
      expect(screen.getByTestId('cases-empty-cat_alpha')).toBeInTheDocument();
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
});
