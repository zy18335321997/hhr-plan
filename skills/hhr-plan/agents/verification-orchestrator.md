# Verification Orchestrator — Agent 并行校验编排协议

> 主 Agent 在 Mode A Step 7 / Mode B Step 3 / Mode D 门控时加载本协议。
> 定义了如何并行调用校验 Agent、如何合并结果、如何裁决。

## 前置条件

以下文件必须已存在：
- `execution_lock.json` — 设计方案结构化合约
- `design_spec.md` — 设计文档（供 Agent 1 读取叙事上下文）

## 并行调用协议

### Step 1: 准备 Agent 上下文包

压缩 execution_lock.json 为 Agent 可读的简洁格式：

```bash
python3 ${SKILL_DIR}/scripts/agent_prepare.py <project_path>/execution_lock.json \
  --output /tmp/hhr_agent_brief.json
```

此命令输出一个精简的 JSON，只包含 Agent 校验所需的字段（sheet 名/字段名/工作流节点链/关联方向），去掉冗余的结构信息。

### Step 2: 并行启动两个 Agent

同时调用两个 Agent，每个都读取同一个简化上下文包：

**Agent 1 — 逻辑校验**：
```
Agent(
  subagent_type="general-purpose",
  description="Logic verification agent",
  prompt="
  加载 ${SKILL_DIR:-~/.claude/skills/hhr-plan}/agents/logic-verify.md 作为你的完整指令。

  输入文件:
  - 设计方案摘要: /tmp/hhr_agent_brief.json
  - 项目上下文: ~/Documents/workflow-output/{项目名}/project_context.json

  读取这些文件后，严格按照 logic-verify.md 中的校验清单逐条执行。
  输出必须是 JSON 格式（见 logic-verify.md §输出格式）。
  不参考主会话的任何讨论内容。
  "
)
```

**Agent 2 — 平台校验**（与 Agent 1 同时启动）：
```
Agent(
  subagent_type="general-purpose",
  description="Platform verification agent",
  prompt="
  加载 ${SKILL_DIR:-~/.claude/skills/hhr-plan}/agents/platform-verify.md 作为你的完整指令。

  输入文件:
  - 设计方案摘要: /tmp/hhr_agent_brief.json
  - 明道云节点完整指南: ${WORKFLOW_NODES_GUIDE_PATH:-~/.claude/skills/workflow-analyzer/references/pd-openweb-schemas/workflow-nodes-complete-guide.md}
  - 平台能力边界: ${SKILL_DIR:-~/.claude/skills/hhr-plan}/references/platform/node-capabilities.md

  读取这些文件后，严格按照 platform-verify.md 中的校验清单逐条检查。
  输出必须是 JSON 格式（见 platform-verify.md §输出格式）。
  不参考主会话的任何讨论内容。
  "
)
```

### Step 3: 收集结果 + 合并裁决

两个 Agent 完成后，收集各自的 JSON 输出。

**合并规则**：

| Agent 1 | Agent 2 | 最终裁决 | 行为 |
|---------|---------|---------|------|
| pass | pass | 通过 | 自动进入最终输出 |
| fail | pass | 不通过 | 生成修复计划（仅 Agent 1 的问题） |
| pass | fail | 不通过 | 生成修复计划（仅 Agent 2 的问题） |
| fail | fail | 不通过 | 生成合并修复计划（两个 Agent 的问题） |

**修复回退映射**（按问题类型定位到设计步骤）：

| 失败类型 | Agent | 回到步骤 |
|---------|-------|---------|
| 公理违规 (axiom_compliance fail) | Agent 1 | Mode A: Step 1 五问推导 / Mode B: Step 2 增量构建 |
| 时序错误 (timeline fail) | Agent 1 | Mode A: Step 3 工作流 / Mode B: Step 2.7 节点链路 |
| 命名/字段问题 (naming/fields fail) | Agent 1 | Mode A: Step 4 字段配置 / Mode B: Step 2 增量构建 |
| 逻辑问题 (logic fail) | Agent 1 | Mode A: Step 3 工作流 / Mode B: Step 2 增量构建 |
| 过度设计 (signals fail) | Agent 1 | Mode A: Step 3 工作流（删节点）/ Mode B: Step 2 |
| typeId/actionId 错误 | Agent 2 | Mode A: Step 3 工作流 / Mode B: Step 2 |
| 批量上限/拓扑问题 | Agent 2 | Mode A: Step 3 工作流（重构节点链）/ Mode B: Step 2 |
| 平台陷阱 | Agent 2 | Mode A: Step 0 平台边界 / Mode B: Step 0 上下文 |

