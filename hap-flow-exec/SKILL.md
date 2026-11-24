---
name: hap-flow-exec
description: 工作流创建执行器。消费父技能 hhr-plan 从 execution_lock.json 派生的执行合约（execution_contracts/<safe-workflow-name>.json），通过 hap CLI 在明道云平台创建为可运行的工作流。先预检再执行，步步验证，失败硬停。当用户说"创建工作流""按设计创建""部署工作流""执行设计方案"时触发。
user_invocable: true
version: 1.2.0
lifecycle: validating
references:
  - system-prompt.md
  - references/execution-contract-schema.md
  - references/execution-orchestrator.md
  - references/verified-node-dsl.md
  - references/behavior-traps.md
  - scripts/execution_state.py
  - scripts/preflight.py
  - scripts/live_preflight.py
  - scripts/contract_to_batch_dsl.py
  - scripts/hap_dsl_extensions.py
  - scripts/run_batch_add.py
  - scripts/structure_to_mappings.py
  - scripts/save_actions.py
---

# HAP 工作流执行器

> 执行合约的忠实执行者。不做推理，不做简化，不做偏离。
> Pipeline 唯一真源是 `system-prompt.md`；本文件只保留摘要与指针。

## 核心约束

**执行合约是权威输入。执行器只消费，不产出、不手改。**

- 合约由父技能 hhr-plan 的 `lock_to_contract.py` 从 `execution_lock.json` 派生，
  并由父技能 `contract_compat.py validate-exec` 校验
- 每个节点严格按合约配置
- 每个 fieldId、option key 必须预检存在
- 创建后拉实际结构对比合约
- 任何环节不匹配 → Hard Stop，不继续

## 前置检查

### hap CLI 可用性

```bash
hap auth whoami
```

- 返回用户信息 → 继续
- 命令未找到 / 未登录 / 报错 → 输出停止卡片，严禁继续

## 执行 Pipeline（摘要）

执行前用 `scripts/execution_state.py init` 初始化 `execution_state.json`；每步成功后
持久化 checkpoint，重进会话先校验合约 digest，再从未完成步骤继续。已完成的写入
步骤禁止重复执行。

```
Step 0: 加载执行合约            ⛔ 缺失/无法解析→停
Step 1: 校验执行合约            ⛔ validate-exec 失败→停
Step 2: 静态预检 + 平台只读预检  ⛔ 任何 ID/option key 无效→停
Step 3: 创建工作流骨架 + 触发器  AUTO
Step 4: 合约→Batch DSL→批量创建节点骨架 AUTO
Step 4.5: 配置 action 节点字段  AUTO（save-action）
Step 5: 结构验证                ⛔ 不匹配→停，逐项差异
Step 6: 发布（先 inner 后主）    ⛔ 发布失败→停
Step 7: 确认                    AUTO
```

用户确认已在 hhr-plan 设计阶段完成；执行器只在 Step 2 预检发现与合约/平台偏差时
再次停等用户，不在入口重复要求确认。

每步 GATE、BLOCKING 清单、Hard Stop 条件与 batch-add 退出码语义全部以
`system-prompt.md` 为准。失败分类与恢复见 `scripts/execution_state.py`；
步进与状态映射见 `references/execution-orchestrator.md`。
