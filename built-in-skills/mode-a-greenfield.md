# Mode A: 绿地设计

> 从零设计一个新的明道云应用。输入是业务需求，输出是完整的表结构+工作流+字段配置方案。

## Pipeline Overview

```
Step 0 ──→ Step 1 ──→ Design ──→ Step 2 ──→ Step 3 ──→ Step 4 ──→ Step 5 ──→ Step 6 ──→ Step 7 ──→ Output
 平台边界+筛选  五问推导  Confirm    建表      建工作流    字段配置    视图设计    模式库匹配   门控      设计文档+SOP
⛔不可行时停           ⛔用户确认                              ⛔Agent双不通过时停
```

| Step | 名称 | 类型 | 产出物 |
|------|------|------|--------|
| 0 | 平台边界确认 + 需求筛选 | ⛔ BLOCKING（不可行时） | 可行性结论 |
| 1 | 五问推导 | AUTO | 核心实体 + 泳道初稿 |
| **确认** | **Design Confirmations** | **⛔ BLOCKING（Tier 1 + Tier 2）** | **已确认的锚点 + 派生决策** |
| 2 | 建表 | AUTO | 工作表清单 + Hub表结构 |
| 3 | 建工作流 | AUTO | 工作流节点链路 |
| 4 | 字段配置 | AUTO | 逐字段详细配置 |
| 5 | 视图设计 | AUTO | 按角色视图方案 |
| 6 | 模式库匹配 | AUTO | 模式匹配报告 |
| 7 | 门控 | ⛔ BLOCKING（Agent 不通过时） | 校验结果 |
| 最终 | 输出 | AUTO（门控通过后） | 设计文档 + SOP + execution_lock |

> **执行纪律**：非 BLOCKING 步自动连续推进，不等待用户。⛔ 标记的步骤必须停等确认后才进入下一步。

---

## 触发条件

用户说"设计一个XX""新建XX应用""做一个XX系统"，且项目尚未存在于 `~/Documents/workflow-output/projects_registry.json` 中。

## 前置加载

- `system-prompt.md` — 元公理与设计公理
- `references/theorems-and-protocols.md` — 定理与执行协议
- `references/unified-design-spec.md` — 三层详细门控唯一真源
- `references/tool-dispatch.md` — **🚨 强制**：工具调度卡（禁止用 grep/curl 替代）
- `references/platform/node-capabilities.md` — **必须先加载**，了解平台能做什么、不能做什么
- `references/data-model-derivation.md` — 五问推导法
- `agents/verification-orchestrator.md` — Agent 调用、输出校验和裁决合并
- `references/templates/` — 按需加载字段配置模板

---

## Step 0: 平台边界确认 + 需求筛选

🚧 **GATE**：前置文件已加载。用户描述了业务需求。

### 0.1 平台能力确认

```
1. 需求中涉及的工作流节点类型，在 platform/node-capabilities.md 中有对应吗？
2. 需求中涉及的关联方式，平台是否支持？（一对多/多对多等）
3. 是否有明显的平台限制？（如审批退回只支持发起节点、子流程不支持并行等）
```

**必须输出**: 平台可行性结论（可行 / 需调整 / 不可行）

### 0.2 需求筛选

加载 `requirement-triage.md`，执行需求筛选四问（Q1-Q4）。

### ⛔ BLOCKING — 需求筛选不通过时必须停止

```
□ 平台不可行 → 直接说明原因，不进入 Step 1
□ 需求已存在 → 指向现成方案，不重复设计
□ 不做 → 说明原因
```

### ✅ Checkpoint

```markdown
## ✅ Step 0 完成
- [x] 平台能力确认（可行 / 需调整）
- [x] 需求筛选通过
- [ ] **Next**: 自动进入 Step 1
```

---

## Step 1: 客户需求 → design_ir

🚧 **GATE**：Step 0 通过，需求可行。

```
1. 业务围绕哪几个东西转？→ 核心实体（Hub候选）
2. 谁在什么时候做什么？→ 角色×动作×时机，初画泳道
3. 数据从哪来、到哪去？→ 录入/生成/引用
4. 需要查什么？→ 视图需求
5. 什么条件触发下一步？→ 工作流触发条件
```

