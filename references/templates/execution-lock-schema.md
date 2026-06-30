# execution_lock.json Schema

> 机器可读设计合约。与 design_spec.md 同时产出，在所有后续修改/验证/恢复上下文时作为权威来源。

## 使用场景

| 场景 | 用法 |
|------|------|
| 设计输出时 | AI 写完 design_spec.md 后同步生成 execution_lock.json |
| 上下文恢复 | 新会话加载 execution_lock.json 即可恢复全部设计状态 |
| 验证 | `design_validator.py --lock-file <path>` 校验表中引用 |
| 增量修改 | Mode B 修改前加载 lock 文件，修改后更新 lock 文件 |

## 完整 Schema

```json
{
  "meta": {
    "project": "string",
    "mode": "A|B",
    "created": "YYYY-MM-DD",
    "updated": "YYYY-MM-DD",
    "axioms_covered": ["公理1", "公理2", ...],
    "confidence": "HIGH|MEDIUM|LOW"
  },
  "naming": {
    "auto_number_prefix": "string (2-4字母)",
    "workflow_verb_prefixes": ["string", ...],
    "worksheet_suffix_format": "子表（父表/操作类型）",
    "bool_field_prefix": "是否",
    "field_ordering": ["身份标识", "业务属性", "关联引用", "计算汇总"]
  },
  "sheets": [
    {
      "name": "string",
      "module": "string",
      "is_hub": true|false,
      "hub_reference": "string|null (非Hub时指向Hub表)",
      "fields": [
        {
          "name": "string",
          "type": "Text|Number|Date|DateTime|Attachment|...",
          "default_value": "string|null",
          "required": true|false,
          "unique": true|false,
          "axiom_ref": "公理N",
          "note": "string (可选)"
        }
      ]
    }
  ],
  "associations": [
    {
      "from_sheet": "string",
      "to_sheet": "string",
      "field_name": "string (关联字段名)",
      "type": 29|30|34,
      "type_label": "关联表|他表字段|子表",
      "display_fields": ["string"],
      "filter": "string|null",
      "on_empty": "赋空值继续|null",
      "axiom_ref": "公理N",
      "direction_note": "单向引用Hub / 只读汇总 / 主子关系"
    }
  ],
  "workflows": [
    {
      "name": "string",
      "trigger_sheet": "string",
      "trigger_type": "button|event|schedule|subprocess",
      "trigger_name": "string (按钮名/事件类型)",
      "complexity": "Simple|Standard|Complex|VComplex",
      "data_signature": "Mutator|Signal|Creator|Orchestrator",
      "node_count": 0,
      "has_approval": true|false,
      "has_notification": true|false,
      "pattern_match": "Pattern-A|Pattern-B|...|null",
      "axiom_ref": "公理N",
      "node_chain": [
        {
          "index": "T0|T1|T2|...",
          "node_type": "string (触发|查询|获取单条|获取多条|新增|更新|审批|分支|通知|子流程|...)",
          "type_id": 0,
          "description": "string",
          "target_sheet": "string|null",
          "writes_fields": ["string"],
          "reads_fields": ["string"],
          "empty_strategy": "继续执行|中止|null",
          "approval_config": {
            "mode": "或签|会签|null",
            "approver_source": "string|null",
            "timeout_hours": 0,
            "fallback": "流程拥有者代理|null",
            "retreat_target": "仅发起节点|null"
          },
          "subprocess_config": {
            "workflow_name": "string|null",
            "execution_mode": "逐条|批量|单次|null",
            "abort_strategy": "继续下一条|中止|null"
          }
        }
      ],
      "timing_constraint": "Tn 只读 T0..T{n-1} 已写入的字段"
    }
  ],
  "gates": {
    "gate_1_dependency": {"result": "pass|fail", "issues": ["string"]},
    "gate_2_logic": {"result": "pass|fail", "issues": ["string"]},
    "gate_3_timing": {"result": "pass|fail|n/a", "issues": ["string"]},
    "gate_4_fields": {"result": "pass|fail", "issues": ["string"]},
    "gate_5_platform": {"result": "pass|fail", "issues": ["string"]},
    "gate_6_reasoning": {"result": "pass|fail", "issues": ["string"]}
  }
}
```

## 与 design_validator.py 的集成

```bash
# 验证 lock 文件中的表/字段引用
python3 design_validator.py 几建 --lock-file execution_lock.json

# 验证新增关联不产生环路
python3 design_validator.py 几建 --lock-file execution_lock.json --check-graph
```
