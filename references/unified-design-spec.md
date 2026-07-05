# 统一设计规范 — 三层校验框架

> 整合 hhr-plan 6 门控（正确性）+ hap-app-builder 5 闭环（完整度）+ workflow_rules.md（可构建性）
> 所有模式（A/B/C/D）输出设计方案前，逐层自检。

---

## 框架总览

```
输入: 设计方案（表+字段+工作流节点+视图+按钮+通知）
  │
  ▼
第一层: 完整度闭环 (5 checks)  ← hap-app-builder 来源
  "该设计的都设计了吗？有没有漏的？"
  │
  ▼
第二层: 正确性门控 (6 gates)  ← hhr-plan 来源（增强）
  "设计的东西对吗？会不会出错？"
  │
  ▼
第三层: 可构建性 (7 rules)    ← workflow_rules.md 来源
  "设计能翻译成 API 调用吗？会炸吗？"
  │
  ▼
输出: 可执行方案
```

---

## 第一层：完整度闭环（Completeness）

> 来源: hap-app-builder plan/design_guide.md + plan/1b_plan_schema.md
> 时机: 节点设计完成后

### 闭环 1: 视图 ↔ 字段

```
□ 每个视图的 filter 中引用的字段选项值，在对应字段的 options 中确实存在？
□ 看板视图: 分组字段是否有 ≥3 个选项值？
□ 日历视图: 日期字段是否确实存在于该工作表中？
□ 每个视图设置了 quickFilters（3-5 个高频字段）？
□ 「全部」视图如有 ≥5 个选项的单选字段 → 设了 filterList 左侧分类导航？
```

### 闭环 2: 字段 ↔ 工作流

```
□ 时间敏感状态（如"逾期"、"已超期"、"即将到期"）→ 是否有对应的自动标记工作流？
  - 例: 借阅记录.状态=逾期 → 必须有定时/日期字段触发的工作流标记
□ 工作流写入的字段值 → 字段的 options 中是否存在？
  - 例: 工作流写 状态←已归还 → "已归还"必须在 状态 字段的 options 中
□ 工作流读取的字段 → 在工作流触发时是否有值？（见第三层时序校验）
□ 公式/汇总字段的依赖字段 → 是否被正确写入？
```

### 闭环 3: 按钮 ↔ 字段 ↔ 工作流

```
□ 每个 triggerWorkflow 按钮 → 是否有对应的工作流设计？
  - 按钮名称和触发的工作流名称是否一致？
□ 每个按钮的 enableCondition 引用的字段 → 是否存在？
  - 例: enableCondition = "状态 = 借阅中 或 逾期"
  - 字段"状态"存在 + 选项值"借阅中""逾期"存在
□ 按钮触发的工作流结果 → 是否写回该按钮所在表的字段？
  - 用户点完按钮后能看到状态变化
□ createRelatedRecord 按钮 → 源表是否有到达目标表的关联字段？
  - 例: 在借阅记录上建"入库申请" → 借阅记录必须有→入库申请的关联字段
□ 绝对禁止: "审批通过"/"审批驳回"/"审批否决" 按钮
  - 这些必须走 approval_block，不能是自定义按钮
```

### 闭环 4: 页面 ↔ 视图

```
□ 仪表盘上的图表/统计 → 依赖的视图是否存在？
□ 工作台上的按钮 → 是否已有对应的自定义动作？
□ 嵌入的视图 → 视图名称和筛选条件是否匹配工作台上的目标用户？
□ 导航分组 → 所有工作表/页面/AI 助手都在且只在唯一一个分组中？
```

### 闭环 5: 工作流数据闭环

```
□ 主表状态变更 → 关联表是否需要联动更新？
  - 例: 归还成功 → 图书表.状态: 借出→在库
□ 关键操作 → 有没有创建日志/记录？
□ 审批/状态变更 → 有没有通知到相关人员？
  - 通过 → 通知发起人/借阅人
  - 否决 → 通知发起人/借阅人
  - 异常/逾期 → 通知责任人
□ 通知内容是否包含足够上下文？
  - ✅ "您借阅的《三国演义》已确认归还，归还日期：2026-07-05。"
  - ❌ "借阅归还有更新，请查看。"
```

---

## 设计质量约束

> 来源: hap-app-builder 设计规范（平台实战验证）。Mode A/B 设计输出前必须逐项检查。

### 字段数量下限

