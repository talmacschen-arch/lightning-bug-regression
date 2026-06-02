import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatRelativeUtc } from '@/lib/time';
import { caseStatusColor } from '@/lib/caseStatus';

type CaseDetail = components['schemas']['CaseDetail'];
type CaseRecentRunOut = components['schemas']['CaseRecentRunOut'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${(s / 60).toFixed(1)}m`;
}

// ---------------------------------------------------------------------------
// M6-D3 T2 — Per-version pass rate table
// ---------------------------------------------------------------------------

const NO_VERSION_LABEL = '(no version)';

interface VersionPassRateTableProps {
  runs: CaseRecentRunOut[];
}

function VersionPassRateTable({ runs }: VersionPassRateTableProps) {
  if (runs.length === 0) return null;

  // Group runs by target_version; null versions go under NO_VERSION_LABEL.
  const versionMap = new Map<string, { pass: number; total: number }>();
  for (const r of runs) {
    const key = r.target_version ?? NO_VERSION_LABEL;
    const entry = versionMap.get(key) ?? { pass: 0, total: 0 };
    entry.total += 1;
    if ((r.case_status ?? '').toLowerCase() === 'pass') {
      entry.pass += 1;
    }
    versionMap.set(key, entry);
  }

  // Only show if there are multiple distinct version keys, or if any version
  // has a real version string (not just the no-version fallback).
  const entries = Array.from(versionMap.entries());
  const hasVersioned = entries.some(([key]) => key !== NO_VERSION_LABEL);
  if (!hasVersioned) return null;

  return (
    <div data-testid="version-pass-rate" className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
      {entries.map(([ver, { pass, total }]) => (
        <span key={ver} data-testid={`version-pass-rate-${ver}`}>
          <span className="font-medium">{ver}</span>
          {': '}
          <span className={pass === total ? 'text-green-700' : 'text-red-700'}>
            {pass}/{total}
          </span>
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// M6-D3 T1 — CaseTimeline sparkline card
// ---------------------------------------------------------------------------

interface CaseTimelineProps {
  runs: CaseRecentRunOut[];
}

function CaseTimeline({ runs }: CaseTimelineProps) {
  const navigate = useNavigate();

  // oldest→newest: API returns most-recent-first, so reverse.
  const ordered = [...runs].reverse();

  const n = ordered.length;
  const passCount = ordered.filter((r) => (r.case_status ?? '').toLowerCase() === 'pass').length;
  const failCount = ordered.filter((r) => (r.case_status ?? '').toLowerCase() === 'fail').length;
  const skipCount = ordered.filter((r) => (r.case_status ?? '').toLowerCase() === 'skip').length;

  // Last failure: most-recent run (from original order, so last item in reversed)
  // that is fail/error — find from newest-first (original API order).
  const lastFailRun = runs.find(
    (r) => (r.case_status ?? '').toLowerCase() === 'fail' || (r.case_status ?? '').toLowerCase() === 'error',
  );

  return (
    <Card data-testid="case-timeline">
      <CardHeader>
        <CardTitle className="text-base">
          <span data-testid="case-timeline-summary">
            {`最近 ${n} 次：${passCount} pass / ${failCount} fail / ${skipCount} skip`}
            {lastFailRun != null && (
              <span className="ml-3 text-sm font-normal text-red-600">
                {`上次失败：Run #${lastFailRun.run_id}（${formatRelativeUtc(lastFailRun.started_at)}）`}
              </span>
            )}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {ordered.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <div className="flex flex-wrap gap-1">
            {ordered.map((r) => {
              const status = (r.case_status ?? '').toLowerCase();
              const colorCls = caseStatusColor(status);
              const relTime = formatRelativeUtc(r.started_at);
              const dur = formatDuration(r.duration_ms);
              const ver = r.target_version ?? null;
              const tooltip = `Run #${r.run_id} · ${relTime}${dur ? ` · ${dur}` : ''}${ver ? ` · ${ver}` : ''}`;
              return (
                <button
                  key={r.run_id}
                  data-testid={`case-timeline-cell-${r.run_id}`}
                  title={tooltip}
                  onClick={() => navigate(`/runs/${r.run_id}`)}
                  className={`w-5 h-5 rounded-sm ${colorCls} hover:opacity-75 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-500 cursor-pointer`}
                  aria-label={tooltip}
                />
              );
            })}
          </div>
        )}
        <VersionPassRateTable runs={ordered} />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// M5-3 — RecentRuns list card (now receives data from parent)
