/**
 * AdminTargetVersionsPage smoke tests.
 *
 * Mocks raw `fetch` for /admin/target-versions endpoints. Mirrors the
 * style of AdminSkipListPage.test.tsx (vitest + vi.stubGlobal('fetch')).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminTargetVersionsPage from './AdminTargetVersionsPage';

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

const SEED = [
  {
    id: 1,
    name: 'SynxDB-4.5.0-build130',
    display_order: 100,
    is_active: true,
    is_default: true,
    notes: null,
    created_at: '2026-05-26T00:00:00',
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminTargetVersionsPage />
    </MemoryRouter>,
  );
}

describe('AdminTargetVersionsPage', () => {
  it('renders the seeded row after GET succeeds', async () => {
    mockFetch.mockResolvedValueOnce(mockJson(SEED));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-name-1')).toHaveTextContent(
        'SynxDB-4.5.0-build130',
      );
    });
    expect(screen.getByTestId('admin-target-versions-default-radio-1')).toBeChecked();
    expect(screen.getByTestId('admin-target-versions-active-toggle-1')).toBeChecked();
  });

  it('shows error banner when GET fails', async () => {
    mockFetch.mockResolvedValueOnce(mockJson(null, false, 500));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-error')).toBeInTheDocument();
    });
  });

  it('shows empty state when GET returns []', async () => {
    mockFetch.mockResolvedValueOnce(mockJson([]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-empty')).toBeInTheDocument();
    });
  });

  it('Add row: POST → refetch → new row appears', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson([])) // initial GET (empty)
      .mockResolvedValueOnce(
        mockJson({
          id: 2,
          name: 'SynxDB-4.6.0-build42',
          display_order: 200,
          is_active: true,
          is_default: false,
          notes: null,
          created_at: '2026-05-26T01:00:00',
        }),
      ) // POST
      .mockResolvedValueOnce(
        mockJson([
          ...SEED,
          {
            id: 2,
            name: 'SynxDB-4.6.0-build42',
            display_order: 200,
            is_active: true,
            is_default: false,
            notes: null,
            created_at: '2026-05-26T01:00:00',
          },
        ]),
      ); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-empty'));

    fireEvent.change(screen.getByTestId('admin-target-versions-add-name-input'), {
      target: { value: 'SynxDB-4.6.0-build42' },
    });
    fireEvent.change(screen.getByTestId('admin-target-versions-add-order-input'), {
      target: { value: '200' },
    });
    fireEvent.click(screen.getByTestId('admin-target-versions-add-button'));

    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-name-2')).toHaveTextContent(
        'SynxDB-4.6.0-build42',
      );
    });

    const calls = mockFetch.mock.calls;
    const postCall = calls.find((c) => c[1]?.method === 'POST');
    expect(postCall).toBeDefined();
    const sentBody = JSON.parse(postCall![1].body as string);
    expect(sentBody.name).toBe('SynxDB-4.6.0-build42');
    expect(sentBody.display_order).toBe(200);
  });

  it('POST 409 duplicate name → form error shown', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SEED)) // GET
      .mockResolvedValueOnce(
        mockJson({ detail: "name 'SynxDB-4.5.0-build130' already exists" }, false, 409),
      ); // POST

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-1'));

    fireEvent.change(screen.getByTestId('admin-target-versions-add-name-input'), {
      target: { value: 'SynxDB-4.5.0-build130' },
    });
    fireEvent.click(screen.getByTestId('admin-target-versions-add-button'));

    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-add-error')).toHaveTextContent(
        /already exists/,
      );
    });
  });

  it('Toggle Active: PATCH fires with is_active: false', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SEED)) // GET
      .mockResolvedValueOnce(mockJson({ ...SEED[0], is_active: false })) // PATCH
      .mockResolvedValueOnce(mockJson([{ ...SEED[0], is_active: false }])); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-1'));

    fireEvent.click(screen.getByTestId('admin-target-versions-active-toggle-1'));

    await waitFor(() => {
      const patchCall = mockFetch.mock.calls.find((c) => c[1]?.method === 'PATCH');
      expect(patchCall).toBeDefined();
      const body = JSON.parse(patchCall![1].body as string);
      expect(body).toEqual({ is_active: false });
    });
  });

  it('Set Default: PATCH fires with is_default: true', async () => {
    const twoRows = [
      { ...SEED[0], is_default: false },
      {
        id: 2,
        name: 'SynxDB-4.6.0-build42',
        display_order: 200,
        is_active: true,
        is_default: true,
        notes: null,
        created_at: '2026-05-26T01:00:00',
      },
    ];
    mockFetch
      .mockResolvedValueOnce(mockJson(twoRows)) // GET
      .mockResolvedValueOnce(mockJson({ ...twoRows[0], is_default: true })) // PATCH
      .mockResolvedValueOnce(
        mockJson([
          { ...twoRows[0], is_default: true },
          { ...twoRows[1], is_default: false },
        ]),
      ); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-2'));

    fireEvent.click(screen.getByTestId('admin-target-versions-default-radio-1'));

    await waitFor(() => {
      const patchCall = mockFetch.mock.calls.find((c) => c[1]?.method === 'PATCH');
      expect(patchCall).toBeDefined();
      const body = JSON.parse(patchCall![1].body as string);
      expect(body).toEqual({ is_default: true });
    });
  });

  it('Delete unreferenced: DELETE 204 → row removed', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SEED)) // GET
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: () => Promise.resolve(null),
      }) // DELETE
      .mockResolvedValueOnce(mockJson([])); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-1'));

    fireEvent.click(screen.getByTestId('admin-target-versions-delete-1'));

    await waitFor(() => {
      expect(screen.getByTestId('admin-target-versions-empty')).toBeInTheDocument();
    });

    const deleteCalls = mockFetch.mock.calls.filter((c) => c[1]?.method === 'DELETE');
    expect(deleteCalls).toHaveLength(1);
    expect(deleteCalls[0][0]).not.toContain('force=true');
  });

  it('Delete referenced (409 with run_count): second confirm → DELETE ?force=true', async () => {
    const confirmSpy = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(true);
    vi.stubGlobal('confirm', confirmSpy);
    mockFetch
      .mockResolvedValueOnce(mockJson(SEED)) // GET
      .mockResolvedValueOnce(
        mockJson({ detail: 'referenced by 5 runs', run_count: 5 }, false, 409),
      ) // DELETE (no force)
      .mockResolvedValueOnce({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: () => Promise.resolve(null),
      }) // DELETE ?force=true
      .mockResolvedValueOnce(mockJson([])); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-1'));

    fireEvent.click(screen.getByTestId('admin-target-versions-delete-1'));

    await waitFor(() => {
      const deleteCalls = mockFetch.mock.calls.filter((c) => c[1]?.method === 'DELETE');
      expect(deleteCalls).toHaveLength(2);
      expect(deleteCalls[1][0]).toContain('force=true');
    });

    expect(confirmSpy).toHaveBeenCalledTimes(2);
    expect(confirmSpy.mock.calls[1][0]).toMatch(/5 historical run/);
  });

  it('Edit name inline: PATCH fires with new name', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SEED)) // GET
      .mockResolvedValueOnce(mockJson({ ...SEED[0], name: 'SynxDB-4.5.0-build131' })) // PATCH
      .mockResolvedValueOnce(mockJson([{ ...SEED[0], name: 'SynxDB-4.5.0-build131' }])); // refetch

    renderPage();
    await waitFor(() => screen.getByTestId('admin-target-versions-row-1'));

    fireEvent.click(screen.getByTestId('admin-target-versions-edit-1'));
    fireEvent.change(screen.getByTestId('admin-target-versions-edit-name-1'), {
      target: { value: 'SynxDB-4.5.0-build131' },
    });
    fireEvent.click(screen.getByTestId('admin-target-versions-save-1'));

    await waitFor(() => {
      const patchCall = mockFetch.mock.calls.find((c) => c[1]?.method === 'PATCH');
      expect(patchCall).toBeDefined();
      const body = JSON.parse(patchCall![1].body as string);
      expect(body.name).toBe('SynxDB-4.5.0-build131');
    });
  });
});