| 表类型 | 最少字段 | 示例 |
|--------|:--:|------|
| 主数据表 (客户/图书/商品/设备) | >= 15 | 编号+名称+分类+规格+状态+创建人+... |
| 业务单据表 (订单/借阅记录/工单) | >= 12 | 编号+关联+数量+日期+状态+负责人+... |
| 流程事务表 (入库单/巡检记录) | >= 8 | 编号+关联+状态+时间+备注+... |

### 七维字段覆盖

每张表必须覆盖 7 个维度（每维 >= 1 字段）。第 2 维（核心业务属性）最常被忽略：

1. **主标识** — 编号/名称/标题
2. **核心业务属性** — 该实体独有的关键属性
3. **状态与分类** — 状态/类型/标签
4. **时间维度** — 创建/开始/结束/截止日期
5. **责任与协作** — 拥有者/负责人/参与人
6. **数量与金额** — 数值/金额/计数
7. **备注与附件** — 说明/备注/附件/图片

### 视图驱动规则

| 字段条件 | 必须创建的视图 |
|----------|-------------|
| 自引用或回环关联字段 | 层级图 |
| 单选 >= 3 个选项 | 看板 |
| 位置字段 | 地图 |
| 附件中有核心图片内容 | 画廊 |
| 计划开始+结束日期 | 甘特图 |
| 时间段+人员/资源字段 | 资源图 |
| 单记录配置表 | 详情(mode=first) |

### consistencyNotes

每张表输出时携带 `consistencyNotes`：
- 哪些字段 options 支持哪些视图 filter
- 哪些字段被哪些工作流读写
- 自定义按钮的 enableCondition 依赖了哪些字段
- 关联字段方向 + 目标表

---

## 第二层：正确性门控（Correctness）

> 来源: hhr-plan 5 公理 → 6 Gate（增强版：整合 workflow 设计规则）
> 时机: 完整度闭环全部通过后

### Gate 1: 依赖图

```
□ 查过 dependency_graph.json？
  - Mode A 新表: 确认不产生 DAG 环路（单向依赖，公理4）
  - Mode B 改造: 列出所有读写该表/字段的工作流
□ 新增关联 → 是否产生双向引用？
  - 禁止: A→B 且 B→A
  - 允许: A→B←C（Hub-Spoke）
□ 影响面评估:
  - ≤3 个工作流受影响 → 列出名称
  - 4-10 个 → 输出依赖关系图
  - >10 个 → Hard Stop
```

### Gate 2: 逻辑校验（整合 workflow 设计 8 规则）

```
□ 数据血缘（公理1）:
  - 新增记录 → 回写父引用
  - 主子表 → 先主后子
  - 查询 → 按记录ID精确查；未获取到→继续执行

□ 人在回路（公理2）:
  - 人工决策 → 按钮触发（不用定时触发）
  - 审批 → 或签 + 退回仅发起节点
  - 审批人为空 → 拥有者代理
  - allowReject = true（显式开启）
  - initiators 必填

□ 自文档化（公理3）:
  - 编号 = 拼音前缀 + YYYYMMDD + 流水号
  - 布尔字段 = 是否XX
  - nodeAlias = 英文 snake_case
  - 参数名 ≠ param1/recordId

□ 关联表联动（step 9 rule 1）:
  - 逐表扫描 worksheetContext
  - 子表变化→主表统计/状态？主表修改→子表同步？

□ 前置查询（step 9 rule 2）:
  - 更新其他表 → 前面必须有查询节点
  - 定时工作流 → 无触发记录，必须先查询

□ 状态流转完整（step 9 rule 3）:
  - 状态变更 → 同步写时间戳 + 操作人 + 关联表状态

□ 分支处理（step 9 rule 4）:
  - get_single 结果 → 直接判断 rowid 是否 not_empty
  - get_multiple 结果 → 必须先 rollup COUNT → 再判断 count > 0
  - 分支覆盖所有可能的字段值

□ 单向依赖（公理4）:
  - 新关联 → 不产生环路
  - Hub 表集中属性
  - 他表字段仅用于只读展示

□ 优雅降级（公理5）:
  - 查询空 → 继续执行
  - 子流程 → 逐条执行 + 中止继续下一条
  - 状态/日期/拥有者 → 设默认值
```

### Gate 3: 时序校验

