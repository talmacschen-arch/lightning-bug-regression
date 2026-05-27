/**
 * Shared time utilities.
 *
 * parseUtc — parse a naive-ISO string that the backend emits without a
 * timezone suffix (e.g. "2026-05-28T10:00:00") as UTC, not local time.
 *
 * Background: Python's `datetime.utcnow()` / `.isoformat()` produces strings
 * like "2026-05-28T10:00:00" with no trailing 'Z' or '+00:00'.  The default
 * JS `new Date("2026-05-28T10:00:00")` treats that as *local time* on most
 * engines, causing a ~8 h skew for UTC+8 clients.
 *
 * Extracted from RunDetailPage.tsx (~line 336) so CaseDetailPage can reuse
 * the same fix.  RunDetailPage is intentionally NOT changed in this PR (see
 * m6d3t1 out-of-scope note).
 */
export function parseUtc(dateStr: string): Date {
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(dateStr);
  return new Date(hasTz ? dateStr : dateStr + 'Z');
}

/**
 * Format a UTC date string as a human-readable relative time (e.g. "3m ago").
 * Uses parseUtc to avoid the ~8 h local-time skew on UTC+8 clients.
 */
export function formatRelativeUtc(dateStr: string): string {
  const diffMs = Date.now() - parseUtc(dateStr).getTime();
  const diffM = Math.floor(diffMs / 60_000);
  if (diffM < 1) return 'just now';
  if (diffM < 60) return `${diffM}m ago`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}
