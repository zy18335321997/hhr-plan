# implementation-notes: 结构化确认协议

## 设计

对标 ppt-master 的 Eight Confirmations 双层依赖排序设计。

### Mode A — Design Confirmations（插在 Step 1 和 Step 2 之间）

Tier 1 (锚点 — 先确认):
  a. 核心实体 — 五问推导产出的 Hub 候选
  b. 泳道概览 — 角色×动作×时机
  c. 关联方向 — 单向引用 Hub，谁指向谁

Tier 2 (派生 — 从用户确认的 Tier 1 重新推导):
  d. 工作表结构 — 表数/字段估算/Hub 分配
  e. 工作流触发 — 每个工作流的触发方式（按钮/事件/定时）
  f. 命名方案 — 应用哪个编号前缀/动词前缀

### Mode B — Change Confirmations（重构现有 Step 0）

Tier 1 (锚点 — 先确认):
  a. 涉事表 + 已有工作流数
  b. 项目命名规范
  c. 修改范围 — 新增/修改/扩展

Tier 2 (派生 — 从 Tier 1 推导):
  d. 数据链路验证 — 上下游依赖
  e. 影响面评估 — 受影响工作流数
  f. 工作流节点链路 — 修改目标的完整节点链（仅涉及修改时）

### 执行规则
- Tier 1 是 BLOCKING — 用户确认后才能推进
- Tier 2 从用户实际确认的 Tier 1 重新推导，不预设
- 非 UI 路径，全部在 chat 中完成

### 与 ppt-master 的差异
- 不需要 UI 页面（hhr-plan 输出不是视觉产物）
- 确认项是 3+3 而非 4+4（设计决策正交维度更少）
- 不是独立 Step，而是嵌入现有流水线的确认门

## 状态
✅ 完成 (2026-06-26)

### Mode A: 新增 Design Confirmations Step（Step 1 和 Step 2 之间）
- Tier 1: a.核心实体 b.泳道概览 c.关联方向
- Tier 2: d.工作表结构 e.工作流触发策略 f.命名方案

### Mode B: Step 0 重构为双 Tier
- Tier 1: a.涉事表确认 b.项目命名规范 c.修改范围
- Tier 2: d.数据链路验证 e.影响面预览 f.工作流节点链路
