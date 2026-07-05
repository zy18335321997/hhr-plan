# Mode B: 棕地设计

> 在已有明道云应用上进行修改、扩展或优化。输入是需求+项目上下文，输出是增量变更方案。

## Pipeline Overview

```
Step 0 ──→ Step 1 ──→ Step 2 ──→ Step 3 ──→ Output
 上下文确认    影响面分析   增量构建    门控      方案文档
⛔Tier1+Tier2    ⛔>10流Stop
```

| Step | 名称 | 类型 | 产出物 |
|------|------|------|--------|
| 0 | 上下文确认 | ⛔ BLOCKING | 涉事表清单 + 命名规范 + 数据链路 |
| 1 | 影响面分析 | AUTO（>10 流时 ⛔ Hard Stop） | 影响面报告 |
| 2 | 增量构建 | AUTO | 表和字段变更 + 工作流修改方案 |
| 3 | 门控 | AUTO（不通过则拦截修正） | Gate 1-6 自检结果 |
| 最终 | 输出 | AUTO（门控通过后） | 增量变更方案 + 影响面报告 |

> **执行纪律**：非 BLOCKING 步自动连续推进，不等待用户。⛔ 标记的步骤必须停等确认后才进入下一步。

---

## 触发条件

用户说"在XX里加""修改XX""扩展XX""优化XX"，且项目存在于 `~/Documents/workflow-output/projects_registry.json` 中。

## 前置加载（全部在推理前加载）

- `system-prompt.md` — 全部公理+定理
- `references/tool-dispatch.md` — **🚨 强制**：工具调度卡（禁止用 grep/curl 替代）
- `references/business-flow-manifest.json` — **必须先加载**，了解所有已有工作流的读/写关系
- `references/project_context.json` — 表/字段/关联快照 + Hub表 + 命名规范
- `references/aliases.json` — 客户用语→系统名称
- `references/platform/node-capabilities.md` — 平台能力边界

---

## Step 0: 上下文确认 ⛔ BLOCKING

🚧 **GATE**：前置文件已加载。用户描述了变更需求。**这是设计中唯一的用户确认门。**

> 对标 ppt-master Eight Confirmations：Tier 1 确认锚点 → 从锚点重新派生 Tier 2。
> 两层确认在同一个 chat 回复中完成，Tier 1 确认后 AI 立即重新推导并呈现 Tier 2。

**必须先回答以下问题，并展示给用户确认。跳过此步骤直接给方案 = 违反定理6（收拢协议）。**

---

### Tier 1 — 锚点确认（先确认，再往下）

**a. 涉事表确认**

```
1. 需求涉及哪些表？→ 查 project_context.worksheets
2. 这些表是否已存在？→ 查 manifest，列出每张表的已有工作流
3. 如果不存在 → 查 aliases.json 确认客户术语 ↔ 系统名称的映射
```

**必须输出**: 涉事表清单 + 每张表的已有工作流数量 + 映射结果

**b. 项目命名规范**

```
1. 查 project_context.naming：
   - auto_number_prefixes: 项目用什么前缀？
   - worksheet_naming: 括号标注格式？
   - workflow_verb_prefixes: 工作流用什么动词开头？
   - common_field_names: 字段名约定？
   - param_name_sample: 流程参数命名风格？
```

**必须输出**: 项目的命名规范摘要（前缀、动词前缀、字段约定）

**c. 修改范围**

```
1. 操作类型：新增表 / 修改已有表 / 扩展工作流 / 替换工作流？
2. 是已有工作流的自然延伸还是全新流程？
3. 是否需要引入新的审批链、新的触发方式？
```

**必须输出**: 修改范围一句话 + 新建 vs 修改决策倾向

⛔ **停等用户确认或修改 Tier 1 的 a/b/c。** 用户回复后，从用户实际确认的锚点重新推导 Tier 2。

---

### Tier 2 — 派生确认（从 Tier 1 重新推导后呈现）

> ⚠️ Tier 2 的验证结果必须从用户实际确认的 Tier 1 重新推导，不得沿用预设值。

