# Agent 执行编排协议

> Agent 负责观察、分类和路由；脚本负责确定性验证、写入与状态持久化。
> Agent 不得直接修改 `execution_contract.json`。

## 初始化

```bash
python3 scripts/execution_state.py init \
  --contract execution_contract.json \
  --state execution_state.json
```

每次动作前先运行 `status`。若 contract digest 变化，旧状态作废，回到 hhr-plan
重新门控并初始化新状态。

## 固定循环

1. 读取 `execution_state.current_step`。
2. 写入步骤先运行 `execution_state.py begin --state ... --step ...`，把 operation_id
   持久化后才调用平台。会话若在平台成功与 advance 之间中断，恢复时必须先只读
   探测，禁止直接重跑。
3. 只执行该步骤对应的确定性命令。
4. 成功后运行 `execution_state.py advance`，把 PID、triggerNodeId、
   aliasToNodeId 和 innerProcessId 写入状态。
5. 失败后运行 `execution_state.py fail`，按 `decision` 处理：

| decision | Agent 行为 |
|---|---|
| `retry` | 仅重试同一步；最多 3 次，不重新创建已完成节点 |
| `reprobe` | 重跑 live preflight，刷新运行时 ID；不修改设计 |
| `mode_b_handoff` | 输出结构化错误和当前状态，回 hhr-plan Mode B 修改 lock |
| `await_user` | 已有部分写入；列出补偿/保留方案，等待用户确认 |
| `hard_stop` | 停止，报告重复失败证据 |

## 步骤命令

```text
static_preflight  → preflight.py
live_preflight    → live_preflight.py
create_skeleton   → hap workflow create / create-custom-action
batch_add         → contract_to_batch_dsl.py → hap workflow node batch-add
save_actions      → save_actions.py
structure_verify  → hap workflow structure + deterministic diff
publish_inner     → 按 execution_state.inner_pids 发布
publish_main      → 发布 execution_state.pid
complete          → 最终只读结构复核
```

## Mode B handoff

语义或合约错误必须返回：

```json
{
  "source": "hap-flow-exec",
  "workflow_name": "工作流名",
  "contract_digest": "sha256",
  "failed_step": "batch_add",
  "failure_class": "SEMANTIC",
  "message": "原始错误",
  "runtime": {"pid": "...", "completed_steps": []},
  "next_action": "return_to_hhr_plan_mode_b"
}
```

Mode B 修改 `execution_lock.json` 后，重新执行门控、派生 contract、等待用户确认。
禁止直接修补旧 contract 后继续。
