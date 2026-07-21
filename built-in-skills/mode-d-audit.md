# Mode D: 健康审计

> 对已有明道云应用做系统级公理合规扫描。输出评分卡、问题清单（按严重度排序）、修复建议。

## Pipeline Overview

```
Step 1 ──→ Step 2 ──→ Step 3 ──→ Output
 扫描准备    五维度扫描   门控验证    审计报告+评分卡+DAG图+SOP
⛔数据不可用时停      ⛔Agent3不通过时补扫
```

| Step | 名称 | 类型 | 产出物 |
|------|------|------|--------|
| 1 | 扫描准备 | ⛔ BLOCKING（数据不可用时） | 项目快照 + 数据完整性确认 |
| 2 | 五维度扫描 | AUTO | 公理1-5 逐项检查结果 |
| 3 | 门控验证 | ⛔ BLOCKING（Agent 3 不通过时） | 扫描完整性确认 |
| 最终 | 输出 | AUTO（门控通过后） | 审计报告 + DAG 图 + SOP |

> **执行纪律**：非 BLOCKING 步自动连续推进，不等待用户。⛔ 标记的步骤必须停等确认后才进入下一步。

---

## 触发条件

用户说"检查一下这个项目""审计XX应用""看看有没有问题""健康度""项目体检"。

## 前置加载

- `system-prompt.md` — 元公理和设计公理
- `references/unified-design-spec.md` — 扫描维度与详细门控唯一真源
- `references/tool-dispatch.md` — **🚨 强制**：工具调度卡（禁止用 grep/curl 替代）
- `agents/verification-orchestrator.md` — Agent 3 调用、格式校验和裁决合并
- `~/Documents/workflow-output/{项目名}/project-snapshot.md` — 全景快照（先加载）
- `~/Documents/workflow-output/{项目名}/project_context.json` — 当前项目快照
- `~/Documents/workflow-output/{项目名}/aliases.json` — 术语映射
- `~/Documents/workflow-output/{项目名}/business-flow-manifest.json` — 工作流读写清单
- **如果 manifest/context 不可用或不完整 → 加载 `references/runtime-probe.md` → 走 hap-bridge 实时降级流（按优先级抽样）**