**d. 数据链路验证**

```
1. 查 manifest：
   - 涉事表被哪些工作流读写？
   - 新需求的数据流转是否与已有链路冲突？
2. 查 hub_tables：
   - 新流程应挂哪个 Hub？
3. 查 relation_graph：
   - 新关联是否会产生 DAG 环路？（定理3）
```

**必须输出**: 涉事表的上下游链路 + Hub 归属 + 环路检查结果

**e. 影响面评估（预览）**

基于 Tier 1 的修改范围，预跑脚本：

```bash
python3 ~/.claude/skills/hhr-plan/scripts/rebuild_graph.py <项目名> --lifecycle <表名>
python3 ~/.claude/skills/hhr-plan/scripts/search.py "<表名>" --writes-to -p <项目名>
python3 ~/.claude/skills/hhr-plan/scripts/search.py "<表名>" --reads-from -p <项目名>
```

**必须输出**: 预估受影响工作流数 + 严重度预判（≤3 / 4-10 / >10）

**f. 需修改的工作流节点链路**

如果 Tier 1 确认涉及修改已有工作流，**加载该工作流的完整 node_configs.json**：

```
~/Documents/workflow-output/<项目名>/默认模块/<工作流名>/node_configs.json
```

**必须输出**:
- 现有节点序列（T0→T1→T2→...）
- 修改位置（Tn 之后插入/替换）
- 确认 Tn 之后插入的节点不会读取 T{n+1} 之后才写入的字段（定理1：时序校验）

⛔ **再次停等用户确认或修改 Tier 2。** 用户回复后，自动进入 Step 1 影响面分析。

### ✅ Checkpoint

```markdown
## ✅ Step 0 完成
- [x] Tier 1 锚点已确认（涉事表 + 命名规范 + 修改范围）
- [x] Tier 2 派生已确认（数据链路 + 影响面预览 + 节点链路）
- [x] 用户确认后的值已写入后续步骤
- [ ] **Next**: 自动进入 Step 1
```

---

## Step 1: 影响面分析

🚧 **GATE**：Step 0 完成，用户已确认上下文。

### 1.0 先加载依赖图

**输出任何方案前，必须先跑：**

```bash
# 实体生命周期 → 谁创建/更新/读取这张表
python3 ~/.claude/skills/hhr-plan/scripts/rebuild_graph.py 几建 --lifecycle 表名

# 反向查 → 谁写这张表，谁读这张表
python3 ~/.claude/skills/hhr-plan/scripts/search.py "表名" --writes-to -p 几建
python3 ~/.claude/skills/hhr-plan/scripts/search.py "表名" --reads-from -p 几建
```

不跑这步 = 不知道影响面 = 方案不可靠。

### 1.1 依赖分类

查 manifest，按依赖类型分类列出所有受影响的工作流：

| 依赖类型 | 说明 | 检查方法 |
|---------|------|---------|
| 直接触发依赖 | 同一表上的其他工作流可能被同一操作间接激活 | manifest: 查同表所有触发类型 |
| 数据读取依赖 | 其他工作流查询/获取本次修改涉及的表 | manifest: 其他 wf 的读列表 ∩ 本次涉事表 |
| 数据写入依赖 | 本次修改涉及的表被其他工作流写入 | manifest: 其他 wf 的写列表 ∩ 本次涉事表 |
| 子流程调用依赖 | 被修改的工作流被其他工作流作为子流程调用 | node_configs: 查子流程节点的目标工作流名 |
| 审批链依赖 | 被修改工作流的审批结果触发其他工作流 | manifest: 查审批事件触发的工作流 |

### 1.2 影响面评估

```
影响面 = 直接依赖数 + 间接依赖数(一跳)
```

| 影响面 | 处理方式 |
|--------|---------|
| ≤3 个工作流 | 直接修改，标注每个受影响工作流的依赖类型 |
| 4-10 个工作流 | 输出依赖关系图，列出每条依赖的类型和风险，确认后修改 |
| >10 个工作流 | ⛔ Hard Stop：输出完整依赖关系图 + 影响面报告，等待用户决策 |

