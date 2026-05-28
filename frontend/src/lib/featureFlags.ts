// §M7-followup (2026-05-28): 单个可变 singleton object 持有 feature 开关。
// 用 object 而非 module-level const 是为了让 vitest 能在 beforeEach/afterEach
// 里 flip 单个字段——直接 mutate 属性、避开 vi.mock 的 hoisting 复杂度。
//
// 恢复完整 LLM 入口：把 `llmFeatureEnabled: false` 改成 `true`，单文件一行。
export const flags = {
  llmFeatureEnabled: false,
};
