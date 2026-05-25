/**
 * auth.ts helpers (v1.17).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  clearAuthToken,
  fetchMe,
  getAuthToken,
  login,
  logout,
  setAuthToken,
  authHeaders,
} from './auth';

const mockFetch = vi.fn();

function mockJson(body: unknown, ok = true, status = ok ? 200 : 401) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Unauthorized',
    json: () => Promise.resolve(body),
  };
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token storage', () => {
  it('getAuthToken returns null when nothing stored', () => {
    expect(getAuthToken()).toBeNull();
  });

  it('setAuthToken + getAuthToken round-trip', () => {
    setAuthToken('xyz');
    expect(getAuthToken()).toBe('xyz');
  });

  it('clearAuthToken removes the key', () => {
    setAuthToken('xyz');
    clearAuthToken();
    expect(getAuthToken()).toBeNull();
  });

  it('authHeaders returns {} when no token', () => {
    expect(authHeaders()).toEqual({});
  });

  it('authHeaders returns Bearer header when token set', () => {
    setAuthToken('abc');
    expect(authHeaders()).toEqual({ Authorization: 'Bearer abc' });
  });
});

describe('login', () => {
  it('stores token on success', async () => {
    mockFetch.mockResolvedValueOnce(
      mockJson({ token: 'tok-1', username: 'admin', must_change_password: true }),
    );
    const r = await login('admin', 'admin');
    expect(r.token).toBe('tok-1');
    expect(r.must_change_password).toBe(true);
    expect(getAuthToken()).toBe('tok-1');
  });

  it('throws on 401 + does NOT store token', async () => {
    mockFetch.mockResolvedValueOnce(mockJson({ detail: 'bad creds' }, false, 401));
    await expect(login('admin', 'wrong')).rejects.toThrow('bad creds');
    expect(getAuthToken()).toBeNull();
  });

  it('throws generic message if response has no detail', async () => {
    mockFetch.mockResolvedValueOnce(mockJson({}, false, 500));
    await expect(login('admin', 'x')).rejects.toThrow(/HTTP 500/);
  });
});

describe('logout', () => {
  it('clears local token + calls backend with bearer header', async () => {
    setAuthToken('tok-1');
    mockFetch.mockResolvedValueOnce(mockJson({}, true, 204));
    await logout();
    expect(getAuthToken()).toBeNull();
    const call = mockFetch.mock.calls[0];
    expect(call[0]).toContain('/auth/logout');
    expect(call[1].headers.Authorization).toBe('Bearer tok-1');
  });

  it('no-op fetch when no token (still clears anyway)', async () => {
    await logout();
    expect(mockFetch).not.toHaveBeenCalled();
    expect(getAuthToken()).toBeNull();
  });

  it('still clears token even if backend errors', async () => {
    setAuthToken('tok-1');
    mockFetch.mockRejectedValueOnce(new Error('network'));
    await logout();
    expect(getAuthToken()).toBeNull();
  });
});

describe('fetchMe', () => {
  it('returns null when no token', async () => {
    expect(await fetchMe()).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('returns user on 200', async () => {
    setAuthToken('tok-1');
    mockFetch.mockResolvedValueOnce(
      mockJson({ username: 'admin', must_change_password: false }),
    );
    const me = await fetchMe();
    expect(me).toEqual({ username: 'admin', must_change_password: false });
  });

  it('clears token + returns null on 401', async () => {
    setAuthToken('stale-token');
    mockFetch.mockResolvedValueOnce(mockJson({ detail: 'invalid' }, false, 401));
    expect(await fetchMe()).toBeNull();
    expect(getAuthToken()).toBeNull();
  });

  it('keeps token + returns null on network error', async () => {
    setAuthToken('tok-1');
    mockFetch.mockRejectedValueOnce(new Error('boom'));
    expect(await fetchMe()).toBeNull();
    // Token NOT cleared — network error is transient, user might retry
    expect(getAuthToken()).toBe('tok-1');
  });
});
