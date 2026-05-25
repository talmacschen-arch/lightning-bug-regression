/**
 * Admin target_versions CRUD.
 *
 * Wraps GET /admin/target-versions, POST /admin/target-versions,
 * PATCH /admin/target-versions/{id}, DELETE /admin/target-versions/{id}.
 *
 * Source-of-truth for the "Trigger New Run → Target version" dropdown
 * (RunNewPage) and the Version column on the Runs list (RunsPage).
 *
 * is_default: at-most-one across all rows; setting one row's is_default
 * to true clears the others server-side in the same tx — UI only needs
 * to re-fetch.
 *
 * Soft-delete via is_active toggle hides a row from RunNewPage's
 * dropdown but historical runs still display the version string.
 * Hard DELETE refuses if any historical runs reference the version;
 * override with ?force=true after a second confirm.
 */
import { useCallback, useEffect, useState } from 'react';
import { authHeaders } from '@/lib/auth';

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

interface TargetVersion {
  id: number;
  name: string;
  display_order: number;
  is_active: boolean;
  is_default: boolean;
  notes: string | null;
  created_at: string;
}

function jsonHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', ...(authHeaders() as Record<string, string>) };
}

/**
 * Read an error response body and normalize FastAPI's two shapes.
 *
 * FastAPI wraps `HTTPException(detail=<dict>)` payloads under a top-level
 * `detail` key, so DELETE 409 actually serializes as:
 *   { "detail": { "detail": "...message...", "run_count": N } }
 * but 400s with a plain string come back as:
 *   { "detail": "name is required" }
 *
 * Normalize both:
 *   - nested dict → promote inner fields (treat as the flat shape)
 *   - flat       → return as-is
 *
 * Caller then reads `.detail` (string message) and `.run_count` uniformly.
 */
async function readDetail(
  resp: Response,
): Promise<{ detail?: string; run_count?: number } | null> {
  try {
    const body: unknown = await resp.json();
    if (body && typeof body === 'object') {
      const obj = body as { detail?: unknown; run_count?: number };
      // Nested case: FastAPI HTTPException(detail={...}) — unwrap one level.
      if (obj.detail && typeof obj.detail === 'object') {
        return obj.detail as { detail?: string; run_count?: number };
      }
      // Flat case: plain {detail: "string"} or {detail: "string", run_count: N}.
      return obj as { detail?: string; run_count?: number };
    }
    return null;
  } catch {
    return null;
  }
}

