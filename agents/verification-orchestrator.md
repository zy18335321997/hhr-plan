# Verification Orchestrator — Cursor Subagent 校验协议

> 本协议由 Cursor 主 Agent 执行。Agent 1/2/3 是 LLM Subagent，必须通过 Cursor
> `Subagent` 工具调用。`agent_prepare.py`、`validate-agent-output.py` 和
> `verification_merge.py` 都是确定性脚本，**不能发起、模拟或替代 LLM 调用**。

## 固定输出契约

三个 Agent 必须使用同一个 envelope：

`schema_version / agent_id / input_digest / verdict / failure_code / summary / issues / fix_guide / uncertain_items / payload`

- Schema：`references/schemas/agent-verification-output.schema.json`
- 失败码：`references/schemas/verification-failure-codes.md`
- Agent 1：`agent_id=agent_1_logic`
- Agent 2：`agent_id=agent_2_platform`
- Agent 3：`agent_id=agent_3_audit`

## Mode A/B：Agent 1 + Agent 2

### Step 1：主 Agent 准备只读上下文

```bash
python3 "${SKILL_DIR}/scripts/agent_prepare.py" \
  "<project_path>/execution_lock.json" \
  --validator-result "/tmp/hhr_design_validation.json" \
  --output "/tmp/hhr_agent_brief.json"
```

脚本只压缩输入，不调用 LLM，也不修改 `execution_lock.json`。它会对排除派生
`verification` 与 Agent gates 后的规范化 lock 计算 SHA-256，并写入 brief 顶层
`input_digest`。它还会拒绝失败或摘要不匹配的 `design_validator` 结果，并将通过的
确定性结果放入 `deterministic_evidence.design_validator`。Agent 1/2 必须原样复制
摘要；Agent 1 必须复用这份确定性证据，不重复伪造字段与依赖检查。

### Step 2：主 Agent 并行调用 Subagent 工具

主 Agent 必须在**同一条工具消息**中发出以下两个 `Subagent` 调用。不要串行等待；
不要把整项任务委托给一个 Subagent。

Agent 1 调用：

```text
Subagent(
  subagent_type="generalPurpose",
  description="执行设计逻辑校验",
  run_in_background=false,
  prompt="""
你是 hhr-plan Agent 1，独立执行设计逻辑校验，不继承主会话结论。

完整指令：<SKILL_DIR>/agents/logic-verify.md
输入：
- <absolute_path>/hhr_agent_brief.json
- <project_path>/project_context.json
- <project_path>/aliases.json
- 如涉及工作流修改：对应 node_configs.json

复用 brief 中 deterministic_evidence.design_validator 的字段/依赖检查结果，
只对确定性脚本未覆盖的语义项做 LLM 判断。逐项完成全部检查。最终只返回一个符合
<SKILL_DIR>/references/schemas/agent-verification-output.schema.json
的 JSON 对象；固定 agent_id=agent_1_logic。不要返回代码围栏或解释。
"""
)
```

Agent 2 调用：

```text
Subagent(
  subagent_type="generalPurpose",
  description="执行平台能力校验",
  run_in_background=false,
  prompt="""
你是 hhr-plan Agent 2，独立执行明道云平台能力校验，不继承主会话结论。

完整指令：<SKILL_DIR>/agents/platform-verify.md
输入：
- <absolute_path>/hhr_agent_brief.json
- <WORKFLOW_NODES_GUIDE_PATH>
- <SKILL_DIR>/references/platform/node-capabilities.md
- <project_path>/business-flow-manifest.json

逐节点完成全部检查，再完成全部拓扑检查。最终只返回一个符合
<SKILL_DIR>/references/schemas/agent-verification-output.schema.json
的 JSON 对象；固定 agent_id=agent_2_platform。不要返回代码围栏或解释。
"""
)
```

`<...>` 占位符必须在调用前替换为真实绝对路径。Subagent 不会自动获得用户消息、
主 Agent 的前文或未写入文件的设计内容，因此 prompt 必须列全输入。

### Step 3：主 Agent 保存并验证返回值

主 Agent 将两个 Subagent 返回的原始 JSON 分别保存为：

- `/tmp/hhr_agent1_output.json`
- `/tmp/hhr_agent2_output.json`

然后运行：

```bash
python3 "${SKILL_DIR}/scripts/validate-agent-output.py" \
  --agent1 "/tmp/hhr_agent1_output.json" \
  --agent2 "/tmp/hhr_agent2_output.json"
```

验证结果分成两条互不混淆的通道：

