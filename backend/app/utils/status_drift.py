"""status 漂移判定的**单一真源**（§14 R26/铁律5：判定逻辑不许两处实现）。

`status`（open/fixed/wontfix/stub）是 case YAML 里手工维护的元数据，与 runs.db
里每次 run 的 verdict（pass/fail/skip）是两条独立的轴（design.md §4.3 L388）。
本模块把「某 case 当前 status + 它最近若干 run 的 verdict」映射成一个漂移类别，
供两处复用：

  - ``scripts/status-drift.py``（CLI / 挂 rollup / CI）
  - ``GET /cases/status-drift``（前端 Dashboard 卡片）

纯函数、无 IO：调用方各自负责扫 YAML 拿 status、查 DB 拿 verdict，再把结果喂进
``classify``。这样查询实现可以各按环境不同（脚本用 sqlite3 直连，后端走 ORM），
但**易错的判定阈值只有这一份**。
"""
from __future__ import annotations

# status 语义按「BUG 修复轴」推导；只有落在这条轴上的 status 才参与漂移对账。
# extension 的 stable/experimental/... 是「成熟度轴」，wontfix/stub 是人工终态，
# 都不参与——调用方用本集合过滤即可。
BUGFIX_AXIS: frozenset[str] = frozenset({"open", "fixed"})

# 漂移类别，按「需人处理」的优先级从高到低。UI / CLI 排序都用这个次序。
REGRESSION = "REGRESSION"          # fixed 却又 fail —— 修好的坏了（最高优先级）
CANDIDATE = "CANDIDATE"            # open 却连续 N 次全 pass —— 疑似已修，可 flip
THIN_EVIDENCE = "THIN-EVIDENCE"    # open 且最近 pass 但采样不足 N —— 先别 flip
NO_DATA = "NO-DATA"                # 最近 run 无有效 verdict（全 skip / 无记录）
EXPECTED = "EXPECTED"              # open 且最近仍 fail —— BUG 仍复现，符合预期
OK = "OK"                          # fixed 且最近 pass —— 一致

DRIFT_ORDER: tuple[str, ...] = (
    REGRESSION, CANDIDATE, THIN_EVIDENCE, NO_DATA, EXPECTED, OK,
)

# 需要人关注/处理的类别（UI 摘要与 CLI 默认只列这些）。
ACTIONABLE: frozenset[str] = frozenset({REGRESSION, CANDIDATE, THIN_EVIDENCE})

ICON: dict[str, str] = {
    REGRESSION: "🔴", CANDIDATE: "🟢", THIN_EVIDENCE: "⏳",
    NO_DATA: "⚪", EXPECTED: "✓", OK: "·",
}


def classify(status: str, verdicts: list[str], rounds: int) -> tuple[str, str]:
    """把 (status, 最近 verdict 列表) 判成 (漂移类别, 中文说明)。

    参数:
      status:   case 当前 YAML status（调用方应已用 ``BUGFIX_AXIS`` 过滤，
                只传 open / fixed 进来；其它值行为未定义）。
      verdicts: 该 case 最近若干 run 的 verdict，**新→旧**排列，元素取值
                'pass'/'fail'/'error'/'skip'。缺某次 run 的记录就不出现在列表里。
      rounds:   认定 CANDIDATE 需要的「连续全 pass」次数阈值。

    为何用「连续 N 次 run 全 pass」而非「最近一次 pass」：bug-0009 的教训
    （§14 R28）——间歇性 BUG 单次跑绿是假阳性。这是跨 run 的稳健性闸门，与 case
    单次 run 内的重复轮次（rounds-in-case，由 YAML 自己控制）是不同维度、可叠加。
    """
    non_skip = [v for v in verdicts if v in ("pass", "fail", "error")]

    if status == "fixed":
        if any(v in ("fail", "error") for v in non_skip):
            return REGRESSION, f"最近 {len(non_skip)} 次有 fail/error（修好的又坏了）"
        if non_skip:
            return OK, "最近仍 pass，一致"
        return NO_DATA, "最近 run 无有效 verdict（全 skip/无记录）"

    # status == "open"
    if not non_skip:
        return NO_DATA, "最近 run 无有效 verdict（全 skip/无记录）"
    if all(v == "pass" for v in non_skip):
        if len(non_skip) >= rounds:
            return CANDIDATE, f"最近连续 {len(non_skip)} 次全 pass（≥阈值 {rounds}，疑似已修）"
        msg = f"最近 {len(non_skip)} 次 pass 但 < 阈值 {rounds}（采样不足，先别 flip）"
        return THIN_EVIDENCE, msg
    return EXPECTED, "最近仍 fail（BUG 仍复现，符合 open 预期）"
