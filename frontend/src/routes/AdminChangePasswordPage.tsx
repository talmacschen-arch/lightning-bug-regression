/**
 * AdminChangePasswordPage — change current user's password (v1.17).
 *
 * On success:
 *   - backend updates password_hash + password_changed_at
 *   - frontend re-fetches /auth/me so the "请改密码" red banner in Layout
 *     disappears (Layout polls fetchMe on mount; we trigger a re-mount
 *     via location.reload() to refresh the global state cheaply)
 *
 * Validation (mirrors backend rules in app/api/auth.py):
 *   - new password ≥4 chars
 *   - new password ≠ current
 *   - new password = confirm password (frontend-only check)
 */
import { useState } from 'react';
import { changePassword } from '@/lib/auth';

export default function AdminChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (newPassword.length < 4) {
      setError('new password must be at least 4 characters');
      return;
    }
    if (newPassword === currentPassword) {
      setError('new password must differ from current');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('new password and confirmation do not match');
      return;
    }

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      // Refresh Layout's me state so the "must change password" banner
      // disappears (Layout fetchMe runs on mount; a soft page reload is
      // the simplest way to re-trigger that without lifting state up).
      if (typeof window !== 'undefined') {
        setTimeout(() => window.location.reload(), 1500);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div data-testid="page-admin-change-password" className="p-6 space-y-4 max-w-md">
      <h1 className="text-xl font-semibold">Change password</h1>
      <p className="text-sm text-muted-foreground">
        Current user: <code>admin</code> (single-user mode). New password must be ≥4 chars and
        differ from current.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="space-y-1">
          <label htmlFor="cp-current" className="text-xs text-gray-600">
            Current password
          </label>
          <input
            id="cp-current"
            data-testid="cp-current"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
            className="w-full border px-2 py-1 rounded"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="cp-new" className="text-xs text-gray-600">
            New password
          </label>
          <input
            id="cp-new"
            data-testid="cp-new"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            className="w-full border px-2 py-1 rounded"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="cp-confirm" className="text-xs text-gray-600">
            Confirm new password
          </label>
          <input
            id="cp-confirm"
            data-testid="cp-confirm"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            className="w-full border px-2 py-1 rounded"
          />
        </div>

        {error !== null && (
          <div data-testid="cp-error" className="text-sm text-red-600">
            {error}
          </div>
        )}

        {success && (
          <div data-testid="cp-success" className="text-sm text-green-700">
            ✓ Password changed. Refreshing…
          </div>
        )}

        <button
          type="submit"
          data-testid="cp-submit"
          disabled={submitting || success}
          className="bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </div>
  );
}
