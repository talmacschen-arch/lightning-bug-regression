import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RunNewPage from './RunNewPage';
import * as clientModule from '@/api/client';

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(clientModule.apiFetch);

const FAKE_CATEGORIES = [
  {
    name: 'bug_regression',
    display_name: 'Bug Regression',
    description: null,
    id_prefix: 'bug-',
    dir_path: 'cases/bug_regression',
    status_whitelist: [],
    default_status: 'active',
    display_order: 1,
  },
  {
    name: 'extension',
    display_name: 'Extension',
    description: null,
    id_prefix: 'ext-',
    dir_path: 'cases/extension',
    status_whitelist: [],
    default_status: 'active',
    display_order: 2,
  },
];

const FAKE_CASES_BUG = [
  { id: 'bug-001', category: 'bug_regression', title: 'First bug', status: 'active', destructive: false, tags: null, error: null },
  { id: 'bug-002', category: 'bug_regression', title: 'Second bug', status: 'active', destructive: false, tags: null, error: null },
];

const FAKE_CASES_EXT = [
  { id: 'ext-001', category: 'extension', title: 'Ext case', status: 'active', destructive: false, tags: null, error: null },
];

function setupMocks() {
  mockApiFetch.mockImplementation(async (path: string, _method: string, init?: { query?: Record<string, string | number | undefined> }) => {
    if (path === '/admin/categories') return FAKE_CATEGORIES;
    if (path === '/cases') {
      const category = init?.query?.['category'];
      if (category === 'bug_regression') return FAKE_CASES_BUG;
      if (category === 'extension') return FAKE_CASES_EXT;
      return [...FAKE_CASES_BUG, ...FAKE_CASES_EXT];
    }
    return [];
  });
}

// Helper to wait for the page to finish loading
async function renderAndLoad() {
  const result = render(
    <MemoryRouter>
      <RunNewPage />
    </MemoryRouter>,
  );
  // Wait until checkboxes appear
  await waitFor(() => {
    expect(screen.getByTestId('case-checkbox-bug-001')).toBeInTheDocument();
  });
  return result;
}

