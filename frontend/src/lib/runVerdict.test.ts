import { describe, it, expect } from 'vitest';
import type { components } from '@/api/client';
import { runVerdict, verdictToBadgeClass, VERDICT_OPTIONS } from './runVerdict';

type RunSummary = components['schemas']['RunSummary'];

function makeRun(partial: Partial<RunSummary & { errored?: number | null }>): RunSummary {
  return {
    id: 1,
    status: 'done',
    target_version: '4.5.0',
    triggered_by: 'gpadmin',
    started_at: '2026-05-25T00:00:00Z',
    finished_at: null,
    total: 0,
    passed: 0,
    failed: 0,
    skipped: 0,
    ...partial,
  } as RunSummary;
}

describe('runVerdict', () => {
  it('returns "running" when lifecycle status is running (regardless of counts)', () => {
    expect(runVerdict(makeRun({ status: 'running', passed: 0, failed: 0 }))).toBe('running');
    expect(runVerdict(makeRun({ status: 'running', passed: 5, failed: 2 }))).toBe('running');
  });

  it('returns "aborted" when lifecycle status is aborted (regardless of counts)', () => {
    expect(runVerdict(makeRun({ status: 'aborted', passed: 0, failed: 0 }))).toBe('aborted');
    expect(runVerdict(makeRun({ status: 'aborted', passed: 5, failed: 0 }))).toBe('aborted');
  });

  it('returns "fail" when status=done and failed>0 (failed dominates)', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 0, failed: 1 }))).toBe('fail');
    expect(runVerdict(makeRun({ status: 'done', passed: 10, failed: 1 }))).toBe('fail');
  });

  it('returns "pass" when status=done and failed=0 and passed>0', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 9, failed: 0 }))).toBe('pass');
    expect(runVerdict(makeRun({ status: 'done', passed: 1, failed: 0 }))).toBe('pass');
  });

  it('returns "empty" when status=done and both passed/failed are 0', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 0, failed: 0 }))).toBe('empty');
  });

  it('treats null passed/failed as 0', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: null, failed: null }))).toBe('empty');
    expect(runVerdict(makeRun({ status: 'done', passed: 5, failed: null }))).toBe('pass');
    expect(runVerdict(makeRun({ status: 'done', passed: null, failed: 3 }))).toBe('fail');
  });

  it('NEVER reads the raw backend "done" status as a verdict — regression for PR #107 / RunsPage bug', () => {
    // Pre-fix, RunsPage filter checked `r.status === 'pass'` which never matched
    // any real run (backend writes 'done'). With runVerdict, a status='done'
    // run with passed>0 produces 'pass'.
    const realBackendRun = makeRun({ status: 'done', passed: 9, failed: 0 });
    expect(runVerdict(realBackendRun)).not.toBe('done');
    expect(runVerdict(realBackendRun)).toBe('pass');
  });

  // --- 'error' verdict tests (dogfood run #25, 2026-05-26) ---

  it('returns "error" when errored>0 and failed=0 (dogfood run #25 zombodb case)', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 15, failed: 0, errored: 1 }))).toBe('error');
  });

  it('returns "fail" when both failed>0 and errored>0 (failed has higher priority)', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 5, failed: 1, errored: 1 }))).toBe('fail');
  });

  it('returns "pass" when errored=0 and failed=0 and passed>0 (regression guard — errored=0 does not affect pass)', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 10, failed: 0, errored: 0 }))).toBe('pass');
  });

  it('returns "pass" when errored field is absent (pre-PR-D rows without errored field)', () => {
    // makeRun does not set errored, so it is undefined on the object
    expect(runVerdict(makeRun({ status: 'done', passed: 10, failed: 0 }))).toBe('pass');
  });

  it('treats null errored as 0', () => {
    expect(runVerdict(makeRun({ status: 'done', passed: 5, failed: 0, errored: null }))).toBe('pass');
  });
});

describe('verdictToBadgeClass', () => {
  it('maps each verdict to a CSS class', () => {
    expect(verdictToBadgeClass('pass')).toBe('badge-success');
    expect(verdictToBadgeClass('fail')).toBe('badge-danger');
    expect(verdictToBadgeClass('error')).toBe('badge-danger');
    expect(verdictToBadgeClass('aborted')).toBe('badge-danger');
    expect(verdictToBadgeClass('running')).toBe('badge-warning');
    expect(verdictToBadgeClass('empty')).toBe('badge-muted');
  });
});

describe('VERDICT_OPTIONS', () => {
  it('lists the 5 user-facing verdict choices (no "empty")', () => {
    expect(VERDICT_OPTIONS).toEqual(['pass', 'fail', 'error', 'running', 'aborted']);
  });
});
