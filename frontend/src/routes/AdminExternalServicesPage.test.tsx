/**
 * AdminExternalServicesPage — read-only browser smoke tests (v1.15+).
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminExternalServicesPage from './AdminExternalServicesPage';

const mockFetch = vi.fn();

const FAKE_SERVICES = [
  {
    name: 'dut',
    filename: 'dut.yml',
    size_bytes: 87,
    modified_at: '2026-05-25T03:00:00Z',
    content: 'host: 127.0.0.1\nport: 5432\nuser: gpadmin\ndatabase: gpadmin\n',
    parse_error: null,
  },
  {
    name: 'elasticsearch',
    filename: 'elasticsearch.yml',
    size_bytes: 120,
    modified_at: '2026-05-25T03:01:00Z',
    content: 'host: 192.168.195.203\nport: 9200\nextras:\n  scheme: http\n',
    parse_error: null,
  },
];

function mockJson(body: unknown, ok = true, status = ok ? 200 : 500) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Server Error',
    json: () => Promise.resolve(body),
  };
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminExternalServicesPage />
    </MemoryRouter>,
  );
}

describe('AdminExternalServicesPage', () => {
  it('renders edit-hint banner pointing at filesystem (read-only)', async () => {
    mockFetch.mockResolvedValue(mockJson(FAKE_SERVICES));
    renderPage();
    expect(screen.getByTestId('external-services-edit-hint')).toBeInTheDocument();
    expect(screen.getByTestId('external-services-edit-hint').textContent).toContain('vi');
    expect(screen.getByTestId('external-services-edit-hint').textContent).toContain('git commit');
  });

  it('renders list of services with content + size + modified time', async () => {
    mockFetch.mockResolvedValue(mockJson(FAKE_SERVICES));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('external-services-list')).toBeInTheDocument();
    });
    expect(screen.getByTestId('external-services-item-dut')).toBeInTheDocument();
    expect(screen.getByTestId('external-services-item-elasticsearch')).toBeInTheDocument();
    expect(screen.getByTestId('external-services-svc-dut')).toHaveTextContent('dut');
    expect(screen.getByTestId('external-services-content-dut')).toHaveTextContent(
      'host: 127.0.0.1',
    );
    expect(screen.getByTestId('external-services-content-elasticsearch')).toHaveTextContent(
      '192.168.195.203',
    );
  });

  it('shows empty hint with sample YAML when no files', async () => {
    mockFetch.mockResolvedValue(mockJson([]));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('external-services-empty')).toBeInTheDocument();
    });
    expect(screen.getByTestId('external-services-empty').textContent).toContain('myservice.yml');
  });

  it('shows top-level error on fetch failure', async () => {
    mockFetch.mockRejectedValue(new Error('network down'));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('external-services-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('external-services-error')).toHaveTextContent('network down');
  });

  it('shows top-level error on non-2xx response', async () => {
    mockFetch.mockResolvedValue(mockJson({}, false, 503));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('external-services-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('external-services-error')).toHaveTextContent('503');
  });

  it('flags rows with parse_error inline', async () => {
    mockFetch.mockResolvedValue(
      mockJson([
        {
          name: 'broken',
          filename: 'broken.yml',
          size_bytes: 30,
          modified_at: '2026-05-25T03:00:00Z',
          content: '- a\n- b\n',
          parse_error: 'top-level must be a YAML mapping; got list',
        },
      ]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('external-services-parse-error-broken')).toBeInTheDocument();
    });
    expect(screen.getByTestId('external-services-parse-error-broken')).toHaveTextContent(
      'top-level must be a YAML mapping',
    );
  });
});
