/**
 * §6.4 R2 contract test — verifies the POST /runs body shape sent by RunNewPage.
 *
 * All API calls are intercepted via page.route() — no real backend needed.
 * The critical assertion is on route.request().postDataJSON(), which proves
 * the wire contract (case_ids array + target_version field) is actually sent.
 *
 * §14 R8 — skip condition at declaration level: if the chromium shared library
 * libgbm.so.1 is not present on this host the tests are skipped rather than
 * failing with an unintelligible launcher error.
 */
import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';

// Detect whether chromium can actually launch on this OS.
// This is a declaration-level guard per §14 R8.
function chromiumCanLaunch(): boolean {
  try {
    execSync('ldconfig -p 2>/dev/null | grep libgbm', { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

const SKIP_REASON = 'libgbm.so.1 not found — chromium cannot launch on this host (§14 R8 declaration-level skip)';
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
  { id: 'smoke-001', category: 'smoke', title: 'First smoke', status: 'active', destructive: false, tags: null, error: null },
  { id: 'smoke-002', category: 'smoke', title: 'Second smoke', status: 'active', destructive: false, tags: null, error: null },
];

test.describe('RunNewPage — POST /runs contract (§6.4 R2)', () => {
  // §14 R8: skip at declaration level when chromium can't launch
  test.skip(!canLaunch, SKIP_REASON);

  test('POST /runs body shape: case_ids array + target_version string', async ({ page }) => {
    // Stub categories endpoint
    await page.route('**/admin/categories', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CATEGORIES) }),
    );

    // Stub cases endpoint
    await page.route('**/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CASES) }),
    );

    // Capture POST /runs body and stub the 202 response
    let postBody: unknown = null;
    await page.route('**/runs', (route) => {
      if (route.request().method() === 'POST') {
        postBody = route.request().postDataJSON() as unknown;
        return route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({ run_id: 7, status: 'running', started_at: '2026-01-01T00:00:00Z', location: '/runs/7' }),
        });
      }
      return route.continue();
    });

    await page.goto('/runs/new');

    // Wait for cases to render
    await page.waitForSelector('[data-testid="case-checkbox-smoke-001"]');

    // Select both cases
    await page.click('[data-testid="case-checkbox-smoke-001"]');
    await page.click('[data-testid="case-checkbox-smoke-002"]');

    // Fill in target version
    await page.fill('[data-testid="input-target-version"]', '5.1.0');

    // Submit
    await page.click('[data-testid="btn-submit-run"]');

    // Wait for navigation to /runs/7
    await page.waitForURL('**/runs/7');

    // §6.4 R2: Assert the actual wire body shape — NOT just "button existed" / "click happened"
    expect(postBody).not.toBeNull();
    const body = postBody as { case_ids: string[]; target_version: string | null };
    expect(body).toHaveProperty('case_ids');
    expect(body).toHaveProperty('target_version');
    expect(Array.isArray(body.case_ids)).toBe(true);
    expect(body.case_ids).toHaveLength(2);
    expect(body.case_ids).toContain('smoke-001');
    expect(body.case_ids).toContain('smoke-002');
    expect(body.target_version).toBe('5.1.0');
  });

  test('POST /runs body shape: target_version is null when input is empty', async ({ page }) => {
    await page.route('**/admin/categories', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CATEGORIES) }),
    );

    await page.route('**/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CASES) }),
    );

    let postBody: unknown = null;
    await page.route('**/runs', (route) => {
      if (route.request().method() === 'POST') {
        postBody = route.request().postDataJSON() as unknown;
        return route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({ run_id: 8, status: 'running', started_at: '2026-01-01T00:00:00Z', location: '/runs/8' }),
        });
      }
      return route.continue();
    });

    await page.goto('/runs/new');
    await page.waitForSelector('[data-testid="case-checkbox-smoke-001"]');

    // Select one case, leave target_version empty
    await page.click('[data-testid="case-checkbox-smoke-001"]');
    await page.click('[data-testid="btn-submit-run"]');

    await page.waitForURL('**/runs/8');

    expect(postBody).not.toBeNull();
    const body = postBody as { case_ids: string[]; target_version: string | null };
    expect(body.case_ids).toEqual(['smoke-001']);
    expect(body.target_version).toBeNull();
  });

  test('409 conflict shows modal with link to active run', async ({ page }) => {
    await page.route('**/admin/categories', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CATEGORIES) }),
    );

    await page.route('**/cases**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_CASES) }),
    );

    await page.route('**/runs', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Run already active', active_run_id: 99 }),
        });
      }
      return route.continue();
    });

    await page.goto('/runs/new');
    await page.waitForSelector('[data-testid="case-checkbox-smoke-001"]');

    await page.click('[data-testid="case-checkbox-smoke-001"]');
    await page.click('[data-testid="btn-submit-run"]');

    // Modal should appear
    await page.waitForSelector('[data-testid="modal-active-run-conflict"]');

    const link = page.getByTestId('link-existing-run');
    await expect(link).toBeVisible();

    // Link href should point to the active run
    const href = await link.getAttribute('href');
    expect(href).toContain('/runs/99');
  });
});
