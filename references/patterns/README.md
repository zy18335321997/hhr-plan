# 可复用模式库

> 从几建（338个工作流）提炼的业务模式和工作流设计模板。Mode A/B 设计时作为起点，减少重复造轮子。

## 目录结构

```
patterns/
├── README.md                    ← 本文件
├── modules/                     ← 工作流结构模式（按数据流签名分类）
│   ├── pattern-a-data-interrogation.md
│   ├── pattern-b-conditional-iteration.md
│   ├── pattern-c-query-modify.md
│   ├── pattern-d-pure-signal.md
│   └── pattern-e-complex-integration.md
├── approval/                    ← 审批流程模式
│   ├── _index.md
│   ├── single-sign.md
│   ├── multi-level.md
│   ├── conditional-approval.md
│   └── retreat-refill.md
├── trigger/                     ← 触发模式
│   ├── _index.md
│   ├── button-trigger.md
│   ├── event-trigger.md
│   └── subprocess-trigger.md
├── notification/                ← 通知策略模式
│   ├── _index.md
│   └── approval-result.md
└── data-validation/             ← 数据校验模式
    ├── _index.md
    ├── required-field-check.md
    ├── dedup-check.md
    └── parent-child-consistency.md
```

## 使用方式

### 结构模式 (modules/)

设计时加载 `built-in-skills/pattern-select.md`，按**数据流签名**匹配：

| 模式 | 文件 | 数据流签名 | 几建占比 | 典型场景 |
|------|------|----------|---------|---------|
| Pattern A 数据聚合 | `modules/pattern-a-data-interrogation.md` | Query→Query→Query | ~15% | 多源聚合查询后操作 |
| Pattern B 条件迭代 | `modules/pattern-b-conditional-iteration.md` | Branch→... | ~12% | 多路径条件分支决策 |
| Pattern C 查询修改 | `modules/pattern-c-query-modify.md` | 1→1 | 48.6% | 状态转换（最常见） |
| Pattern D 纯信号 | `modules/pattern-d-pure-signal.md` | 0→0 | 23.0% | 通知/提醒/状态推送 |
| Pattern E 复杂集成 | `modules/pattern-e-complex-integration.md` | 2+→2+ | 15.0% | 多表编排/跨模块同步 |

### 领域模式 (approval/ trigger/ notification/ data-validation/)

设计时按**业务场景**匹配，加载对应目录下的 `_index.md` 查自动选择表。

| 目录 | 模式数 | 自动选择表 | 几建证据 |
|------|--------|----------|---------|
| `approval/` | 6 | 审批单人→single-sign / 多级→multi-level / 条件→conditional / 退回→retreat-refill | 65个审批流 |
| `trigger/` | 6 | 人工决策→button / 数据级联→event / 复用逻辑→subprocess | 338个流全量 |
| `notification/` | 6 | 审批结果→approval-result / 任务分配→task-assignment / 告警→alert-escalation | 512个CRUD映射 |
| `data-validation/` | 6 | 去重→dedup-check / 主子→parent-child / 非空→required-field | 241个空处理节点 |

### 加载顺序

```
1. pattern-select.md → 按数据流签名匹配 modules/ 中的结构模式
2. 按业务场景 → 加载对应领域目录的 _index.md
3. 从自动选择表定位具体模式文件
4. 根据模式文件中的节点链模板组装工作流
```

### 模板格式

每个模式文件包含：
- 场景（触发条件）
- 最小节点链（T0→Tn 模板）
- 常见变体（含复杂度分级）
- 公理约束（逐节点对照表）
- 几建证据（数据支撑）
