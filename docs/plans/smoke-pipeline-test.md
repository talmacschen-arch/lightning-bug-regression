# Sprint: smoke-pipeline-test

实测新 review 流水线(reviewer 前置闸门 + smoke 后置,design.md v1.22)。
单个安全 doc 任务,目的是完整触发 specialist→reviewer→武装→CI→merge→smoke 链,
验证新 wiring 真按设计跑。

## 任务

- [x] **doc-pipeline-section**（deliverable 完成 PR #183 `e41e88a`；但本 sprint 的 smoke-gate 环节**暴露了 v1.23 编排 bug**——foreman 后台派 smoke 后即退、r25_violation，smoke 验收实际由人工补跑拿 GO 基线。bug 已由 PR #184 修复、PR #185 `smoke-gate-e2e-verify` 真 foreman 实跑端到端验证）: 让 doc-writer 在 `README.md` 的"多 agent 自动协作"
      相关章节附近,加一段简短(~10-15 行)的 "Review 流水线(v1.22)" 说明,概括新流程:
      specialist 开 PR(不武装 auto-merge)→ foreman 派 reviewer(§14 + 6 域审查)作
      **merge 前置闸门** → reviewer APPROVE 后**由 foreman**武装 auto-merge → CI 绿
      自动 merge → foreman 派 smoke-runner 真集群验收(NO-GO 自动开 revert PR)。
      内置 `/review` `/ultrareview` 由用户**手动**调,不进自动流水线。
      只改 README.md,不碰代码。
