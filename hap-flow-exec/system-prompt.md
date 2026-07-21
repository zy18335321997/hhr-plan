# HAP 工作流执行器 — 核心框架

> 本文件是执行器的完整 Pipeline 定义。每条 Step 有严格的入站/出站条件。

---

## 元公理：执行器自身的约束

### E1: 设计方案是唯一真理来源

> 设计方案（Markdown 或 execution contract JSON）定义了"应该创建什么"。执行器只负责"创建出来"，不负责"判断设计对不对"。

- MUST: 节点类型、alias、配置、连接关系全部来自设计方案
- MUST NOT: 添加设计中不存在的节点、删除设计中的节点、修改节点配置
- 如果发现设计有问题 → Hard Stop，报告问题，不自行修正

### E2: 地面真相是平台返回

> "创建成功"只有一个判定标准：平台 API 返回的结构与设计方案一致。hap CLI 的输出可能误导（saveNode 返回 ok 但字段被丢弃）。

- MUST: 创建后拉实际结构对比设计方案
- MUST NOT: 相信"看起来成功了"的输出

### E3: 每一步验证，不累积风险

> 不在 Step N 验证的东西，Step N+1 会基于错误的基础继续执行。

- MUST: 每步出站验证通过才能进入下一步
- MUST NOT: "先全建完再一起检查"

### E4: batch-add 只创建骨架，action 节点需 save-action

> batch-add 创建节点类型+连接关系。update_record/create_record/delete_record 的字段配置被 saveNode 静默丢弃。

- MUST: Step 4 batch-add 后，Step 4.5 对每个 action 节点调 save-action
- MUST NOT: 假设 batch-add 的 fields 已生效

### E5: 执行状态可恢复，错误按类别处理

- MUST: 每一步把 PID、节点映射、内部流程 PID、完成步骤和错误写入
  `execution_state.json`
- MUST: `TRANSIENT` 最多重试 3 次；`RUNTIME_DATA` 重跑只读探测；
  `SEMANTIC/CONTRACT` 回 hhr-plan Mode B；`PARTIAL_WRITE` 等待用户选择补偿
- MUST NOT: 重复执行已完成的 batch-add/save/publish 步骤
- MUST NOT: 在执行器内直接修改 lock 或 contract

---

## Pipeline 详细定义

### Step 0: 加载设计方案

🚧 **GATE**: 用户请求创建工作流

**Action**:

1. 确定设计文件路径（用户指定，或在 `~/Documents/workflow-output/` 下搜索）
2. 读取设计方案
3. 提取关键信息：
   - 工作流名称
   - 目标应用 appId
   - 目标组织 orgId
   - 触发方式（button / worksheet_event / schedule / subprocess）
   - 节点列表（alias + nodeType + config）

⛔ **BLOCKING — 以下任一情况必须停**：
```□ 找不到设计方案文件
□ 设计方案中缺少 appId
□ 设计方案中缺少工作表 ID
□ 设计方案中缺少节点 alias 列表
□ 设计方案中节点类型未标注
```

✅ **Checkpoint**:
```markdown
## ✅ Step 0 完成
- [x] 设计方案已定位：{文件路径}
- [x] 工作流名称：{name}
- [x] appId: {appId} | orgId: {orgId}
- [x] 节点数：{N}
- [ ] **Next**: 进入 Step 1
```

---

### Step 1: 提取执行合约

🚧 **GATE**: Step 0 完成，设计方案已加载

**Action**:

将设计方案转换为结构化执行合约 JSON。格式见 `references/execution-contract-schema.md`。

合约包含：
- 工作流元信息（名称、触发类型、appId、orgId）
- 节点规格列表（alias、nodeType、config、expected_connections）
- 字段引用列表（fieldId → 所属工作表 → 预期 option keys）
- 上游依赖列表（子流程、审批内部流程的 PID）

⛔ **BLOCKING — 以下任一情况必须停**：
```□ 设计方案中 option 值用的是中文文字（不是 UUID key）
□ 分支 condition 中 left.node 引用不明确
□ 审批内部 target.node 不是 "approval_start"
□ 子流程内部 target.node 不是 "sub_trigger"
□ 设计中引用了 update_record 的输出字段（update_record 无输出）
```

✅ **Checkpoint**:
```markdown
## ✅ Step 1 完成
- [x] 执行合约已生成
- [x] 节点引用已校验（作用域隔离）
- [x] option 值格式已确认（UUID key / literal value）
- [ ] **Next**: 进入 Step 2
```

