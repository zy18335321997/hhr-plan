---
name: hap-flow-exec
description: 工作流创建执行器。将设计方案（Markdown 或 JSON）通过 hap CLI 在明道云平台创建为可运行的工作流。先预检再执行，步步验证，失败硬停。当用户说"创建工作流""按设计创建""部署工作流""执行设计方案"时触发。
user_invocable: true
version: 1.1.0
lifecycle: validating
references:
  - system-prompt.md
  - references/execution-contract-schema.md
  - references/execution-orchestrator.md
  - references/verified-node-dsl.md
  - references/behavior-traps.md
  - scripts/preflight.py
  - scripts/live_preflight.py
  - scripts/contract_to_batch_dsl.py
  - scripts/run_batch_add.py
  - scripts/structure_to_mappings.py
  - scripts/save_actions.py
---

# HAP 工作流执行器 v1.1

> 设计方案的忠实执行者。不做推理，不做简化，不做偏离。
> Agent 按 `references/execution-orchestrator.md` 观察和收敛失败；底层 CLI
> 始终保持确定性。

## 核心约束

**设计方案是权威输入。执行器不修改、不简化、不猜测。**

- 每个节点严格按设计配置
- 每个 fieldId 必须预检存在
- 每个 option key 必须预检存在
- 创建后拉实际结构对比设计
- 任何环节不匹配 → Hard Stop，不继续

## 前置检查

### hap CLI 可用性

```bash
hap auth whoami
```

- 返回用户信息 → 继续
- 命令未找到 / 未登录 / 报错 → 输出停止卡片，严禁继续

## 执行 Pipeline

执行前初始化 `execution_state.json`；每一步成功后持久化 checkpoint，重进会话先
校验 contract digest，再从未完成步骤继续。已完成的写入步骤禁止重复执行。

```
Step 0: 加载设计方案          ⛔ 缺失/模糊→停
Step 1: 提取执行合约          ⛔ 关键信息缺失→停
Step 2: 静态预检 + 平台只读预检 ⛔ 任何 ID/option key 无效→停
  ⏸ 用户确认                  ⛔ 必须等用户确认后才进入创建
Step 3: 创建工作流骨架        AUTO
Step 4: 合约→Batch DSL→批量创建节点骨架 AUTO
Step 4.5: 配置 action 节点字段 AUTO（save-action）
Step 5: 结构验证              ⛔ 不匹配→停，逐项差异
Step 6: 发布（先 inner 后主）  ⛔ 发布失败→停
Step 7: 确认                  AUTO
```

每步格式：🚧 GATE（入站条件）→ Action（执行）→ ✅ Checkpoint（出站验证）

非 BLOCKING 步骤自动连续推进。⛔ 标记步骤必须停等。

详细 Pipeline 定义见 `system-prompt.md`。

## Hard Stop 条件

| 条件 | 动作 |
|------|------|
| Step 0 设计方案找不到或版本不匹配 | 停。列出已找到的文件 |
| Step 2 预检发现 fieldId 不存在 | 停。列出缺失 ID + 来源表 |
| Step 2 预检发现 option key 不存在 | 停。列出字段 + 当前 options |
| Batch DSL 缺少物理 trigger nodeId | 停。先完成骨架创建并回填运行时 ID |
| save-action 缺少 PID/aliasToNodeId | 停。保留执行状态，不猜测映射 |
| Step 4 batch-add 返回非 200 | 停。报告完整错误+请求体 |
| Step 5 结构对比不匹配 | 停。列出逐项差异（预期 vs 实际） |
| Step 6 publish 返回 Error | 停。报告。不尝试重试 |
| 同一错误出现 2 次 | 停。标记已知限制 |
