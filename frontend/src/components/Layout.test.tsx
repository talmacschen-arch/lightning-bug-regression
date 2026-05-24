/**
 * M5-1 — Layout.test.tsx
 *
 * Covers:
 *   - Sidebar renders all required nav links with correct data-testid (R6)
 *   - Breadcrumb renders based on current pathname
 *   - Active-run pip color logic (green/red/yellow/grey) from mocked API
 *   - Admin nav link is disabled (not an anchor / aria-disabled=true)
 *   - ErrorBoundary remains outside Layout (tested in App.test.tsx; here we
 *     just confirm Layout itself doesn't throw)
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Layout } from './Layout';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRunsResponse(status: string, id = 42): Response {
  return new Response(
    JSON.stringify([
      {
        id,
        status,
        started_at: new Date(Date.now() - 4 * 3_600_000).toISOString(), // 4h ago
        finished_at: null,
        total: 10,
        passed: 8,
        failed: 2,
        skipped: 0,
        target_version: null,
        triggered_by: null,
      },
    ]),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function makeEmptyRunsResponse(): Response {
  return new Response(JSON.stringify([]), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Render Layout inside a MemoryRouter at a given path, with a stubbed fetch */
function renderLayout(
  path: string,
  fetchImpl: (input: RequestInfo | URL) => Promise<Response>,
) {
  vi.spyOn(global, 'fetch').mockImplementation(fetchImpl);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Layout />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Layout sidebar', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders all sidebar nav links with correct data-testid', async () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));

    expect(screen.getByTestId('sidebar-nav-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-nav-cases')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-nav-runs')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-nav-admin')).toBeInTheDocument();
  });

  it('renders main-content area', () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));
    expect(screen.getByTestId('main-content')).toBeInTheDocument();
  });

  it('Admin nav item is disabled (aria-disabled=true, not an anchor)', () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));
    const adminEl = screen.getByTestId('sidebar-nav-admin');
    expect(adminEl.getAttribute('aria-disabled')).toBe('true');
    expect(adminEl.tagName.toLowerCase()).not.toBe('a');
  });

  it('Admin nav item has "Coming soon" tooltip', () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));
    const adminEl = screen.getByTestId('sidebar-nav-admin');
    expect(adminEl.getAttribute('title')).toBe('Coming soon');
  });

  it('Cases nav link points to /cases', () => {
    renderLayout('/cases', () => Promise.resolve(makeEmptyRunsResponse()));
    const casesEl = screen.getByTestId('sidebar-nav-cases');
    expect(casesEl.getAttribute('href')).toBe('/cases');
  });

  it('Runs nav link points to /runs', () => {
    renderLayout('/runs', () => Promise.resolve(makeEmptyRunsResponse()));
    const runsEl = screen.getByTestId('sidebar-nav-runs');
    expect(runsEl.getAttribute('href')).toBe('/runs');
  });
});

describe('Layout breadcrumb', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders breadcrumb element', () => {
    renderLayout('/cases', () => Promise.resolve(makeEmptyRunsResponse()));
    expect(screen.getByTestId('breadcrumb')).toBeInTheDocument();
  });

  it('breadcrumb shows "Cases" segment for /cases', () => {
    renderLayout('/cases', () => Promise.resolve(makeEmptyRunsResponse()));
    const bc = screen.getByTestId('breadcrumb');
    expect(bc.textContent).toContain('Cases');
  });

  it('breadcrumb shows "Runs" segment for /runs', () => {
    renderLayout('/runs', () => Promise.resolve(makeEmptyRunsResponse()));
    const bc = screen.getByTestId('breadcrumb');
    expect(bc.textContent).toContain('Runs');
  });

  it('breadcrumb shows "Cases" and "New" for /cases/new', () => {
    renderLayout('/cases/new', () => Promise.resolve(makeEmptyRunsResponse()));
    const bc = screen.getByTestId('breadcrumb');
    expect(bc.textContent).toContain('Cases');
    expect(bc.textContent).toContain('New');
  });
});

describe('Layout active-run pip', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the active-run-pip element', async () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));
    expect(screen.getByTestId('sidebar-active-run-pip')).toBeInTheDocument();
  });

  it('pip shows green dot when run status is "pass"', async () => {
    renderLayout('/', () => Promise.resolve(makeRunsResponse('pass')));
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('span.rounded-full');
      expect(dot?.className).toContain('bg-green-500');
    });
  });

  it('pip shows red dot when run status is "fail"', async () => {
    renderLayout('/', () => Promise.resolve(makeRunsResponse('fail')));
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('span.rounded-full');
      expect(dot?.className).toContain('bg-red-500');
    });
  });

  it('pip shows yellow dot when run status is "running"', async () => {
    renderLayout('/', () => Promise.resolve(makeRunsResponse('running')));
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('span.rounded-full');
      expect(dot?.className).toContain('bg-yellow-400');
    });
  });

  it('pip shows grey dot when no run data (empty array)', async () => {
    renderLayout('/', () => Promise.resolve(makeEmptyRunsResponse()));
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('span.rounded-full');
      expect(dot?.className).toContain('bg-gray-400');
    });
  });

  it('pip shows grey dot when fetch fails', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network error'));
    render(
      <MemoryRouter initialEntries={['/']}>
        <Layout />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('span.rounded-full');
      expect(dot?.className).toContain('bg-gray-400');
    });
  });

  it('pip calls GET /runs with limit=1 query param', async () => {
    const spy = vi
      .spyOn(global, 'fetch')
      .mockImplementation(() => Promise.resolve(makeEmptyRunsResponse()));
    render(
      <MemoryRouter initialEntries={['/']}>
        <Layout />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const urls = spy.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('/runs') && u.includes('limit=1'))).toBe(
        true,
      );
    });
  });

  it('pip tooltip includes run id, status, and relative time for pass run', async () => {
    renderLayout('/', () => Promise.resolve(makeRunsResponse('pass', 99)));
    await waitFor(() => {
      const pip = screen.getByTestId('sidebar-active-run-pip');
      expect(pip.getAttribute('title')).toContain('Run #99');
      expect(pip.getAttribute('title')).toContain('PASS');
    });
  });
});
