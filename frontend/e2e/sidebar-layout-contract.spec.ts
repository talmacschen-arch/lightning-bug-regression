/**
 * M5-1 — Sidebar layout contract test (§14 R2).
 *
 * Verifies:
 *   - Sidebar nav links are present (data-testid)
 *   - Clicking Cases / Runs nav links transitions URL correctly
 *   - Breadcrumb reflects current path
 *   - Active-run pip renders and calls GET /runs?limit=1
 *   - Admin link is disabled (no href navigation)
 *
 * All API calls intercepted via page.route() — no real backend needed.
 *
 * §14 R8 — skip at declaration level when chromium can't launch.
 */
import { test, expect } from '@playwright/test';
import { chromiumCanLaunch, SKIP_REASON } from './_helpers';

const canLaunch = chromiumCanLaunch();

const FAKE_CATEGORIES = [
  {
    name: 'smoke',
    display_name: 'Smoke',
    description: null,
    id_prefix: 'smoke-',
    dir_path: 'cases/smoke',
    status_whitelist: [],
    default_status: 'active',
    display_order: 1,
  },
];

const FAKE_CASES = [
  {
    id: 'smoke-001',
    category: 'smoke',
    title: 'First smoke',
    status: 'active',
    destructive: false,
    tags: null,
    error: null,
  },
];

const FAKE_RUNS = [
  {
    id: 42,
    status: 'pass',
    started_at: new Date(Date.now() - 4 * 3_600_000).toISOString(),
    finished_at: null,
    total: 10,
    passed: 8,
    failed: 2,
    skipped: 0,
    target_version: null,
    triggered_by: null,
  },
];

/** Wire up all common API mocks needed to render the layout */
async function setupApiMocks(
  page: import('@playwright/test').Page,
  runsPayload: unknown = FAKE_RUNS,
) {
  await page.route('**/admin/categories', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(FAKE_CATEGORIES),
    }),
  );

  await page.route('**/runs**', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(runsPayload),
      });
    }
    return route.continue();
  });

  await page.route('**/cases**', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAKE_CASES),
      });
    }
    return route.continue();
  });
}

test.describe('M5-1 Sidebar layout contract', () => {
  test.skip(!canLaunch, SKIP_REASON);

  test('sidebar nav links are present with required data-testid', async ({
    page,
  }) => {
    await setupApiMocks(page);
    await page.goto('/cases');

    await expect(
      page.getByTestId('sidebar-nav-dashboard'),
    ).toBeVisible();
    await expect(page.getByTestId('sidebar-nav-cases')).toBeVisible();
    await expect(page.getByTestId('sidebar-nav-runs')).toBeVisible();
    await expect(page.getByTestId('sidebar-nav-admin')).toBeVisible();
    await expect(page.getByTestId('main-content')).toBeVisible();
    await expect(page.getByTestId('breadcrumb')).toBeVisible();
  });

  test('clicking Cases nav link navigates to /cases', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/runs');

    await page.getByTestId('sidebar-nav-cases').click();
    await expect(page).toHaveURL(/\/cases/);
  });

  test('clicking Runs nav link navigates to /runs', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/cases');

    await page.getByTestId('sidebar-nav-runs').click();
    await expect(page).toHaveURL(/\/runs/);
  });

  test('breadcrumb reflects /cases path', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/cases');

    const bc = page.getByTestId('breadcrumb');
    await expect(bc).toContainText('Cases');
  });

  test('breadcrumb reflects /runs path', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/runs');

    const bc = page.getByTestId('breadcrumb');
    await expect(bc).toContainText('Runs');
  });

  test('active-run pip renders and calls GET /runs?limit=1', async ({
    page,
  }) => {
    let runsRequestUrl: string | null = null;

    await page.route('**/admin/categories', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAKE_CATEGORIES),
      }),
    );

    // Capture the /runs GET request URL
    await page.route('**/runs**', (route) => {
      if (route.request().method() === 'GET') {
        runsRequestUrl = route.request().url();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(FAKE_RUNS),
        });
      }
      return route.continue();
    });

    await page.route('**/cases**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAKE_CASES),
      }),
    );

    await page.goto('/cases');

    // Wait for pip to appear
    await expect(page.getByTestId('sidebar-active-run-pip')).toBeVisible();

    // The pip must have triggered a /runs call with limit=1
    expect(runsRequestUrl).not.toBeNull();
    expect(runsRequestUrl).toContain('limit=1');
  });

  test('active-run pip shows green for pass run', async ({ page }) => {
    await setupApiMocks(page, FAKE_RUNS); // FAKE_RUNS has status: 'pass'
    await page.goto('/cases');

    const pip = page.getByTestId('sidebar-active-run-pip');
    await expect(pip).toBeVisible();

    // The green dot is a child span with bg-green-500 class
    const dot = pip.locator('span.rounded-full');
    await expect(dot).toHaveClass(/bg-green-500/);
  });

  test('active-run pip shows grey when no runs exist', async ({ page }) => {
    await setupApiMocks(page, []); // empty array
    await page.goto('/cases');

    const pip = page.getByTestId('sidebar-active-run-pip');
    await expect(pip).toBeVisible();

    const dot = pip.locator('span.rounded-full');
    await expect(dot).toHaveClass(/bg-gray-400/);
  });

  test('Admin nav link does not navigate (is disabled)', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/cases');

    const adminEl = page.getByTestId('sidebar-nav-admin');
    await expect(adminEl).toBeVisible();

    // Disabled element should not be an anchor (no href)
    const tagName = await adminEl.evaluate((el) => el.tagName.toLowerCase());
    expect(tagName).not.toBe('a');

    // aria-disabled should be true
    await expect(adminEl).toHaveAttribute('aria-disabled', 'true');
  });
});