```
□ 标注了完整时序 T0(触发) → T1 → T2 → ... → Tn？
□ 列出了每个节点的写入字段？
□ Tk 读取的字段在 T0..T{k-1} 中是否已存在？
  - 已知错误: T0 就查"流程状态""审批状态" → 后面才写入 → ❌
□ 审批结果分支:
  - 内部: approve → branch(approval_result) → 写 executorid/opinionSummary
  - 外部: approval_block → branch(PASS/OVERRULE) → 业务处理
```

### Gate 4: 字段与实体存在性

```
□ 方案引用的每个字段名在工作表中存在？（查 project_context / worksheetContext）
□ 方案引用的每个工作表名存在？
□ 选项值在字段的 options 中存在？（用中文 value，不是 key）
□ 新表名/工作流名/按钮名不与已有名称重复？
□ 新编号前缀不与已有前缀冲突？
```

### Gate 5: 平台可行性

```
□ 节点类型          → 平台支持？
□ 关联方式          → 支持？
□ 子流程嵌套深度     → ≤2 层？
□ 总节点数          → ≤10 或已拆分子流程？
□ 批量操作          → CRUD ≤100 / 子流程 ≤10000？
□ 同一表多事件触发   → 有并发冲突风险？
□ 审批块            → typeId=26（非已弃用的 typeId=4）
□ 自定义动作工作流   → processId 是否已存在？（不能 create_process）
```

### Gate 6: 推理质量

```
□ 方案是否过度设计？能否删掉一半节点？
□ 是否有隐藏假设未标注？（标注置信度 HIGH/MEDIUM/LOW）
□ 方案所有决策是否可追溯到公理编号或设计规则？
□ 是否存在"我推断应该有这个字段"但未验证的情况？
```

---

## 第三层：可构建性（Buildability）

> 来源: hap-app-builder build/steps/workflow_rules.md
> 时机: 前两层全部通过后，出最终方案前
> 这些是"翻译成 API 调用时会炸"的物理约束，必须在设计阶段就排除

### BR1: ValueRef 引用

```
□ 字段引用 → kind: "field", 必须带 node + fieldId（真实 24 位十六进制 ID，严禁 alias）
□ 系统字段 → kind: "systemField", 只能 fieldId, 不能带 node
  - nowTime / triggertime / triggeraid
□ 固定值   → kind: "literal", value 为中文选项名（非 UUID key）
□ 整条记录 → kind: "record", node 指向触发记录或查询节点
□ 模板     → kind: "template", value 含 $nodeAlias-fieldId$ 或 $system-fieldId$
□ 空值     → kind: "empty"
```

### BR2: Condition 条件

```
□ left.node 始终必填，按上下文不同:
  ┌──────────────────────┬──────────────────────────────────┐
  │ 上下文               │ left.node 指向                    │
  ├──────────────────────┼──────────────────────────────────┤
  │ get_single/multiple  │ 查询节点自身 (如 find_book)       │
  │ 自身 filter          │ right.node 指向上游提供动态值     │
  ├──────────────────────┼──────────────────────────────────┤
  │ branch 条件          │ 上游数据源节点 (如 get_record)     │
  │                      │ 严禁指向分支自身                   │
  ├──────────────────────┼──────────────────────────────────┤
  │ 触发器 filter        │ 触发器节点自身                    │
  └──────────────────────┴──────────────────────────────────┘
□ 操作符合法枚举 (19个):
  eq / ne / gt / gte / lt / lte / in / not_in /
  empty / not_empty / contains / not_contains / starts_with / ends_with /
  all_contains / belongs / not_belongs / checked / unchecked
  禁止: equals / is_empty / ge / le / neq 等变体
□ Date/DateTime 字段用专用 conditionId（非通用数值）:
  lt→17(早于) / lte→42(早于等于) / gt→18(晚于) / gte→40(晚于等于)
□ config.target 而非 sourceNode — HAP NodeSpec 没有 sourceNode 属性
  update_record / cc / approval_block 的数据源统一用 config.target
□ systemField/nowTime 在 filter 中引用固定系统节点:
  {controlId: nowTime, nodeId: 5d39140d381d42d20db0c4da,
   appType: 100, nodeType: 100}
```

### BR3: 作用域隔离

```
□ 审批块内部:
  - 引用被审批记录 → { nodeAlias: "approval_start" }（固定别名）
  - approve 的 approvers 只能引用 approval_start 作用域内的字段
  - initiators 必填（通常绑定 ownerid）
  - fill_in assignee 是单个 PersonRef（非数组），formProperties >= 1
□ 子流程内部:
  - 引用当前记录 → { nodeAlias: "sub_trigger" }（固定别名）
  - 不能跨作用域引用主流程节点
  - 参数通过 sub_process 节点的 params 显式传入
□ 自定义动作工作流触发器引用:
  - 必须用物理 nodeId（从 get_workflow_structure 获取）
  - 严禁假设别名为 "trigger" → StartNodeControlsIsNull 致命错误
  - 普通工作表工作流: 用 nodeAlias（从 create_process 获取）
```