| 字段 | 含义 | 行为 |
|---|---|---|
| `format_verdict=fail` | JSON、envelope、payload 或内部一致性不完整 | 重新调用对应 Subagent；不得写 gates |
| `format_verdict=pass, semantic_verdict=fail` | 输出完整，但 Agent 判断设计不通过 | 不重跑格式；按 issues 修复设计 |
| 两者均为 `pass` | 输出完整且设计通过 | 进入合并 |

`validate-agent-output.py` 返回 0 仅表示格式完整；不能把返回 0 解释成设计通过。

### Step 4：完整性通过后合并 gates

```bash
python3 "${SKILL_DIR}/scripts/verification_merge.py" \
  --target "<project_path>/execution_lock.json" \
  --agent1 "/tmp/hhr_agent1_output.json" \
  --agent2 "/tmp/hhr_agent2_output.json" \
  --mode design
```

合并器会再次校验完整性，避免绕过 Step 3：

- 任何格式/完整性失败：退出码 2，不修改目标文件。
- 输出完整但至少一个 Agent 语义失败：写入失败 Agent gates 和顶层
  `verification.fix_plan`，退出码 1。
- 输出完整且全部语义通过：写入通过 gates，退出码 0。
- 写入采用同目录临时文件 + 原子替换，不产生半写入 gates。
- Agent 输出的 `input_digest` 与当前 lock 不一致：退出码 2，不写文件，必须重跑 Agent。

语义失败时，主 Agent 按合并后的 `verification.fix_plan` 先 easy、再 medium、最后 hard
修正设计，然后重新执行 Agent 1/2。不得通过手工把 gate 改成 pass 绕过复检。

## Mode D：Agent 3

### Step 1：主 Agent 调用 Subagent 工具

```text
Subagent(
  subagent_type="generalPurpose",
  description="检查审计扫描完整性",
  run_in_background=false,
  prompt="""
你是 hhr-plan Agent 3，只检查 Mode D 扫描完整性，不判断审计结论是否正确。

完整指令：<SKILL_DIR>/agents/audit-scanner.md
输入：
- <absolute_path>/audit-report.md
- input_digest=<审计报告原始字节的 64 位 SHA-256>
- <project_path>/project_context.json
- <SKILL_DIR>/system-prompt.md

完成全部五项检查。最终只返回一个符合
<SKILL_DIR>/references/schemas/agent-verification-output.schema.json
的 JSON 对象；固定 agent_id=agent_3_audit。
漏检维度必须写在 payload.missed_dimensions。不要返回代码围栏或解释。
"""
)
```

主 Agent 将返回 JSON 保存为 `/tmp/hhr_agent3_output.json`。

### Step 2：验证并合并

```bash
python3 "${SKILL_DIR}/scripts/validate-agent-output.py" \
  --agent3 "/tmp/hhr_agent3_output.json"

python3 "${SKILL_DIR}/scripts/verification_merge.py" \
  --target "<absolute_path>/mode-d-verification-state.json" \
  --source "<absolute_path>/audit-report.md" \
  --agent3 "/tmp/hhr_agent3_output.json" \
  --mode audit
```

Mode D 的 target 必须是顶级 JSON 对象；没有 `gates` 时合并器会创建。Agent 3
必须复制主 Agent 提供的审计报告 SHA-256；合并器按 `--source` 原始字节复核。
`payload.missed_dimensions`、`uncovered_constraints`、`false_negatives` 任一非空，
都属于结构完整的语义失败：合并器写入失败 gate，主 Agent 补扫后再调用 Agent 3。

## 全量三 Agent 合并

如果某次 Mode D 既要求 Agent 1/2 检查设计质量，又要求 Agent 3 检查扫描完整性，
主 Agent先并行取得三个输出，再执行：

```bash
python3 "${SKILL_DIR}/scripts/verification_merge.py" \
  --target "<absolute_path>/verification-state.json" \
  --source "<absolute_path>/audit-report.md" \
  --agent1 "/tmp/hhr_agent1_output.json" \
  --agent2 "/tmp/hhr_agent2_output.json" \
  --agent3 "/tmp/hhr_agent3_output.json" \
  --mode all
```

只有三个输出全部通过完整性校验时才写 gates。

## 修正上限

- 格式失败：只重跑格式不完整的 Agent，不计入设计修正次数。
- 语义失败：修正设计/补扫后复检，同一问题最多修正 3 次。
- 第 3 次仍语义失败：保留失败 gates，输出 LOW 置信度及全部争议点，由用户决定；
  不得把失败 gate 改写为 pass。
