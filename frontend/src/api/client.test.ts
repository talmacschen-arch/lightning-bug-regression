import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch } from './client';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
});

describe('apiFetch', () => {
  it('returns parsed JSON body on success', async () => {
    const body = { status: 'ok', db: 'ok' };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(body),
    });

    const result = await apiFetch('/healthz', 'get');
    expect(result).toEqual(body);
  });

  it('throws on non-2xx response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.resolve({ detail: 'error' }),
    });

    await expect(apiFetch('/healthz', 'get')).rejects.toThrow('500');
  });

  it('JSON-stringifies the request body', async () => {
    const responseBody = { run_id: 1, status: 'pending', started_at: '2024-01-01T00:00:00Z', location: '/runs/1' };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 202,
      statusText: 'Accepted',
      json: () => Promise.resolve(responseBody),
    });

    const payload = { case_ids: ['case-001'], target_version: '5.1' };
    await apiFetch('/runs', 'post', { body: payload });

    const [, calledInit] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(calledInit.body).toBe(JSON.stringify(payload));
    expect((calledInit.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('appends query params when provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve([]),
    });

    await apiFetch('/runs', 'get', { query: { limit: 10 } });

    const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toContain('limit=10');
  });

  it('omits undefined query params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve([]),
    });

    await apiFetch('/cases', 'get', { query: { category: undefined, q: 'search' } });

    const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toContain('q=search');
    expect(calledUrl).not.toContain('category');
  });
});
