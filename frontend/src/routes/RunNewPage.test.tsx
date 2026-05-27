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

const FAKE_VERSION_OPTIONS = [
  { id: 1, name: 'SynxDB-4.5.0-build130', is_default: true },
  { id: 2, name: 'SynxDB-4.6.0-build42', is_default: false },
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
    if (path === '/admin/target-versions') return FAKE_VERSION_OPTIONS;
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

  it('renders global select-all, invert, submit, and version select', async () => {
    await renderAndLoad();
    expect(screen.getByTestId('select-all-global')).toBeInTheDocument();
    expect(screen.getByTestId('invert-selection')).toBeInTheDocument();
    const versionSelect = screen.getByTestId('input-target-version');
    expect(versionSelect).toBeInTheDocument();
    expect(versionSelect.tagName).toBe('SELECT');
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
      if (path === '/admin/target-versions') return [];
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

  // ---------------------------------------------------------------------------
  // Target version dropdown tests
  // ---------------------------------------------------------------------------

  it('dropdown: renders options from API + preselects is_default row', async () => {
    await renderAndLoad();
    // Wait for version options to load
    await waitFor(() => {
      const select = screen.getByTestId('input-target-version') as HTMLSelectElement;
      expect(select.options.length).toBe(3); // None + 2 versions
    });
    const select = screen.getByTestId('input-target-version') as HTMLSelectElement;
    expect(select.options[0].text).toBe('— None —');
    expect(select.options[1].text).toBe('SynxDB-4.5.0-build130');
    expect(select.options[2].text).toBe('SynxDB-4.6.0-build42');
    // is_default=true on id=1 → preselected
    expect(select.value).toBe('SynxDB-4.5.0-build130');
  });

  it('dropdown: selecting None submits target_version: null', async () => {
    let capturedBody: unknown = undefined;
    mockApiFetch.mockImplementation(async (path: string, method: string, init?: { query?: Record<string, string | number | undefined>; body?: unknown }) => {
      if (path === '/admin/categories') return FAKE_CATEGORIES;
      if (path === '/cases') {
        const category = init?.query?.['category'];
        if (category === 'bug_regression') return FAKE_CASES_BUG;
        if (category === 'extension') return FAKE_CASES_EXT;
        return [...FAKE_CASES_BUG, ...FAKE_CASES_EXT];
      }
      if (path === '/admin/target-versions') return FAKE_VERSION_OPTIONS;
      if (path === '/runs' && method === 'post') {
        capturedBody = init?.body;
        return { run_id: 99 };
      }
      return [];
    });

    await renderAndLoad();
    // Wait for default preselection
    await waitFor(() => {
      const select = screen.getByTestId('input-target-version') as HTMLSelectElement;
      expect(select.value).toBe('SynxDB-4.5.0-build130');
    });
    // Change to None
    fireEvent.change(screen.getByTestId('input-target-version'), { target: { value: '' } });
    // Select a case and submit
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    fireEvent.click(screen.getByTestId('btn-submit-run'));

    await waitFor(() => {
      expect(capturedBody).not.toBeUndefined();
    });
    expect((capturedBody as { target_version: unknown }).target_version).toBeNull();
  });

  it('dropdown: selecting a named version submits that string', async () => {
    let capturedBody: unknown = undefined;
    mockApiFetch.mockImplementation(async (path: string, method: string, init?: { query?: Record<string, string | number | undefined>; body?: unknown }) => {
      if (path === '/admin/categories') return FAKE_CATEGORIES;
      if (path === '/cases') {
        const category = init?.query?.['category'];
        if (category === 'bug_regression') return FAKE_CASES_BUG;
        if (category === 'extension') return FAKE_CASES_EXT;
        return [...FAKE_CASES_BUG, ...FAKE_CASES_EXT];
      }
      if (path === '/admin/target-versions') return FAKE_VERSION_OPTIONS;
      if (path === '/runs' && method === 'post') {
        capturedBody = init?.body;
        return { run_id: 100 };
      }
      return [];
    });

    await renderAndLoad();
    // Wait for options to load
    await waitFor(() => {
      const select = screen.getByTestId('input-target-version') as HTMLSelectElement;
      expect(select.options.length).toBe(3);
    });
    // Pick the second version (not the default)
    fireEvent.change(screen.getByTestId('input-target-version'), { target: { value: 'SynxDB-4.6.0-build42' } });
    // Select a case and submit
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    fireEvent.click(screen.getByTestId('btn-submit-run'));

    await waitFor(() => {
      expect(capturedBody).not.toBeUndefined();
    });
    expect((capturedBody as { target_version: unknown }).target_version).toBe('SynxDB-4.6.0-build42');
  });

  it('dropdown: GET /admin/target-versions 500 → only None option, run submission still works', async () => {
    let capturedBody: unknown = undefined;
    mockApiFetch.mockImplementation(async (path: string, method: string, init?: { query?: Record<string, string | number | undefined>; body?: unknown }) => {
      if (path === '/admin/categories') return FAKE_CATEGORIES;
      if (path === '/cases') {
        const category = init?.query?.['category'];
        if (category === 'bug_regression') return FAKE_CASES_BUG;
        if (category === 'extension') return FAKE_CASES_EXT;
        return [...FAKE_CASES_BUG, ...FAKE_CASES_EXT];
      }
      if (path === '/admin/target-versions') throw new Error('500 Internal Server Error');
      if (path === '/runs' && method === 'post') {
        capturedBody = init?.body;
        return { run_id: 101 };
      }
      return [];
    });

    await renderAndLoad();
    // Wait for the error state to settle
    await waitFor(() => {
      expect(screen.getByTestId('version-load-error')).toBeInTheDocument();
    });
    const select = screen.getByTestId('input-target-version') as HTMLSelectElement;
    // Only the "None" option
    expect(select.options.length).toBe(1);
    expect(select.options[0].text).toBe('— None —');
    // Run submission still works
    fireEvent.click(screen.getByTestId('case-checkbox-bug-001'));
    fireEvent.click(screen.getByTestId('btn-submit-run'));
    await waitFor(() => {
      expect(capturedBody).not.toBeUndefined();
    });
    expect((capturedBody as { target_version: unknown }).target_version).toBeNull();
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
    if (path === '/admin/target-versions') return [];
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

// ---------------------------------------------------------------------------
// M6-D1 — ?case_ids= preselect channel + stale target_version
// ---------------------------------------------------------------------------

describe('RunNewPage M6-D1 — case_ids preselect', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupPresetMocks();
  });

  it('case_ids all existing: all are selected, banner shows Re-run from Run #X, Trigger counts match', async () => {
    // bug-001 and bug-002 exist in FAKE_PRESET_CASES_BUG
    renderAtUrl('/runs/new?case_ids=bug-001,bug-002&from_run=42');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // Banner shows from_run context
    expect(screen.getByTestId('preset-banner-label')).toHaveTextContent('Re-run from Run #42');
    // Count shows selected (2)
    expect(screen.getByTestId('preset-banner-count')).toHaveTextContent('2 cases');
    // Both checkboxes are checked
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const c2 = screen.getByTestId('case-checkbox-bug-002') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    expect(c2.checked).toBe(true);
    // Trigger button shows "2 cases"
    expect(screen.getByTestId('btn-submit-run')).toHaveTextContent('Trigger Run (2 cases)');
  });

  it('case_ids with 1 deleted id: deleted id NOT in selected, banner shows skipped, Trigger counts only survivors', async () => {
    // bug-001 exists; bug-deleted-xyz does not exist in FAKE_PRESET_CASES_BUG/EXT
    renderAtUrl('/runs/new?case_ids=bug-001,bug-deleted-xyz&from_run=55');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // bug-001 selected, bug-deleted-xyz NOT in list (not rendered)
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    // No checkbox rendered for the deleted case (it doesn't exist in allCases)
    expect(screen.queryByTestId('case-checkbox-bug-deleted-xyz')).toBeNull();
    // Banner shows skipped notice
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner-skipped')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-banner-skipped')).toHaveTextContent(
      '1 case(s) from Run #55 no longer exist — skipped',
    );
    // Trigger button counts only the 1 surviving case
    expect(screen.getByTestId('btn-submit-run')).toHaveTextContent('Trigger Run (1 case)');
  });

  it('case_ids: all deleted → selected is empty, all ids skipped in banner', async () => {
    renderAtUrl('/runs/new?case_ids=gone-001,gone-002&from_run=60');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner-skipped')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-banner-skipped')).toHaveTextContent(
      '2 case(s) from Run #60 no longer exist — skipped',
    );
    // Trigger button disabled (0 selected)
    const btn = screen.getByTestId('btn-submit-run') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('case_ids takes priority over category/status when both present in URL', async () => {
    // Even with ?category=bug_regression, the case_ids channel wins
    renderAtUrl('/runs/new?case_ids=bug-001&from_run=77&category=extension');
    await waitFor(() => {
      expect(screen.getByTestId('preset-banner')).toBeInTheDocument();
    });
    // Only bug-001 is selected (not all extension cases)
    const c1 = screen.getByTestId('case-checkbox-bug-001') as HTMLInputElement;
    const cExt = screen.getByTestId('case-checkbox-ext-001') as HTMLInputElement;
    expect(c1.checked).toBe(true);
    expect(cExt.checked).toBe(false);
    // Banner is the rerun variant (from_run present)
    expect(screen.getByTestId('preset-banner-label')).toHaveTextContent('Re-run from Run #77');
  });
});

