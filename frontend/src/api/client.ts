import type { paths, components } from './types';

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000';

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

  if (init?.body !== undefined) {
    fetchInit.headers = { 'Content-Type': 'application/json' };
    fetchInit.body = JSON.stringify(init.body);
  }

  const res = await fetch(url, fetchInit);

  const isAllowed = init?.allowedStatuses?.includes(res.status) ?? false;

  if (!res.ok && !isAllowed) {
    throw new Error(`API ${method as string} ${path as string} failed: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<unknown>;
}

export type { paths, components };
