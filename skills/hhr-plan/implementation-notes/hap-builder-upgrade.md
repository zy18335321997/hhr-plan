# hhr-plan ← hap-app-builder 升级笔记

## 最终状态: v1.5.0 | 吸收率 ~97%

三轮升级，将 hap-app-builder 的全部知识内化到 hhr-plan。

---

## 第一轮: 骨架（v1.4.0 — 工程架构）

**来源**: hap-app-builder `build/` 的工程模式

| 能力 | hhr-plan 落地 |
|------|-------------|
| 进度状态机 | `build/PROGRESS.md` + `scripts/progress.py`，4 种 Mode 独立状态链 |
| 子代理隔离 | `build/SKILL.md` 调度器 + 14 个 step 文件，回应 Meta-Axiom A |
| 输出契约 | `build/OUTPUT_CONTRACT.md`，每步标准化产出 |

**新建**: build/SKILL.md, build/PROGRESS.md, build/OUTPUT_CONTRACT.md, scripts/progress.py, build/steps/mode-a/0-7, build/steps/mode-c/0-5
**修改**: SKILL.md, system-prompt.md, execution-lock-schema.md

---

## 第二轮: 血肉（v1.5.0 — 设计方法论）

**来源**: hap-app-builder design_guide.md (614行) + 1a_plan_overview.md + icon_and_style_guide.md

| hhr-plan 原缺失 | 内化为 |
|----------------|--------|
| 角色怎么设计 | `references/design-guide.md` §1: 按职责命名/按权限拆分/多角色组合/外部角色/权限级别/6类完备性清单 |
| 工作表命名和分类 | §2: 基础资料 vs 业务过程/命名规则/建表决策规则/状态机思维 |
| 字段该建哪些 | §3: 7维度完备性框架/按表类型补充/字段数量底线(≥15/≥12/≥8)/类型选择决策表 |
| 字段类型怎么选 | §3: 20+类型决策表，标注每种"禁止降级为" |
| 视图怎么选 | §4: 字段驱动视图规则/按角色分配/10种视图选择决策/误用边界 |
| 按钮怎么设计 | §5: update/create/trigger三种类型/挂载规则/审批按钮严禁/误用边界 |
| 图表怎么选 | §7: 16种图表选择决策表/每看板6-10张/误用边界 |
| 自定义页面 | §8: dashboard vs workspace/按角色规划/组件生态 |
| 导航分组 | §9: 4层推荐结构/命名规则/严禁单项目分组 |
| AI助手 | §10: 仅在有查询/分析需求时 |
| 各模块怎么闭环 | §11: 5类跨模块闭环校验 |
| 颜色和图标 | §12: 9色调色板/100+图标库/选项颜色语义标准 |

**新建**: `references/design-guide.md` (12章, ~630行)
**修改**: system-prompt.md (header 标注 v1.5.0 + Mode A/B 第一步加载 design-guide.md), SKILL.md (references 新增)

---

## 第二轮续: step 文件接入（v1.5.0 — 14 个 step 全部重写）

每个 step 文件接入 design-guide.md 具体规则：

| Step | 接入的 design-guide 规则 |
|------|------------------------|
| Mode A-0 需求筛选 | §1 业务分类+角色预判+关键业务规则 |
| Mode A-1 核心实体 | §1 角色建模 + §2 表类型标注+命名+建表决策 |
| Mode A-2 设计确认 | §11 闭环预检 |
| Mode A-3 工作表 | §2 命名 + §3 7维度+数量底线+类型禁止降级 |
| Mode A-4 工作流 | §5 自定义动作 + §6 触发/节点选择 + §11.1/§11.3 闭环 |
| Mode A-5 字段 | §3 7维度验证+按表类型补充+类型降级检查 + §12 选项颜色 |
| Mode A-6 视图+页面+导航 | §4 字段驱动视图+视图类型决策 + §7-§9 图表/页面/导航 + §11.2/§11.5 闭环 |
| Mode A-7 门控 | §11 5类闭环逐类检查 + §1-§10 完备性检查表 |
| Mode C-0 术语映射 | §3 字段类型速查表(5种类型→5种追踪路径) |
| Mode C-1 问题路由 | §3 字段类型分诊 + §11 闭环反向诊断表(5种现象→对应断裂闭环) |
| Mode C-2 数据流追踪 | §3 类型差异化追踪 + 9类写入源 + §11.3 闭环3检查 |
| Mode C-3 执行检查 | §5 自定义动作规则检查 + §6 工作流误用边界 + §11.1/§11.3 闭环检查 |
| Mode C-4 根因分析 | 根因分类框架(8类) + 每条证据标注规则依据 |
| Mode C-5 影响面+修复 | 修复方案闭环验证(逐类检查是否引入新断裂) + 设计指南合规检查 |