describe('RunNewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  it('renders case checkboxes from API data (§14 R4b — not hardcoded)', async () => {
    await renderAndLoad();
    expect(screen.getByTestId('case-checkbox-bug-001')).toBeInTheDocument();
    expect(screen.getByTestId('case-checkbox-bug-002')).toBeInTheDocument();
    expect(screen.getByTestId('case-checkbox-ext-001')).toBeInTheDocument();
  });

  it('renders per-category select-all checkboxes from API categories', async () => {
    await renderAndLoad();
    expect(screen.getByTestId('select-all-bug_regression')).toBeInTheDocument();
    expect(screen.getByTestId('select-all-extension')).toBeInTheDocument();
  });

  it('renders global select-all, invert, submit, and version input', async () => {
    await renderAndLoad();
    expect(screen.getByTestId('select-all-global')).toBeInTheDocument();
    expect(screen.getByTestId('invert-selection')).toBeInTheDocument();
    expect(screen.getByTestId('input-target-version')).toBeInTheDocument();
    expect(screen.getByTestId('btn-submit-run')).toBeInTheDocument();
  });

  it('submit button is disabled when no cases are selected', async () => {
    await renderAndLoad();
    const btn = screen.getByTestId('btn-submit-run') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('selecting a case enables submit button', async () => {
    await renderAndLoad();
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    const btn = screen.getByTestId('btn-submit-run') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('select-all-global selects all cases', async () => {
    await renderAndLoad();
    fireEvent.click(screen.getByTestId('select-all-global'));
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const c2 = screen.getByTestId('case-checkbox-bug-002') as HTMLInputElement;
    const c3 = screen.getByTestId('case-checkbox-ext-001') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    expect(c2.checked).toBe(true);
    expect(c3.checked).toBe(true);
  });

  it('select-all-global unchecks all when all are selected', async () => {
    await renderAndLoad();
    // Select all first
    fireEvent.click(screen.getByTestId('select-all-global'));
    // Then deselect all
    fireEvent.click(screen.getByTestId('select-all-global'));
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    expect(c1.checked).toBe(false);
  });

  it('per-category select-all selects only that category', async () => {
    await renderAndLoad();
    fireEvent.click(screen.getByTestId('select-all-bug_regression'));
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const c2 = screen.getByTestId('case-checkbox-bug-002') as HTMLInputElement;
    const c3 = screen.getByTestId('case-checkbox-ext-001') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    expect(c2.checked).toBe(true);
    expect(c3.checked).toBe(false);
  });

  it('invert flips selection state', async () => {
    await renderAndLoad();
    // Select only bug-001
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    // Invert: bug-001 should be deselected, bug-002 and ext-001 selected
    fireEvent.click(screen.getByTestId('invert-selection'));
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const c2 = screen.getByTestId('case-checkbox-bug-002') as HTMLInputElement;
    const c3 = screen.getByTestId('case-checkbox-ext-001') as HTMLInputElement;
    expect(c1.checked).toBe(false);
    expect(c2.checked).toBe(true);
    expect(c3.checked).toBe(true);
  });

  it('invert with nothing selected selects all', async () => {
    await renderAndLoad();
    fireEvent.click(screen.getByTestId('invert-selection'));
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const c2 = screen.getByTestId('case-checkbox-bug-002') as HTMLInputElement;
    const c3 = screen.getByTestId('case-checkbox-ext-001') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    expect(c2.checked).toBe(true);
    expect(c3.checked).toBe(true);
  });

  it('shows conflict dialog on 409 response', async () => {
    mockApiFetch.mockImplementation(async (path: string, _method: string, init?: { query?: Record<string, string | number | undefined> }) => {
      if (path === '/admin/categories') return FAKE_CATEGORIES;
      if (path === '/cases') {
        const category = init?.query?.['category'];
        if (category === 'bug_regression') return FAKE_CASES_BUG;
        if (category === 'extension') return FAKE_CASES_EXT;
        return FAKE_CASES_BUG;
      }
      if (path === '/runs') return { detail: 'Run already active', active_run_id: 42 };
      return [];
    });

    await renderAndLoad();
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    fireEvent.click(screen.getByTestId('btn-submit-run'));

    await waitFor(() => {
      expect(screen.getByTestId('modal-active-run-conflict')).toBeInTheDocument();
    });
    expect(screen.getByTestId('link-existing-run')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// M5-5 — URL preset (?category=X&status=Y) tests
// ---------------------------------------------------------------------------

const FAKE_PRESET_CASES_BUG = [
  { id: 'bug-001', category: 'bug_regression', title: 'open 1', status: 'open', destructive: false, tags: null, error: null },
  { id: 'bug-002', category: 'bug_regression', title: 'open 2', status: 'open', destructive: false, tags: null, error: null },
  { id: 'bug-003', category: 'bug_regression', title: 'fixed 1', status: 'fixed', destructive: false, tags: null, error: null },
];

const FAKE_PRESET_CASES_EXT = [
  { id: 'ext-001', category: 'extension', title: 'stable 1', status: 'stable', destructive: false, tags: null, error: null },
];

function setupPresetMocks() {
  mockApiFetch.mockImplementation(async (path: string, _method: string, init?: { query?: Record<string, string | number | undefined> }) => {
    if (path === '/admin/categories') return FAKE_CATEGORIES;
    if (path === '/cases') {
      const category = init?.query?.['category'];
      if (category === 'bug_regression') return FAKE_PRESET_CASES_BUG;
      if (category === 'extension') return FAKE_PRESET_CASES_EXT;
      return [...FAKE_PRESET_CASES_BUG, ...FAKE_PRESET_CASES_EXT];
    }
    return [];
  });
}

function renderAtUrl(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <RunNewPage />
    </MemoryRouter>,
  );
}

describe('RunNewPage M5-5 — URL preset (?category=X&status=Y)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupPresetMocks();
  });

  it('no preset banner when URL has no category/status', async () => {
    renderAtUrl('/runs/new');
    await waitFor(() => {
      expect(screen.getByTestId('case-checkbox-bug-001')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('preset-banner')).toBeNull();
  });

  it('shows preset banner when URL has category', async () => {
    renderAtUrl('/runs/new?category=bug_regression');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-banner-category')).toHaveTextContent('bug_regression');
  });

  it('pre-selects all bug_regression open cases when ?category=bug_regression&status=open', async () => {
    renderAtUrl('/runs/new?category=bug_regression&status=open');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // 2 "open" cases in fixture (bug-001 / bug-002), bug-003 is "fixed" → excluded
    expect(screen.getByTestId('preset-banner-count')).toHaveTextContent('2 cases matched');
    // Selection count visible in select-all label
    await waitFor(() => {
      expect(screen.getByText(/Select all \(2 \/ 4\)/)).toBeInTheDocument();
    });
  });

  it('pre-selects all matching status across categories when only ?status=stable', async () => {
    renderAtUrl('/runs/new?status=stable');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // Only ext-001 has status='stable'
    expect(screen.getByTestId('preset-banner-count')).toHaveTextContent('1 case matched');
  });

  it('pre-selects entire category when only ?category=bug_regression', async () => {
    renderAtUrl('/runs/new?category=bug_regression');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // 3 bug cases total (bug-001/002/003)
    expect(screen.getByTestId('preset-banner-count')).toHaveTextContent('3 cases matched');
  });

  it('shows 0 cases matched when preset matches nothing', async () => {
    renderAtUrl('/runs/new?category=bug_regression&status=wontfix');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-banner-count')).toHaveTextContent('0 cases matched');
  });

  it('Clear preset button removes URL params + deselects all', async () => {
    renderAtUrl('/runs/new?category=bug_regression&status=open');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // Confirm 2 selected
    await waitFor(() => {
      expect(screen.getByText(/Select all \(2 \/ 4\)/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('preset-banner-clear'));
    await waitFor(() => {
      expect(screen.queryByTestId('preset-banner')).toBeNull();
    });
    // Selection count reset
    expect(screen.getByText(/Select all \(0 \/ 4\)/)).toBeInTheDocument();
  });

  it('shows both category and status labels when both present', async () => {
    renderAtUrl('/runs/new?category=extension&status=stable');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-banner-category')).toHaveTextContent('extension');
    expect(screen.getByTestId('preset-banner-status')).toHaveTextContent('stable');
  });
});
