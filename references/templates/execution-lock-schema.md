# execution_lock.json Schema

> `execution_lock.json` 是设计阶段唯一真源。`design_spec.md` 只供人阅读；
> `execution_contract.json` 必须由 `lock_to_contract.py` 生成，不得手工维护。

## 字段命名与兼容边界

- lock 规范字段统一使用 `snake_case`，尤其是 `type_id`、`action_id`。
- 校验器和转换器暂时兼容旧输入 `typeId`、`actionId`；两种写法同时出现时值必须一致。
- 节点 `config` 是 hap-flow-exec DSL 的原样配置，内部键名（如 `fieldId`、
  `nodeAlias`）遵循执行器协议，不做改名。
- 所有平台 ID 和节点 `config` 必须在 lock 中明确给出。转换器不会根据名称、
  上下文或节点类型补值。
- 选项字段统一使用 `{key, label}`：lock 同时保存平台 key 与客户可读 label；
  `lock_to_contract.py` 只把 key 传给执行器，严禁用中文 label 猜 key。

机器校验定义：
`references/schemas/execution-lock-validation-schema.json`。

## 规范结构

```json
{
  "meta": {
    "schema_version": "2.1",
    "source_design": "path/to/design_spec.md",
    "project": "项目名",
    "mode": "A",
    "created": "2026-07-21",
    "updated": "2026-07-21",
    "axioms_covered": ["公理1"],
    "confidence": "HIGH"
  },
  "target": {
    "org_id": "组织ID",
    "app_id": "应用ID"
  },
  "naming": {
    "auto_number_prefix": "PO",
    "workflow_verb_prefixes": ["创建", "更新"],
    "worksheet_suffix_format": "子表（父表/操作类型）",
    "bool_field_prefix": "是否",
    "field_ordering": ["身份标识", "业务属性", "关联引用", "计算汇总"]
  },
  "design_ir": {
    "requirements": [{"id": "REQ-001", "statement": "客户原始需求", "priority": "must", "acceptance_criteria": ["可验收结果"]}],
    "actors": [{"id": "ACT-001", "name": "业务角色", "responsibilities": ["角色职责"]}],
    "scenarios": [{"id": "SCN-001", "actor_ids": ["ACT-001"], "trigger": "触发条件", "outcome": "业务结果", "exceptions": []}],
    "entities": [{"id": "ENT-001", "table_name": "工作表名", "field_dimensions": {"identity": [], "business": ["业务字段"], "status": ["状态"], "time": [], "ownership": [], "relations": [], "audit": []}}],
    "state_machines": [],
    "business_rules": [],
    "permissions": [{"actor_id": "ACT-001", "table": "工作表名", "actions": ["read"], "row_scope": "按角色范围"}],
    "views": [{"id": "VIEW-001", "actor_id": "ACT-001", "name": "角色视图", "table": "工作表名", "fields": [], "filter": "", "sort": ""}],
    "buttons": [],
    "notifications": [],
    "assumptions": [],
    "traceability": [{"requirement_id": "REQ-001", "artifacts": [{"kind": "entity", "ref": "ENT-001"}]}]
  },
  "sheets": [
    {
      "name": "采购需求",
      "worksheet_id": "worksheet-id",
      "module": "采购",
      "is_hub": false,
      "hub_reference": null,
      "fields": [
        {
          "name": "状态",
          "field_id": "field-id",
          "type": "SingleSelect",
          "options": [
            {"key": "draft-option-key", "label": "草稿"},
            {"key": "submitted-option-key", "label": "已提交"}
          ],
          "default_value": {"key": "draft-option-key", "label": "草稿"},
          "required": true,
          "unique": false,
          "axiom_ref": "公理3",
          "note": ""
        }
      ]
    }
  ],
  "associations": [
    {
      "from_sheet": "采购需求",
      "to_sheet": "供应商",
      "field_name": "供应商",
      "field_id": "relation-field-id",
      "type": 29,
      "type_label": "关联表",
      "display_fields": ["供应商名称"],
      "filter": null,
      "on_empty": "赋空值继续",
      "axiom_ref": "公理4",
      "direction_note": "业务表单向引用 Hub"
    }
  ],
  "workflows": [
    {
      "name": "提交采购需求",
      "worksheet_id": "worksheet-id",
      "trigger_sheet": "采购需求",
      "trigger_type": "button",
      "trigger": {
        "type": "button",
        "config": {
          "name": "提交",
          "worksheet_id": "worksheet-id",
          "app_id": "应用ID",
          "enable_condition": "明确的执行条件"
        }
      },
      "complexity": "Simple",
      "data_signature": "Mutator",
      "node_count": 1,
      "node_chain": [
        {
          "index": "T1",
          "alias": "update_status",
          "node_type": "update_record",
          "type_id": 6,
          "action_id": 2,
          "name": "更新状态",
          "description": "把当前记录状态更新为已提交",
          "target_sheet": "采购需求",
          "writes_fields": ["状态"],
          "reads_fields": [],
          "config": {
            "worksheet": "worksheet-id",
            "target": {"kind": "trigger", "node": "trigger"},
            "fields": [
              {
                "fieldId": "field-id",
                "value": {
                  "key": "submitted-option-key",
                  "label": "已提交"
                }
              }
            ]
          }
        }
      ],
      "field_references": [
        {
          "field_id": "field-id",
          "worksheet_id": "worksheet-id",
          "field_name": "状态",
          "type": "SingleSelect",
          "expected_options": [
            {"key": "draft-option-key", "label": "草稿"},
            {"key": "submitted-option-key", "label": "已提交"}
          ]
        }
      ],
      "dependencies": {"subprocesses": []},
      "publish_order": ["main_workflow"],
      "timing_constraint": "Tn 只读 T0..T{n-1} 已写入的字段"
    }
  ],
  "gates": {
    "gate_1_dependency": {"result": "pass", "issues": []},
    "gate_2_logic": {"result": "pass", "issues": []},
    "gate_3_timing": {"result": "pass", "issues": []},
    "gate_4_fields": {"result": "pass", "issues": []},
    "gate_5_platform": {"result": "pass", "issues": []},
    "gate_6_reasoning": {"result": "pass", "issues": []},
    "agent_1_logic": {"result": "pass"},
    "agent_2_platform": {"result": "pass"}
  },
  "verification": {
    "input_digest": "<由 agent_prepare.py 计算的 64 位 SHA-256>",
    "verification_agents": {
      "schema_version": "1.1",
      "completeness": "pass",
      "semantic_verdict": "pass",
      "agents": ["agent_1_logic", "agent_2_platform"]
    },
    "fix_plan": {"easy": [], "medium": [], "hard": [], "total_issues": 0}
  }
}
```

