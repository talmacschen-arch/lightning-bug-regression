/**
 * AdminSkipListPage smoke tests (M6-4 + combobox).
 *
 * Combobox UX: case_id input is now a CaseIdCombobox that fetches
 * /cases on mount and shows fuzzy-searchable popover. Tests mock /cases
 * + interact via the combobox testids (trigger / search / item-{id}).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminSkipListPage from './AdminSkipListPage';

const mockFetch = vi.fn();
const apiFetchMock = vi.fn();

// CaseIdCombobox calls apiFetch from @/api/client (typed fetch wrapper),
// not raw fetch — mock that path. Other endpoints in AdminSkipListPage
// (skip-list CRUD) use raw fetch.
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('confirm', () => true);
  mockFetch.mockReset();
  apiFetchMock.mockReset();
  // Default /cases payload — used by CaseIdCombobox; tests can override
  // before render() if a specific case row needs to be selected.
  apiFetchMock.mockResolvedValue([
    { id: 'lg-bug-9999-flaky', category: 'bug_regression', title: 'Flaky bug', status: 'open', destructive: false, tags: null, error: null },
    { id: 'lg-bug-x', category: 'bug_regression', title: 'Test case X', status: 'open', destructive: false, tags: null, error: null },
    { id: 'a', category: 'bug_regression', title: 'Single-letter id', status: 'open', destructive: false, tags: null, error: null },
  ]);
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJson(body: unknown, ok = true, status = ok ? 200 : 500) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Server Error',
    json: () => Promise.resolve(body),
  };
}

const SAMPLE_ENTRIES = [
  {
    id: 1,
    case_id: 'lg-bug-9999-flaky',
    reason: 'intermittent on 4.5.0 (R28)',
    applies_to_version: 'SynxDB-4.5.0-build130',
    upstream_issue: null,
    until_date: '2026-12-31',
  },
];

/** Pick a case via the combobox: click trigger → click item. */
async function pickCaseInCombobox(caseId: string) {
  fireEvent.click(screen.getByTestId('skip-list-input-case-id-trigger'));
  await waitFor(() => {
    expect(screen.getByTestId(`skip-list-input-case-id-item-${caseId}`)).toBeInTheDocument();
  });
  fireEvent.click(screen.getByTestId(`skip-list-input-case-id-item-${caseId}`));
}

describe('AdminSkipListPage', () => {
  it('renders existing entries from GET /admin/skip-list', async () => {
    mockFetch.mockResolvedValueOnce(mockJson(SAMPLE_ENTRIES));
    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('skip-list-table')).toBeInTheDocument();
    });
    expect(screen.getByTestId('skip-list-row-1')).toBeInTheDocument();
    expect(screen.getByText('lg-bug-9999-flaky')).toBeInTheDocument();
  });

  it('shows empty hint when list is empty', async () => {
    mockFetch.mockResolvedValueOnce(mockJson([]));
    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('skip-list-empty')).toBeInTheDocument();
    });
  });

  it('add form POSTs and refreshes (case_id picked via combobox)', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson([])) // initial GET /admin/skip-list
      .mockResolvedValueOnce(mockJson({ ...SAMPLE_ENTRIES[0], id: 7, case_id: 'lg-bug-x' }, true, 201)) // POST
      .mockResolvedValueOnce(mockJson([{ ...SAMPLE_ENTRIES[0], id: 7, case_id: 'lg-bug-x' }])); // refresh GET

    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('skip-list-empty')).toBeInTheDocument());

    await pickCaseInCombobox('lg-bug-x');
    fireEvent.change(screen.getByTestId('skip-list-input-reason'), { target: { value: 'test reason' } });
    fireEvent.click(screen.getByTestId('skip-list-add-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('skip-list-row-7')).toBeInTheDocument();
    });
    // POST call sent with proper body
    const postCall = mockFetch.mock.calls[1];
    expect(postCall[0]).toContain('/admin/skip-list');
    expect(postCall[1].method).toBe('POST');
    expect(JSON.parse(postCall[1].body)).toMatchObject({
      case_id: 'lg-bug-x',
      reason: 'test reason',
    });
  });

  it('delete calls DELETE and refreshes', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SAMPLE_ENTRIES))
      .mockResolvedValueOnce(mockJson({}, true, 204))
      .mockResolvedValueOnce(mockJson([]));

    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('skip-list-row-1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('skip-list-delete-1'));
    await waitFor(() => expect(screen.getByTestId('skip-list-empty')).toBeInTheDocument());
    expect(mockFetch.mock.calls[1][1].method).toBe('DELETE');
  });

  it('sends Authorization: Bearer header from authHeaders() (v1.17 token-auth)', async () => {
    // Dogfood 2026-05-26: legacy X-Admin-Password header path was
    // disabled when v1.17 user-login replaced ADMIN_PASSWORD env auth.
    // Skip List CRUD now uses authHeaders() → Authorization: Bearer.
    if (typeof localStorage !== 'undefined') localStorage.setItem('authToken', 'tok-abc');
    mockFetch
      .mockResolvedValueOnce(mockJson([]))
      .mockResolvedValueOnce(mockJson({ id: 5, case_id: 'a', reason: 'b', applies_to_version: null, upstream_issue: null, until_date: null }, true, 201))
      .mockResolvedValueOnce(mockJson([]));

    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('skip-list-empty')).toBeInTheDocument());
    await pickCaseInCombobox('a');
    fireEvent.change(screen.getByTestId('skip-list-input-reason'), { target: { value: 'b' } });
    fireEvent.click(screen.getByTestId('skip-list-add-submit'));
    await waitFor(() => expect(mockFetch.mock.calls.length).toBeGreaterThan(1));
    const postCall = mockFetch.mock.calls[1];
    expect(postCall[1].headers['Authorization']).toBe('Bearer tok-abc');
    // Legacy header gone
    expect(postCall[1].headers['X-Admin-Password']).toBeUndefined();
  });
});
