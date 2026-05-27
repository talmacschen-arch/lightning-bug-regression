# Pipeline Probe (throwaway)

这是一次性的流水线验证探针文件,用于实测目标 review 流水线:

- **A**: reviewer 作为 merge 前闸门——开 PR 后不武装 auto-merge,等 reviewer verdict + CI 都 OK 才事后武装。
- **B**: smoke NO-GO 自动开 revert PR——本探针 merge 后会被一个 revert PR 移除。

设计稿: docs/plans/review-pipeline-completion.md
验证日期: 2026-05-28

> 本文件预期会被随后的 revert PR 删除,main 最终不保留它。
