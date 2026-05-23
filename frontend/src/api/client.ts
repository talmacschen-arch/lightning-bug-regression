import type { paths, components } from './types';

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000';

type Method = 'get' | 'post' | 'put' | 'delete' | 'patch';

export async function apiFetch<P extends keyof paths, M extends keyof paths[P] & Method>(
  path: P,
  method: M,
  init?: { body?: unknown; query?: Record<string, string | number | undefined> },
): Promise<unknown> {
  let url: string = BASE + (path as string);

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

  if (!res.ok) {
    throw new Error(`API ${method as string} ${path as string} failed: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<unknown>;
}

export type { paths, components };