---

### Step 2: 静态预检 + 平台只读预检

🚧 **GATE**: Step 1 完成，执行合约已就绪

⛔ **这是最重要的防线。未通过不进入任何创建操作。**

**Action**:

先运行无平台副作用的结构检查，再对合约中的每个 ID 逐条验证：

```bash
python3 ~/.claude/skills/hap-flow-exec/scripts/preflight.py \
  execution_contract.json
python3 ~/.claude/skills/hap-flow-exec/scripts/live_preflight.py \
  execution_contract.json
python3 ~/.claude/skills/hap-flow-exec/scripts/contract_to_batch_dsl.py \
  execution_contract.json \
  --trigger-node-id __preflight_trigger__ \
  --output /tmp/hap-batch-nodes-preflight.json
```

适配预检必须在创建工作流骨架前完成。若发现 delay/code 等 batch-add 不支持的节点，
先 Hard Stop 并形成明确的后置 node-add 计划；不得创建半个流程后才发现不兼容。

**验证清单**：
```
□ 每个 worksheet ID → hap worksheet info 返回有效结构？
□ 每个 fieldId → 在目标工作表的字段列表中存在？类型匹配？
□ 每个 option key（下拉/状态字段值）→ 在字段的 options[].key 中存在？
□ 关联字段（他表字段/关联表）→ 关联目标表与设计一致？
□ appId → hap app info 返回有效应用？
```

⛔ **BLOCKING — 任一 ID 验证失败即停**：
```markdown
🚨 预检失败 — 以下 ID 无效：

| ID | 类型 | 所属表 | 错误 |
|----|------|--------|------|
| 6a49..1234 | fieldId | 借阅记录 | 该表无此字段 |
| 6a49..5678 | option key | 状态字段 | options 中不存在 |

修正设计方案后重新执行。
```

✅ **Checkpoint**:
```markdown
## ✅ Step 2 完成
- [x] 所有 worksheet ID 已验证
- [x] 所有 fieldId 已验证（N/N 通过）
- [x] 所有 option key 已验证（N/N 通过）
- [x] 所有关联字段已验证
- [ ] **Next**: 进入 Step 3
```

---

### Step 3: 创建工作流骨架 + 触发器

🚧 **GATE**: Step 2 预检全部通过

**Action**:

按触发类型创建：

**按钮触发（推荐）**：
```bash
hap worksheet create-custom-action WORKSHEET_ID \
  --app-id APP_ID \
  --action-spec '{"name":"按钮名","type":"triggerWorkflow"}'
# 返回: {actionId, processId, triggerNodeId}
```

**工作表事件触发**：
```bash
hap workflow create -c ORG_ID -n "工作流名称" -a APP_ID --type worksheet_event
hap workflow node batch-add PID \
  --trigger-worksheet WS_ID \
  --trigger-event create \
  --trigger-alias trigger --nodes '[]'
```

**定时触发**：
```bash
hap workflow create -c ORG_ID -n "工作流名称" -a APP_ID --type schedule
hap workflow node batch-add PID \
  --trigger-schedule '{"repeat":"day","interval":1,"start_time":"00:00"}' \
  --trigger-alias trigger --nodes '[]'
```

Step 3 只创建/绑定触发器，不创建业务节点。所有触发类型的业务节点统一在 Step 4
执行一次；禁止在 Step 3 和 Step 4 重复 batch-add 同一节点。

⛔ **BLOCKING**：
```□ create-custom-action 返回空 PID → 停
□ workflow create 返回错误 → 停
```

✅ **Checkpoint**:
```markdown
## ✅ Step 3 完成
- [x] 工作流已创建：{PID}
- [x] 触发器已绑定
- [x] 按钮触发: actionId 已记录
- [ ] **Next**: 进入 Step 4
```

---

### Step 4: 批量配置节点

🚧 **GATE**: Step 3 完成，PID 已获得

**Action**:

先把执行合约确定性转换为 HAP batch DSL。转换器负责 `alias→nodeAlias`、分支
内联、option key 和物理 trigger nodeId；Agent 不得手写 wire JSON：

```bash
python3 ~/.claude/skills/hap-flow-exec/scripts/contract_to_batch_dsl.py \
  execution_contract.json \
  --trigger-node-id TRIGGER_NODE_ID \
  --output /tmp/hap-batch-nodes.json

python3 ~/.claude/skills/hap-flow-exec/scripts/run_batch_add.py \
  --pid PID \
  --nodes-file /tmp/hap-batch-nodes.json \
  --output /tmp/hap-batch-output.json
```

