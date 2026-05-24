/**
 * Admin landing — links to /admin/skip-list and /admin/settings (M6-4).
 */
import { Link } from 'react-router-dom';

export default function AdminPage() {
  return (
    <div data-testid="page-admin" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Admin</h1>
      <p className="text-sm text-muted-foreground">
        Runtime tunables only. Schema-level changes (case categories /
        step kinds) live in code and migrate via PR.
      </p>
      <ul className="space-y-2">
        <li>
          <Link
            to="/admin/skip-list"
            data-testid="admin-link-skip-list"
            className="text-blue-700 hover:underline"
          >
            Skip list →
          </Link>
          <span className="ml-2 text-xs text-muted-foreground">
            Mark a case as "do not run" with a reason (e.g. intermittent BUG, env issue)
          </span>
        </li>
        <li>
          <Link
            to="/admin/settings"
            data-testid="admin-link-settings"
            className="text-blue-700 hover:underline"
          >
            Settings →
          </Link>
          <span className="ml-2 text-xs text-muted-foreground">
            jinja_context / dut_hosts / server_log_path
          </span>
        </li>
      </ul>
    </div>
  );
}
