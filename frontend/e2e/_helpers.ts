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
