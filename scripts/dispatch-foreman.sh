#!/usr/bin/env bash
# dispatch-foreman.sh — wrapper around `claude --print --agent foreman ...`
# that guarantees a final-result JSON regardless of whether foreman itself
# returns one (design.md §14 R25; mitigates the "foreman exits without
# final JSON" anti-pattern that triggered 3 consecutive R25 violations
# 2026-05-23~24, even after spec hardening at commit 126bba3).
#
# Behavior:
#   1. Snapshot start state: fetch origin/main, record start_sha + ISO ts
#   2. Source ~/.bashrc for HTTP proxy + extract GH_TOKEN from .git-credentials
#      (same pattern as scripts/cron-report-status.sh — see [[cron-permission-mode]] memory)
#   3. Invoke `claude --print --permission-mode auto --agent foreman [--model X]`
#      with the prompt from STDIN, capturing stdout to a log file
#   4. After foreman exits, snapshot end state: fetch origin/main, record end_sha + ts
#   5. Try to extract foreman's final JSON from the captured stdout (best-effort:
#      fenced ```json blocks first, then balanced-brace fallback)
#   6. Independently verify via gh: list merged PRs in [start_ts, end_ts] window
#   7. Build a reconciled JSON combining foreman's self-report + verified-from-gh facts
#   8. Write the reconciled JSON + raw log to docs/foreman-runs/, print JSON to stdout
#
# Usage:
#   echo "<dispatch prompt>" | scripts/dispatch-foreman.sh <sprint-label> [--model opus|sonnet]
#   scripts/dispatch-foreman.sh <sprint-label> [--model X] < prompt.txt
#
# Output paths (under repo root; NOT docs/status/ which is reporter-only-write-scope):
#   docs/foreman-runs/<sprint>-<ts>.log
#   docs/foreman-runs/<sprint>-<ts>.json
#
# Exit code = foreman's exit code (preserved for caller).

set -e

# ---- arg parsing -----------------------------------------------------------

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <sprint-label> [--model opus|sonnet|haiku]" >&2
  echo "       <prompt> goes on STDIN" >&2
  exit 2
fi

SPRINT="$1"; shift
MODEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      MODEL="$2"; shift 2 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---- env (same as cron wrapper) --------------------------------------------

if [[ "$(id -u)" -eq 0 && -f /root/.bashrc ]]; then
  # shellcheck disable=SC1091
  set +e  # /etc/bashrc references BASHRCSOURCED; tolerate unbound
  . /root/.bashrc
  set -e
fi
if [[ -f ~/.git-credentials ]]; then
  GH_TOKEN=$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)
  export GH_TOKEN
fi

# Move to repo root (one level up from this script)
cd "$(cd "$(dirname "$0")/.." && pwd)"

# ---- snapshot start state --------------------------------------------------

