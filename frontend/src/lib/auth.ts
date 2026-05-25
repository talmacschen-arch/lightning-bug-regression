/**
 * Auth state helpers (v1.17).
 *
 * Token storage: localStorage `authToken` (single canonical key).
 * Multi-tab: token shared via localStorage; logout in one tab eventually
 * surfaces in others via next 401-on-fetch + auto-redirect (in api/client.ts).
 *
 * Stale value (e.g. after backend restart with fresh DB) is cleared by
 * the next API call returning 401, which triggers token wipe + nav to /login.
 *
 * NOT covered by this module:
 *  - Adding Authorization header to fetches — see `api/client.ts apiFetch`.
 *  - Redirect on 401 — see `api/client.ts` (uses window.location.href).
 *  - Protected-route gating — see `App.tsx` `<RequireAuth>` wrapper.
 */

const TOKEN_KEY = 'authToken';

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

export interface MeResponse {
  username: string;
  must_change_password: boolean;
}

export interface LoginResponse {
  token: string;
  username: string;
  must_change_password: boolean;
}

export function getAuthToken(): string | null {
  if (typeof localStorage === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** POST /auth/login. Throws on bad credentials (401). Stores token on success. */
export async function login(username: string, password: string): Promise<LoginResponse> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }
  const body = (await resp.json()) as LoginResponse;
  setAuthToken(body.token);
  return body;
}

/**
 * POST /auth/logout. Always clears local token even if backend call fails
 * (backend itself is idempotent: 204 even without a header).
 */
export async function logout(): Promise<void> {
  const token = getAuthToken();
  clearAuthToken();
  if (token) {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // network error — token already cleared locally, fine
    }
  }
}

/**
 * GET /auth/me. Returns null on 401 (token invalid / expired) — caller
 * should treat that as "not logged in" and route to /login.
 */
export async function fetchMe(): Promise<MeResponse | null> {
  const token = getAuthToken();
  if (!token) return null;
  try {
    const resp = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.status === 401) {
      clearAuthToken();
      return null;
    }
    if (!resp.ok) {
      // 5xx / network — keep token, return null so caller falls back to login
      return null;
    }
    return (await resp.json()) as MeResponse;
  } catch {
    return null;
  }
}
