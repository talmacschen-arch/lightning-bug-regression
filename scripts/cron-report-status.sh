#!/usr/bin/env bash
# Wrapper for the cron-fired /report-status invocation.
#
# Why this exists: cron's environment is minimal — no HTTP proxy variables,
# no shell profile, no PATH beyond /usr/bin:/bin. On this machine the host's
# https_proxy / http_proxy / NO_PROXY exports live in /root/.bashrc; without
# them, `claude --print` reaches the Anthropic API directly, which the
# corporate egress blocks, returning "403 Request not allowed".
#
# Sourcing /root/.bashrc here picks up:
#   - https_proxy / http_proxy / HTTPS_PROXY / HTTP_PROXY / all_proxy
#   - NO_PROXY
#   - PATH additions (incl. ~/.local/bin where claude lives)
# /root/.bashrc has no non-interactive guard, so it's safe to source from
# a non-interactive cron context.
#
# Cron entry shape (managed by scripts/install-cron.sh):
#   0 12 * * * <repo>/scripts/cron-report-status.sh >> <repo>/docs/status/cron.log 2>&1
#   0 20 * * * <repo>/scripts/cron-report-status.sh >> <repo>/docs/status/cron.log 2>&1

set -e
# NOTE: deliberately NOT `set -u` here. /etc/bashrc on RHEL-likes references
# unset BASHRCSOURCED gating variables and would fail under nounset.

# Source host shell env (proxy exports etc.). Guarded so non-root users with
# a different home still get a sane failure mode instead of silent skip.
if [[ "$(id -u)" -eq 0 && -f /root/.bashrc ]]; then
  # shellcheck disable=SC1091
  . /root/.bashrc
fi

# Pre-flight GH_TOKEN from ~/.git-credentials so the spawned `gh` calls
# inside /report-status can authenticate (cron's env doesn't otherwise
# carry GH_TOKEN). Project memory: feedback-gh-token-auto.
if [[ -f ~/.git-credentials ]]; then
  GH_TOKEN=$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)
  export GH_TOKEN
fi

# cd into the repo (one level up from scripts/)
cd "$(cd "$(dirname "$0")/.." && pwd)"

# Stamp the log so we can correlate cron fires with claude outputs.
echo "---- $(date -Is) cron-report-status.sh fired ----"

# --permission-mode auto: claude --print is non-interactive, so there's no
# human to approve Bash / Write tool calls; without an explicit permission
# mode the skill silently blocks on every tool prompt.
#
# Mode selection empirically (probed 2026-05-23):
#   --dangerously-skip-permissions  → REJECTED under root ("cannot be used
#                                      with root/sudo privileges"); cron
#                                      runs as root, so unusable.
#   --permission-mode bypassPermissions → same root rejection as above.
#   --permission-mode acceptEdits   → allows echo + git but BLOCKS gh
#                                      ("requires user approval"); §3 of
#                                      the report stays empty.
#   --permission-mode dontAsk       → counter-intuitive: "don't ask = deny";
#                                      blocks even gh pr list silently.
#   --permission-mode auto          → allows echo + git + gh; only mode
#                                      that lets the full report render.
# Verdict: use `auto`. The /report-status skill's contract still constrains
# write-scope to docs/status/ (SKILL.md "Hard rules" + "What this skill
# does NOT do"); cron is a trusted local action on this single-user box.
exec /root/.local/bin/claude --print --permission-mode auto "/report-status"
