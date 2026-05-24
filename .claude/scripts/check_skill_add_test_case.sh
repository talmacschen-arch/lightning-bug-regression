#!/usr/bin/env bash
# check_skill_add_test_case.sh — lint for .claude/skills/add-test-case/SKILL.md.
#
# Enforces design.md §5.5 + §14 R4b + §5.5.1 generator-only 铁律 at CI time so
# regressions can't quietly land in the skill. Specifically:
#
#   1. SKILL.md exists and is non-empty.
#   2. frontmatter contains name / description / model: opus.
#   3. All required §5.5 sections present (设计原则 / 输入模式 / 工作流 /
#      对齐 / 场景特化 / Canonical / cross-check / 输出格式).
#   4. §14 R4b: no hardcoded category names in conditional-looking context
#      (matches `category == "bug_regression"` / `if category` literal etc.).
#   5. §5.5.1 generator-only: no banned-tool tokens (Write tool / git add /
#      git commit / git push / POST /cases/submit / os.system / subprocess).
#   6. Output format: `─── BEGIN YAML ───` / `─── END YAML ───` fence
#      markers documented.
#
# Tokens inside `❌` (anti-pattern) blocks within the file are intentionally
# educational and are NOT failures — the lint walks 5 lines of context above
# each match to find a ❌ marker.
#
# Authoritative spec: design.md §5.5 (10 子节) + §13.8 (M3b plan) +
# §14 R4b/R26.
#
# Usage:
#   .claude/scripts/check_skill_add_test_case.sh          # default file
#   .claude/scripts/check_skill_add_test_case.sh <path>   # explicit path
#
# Exit codes:
#   0 — all checks pass
#   1 — at least one check failed (each failure printed)
#   2 — usage error / file missing

set -u

FILE="${1:-.claude/skills/add-test-case/SKILL.md}"

if [[ ! -f "$FILE" ]]; then
  echo "ERR: file not found: $FILE" >&2
  exit 2
fi

if [[ ! -s "$FILE" ]]; then
  echo "ERR: file is empty: $FILE" >&2
  exit 1
fi

fail=0

# ---- frontmatter -----------------------------------------------------------
if ! awk 'NR==1 && /^---/{found=1} NR>1 && found && /^---/{exit 0} END{exit !found}' "$FILE"; then
  echo "FAIL [frontmatter]: missing leading --- / --- fence at top of file"
  fail=1
fi
for key in 'name:' 'description:' 'model:'; do
  if ! grep -qE "^${key}" "$FILE"; then
    echo "FAIL [frontmatter]: missing key '${key}' in frontmatter"
    fail=1
  fi
done
if ! grep -qE "^model:[[:space:]]*opus\b" "$FILE"; then
  echo "FAIL [frontmatter]: model must be 'opus' (§13.8) — sonnet drifts on canonical ordering"
  fail=1
fi

# ---- required §5.5 section headers (markdown ## / ###) ---------------------
declare -a REQUIRED_HEADERS=(
  '设计原则'
  '输入模式'
  '工作流'
  '对齐'
  '场景特化'
  'Canonical'
  'cross-check'
  '输出格式'
)
for hdr in "${REQUIRED_HEADERS[@]}"; do
  if ! grep -qE "^#{2,4}.*${hdr}" "$FILE"; then
    echo "FAIL [§5.5 sections]: missing section heading containing '${hdr}'"
    fail=1
  fi
done

# ---- helper: emit fails for matches outside anti-pattern / instructional context
# Context check (15 lines back) looks for any of:
#   - ❌ marker (anti-pattern block heading)
#   - 禁止 / 不允许 / 不要 (Chinese "do NOT")
#   - never / must not / forbidden (English "do NOT")
#   - 反例 (anti-pattern label)
# Any of these in the 15-line context means the match is inside instructional
# / anti-pattern text explaining what NOT to do, NOT actual offending code.
check_banned_pattern() {
  local label="$1" pat="$2"
  while IFS=: read -r ln content; do
    [[ -z "$ln" ]] && continue
    local ctx_start=$((ln - 15))
    [[ $ctx_start -lt 1 ]] && ctx_start=1
    local ctx
    ctx=$(sed -n "${ctx_start},${ln}p" "$FILE")
    if echo "$ctx" | grep -qE '❌|禁止|不允许|不要|反例|never|must not|forbidden'; then
      continue
    fi
    echo "FAIL [${label}]: line ${ln}: ${content}"
    fail=1
  done < <(grep -nP "$pat" "$FILE" 2>/dev/null)
}

# ---- §14 R4b: no hardcoded category in conditional context -----------------
check_banned_pattern '§14 R4b'  'if[[:space:]]+category[[:space:]]*==[[:space:]]*["'"'"']bug_regression'
check_banned_pattern '§14 R4b'  'if[[:space:]]+category[[:space:]]*==[[:space:]]*["'"'"']extension'
check_banned_pattern '§14 R4b'  'category[[:space:]]*===[[:space:]]*["'"'"']bug_regression'
check_banned_pattern '§14 R4b'  'category[[:space:]]*===[[:space:]]*["'"'"']extension'

# ---- §5.5.1 generator-only — banned side-effect tokens ---------------------
check_banned_pattern '§5.5.1 gen-only'  'Write[[:space:]]+tool\b'
check_banned_pattern '§5.5.1 gen-only'  '\bgit[[:space:]]+add\b'
check_banned_pattern '§5.5.1 gen-only'  '\bgit[[:space:]]+commit\b'
check_banned_pattern '§5.5.1 gen-only'  '\bgit[[:space:]]+push\b'
check_banned_pattern '§5.5.1 gen-only'  'POST[[:space:]]*/cases/submit'
check_banned_pattern '§5.5.1 gen-only'  '\bos\.system\b'
check_banned_pattern '§5.5.1 gen-only'  '\bsubprocess\.'

# ---- §5.5.8 output format fence markers documented -------------------------
if ! grep -qE '─── BEGIN YAML ───' "$FILE"; then
  echo "FAIL [§5.5.8 output format]: missing '─── BEGIN YAML ───' fence marker reference"
  fail=1
fi
if ! grep -qE '─── END YAML ───' "$FILE"; then
  echo "FAIL [§5.5.8 output format]: missing '─── END YAML ───' fence marker reference"
  fail=1
fi

# ---- Verdict ---------------------------------------------------------------
if [[ "$fail" -eq 0 ]]; then
  echo "OK: $FILE passes all §5.5 + §14 R4b + §5.5.1 lint checks"
  exit 0
fi
exit 1