// ---------------------------------------------------------------------------

interface CaseRecentRunsProps {
  runs: CaseRecentRunOut[] | null;
  error: string | null;
}

function CaseRecentRuns({ runs, error }: CaseRecentRunsProps) {
  if (error) {
    return (
      <Card data-testid="case-recent-runs-error" className="border-red-200">
        <CardHeader>
          <CardTitle className="text-base">Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-700">Failed to load: {error}</p>
        </CardContent>
      </Card>
    );
  }
  if (runs === null) {
    return (
      <Card data-testid="case-recent-runs-loading">
        <CardHeader>
          <CardTitle className="text-base">Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-4 w-64" />
        </CardContent>
      </Card>
    );
  }
  if (runs.length === 0) {
    return (
      <Card data-testid="case-recent-runs-empty">
        <CardHeader>
          <CardTitle className="text-base">Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            This case has not been included in any run yet.
          </p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card data-testid="case-recent-runs">
      <CardHeader>
        <CardTitle className="text-base">Recent runs ({runs.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {runs.map((r) => (
            <li
              key={r.run_id}
              data-testid={`case-recent-run-${r.run_id}`}
              className="flex items-center gap-3 text-sm"
            >
              <Link
                to={`/runs/${r.run_id}`}
                className="text-blue-700 hover:underline font-mono"
              >
                Run #{r.run_id}
              </Link>
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700">
                {(r.case_status ?? r.run_status ?? '').toUpperCase()}
              </span>
              {r.duration_ms !== undefined && r.duration_ms !== null && (
                <span className="text-xs text-gray-500">{r.duration_ms}ms</span>
              )}
              <span className="text-xs text-gray-500 ml-auto">
                {formatRelativeUtc(r.started_at)}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// Status badge styling — keep it data-driven (no hardcoded category logic per §14 R4b).
function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    active: 'bg-green-100 text-green-800',
    skip: 'bg-yellow-100 text-yellow-800',
    invalid: 'bg-red-100 text-red-800',
  };
  const cls = colorMap[status] ?? 'bg-gray-100 text-gray-800';
  return (
    <span
      data-testid="case-detail-status-badge"
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  );
}

function ParsedSection({ label, content, testId }: { label: string; content: string; testId: string }) {
  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle className="text-base">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="whitespace-pre-wrap break-words text-sm">{content}</p>
      </CardContent>
    </Card>
  );
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // Lifted from CaseRecentRuns — single fetch, shared by both CaseTimeline and
  // CaseRecentRuns so the endpoint is only called once.
  const [recentRuns, setRecentRuns] = useState<CaseRecentRunOut[] | null>(null);
  const [recentRunsError, setRecentRunsError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    setLoading(true);
    setNotFound(false);

    apiFetch('/cases/{case_id}', 'get', { path: { case_id: id } })
      .then((data) => {
        if (!cancelled) {
          setCaseDetail(data as CaseDetail);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoading(false);
          // Detect 404 from the error message produced by apiFetch.
          if (err instanceof Error && err.message.includes('404')) {
            setNotFound(true);
          } else {
            setNotFound(true);
          }
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Fetch recent-runs once, feed both CaseTimeline and CaseRecentRuns.
  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    setRecentRuns(null);
    setRecentRunsError(null);

    apiFetch('/cases/{case_id}/recent-runs', 'get', {
      path: { case_id: id },
    })
      .then((data) => {
        if (!cancelled) setRecentRuns(data as CaseRecentRunOut[]);
      })
      .catch((e: unknown) => {
        if (!cancelled) setRecentRunsError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div data-testid="case-detail-loading" className="p-6 space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-1/4" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (notFound || !caseDetail) {
    return (
      <div data-testid="case-detail-not-found" className="p-6 text-center">
        <h2 className="text-xl font-semibold mb-2">Case not found</h2>
        <p className="text-muted-foreground mb-4">
          The case <span className="font-mono">{id}</span> could not be found.
        </p>
        <Link
          to="/cases"
          data-testid="case-detail-back-link"
          className="text-primary underline hover:no-underline"
        >
          Back to cases
        </Link>
      </div>
    );
  }

  const parsed = caseDetail.parsed ?? {};
  const description = typeof parsed['description'] === 'string' ? parsed['description'] : null;
  const procedure = typeof parsed['procedure'] === 'string' ? parsed['procedure'] : null;
  const expected = typeof parsed['expected'] === 'string' ? parsed['expected'] : null;
  const artifacts = typeof parsed['artifacts'] === 'string' ? parsed['artifacts'] : null;

  // Collect related links from parsed fields.
  const linkEntries: { label: string; href: string }[] = [];
  if (typeof parsed['related_pr'] === 'string' && parsed['related_pr']) {
    linkEntries.push({ label: 'Related PR', href: parsed['related_pr'] as string });
  }
  if (typeof parsed['related_issue'] === 'string' && parsed['related_issue']) {
    linkEntries.push({ label: 'Related Issue', href: parsed['related_issue'] as string });
  }
  const links = parsed['links'];
  if (Array.isArray(links)) {
    for (const l of links) {
      if (typeof l === 'string' && l) {
        linkEntries.push({ label: l, href: l });
      } else if (l && typeof l === 'object') {
        const lo = l as Record<string, unknown>;
        const href = typeof lo['url'] === 'string' ? lo['url'] : typeof lo['href'] === 'string' ? lo['href'] : null;
        const label = typeof lo['label'] === 'string' ? lo['label'] : href;
        if (href && label) {
          linkEntries.push({ label, href });
        }
      }
    }
  }

  return (
    <div data-testid="page-case-detail" className="p-6 space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 data-testid="case-detail-title" className="text-2xl font-bold">
            {caseDetail.title ?? caseDetail.id}
          </h1>
          <StatusBadge status={caseDetail.status} />
          {caseDetail.destructive && (
            <span
              data-testid="case-detail-destructive-badge"
              className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-600/20"
            >
              destructive
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 text-sm text-muted-foreground flex-wrap">
          <span data-testid="case-detail-id">
            <span className="font-mono">{caseDetail.id}</span>
          </span>
          {caseDetail.category && (
            <span data-testid="case-detail-category">{caseDetail.category}</span>
          )}
        </div>

        {caseDetail.tags && caseDetail.tags.length > 0 && (
          <div data-testid="case-detail-tags" className="flex flex-wrap gap-2">
            {caseDetail.tags.map((tag) => (
              <span
                key={tag}
                data-testid={`case-detail-tag-${tag}`}
                className="inline-flex items-center rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-700/10"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Parsed narrative sections */}
      {description && (
        <ParsedSection label="Description" content={description} testId="case-detail-section-description" />
      )}
      {procedure && (
        <ParsedSection label="Procedure" content={procedure} testId="case-detail-section-procedure" />
      )}
      {expected && (
        <ParsedSection label="Expected" content={expected} testId="case-detail-section-expected" />
      )}
      {artifacts && (
        <ParsedSection label="Artifacts / Links" content={artifacts} testId="case-detail-section-artifacts" />
      )}

      {/* YAML raw view */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Raw YAML</CardTitle>
        </CardHeader>
        <CardContent>
          <pre
            data-testid="case-yaml-raw"
            className="font-mono text-sm whitespace-pre-wrap break-words bg-muted rounded-md p-4 overflow-x-auto"
          >
            {caseDetail.yaml_raw}
          </pre>
        </CardContent>
      </Card>

      {/* Related links */}
      {linkEntries.length > 0 && (
        <Card data-testid="case-detail-links-section">
          <CardHeader>
            <CardTitle className="text-base">Related Links</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1">
              {linkEntries.map((entry, idx) => (
                <li key={idx}>
                  <a
                    data-testid={`case-link-${idx}`}
                    href={entry.href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline hover:no-underline text-sm"
                  >
                    {entry.label}
                  </a>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* M6-D3 T1 — Case timeline sparkline (above Recent runs) */}
      {recentRuns !== null && recentRunsError === null && (
        <CaseTimeline runs={recentRuns} />
      )}

      {/* M5-3 — Recent runs that touched this case */}
      <CaseRecentRuns runs={recentRuns} error={recentRunsError} />

      {/* Error notice for invalid YAML cases */}
      {caseDetail.error && (
        <Card data-testid="case-detail-error" className="border-red-200">
          <CardHeader>
            <CardTitle className="text-base text-red-600">Parse Error</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-red-700 whitespace-pre-wrap break-words">{caseDetail.error}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