开始前必须设置真实项目路径：

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.claude/skills/hhr-plan}"
PROJECT_DIR="$HOME/Documents/workflow-output/<当前项目名>"
REPORT_DIR="${PROJECT_DIR}/reports"
AUDIT_REPORT="${REPORT_DIR}/audit-report.md"
STATE_FILE="${REPORT_DIR}/mode-d-verification-state.json"
CONTEXT_FILE="${PROJECT_DIR}/project_context.json"
MANIFEST_FILE="${PROJECT_DIR}/business-flow-manifest.json"
GRAPH_FILE="${PROJECT_DIR}/dependency_graph.json"
```

`<当前项目名>` 必须来自用户确认或 registry 唯一匹配。示例项目路径不得进入实际命令。

---

## Step 1: 扫描准备

🚧 **GATE**：前置文件已加载。

### ⛔ BLOCKING — 数据源不可用或不完整时

manifest/context 不可用或不完整 → 停止，加载 `references/runtime-probe.md` → 走 hap-bridge 实时降级流（按优先级抽样）。数据就绪后再继续。

### 严重度分级

| 级别 | 定义 | 示例 |
|------|------|------|
| **Critical** | 数据丢失或业务流程硬中断 | 孤儿记录、双向关联、查询空→中止 |
| **Major** | 可维护性严重受损，未来必出问题 | 命名混乱、编号无前缀、缺少默认值 |
| **Minor** | 偏离最佳实践，建议优化 | 颜色语义不标准、字段排列不统一 |
| **Info** | 信息性提示 | 可复用→建议封装、相似模块→建议统一 |

### ✅ Checkpoint

```markdown
## ✅ Step 1 完成
- [x] 项目快照已加载
- [x] 数据源完整性已确认（或已走降级流）
- [ ] **Next**: 自动进入 Step 2
```

---

## Step 2: 五维度扫描

🚧 **GATE**：Step 1 完成，数据源就绪。

### 公理1 数据血缘检查

```
□ 所有新增节点是否回写父引用 (MUST)
□ 主子表创建顺序是否正确 (MUST)
□ 流程参数命名是否携带语义 (MUST)
□ 跨表查询是否使用精确查找 (MUST)
□ 获取方式是否用"直接获取"而非"动态获取" (MUST)
□ 是否存在孤儿记录——创建时不回写来源的数据行 (MUST NOT)
```

### 公理2 人在回路检查

```
□ 审批类流程是否使用按钮触发而非定时/事件触发 (MUST)
□ 审批是否配置了限时处理和邮件通知 (MUST)
□ 审批人为空时是否由流程拥有者代理 (MUST)
□ 是否存在定时触发替代人工决策 (MUST NOT)
□ 是否存在发起人自动通过自己审批 (MUST NOT)
```

### 公理3 自文档化检查

```
□ 自动编号是否拼音前缀+日期+流水号 (MUST)
□ 父子表命名是否括号标注关系 (MUST)
□ 单选颜色是否冷→暖语义梯度 (MUST)
□ 字段命名是否符合规范（布尔→是否XX, 名称→可搜索） (MUST)
□ 工作流命名是否动词+名词 (MUST)
□ 通知消息是否内联引用字段值 (MUST)
□ 字段排列是否符合规范（身份→业务→关联→汇总） (MUST)
```

### 公理4 单向依赖检查

```
□ 是否存在双向关联 (MUST NOT — Critical)
□ 是否存在DAG环路 (MUST NOT — Critical)
□ Hub表是否被相关表单向引用 (MUST)
□ 他表字段是否仅用于只读场景 (MUST)
```

### 公理5 优雅降级检查

```
□ 查询/获取节点是否配置"未获取到时继续执行" (MUST)
□ 子流程是否逐条执行+中止时继续下一条 (MUST)
□ 状态/日期/拥有者字段是否设默认值 (MUST)
□ 是否存在"未获取到数据时中止流程" (MUST NOT — Critical)
```

### 跨公理检查

```
□ 可复用逻辑是否封装为模板（公理1+公理3）
□ 是否有"可能用到"的预留字段（违反增量构建硬纪律4）
□ 新模块是否单向引用Hub（公理4+增量框架）
```

### ✅ Checkpoint

```markdown
## ✅ Step 2 完成
- [x] 公理1 数据血缘: 已扫描
- [x] 公理2 人在回路: 已扫描
- [x] 公理3 自文档化: 已扫描
- [x] 公理4 单向依赖: 已扫描
- [x] 公理5 优雅降级: 已扫描
- [x] 跨公理检查: 已扫描
- [ ] **Next**: 自动进入 Step 3
```

---

## Step 3: 门控验证 — Agent 3 审计扫描完整性

🚧 **GATE**：Step 2 完成，五维度扫描已完成，审计报告初稿已生成。

严格执行 `agents/verification-orchestrator.md`：

1. 计算 `AUDIT_REPORT` 原始字节的 SHA-256，并把摘要、`AUDIT_REPORT`、
   `CONTEXT_FILE` 和 `system-prompt.md` 的真实绝对路径完整提供给 Agent 3。
2. 将 Agent 3 原始 JSON 保存为 `/tmp/hhr_agent3_output.json`。
3. 创建顶级 JSON 对象 `${STATE_FILE}`，记录 Mode、报告路径和当前项目；不得把审计 Markdown 当合并目标。
4. 运行格式校验和原子合并：

```bash
python3 "${SKILL_DIR}/scripts/validate-agent-output.py" \
  --agent3 "/tmp/hhr_agent3_output.json"
