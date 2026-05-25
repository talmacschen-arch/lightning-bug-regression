/**
 * Run verdict derivation — shared between DashboardPage and RunsPage.
 *
 * Backend `run.status` is the LIFECYCLE phase ('running' / 'done' /
 * 'aborted') — NOT the verdict. The verdict (pass / fail / error /
 * running / aborted / empty) must be derived from the combination of
 * `status` + `failed` + `errored` counts.
 *
 * Pre-PR #107: DashboardPage RecentRunsTile filtered `r.status === 'pass'`
 * which never matched any real run (backend writes 'done', not 'pass')
 * so all 3 counters showed 0. PR #107 fixed Dashboard with an inline
 * helper. This module extracts that helper so RunsPage can fix the same
 * bug (RUN_STATUS_OPTIONS=['pass','fail','running','error','completed']
 * is also wrong — backend writes none of those values).
 *
 * 'error' verdict (added post-dogfood run #25, 2026-05-26):
 *   fail  = assertion not satisfied (test ran, result was wrong)
 *   error = driver-side problem (jinja UndefinedError, sql connection
 *           refused, shell spawn failed) — different diagnostic path.
 * The `errored` field is added by backend PR-D (feat/runs-errored-column).
 * Until that OpenAPI regen lands, we use a local type extension so this
 * code is forward-compatible without touching types.ts.
 */
import type { components } from '@/api/client';

type RunSummary = components['schemas']['RunSummary'];

// Local type extension: `errored` is new in PR-D; not yet in auto-generated
// types.ts. Cast internally until `npm run gen:types` picks it up.
type RunSummaryWithErrored = RunSummary & { errored?: number | null };

export type RunVerdict = 'pass' | 'fail' | 'error' | 'running' | 'aborted' | 'empty';

export function runVerdict(r: RunSummary): RunVerdict {
  if (r.status === 'running') return 'running';
  if (r.status === 'aborted') return 'aborted';
  const failed = r.failed ?? 0;
  const passed = r.passed ?? 0;
  const errored = ((r as RunSummaryWithErrored).errored) ?? 0;
  if (failed > 0) return 'fail';
  if (errored > 0) return 'error';
  if (passed > 0) return 'pass';
  return 'empty';
}

export function verdictToBadgeClass(verdict: RunVerdict): string {
  if (verdict === 'pass') return 'badge-success';
  if (verdict === 'fail') return 'badge-danger';
  if (verdict === 'error') return 'badge-danger';
  if (verdict === 'aborted') return 'badge-danger';
  if (verdict === 'running') return 'badge-warning';
  return 'badge-muted';
}

export const VERDICT_OPTIONS: RunVerdict[] = ['pass', 'fail', 'error', 'running', 'aborted'];
