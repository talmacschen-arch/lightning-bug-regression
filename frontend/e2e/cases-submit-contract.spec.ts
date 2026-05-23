/**
 * M3a-8 contract test — verifies the POST /api/cases/submit body shape sent by CaseNewPage.
 *
 * All API calls are intercepted via page.route() — no real backend needed.
 * The critical §14 R2 assertion is on route.request().postDataJSON(), which
 * proves the wire contract ({ yaml, case_id, branch_name }) is actually sent.
 *
 * §14 R8 — skip condition at declaration level: if the chromium shared library
 * libgbm.so.1 is not present on this host the tests are skipped rather than
 * failing with an unintelligible launcher error.
 */
import { test, expect } from '@playwright/test';
import { chromiumCanLaunch, SKIP_REASON } from './_helpers';

const canLaunch = chromiumCanLaunch();

test.describe('/cases/new → /cases/submit contract (M3a-8)', () => {
  // §14 R8: skip at declaration level when chromium can't launch
  test.skip(!canLaunch, SKIP_REASON);

  test('full Validate→Try→Save flow asserts submit body shape', async ({ page }) => {
    // CaseNewPage uses API_BASE (http://127.0.0.1:8000) + path, so we route
    // against the absolute origin pattern.
    await page.route('**/api/cases/validate', async (route) => {
      const body = route.request().postDataJSON() as { yaml: string };
      expect(body).toMatchObject({ yaml: expect.any(String) });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, errors: [] }),
      });
    });

    await page.route('**/api/cases/try', async (route) => {
      const body = route.request().postDataJSON() as { yaml: string };
      expect(body).toMatchObject({ yaml: expect.any(String) });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          yaml_sha256: 'deadbeef'.repeat(8),
          step_results: [
            {
              step_id: 's1',
              kind: 'sql',
              status: 'pass',
              duration_ms: 12,
              stderr_preview: null,
              error: null,
            },
          ],
          validation_errors: [],
        }),
      });
    });

    // §14 R2: capture submit body for concrete assertions after the flow
    let submitBodyCaptured: {
      yaml: string;
      case_id: string;
      branch_name: string;
    } | null = null;
    await page.route('**/api/cases/submit', async (route) => {
      submitBodyCaptured = route.request().postDataJSON() as {
        yaml: string;
        case_id: string;
        branch_name: string;
      };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          pr_url: 'https://github.com/example/repo/pull/42',
          pr_number: 42,
          branch: 'case/lg-bug-9999-contract-test',
        }),
      });
    });

    await page.goto('/cases/new');

    const sampleYaml = [
      'id: lg-bug-9999-contract-test',
      'category: bug-regression',
      'title: contract test stub',
      'status: open',
      'steps:',
      '  - kind: sql',
      '    sql: select 1',
      '    expect: { scalar: 1 }',
    ].join('\n');

    // Fill the main YAML editor directly (textarea-yaml-editor mirrors entry state)
    await page.getByTestId('textarea-yaml-editor').fill(sampleYaml);

    // Click Validate — always enabled
    await page.getByTestId('btn-validate').click();

    // Try button should be enabled after validate-ok
    await expect(page.getByTestId('btn-try')).toBeEnabled();
    await page.getByTestId('btn-try').click();

    // Step result row proves /try response was consumed
    await expect(page.getByTestId('try-step-row-0')).toBeVisible();

    // Save button should be enabled after try-ok
    await expect(page.getByTestId('btn-save')).toBeEnabled();
    await page.getByTestId('btn-save').click();

    // PR URL link proves /submit response was consumed
    await expect(page.getByTestId('link-pr-url')).toBeVisible();

    // ============================================================
    // §14 R2 contract assertion — the critical part
    // postDataJSON() proves the wire body was actually sent
    // ============================================================
    expect(submitBodyCaptured).not.toBeNull();
    expect(submitBodyCaptured).toMatchObject({
      yaml: expect.any(String),
      case_id: expect.any(String),
      branch_name: expect.any(String),
    });
    // Concrete value assertions — these fail if the component wiring breaks
    expect(submitBodyCaptured!.case_id).toBe('lg-bug-9999-contract-test');
    expect(submitBodyCaptured!.branch_name).toBe('case/lg-bug-9999-contract-test');
    expect(submitBodyCaptured!.yaml).toContain('id: lg-bug-9999-contract-test');
  });
});
