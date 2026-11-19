#!/usr/bin/env bash
# install-cron.sh — register the /report-status cron entries (M0 step 8).
#
# Authoritative spec: design.md §15.3.1 (v1.3 OS crontab path; the v1.0~v1.2
# Claude Code CronCreate path was abandoned — session-only, REPL-idle-gated).
#
# Default = dry-run: show what *would* change, don't touch crontab.
# Pass --apply to actually write.
#
# Idempotent: detects whether our entry is already present and skips it.
# Re-running is a no-op.
#
# History: originally managed two entries (12:00 + 20:00). The 20:00 evening
# fire was dropped on 2026-11-20 per request — one noon rollup is enough while
# the pipeline is idle; the tag-based apply below also cleans out any leftover
# 20:00 line from older crontabs.

set -euo pipefail

REPO_ABS="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_BIN="/root/.local/bin/claude"
CRON_TAG="lightning-bug-regression /report-status"

ENTRY_NOON="0 12 * * * ${REPO_ABS}/scripts/cron-report-status.sh >> ${REPO_ABS}/docs/status/cron.log 2>&1  # ${CRON_TAG}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--apply | --dry-run | --check]

  --dry-run   (default) Show what would be added; touch nothing.
  --apply               Actually write the crontab.
  --check               Report whether the entry is already in place;
                        exit 0 = present, 1 = missing.

Per design.md §15.3.1, this script runs as root (root crontab is the one we
add to). It refuses to run as a non-root user.

The entry it manages is:
  ${ENTRY_NOON}
USAGE
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "error: must run as root (current user: $(id -un))" >&2
    echo "       try: sudo $0 $*" >&2
    exit 2
  fi
}

require_claude() {
  if [[ ! -x "${CLAUDE_BIN}" ]]; then
    echo "error: ${CLAUDE_BIN} not found or not executable" >&2
    echo "       design.md §13.0 self-check assumes this path; install claude first" >&2
    exit 3
  fi
}

read_crontab() {
  # Empty crontab returns exit 1 from `crontab -l`; suppress that.
  crontab -l 2>/dev/null || true
}

has_entry() {
  local current="$1" needle="$2"
  grep -Fq "${needle}" <<<"${current}"
}

cmd_check() {
  local current
  current="$(read_crontab)"
  if has_entry "${current}" "${ENTRY_NOON}"; then
    echo "✓ noon entry present"
    exit 0
  else
    echo "✗ noon entry MISSING"
    exit 1
  fi
}

cmd_dry_run() {
  local current
  current="$(read_crontab)"
  echo "=== current root crontab ==="
  if [[ -z "${current}" ]]; then
    echo "(empty)"
  else
    echo "${current}"
  fi
  echo
  echo "=== entry this script manages ==="
  echo "${ENTRY_NOON}"
  echo
  if has_entry "${current}" "${ENTRY_NOON}"; then
    echo "=== verdict: entry already present; nothing to do ==="
    exit 0
  fi
  echo "=== verdict: would add ===  (run with --apply to write)"
  echo "  + ${ENTRY_NOON}"
}

cmd_apply() {
  # Strategy: tag-based idempotency. Remove every existing line that
  # contains CRON_TAG (handles format upgrades and the dropped 20:00 entry —
  # old entries get cleaned out before the canonical entry is added).
  # Then write the single canonical entry.
  local current other
  current="$(read_crontab)"
  other="$(grep -Fv "${CRON_TAG}" <<<"${current}" || true)"
  # Trim trailing blank lines that grep -v can leave behind.
  other="$(printf '%s' "${other}" | sed -e :a -e '/^$/{$d;N;ba' -e '}')"
  local new="${other}${other:+$'\n'}${ENTRY_NOON}"
  printf '%s\n' "${new}" | crontab -
  echo "=== new root crontab ==="
  crontab -l
  echo
  echo "next fires at the next 12:00 (local time)."
  echo "to force an immediate end-to-end test, add a temp entry that"
  echo "fires in ~3 minutes pointing at the same wrapper, wait for"
  echo "docs/status/cron.log + new docs/status/*.md, then remove the"
  echo "temp entry. The canonical entries stay untouched throughout."
}

main() {
  local mode="${1:-}"
  case "${mode}" in
    ""|--dry-run)
      cmd_dry_run
      ;;
    --apply)
      require_root
      require_claude
      cmd_apply
      ;;
    --check)
      cmd_check
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
