#!/usr/bin/env bash
# scripts/smoke.sh — self-contained smoke test of the regression HARNESS TOOLCHAIN.
#
# 它测的是【工具链】不是【case 内容】:用 status:fixed 的 known-good case 当"试纸"
# (答案已知必 PASS),验证 backend → runner → 真集群 → DB → verdict 整条链是否健康。
# 若 known-good case 跑不出 PASS,问题在工具链(backend/runner/集群连接/DB/verdict),
# 不在 case。这是 ci-gate 覆盖不到的层(GitHub runner 上没有真集群)。
#
# 用法: bash scripts/smoke.sh   → 打印 GO / NO-GO,exit 0 / 1。
# foreman 在 merge 后派 smoke-runner 调它(review-pipeline v3, design.md §15.1 step 6.a)。
#
# 自包含:自己起 backend(临时端口+临时 DB,零污染生产 runs.db)→ 跑 → 验 → 自停。
# 真集群常驻(mdw=coordinator),连接走 external/dut.yml(backend dsn_builder 已读)。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
PORT="${SMOKE_PORT:-18000}"          # 非 8000,避免撞常驻 backend
TS="$(date -u +%Y-%m-%d-%H%M%S)"
LOG="$REPO_ROOT/docs/status/smoke-$TS.log"
TMPDB="$(mktemp -u -t smoke-XXXXXX.db)"
ARTIFACTS_TMP="$(mktemp -d -t smoke-art-XXXXXX)"
API="http://127.0.0.1:$PORT"
# known-good 试纸:轻量纯 SQL 的 fixed case(避开 pax/orca 重型 + destructive)
KNOWN_GOOD=("lg-bug-0001-hashjoin-right-table" "lg-bug-0002-array-unnest-crash")
BACKEND_PID=""

log()  { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }
nogo() { log "NO-GO: $*"; exit 1; }    # cleanup 由 trap EXIT 统一做
cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && wait "$BACKEND_PID" 2>/dev/null
  rm -f "$TMPDB"
  rm -rf "$ARTIFACTS_TMP"
}
trap cleanup EXIT

mkdir -p "$(dirname "$LOG")"
log "smoke start — port=$PORT tmpdb=$TMPDB cases=${KNOWN_GOOD[*]}"
log "测的是 harness 工具链(非 case 内容);known-good case 当试纸"

cd "$BACKEND" || nogo "backend dir 不存在: $BACKEND"
[ -x .venv/bin/python ] || nogo "backend venv 缺失(.venv/bin/python)"

# 1. 临时 DB 建表(alembic upgrade head 含 seed categories) — 零污染生产 runs.db
log "step 1: alembic upgrade head → 临时 DB"
DATABASE_URL="sqlite:///$TMPDB" .venv/bin/alembic upgrade head >>"$LOG" 2>&1 \
  || nogo "alembic upgrade 失败(见 $LOG)"

# 2. 起 backend(临时 DB + 临时端口 + 临时 artifacts;连真集群走 dut.yml)
log "step 2: 起 backend @ $API"
DATABASE_URL="sqlite:///$TMPDB" \
CASES_ROOT="$REPO_ROOT/cases" \
EXTERNAL_DEPS_DIR="$REPO_ROOT/external" \
ARTIFACTS_ROOT="$ARTIFACTS_TMP" \
LBR_REPO_ROOT="$REPO_ROOT" \
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=gpadmin PGDATABASE=gpadmin \
  nohup .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" --loop asyncio >>"$LOG" 2>&1 &
BACKEND_PID=$!
log "backend pid=$BACKEND_PID"

# 3. 健康等待(≤30s)
log "step 3: 等 backend 就绪"
ready=0
for _ in $(seq 1 30); do
  if curl -sf -m 3 "$API/admin/categories" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" -eq 1 ] || nogo "backend 30s 内没就绪(见 $LOG)"
log "backend 就绪"

# 3.5 登录拿 Bearer token. POST /runs 是 mutation,v1.17+ 要 auth(runs.py 用
# CurrentUser 依赖)。临时 DB 的 backend startup 会 seed admin/admin,所以这里
# 用默认账号登录即可——不依赖生产 DB 被改过的密码(用临时 DB 的又一好处)。
log "step 3.5: POST /auth/login (admin/admin on fresh tmp DB)"
token=$(curl -sf -m 10 -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' 2>>"$LOG" \
  | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['token'])" 2>>"$LOG") \
  || nogo "登录失败(临时 DB 应 startup seed admin/admin)"
log "got bearer token"

# 4. POST /runs(带 Bearer token) → run_id
log "step 4: POST /runs"
payload=$(printf '{"case_ids":["%s","%s"]}' "${KNOWN_GOOD[0]}" "${KNOWN_GOOD[1]}")
resp=$(curl -sf -m 10 -X POST "$API/runs" -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $token" -d "$payload" 2>>"$LOG") \
  || nogo "POST /runs 失败"
run_id=$(echo "$resp" | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['run_id'])" 2>>"$LOG") \
  || nogo "解析 run_id 失败: $resp"
log "run_id=$run_id"

# 5. 轮询到 terminal(done/aborted,≤5min)
log "step 5: 轮询 run $run_id"
st=""; summary=""
for _ in $(seq 1 100); do
  summary=$(curl -sf -m 5 "$API/runs/$run_id" -H "Authorization: Bearer $token" 2>>"$LOG") || nogo "GET /runs/$run_id 失败"
  st=$(echo "$summary" | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)
  { [ "$st" = "done" ] || [ "$st" = "aborted" ]; } && break
  sleep 3
done
{ [ "$st" = "done" ] || [ "$st" = "aborted" ]; } || nogo "run $run_id 5min 没结束(status=$st)"
log "terminal status=$st"
log "summary: $summary"

# 6. verdict: GO = done + 全部 known-good PASS + 无 fail/error
read -r passed failed errored < <(echo "$summary" | .venv/bin/python -c \
  "import sys,json;d=json.load(sys.stdin);print(d.get('passed') or 0, d.get('failed') or 0, d.get('errored') or 0)")
log "passed=$passed failed=$failed errored=$errored (期望 passed=${#KNOWN_GOOD[@]}, fail=0, error=0)"
if [ "$st" = "done" ] && [ "$failed" -eq 0 ] && [ "$errored" -eq 0 ] && [ "$passed" -eq "${#KNOWN_GOOD[@]}" ]; then
  log "GO — harness 工具链健康(${#KNOWN_GOOD[@]} known-good case 全 PASS,真集群链路通)"
  exit 0
fi
nogo "harness 工具链异常: status=$st passed=$passed failed=$failed errored=$errored — 不是 case 问题,是工具链断了"
