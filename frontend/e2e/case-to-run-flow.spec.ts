/**
 * M2-9 end-to-end happy-path test: cases → select category → submit run → see PASS.
 *
 * All API calls are intercepted via page.route() — no real backend needed.
 *
 * §14 R6  — every selector uses data-testid; no CSS selectors or text matching.
 * §14 R8  — skip at declaration level when chromium cannot launch on this host.
 * §14 R24 — verified locally: tsc + lint + vitest all green before commit.
 */
import { test, expect } from '@playwright/test';
import { chromiumCanLaunch, SKIP_REASON } from './_helpers';

const canLaunch = chromiumCanLaunch();

const FAKE_CATEGORIES = [
  {
    name: 'bug_regression',
    display_name: 'Bug Regression',
    id_prefix: 'bug-',
    dir_path: 'cases/bug_regression',
    status_whitelist: [],
    default_status: 'active',
    display_order: 1,
    description: null,
  },
  {
    name: 'extension',
    display_name: 'Extension',
    id_prefix: 'ext-',
    dir_path: 'cases/extension',
    status_whitelist: [],
    default_status: 'active',
    display_order: 2,
    description: null,
  },
];

const FAKE_CASES_BUG = [
  { id: 'bug-001', category: 'bug_regression', title: 'Bug 1', status: 'active', destructive: false, tags: null, error: null },
  { id: 'bug-002', category: 'bug_regression', title: 'Bug 2', status: 'active', destructive: false, tags: null, error: null },
  { id: 'bug-003', category: 'bug_regression', title: 'Bug 3', status: 'active', destructive: false, tags: null, error: null },
];

const FAKE_RUN_TERMINAL = {
  id: 99,
  status: 'pass',
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:01:00Z',
  target_version: '5.1.0',
  triggered_by: null,
  total: 3,
  passed: 3,
  failed: 0,
  skipped: 0,
  case_results: [
    { case_id: 'bug-001', status: 'pass', duration_ms: 1000, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-002', status: 'pass', duration_ms: 1100, skip_reason: null, expect_detail: null, artifacts_path: null },
    { case_id: 'bug-003', status: 'pass', duration_ms: 1050, skip_reason: null, expect_detail: null, artifacts_path: null },
  ],
};

test.describe('M2-9 case → run → result happy path', () => {
  // §14 R8: skip at declaration level when chromium can't launch
  test.skip(!canLaunch, SKIP_REASON);

  test('end to end: pick category → select cases → submit run → see PASS', async ({ page }) => {
    // Stub categories
    await page.route('**/admin/categories', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAKE_CATEGORIES),
      }),
    );

    // Stub cases — branch on category query param
    await page.route('**/cases?**', (route) => {
      const url = new URL(route.request().url());
      const category = url.searchParams.get('category');
      if (category === 'bug_regression') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(FAKE_CASES_BUG),
        });
      }
      // extension (and any other) → empty
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    // Capture POST /runs body and fulfill with 202
    let postBody: unknown = null;
    await page.route('**/runs', (route) => {
      if (route.request().method() === 'POST') {
        postBody = route.request().postDataJSON() as unknown;
        return route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 99,
            status: 'running',
            started_at: '2026-01-01T00:00:00Z',
            location: '/runs/99',
          }),
        });
      }
      return route.continue();
    });

    // Stub GET /runs/99 — return terminal run immediately
    await page.route('**/runs/99', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FAKE_RUN_TERMINAL),
      }),
    );

    // 1. Navigate to /cases
    await page.goto('/cases');

    // 2. Wait for bug_regression tab to appear
    await page.waitForSelector('[data-testid="tab-bug_regression"]');

    // Extra: click extension tab to exercise empty-state path, then switch back
    await page.click('[data-testid="tab-extension"]');
    await page.waitForSelector('[data-testid="cases-empty-extension"]');
    await page.click('[data-testid="tab-bug_regression"]');

    // 3. Click bug_regression tab (already done via back-click above, but explicit for clarity)
    await page.waitForSelector('[data-testid="cases-list-bug_regression"]');

    // 5. Assert 3 case cards are visible
    await expect(page.locator('[data-testid^="case-card-bug-"]')).toHaveCount(3);

    // 6. Navigate to /runs/new
    await page.goto('/runs/new');

    // 7. Wait for checkboxes to appear
    await page.waitForSelector('[data-testid="case-checkbox-bug-001"]');

    // 8. Select all cases via global select-all
    await page.click('[data-testid="select-all-global"]');

    // 9. Fill in target version
    await page.fill('[data-testid="input-target-version"]', '5.1.0');

    // 10. Submit
    await page.click('[data-testid="btn-submit-run"]');

    // 11. Wait for navigation to /runs/99
    await page.waitForURL('**/runs/99');

    // 12. Wait for run-status-badge to appear
    await page.waitForSelector('[data-testid="run-status-badge"]');

    // 13. Assert status badge shows PASS
    await expect(page.getByTestId('run-status-badge')).toContainText('PASS');

    // 14. Assert 3 case rows are present
    await expect(page.locator('[data-testid^="run-case-row-bug-"]')).toHaveCount(3);

    // 15. Assert POST body had correct shape
    expect(postBody).not.toBeNull();
    expect((postBody as { case_ids: string[]; target_version: string }).case_ids).toHaveLength(3);
    expect((postBody as { case_ids: string[]; target_version: string }).target_version).toBe('5.1.0');
  });
});
