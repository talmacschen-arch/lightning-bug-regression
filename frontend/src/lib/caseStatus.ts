// ---------------------------------------------------------------------------
// Shared case-status → Tailwind class helpers.
//
// Canonical status verdicts (see runVerdict.ts):
//   pass  = assertions satisfied
//   fail  = assertion not satisfied (test ran, result was wrong)
//   error = driver-side problem (jinja/sql/shell blew up) — different path
//   skip  = case skipped (skip-list / unmet precondition)
//
// The solid `bg-*-500` dot palette is the canonical one (used by
// CaseDetailPage's per-version table); badge + row helpers reuse the same
// hues at lighter tints so the whole app stays visually consistent.
//
// All helpers return COMPLETE literal class strings (no runtime
// concatenation of color fragments) so Tailwind's JIT can see them.
// ---------------------------------------------------------------------------

function norm(status: string | null | undefined): string {
  return (status ?? '').toLowerCase();
}

/** Solid dot color (bg-*-500). Unknown → neutral gray. */
const CASE_STATUS_DOT: Record<string, string> = {
  pass: 'bg-green-500',
  fail: 'bg-red-500',
  skip: 'bg-gray-400',
  error: 'bg-orange-500',
};

export function caseStatusColor(status: string | null | undefined): string {
  return CASE_STATUS_DOT[norm(status)] ?? 'bg-gray-300';
}

/** Pill/badge classes (lighter tint + readable text). Unknown → gray. */
const CASE_STATUS_BADGE: Record<string, string> = {
  pass: 'bg-green-100 text-green-800',
  fail: 'bg-red-100 text-red-800',
  skip: 'bg-gray-100 text-gray-700',
  error: 'bg-orange-100 text-orange-800',
};

export function caseStatusBadgeClass(status: string | null | undefined): string {
  return CASE_STATUS_BADGE[norm(status)] ?? 'bg-gray-100 text-gray-700';
}

/** A failed (assertion) or errored (driver) case — the ones worth highlighting. */
export function isProblemStatus(status: string | null | undefined): boolean {
  const s = norm(status);
  return s === 'fail' || s === 'error';
}

/**
 * Row-highlight classes for problem cases (tinted background + colored left
 * rule). Non-problem statuses get an empty string so the row stays plain.
 */
const CASE_STATUS_ROW: Record<string, string> = {
  fail: 'bg-red-50 border-l-4 border-l-red-500 pl-2',
  error: 'bg-orange-50 border-l-4 border-l-orange-500 pl-2',
};

export function caseStatusRowClass(status: string | null | undefined): string {
  return CASE_STATUS_ROW[norm(status)] ?? '';
}