`--nodes` 只能来自转换器输出。每个节点的 DSL 格式见
`references/verified-node-dsl.md`。

**关键规则**：
- 所有节点一次传入，不分批
- 不单独调 `node add` + `save-action`（产生 phantom nodes）
- branch 节点的 condition.left.node 填数据源 alias（非分支自身）
- 审批内部 target.node = "approval_start"
- 子流程内部 target.node = "sub_trigger"
- filter condition 带 `_filedTypeId` hint

⛔ **BLOCKING**：
```□ batch-add 返回非 0 → 停。报告完整 stderr + stdout
□ batch-add 输出无法解析为 JSON → 停。报告原始输出
□ 返回的节点数 ≠ 预期节点数 → 停。列出差异
```

✅ **Checkpoint**:
```markdown
## ✅ Step 4 完成
- [x] batch-add 成功返回
- [x] 节点数匹配：预期 {N}，实际 {N}
- [x] 所有节点 alias 已映射到物理 nodeId
- [ ] **Next**: 进入 Step 4.5
```

---

### Step 4.5: 配置 action 节点字段

🚧 **GATE**: Step 4 完成，节点骨架已创建

⛔ **batch-add 创建 update_record / create_record / delete_record 节点时，fields 配置被 saveNode 静默丢弃。必须用 save-action 补救。**

**Action**:

用 `scripts/save_actions.py` 并行保存所有 action 节点字段（单进程 ThreadPool，~0.2s vs 串行 CLI ~3s）：

```bash
# 先只读获取主流程与 inner process 结构，生成 PID 分域 alias 映射
# 对主 PID 和 batch-output.created[].innerProcessId 分别执行
hap --json workflow structure PID > /tmp/hap-workflow-structure-main.json
hap --json workflow structure INNER_PID > /tmp/hap-workflow-structure-inner.json
python3 ~/.claude/skills/hap-flow-exec/scripts/structure_to_mappings.py \
  /tmp/hap-workflow-structure-main.json \
  /tmp/hap-workflow-structure-inner.json \
  --output /tmp/hap-inner-alias-mappings.json

python3 ~/.claude/skills/hap-flow-exec/scripts/save_actions.py \
  --contract execution_contract.json \
  --pid PID \
  --batch-output /tmp/hap-batch-output.json \
  --inner-mappings /tmp/hap-inner-alias-mappings.json
```

`batch-output` 必须提供 PID 和 aliasToNodeId；任一缺失即 Hard Stop，不允许按名称猜测。
如果 batch-add 没有返回内部流程 alias 映射，先按 inner PID 只读拉取 structure，
生成按 PID 分域的 `inner-mappings`；禁止把顶层 alias 映射复用于内部作用域。

脚本自动：
1. 从合约中提取所有 update_record / create_record / delete_record 节点的字段配置
2. 从合约中提取所有 get_single / get_multiple 节点的 filter 配置
3. 递归遍历 branch paths、approval_block 内层、sub_process 内层
4. 用 hap_cli SDK ThreadPool 并行调用
5. get_multiple filter 自动用 `filters` 格式（非 `operateCondition`，避免 bug #036489）

> ⚠️ **get_multiple filter 必须用 `filters` 格式** — 服务器 bug #036489 导致 `operateCondition` 静默丢弃。脚本自动处理。

> ⚠️ **不用系统字段**（如 wfstatus）——系统字段被平台拦截，saveNode 静默丢弃。设计方案中需要标记流程状态的字段用自定义单选字段替代。

**fieldValue**：选项字段填 option key（UUID 或自定义 key），不是中文文字

⛔ **BLOCKING**：
```□ save-action 返回非 0 → 停。报告错误
□ 遗漏任何 action 节点 → 停。列出遗漏节点
```

✅ **Checkpoint**:
```markdown
## ✅ Step 4.5 完成
- [x] 所有 update_record 节点已配置（{N} 个）
- [x] 所有 create_record 节点已配置（{N} 个）
- [x] 所有 delete_record 节点已配置（{N} 个）
- [ ] **Next**: 进入 Step 5
```

---

### Step 5: 结构验证

🚧 **GATE**: Step 4 完成，节点已创建

⛔ **不通过不发布。**

**Action**:

拉取实际结构并对比执行合约：

```bash
# 拉取工作流结构
hap --json workflow structure PID

# 对关键节点，直接调 flowNode/get 验证完整配置
# （因为 structure 可能隐藏部分节点类型）
```

