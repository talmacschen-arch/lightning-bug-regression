import type { paths, components } from './types';
import { authHeaders, clearAuthToken } from '@/lib/auth';

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000';

/**
 * Paths that are open without authentication. apiFetch will NOT trigger
 * the 401 → /login redirect for these — they intentionally need to work
 * pre-login (`/auth/login` itself) or just don't gate read access (`/auth/me`
 * is checked by the caller, which handles 401 explicitly).
 */
const PUBLIC_PATHS = new Set<string>([
  '/auth/login',
  '/auth/me',
  '/auth/logout',
]);

type Method = 'get' | 'post' | 'put' | 'delete' | 'patch';

export interface ApiFetchInit {
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  path?: Record<string, string | number>;
  /**
   * Additional HTTP status codes beyond 2xx that should be treated as
   * non-error (i.e. response body is returned rather than thrown).
   * Callers use this to read error-shaped response bodies (e.g. 409).
   */
  allowedStatuses?: number[];
}

export async function apiFetch<P extends keyof paths, M extends keyof paths[P] & Method>(
  path: P,
  method: M,
  init?: ApiFetchInit,
): Promise<unknown> {
  let url: string = BASE + (path as string);

  // Substitute path params: replace {param} with the provided value.
  if (init?.path) {
    for (const [k, v] of Object.entries(init.path)) {
      url = url.replace(`{${k}}`, encodeURIComponent(String(v)));
    }
  }

  if (init?.query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(init.query)) {
      if (v !== undefined) {
        params.set(k, String(v));
      }
    }
    const qs = params.toString();
    if (qs) {
      url += '?' + qs;
    }
  }

  const fetchInit: RequestInit = { method: method as string };

  // Build headers: auto-inject Authorization for any path with a token,
  // plus Content-Type when there's a JSON body. authHeaders() returns
  // `{}` when no token is stored — safe to spread.
  const headers: Record<string, string> = { ...(authHeaders() as Record<string, string>) };
  if (init?.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    fetchInit.body = JSON.stringify(init.body);
  }
  if (Object.keys(headers).length > 0) {
    fetchInit.headers = headers;
  }

  const res = await fetch(url, fetchInit);

  const isAllowed = init?.allowedStatuses?.includes(res.status) ?? false;

  // Auth gate: a 401 on a non-public path means token is gone / invalid.
  // Wipe local token + redirect to /login so the user re-authenticates.
  // PUBLIC_PATHS opt-out: /auth/login (callers handle 401 directly to
  // show "invalid credentials"); /auth/me + /auth/logout (caller already
  // expects null/idempotent semantics).
  if (res.status === 401 && !PUBLIC_PATHS.has(path as string) && !isAllowed) {
    clearAuthToken();
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
  }

  if (!res.ok && !isAllowed) {
    throw new Error(`API ${method as string} ${path as string} failed: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<unknown>;
}

export type { paths, components };
