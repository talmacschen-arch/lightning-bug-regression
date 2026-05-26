/**
 * LoginPage — single-user login form (v1.17).
 *
 * On success, token is stored in localStorage by `lib/auth.login()` and
 * user is navigated to / (Dashboard via Navigate-replace, then router
 * shows whatever was deep-linked via `?next=` if present).
 *
 * UI is intentionally minimal — no "remember me" / no "forgot password"
 * (single-user tool, password reset = CLI on backend).
 *
 * 初始账号 admin / admin — hint shown if password_changed_at is null
 * (i.e. first boot, never customized). Hint disappears after first
 * change-password.
 */
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { login } from '@/lib/auth';

export default function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      const next = searchParams.get('next') || '/dashboard';
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      data-testid="page-login"
      className="min-h-screen flex items-center justify-center bg-gray-50"
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white p-6 rounded shadow w-80 space-y-3"
      >
        <h1 className="text-xl font-semibold">Lightning Bug Regression</h1>

        <div className="space-y-1">
          <label htmlFor="login-username" className="text-xs text-gray-600">
            Username
          </label>
          <input
            id="login-username"
            data-testid="login-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            className="w-full border px-2 py-1 rounded"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="login-password" className="text-xs text-gray-600">
            Password
          </label>
          <input
            id="login-password"
            data-testid="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="w-full border px-2 py-1 rounded"
          />
        </div>

        {error !== null && (
          <div data-testid="login-error" className="text-xs text-red-600">
            {error}
          </div>
        )}

        <button
          type="submit"
          data-testid="login-submit"
          disabled={submitting}
          className="w-full bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
