/**
 * M5-1 — Sidebar + main content two-column layout.
 *
 * Replaces the original top-nav layout with:
 *  - Sidebar (240px fixed): logo, nav links, active-run pip
 *  - Main content area: breadcrumb, <Outlet />, footer
 *
 * shadcn/ui Sidebar and Breadcrumb components are NOT yet installed (only
 * badge/button/card/dialog/skeleton/tabs/toast are present in ui/).  Rather
 * than adding them via `shadcn add` mid-sprint (which would pull in 900+ LOC
 * of extra primitives), this file implements the same visual contract using
 * Tailwind classes + lucide-react icons directly.  The data-testid contract
 * (R6) is the same regardless of the underlying primitives.
 *
 * API call: active-run pip calls GET /runs?limit=1 via apiFetch (R27 —
 * no inline fetch URL).
 */
import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation, NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderOpen,
  Play,
  Settings,
  Zap,
} from 'lucide-react';
import { apiFetch } from '../api/client';
import type { components } from '../api/client';

type RunSummary = components['schemas']['RunSummary'];

// ---------------------------------------------------------------------------
// Active-run pip
// ---------------------------------------------------------------------------

type PipColor = 'green' | 'red' | 'yellow' | 'grey';

function statusToPipColor(status: string): PipColor {
  if (status === 'pass') return 'green';
  if (status === 'fail') return 'red';
  if (status === 'running') return 'yellow';
  return 'grey';
}

const PIP_CLASSES: Record<PipColor, string> = {
  green: 'bg-green-500',
  red: 'bg-red-500',
  yellow: 'bg-yellow-400',
  grey: 'bg-gray-400',
};

function formatRelative(dateStr: string): string {
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const diffH = Math.floor(diffMs / 3_600_000);
  if (diffH < 1) {
    const diffM = Math.floor(diffMs / 60_000);
    return `${diffM}m ago`;
  }
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}

function ActiveRunPip() {
  const [run, setRun] = useState<RunSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/runs', 'get', { query: { limit: 1 } })
      .then((data) => {
        if (cancelled) return;
        const list = data as RunSummary[];
        setRun(list.length > 0 ? list[0] : null);
      })
      .catch(() => {
        // Silently ignore — pip becomes grey (no run data)
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const color = run ? statusToPipColor(run.status) : 'grey';
  const tooltip = run
    ? `Run #${run.id} ${run.status.toUpperCase()} ${formatRelative(run.started_at)}`
    : 'No recent runs';

  return (
    <div
      data-testid="sidebar-active-run-pip"
      className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground"
      title={tooltip}
    >
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full flex-shrink-0 ${PIP_CLASSES[color]}`}
        aria-label={tooltip}
      />
      <span className="truncate">{tooltip}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Breadcrumb
// ---------------------------------------------------------------------------

function pathToBreadcrumbs(pathname: string): { label: string; to: string }[] {
  const crumbs: { label: string; to: string }[] = [];
  const segments = pathname.split('/').filter(Boolean);
  let acc = '';
  for (const seg of segments) {
    acc += '/' + seg;
    const label =
      seg === 'cases'
        ? 'Cases'
        : seg === 'new'
          ? 'New'
          : seg === 'runs'
            ? 'Runs'
            : seg === 'dashboard'
              ? 'Dashboard'
              : seg;
    crumbs.push({ label, to: acc });
  }
  return crumbs;
}

function Breadcrumb() {
  const { pathname } = useLocation();
  const crumbs = pathToBreadcrumbs(pathname);

  return (
    <nav
      data-testid="breadcrumb"
      aria-label="breadcrumb"
      className="flex items-center gap-1 text-sm text-muted-foreground px-6 py-3 border-b border-border"
    >
      <Link to="/" className="hover:text-foreground transition-colors">
        Home
      </Link>
      {crumbs.map((crumb, i) => (
        <span key={crumb.to} className="flex items-center gap-1">
          <span className="text-muted-foreground/50">/</span>
          {i === crumbs.length - 1 ? (
            <span className="text-foreground font-medium">{crumb.label}</span>
          ) : (
            <Link
              to={crumb.to}
              className="hover:text-foreground transition-colors"
            >
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Sidebar nav items
// ---------------------------------------------------------------------------

interface NavItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  testId: string;
  disabled?: boolean;
  disabledTooltip?: string;
}

function NavItem({
  to,
  icon,
  label,
  testId,
  disabled,
  disabledTooltip,
}: NavItemProps) {
  if (disabled) {
    return (
      <span
        data-testid={testId}
        title={disabledTooltip}
        className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-muted-foreground/50 cursor-not-allowed select-none"
        aria-disabled="true"
      >
        {icon}
        <span className="lg:inline hidden">{label}</span>
      </span>
    );
  }

  return (
    <NavLink
      to={to}
      data-testid={testId}
      className={({ isActive }) =>
        [
          'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
          isActive
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
        ].join(' ')
      }
    >
      {icon}
      <span className="lg:inline hidden">{label}</span>
    </NavLink>
  );
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-14 lg:w-60 flex-shrink-0 border-r border-border bg-card flex flex-col">
        {/* Logo / app title */}
        <div className="flex items-center gap-2 px-3 py-4 border-b border-border">
          <Zap className="h-5 w-5 flex-shrink-0 text-primary" aria-hidden />
          <span className="lg:inline hidden font-semibold text-sm leading-tight">
            Lightning Bug Regression
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 flex flex-col gap-1 p-2 overflow-y-auto">
          <NavItem
            to="/dashboard"
            icon={<LayoutDashboard className="h-4 w-4 flex-shrink-0" />}
            label="Dashboard"
            testId="sidebar-nav-dashboard"
          />
          <NavItem
            to="/cases"
            icon={<FolderOpen className="h-4 w-4 flex-shrink-0" />}
            label="Cases"
            testId="sidebar-nav-cases"
          />
          <NavItem
            to="/runs"
            icon={<Play className="h-4 w-4 flex-shrink-0" />}
            label="Runs"
            testId="sidebar-nav-runs"
          />
          <NavItem
            to="/admin"
            icon={<Settings className="h-4 w-4 flex-shrink-0" />}
            label="Admin"
            testId="sidebar-nav-admin"
            disabled
            disabledTooltip="Coming soon"
          />
        </nav>

        {/* Active-run pip */}
        <div className="border-t border-border">
          <ActiveRunPip />
        </div>
      </aside>

      {/* Main content */}
      <div
        data-testid="main-content"
        className="flex-1 flex flex-col overflow-hidden"
      >
        <Breadcrumb />

        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>

        <footer className="border-t border-border px-6 py-2 text-xs text-muted-foreground flex items-center justify-between flex-shrink-0">
          <span>Lightning Bug Regression</span>
          <span>
            {import.meta.env.VITE_APP_ENV ?? 'dev'} &middot;{' '}
            {import.meta.env.VITE_APP_VERSION ?? '0.1.0'}
          </span>
        </footer>
      </div>
    </div>
  );
}
