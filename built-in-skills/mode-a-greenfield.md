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

- `system-prompt.md` — 全部公理+定理
- `references/tool-dispatch.md` — **🚨 强制**：工具调度卡（禁止用 grep/curl 替代）
- `references/platform/node-capabilities.md` — **必须先加载**，了解平台能做什么、不能做什么
- `references/data-model-derivation.md` — 五问推导法
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

## Step 1: 五问推导

🚧 **GATE**：Step 0 通过，需求可行。

```
1. 业务围绕哪几个东西转？→ 核心实体（Hub候选）
2. 谁在什么时候做什么？→ 角色×动作×时机，初画泳道
3. 数据从哪来、到哪去？→ 录入/生成/引用
4. 需要查什么？→ 视图需求
5. 什么条件触发下一步？→ 工作流触发条件
```

### ✅ Checkpoint

```markdown
## ✅ Step 1 完成
- [x] 核心实体已识别（Hub 候选）
- [x] 泳道初稿已完成（角色 × 动作 × 时机）
- [x] 数据流向已标注
- [ ] **Next**: 进入 Design Confirmations（⛔ BLOCKING）
```

---

## Design Confirmations: ⛔ BLOCKING

🚧 **GATE**：Step 1 完成，核心实体和泳道已产出。**这是设计中唯一的用户确认门。**

> 对标 ppt-master Eight Confirmations：Tier 1 确认锚点 → 从锚点重新派生 Tier 2。
> 两层确认在同一个 chat 回复中完成，Tier 1 确认后 AI 立即重新推导并呈现 Tier 2。

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

⛔ **停等用户确认或修改 Tier 1 的 a/b/c。** 用户回复后，从用户实际确认的锚点重新推导 Tier 2。

---

### Tier 2 — 派生确认（从 Tier 1 重新推导后呈现）

> ⚠️ Tier 2 的推荐值必须从用户实际确认的 Tier 1 重新推导，不得沿用你在 Tier 1 阶段预设的值。

**d. 工作表结构**

从确认的核心实体 + 关联方向推导：

| 工作表 | 类型 | 关键字段（估算） | 关联方向 | 公理 |
|--------|------|----------------|---------|------|
| [表名] | Hub/子表/关联表 | [3-5个] | →/←← | 公理N |

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

⛔ **再次停等用户确认或修改 Tier 2。** 用户回复后，自动进入 Step 2 建表。

### ✅ Checkpoint

```markdown
## ✅ Design Confirmations 完成
- [x] Tier 1 锚点已确认（核心实体 + 泳道 + 关联方向）
- [x] Tier 2 派生已确认（表结构 + 触发策略 + 命名方案）
- [x] 用户确认后的值已写入后续步骤
- [ ] **Next**: 自动进入 Step 2
```

---

## Step 2: 建表

🚧 **GATE**：Design Confirmations 完成，核心实体和关联方向已锁定。

按增量构建框架的四个阶段执行：
- 阶段0: 识别核心实体 → Hub候选
- 阶段1: 核心Hub表（最少字段集）
- 阶段2: 第一个业务流程（端到端最小闭环）
- 硬纪律: 没走通完整闭环前，不建第三张表

每个表默认按 Hub 设计。

### ✅ Checkpoint

```markdown
## ✅ Step 2 完成
- [x] 核心 Hub 表已建立（最少字段集）
- [x] 第一个业务流程的最小闭环已走通
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

## Step 6: 模式库匹配

🚧 **GATE**：Step 5 完成，设计方案已完整。

加载 `pattern-select.md`，检查需求是否匹配已有业务模块模板。如匹配，标注覆盖率和需定制部分。

### ✅ Checkpoint

```markdown
## ✅ Step 6 完成
- [x] 模式库匹配已完成
- [x] 覆盖率 + 需定制部分已标注
- [ ] **Next**: 自动进入 Step 7
```

---

## Step 7: 门控 — 脚本预检 + Agent 并行校验

🚧 **GATE**：Step 1-6 完成，`execution_lock.json` 已生成。

### 7.0 脚本预检（自动，先跑）

先跑确定性验证。不通过 → 修正 → 重跑。通过 → 继续：

```bash
# 平台机械校验（typeId/actionId/批量上限/拓扑）
python3 ${SKILL_DIR}/scripts/verify-platform.py --lock-file execution_lock.json

