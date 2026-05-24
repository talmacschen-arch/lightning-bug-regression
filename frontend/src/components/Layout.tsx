/**
 * M5-1 minimal sidebar — replaces top nav.
 *
 * Deliberately minimal compared to PR #94 attempt:
 *  - No useEffect + apiFetch on mount (no async render dependency)
 *  - No responsive collapse (always 240px sidebar, labels always visible)
 *  - No import.meta.env access in footer
 *  - Plain CSS classes / inline styles, NOT Tailwind responsive (`lg:*`),
 *    so generation/visibility doesn't depend on viewport breakpoints
 *
 * Rationale: PR #94 attempted full-feature sidebar (responsive + apiFetch
 * + env-driven footer) and failed 9/15 playwright e2e tests with "element
 * not found" — root cause not visible from CI logs. Reducing surface area
 * to "minimal sidebar that's structurally hard to break", then iterating
 * upward (M5-2 will add the active-run pip via Dashboard data).
 *
 * data-testid contract for tests (per design.md §13.11 / §17 R6):
 *   sidebar-nav-dashboard / -cases / -runs / -admin (disabled)
 *   sidebar-active-run-pip  (static grey for now; M5-2 will wire data)
 *   breadcrumb / main-content
 */
import { Link, Outlet, useLocation, NavLink } from 'react-router-dom';

interface NavItemProps {
  to: string;
  label: string;
  testId: string;
  disabled?: boolean;
}

function NavItem({ to, label, testId, disabled }: NavItemProps) {
  if (disabled) {
    return (
      <span
        data-testid={testId}
        title="Coming soon"
        aria-disabled="true"
        className="sidebar-nav-item sidebar-nav-item--disabled"
      >
        {label}
      </span>
    );
  }
  return (
    <NavLink
      to={to}
      data-testid={testId}
      className={({ isActive }) =>
        isActive ? 'sidebar-nav-item sidebar-nav-item--active' : 'sidebar-nav-item'
      }
    >
      {label}
    </NavLink>
  );
}

function pathToBreadcrumb(pathname: string): string {
  if (pathname === '/' || pathname === '/dashboard') return 'Dashboard';
  if (pathname.startsWith('/cases/new')) return 'Cases / New';
  if (pathname.startsWith('/cases/')) return 'Cases / Detail';
  if (pathname === '/cases') return 'Cases';
  if (pathname.startsWith('/runs/new')) return 'Runs / New';
  if (pathname.startsWith('/runs/diff')) return 'Runs / Diff';
  if (pathname.startsWith('/runs/')) return 'Runs / Detail';
  if (pathname === '/runs') return 'Runs';
  if (pathname === '/admin') return 'Admin';
  if (pathname.startsWith('/admin/skip-list')) return 'Admin / Skip list';
  if (pathname.startsWith('/admin/external-services')) return 'Admin / External services';
  return pathname;
}

export function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="app-shell-v2">
      <aside className="sidebar" data-testid="sidebar">
        <Link to="/" className="sidebar-brand">
          Lightning Bug Regression
        </Link>
        <nav className="sidebar-nav">
          <NavItem to="/dashboard" label="Dashboard" testId="sidebar-nav-dashboard" />
          <NavItem to="/cases" label="Cases" testId="sidebar-nav-cases" />
          <NavItem to="/runs" label="Runs" testId="sidebar-nav-runs" />
          <NavItem to="/admin" label="Admin" testId="sidebar-nav-admin" />
        </nav>
        <div
          data-testid="sidebar-active-run-pip"
          className="sidebar-active-run-pip"
          title="No recent runs (M5-2 will wire data)"
        >
          <span className="pip-dot pip-dot--grey" aria-label="no recent runs" />
          <span className="pip-label">No recent runs</span>
        </div>
      </aside>
      <div className="main-area" data-testid="main-content">
        <div className="breadcrumb" data-testid="breadcrumb">
          {pathToBreadcrumb(pathname)}
        </div>
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
