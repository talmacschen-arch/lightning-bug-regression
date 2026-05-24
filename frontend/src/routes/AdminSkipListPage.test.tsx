/**
 * AdminSkipListPage smoke tests (M6-4).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminSkipListPage from './AdminSkipListPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('confirm', () => true);
  mockFetch.mockReset();
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

  it('add form POSTs and refreshes', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson([])) // initial GET
      .mockResolvedValueOnce(mockJson({ ...SAMPLE_ENTRIES[0], id: 7 }, true, 201)) // POST
      .mockResolvedValueOnce(mockJson([{ ...SAMPLE_ENTRIES[0], id: 7 }])); // refresh GET

    render(
      <MemoryRouter>
        <AdminSkipListPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('skip-list-empty')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('skip-list-input-case-id'), { target: { value: 'lg-bug-x' } });
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

  it('sends X-Admin-Password header when localStorage adminPassword set', async () => {
    if (typeof localStorage !== 'undefined') localStorage.setItem('adminPassword', 'pw-2026');
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
    fireEvent.change(screen.getByTestId('skip-list-input-case-id'), { target: { value: 'a' } });
    fireEvent.change(screen.getByTestId('skip-list-input-reason'), { target: { value: 'b' } });
    fireEvent.click(screen.getByTestId('skip-list-add-submit'));
    await waitFor(() => expect(mockFetch.mock.calls.length).toBeGreaterThan(1));
    const postCall = mockFetch.mock.calls[1];
    expect(postCall[1].headers['X-Admin-Password']).toBe('pw-2026');
  });
});