### ⛔ Hard Stop — 影响面 >10 个工作流

输出完整依赖关系图 + 影响面报告 → 等待用户决策。用户确认后再进入 Step 2。

### ✅ Checkpoint

```markdown
## ✅ Step 1 完成
- [x] 依赖图已加载（lifecycle + writes-to + reads-from）
- [x] 依赖分类完成（5 种依赖类型）
- [x] 影响面已评估（受影响工作流数量）
- [x] 如 >10 流，Hard Stop 已触发
- [ ] **Next**: 自动进入 Step 2
```

---

## Step 2: 增量构建

🚧 **GATE**：Step 1 完成，影响面已分析。

### 表和字段修改（已有规则）

按增量构建框架的阶段 3-N：
1. 查已有表能复用吗
2. 新表单向引用 Hub
3. 新字段优先加源头表
4. 旧流不受影响

### 工作流修改

#### 2.5 新建 vs 修改决策

| 信号 | 决策 |
|------|------|
| 需求是已有工作流的自然延伸（加一个通知、加一个字段更新） | 修改已有工作流 |
| 需求引入新的触发条件或新的审批链 | 新建工作流 |
| 修改后节点数会超过 10 | 拆分：保留原工作流 + 新建子流程 |
| 需求逻辑与已有工作流共享 ≥50% 节点 | 修改已有工作流，用分支区分 |
| 需求逻辑与已有工作流几乎不重叠 | 新建工作流 |

新建工作流时，加载 `references/workflow-design-derivation.md`，按六步推导法执行。

#### 2.6 工作流修改操作类型与风险

| 操作类型 | 风险等级 | 前置检查 |
|---------|---------|---------|
| 节点插入 | 低 | 时序校验（定理1）：新节点只能读已有字段 |
| 节点删除 | 高 | 检查被删节点的输出是否被下游节点引用 |
| 触发方式变更 | 高 | 检查所有调用方（父流程、按钮配置、事件监听） |
| 审批链修改 | 中 | 检查审批结果触发的下游工作流（审批链依赖） |
| 工作流拆分 | 高 | 拆分点的数据传递：主→子参数传递 + 子→主结果回写 |
| 工作流合并 | 中 | 合并后节点数 ≤10，否则反向拆分 |
| 子流程替换 | 中 | 检查输入参数兼容性 + 输出数据格式一致性 |

#### 2.7 安全修改检查清单

**修改前**:
- □ 加载目标工作流 node_configs.json（Step 0.4 已完成）
- □ 输出完整时序标注 T0→T1→...→Tn
- □ 标注修改位置（Tn 之后插入/替换/删除）
- □ 依赖分析：列出读取本工作流输出的其他工作流（Step 1 已完成）

**修改中**:
- □ 新节点时序校验：Tn 只能读 T0..T{n-1} 已写入的字段（定理1）
- □ 数据链路完整性：删除节点不得切断下游数据源
- □ 容错配置：查询空→继续执行、子流程→逐条+中止继续（公理5）
- □ 命名一致：新节点/参数遵循项目命名规范（Step 0.2）

**修改后**:
- □ 受影响工作流逐一检查（Step 1 的依赖列表）
- □ 输出修改前/后对照的完整节点链
- □ 更新涉事表的 SOP

### ✅ Checkpoint

```markdown
## ✅ Step 2 完成
- [x] 表/字段变更方案已确定（复用优先、单向引用）
- [x] 新建 vs 修改决策已按决策表执行
- [x] 工作流修改操作已完成安全检查清单
- [x] 修改前/后节点链路对照已输出
- [ ] **Next**: 自动进入 Step 3
```

---

## Step 3: 门控 — Agent 并行校验 + Gate 自检

🚧 **GATE**：Step 2 完成，增量方案已完整，`execution_lock.json` 已更新。

### 3.1 脚本预检（自动）

先跑自动验证，替代 Gate 4 + Gate 1 的人工 □：

