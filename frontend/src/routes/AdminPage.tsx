/**
 * Admin landing — link to /admin/skip-list (M6-4 + post-Settings refactor).
 *
 * Settings sub-page removed 2026-05-25 — the 3 keys it allowlisted had
 * effectively no real consumers, and DUT connection moved to
 * external/dut.yml (M6-5 external_deps mechanism). External system config
 * (ES URL, Hive params, etc.) lives under `external/<svc>.yml` files,
 * which are git-tracked and edited via the filesystem.
 */
import { Link } from 'react-router-dom';

export default function AdminPage() {
  return (
    <div data-testid="page-admin" className="p-6 space-y-4">
      <h1 className="text-xl font-semibold">Admin</h1>
      <p className="text-sm text-muted-foreground">
        Runtime tunables only. Schema-level changes (case categories / step
        kinds) live in code and migrate via PR; DUT connection + external
        service configs live under <code>external/&lt;svc&gt;.yml</code>.
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
      </ul>
    </div>
  );
}