### BR4: 节点引用约束

```
□ update_record 节点执行后没有输出字段
  - 后续节点需要字段值 → 追溯引用触发节点或上游查询节点
  - 严禁引用 update_record 节点的字段 → StartNodeControlsIsNull 致命错误
□ rollup/compute 输出字段是固定常量:
  - rollup → number_fx_id
  - compute(number/dateDiff) → number_fx_id
  - compute(dateOffset) → date_fx_id
  - code → 自定义输出参数名
□ dateOffset 表达式严格格式:
  - 必须有符号 + 单位: "+30d", "-1d", "+3d"
  - 大小写敏感，数字无符号/单位 → INVALID_NODE 致命错误
□ systemField 在模板中必须用 $system-fieldId$，严禁 $nodeAlias-systemField$
□ wfstatus 是系统只读字段，不可写入 → 用自定义单选字段代替
```


### BR5: 分支路径约束

```
□ 分支后的节点 → prevNode 不能指向分支节点本身
  - 用 parentNode 挂到对应路径下
  - 路径下第一个节点的 prevNode = 路径 alias（与 parentNode 相同）
□ 分支路径 alias → 不能作为下游节点的 target.node
□ 不能作为下游节点的 prevNode（只用于层级组织）
```

### BR6: 审批结果两层处理

```
审批内部 (config.process.nodes):
  □ approve 节点之后
  □ branch(type: "approval_result")
  □ 写入 executorid / opinionSummary

外部主流程 (approval_block 之后):
  □ branch 判断 PASS / OVERRULE
  □ PASS → 更新业务状态 + 通知
  □ OVERRULE → 恢复/否决状态 + 通知
```

### BR7: 发布顺序

```
□ 含 sub_process / approval_block (mode: create) 时:
  1. batch_create/create 创建所有节点
  2. 从 batch-add 返回值提取 innerProcessId
  3. 先 publish 每个内部流程（审批块 → 子流程）
  4. 最后 publish 主流程
  违反 → NodeAppIsNull 致命错误
□ hap CLI 对应:
  hap workflow publish <inner_pid>   # 先内
  hap workflow publish <main_pid>   # 后主
```


---

## 三层校验通过标准

| 层 | 来源 | 通过条件 | 不通过处理 |
|----|------|---------|-----------|
| 第一层 完整度 | hap-app-builder | 5 闭环全部 ✅ | 补充缺失的视图/按钮/通知/联动 |
| 第二层 正确性 | hhr-plan | 6 Gate 全部 ✅ | 修正设计逻辑 |
| 第三层 可构建性 | workflow_rules.md | 7 Rule 全部 ✅ | 修正物理配置 |

三层全部通过后 → 输出方案。任一层未通过 → 修正后重新从该层开始。

---

## 模式适配

| 模式 | 第一层（完整度） | 第二层（正确性） | 第三层（可构建性） |
|------|:--:|:--:|:--:|
| Mode A（绿地设计） | 全跑 | 全跑 | 全跑 |
| Mode B（棕地改造） | 闭环 2,3,5 | 全跑 | BR3,4,5,7 |
| Mode C（诊断排查） | 不跑 | Gate 1,2,3 | BR2,3,4 |
| Mode D（健康审计） | 闭环 1,2,3 | Gate 5,6 | BR7 |

---

## 与原始公理的对应关系

| hhr-plan 公理 | 第二层 Gate | 第三层 Rule |
|-------------|------------|------------|
| 公理1 数据血缘 | Gate 2(数据血缘+前置查询+状态流转) | BR4(不可引用 update_record) |
| 公理2 人在回路 | Gate 2(人在回路) | BR3(作用域隔离) |
| 公理3 自文档化 | Gate 2(自文档化) | — |
| 公理4 单向依赖 | Gate 1 + Gate 2(单向依赖) | — |
| 公理5 优雅降级 | Gate 2(优雅降级) | BR7(发布顺序防崩溃) |
| 元公理A 上下文过载 | Gate 5(节点数<10) | — |
| 元公理B 平台知识 | — | BR1-7(全部) |