// ---------------------------------------------------------------------------
// M6-D1 — ?target_version= preselect + stale version fallback
// ---------------------------------------------------------------------------

function setupVersionPresetMocks(versions: { id: number; name: string; is_default: boolean }[]) {
  mockApiFetch.mockImplementation(async (path: string, _method: string, init?: { query?: Record<string, string | number | undefined> }) => {
    if (path === '/admin/categories') return FAKE_CATEGORIES;
    if (path === '/cases') {
      const category = init?.query?.['category'];
      if (category === 'bug_regression') return FAKE_CASES_BUG;
      if (category === 'extension') return FAKE_CASES_EXT;
      return [...FAKE_CASES_BUG, ...FAKE_CASES_EXT];
    }
    if (path === '/admin/target-versions') return versions;
    return [];
  });
}

describe('RunNewPage M6-D1 — target_version preselect', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('valid target_version in URL: version is preselected in dropdown, no stale notice', async () => {
    setupVersionPresetMocks(FAKE_VERSION_OPTIONS);
    renderAtUrl('/runs/new?case_ids=bug-001&from_run=10&target_version=SynxDB-4.6.0-build42');
    await waitFor(() => {
      expect(screen.getByTestId('case-checkbox-bug-001')).toBeInTheDocument();
    });
    await waitFor(() => {
      const sel = screen.getByTestId('input-target-version') as HTMLSelectElement;
      expect(sel.value).toBe('SynxDB-4.6.0-build42');
    });
    // No stale notice
    expect(screen.queryByTestId('stale-version-notice')).toBeNull();
  });

  it('stale target_version (not in active list): falls back to default, shows stale notice', async () => {
    setupVersionPresetMocks(FAKE_VERSION_OPTIONS);
    renderAtUrl('/runs/new?case_ids=bug-001&from_run=10&target_version=SynxDB-3.0.0-old');
    await waitFor(() => {
      expect(screen.getByTestId('case-checkbox-bug-001')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId('stale-version-notice')).toBeInTheDocument();
    });
    expect(screen.getByTestId('stale-version-notice')).toHaveTextContent(
      'SynxDB-3.0.0-old',
    );
    expect(screen.getByTestId('stale-version-notice')).toHaveTextContent(
      'no longer available',
    );
    // Falls back to default (SynxDB-4.5.0-build130 is_default=true)
    const sel = screen.getByTestId('input-target-version') as HTMLSelectElement;
    expect(sel.value).toBe('SynxDB-4.5.0-build130');
  });
});
