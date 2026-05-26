#!/usr/bin/env bash
# bootstrap.sh — fresh-clone setup for lightning-bug-regression.
#
# Idempotent: re-runs are safe (skips already-done steps).
# Run from repo root: `bash scripts/bootstrap.sh`
#
# Performs:
#   1. backend venv + pip install -e ".[dev]"
#   2. alembic upgrade head (creates 7 SQLite tables + seeds admin/admin user)
#   3. frontend npm ci (uses package-lock.json for reproducibility)
#
# Does NOT:
#   - start backend / frontend (see README "## 日常启动")
#   - install OS packages (Python 3.11+, Node 20+, npm assumed present)
#   - touch external/dut.yml or external/*.yml (sample files committed)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== lightning-bug-regression bootstrap ==="
echo "repo root: $REPO_ROOT"
echo

# --- 1. backend venv + deps -------------------------------------------------

echo "[1/3] backend venv + pip install..."
cd "$REPO_ROOT/backend"

if [ ! -d .venv ]; then
  echo "  creating .venv (python3 -m venv .venv)"
  python3 -m venv .venv
else
  echo "  .venv already exists — skipping creation"
fi

PYBIN=".venv/bin/python"
"$PYBIN" -m pip install --quiet --upgrade pip
"$PYBIN" -m pip install --quiet -e ".[dev]"
echo "  ✓ backend deps installed"
echo

# --- 2. alembic migration + seed admin --------------------------------------

echo "[2/3] alembic upgrade head (creates tables + seeds admin/admin)..."
mkdir -p "$REPO_ROOT/backend/data"
DB_PATH="$REPO_ROOT/backend/data/runs.db"
DATABASE_URL="sqlite:///$DB_PATH" "$PYBIN" -m alembic upgrade head
echo "  ✓ DB schema at $DB_PATH"
echo "  ✓ admin user seeded (login: admin / admin — change after first login)"
echo

# --- 3. frontend npm ci -----------------------------------------------------

echo "[3/3] frontend npm ci..."
cd "$REPO_ROOT/frontend"
if [ ! -d node_modules ] || [ "${LBR_BOOTSTRAP_FORCE:-0}" = "1" ]; then
  npm ci --silent
  echo "  ✓ frontend deps installed (node_modules/ populated)"
else
  echo "  node_modules/ already exists — skipping (set LBR_BOOTSTRAP_FORCE=1 to force re-install)"
fi
echo

# --- done -------------------------------------------------------------------

cd "$REPO_ROOT"
cat <<EOF
=== bootstrap done ===

Next steps:
  - Daily start: see README "## 日常启动" section
  - First login: admin / admin (change password after — Layout will show red banner)

Quick start (two terminals):

  # terminal 1 (backend)
  cd backend
  CASES_ROOT=$REPO_ROOT/cases \\
  EXTERNAL_DEPS_DIR=$REPO_ROOT/external \\
  ARTIFACTS_ROOT=$REPO_ROOT/artifacts \\
  DATABASE_URL=sqlite:///$DB_PATH \\
  PGHOST=127.0.0.1 PGPORT=5432 PGUSER=gpadmin PGDATABASE=gpadmin \\
  LBR_REPO_ROOT=$REPO_ROOT \\
  ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
  # \`--loop asyncio\` 强制走 stdlib asyncio 而非默认 uvloop。dogfood
  # 2026-05-26: uvloop 的 subprocess.communicate() 在某些 detach-child
  # 命令上（如 \`pxf cluster restart\` 触发 PXF JVM 重启）不返回，撞
  # asyncio.wait_for timeout。stdlib asyncio 没这个问题。

  # terminal 2 (frontend)
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5173
EOF
