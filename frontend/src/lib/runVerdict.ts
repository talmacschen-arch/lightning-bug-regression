/**
 * Run verdict derivation — shared between DashboardPage and RunsPage.
 *
 * Backend `run.status` is the LIFECYCLE phase ('running' / 'done' /
 * 'aborted') — NOT the verdict. The verdict (pass / fail / running /
 * aborted / empty) must be derived from the combination of `status` +
 * `failed` count.
 *
 * Pre-PR #107: DashboardPage RecentRunsTile filtered `r.status === 'pass'`
 * which never matched any real run (backend writes 'done', not 'pass')
 * so all 3 counters showed 0. PR #107 fixed Dashboard with an inline
 * helper. This module extracts that helper so RunsPage can fix the same
 * bug (RUN_STATUS_OPTIONS=['pass','fail','running','error','completed']
 * is also wrong — backend writes none of those values).
 */
import type { components } from '@/api/client';

type RunSummary = components['schemas']['RunSummary'];

export type RunVerdict = 'pass' | 'fail' | 'running' | 'aborted' | 'empty';

export function runVerdict(r: RunSummary): RunVerdict {
  if (r.status === 'running') return 'running';
  if (r.status === 'aborted') return 'aborted';
  const failed = r.failed ?? 0;
  const passed = r.passed ?? 0;
  if (failed > 0) return 'fail';
  if (passed > 0) return 'pass';
  return 'empty';
}

export function verdictToBadgeClass(verdict: RunVerdict): string {
  if (verdict === 'pass') return 'badge-success';
  if (verdict === 'fail') return 'badge-danger';
  if (verdict === 'aborted') return 'badge-danger';
  if (verdict === 'running') return 'badge-warning';
  return 'badge-muted';
}

export const VERDICT_OPTIONS: RunVerdict[] = ['pass', 'fail', 'running', 'aborted'];