把五问结果写成 `execution_lock.design_ir` 草案：

1. 每条客户需求分配稳定 `REQ-*`，保留原话和验收标准。
2. 定义角色、业务场景、实体职责、状态机、规则、权限、视图、按钮、通知和异常路径。
   - 每个拥有独立开始/结束条件的业务对象单独建状态机。
   - 禁止把询价、订单、收货、付款等独立生命周期压成主单的一条“大状态”。
   - 每个状态机至少覆盖正常推进、退回/拒绝、撤回或取消、失败补偿和终态。
3. 建立 `requirement → entity/field/state_machine/workflow/view/permission` 追踪。
4. 在确认前加载 `pattern-select.md`，把命中的模式合并进 design_ir；模式只提供候选，
   不得覆盖客户确认的规则。
5. 不确定项进入 `assumptions`，标注置信度和待确认状态；不得因为待确认就停止生成
   条件化完整方案。

### ✅ Checkpoint

```markdown
## ✅ Step 1 完成
- [x] 核心实体已识别（Hub 候选）
- [x] 泳道初稿已完成（角色 × 动作 × 时机）
- [x] 数据流向已标注
- [x] design_ir 已覆盖状态机、权限、视图和需求追踪
- [x] 模式库已在确认前匹配并合并
- [ ] **Next**: 进入 Design Confirmations（⛔ BLOCKING）
```

---

## Design Confirmations: ⛔ BLOCKING

🚧 **GATE**：Step 1 完成，design_ir 草案已产出。确认门只锁定会改变系统结构的
决策；其余不确定项保留为显式假设，确认后继续给出完整条件化方案。

> 一次性交付完整的条件化设计预览：Tier 1 是业务锚点，Tier 2 是基于锚点的系统
> 派生。两层必须在同一个回复中呈现；不得只给 Tier 1 就停止。用户确认的是执行
> 锚点，不是阻止 Agent 展开完整方案。

### Tier 1 — 锚点确认（先确认，再往下）

**a. 核心实体（Hub 候选）**

从五问推导 Step 1 中提取。列出每个核心实体及其一句话定义：

| 实体 | 一句话定义 | Hub？ |
|------|-----------|-------|
| [实体名] | [一句话] | 是/否 |

**b. 泳道概览**

从五问推导 Step 1 中提取。角色×动作×时机的关键路径：

```
角色A → 动作X → 触发 → 角色B → 动作Y → ...
```

**c. 关联方向**

核心实体间的单向引用关系（公理4）：

```
[Hub表A] ← [表B]  （原因：...）
[Hub表A] ← [表C]  （原因：...）
```

继续生成 Tier 2。未确认项标注 `待确认` 和采用该假设时的影响，不在此处停。

---

### Tier 2 — 派生确认（从 Tier 1 重新推导后呈现）

> ⚠️ Tier 2 必须从当前 Tier 1 锚点推导。待确认锚点使用条件化假设并明确影响；
> 用户修改锚点后，整份 Tier 2 必须重新派生。

**d. 工作表结构**

从确认的核心实体 + 关联方向推导：

| 工作表 | 类型 | 七维字段覆盖 | 关联方向 | 对应需求 |
|--------|------|-------------|---------|---------|
| [表名] | Hub/子表/关联表 | 身份/业务/状态/时间/归属/关联/审计 | →/←← | REQ-* |

**e. 工作流触发策略**

从确认的泳道推导每个工作流的触发方式：

| 工作流 | 触发方式 | 决策依据 |
|--------|---------|---------|
| [流名] | 按钮/事件/定时 | 涉及人工决策→按钮（公理2）/ 纯数据级联→事件 / 可复用→子流程 |

**f. 命名方案**

从项目命名规范推导：

| 规则 | 约定 |
|------|------|
| 编号前缀 | [2-4字母拼音] + YYYYMMDD + 3位流水号 |
| 工作流动词 | [新增/发布/生成/修改/...] |
| 子表标识 | [子表名（父表名/操作类型）] |

**g. 状态机与异常路径**

逐个有状态实体列出状态、正常转换、退回/拒绝/撤回、异常补偿、触发角色和对应
工作流。必须先列出“哪些实体有独立生命周期”；遗漏任一独立生命周期不能通过确认。