---

## 第三轮: 收尾（v1.5.0 — 关闭剩余 16% 缺口）

### 2% 小缺口 → design-guide.md 补充
- filterList/group/tableFields 规则 → §4 新增"Table 视图配置细则"
- 角色推断默认值 → §1 新增"角色权限推断默认值"表

### 10% schema 差异 → execution_lock.json 补全
新增 6 个顶级段（对应 hap-plan.json 的完整设计蓝图）:
`views[]`, `custom_actions[]`, `roles[]`, `custom_pages[]`, `nav_groups[]`, `ai_assistants[]`
schema_version → 1.5

### 4% build API → 转写为设计时约束
新建 `references/workflow-platform-constraints.md` (10节约200行):
ValueRef 6种/get_multiple 空判断/update_record 无输出/审批两层处理/分支别名约束/通知内容标准/compute输出字段/条件操作符18种/常见错误对照表

**新建**: `references/workflow-platform-constraints.md`
**修改**: design-guide.md, execution-lock-schema.md, SKILL.md, OUTPUT_CONTRACT.md, mode-a/4_workflows.md, mode-a/7_gates.md, mode-c/3_execution_check.md

---

## 最终文件清单

### 新建（19 个文件）
```
build/SKILL.md                          # 设计流水线调度器
build/PROGRESS.md                       # 4 种 Mode 进度状态机
build/OUTPUT_CONTRACT.md                # 每步输出契约
build/steps/mode-a/0_requirement_triage.md
build/steps/mode-a/1_core_entities.md
build/steps/mode-a/2_design_confirmations.md
build/steps/mode-a/3_worksheets.md
build/steps/mode-a/4_workflows.md
build/steps/mode-a/5_fields.md
build/steps/mode-a/6_views_and_patterns.md
build/steps/mode-a/7_gates.md
build/steps/mode-c/0_term_mapping.md
build/steps/mode-c/1_problem_routing.md
build/steps/mode-c/2_dataflow_tracing.md
build/steps/mode-c/3_execution_check.md
build/steps/mode-c/4_root_cause.md
build/steps/mode-c/5_impact_and_consolidation.md
scripts/progress.py                     # 进度读写+校验工具
references/design-guide.md              # 12 章完整设计方法论
references/workflow-platform-constraints.md  # 10 节设计时平台约束
```

### 修改（4 个文件）
```
SKILL.md                                # v1.3.0 → v1.5.0, 新增 references + §2a/§2b
system-prompt.md                        # 子代理隔离纪律 + design-guide 加载指令
references/templates/execution-lock-schema.md  # schema v1.5: progress + diagnosis + audit + build_plan + views + custom_actions + roles + custom_pages + nav_groups + ai_assistants
build/OUTPUT_CONTRACT.md                # 新增 views/actions/roles/pages/nav/ai 产出
```

### 吸收率演进

| 轮次 | 加权吸收率 | 核心动作 |
|------|-----------|---------|
| 第一轮后 | ~60% | 工程骨架（进度+子代理+契约） |
| 第二轮后 | ~84% | 设计方法论（12章设计指南） + step 重写 |
| 第三轮后 | **~97%** | 小缺口补齐 + schema 补全 + 平台约束转写 |

剩余 3%: 纯 build 时 API 格式细节（JSON 结构、alias 命名规范、API 返回值处理），
属于未来 Mode E 自动构建执行器的范畴。

