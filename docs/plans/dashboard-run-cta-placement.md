# 设计稿：跑测试入口重新放置（New Run CTA）

状态：**设计稿，待命未开干**（用户 2026-05-28 要求先设计不实操）
范围：纯前端布局，**零后端改动**。

## 1. 问题

跑测试是本工具的核心动作，但当前在全站**没有显眼入口**：

- 侧边栏只有 Dashboard / Cases / Runs / Admin，**没有任何"发起 run"入口**。
- Dashboard 上唯一的跑测试触发是 `QuickActions`（"Run all X (status: Y)" 预设按钮），位于
  KPI 两行 + Recent activity **之后的最底部**，要滚到底才看得到。
- `/runs/new`（真正选 case 跑的页面）只能靠纯文字链接（"Trigger one from /runs/new"）
  或手敲 URL 进入。

## 2. 目标 / 成功标准

- 从**任意页面** ≤1 次点击能发起 run（侧边栏常驻入口）。
- Dashboard 上跑测试入口在**首屏可见**，不用滚动。
- 预设快捷（按分类整批跑）保留，但从底部上移到显眼处。
- 不破坏现有 `data-testid` 契约（§13.11 / §17 R6），不动后端，不动 `/runs/new` 页本身。

## 3. 用户已确认的两个决策（2026-05-28）

- **放置**：侧边栏全局「▶ New Run」主按钮 + Dashboard 顶部 CTA（两处都加）。
- **目标行为**：两个「New Run」CTA → `/runs/new` 空白态（手动选 case）；
  Dashboard 预设快捷仍带 `?category=X&status=Y` 过滤跳 `/runs/new`。职责分明：
  - **New Run CTA** = 通用入口，自己挑 case。
  - **Quick start 预设** = 按分类整批跑的快捷。

## 4. 改动详情

### 4.1 侧边栏全局按钮（`components/Layout.tsx`）

- 位置：`.sidebar-brand` 与 `.sidebar-nav` 之间（导航项**上方**，视觉上是动作不是分区）。
- 形态：`<Link to="/runs/new">` 包一个主按钮样式 —— **复用 `components/ui/button.tsx`**
  （`variant="default"` 主色），用 `asChild` 包 `<Link>`（shadcn link-button 惯例；
  落地时确认 `<Button>` 支持 `asChild`，不支持则 `<Link>` 外层 + `className={buttonVariants()}`）。
- `data-testid="sidebar-new-run"`（对齐 `sidebar-nav-*` 契约命名）。
- 文案 `▶ New Run`；图标加 `aria-hidden`，按钮整体有可读 label。
- 因 Layout 包裹所有路由，**每页都在**。

### 4.2 Dashboard 顶部 CTA（`routes/DashboardPage.tsx`）

- 标题行从单独 `<h1>` 改成 flex 行：左 `Dashboard`，右 `[▶ New Run]` 主按钮。
  复用同一个 `<Button>` 组件（与侧边栏同款，避免第三种样式）。
- `data-testid="dashboard-new-run"`，`→ /runs/new`。
- CSS：标题行加 `display:flex; align-items:center; justify-between`（可在 `.dashboard-title`
  外包一个 `.dashboard-header` 类，不改 `.dashboard-title` 本身字号）。

### 4.3 预设快捷上移 + 更名（`routes/DashboardPage.tsx`）

- 把 `<QuickActions>` 从 JSX 末尾（`<RecentActivity>` 之后）**移到标题行之后、KPI 行之前**。
- section 标题文案 `Quick actions` → `Quick start`（更准确：这是跑测试的快捷，不是泛"操作"）。
- **保留** `data-testid="dashboard-quick-actions"` + 每个 `dashboard-quick-action-<cat>-<status>`
  testid 与跳转行为（`/runs/new?category=X&status=Y`）**完全不变** —— 测试依赖它们（§9 项目约定）。

### 4.4 Dashboard 新布局顺序（从上到下）

1. 标题行：`Dashboard` + `[▶ New Run]` CTA
2. **Quick start**（预设，上移到这）
3. KPI 行 1（分类计数 + recent runs）
4. KPI 行 2（status breakdown）
5. Recent activity

## 5. 样式决策（CLAUDE.md §5：不平均两种写法）

项目按钮两套并存：`<Button>`（shadcn，4 处在用、有测试）vs dashboard/sidebar 的一次性
纯 CSS class（`.dashboard-quick-action`）。**新的主 CTA 复用 `<Button>` 组件**（更稳定、
有测试覆盖），不再造第三种样式。`.dashboard-quick-action` 预设按钮**本次不动**（只移位置 +
改 section 标题），其纯-CSS 风格作为既存不一致留给后续统一清理，不在本设计范围。

## 6. 测试影响

- `DashboardPage.test.tsx`：① 现有 QuickActions 断言因 testid 不变仍通过（只是渲染顺序变）；
  ② **新增**断言 `dashboard-new-run` CTA 存在且 `href`/点击 → `/runs/new`。
- `Layout` 若有测试：新增 `sidebar-new-run` 存在断言。（落地时先 `ls frontend/src/components/Layout.test.tsx` 确认是否存在。）
- 验证意图（§7 铁律）：断言不只是"按钮存在"，要 assert **点击/href 真的导向 `/runs/new`**，
  以及预设按钮 href 真带 `?category=&status=`。

## 7. 非目标 / out of scope

- 不改后端、不改 `POST /runs`、不改 `RunNewPage`。
- 不删除空态文字链接（"/runs/new"）。
- 不动侧边栏 `active-run-pip` / 用户区。
- 不统一 `<Button>` vs 纯-CSS 的历史不一致（标出，留后续）。

## 8. 落地顺序建议（实操阶段，非本次）

1. 先 `ui/button` 确认 `asChild` 支持 + 看一个现有 `<Button asChild><Link>` 用例对齐写法。
2. 改 `Layout.tsx`（侧边栏按钮）→ 改 `DashboardPage.tsx`（CTA + 移 QuickActions + 更名）→
   `index.css` 加 `.dashboard-header` flex。
3. 补/改 vitest（DashboardPage + Layout），跑 `tsc + eslint + vitest`。
4. 走正常 PR 流程（specialist 开 PR 不武装 → reviewer → CI → merge）。