export default function AdminTargetVersionsPage() {
  const [rows, setRows] = useState<TargetVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ name: '', display_order: '100', notes: '' });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState({ name: '', display_order: '100', notes: '' });

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/admin/target-versions`, { headers: authHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = (await resp.json()) as TargetVersion[];
      setRows(data);
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
      const name = draft.name.trim();
      if (!name) throw new Error('name is required');
      const body: Record<string, unknown> = { name };
      const order = Number.parseInt(draft.display_order, 10);
      if (Number.isFinite(order)) body.display_order = order;
      if (draft.notes.trim()) body.notes = draft.notes.trim();
      const resp = await fetch(`${API_BASE}/admin/target-versions`, {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const detail = await readDetail(resp);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      setDraft({ name: '', display_order: '100', notes: '' });
      await refresh();
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function patchRow(id: number, patch: Record<string, unknown>) {
    try {
      const resp = await fetch(`${API_BASE}/admin/target-versions/${id}`, {
        method: 'PATCH',
        headers: jsonHeaders(),
        body: JSON.stringify(patch),
      });
      if (!resp.ok) {
        const detail = await readDetail(resp);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(row: TargetVersion) {
    if (!window.confirm(`Delete target version "${row.name}"?`)) return;
    const tryDelete = async (force: boolean) =>
      fetch(`${API_BASE}/admin/target-versions/${row.id}${force ? '?force=true' : ''}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
    try {
      let resp = await tryDelete(false);
      if (resp.status === 409) {
        const detail = await readDetail(resp);
        const n = detail?.run_count ?? 0;
        const ok = window.confirm(
          `Version "${row.name}" is referenced by ${n} historical run(s). ` +
            `Force delete? Those runs will keep the version string as-is.`,
        );
        if (!ok) return;
        resp = await tryDelete(true);
      }
      if (!resp.ok && resp.status !== 204) {
        const detail = await readDetail(resp);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function startEdit(row: TargetVersion) {
    setEditingId(row.id);
    setEditDraft({
      name: row.name,
      display_order: String(row.display_order),
      notes: row.notes ?? '',
    });
  }

  async function saveEdit() {
    if (editingId === null) return;
    const patch: Record<string, unknown> = {
      name: editDraft.name.trim(),
      notes: editDraft.notes.trim() === '' ? null : editDraft.notes.trim(),
    };
    const order = Number.parseInt(editDraft.display_order, 10);
    if (Number.isFinite(order)) patch.display_order = order;
    await patchRow(editingId, patch);
    setEditingId(null);
  }

  return (
    <div data-testid="admin-target-versions-page" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Target Versions</h1>
      <p className="text-sm text-muted-foreground">
        Maintain the catalog used by "Trigger New Run → Target version".
        Inactive rows are hidden from the dropdown; the at-most-one
        Default row is preselected. Historical runs keep the string they
        were created with regardless of edits here.
      </p>

      <form
        data-testid="admin-target-versions-add-form"
        onSubmit={handleAdd}
        className="grid gap-2 max-w-2xl border rounded p-3"
      >
        <input
          data-testid="admin-target-versions-add-name-input"
          placeholder="name (required, e.g. SynxDB-4.6.0-build42)"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="admin-target-versions-add-order-input"
          placeholder="display_order (integer, default 100)"
          type="number"
          value={draft.display_order}
          onChange={(e) => setDraft({ ...draft, display_order: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <input
          data-testid="admin-target-versions-add-notes-input"
          placeholder="notes (optional)"
          value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
          className="border px-2 py-1 rounded"
        />
        <button
          type="submit"
          data-testid="admin-target-versions-add-button"
          disabled={submitting}
          className="bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
        >
          {submitting ? 'Adding…' : '+ Add version'}
        </button>
        {submitError !== null && (
          <div data-testid="admin-target-versions-add-error" className="text-sm text-red-600">
            {submitError}
          </div>
        )}
      </form>

      {error !== null && (
        <div data-testid="admin-target-versions-error" className="text-sm text-red-600">
          {error}
        </div>
      )}

      {rows === null ? (
        <div data-testid="admin-target-versions-loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div data-testid="admin-target-versions-empty" className="text-sm text-muted-foreground">
          No target versions yet. Add one to populate the Trigger New Run dropdown.
        </div>
      ) : (
        <table data-testid="admin-target-versions-table" className="w-full text-sm">
          <thead>
            <tr>
              <th className="text-left">ID</th>
              <th className="text-left">Name</th>
              <th className="text-left">Order</th>
              <th className="text-left">Active</th>
              <th className="text-left">Default</th>
              <th className="text-left">Notes</th>
              <th className="text-left">Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const editing = editingId === r.id;
              return (
                <tr
                  key={r.id}
                  data-testid={`admin-target-versions-row-${r.id}`}
                  className={r.is_active ? '' : 'opacity-50'}
                >
                  <td className="font-mono">{r.id}</td>
                  <td className="font-mono">
                    {editing ? (
                      <input
                        data-testid={`admin-target-versions-edit-name-${r.id}`}
                        value={editDraft.name}
                        onChange={(e) => setEditDraft({ ...editDraft, name: e.target.value })}
                        className="border px-2 py-0.5 rounded text-xs w-full"
                      />
                    ) : (
                      <span data-testid={`admin-target-versions-name-${r.id}`}>{r.name}</span>
                    )}
                  </td>
                  <td className="font-mono text-xs">
                    {editing ? (
                      <input
                        data-testid={`admin-target-versions-edit-order-${r.id}`}
                        type="number"
                        value={editDraft.display_order}
                        onChange={(e) =>
                          setEditDraft({ ...editDraft, display_order: e.target.value })
                        }
                        className="border px-2 py-0.5 rounded text-xs w-16"
                      />
                    ) : (
                      r.display_order
                    )}
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      data-testid={`admin-target-versions-active-toggle-${r.id}`}
                      checked={r.is_active}
                      onChange={() => void patchRow(r.id, { is_active: !r.is_active })}
                    />
                  </td>
                  <td>
                    <input
                      type="radio"
                      name="target-version-default"
                      data-testid={`admin-target-versions-default-radio-${r.id}`}
                      checked={r.is_default}
                      onChange={() => void patchRow(r.id, { is_default: true })}
                    />
                  </td>
                  <td className="text-xs">
                    {editing ? (
                      <input
                        data-testid={`admin-target-versions-edit-notes-${r.id}`}
                        value={editDraft.notes}
                        onChange={(e) => setEditDraft({ ...editDraft, notes: e.target.value })}
                        className="border px-2 py-0.5 rounded text-xs w-full"
                      />
                    ) : (
                      r.notes ?? '—'
                    )}
                  </td>
                  <td className="font-mono text-xs">{r.created_at?.slice(0, 19) ?? '—'}</td>
                  <td className="space-x-2 whitespace-nowrap">
                    {editing ? (
                      <>
                        <button
                          type="button"
                          data-testid={`admin-target-versions-save-${r.id}`}
                          onClick={() => void saveEdit()}
                          className="text-blue-700 hover:underline text-xs"
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          data-testid={`admin-target-versions-cancel-${r.id}`}
                          onClick={() => setEditingId(null)}
                          className="text-gray-600 hover:underline text-xs"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          data-testid={`admin-target-versions-edit-${r.id}`}
                          onClick={() => startEdit(r)}
                          className="text-blue-700 hover:underline text-xs"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          data-testid={`admin-target-versions-delete-${r.id}`}
                          onClick={() => void handleDelete(r)}
                          className="text-red-600 hover:underline text-xs"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
