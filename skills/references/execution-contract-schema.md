# execution_contract.json Schema

> 设计方案 → 机器可读执行合约。Step 1 产出，Step 2-6 消费。执行器不修改此文件。

## 完整 Schema

```json
{
  "meta": {
    "schema_version": "1.0",
    "source_design": "path/to/设计方案-v2.md",
    "project": "同技智能",
    "created": "2026-07-05",
    "workflow_name": "图书归还",
    "node_count": 10
  },
  "target": {
    "org_id": "0a2cb820...",
    "app_id": "0a2cb820-3d11-4a3a-b9e4-ef5d62bcbfc2",
    "worksheet_id": "6a4919614571a285a30463ac"
  },
  "trigger": {
    "type": "button",
    "config": {
      "name": "图书归还",
      "worksheet_id": "6a4919614571a285a30463ac",
      "app_id": "0a2cb820-3d11-4a3a-b9e4-ef5d62bcbfc2",
      "enable_condition": "status in [borrowing, overdue]"
    }
  },
  "nodes": [
    {
      "seq": "T1",
      "alias": "get_borrow_record",
      "nodeType": "get_single",
      "name": "获取借阅记录",
      "config": {
        "worksheet": "6a4919614571a285a30463ac",
        "target": {"kind": "trigger", "node": "trigger"},
        "ifEmpty": "continue"
      }
    },
    {
      "seq": "T2",
      "alias": "check_status",
      "nodeType": "branch",
      "name": "状态校验",
      "config": {
        "target": {"node": "get_borrow_record"},
        "mode": "firstMatch",
        "paths": [
          {
            "name": "可归还",
            "condition": {
              "left": {"fieldId": "6a49..63be", "node": "get_borrow_record", "_filedTypeId": 9},
              "op": "in",
              "right": {"kind": "literal", "value": ["<借阅中-key>", "<逾期-key>"]}
            },
            "nodes": ["mark_approving", "return_approval", "check_approval_result",
                       "update_returned", "book_shelf_subprocess", "notify_returned",
                       "update_rejected", "notify_rejected"]
          },
          {
            "name": "已归还",
            "condition": {
              "left": {"fieldId": "6a49..63be", "node": "get_borrow_record", "_filedTypeId": 9},
              "op": "eq",
              "right": {"kind": "literal", "value": "<已归还-key>"}
            },
            "nodes": []
          }
        ]
      }
    }
  ],
  "field_references": [
    {"fieldId": "6a49..63be", "worksheet": "6a4919614571a285a30463ac", "fieldName": "状态", "type": "SingleSelect", "expected_options": ["借阅中", "已归还", "逾期"]},
    {"fieldId": "6a49..63bd", "worksheet": "6a4919614571a285a30463ac", "fieldName": "实际归还日期", "type": "Date"},
    {"fieldId": "6a49..63b8", "worksheet": "6a4919614571a285a30463ac", "fieldName": "关联图书", "type": "Relation"}
  ],
  "dependencies": {
    "subprocesses": [
      {"name": "图书归还-归架流程", "pid": null}
    ]
  },
  "publish_order": ["subprocesses", "main_workflow"]
}
```

## 字段说明

### nodes[].config.target
- `kind`: "trigger" | "record" | "node"
- `node`: 上游节点 alias（get_single/get_multiple/approval_block 产出的记录）

### nodes[].config.condition (for get_single/get_multiple filter)
```json
{
  "logic": "and",
  "items": [
    {
      "left": {"fieldId": "<fieldId>", "node": "<本节点alias>", "_filedTypeId": 9},
      "op": "eq",
      "right": {"kind": "literal", "value": "<UUID key>"}
    }
  ]
}
```

### nodes[].config.paths[].condition (for branch)
```json
{
  "left": {"fieldId": "<fieldId>", "node": "<数据源alias>", "_filedTypeId": 9},
  "op": "eq",
  "right": {"kind": "literal", "value": "<UUID key>"}
}
```
> ⚠️ `left.node` = 数据源节点 alias（如 get_borrow_record），**不是分支自身 alias**

### nodes[].config (for approval_block)
```json
{
  "target": {"node": "<记录alias>"},
  "initiators": [{"kind": "triggerUser"}],
  "process": {
    "mode": "create",
    "name": "审批流程名",
    "nodes": [
      {"nodeAlias": "approval_start", "nodeType": "approval_start"},
      {
        "nodeAlias": "approve_step",
        "nodeType": "approve",
        "name": "审批步骤",
        "config": {
          "target": {"node": "approval_start"},
          "approvers": [{"kind": "triggerUser"}],
          "allowReject": true
        }
      }
    ]
  }
}
```
> ⚠️ 审批内部 target.node = **"approval_start"**（固定值）

### nodes[].config (for sub_process)
```json
{
  "target": {"node": "<数据源alias>"},
  "executionMode": "sequential_each_continue_on_error",
  "process": {
    "mode": "create",
    "name": "子流程名",
    "nodes": []
  }
}
```
> ⚠️ 子流程内层节点 target.node = **"sub_trigger"**（固定值）
