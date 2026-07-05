# implementation-notes: validate-agent-output-py

## 目标

创建 `scripts/validate-agent-output.py`，作为后置闸门验证 Agent 1/2/3 的输出完整性。
这是 RepoPrompt CE `source_layout_guardrails.sh` 的等价物——在 Agent 输出进入用户视野之前做确定性格式校验。

## 设计决策

### 1. 检查维度

| 检查项 | 说明 | 严重度 |
|--------|------|--------|
| JSON 可解析 | 输入是有效 JSON | high |
| 顶级字段存在 | verdict, sections/node_checks, issues, fix_guide, summary 存在 | high |
| sections 完整性 (Agent 1) | axiom_compliance, timeline, naming_and_fields, logic, signals 全部存在 | high |
| node_checks 完整性 (Agent 2) | 每个节点有 type_exists, sub_mode, data_link, batch_limit, no_data_policy, fetch_mode | medium |
| verdict 一致性 | summary 中的 failed 数 > 0 时 verdict 应为 fail | medium |
| issues 结构 | 每条 issue 有 severity, description, fix | medium |
| fix_guide 分组 | easy/medium/hard 必须存在（即使为空数组） | low |
| 无空 section | section.result 不为 null/None/空字符串 | high |
| delegated items 标记 | 委托给其他 Agent 的检查必须显式标注 | low |

### 2. 不像 RepoPrompt CE 做的事
- 不验证 Agent 判断的**正确性**（那是人工审查的事）
- 不修改 Agent 输出（只读验证）
- 不确定性问题不做判断（如"Agent 说公理3通过但实际可能不通过"）

### 3. 累积式失败
同 verify-platform.py 和 RepoPrompt CE 的 guardrails：
- 所有检查项收集到 violations 列表
- 不提前退出
- exit code 0 = 格式完整, exit code 1 = 格式有问题