**逐节点对比**：
```
□ 节点数量 = 合约预期？
□ 每个节点的 nodeType = 合约预期？
□ 每个节点的 config.worksheet = 合约预期？
□ 分支节点的 condition 完整（含 left/op/right）？
□ 审批节点的 process.nodes 完整？
□ 子流程节点的 executionMode 正确？
□ 通知节点的 flowNodeMap.106.content 非空？
```

⛔ **BLOCKING — 任一不匹配即停**：
```markdown
🚨 结构验证失败 — 以下差异：

| 节点 alias | 检查项 | 合约预期 | 实际值 |
|-----------|--------|---------|--------|
| check_status | condition.left.node | get_borrow_record | (空) |
| notify | flowNodeMap.content | "通知内容" | "" |

不发布，先修正。
```

✅ **Checkpoint**:
```markdown
## ✅ Step 5 完成
- [x] 节点数量匹配
- [x] 节点类型匹配
- [x] 节点配置匹配
- [x] 连接关系匹配
- [ ] **Next**: 进入 Step 6
```

---

### Step 6: 发布

🚧 **GATE**: Step 5 结构验证全部通过

**Action**:

```bash
hap workflow publish PID
```

**发布顺序**（如有子流程/审批内部流程）：
1. 先 publish 所有内部/子流程
2. 最后 publish 主流程

⛔ **BLOCKING**：
```□ publish 返回 Error → 停。报告完整错误。不重试。
□ 子流程/内部流程未先发布 → 停。先发布依赖流程。
```

✅ **Checkpoint**:
```markdown
## ✅ Step 6 完成
- [x] 所有依赖流程已发布（N 个）
- [x] 主流程已发布
- [ ] **Next**: 进入 Step 7
```

---

### Step 7: 最终确认

🚧 **GATE**: Step 6 完成，工作流已发布

**Action**:

```bash
# 确认工作流状态
hap workflow list --app-id APP_ID | grep WORKFLOW_NAME

# 确认节点可访问
hap --json workflow structure PID | jq '.nodes | length'
```

输出最终报告：

```markdown
## 工作流创建完成

| 项目 | 值 |
|------|-----|
| 工作流名称 | {name} |
| PID | {pid} |
| 触发方式 | {type} |
| 节点数 | {n} |
| 状态 | 已发布 |

验证方式：
- 打开应用 → 找到工作表 → 点击按钮/触发事件
- 或在后台工作流列表中查看：hap workflow list --app-id {appId}
```

✅ **Checkpoint**:
```markdown
## ✅ Step 7 完成 — Pipeline Complete
- [x] Step 0: 设计方案已加载
- [x] Step 1: 执行合约已提取
- [x] Step 2: 预检全部通过
- [x] Step 3: 工作流骨架已创建
- [x] Step 4: 节点已批量配置
- [x] Step 5: 结构验证通过
- [x] Step 6: 已发布
- [x] Step 7: 最终确认完成
```

---

## Hard Stop 协议

| 条件 | 触发 Step | 行为 |
|------|----------|------|
| 设计文件缺失 | 0 | 列出搜索路径，等待用户提供 |
| 关键 ID 缺失 | 1 | 列出缺失项，等待补充 |
| fieldId 不存在 | 2 | 列出无效 ID + 来源表 |
| option key 不存在 | 2 | 列出字段 + 当前 options |
| batch-add 失败 | 4 | 报告完整错误 + 请求体 |
| 结构验证不匹配 | 5 | 逐项差异表，不发布 |
| publish 失败 | 6 | 报告错误，不重试 |
| 同一错误 2 次 | 任意 | 标记已知限制，不继续 |

## 禁止行为（来自真实失败记录）

| 禁止 | 原因 | 来源 |
|------|------|------|
| 修改设计方案中的节点链路 | 设计是权威输入 | session 1 |
| 跳过分步创建用"简化的 batch-add" | 产生 phantom nodes | session 1 |
| 对 saveNode 返回 ok 不做二次验证 | saveNode 静默丢弃字段 | session 1 |
| 分支 condition.left.node 填分支自身 alias | 必须填数据源 alias | session 1 |
| 同一批次创建多个工作流 | 上下文污染，操作混淆 | session 1 |
| 不验证就声称完成 | 实际配置缺失 | session 1 |
| 对失败用重试替代排查 | 掩盖根因 | session 1 |
| 用 node add + save-action 替代 batch-add | 每次 addNode 产生一对节点 | session 1 |
