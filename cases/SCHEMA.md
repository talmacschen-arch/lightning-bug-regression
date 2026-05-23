# cases/ YAML schema

权威定义见 `design.md` §4.1（用例 YAML schema，v0.5 step 级 `expect:` 写法 + v0.7 顶层 `category:` 字段 + v0.9 `host:` / `destructive:` / 4-tuple 叙事字段）。

子目录按 `category` 分：

- `bug-regression/` — `category: bug_regression`，status 枚举 `open / fixed / wontfix / stub`
- `extension/` — `category: extension`，status 枚举 `stable / experimental / deprecated / stub`

门类元数据由 `case_categories` 表（design.md §4.5）驱动，schema 校验 / UI / skill 对齐题 / 目录扫描全部从 `GET /admin/categories` 拉，**不在代码硬编码**。新增门类按 design.md §13.3 的 5 步法。

本文件在 M3a（runner schema 校验落地）时填实际示例与字段表。当前为占位。
