/**
 * Admin settings list + JSON editor (M6-4).
 *
 * Each allowlisted key gets a row showing current value (pretty-printed
 * JSON) + an inline textarea to edit. Saving issues PUT /admin/settings/{key}
 * with the parsed JSON. Bad JSON shows an inline error and rejects save.
 *
 * Optional `X-Admin-Password` header from localStorage.adminPassword.
 */
import { useCallback, useEffect, useState } from 'react';

const API_BASE =
  ((import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
    ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

// Must mirror backend admin.py ADMIN_EDITABLE_SETTINGS — only keys
// with a real runtime consumer. dev_db_url / cluster_topology were
// removed 2026-05-25; they had no consumer.
const EDITABLE_KEYS = [
  'jinja_context',
  'dut_hosts',
  'server_log_path',
] as const;

interface SettingEntry {
  key: string;
  value: unknown;
  value_type: string;
  updated_at: string;
}

function adminHeaders(extra?: Record<string, string>): HeadersInit {
  const pw = typeof localStorage !== 'undefined' ? localStorage.getItem('adminPassword') : null;
  const h: Record<string, string> = { ...extra };
  if (pw) h['X-Admin-Password'] = pw;
  return h;
}

function SettingEditor({
  settingKey,
  currentValue,
  onSaved,
}: {
  settingKey: string;
  currentValue: unknown;
  onSaved: () => void;
}) {
  const initialJson =
    currentValue === undefined ? '{}' : JSON.stringify(currentValue, null, 2);
  const [draft, setDraft] = useState(initialJson);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft);
    } catch (e) {
      setSaveError(`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`);
      setSaving(false);
      return;
    }
    try {
      const resp = await fetch(`${API_BASE}/admin/settings/${encodeURIComponent(settingKey)}`, {
        method: 'PUT',
        headers: adminHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ value: parsed }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${resp.status}`);
      }
      const body = await resp.json();
      setSavedAt(body.updated_at);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      data-testid={`settings-key-${settingKey}`}
      className="border rounded p-3 space-y-1"
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono font-semibold text-sm">{settingKey}</span>
        {savedAt !== null && (
          <span className="text-xs text-green-700">Saved {savedAt}</span>
        )}
      </div>
      <textarea
        data-testid={`settings-textarea-${settingKey}`}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-full font-mono text-xs border rounded p-2 min-h-[8em]"
      />
      {saveError !== null && (
        <div
          data-testid={`settings-error-${settingKey}`}
          className="text-xs text-red-600"
        >
          {saveError}
        </div>
      )}
      <button
        type="button"
        data-testid={`settings-save-${settingKey}`}
        onClick={() => void handleSave()}
        disabled={saving}
        className="bg-blue-600 text-white rounded px-2 py-1 text-sm disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<SettingEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/admin/settings`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setSettings(await resp.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const byKey = new Map<string, SettingEntry>(
    (settings ?? []).map((s) => [s.key, s]),
  );

  return (
    <div data-testid="page-admin-settings" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <p className="text-sm text-muted-foreground">
        Each setting value must be a JSON object. Wrap scalars/lists as
        needed (e.g. <code>{`{ "hosts": ["mdw","sdw1"] }`}</code>).
      </p>

      {error !== null && (
        <div data-testid="settings-error" className="text-sm text-red-600">
          {error}
        </div>
      )}

      {settings === null ? (
        <div data-testid="settings-loading">Loading…</div>
      ) : (
        <div className="space-y-3">
          {EDITABLE_KEYS.map((k) => (
            <SettingEditor
              key={k}
              settingKey={k}
              currentValue={byKey.get(k)?.value}
              onSaved={() => void refresh()}
            />
          ))}
        </div>
      )}
    </div>
  );
}
