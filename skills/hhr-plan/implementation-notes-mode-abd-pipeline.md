# implementation-notes: Mode A/B/D Pipeline 改造

**状态**: ✅ 完成 (2026-06-26)

## Phase 2 完成项

| # | 改动 | 状态 |
|---|------|------|
| execution_lock.json | lock_manager.py + schema 文档 + Mode A/B 集成 | ✅ |
| 结构化确认协议 | Mode A Design Confirmations + Mode B Tier 1/2 重构 | ✅ |
| Pattern 目录扩充 | 4 新目录 × 13 个模式文件 + 各 _index.md | ✅ |

## Mode A 设计

### Pipeline: Step 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → Output
### BLOCKING 点
- Step 0 需求筛选不通过 → ⛔ 停止，按响应分级处理
- Step 7 门控 Agent 双不通过 → ⛔ 修正方案后重检

### 非 BLOCKING 步
- Step 1-6 全部 AUTO（五问推导→建表→建工作流→字段→视图→模式库）
- Step 2 建表后不设 BLOCKING——Mode A 是绿地，没有已有系统需要确认

## Mode B 设计

### Pipeline: Step 0 → 1 → 2 → 3 → Output
### BLOCKING 点
- Step 0 上下文确认 → ⛔ 必须用户确认（原文件已标注，加 ⛔ 显式化）
- Step 1 影响面 >10 → ⛔ Hard Stop（原有，保留）

### 非 BLOCKING 步
- Step 2 增量构建 AUTO（Step 0 确认后连续推进到门控）
- Step 3 门控自检 AUTO（如不通过则拦截修正）

## Mode D 设计

### Pipeline: Step 1 → 2 → 3 → Output
### BLOCKING 点
- 数据源不可用 → ⛔ 停止，走降级流（runtime-probe）
- 门控 Agent 3 不通过 → ⛔ 补扫缺失维度

### 非 BLOCKING 步
- 五维度扫描全部 AUTO 推进

## 偏离
- Mode A Step 2 不设 BLOCKING（与 ppt-master Eight Confirmations 不同），因为绿地设计没有"已有系统"需要对齐
- Mode B Step 0 已有"确认后才能进入"语义，只加 ⛔ 标记，不改逻辑
- Mode D 扫描维度保持原有 checklist 格式，不拆成独立 Step
