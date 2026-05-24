/**
 * AdminSettingsPage smoke tests (M6-4).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminSettingsPage from './AdminSettingsPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
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

const SAMPLE_SETTINGS = [
  {
    key: 'jinja_context',
    value: { cluster: 'synxdb-0001' },
    value_type: 'json',
    updated_at: '2026-05-24T00:00:00Z',
  },
];

describe('AdminSettingsPage', () => {
  it('renders one editor per editable key, populated with current value', async () => {
    mockFetch.mockResolvedValueOnce(mockJson(SAMPLE_SETTINGS));
    render(
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('settings-key-jinja_context')).toBeInTheDocument();
    });
    // All allowlisted keys present even if not yet stored
    expect(screen.getByTestId('settings-key-dut_hosts')).toBeInTheDocument();
    expect(screen.getByTestId('settings-key-server_log_path')).toBeInTheDocument();
    // dev_db_url / cluster_topology were removed 2026-05-25 (no consumer)
    expect(screen.queryByTestId('settings-key-dev_db_url')).toBeNull();
    expect(screen.queryByTestId('settings-key-cluster_topology')).toBeNull();

    // jinja_context textarea pre-populated
    const ta = screen.getByTestId('settings-textarea-jinja_context') as HTMLTextAreaElement;
    expect(ta.value).toContain('cluster');
    expect(ta.value).toContain('synxdb-0001');
  });

  it('save sends PUT with parsed JSON body', async () => {
    mockFetch
      .mockResolvedValueOnce(mockJson(SAMPLE_SETTINGS))
      .mockResolvedValueOnce(
        mockJson({
          key: 'jinja_context',
          value: { cluster: 'new-val' },
          value_type: 'json',
          updated_at: '2026-05-25T01:00:00Z',
        }),
      )
      .mockResolvedValueOnce(mockJson([]));

    render(
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('settings-key-jinja_context')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('settings-textarea-jinja_context'), {
      target: { value: '{"cluster":"new-val"}' },
    });
    fireEvent.click(screen.getByTestId('settings-save-jinja_context'));

    await waitFor(() => {
      const putCall = mockFetch.mock.calls.find(
        (c) => c[1]?.method === 'PUT',
      );
      expect(putCall).toBeDefined();
      expect(putCall[0]).toContain('/admin/settings/jinja_context');
      expect(JSON.parse(putCall[1].body)).toEqual({ value: { cluster: 'new-val' } });
    });
  });

  it('rejects invalid JSON inline (no PUT issued)', async () => {
    mockFetch.mockResolvedValueOnce(mockJson([]));
    render(
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId('settings-textarea-jinja_context')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('settings-textarea-jinja_context'), {
      target: { value: '{not-json' },
    });
    fireEvent.click(screen.getByTestId('settings-save-jinja_context'));
    await waitFor(() => {
      expect(screen.getByTestId('settings-error-jinja_context')).toBeInTheDocument();
    });
    // No PUT happened — only the initial GET
    expect(mockFetch.mock.calls.filter((c) => c[1]?.method === 'PUT')).toHaveLength(0);
  });

  it('shows top-level error when initial GET fails', async () => {
    mockFetch.mockResolvedValueOnce(mockJson({}, false, 500));
    render(
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('settings-error')).toBeInTheDocument();
    });
  });
});
