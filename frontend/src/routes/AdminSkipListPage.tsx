/**
 * Admin skip-list CRUD (M6-4).
 *
 * Wraps `GET /admin/skip-list` (list), `POST /admin/skip-list` (add),
 * `DELETE /admin/skip-list/{id}` (remove). Optional `X-Admin-Password`
 * header is read from localStorage `adminPassword` if present (set via
 * /admin/settings).
 */
import { useCallback, useEffect, useState } from 'react';

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

interface SkipEntry {
  id: number;
  case_id: string;
  reason: string;
  applies_to_version: string | null;
  upstream_issue: string | null;
  until_date: string | null;
}

function adminHeaders(extra?: Record<string, string>): HeadersInit {
  const pw = typeof localStorage !== 'undefined' ? localStorage.getItem('adminPassword') : null;
  const h: Record<string, string> = { ...extra };
  if (pw) h['X-Admin-Password'] = pw;
  return h;
}

export default function AdminSkipListPage() {
  const [entries, setEntries] = useState<SkipEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    case_id: '',
    reason: '',
    applies_to_version: '',
    upstream_issue: '',
    until_date: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/admin/skip-list`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setEntries(await resp.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body: Record<string, string | null> = {
        case_id: draft.case_id.trim(),
        reason: draft.reason.trim(),
      };
      if (draft.applies_to_version.trim()) body.applies_to_version = draft.applies_to_version.trim();
      if (draft.upstream_issue.trim()) body.upstream_issue = draft.upstream_issue.trim();
      if (draft.until_date) body.until_date = draft.until_date;
      const resp = await fetch(`${API_BASE}/admin/skip-list`, {
        method: 'POST',
        headers: adminHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      setDraft({ case_id: '', reason: '', applies_to_version: '', upstream_issue: '', until_date: '' });
      await refresh();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm(`Delete skip-list entry #${id}?`)) return;
    try {
      const resp = await fetch(`${API_BASE}/admin/skip-list/${id}`, {
        method: 'DELETE',
        headers: adminHeaders(),
      });
      if (!resp.ok && resp.status !== 204) {
        const detail = await resp.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div data-testid="page-admin-skip-list" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Skip list</h1>

      <form
        data-testid="skip-list-add-form"
        onSubmit={handleAdd}
        className="grid gap-2 max-w-2xl"
      >
        <input
          data-testid="skip-list-input-case-id"
          placeholder="case_id (required, e.g. lg-bug-0009-flaky)"
          value={draft.case_id}
          onChange={(e) => setDraft({ ...draft, case_id: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="skip-list-input-reason"
          placeholder="reason (required)"
          value={draft.reason}
          onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="skip-list-input-version"
          placeholder="applies_to_version (optional, e.g. SynxDB-4.5.0-build130)"
          value={draft.applies_to_version}
          onChange={(e) => setDraft({ ...draft, applies_to_version: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="skip-list-input-issue"
          placeholder="upstream_issue URL (optional)"
          value={draft.upstream_issue}
          onChange={(e) => setDraft({ ...draft, upstream_issue: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="skip-list-input-until"
          type="date"
          placeholder="until_date (optional)"
          value={draft.until_date}
          onChange={(e) => setDraft({ ...draft, until_date: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <button
          type="submit"
          data-testid="skip-list-add-submit"
          disabled={submitting}
          className="bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
        >
          {submitting ? 'Adding…' : 'Add skip entry'}
        </button>
        {submitError !== null && (
          <div data-testid="skip-list-add-error" className="text-sm text-red-600">
            {submitError}
          </div>
        )}
      </form>

      {error !== null && (
        <div data-testid="skip-list-error" className="text-sm text-red-600">
          {error}
        </div>
      )}

      {entries === null ? (
        <div data-testid="skip-list-loading">Loading…</div>
      ) : entries.length === 0 ? (
        <div data-testid="skip-list-empty" className="text-sm text-muted-foreground">
          No skip-list entries.
        </div>
      ) : (
        <table data-testid="skip-list-table" className="w-full text-sm">
          <thead>
            <tr>
              <th className="text-left">ID</th>
              <th className="text-left">case_id</th>
              <th className="text-left">Reason</th>
              <th className="text-left">Version</th>
              <th className="text-left">Issue</th>
              <th className="text-left">Until</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} data-testid={`skip-list-row-${e.id}`}>
                <td className="font-mono">{e.id}</td>
                <td className="font-mono">{e.case_id}</td>
                <td>{e.reason}</td>
                <td className="font-mono text-xs">{e.applies_to_version ?? '—'}</td>
                <td className="text-xs">{e.upstream_issue ?? '—'}</td>
                <td className="font-mono text-xs">{e.until_date ?? '—'}</td>
                <td>
                  <button
                    type="button"
                    data-testid={`skip-list-delete-${e.id}`}
                    onClick={() => void handleDelete(e.id)}
                    className="text-red-600 hover:underline text-xs"
                  >
                    Delete
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
