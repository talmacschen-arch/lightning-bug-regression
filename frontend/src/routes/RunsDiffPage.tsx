/**
 * RunsDiffPage — side-by-side diff between two runs (M6-3).
 *
 * URL: /runs/diff?a=<run_id>&b=<run_id>   (a = older, b = newer)
 *
 * Strategy: fetch both RunDetails (existing GET /runs/{id}) and compute
 * the diff client-side. No new backend endpoint — keeps M6-3 minimal.
 *
 * Diff classification:
 *   - pass_to_fail   case present in both; a=pass, b=fail (regression)
 *   - fail_to_pass   case present in both; a=fail, b=pass (fixed)
 *   - new_case       case present only in b (added)
 *   - removed_case   case present only in a (removed)
 *   - duration_jump  pass→pass but duration_b > 1.5 × duration_a
 *   - unchanged      same status, no big duration jump (hidden by default)
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';

type RunDetail = components['schemas']['RunDetail'];
type CaseResultOut = components['schemas']['CaseResultOut'];

const DURATION_JUMP_RATIO = 1.5; // 1.5× = "duration_jump"

type DiffKind =
  | 'pass_to_fail'
  | 'fail_to_pass'
  | 'new_case'
  | 'removed_case'
  | 'duration_jump'
  | 'status_change_other'
  | 'unchanged';

interface DiffRow {
  case_id: string;
  status_a: string | null;
  status_b: string | null;
  duration_a: number | null;
  duration_b: number | null;
  kind: DiffKind;
}

function caseStatus(c: CaseResultOut | undefined): string | null {
  return c?.status ?? null;
}

function caseDuration(c: CaseResultOut | undefined): number | null {
  return c?.duration_ms ?? null;
}

function classify(
  a: CaseResultOut | undefined,
  b: CaseResultOut | undefined,
): DiffKind {
  if (a === undefined && b !== undefined) return 'new_case';
  if (a !== undefined && b === undefined) return 'removed_case';
  if (a === undefined || b === undefined) return 'unchanged'; // unreachable
  const sa = (a.status ?? '').toLowerCase();
  const sb = (b.status ?? '').toLowerCase();
  if (sa === 'pass' && sb === 'fail') return 'pass_to_fail';
  if (sa === 'fail' && sb === 'pass') return 'fail_to_pass';
  if (sa !== sb) return 'status_change_other';
  // Same status — check duration jump (only meaningful for pass→pass)
  const da = a.duration_ms ?? null;
  const db = b.duration_ms ?? null;
  if (sa === 'pass' && da !== null && db !== null && da > 0 && db / da > DURATION_JUMP_RATIO) {
    return 'duration_jump';
  }
  return 'unchanged';
}

function computeDiff(runA: RunDetail, runB: RunDetail): DiffRow[] {
  const byIdA = new Map<string, CaseResultOut>();
  const byIdB = new Map<string, CaseResultOut>();
  for (const cr of runA.case_results) byIdA.set(cr.case_id, cr);
  for (const cr of runB.case_results) byIdB.set(cr.case_id, cr);
  const allIds = new Set<string>([...byIdA.keys(), ...byIdB.keys()]);
  const rows: DiffRow[] = [];
  for (const id of allIds) {
    const a = byIdA.get(id);
    const b = byIdB.get(id);
    rows.push({
      case_id: id,
      status_a: caseStatus(a),
      status_b: caseStatus(b),
      duration_a: caseDuration(a),
      duration_b: caseDuration(b),
      kind: classify(a, b),
    });
  }
  // Sort: regressions first, then fixes, new, removed, duration_jump, status_change_other, unchanged
  const order: Record<DiffKind, number> = {
    pass_to_fail: 0,
    fail_to_pass: 1,
    new_case: 2,
    removed_case: 3,
    duration_jump: 4,
    status_change_other: 5,
    unchanged: 6,
  };
  rows.sort((x, y) => {
    if (order[x.kind] !== order[y.kind]) return order[x.kind] - order[y.kind];
    return x.case_id.localeCompare(y.case_id);
  });
  return rows;
}

const KIND_LABEL: Record<DiffKind, string> = {
  pass_to_fail: 'Regression (pass → fail)',
  fail_to_pass: 'Fixed (fail → pass)',
  new_case: 'New case',
  removed_case: 'Removed case',
  duration_jump: 'Duration jump (>1.5×)',
  status_change_other: 'Status change (other)',
  unchanged: 'Unchanged',
};

const KIND_BADGE_CLASS: Record<DiffKind, string> = {
  pass_to_fail: 'badge badge-danger',
  fail_to_pass: 'badge badge-success',
  new_case: 'badge badge-success',
  removed_case: 'badge badge-muted',
  duration_jump: 'badge badge-warning',
  status_change_other: 'badge badge-warning',
  unchanged: 'badge badge-muted',
};

function DiffRowComponent({ row }: { row: DiffRow }) {
  return (
    <tr data-testid={`diff-row-${row.case_id}`}>
      <td>
        <Link
          to={`/cases/${row.case_id}`}
          className="font-mono text-sm text-blue-700 hover:underline"
        >
          {row.case_id}
        </Link>
      </td>
      <td>
        <span className={KIND_BADGE_CLASS[row.kind]} data-testid={`diff-kind-${row.case_id}`}>
          {KIND_LABEL[row.kind]}
        </span>
      </td>
      <td className="font-mono text-xs">{row.status_a ?? '—'}</td>
      <td className="font-mono text-xs">{row.status_b ?? '—'}</td>
      <td className="font-mono text-xs text-right">
        {row.duration_a !== null ? `${row.duration_a}ms` : '—'}
      </td>
      <td className="font-mono text-xs text-right">
        {row.duration_b !== null ? `${row.duration_b}ms` : '—'}
      </td>
    </tr>
  );
}

export default function RunsDiffPage() {
  const [searchParams] = useSearchParams();
  const aParam = searchParams.get('a');
  const bParam = searchParams.get('b');
  const aId = aParam ? Number(aParam) : null;
  const bId = bParam ? Number(bParam) : null;
  const [showUnchanged, setShowUnchanged] = useState(false);
  const [runA, setRunA] = useState<RunDetail | null>(null);
  const [runB, setRunB] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (aId === null || bId === null || Number.isNaN(aId) || Number.isNaN(bId)) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      apiFetch('/runs/{run_id}', 'get', { path: { run_id: aId } }),
      apiFetch('/runs/{run_id}', 'get', { path: { run_id: bId } }),
    ])
      .then(([a, b]) => {
        if (cancelled) return;
        setRunA(a as RunDetail);
        setRunB(b as RunDetail);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [aId, bId]);

  const diff = useMemo(() => {
    if (runA === null || runB === null) return null;
    return computeDiff(runA, runB);
  }, [runA, runB]);

  const visibleRows = useMemo(() => {
    if (diff === null) return null;
    return showUnchanged ? diff : diff.filter((r) => r.kind !== 'unchanged');
  }, [diff, showUnchanged]);

  if (aId === null || bId === null || Number.isNaN(aId) || Number.isNaN(bId)) {
    return (
      <div data-testid="runs-diff-empty" className="p-6">
        <p className="text-sm text-muted-foreground">
          Specify two runs via <code>?a=&lt;run_id&gt;&b=&lt;run_id&gt;</code> in the URL.
        </p>
      </div>
    );
  }

  if (loading) {
    return <div data-testid="runs-diff-loading" className="p-6">Loading diff…</div>;
  }

  if (error !== null) {
    return (
      <div data-testid="runs-diff-error" className="p-6 text-sm text-destructive">
        Failed to load: {error}
      </div>
    );
  }

  if (diff === null || visibleRows === null) {
    return null;
  }

  const counts = {
    pass_to_fail: diff.filter((r) => r.kind === 'pass_to_fail').length,
    fail_to_pass: diff.filter((r) => r.kind === 'fail_to_pass').length,
    new_case: diff.filter((r) => r.kind === 'new_case').length,
    removed_case: diff.filter((r) => r.kind === 'removed_case').length,
    duration_jump: diff.filter((r) => r.kind === 'duration_jump').length,
    unchanged: diff.filter((r) => r.kind === 'unchanged').length,
  };

  return (
    <div data-testid="page-runs-diff" className="p-6 space-y-4">
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">Run diff</h1>
        <span data-testid="diff-runs-label" className="text-sm text-muted-foreground">
          Run #{aId} (older) → Run #{bId} (newer)
        </span>
      </div>

      <div data-testid="diff-counts" className="text-sm flex flex-wrap gap-3">
        <span className="badge badge-danger">{counts.pass_to_fail} regression</span>
        <span className="badge badge-success">{counts.fail_to_pass} fixed</span>
        <span className="badge badge-success">{counts.new_case} new</span>
        <span className="badge badge-muted">{counts.removed_case} removed</span>
        <span className="badge badge-warning">{counts.duration_jump} duration jump</span>
        <span className="badge badge-muted">{counts.unchanged} unchanged</span>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          data-testid="diff-show-unchanged"
          checked={showUnchanged}
          onChange={(e) => setShowUnchanged(e.target.checked)}
        />
        Show unchanged
      </label>

      {visibleRows.length === 0 ? (
        <div data-testid="diff-no-changes" className="text-sm text-muted-foreground">
          No case-level differences between these two runs.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table data-testid="diff-table" className="diff-table w-full text-sm">
            <thead>
              <tr>
                <th className="text-left">Case</th>
                <th className="text-left">Change</th>
                <th className="text-left">#{aId} status</th>
                <th className="text-left">#{bId} status</th>
                <th className="text-right">#{aId} duration</th>
                <th className="text-right">#{bId} duration</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <DiffRowComponent key={row.case_id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
