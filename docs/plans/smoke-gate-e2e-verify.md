# Sprint: smoke-gate-e2e-verify

验证 v1.23(PR #184, merge `40942da`)修好的**端到端链**:foreman 在 merge 后
**前台同步**派 smoke-runner 并**在同一轮消费 GO/NO-GO**,然后正常 emit final JSON
(不再 r25_violation)。上一轮 smoke-pipeline-test 卡在这——foreman 后台派 smoke
后即退,smoke verdict 从没回来。这一轮就是要看修法在真 foreman 进程里真的走通。

单个安全 doc 任务,触发完整链:specialist→reviewer→武装→CI→merge→**前台 smoke**→
消费 verdict→final JSON。

## 任务

- [x] **doc-smoke-foreground-note**（完成 PR #185 `9b5a121`；smoke GO，r25_violation=false，端到端链已验证）: 让 doc-writer 在 `README.md` 的
      "Review 流水线（v1.22）" 章节末尾,追加一条简短(2-4 行)的 **v1.23 更正**说明:
      smoke-runner 由 foreman 在 merge 后**前台同步**(synchronous)派发,**不是**后台
      (`run_in_background`)——因 foreman 跑在 `claude --print` 一次性进程里,终态门
      若背景化会 orphan 子 agent 且丢 final JSON;前台同步保证 GO/NO-GO 在同一轮被
      消费。引用 design.md §15.1 hard rule 5 + v1.23 changelog。
      只改 README.md,不碰代码、不碰 design.md / foreman.md。