`field_references` 中 `type=Relation` 时必须额外提供
`relation_worksheet_id`，并在 live preflight 中与平台关联目标逐项核对。

`verification` 与 Agent gates 只能由 `verification_merge.py` 写入。基础 Gate 1-6
属于设计输入并参与摘要；顶层 `verification` 和 Agent gates 是派生裁决，不参与摘要，
避免合并产生自引用哈希。

## 闭环命令

```bash
# 1. lock 结构
python3 scripts/contract_compat.py validate-lock execution_lock.json

# 2. 项目字段与依赖，可注入 fixture，避免依赖 ~/Documents
python3 scripts/design_validator.py 项目名 \
  --lock-file execution_lock.json \
  --context-file project_context.json \
  --graph-file dependency_graph.json

# 3. 平台节点机械检查
python3 scripts/verify-platform.py --lock-file execution_lock.json

# 4. 严格派生单工作流执行合约
python3 scripts/lock_to_contract.py execution_lock.json \
  --workflow 提交采购需求 \
  --output execution_contracts/submit-purchase.json

# 5. hap-flow-exec 合约结构
python3 scripts/contract_compat.py validate-exec \
  execution_contracts/submit-purchase.json
```

若 lock 含多个工作流，转换时必须传 `--workflow` 精确选择；若任何 ID、alias、
`node_type`、`type_id`、必需的 `action_id`、`config`、依赖或发布顺序缺失，
转换立即失败并返回具体 JSON 路径。
