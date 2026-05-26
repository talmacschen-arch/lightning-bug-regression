/**
 * AdminCasesPage — list cases + Delete button per row (v1.16+).
 *
 * **Delete semantics** (decided 2026-05-25):
 *   - Removes the YAML file from disk.
 *   - case_results / runs rows untouched — historical run data persists.
 *   - Caller must `git rm + commit + push` to sync the deletion.
 *   - **Skip List handles temporary disable** (with optional until_date
 *     auto-expiry) — Delete is for **permanent** removal only.
 *   - Confirm dialog educates the user on this distinction.
 *
 * Not implemented here:
 *   - No "Includes case (deleted)" filter in RunsPage — once deleted,
 *     the case_id is gone from /cases so RunsPage combobox no longer
 *     shows it. Historical runs are still in DB but lookup by case_id
 *     becomes unavailable via UI (acceptable per user's 2026-05-25
 *     decision: deleted = forever gone).
 */
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { authHeaders } from '@/lib/auth';

type CaseSummary = components['schemas']['CaseSummary'];

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

// v1.17+ Bearer-token auth (was X-Admin-Password header before;
// backend's get_current_user dependency now requires Authorization:
// Bearer <token>).

const CONFIRM_MESSAGE = (caseId: string): string =>
  `Delete "${caseId}"?\n\n` +
  '此操作从磁盘删 YAML 文件，历史 run 记录保留。\n\n' +
  '💡 想清楚：\n' +
  '  • 短期不想跑某 case → 用 Skip List（可加过期日，到期自动恢复）\n' +
  '  • 只有彻底不再保留这个 case 时才走 Delete\n\n' +
  '操作后记得 `git rm + commit + push` 同步到 git。';

export default function AdminCasesPage() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch('/cases', 'get');
      setCases(data as CaseSummary[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleDelete(caseId: string) {
    if (!confirm(CONFIRM_MESSAGE(caseId))) return;
    setDeletingId(caseId);
    try {
      const resp = await fetch(
        `${API_BASE}/admin/cases/${encodeURIComponent(caseId)}`,
        {
          method: 'DELETE',
          headers: authHeaders(),
        },
      );
      if (!resp.ok && resp.status !== 204) {
        const detail = await resp.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div data-testid="page-admin-cases" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Cases — Delete</h1>
      <p className="text-sm text-muted-foreground">
        Permanently delete a case YAML from disk. <strong>Historical run
        records are preserved.</strong> For temporary disable, use{' '}
        <a href="/admin/skip-list" className="text-blue-700 hover:underline">
          Skip list
        </a>{' '}
        (with optional auto-expire date) instead.
      </p>
      <p
        data-testid="admin-cases-hint"
        className="text-xs bg-yellow-50 border border-yellow-200 rounded p-2"
      >
        ⚠️ <strong>不可逆操作</strong>。删除后需要 <code>git rm + commit + push</code>
        把变化同步到 git。If you only need to skip the case temporarily, prefer Skip list.
      </p>

      {error !== null && (
        <div data-testid="admin-cases-error" className="text-sm text-red-600">
          {error}
        </div>
      )}

      {cases === null && error === null && (
        <div data-testid="admin-cases-loading">Loading cases…</div>
      )}

      {cases !== null && cases.length === 0 && (
        <div data-testid="admin-cases-empty" className="text-sm text-muted-foreground">
          No cases on disk.
        </div>
      )}

      {cases !== null && cases.length > 0 && (
        <table data-testid="admin-cases-table" className="w-full text-sm">
          <thead>
            <tr className="text-left border-b">
              <th className="py-1">case_id</th>
              <th className="py-1">Category</th>
              <th className="py-1">Status</th>
              <th className="py-1">Title</th>
              <th className="py-1"></th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.id}
                data-testid={`admin-cases-row-${c.id}`}
                className="border-b last:border-0"
              >
                <td className="py-1 font-mono text-xs">{c.id}</td>
                <td className="py-1 text-xs">{c.category}</td>
                <td className="py-1 text-xs">{c.status}</td>
                <td className="py-1 text-xs text-muted-foreground truncate max-w-[400px]">
                  {c.title ?? '—'}
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    data-testid={`admin-cases-delete-${c.id}`}
                    onClick={() => void handleDelete(c.id)}
                    disabled={deletingId === c.id}
                    className="text-red-600 hover:underline text-xs disabled:opacity-50"
                  >
                    {deletingId === c.id ? 'Deleting…' : 'Delete'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
