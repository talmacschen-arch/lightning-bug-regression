/**
 * AdminCasesPage smoke tests (v1.16+).
 *
 * Covers: list cases via /cases / Delete button per row / confirm dialog
 * with educational hint / DELETE /admin/cases/{id} call / refresh on
 * success / X-Admin-Password header / error display.
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminCasesPage from './AdminCasesPage';

const apiFetchMock = vi.fn();
vi.mock('@/api/client', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

const mockFetch = vi.fn();

function mockJson(body: unknown, ok = true, status = ok ? 200 : 500) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Server Error',
    json: () => Promise.resolve(body),
  };
}

const FAKE_CASES = [
  {
    id: 'bug-0001-hashjoin-right-table',
    category: 'bug_regression',
    title: 'hashjoin right table',
    status: 'fixed',
    destructive: false,
    tags: null,
    error: null,
  },
  {
    id: 'ext-pgvector-ivfflat-basic',
    category: 'extension',
    title: 'pgvector IVFFLAT 索引',
    status: 'stable',
    destructive: false,
    tags: null,
    error: null,
  },
];

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('confirm', () => true);
  apiFetchMock.mockReset();
  mockFetch.mockReset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminCasesPage />
    </MemoryRouter>,
  );
}

describe('AdminCasesPage', () => {
  it('renders cases table with Delete button per row', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-table')).toBeInTheDocument();
    });
    expect(screen.getByTestId('admin-cases-row-bug-0001-hashjoin-right-table')).toBeInTheDocument();
    expect(screen.getByTestId('admin-cases-row-ext-pgvector-ivfflat-basic')).toBeInTheDocument();
    expect(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table')).toBeInTheDocument();
  });

  it('renders hint banner pointing users to Skip list for temporary disable', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-hint')).toBeInTheDocument();
    });
    expect(screen.getByTestId('admin-cases-hint').textContent).toContain('git rm');
    expect(screen.getByTestId('admin-cases-hint').textContent).toContain('Skip list');
  });

  it('shows empty hint when no cases', async () => {
    apiFetchMock.mockResolvedValue([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-empty')).toBeInTheDocument();
    });
  });

  it('clicking Delete fires DELETE /admin/cases/{id} + refreshes', async () => {
    apiFetchMock
      .mockResolvedValueOnce(FAKE_CASES) // initial list
      .mockResolvedValueOnce([FAKE_CASES[1]]); // after delete
    mockFetch.mockResolvedValueOnce(mockJson({}, true, 204));

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-row-bug-0001-hashjoin-right-table')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table'));

    await waitFor(() => {
      expect(screen.queryByTestId('admin-cases-row-bug-0001-hashjoin-right-table')).toBeNull();
    });
    // Other row still there
    expect(screen.getByTestId('admin-cases-row-ext-pgvector-ivfflat-basic')).toBeInTheDocument();

    // Verify the DELETE call shape
    const deleteCall = mockFetch.mock.calls[0];
    expect(deleteCall[0]).toContain('/admin/cases/bug-0001-hashjoin-right-table');
    expect(deleteCall[1].method).toBe('DELETE');
  });

  it('shows educational confirm dialog text', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    const confirmSpy = vi.fn<[string], boolean>(() => true);
    vi.stubGlobal('confirm', confirmSpy);
    mockFetch.mockResolvedValue(mockJson({}, true, 204));

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table'));

    expect(confirmSpy).toHaveBeenCalled();
    const msg = confirmSpy.mock.calls[0][0];
    expect(msg).toContain('Skip List');
    expect(msg).toContain('过期日');
    expect(msg).toContain('git rm');
    expect(msg).toContain('bug-0001-hashjoin-right-table');
  });

  it('cancel via confirm() → no DELETE call', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    vi.stubGlobal('confirm', () => false);

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table'));

    // No DELETE was made
    expect(mockFetch).not.toHaveBeenCalled();
    // Row still present
    expect(screen.getByTestId('admin-cases-row-bug-0001-hashjoin-right-table')).toBeInTheDocument();
  });

  it('sends Authorization: Bearer header from authHeaders() (v1.17 token-auth)', async () => {
    // v1.17 user-login replaced ADMIN_PASSWORD env auth; legacy
    // X-Admin-Password header path is gone. Dogfood 2026-05-26: Delete
    // had been failing "missing or malformed Authorization header"
    // because the legacy adminHeaders() helper never sent Bearer token.
    if (typeof localStorage !== 'undefined') localStorage.setItem('authToken', 'tok-xyz');
    apiFetchMock
      .mockResolvedValueOnce(FAKE_CASES)
      .mockResolvedValueOnce([FAKE_CASES[1]]);
    mockFetch.mockResolvedValueOnce(mockJson({}, true, 204));

    renderPage();
    await waitFor(() => expect(screen.getByTestId('admin-cases-table')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table'));

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const headers = (mockFetch.mock.calls[0][1] as { headers: Record<string, string> }).headers;
    expect(headers['Authorization']).toBe('Bearer tok-xyz');
    expect(headers['X-Admin-Password']).toBeUndefined();
  });

  it('shows error when DELETE returns non-2xx', async () => {
    apiFetchMock.mockResolvedValue(FAKE_CASES);
    mockFetch.mockResolvedValueOnce(
      mockJson({ detail: 'case not found' }, false, 404),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('admin-cases-delete-bug-0001-hashjoin-right-table'));

    await waitFor(() => {
      expect(screen.getByTestId('admin-cases-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('admin-cases-error')).toHaveTextContent('case not found');
  });
});