**h. 角色落点**

逐角色列出权限范围、默认视图、可见按钮、通知和不可执行动作。

⛔ **完整呈现 Tier 1、Tier 2、状态机、权限视图和需求追踪后，停等一次确认。**
确认前可以输出完整设计文档草案，但不得生成可执行 gates 或进入 CLI。

### ✅ Checkpoint

```markdown
## ✅ Design Confirmations 完成
- [x] Tier 1 锚点已确认（核心实体 + 泳道 + 关联方向）
- [x] Tier 2 派生已确认（七维表结构 + 状态机 + 触发策略 + 角色落点）
- [x] 用户确认后的值已写入后续步骤
- [ ] **Next**: 自动进入 Step 2
```

---

## Step 2: 建表

🚧 **GATE**：Design Confirmations 完成，核心实体和关联方向已锁定。

按增量构建框架的四个阶段执行：
- 阶段0: 识别核心实体 → Hub候选
- 阶段1: 核心Hub表（覆盖已确认需求与七维字段）
- 阶段2: 第一个业务流程（端到端完整闭环，含退回和异常）
- 硬纪律: 没走通完整闭环前，不建第三张表

每个表默认按 Hub 设计。
字段数量只作复杂度提示，不作为完成标准；完成标准是需求追踪 100%、状态转换可闭环、
每个交互角色都有权限和视图落点。

### ✅ Checkpoint

```markdown
## ✅ Step 2 完成
- [x] 核心 Hub 表已覆盖已确认需求和七维字段
- [x] 第一个业务流程的正常、退回和异常闭环已走通
- [x] 表间引用关系为单向（公理4）
- [ ] **Next**: 自动进入 Step 3
```

---

## Step 3: 建工作流

🚧 **GATE**：Step 2 完成，表结构已建立。

加载 `references/workflow-design-derivation.md`，按六步推导法执行：

**3.1 识别数据状态转换**

从 Step 1 泳道中提取：每个泳道步骤 → 一次数据状态转换 → 一个候选工作流。
如果一个步骤同时包含"人工判断"和"数据级联"，拆成两个工作流。

**3.2 确定触发方式**

按 workflow-design-derivation.md §第二步 的决策树，为每个工作流选定触发方式。
涉及人工决策→按钮（公理2）；纯数据级联→工作表事件；可复用逻辑→子流程。

**3.3 确定数据流签名**

标注每个工作流的读（查询/获取节点数）和写（新增/更新节点数），归入四种原型：
Mutator(1→1) / Signal(0→0) / Creator(0→1) / Orchestrator(2+→2+)

**3.4 匹配复杂度分级 + 模式库**

按节点数分级：Simple(2-3) / Standard(4-6) / Complex(7-10) / VComplex(11+)
加载 `pattern-select.md`，匹配 `references/patterns/modules/` 下的已有模式。
VComplex 必须使用子流程拆分（元公理A）。

**3.5 逐节点公理约束对照**

按 workflow-design-derivation.md §第五步 速查表，逐节点检查公理约束。

**3.6 输出时序标注（定理1）**

T0→T1→...→Tn，每个节点标注写入字段。验证：Tn 只读 T0..T{n-1} 已写的字段。

### ✅ Checkpoint

```markdown
## ✅ Step 3 完成
- [x] 每个数据状态转换 → 一个候选工作流
- [x] 触发方式已按公理2决策
- [x] 数据流签名已标注（Mutator/Signal/Creator/Orchestrator）
- [x] 复杂度分级 + 模式库匹配完成
- [x] 时序标注 T0→Tn 完成（定理1）
- [ ] **Next**: 自动进入 Step 4
```

---

## Step 4: 字段配置

🚧 **GATE**：Step 3 完成，工作流节点链路已确定。

逐字段按模板输出。加载 `references/templates/` 下所需模板文件。

### ✅ Checkpoint

```markdown
## ✅ Step 4 完成
- [x] 逐字段类型/默认值/必填/可见性已配置
- [x] 关联表引用方向已标注（公理1/4）
- [x] 布尔字段以"是否"开头（公理3）
- [ ] **Next**: 自动进入 Step 5
```

