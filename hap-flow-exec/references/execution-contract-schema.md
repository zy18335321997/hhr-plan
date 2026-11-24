# 执行合约结构（执行器消费侧）

> 执行合约由父技能 hhr-plan 的 `lock_to_contract.py` 从 `execution_lock.json` 派生，
> 路径 `<project>/execution_contracts/<safe-workflow-name>.json`。
> 执行器只消费，不产出、不手改；合约缺失时不得自行生成。
>
> 权威结构定义不在此文件：以父技能
> `~/.claude/skills/hhr-plan/scripts/contract_compat.py validate-exec` 为准，
> 正例样本见 `~/.claude/skills/hhr-plan/tests/fixtures/expected_execution_contract.json`
> （节点含 `type_id` / `action_id`，本文不复制完整 Schema）。

## 执行器消费的字段

- `meta.workflow_name`
- `target.org_id` / `target.app_id` / `target.worksheet_id`
- `trigger.type`：父技能 lock schema 的五个值 button / event / schedule /
  subprocess / pbp
- `nodes[]` 的 `alias` / `nodeType` / `name` / `config` ——
  `contract_to_batch_dsl.py` 只读这四个键生成 batch DSL，其余键由父技能校验器负责
- `field_references[]`：`fieldId`、`type`、`expected_options`（选项字段）、
  `relation_worksheet_id`（Relation 字段）供预检使用
- `dependencies` / `publish_order`：发布顺序

## 结构备注（执行器消费语义）

### approval_block

审批内部节点的 `config.target.node` 固定为 `"approval_start"`。

### sub_process

子流程内层节点的 `config.target.node` 固定为 `"sub_trigger"`；
`process.mode: "create"` 时由 batch-add 创建 inner process，inner PID 从
batch-output 的 `innerProcessId` 回填。

### Relation 写入值

`Relation` 值必须是目标记录的 `rowId`（GUID），不能是记录 `_id`；
单关联字段在 save-action wire 中使用单个 rowId 字符串。