**修复行动计划生成**（新增）：

从两个 Agent 的 `fix_guide` 生成合并的修复行动计划，按难度排序：

1. **先修 easy**：从两个 Agent 的 fix_guide.easy 合并去重，生成 quick-fix 清单
2. **再修 medium**：合并两个 Agent 的 fix_guide.medium，标注涉及的节点/字段
3. **最后攻坚 hard**：合并两个 Agent 的 fix_guide.hard，标注需要重新设计的方向

生成的修复计划写入 `execution_lock.json` 的 `gates.fix_plan` 字段：

```json
{
  "gates": {
    "agent_1_logic": {"result": "fail", "issues": [...]},
    "agent_2_platform": {"result": "pass", "issues": [...]},
    "fix_plan": {
      "easy": [...],
      "medium": [...],
      "hard": [...],
      "total_issues": 0
    }
  }
}
```

**Hard Stop 条件**：
- 同一问题修正 2 次后 Agent 仍 fail → **输出 LOW 置信度方案**，在输出顶部醒目标注"以下决策置信度为 LOW，建议人工审核"，列出争议点。**不中止**，让用户决定接受 LOW 置信度还是放弃方案
- Agent 返回 uncertain 项 → 主 Agent 逐项判断是否需要打断用户
- `fix_plan.hard` 非空 → 打印醒目的"以下问题需要重新设计"提示，但不阻断输出
- **修正上限**: 同一轮最多修正 3 次。3 次后仍 fail → 强制输出 LOW 置信度方案 + 所有争议点

### Step 4: 写入门控结果

将两个 Agent 的裁决和修复计划写入 `execution_lock.json` 的 `gates` 字段：

```json
{
  "gates": {
    "agent_1_logic": {"result": "pass", "issues": [...]},
    "agent_2_platform": {"result": "pass", "issues": [...]},
    "fix_plan": {"easy": [], "medium": [], "hard": [], "total_issues": 0}
  }
}
```

写入后运行 `lock_manager.py validate` 确认合约仍然有效。

---

## Gate 4: 平台原生校验（地面真相）

Gate 1-3 通过后，调用平台自身的 validate API：

```bash
python3 ${SKILL_DIR}/scripts/platform-validate.py --lock-file execution_lock.json
```

**判定规则**：

| 平台结果 | 行为 |
|---------|------|
| pass | 平台确认通过 → 最终输出，置信度 HIGH |
| fail | 平台拒绝 → 平台说 fail 才是真的 fail。输出平台原生错误 + 修正建议 |
| skipped | 无平台认证 (Chrome 未登录 / 无 AppKey) → 不阻断，标注"未经平台校验" |

**为什么这是地面真相**: 我们的 Agent 1/2 对照的是文档，平台 validate 对照的是运行时。平台知道节点间引用是否有效、数据链路是否合法、是否有我们不知道的平台约束。平台说 pass >> 我们的 Agent 说 pass。

---

## Mode D 专用: Agent 3 (audit-scanner)

Audit-scanner 的调用在 Mode D Step 3 门控验证中：

```
Agent(
  subagent_type="general-purpose",
  description="Audit scan completeness check",
  prompt="
  加载 ${SKILL_DIR:-~/.claude/skills/hhr-plan}/agents/audit-scanner.md 作为你的完整指令。

  输入文件:
  - 审计报告: <审计报告路径>
  - 项目上下文: ~/Documents/workflow-output/{项目名}/project_context.json

  只检查扫描完整性，不判断审计结论的正确性。
  输出 verdict: pass | fail，fail 时列出漏检维度。
  "
)
```

---

## 执行纪律

- Agent 1 和 Agent 2 **必须同时启动**（并行），不能串行等待
- 两个 Agent 都完成后，主 Agent 自动合并结果并推进，不等待用户
- 仅当修正 2 次仍 fail 时才打断用户
- Agent 输出为结构化 JSON，主 Agent 解析 JSON 而非阅读自然语言