---

## Step 5: 视图设计

🚧 **GATE**：Step 4 完成，所有字段已配置。

按角色输出视图方案：

```
| 角色 | 视图名称 | 包含字段 | 默认筛选 | 排序 |
|------|---------|---------|---------|------|
```

### ✅ Checkpoint

```markdown
## ✅ Step 5 完成
- [x] 每个角色至少一个视图
- [x] 视图包含字段/筛选/排序
- [ ] **Next**: 自动进入 Step 6
```

---

## Step 6: 需求追踪与完整度复核

🚧 **GATE**：Step 5 完成，设计方案已完整。

逐条检查 `design_ir.traceability`：

- 每个 `REQ-*` 至少落到一个实体/字段和一个可验收行为。
- 每个有状态实体都有正常、退回/拒绝和异常路径。
- 每个交互角色都有权限、视图和按钮落点。
- Step 1 命中的模式已实际回填字段与节点，不只是附加一份匹配报告。

### ✅ Checkpoint

```markdown
## ✅ Step 6 完成
- [x] 客户需求追踪率 100%
- [x] 状态机与角色落点完整
- [x] 模式候选已合并到实际设计
- [ ] **Next**: 自动进入 Step 7
```

---

## Step 7: 门控 — 脚本预检 + Agent 并行校验

🚧 **GATE**：Step 1-6 完成，`execution_lock.json` 已生成。先设置真实路径：

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.claude/skills/hhr-plan}"
PROJECT_DIR="<本次设计产物的绝对目录>"
LOCK_FILE="${PROJECT_DIR}/execution_lock.json"
DESIGN_SPEC="${PROJECT_DIR}/design_spec.md"
CONTEXT_FILE="${PROJECT_DIR}/project_context.json"
GRAPH_FILE="${PROJECT_DIR}/dependency_graph.json"
VALIDATOR_RESULT="/tmp/hhr_design_validation.json"
```

`PROJECT_DIR` 不得使用示例项目或其他项目路径。

### 7.0 脚本预检（自动，先跑）

按 `references/unified-design-spec.md` 完成三层门控，并运行确定性验证。任一命令失败 → 阻断、修正、重跑：

```bash
python3 "${SKILL_DIR}/scripts/contract_compat.py" validate-lock "${LOCK_FILE}"
python3 "${SKILL_DIR}/scripts/design_ir_validator.py" "${LOCK_FILE}"
python3 "${SKILL_DIR}/scripts/design_spec_linter.py" "${DESIGN_SPEC}" \
  --lock-file "${LOCK_FILE}"
python3 "${SKILL_DIR}/scripts/design_validator.py" "<项目名>" \
  --lock-file "${LOCK_FILE}" \
  --context-file "${CONTEXT_FILE}" \
  --graph-file "${GRAPH_FILE}" \
  --check-graph \
  --output "${VALIDATOR_RESULT}"
python3 "${SKILL_DIR}/scripts/verify-platform.py" --lock-file "${LOCK_FILE}"
```

### 7.1 Agent 1/2 并行校验

严格执行 `agents/verification-orchestrator.md`：

1. 准备只读上下文包：

```bash
python3 "${SKILL_DIR}/scripts/agent_prepare.py" "${LOCK_FILE}" \
  --validator-result "${VALIDATOR_RESULT}" \
  --output "/tmp/hhr_agent_brief.json"
```

2. 在同一轮并行调用 Agent 1/2，将原始 JSON 分别保存为 `/tmp/hhr_agent1_output.json` 和 `/tmp/hhr_agent2_output.json`。
3. 先验证格式，再合并语义裁决：

```bash
python3 "${SKILL_DIR}/scripts/validate-agent-output.py" \
  --agent1 "/tmp/hhr_agent1_output.json" \
  --agent2 "/tmp/hhr_agent2_output.json"
python3 "${SKILL_DIR}/scripts/verification_merge.py" \
  --target "${LOCK_FILE}" \
  --agent1 "/tmp/hhr_agent1_output.json" \
  --agent2 "/tmp/hhr_agent2_output.json" \
  --mode design
