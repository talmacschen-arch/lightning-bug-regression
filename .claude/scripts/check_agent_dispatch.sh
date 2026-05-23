#!/usr/bin/env bash
# check_agent_dispatch.sh — worktree-isolation lint for foreman dispatches.
#
# Reads a JSON object (or array) from stdin describing one or more Agent tool
# invocations and exits non-zero if any code-writing specialist (backend-fixer
# / frontend-fixer / doc-writer) is dispatched without `isolation: "worktree"`.
#
# Authoritative spec: design.md §8.5 (worktree isolation rule, v0.5; absorbed
# from preflight 2026-05-18 incident where two fixers shared one worktree and
# A's WIP got committed by B's lint pass).
#
# Usage:
#   echo '<json>' | .claude/scripts/check_agent_dispatch.sh
#
# Exit codes:
#   0 = all dispatches are safe
#   1 = at least one code-writing specialist lacks isolation:"worktree"
#   2 = malformed input (not valid JSON, or unexpected shape)
#   3 = jq not installed

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "check_agent_dispatch: jq is required but not installed" >&2
  exit 3
fi

# Code-writing specialists subject to the worktree rule.
CODE_WRITERS_REGEX='^(backend-fixer|frontend-fixer|doc-writer)$'

# Normalize stdin to a JSON array of {subagent_type, isolation?} entries.
input="$(cat)"
if [[ -z "$input" ]]; then
  echo "check_agent_dispatch: empty stdin" >&2
  exit 2
fi

normalized="$(jq -c '
  if type == "array" then .
  elif type == "object" then [.]
  else error("expected JSON object or array")
  end
  | map({
      subagent_type: (.subagent_type // .agent // .name // ""),
      isolation: (.isolation // "")
    })
' <<<"$input")" || {
  echo "check_agent_dispatch: malformed JSON input" >&2
  exit 2
}

violations="$(jq -c --arg re "$CODE_WRITERS_REGEX" '
  map(select(.subagent_type | test($re)))
  | map(select(.isolation != "worktree"))
' <<<"$normalized")"

count="$(jq 'length' <<<"$violations")"

if [[ "$count" -gt 0 ]]; then
  echo "check_agent_dispatch: $count code-writing dispatch(es) missing isolation:\"worktree\"" >&2
  jq -r '.[] | "  - subagent_type=\(.subagent_type) isolation=\(.isolation // "<missing>")"' <<<"$violations" >&2
  echo "Required: every backend-fixer / frontend-fixer / doc-writer dispatch must include isolation: \"worktree\" (design.md §8.5)" >&2
  exit 1
fi

echo "check_agent_dispatch: OK ($(jq 'length' <<<"$normalized") dispatch(es) checked)"
exit 0
