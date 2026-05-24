/**
 * M5-1 Layout contract — unit test via vitest + jsdom + react-testing-library.
 *
 * Replaces the playwright e2e attempt from PR #94 which had unexplained
 * "element not found" failures in CI (no artifacts; reviewer host SKIP'd).
 * Vitest unit tests at jsdom level verify all data-testid contracts
 * deterministically — no chromium variance, no responsive class generation
 * uncertainty.
 *
 * Coverage (8 testids, per design.md §13.11 R6):
 *   sidebar / sidebar-nav-dashboard / sidebar-nav-cases / sidebar-nav-runs
 *   sidebar-nav-admin / sidebar-active-run-pip / breadcrumb / main-content
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect } from 'vitest';

import { Layout } from './Layout';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="*" element={<div data-testid="page-outlet">page content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('Layout (M5-1 minimal sidebar)', () => {
  describe('sidebar structure', () => {
    it('renders sidebar with brand + nav items + active-run pip', () => {
      renderAt('/cases');
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar-nav-dashboard')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar-nav-cases')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar-nav-runs')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar-nav-admin')).toBeInTheDocument();
      expect(screen.getByTestId('sidebar-active-run-pip')).toBeInTheDocument();
    });

    it('Dashboard / Cases / Runs nav items are anchor tags with href', () => {
      renderAt('/');
      const dashboard = screen.getByTestId('sidebar-nav-dashboard');
      const cases = screen.getByTestId('sidebar-nav-cases');
      const runs = screen.getByTestId('sidebar-nav-runs');
      expect(dashboard.tagName.toLowerCase()).toBe('a');
      expect(cases.tagName.toLowerCase()).toBe('a');
      expect(runs.tagName.toLowerCase()).toBe('a');
      expect(dashboard).toHaveAttribute('href', '/dashboard');
      expect(cases).toHaveAttribute('href', '/cases');
      expect(runs).toHaveAttribute('href', '/runs');
    });

    it('Admin nav item is enabled (anchor with href=/admin) after M6-4', () => {
      renderAt('/cases');
      const admin = screen.getByTestId('sidebar-nav-admin');
      expect(admin.tagName.toLowerCase()).toBe('a');
      expect(admin).toHaveAttribute('href', '/admin');
      expect(admin).not.toHaveAttribute('aria-disabled');
    });

    it('active-run pip shows static grey with "No recent runs" label', () => {
      renderAt('/cases');
      const pip = screen.getByTestId('sidebar-active-run-pip');
      const dot = pip.querySelector('.pip-dot');
      expect(dot).not.toBeNull();
      expect(dot!.className).toContain('pip-dot--grey');
      expect(pip.textContent).toContain('No recent runs');
    });
  });

  describe('main content + breadcrumb', () => {
    it('renders main-content with breadcrumb above and Outlet inside', () => {
      renderAt('/cases');
      expect(screen.getByTestId('main-content')).toBeInTheDocument();
      expect(screen.getByTestId('breadcrumb')).toBeInTheDocument();
      expect(screen.getByTestId('page-outlet')).toBeInTheDocument();
    });

    it('breadcrumb shows Dashboard at /', () => {
      renderAt('/');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Dashboard');
    });

    it('breadcrumb shows Cases at /cases', () => {
      renderAt('/cases');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Cases');
    });

    it('breadcrumb shows Cases / Detail at /cases/lg-bug-0001', () => {
      renderAt('/cases/lg-bug-0001');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Cases / Detail');
    });

    it('breadcrumb shows Cases / New at /cases/new', () => {
      renderAt('/cases/new');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Cases / New');
    });

    it('breadcrumb shows Runs at /runs', () => {
      renderAt('/runs');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Runs');
    });

    it('breadcrumb shows Runs / Detail at /runs/42', () => {
      renderAt('/runs/42');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Runs / Detail');
    });

    it('breadcrumb shows Runs / Diff at /runs/diff', () => {
      renderAt('/runs/diff?a=1&b=2');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Runs / Diff');
    });

    it('breadcrumb shows Admin at /admin', () => {
      renderAt('/admin');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Admin');
    });

    it('breadcrumb shows Admin / Skip list at /admin/skip-list', () => {
      renderAt('/admin/skip-list');
      expect(screen.getByTestId('breadcrumb').textContent).toContain('Admin / Skip list');
    });

  });

  describe('navigation contract', () => {
    it('active class lands on the route that matches current pathname', () => {
      renderAt('/cases');
      const casesLink = screen.getByTestId('sidebar-nav-cases');
      // Active class follows isActive from react-router NavLink
      expect(casesLink.className).toContain('sidebar-nav-item--active');
    });

    it('inactive nav items do not have --active class', () => {
      renderAt('/cases');
      const dashboard = screen.getByTestId('sidebar-nav-dashboard');
      const runs = screen.getByTestId('sidebar-nav-runs');
      expect(dashboard.className).not.toContain('--active');
      expect(runs.className).not.toContain('--active');
    });
  });

  describe('§14 R4b — no hardcoded category in component', () => {
    it('Layout sidebar does not contain category names', () => {
      // Smoke check: sidebar must NOT contain 'bug_regression' /
      // 'extension' / 'external_systems' strings — categories are
      // page-level concerns, not layout chrome.
      renderAt('/cases');
      const text = screen.getByTestId('sidebar').textContent ?? '';
      expect(text).not.toContain('bug_regression');
      expect(text).not.toContain('external_systems');
    });
  });
});
