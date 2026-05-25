/**
 * Shared Playwright test helpers.
 *
 * chromiumCanLaunch() — §14 R8 declaration-level skip helper.
 * Check whether the chromium shared library (libgbm.so.1) is present on this
 * host. When it is missing, chromium cannot launch and tests should be skipped
 * at declaration level (not inside `test()` body) to avoid an unintelligible
 * launcher error.
 */
import { execSync } from 'child_process';

export function chromiumCanLaunch(): boolean {
  try {
    execSync('ldconfig -p 2>/dev/null | grep libgbm', { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

export const SKIP_REASON =
  'libgbm.so.1 not found — chromium cannot launch on this host (§14 R8 declaration-level skip)';

/**
 * v1.17: pre-seed localStorage.authToken + mock GET /auth/me so the
 * RequireAuth gate (App.tsx) lets the test proceed past /login.
 *
 * Apply via `test.beforeEach(seedAuth)` in every e2e spec that navigates
 * to a protected route. Without this, RequireAuth Navigate→/login and
 * the test fails finding page-specific selectors.
 */
import type { Page, BrowserContext } from '@playwright/test';

export async function seedAuth(
  page: Page,
  context?: BrowserContext,
): Promise<void> {
  // addInitScript runs before any document scripts on each navigation —
  // ensures localStorage is populated before App.tsx reads it.
  await page.addInitScript(() => {
    window.localStorage.setItem('authToken', 'test-token-for-playwright');
  });

  // Mock /auth/me so Layout's useEffect resolves cleanly + sidebar
  // shows the user. Tests don't care which user it is.
  const target = context ?? page.context();
  await target.route('**/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'admin', must_change_password: false }),
    }),
  );
}