git fetch origin main >/dev/null 2>&1 || true
START_SHA=$(git rev-parse origin/main)
START_TS_EPOCH=$(date -u +%s)
START_TS_ISO=$(date -u -d "@${START_TS_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)
TS_TAG=$(date -u -d "@${START_TS_EPOCH}" +%Y%m%dT%H%M%SZ)

mkdir -p docs/foreman-runs
LOG_FILE="docs/foreman-runs/${SPRINT}-${TS_TAG}.log"
JSON_FILE="docs/foreman-runs/${SPRINT}-${TS_TAG}.json"

echo "==[dispatch-foreman]== sprint=${SPRINT} model=${MODEL:-<default>} start_sha=${START_SHA:0:7} log=${LOG_FILE}" >&2

# ---- dispatch foreman ------------------------------------------------------

PROMPT="$(cat)"
if [[ -z "$PROMPT" ]]; then
  echo "dispatch-foreman: empty prompt on stdin" >&2
  exit 2
fi

set +e
if [[ -n "$MODEL" ]]; then
  /root/.local/bin/claude --print --permission-mode auto --agent foreman --model "$MODEL" "$PROMPT" \
    > "$LOG_FILE" 2>&1
else
  /root/.local/bin/claude --print --permission-mode auto --agent foreman "$PROMPT" \
    > "$LOG_FILE" 2>&1
fi
FOREMAN_EXIT=$?
set -e

END_TS_EPOCH=$(date -u +%s)
END_TS_ISO=$(date -u -d "@${END_TS_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)
ELAPSED_SEC=$((END_TS_EPOCH - START_TS_EPOCH))

# ---- snapshot end state ----------------------------------------------------

git fetch origin main >/dev/null 2>&1 || true
END_SHA=$(git rev-parse origin/main)

echo "==[dispatch-foreman]== foreman exited code=${FOREMAN_EXIT} elapsed=${ELAPSED_SEC}s end_sha=${END_SHA:0:7}" >&2

# ---- post-hoc reconciliation (Python inline) -------------------------------
# Use quoted heredoc (<<'PYEOF') so bash doesn't try to interpret backticks
# in the Python source as command substitutions; pass variables via env.

export DF_LOG_FILE="$LOG_FILE"
export DF_JSON_FILE="$JSON_FILE"
export DF_SPRINT="$SPRINT"
export DF_MODEL="$MODEL"
export DF_START_TS="$START_TS_ISO"
export DF_END_TS="$END_TS_ISO"
export DF_START_SHA="$START_SHA"
export DF_END_SHA="$END_SHA"
export DF_EXIT_CODE="$FOREMAN_EXIT"
export DF_ELAPSED="$ELAPSED_SEC"

python3 <<'PYEOF'
import json, re, subprocess, sys, os

LOG = os.environ["DF_LOG_FILE"]
JSON_OUT = os.environ["DF_JSON_FILE"]
SPRINT = os.environ["DF_SPRINT"]
MODEL = os.environ.get("DF_MODEL") or None
START_TS = os.environ["DF_START_TS"]
END_TS = os.environ["DF_END_TS"]
START_SHA = os.environ["DF_START_SHA"]
END_SHA = os.environ["DF_END_SHA"]
EXIT_CODE = int(os.environ["DF_EXIT_CODE"])
ELAPSED = int(os.environ["DF_ELAPSED"])

text = open(LOG, encoding="utf-8", errors="replace").read()

# ---- try to extract foreman's final JSON from stdout ----
def find_balanced_jsons(s):
    """Walk left-to-right; for each '{' find its balanced matching '}' and emit the slice."""
    out, n = [], len(s)
    i = 0
    while i < n:
        if s[i] == '{':
            depth, j = 0, i
            while j < n:
                if s[j] == '{':
                    depth += 1
                elif s[j] == '}':
                    depth -= 1
                    if depth == 0:
                        out.append(s[i:j+1])
                        i = j
                        break
                j += 1
        i += 1
    return out

foreman_json = None
# 1. fenced ```json blocks (highest fidelity)
for m in reversed(re.findall(r"\`\`\`(?:json)?\s*(\{.*?\})\s*\`\`\`", text, re.DOTALL)):
    try:
        cand = json.loads(m)
        if isinstance(cand, dict) and ("status" in cand or "items_done" in cand):
            foreman_json = cand
            break
    except Exception:
        continue
# 2. fallback: any balanced-brace JSON with "status" or "items_done" key
if foreman_json is None:
    for m in reversed(find_balanced_jsons(text)):
        try:
            cand = json.loads(m)
            if isinstance(cand, dict) and ("status" in cand or "items_done" in cand):
                foreman_json = cand
                break
        except Exception:
            continue

# ---- independently verify merged PRs via gh ----
try:
    raw = subprocess.check_output(
        [
            "gh", "pr", "list",
            "--state", "merged",
            "--search", f"merged:>={START_TS}",
            "--limit", "50",
            "--json", "number,title,mergedAt,mergeCommit",
            "--jq", "map({number, title, mergedAt, merge_commit: .mergeCommit.oid[0:7]})",
        ],
        text=True, stderr=subprocess.DEVNULL,
    )
    merged_prs = json.loads(raw) if raw.strip() else []
except Exception as e:
    merged_prs = []
    sys.stderr.write(f"gh pr list failed: {e}\n")

# ---- list new commits on origin/main in window ----
try:
    if START_SHA != END_SHA:
        raw = subprocess.check_output(
            ["git", "log", f"{START_SHA}..{END_SHA}", "--oneline"],
            text=True, stderr=subprocess.DEVNULL,
        )
        new_commits = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    else:
        new_commits = []
except Exception:
    new_commits = []

# ---- last 60 chars of stdout (helpful tail when foreman dumps mid-flight prose) ----
stdout_tail = text.strip()[-400:] if text else ""

# ---- build reconciled JSON ----
out = {
    "wrapper_version": 1,
    "sprint": SPRINT,
    "model": MODEL,
    "start_ts": START_TS,
    "end_ts": END_TS,
    "elapsed_seconds": ELAPSED,
    "start_sha": START_SHA[:7],
    "end_sha": END_SHA[:7],
    "main_advanced": START_SHA != END_SHA,
    "foreman_exit_code": EXIT_CODE,
    "foreman_returned_final_json": foreman_json is not None,
    "r25_violation": foreman_json is None,
    "log_path": LOG,
    "verified_merged_prs_in_window": merged_prs,
    "verified_merged_pr_count": len(merged_prs),
    "new_commits_on_main_in_window": new_commits,
    "stdout_tail_chars_400": stdout_tail,
    "foreman_self_report": foreman_json,
}

with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.write("\n")

# Print to stdout for caller
print(json.dumps(out, indent=2, ensure_ascii=False))
PYEOF

echo "==[dispatch-foreman]== wrote ${JSON_FILE}" >&2
exit "$FOREMAN_EXIT"