```

`validate-agent-output.py` 返回 0 只表示格式完整；必须同时检查输出中的
`semantic_verdict`。`verification_merge.py` 退出码 1 或 2 都是阻断，不得继续生成执行合约。

### 7.2 lock → execution contract

只有确定性 contract/preflight 与 Agent 语义裁决都通过后，才派生执行合约：

```bash
SAFE_WORKFLOW_NAME="<仅含字母、数字、下划线和短横线的工作流安全文件名>"
CONTRACT_FILE="${PROJECT_DIR}/execution_contracts/${SAFE_WORKFLOW_NAME}.json"
python3 "${SKILL_DIR}/scripts/lock_to_contract.py" "${LOCK_FILE}" \
  --workflow "<精确工作流名称>" \
  --output "${CONTRACT_FILE}"
python3 "${SKILL_DIR}/scripts/contract_compat.py" validate-exec \
  "${CONTRACT_FILE}"
```

多工作流 lock 必须逐个使用精确名称和不同的安全文件名转换，统一写入
`execution_contracts/`，不得覆盖。任何缺失 ID、alias、配置、依赖或发布顺序的转换
失败都必须阻断，禁止猜值或手工编辑执行合约。

平台写入验证不属于设计门控。用户确认执行后，由 `hap-flow-exec` 负责真实平台写入与
验证；设计阶段不得用发布动作冒充只读校验。

### ✅ Checkpoint

```markdown
## ✅ Step 7 完成
- [x] lock / 项目字段依赖 / 平台机械检查: pass
- [x] Agent 1/2 输出格式: pass
- [x] Agent 1/2 语义裁决: pass，gates 已原子写入 execution_lock.json
- [x] execution_contract.json 已由 lock 派生并通过结构校验
- [ ] **Next**: 自动进入最终输出
```

---

## 最终输出

🚧 **GATE**：Step 7 全部通过，且执行合约由 lock 成功派生。

### 设计文档 (Markdown)

每个输出必须声明：

- **模式**: Mode A
- **公理覆盖**: 每个决策追溯到公理编号
- **外推置信度**: HIGH (有数据支撑) / MEDIUM (公理推导) / LOW (公理间张力)
- **门控结果**: 确定性 contract/preflight、Agent 1/2 格式与语义

### SOP 操作卡片 (HTML + Markdown)

设计完成后，为每个有工作流的新建表生成 SOP。加载 `references/templates/sop-markdown.md` 模板。

HTML 版调用 **baoyu-design** 渲染交互式操作指南。Markdown 版用于打印和版本追踪。

### 口语检验

输出前加载 `plain-language-check.md`，将配置术语替换为客户语言。

### 两阶段合约（强制）

Schema 和闭环命令参考 `references/templates/execution-lock-schema.md`。

```
1. 设计阶段只编辑 execution_lock.json。
2. verification_merge.py 是 Agent gates 的唯一写入入口。
3. gates 通过后，由 lock_to_contract.py 生成 execution_contract.json。
4. design_spec.md 供人阅读；execution_contract.json 供 hap-flow-exec 使用，两者都不能覆盖 lock。
```

输出后必须停等用户确认。用户确认前不得调用 `hap-flow-exec`；确认后只交付已校验的
`execution_contract.json`，不得把 `execution_lock.json` 直接当执行输入。

### ✅ Pipeline Complete

```markdown
## ✅ Mode A 绿地设计完成
- [x] Step 0: 平台边界确认 + 需求筛选通过
- [x] Step 1: 五问推导（核心实体 + 泳道）
- [x] Design Confirmations: 用户已确认 Tier 1（锚点）+ Tier 2（派生）
- [x] Step 2: 建表（Hub 表 + 最小闭环）
- [x] Step 3: 建工作流（六步推导法 + 时序标注）
- [x] Step 4: 字段配置（逐字段模板）
- [x] Step 5: 视图设计（按角色）
- [x] Step 6: 模式库匹配
- [x] Step 7: 门控（Agent 1 + Agent 2 双通过）
- [x] execution_lock.json 已生成并验证通过
- [x] execution_contract.json 已严格派生并验证通过
- [x] 输出: 设计文档 + SOP + execution_lock.json + execution_contract.json
- [x] 已停等用户确认，尚未执行
```