# 设计合约验证（字段存在性/关联方向/DAG环路）
python3 ${SKILL_DIR}/scripts/design_validator.py <项目名> --lock-file execution_lock.json
python3 ${SKILL_DIR}/scripts/design_validator.py <项目名> --check-graph
```

### 7.1 Agent 并行校验

加载编排协议：
```
Read agents/verification-orchestrator.md
```

### 执行步骤

**1. 准备 Agent 上下文包**

```bash
python3 ${SKILL_DIR}/scripts/agent_prepare.py execution_lock.json --output /tmp/hhr_agent_brief.json
```

**2. 并行启动两个 Agent（同时，不串行）**

两条 Agent 调用在同一轮发送，各自独立运行：

> **Agent 1 — logic-verify**: 读取 `/tmp/hhr_agent_brief.json` + `agents/logic-verify.md`，按五部分校验清单（公理合规/时序/命名/逻辑/推理质量）逐条执行，输出 JSON verdict。

> **Agent 2 — platform-verify**: 读取 `/tmp/hhr_agent_brief.json` + `agents/platform-verify.md`，逐节点检查（节点类型/子模式/数据链路/批量上限/空策略/拓扑），输出 JSON verdict。

**3. 收集结果 + 合并裁决**

两个 Agent 完成后，解析各自的 JSON 输出：

| Agent 1 | Agent 2 | 裁决 | 行为 |
|---------|---------|------|------|
| pass | pass | ✅ | 自动进入最终输出 |
| 任一 fail | — | ❌ | 修正 → 重检 |
| 修正 2 次仍 fail | — | ⛔ | 标注 LOW 置信度，报告用户 |

**4. 写入结果到 execution_lock.json**

```json
"gates": {
  "agent_1_logic": {"result": "pass|fail", "issues": [...]},
  "agent_2_platform": {"result": "pass|fail", "issues": [...]}
}
```

### ✅ Checkpoint

```markdown
## ✅ Step 7 完成
- [x] Agent 1 (逻辑校验): pass — N issues
- [x] Agent 2 (平台校验): pass — N issues
- [x] 裁决: 双通过，门控结果已写入 execution_lock.json
- [ ] **Next**: 自动进入最终输出
```

---

## 最终输出

🚧 **GATE**：Step 7 通过，双 Agent 校验 pass。

### 设计文档 (Markdown)

每个输出必须声明：

- **模式**: Mode A
- **公理覆盖**: 每个决策追溯到公理编号
- **外推置信度**: HIGH (有数据支撑) / MEDIUM (公理推导) / LOW (公理间张力)
- **门控结果**: Agent 1 (逻辑校验): pass/fail, Agent 2 (平台校验): pass/fail

### SOP 操作卡片 (HTML + Markdown)

设计完成后，为每个有工作流的新建表生成 SOP。加载 `references/templates/sop-markdown.md` 模板。

HTML 版调用 **baoyu-design** 渲染交互式操作指南。Markdown 版用于打印和版本追踪。

### 口语检验

输出前加载 `plain-language-check.md`，将配置术语替换为客户语言。

### execution_lock.json（强制，与设计文档同时产出）

设计文档定稿后，同步生成机器可读合约文件。Schema 参考 `references/templates/execution-lock-schema.md`。

```
1. 将设计方案中的 sheets/workflows/associations 结构化写入 execution_lock.json
2. 填写 gates 字段（Step 7 的门控结果）
3. 标注 axioms_covered（每个决策的公理编号）
4. 运行验证:
   python3 ${SKILL_DIR}/scripts/design_validator.py <项目名> --lock-file execution_lock.json
```

**合约文件是后续修改的唯一权威来源。** 任何增量修改（Mode B）必须先加载 execution_lock.json 再修改，修改后更新合约并重验。

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
- [x] 输出: 设计文档 + SOP + execution_lock.json
```
