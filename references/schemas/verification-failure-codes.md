# Agent 校验失败码

失败码只表达 **Agent 的语义裁决**。JSON 无法解析、字段缺失、类型错误等输出完整性问题由
`validate-agent-output.py` 报告为 `format_failures`，不得伪装成 Agent 语义失败。

| failure_code | agent_id | 含义 | 何时使用 |
|---|---|---|---|
| `null` | 全部 | Agent 语义校验通过 | `verdict = pass` |
| `A1_LOGIC_FAILED` | `agent_1_logic` | 设计逻辑、公理、时序、字段或推理质量不通过 | `verdict = fail` |
| `A2_PLATFORM_FAILED` | `agent_2_platform` | 节点能力、数据链路、批量限制或拓扑不通过 | `verdict = fail` |
| `A3_AUDIT_COVERAGE_INCOMPLETE` | `agent_3_audit` | Mode D 扫描存在漏检维度、未覆盖约束或假阴性 | `verdict = fail` |

## 一致性规则

1. `verdict = pass` 时，`failure_code` 必须为 `null`，`summary.failed` 必须为 `0`。
2. `verdict = fail` 时，必须使用与 `agent_id` 对应的失败码，且 `summary.failed > 0`。
3. Agent 3 的 `payload.missed_dimensions` 是固定字段名，不得改成 `missing`、`missed` 或自然语言键。
4. Agent 3 通过时，`missed_dimensions`、`uncovered_constraints`、`false_negatives` 必须全部为空；任一非空时必须判定失败。
5. 输出格式不完整时，合并器不得修改目标文件的 `gates`。

## 合并器退出码

| 退出码 | 含义 | 是否写入 gates |
|---|---|---|
| `0` | 输出完整，所有 Agent 语义通过 | 是 |
| `1` | 输出完整，至少一个 Agent 语义失败 | 是，写入失败裁决和修复计划 |
| `2` | 输出格式或完整性失败 | 否 |