```bash
python3 ${SKILL_DIR}/scripts/design_validator.py <项目名> --lock-file execution_lock.json
python3 ${SKILL_DIR}/scripts/design_validator.py <项目名> --check-graph
```

不通过 → 修正 → 重跑。通过 → 继续。

### 3.2 Agent 并行校验

加载编排协议：
```
Read agents/verification-orchestrator.md
```

准备上下文包：
```bash
python3 ${SKILL_DIR}/scripts/agent_prepare.py execution_lock.json --output /tmp/hhr_agent_brief.json
```

**并行启动 Agent 1 + Agent 2（同 Mode A Step 7）**，收集 JSON 裁决。

### 3.3 Gate 2/3/5/6 人工补充自检

Agent 校验覆盖了大部分 Gate，以下需人工确认：

```
□ Gate 2 逻辑:   Agent 1 逻辑校验 pass？时序标注 T0..Tn 完整？
□ Gate 3 时序:   新节点读取的字段在插入位置确实已存在？
□ Gate 5 平台:   Agent 2 平台校验 pass？
□ Gate 6 推理:   方案无过度设计？隐藏假设已标注置信度？
```

### ⛔ BLOCKING — 任一 Gate 或 Agent 不通过则拦截修正

全部通过 → 将 Agent 结果写入 execution_lock.json → 进入最终输出。

### ✅ Checkpoint

```markdown
## ✅ Step 3 完成
- [x] design_validator.py: pass
- [x] Agent 1 (逻辑校验): pass
- [x] Agent 2 (平台校验): pass
- [x] Gate 2/3/5/6 人工确认: pass
- [x] 门控结果已写入 execution_lock.json
- [ ] **Next**: 自动进入最终输出
```

---

## 最终输出

🚧 **GATE**：Step 3 通过，Gate 1-6 全部 pass。

### 输出要求

- **模式**: Mode B
- **上下文确认结果**: Step 0 的四项输出
- **影响面报告**: Step 1 的完整依赖分析（含依赖图查询结果）
- **公理覆盖**: 每个决策追溯到公理编号
- **门控结果**: Gate 1-6 全部通过（标注在输出末尾）

如果修改涉及已有工作流的表，**更新该表的 SOP**。

### execution_lock.json（强制，与方案文档同时产出/更新）

**新建项目**: 同 Mode A，设计文档定稿后同步生成。
**修改已有项目**: 先加载已有的 `execution_lock.json`，修改后更新并重验：

```
1. 加载已有 execution_lock.json（如项目未生成过，从 project_context.json 生成骨架:
   python3 ${SKILL_DIR}/scripts/lock_manager.py init <项目名> --mode B --output execution_lock.json）
2. 将本次新增/修改的 sheets/workflows/associations 合并到 lock 文件
3. 更新 gates 字段（Step 3 的门控结果）
4. 运行验证:
   python3 ${SKILL_DIR}/scripts/lock_manager.py validate <项目名> execution_lock.json
```

**合约文件是后续修改的唯一权威来源。** 下次修改本方案时，必须先加载 execution_lock.json 恢复设计状态。

### 禁止事项

- ❌ 没查 manifest 就建议"可以建一个XX表"——可能已存在
- ❌ 没查命名规范就建议表名/字段名——会跟项目不统一
- ❌ 没查节点链路就在工作流中间插入节点——可能违反时序
- ❌ 没查 Hub 表归属就让新表反向引用——可能产生环路

### ✅ Pipeline Complete

```markdown
## ✅ Mode B 棕地设计完成
- [x] Step 0: 上下文确认（Tier 1 锚点 + Tier 2 派生，用户已确认）
- [x] Step 1: 影响面分析（依赖分类 + 影响面评估）
- [x] Step 2: 增量构建（表/字段 + 工作流修改 + 安全检查清单）
- [x] Step 3: 门控（Gate 1-6 全部通过）
- [x] execution_lock.json 已更新并验证通过
- [x] 输出: 增量变更方案 + 影响面报告 + 更新 SOP + execution_lock.json
```
