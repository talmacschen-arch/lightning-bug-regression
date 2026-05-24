/**
 * AdminExternalServicesPage — read-only browser for external/<svc>.yml.
 *
 * Why read-only: M6-4 Admin > Settings (the "GUI edit JSON" UX) was
 * removed v1.15 because dogfood proved users prefer editing
 * git-tracked files via `vi external/<svc>.yml` + commit (diff visible,
 * history reviewable). This page exists only for **discovery** — show
 * what svc files exist right now + their content + mtime — so a user
 * can sanity-check current config (e.g. "what's the ES URL?") without
 * shelling in. Editing always goes through the filesystem.
 *
 * Source: GET /admin/external-services (added v1.15+). Each row = one
 * `.yml` / `.yaml` file under `EXTERNAL_DEPS_DIR` (default `external/`).
 */
import { useEffect, useState } from 'react';

// Endpoint added v1.15+, not yet in the OpenAPI codegen — use raw
// fetch like the other Admin pages (AdminSkipListPage / Settings).
const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

interface ExternalServiceOut {
  name: string;
  filename: string;
  size_bytes: number;
  modified_at: string;
  content: string;
  parse_error: string | null;
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(1)} KB`;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

export default function AdminExternalServicesPage() {
  const [services, setServices] = useState<ExternalServiceOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/admin/external-services`)
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = (await resp.json()) as ExternalServiceOut[];
        if (!cancelled) setServices(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-testid="page-admin-external-services" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">External services (read-only)</h1>
      <p className="text-sm text-muted-foreground">
        Cases declare <code>external_deps: [svc_name]</code> and reference
        <code>{' {{ external.<svc>.<field> }} '}</code> in their YAML; runner
        loads <code>external/&lt;svc&gt;.yml</code> at run time and injects.
        DUT connection lives in <code>external/dut.yml</code>.
      </p>
      <p
        data-testid="external-services-edit-hint"
        className="text-xs bg-yellow-50 border border-yellow-200 rounded p-2"
      >
        ✏️ <strong>编辑方式</strong>: 直接 <code>vi external/&lt;svc&gt;.yml</code> +
        <code>git commit</code> + 重启 backend (uvicorn pick up new files on
        next run). 本页 read-only — 不提供 Web 编辑入口，避免 "GUI 编 JSON" 反模式
        (post-M6 v1.15 决策)。
      </p>

      {error !== null && (
        <div data-testid="external-services-error" className="text-sm text-red-600">
          Failed to load: {error}
        </div>
      )}

      {error === null && services === null && (
        <div data-testid="external-services-loading">Loading…</div>
      )}

      {services !== null && services.length === 0 && (
        <div data-testid="external-services-empty" className="text-sm text-muted-foreground">
          No <code>external/*.yml</code> files found. Create one to get started:
          <pre className="mt-2 bg-gray-50 p-2 rounded text-xs">
{`# external/myservice.yml
host: 10.0.0.1
port: 1234
extras:
  api_key: ...`}
          </pre>
        </div>
      )}

      {services !== null && services.length > 0 && (
        <ul
          data-testid="external-services-list"
          className="space-y-3"
        >
          {services.map((s) => (
            <li
              key={s.name}
              data-testid={`external-services-item-${s.name}`}
              className="border rounded p-3 space-y-1"
            >
              <div className="flex items-baseline gap-3 flex-wrap">
                <span className="font-mono font-semibold text-sm">
                  external/{s.filename}
                </span>
                <span
                  data-testid={`external-services-svc-${s.name}`}
                  className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-800"
                >
                  {s.name}
                </span>
                <span className="text-xs text-gray-500">{formatSize(s.size_bytes)}</span>
                <span className="text-xs text-gray-500">
                  modified {formatTime(s.modified_at)}
                </span>
              </div>
              {s.parse_error !== null && (
                <div
                  data-testid={`external-services-parse-error-${s.name}`}
                  className="text-xs text-red-600 font-mono"
                >
                  ⚠️ {s.parse_error}
                </div>
              )}
              <pre
                data-testid={`external-services-content-${s.name}`}
                className="bg-gray-50 p-2 rounded text-xs font-mono overflow-x-auto whitespace-pre-wrap"
              >
                {s.content}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