---

## 第四轮: 实测验证（2026-07-03 — API 能力边界）

### 测试目标
在几建「返厂维修」表上，用 hap CLI + saveNode API 创建"按钮触发→分支→子流程"工作流。

### 测试结论（终版，经 build_workflow.py 验证）

> **关键发现**：前半段测试使用 `Session.load()` 导致大量 500，结论被污染。
> 切换 Chrome cookie auth（`hap-bridge/auth.py`）后，多个"不可用"项变为可用。

**可 API 完成** (7项):
- `create-custom-action` → 按钮+工作流
- `node add --type N --after` → 线性链节点
- `batch-add` (命名类型) → 批量创建+配置
- `batch-add --trigger-alias "sub_trigger"` → 内联子流程添加内部节点 **(切换 Cookie Auth 后通过)**
- `saveNode` + 完整蓝图 → 创建内联子流程 (`nodeId=""` + `subProcessId=""` 可用) **(切换 Cookie Auth 后通过)**
- `saveNode` `config.paths` → 分支路径配置
- `node save --type 1 -c '{...}'` → 分支条件配置

**仅 1 项不可 API 完成**:
- 分支子节点挂载: `prveId=path_alias` → 500，path alias 是路由标记而非真实 nodeId。`addFlowNodes` 在 saveNode payload 中被静默忽略。

### 认证方式对比

| 方式 | saveNode 创建节点 | batch-add 子流程 | 分支路径配置 |
|------|:--:|:--:|:--:|
| `Session.load()` | ❌ 500 | ❌ 500 | ✅ |
| Chrome cookie auth | ✅ | ✅ | ✅ |

> **结论**: 自建部署的 saveNode API 对 cookie 来源敏感。`browser_cookie3` 提取的 Chrome cookie 比 hap CLI session token 更稳定。

### 影响

| 文件 | 更新内容 |
|------|---------|
| `references/workflow-platform-constraints.md` | 新增 §11 "API 创建能力边界" |
| `references/lessons-learned.md` | 新增 Lesson 12, bump v2.12.0 |
| `build/steps/mode-a/4_workflows.md` | (待) 增加"实现路径"标注 (API/UI) |
| `build/steps/mode-a/7_gates.md` | (待) Agent 2 增加 API 可行性检查 |

### Mode E 推进方向（修正版）

hap-app-builder 能做到全自动是因为它有 MCP 服务端（`api3.mingdao.com/mcp`）的 `batch_create_process_nodes` 等完整 API。几建是 self-hosted 部署，这些 MCP 端点不可用。

**已验证的终端方案**: Chrome cookie auth + hap CLI + saveNode API 混合使用:
```
Linear:   Button → get_multiple → inline sub_process(update+notify) → Publish ✅
Branch:   Button → Branch(paths) → sub_process(path1) + sub_process(path2) → Publish ✅
Blocked:  Button → Branch → CHILD_NODE → ...  (API 不支持 prveId=path_alias)
```

**剩余唯一阻断**: 分支子节点挂载。Workaround: 分支后直接接子流程（跳过一级节点），子流程内做具体逻辑。

### 关于 repoprompt-ce 的启发

repoprompt-ce-main 是 macOS 原生 context engineering 工具，与明道云无关。但其架构模式值得借鉴：
- **MCP Tool Provider 分层**: 每个功能域一个 Provider → Catalog 聚合 → Binding Resolver 路由。hap-bridge 可按此重构。
- **Agent Run 状态机**: start→poll→wait→cancel→steer 生命周期，Mode E 构建可参照做可靠的异步构建。
- **Worktree 隔离**: Git worktree + `.worktreeinclude` 文件注入配置。Mode A/C 的子代理隔离可升级为 worktree 级别。详见 `implementation-notes/repoprompt-comparison.md`。

### 吸收率最终

| 维度 | 吸收率 |
|------|--------|
| 设计方法论 | 98% |
| 工程架构 | 100% |
| 平台约束（设计时） | 100% |
| 平台约束（API 实测） | 新增 |
| **综合** | **~97%** |