python3 "${SKILL_DIR}/scripts/verification_merge.py" \
  --target "${STATE_FILE}" \
  --source "${AUDIT_REPORT}" \
  --agent3 "/tmp/hhr_agent3_output.json" \
  --mode audit
```

`validate-agent-output.py` 返回 0 只代表格式完整，仍必须确认 `semantic_verdict=pass`。
合并器退出码 1 表示语义失败，退出码 2 表示格式或输入失败；两者都必须阻断最终输出。

### ⛔ BLOCKING

- 格式失败：修正 Agent 输入或重新调用 Agent 3，不写 gates。
- 语义失败：按 `missed_dimensions`、`uncovered_constraints`、`false_negatives`
  补扫后重新调用 Agent 3。
- 重检仍失败：保留失败 state，报告 blocker；不得把审计标记为完成，不得手工改 pass。

### ✅ Checkpoint

```markdown
## ✅ Step 3 完成
- [x] Agent 3 输出格式: pass
- [x] Agent 3 语义裁决: pass
- [x] mode-d-verification-state.json 已原子写入 gates
- [ ] **Next**: 自动进入最终输出
```

---

## 最终输出

🚧 **GATE**：Step 3 通过，扫描完整性已确认。

### 审计评分卡

```
总分: X/100
公理1 (数据血缘): X/20
公理2 (人在回路): X/20
公理3 (自文档化): X/20
公理4 (单向依赖): X/20
公理5 (优雅降级): X/20
```

### 问题清单（按严重度排序）

```
[Critical] N处
  - [描述] [违反的公理/约束] [修复建议]
  - ...

[Major] N处
  - [描述] [违反的公理/约束] [修复建议]

[Minor] N处
  - ...

[Info] N处
  - ...
```

### 默认输出物（三项）

审计完成后，输出以下三项（均保存到 `reports/<项目名>/`）：

**1. 审计报告 (Markdown)**
评分卡 + 问题清单（按严重度排序）+ 修复优先级。

**2. DAG 拓扑图 (HTML)**
从 `project_context.json` 提取 relation_graph → 调用 **baoyu-design** 生成交互式 DAG 图：
- 表→表单向引用，按模块着色
- Hub 表放大加粗边框
- 支持缩放/拖拽/点击高亮
- 输出到 `designs/<项目名>-topology/topology-dag.html`

**3. SOP 操作卡片 (HTML)**
逐表提取字段 + 工作流 + 按钮触发 → 调用 **baoyu-design** 生成交互式操作指南：
- 流程总览（四步流转图）
- 步骤详情（可展开，逐字段说明）
- 操作按钮面板（阶段×按钮×工作流触发）
- 工作流节点链路可视化
- 常见问题 FAQ
- 输出到 `designs/<项目名>-sop/<工作表名>.html`

SOP 同步生成 **Markdown 版**（`reports/<项目名>/sop/<工作表名>.md`），使用 `references/templates/sop-markdown.md` 模板。Markdown 版供打印、git 版本追踪和全文搜索。

### 修复与执行交接

Mode D 只产出审计，不直接生成或执行 `execution_contract.json`。用户批准修复后：

1. 显式切换到 Mode B。
2. 由 Mode B 更新 `execution_lock.json` 并完成 Agent 1/2 门控。
3. 仅在 gates 通过后运行 `lock_to_contract.py` 派生并校验
   `execution_contract.json`。
4. 再次停等用户确认后，才可交给 `hap-flow-exec`。

禁止从审计报告直接拼装执行合约。

### ✅ Pipeline Complete

```markdown
## ✅ Mode D 健康审计完成
- [x] Step 1: 扫描准备（项目快照 + 数据完整性）
- [x] Step 2: 五维度扫描（公理1-5 + 跨公理检查）
- [x] Step 3: 门控验证（Agent 3 扫描完整性）
- [x] 输出: 审计报告 + 评分卡 + 问题清单 + DAG 图 + SOP
- [x] 如需修复，已路由 Mode B；本次审计未直接执行
```
