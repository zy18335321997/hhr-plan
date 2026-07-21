# 验证通过的节点 DSL 格式

> 来源：2026-07-05 完整验证 session。18 种节点类型全部通过验证。
> 16 种通过 batch-add，2 种（delay / code）通过 node add。

## 获取/查询节点

### get_relation（获取关联记录）

```json
{
  "nodeAlias": "get_book",
  "nodeType": "get_relation",
  "name": "获取关联图书",
  "config": {
    "worksheet": "<源表ID>",
    "target": {"node": "<上游alias>"},
    "fields": [{"fieldId": "<关联字段ID>"}]
  }
}
```

### get_single（查询单条）

```json
{
  "nodeAlias": "find_book",
  "nodeType": "get_single",
  "name": "查找图书",
  "config": {
    "worksheet": "<目标表ID>",
    "target": {"node": "<上游alias>"},
    "ifEmpty": "continue"
  }
}
```

**带 filter：**
```json
{
  "nodeAlias": "find_book",
  "nodeType": "get_single",
  "name": "查找图书",
  "config": {
    "worksheet": "<目标表ID>",
    "target": {"node": "<上游alias>"},
    "ifEmpty": "continue",
    "filter": {
      "logic": "and",
      "items": [
        {
          "left": {"fieldId": "<字段ID>", "node": "find_book", "_filedTypeId": 9},
          "op": "eq",
          "right": {"kind": "literal", "value": "<optionKey>"}
        }
      ]
    }
  }
}
```

### get_multiple（查询多条）

```json
{
  "nodeAlias": "find_overdue",
  "nodeType": "get_multiple",
  "name": "查询逾期",
  "config": {
    "worksheet": "<wsId>",
    "ifEmpty": "continue"
  }
}
```

## 数据操作节点

### update_record（更新记录）

```json
{
  "nodeAlias": "update_status",
  "nodeType": "update_record",
  "name": "更新状态",
  "config": {
    "worksheet": "<wsId>",
    "target": {"node": "<记录alias>"},
    "fields": [
      {"fieldId": "<字段ID>", "value": "<UUID key or text>"}
    ]
  }
}
```

> ⚠️ **batch-add 创建 update_record 后 fields 被 saveNode 静默丢弃。** 必须用 save-action 补救：
> ```bash
> hap workflow node save-action PID NODE_ID -a 2 --app-id WS_ID \
>   -s SOURCE_NODE_ID -n "名称" \
>   -f '[{"fieldId":"<cid>","type":<ft>,"fieldValue":"<val>"}]'
> ```
> `-a`: 1=AddRecord, 2=EditRecord, 3=DeleteRecord | type: 2=Text, 9=SingleSelect, 11=Dropdown, 15=Date
> 同样适用于 create_record (`-a 1`) 和 delete_record (`-a 3`)

### create_record（新增记录）

```json
{
  "nodeAlias": "create_log",
  "nodeType": "create_record",
  "name": "新增日志",
  "config": {
    "worksheet": "<wsId>",
    "target": {"node": "<上游alias>"},
    "fields": [
      {"fieldId": "<字段ID>", "value": "<值>"}
    ]
  }
}
```

### delete_record（删除记录）

```json
{
  "nodeAlias": "delete_item",
  "nodeType": "delete_record",
  "name": "删除记录",
  "config": {
    "worksheet": "<wsId>",
    "target": {"node": "<记录alias>"}
  }
}
```

## 流程控制节点

### branch（分支）

**条件分支（数据驱动）：**
```json
{
  "nodeAlias": "check_status",
  "nodeType": "branch",
  "name": "状态校验",
  "config": {
    "target": {"node": "<数据源alias>"},
    "mode": "firstMatch",
    "paths": [
      {
        "name": "条件分支A",
        "condition": {
          "left": {"fieldId": "<字段ID>", "node": "<数据源alias>", "_filedTypeId": 9},
          "op": "eq",
          "right": {"kind": "literal", "value": "<值>"}
        },
        "nodes": ["后续alias1", "后续alias2"]
      },
      {
        "name": "默认",
        "nodes": []
      }
    ]
  }
}
```

> ⚠️ `condition.left.node` = **数据源节点 alias**（非分支自身）
> ⚠️ `paths[].nodes[]` = 该路径下的**下一层节点 alias 列表**
> ⚠️ 源码已修复：平铺 `{left,op,right}` 自动包装为 `{logic:"and",items:[...]}`

**审批结果分支：**
```json
{
  "nodeAlias": "check_approval",
  "nodeType": "branch",
  "name": "审批结果",
  "config": {
    "resultFlow": true,
    "paths": [
      {"name": "通过", "result_type": "pass", "nodes": ["update_returned"]},
      {"name": "否决", "result_type": "reject", "nodes": ["update_rejected"]}
    ]
  }
}
```

### approval_block（审批块）

```json
{
  "nodeAlias": "approval",
  "nodeType": "approval_block",
  "name": "审批",
  "config": {
    "target": {"node": "<记录alias>"},
    "initiators": [{"kind": "triggerUser"}],
    "process": {
      "mode": "create",
      "name": "审批流程名",
      "nodes": [
        {
          "nodeAlias": "approval_start",
          "nodeType": "approval_start"
        },
        {
          "nodeAlias": "approve_step",
          "nodeType": "approve",
          "name": "审批步骤",
          "config": {
            "target": {"node": "approval_start"},
            "approvers": [{"kind": "triggerUser"}],
            "mode": "any",
            "allowReject": true
          }
        },
        {
          "nodeAlias": "capture_info",
          "nodeType": "branch",
          "name": "审批信息",
          "config": {
            "resultFlow": true,
            "paths": [
              {"name": "通过", "result_type": "pass", "nodes": []},
              {"name": "否决", "result_type": "reject", "nodes": []}
            ]
          }
        }
      ]
    }
  }
}
```

> ⚠️ 审批内部 target.node = **"approval_start"**（固定）
> ⚠️ 审批内部分支 = **resultFlow: true**
> ⚠️ 审批外部必须接 resultFlow: false 的分支处理 PASS/OVERRULE

### sub_process（子流程）

```json
{
  "nodeAlias": "sub",
  "nodeType": "sub_process",
  "name": "子流程",
  "config": {
    "target": {"node": "<数据源alias>"},
    "executionMode": "sequential_each_continue_on_error",
    "process": {
      "mode": "create",
      "name": "子流程名",
      "nodes": [
        {
          "nodeAlias": "sub_trigger",
          "nodeType": "sub_trigger"
        },
        {
          "nodeAlias": "get_book",
          "nodeType": "get_single",
          "name": "获取图书",
          "config": {
            "worksheet": "<wsId>",
            "target": {"node": "sub_trigger"},
            "ifEmpty": "continue"
          }
        }
      ]
    }
  }
}
```

> ⚠️ 子流程内部第一个数据节点 target.node = **"sub_trigger"**（固定）

## node add 专属（不支持 batch-add）

> 以下两种节点类型 hap CLI 显式禁止通过 batch-add 创建，必须用 `hap workflow node add --after` + `hap workflow node save` 分步创建。

### delay（延时等待）

```bash
hap workflow node add PID --type 12 --name "延时等待" --after UPSTREAM_NODE_ID
```

配置（saveNode）：
- `executeTimeType`: 0=固定时长, 1=截止时间
- `number`: 时长数值
- `unit`: 1=分钟, 2=小时, 3=天

> ⚠️ node add 会产生一对节点（phantom），但功能有效
> ⚠️ 不支持 batch-add，源码 `_normalize_v3_node` 显式拒绝

### code（代码块）

```bash
hap workflow node add PID --type 14 --name "代码块" --after UPSTREAM_NODE_ID
```

配置（saveNode）：
- `code`: JS/Python 代码字符串
- `language`: "javascript" (默认) 或 "python"

> ⚠️ node add 时不会产生 phantom（与 delay 不同）
> ⚠️ 不支持 batch-add，源码 `_normalize_v3_node` 显式拒绝

## 统计与通知

### rollup（汇总统计）

```json
{
  "nodeAlias": "count",
  "nodeType": "rollup",
  "name": "统计",
  "config": {
    "target": {"node": "<上游alias>"},
    "aggregations": [
      {"alias": "total", "fieldId": "rowid", "func": "COUNT"}
    ]
  }
}
```

### compute（数值/日期计算）

```json
{
  "nodeAlias": "calc_days",
  "nodeType": "compute",
  "name": "计算天数",
  "config": {
    "computeType": "dateDiff",
    "startTime": {"kind": "systemField", "fieldId": "nowTime"},
    "endTime": {"kind": "field", "node": "<上游alias>", "fieldId": "<日期字段ID>"},
    "outputUnit": "d"
  }
}
```

> 三种 computeType:
> - `number` — 数值公式（config.formula 表达式）
> - `dateDiff` — 日期差值（startTime + endTime + outputUnit: Y/M/d/h/m）
> - `dateOffset` — 日期偏移（inputTime + offsetExpression，如 `"+30d"`）

### cc（记录详情通知）

```json
{
  "nodeAlias": "notify_cc",
  "nodeType": "cc",
  "name": "抄送通知",
  "config": {
    "target": {"node": "<记录alias>"},
    "accounts": [{"kind": "field", "node": "<记录alias>", "fieldId": "<人员字段ID>"}],
    "showRecordTitle": true
  }
}
```

> ⚠️ cc 必须有 target 记录（与 send_internal_notice 不同）
> ⚠️ 发送多条记录时需包裹在 sub_process 内

### send_email（邮件通知）

```json
{
  "nodeAlias": "notify_email",
  "nodeType": "send_email",
  "name": "邮件通知",
  "config": {
    "accounts": [{"kind": "triggerUser"}],
    "subject": "邮件主题",
    "body": "邮件正文内容",
    "bodyType": "html"
  }
}
```

> ⚠️ 收件人 kind=email 时用 `{"kind":"email","email":"addr@example.com"}`
> ⚠️ bodyType: "html" → rich=true; 默认纯文本
> ⚠️ 抄送用 config.cc（非 ccAccounts）

### fill_in（审批内部填写）

```json
{
  "nodeAlias": "fill_step",
  "nodeType": "fill_in",
  "name": "补充信息",
  "config": {
    "accounts": [{"kind": "triggerUser"}],
    "formProperties": [
      {"fieldId": "<字段ID>", "name": "备注", "required": false, "editable": true}
    ],
    "submitText": "提交"
  }
}
```

> ⚠️ fill_in 只能放在 approval_block 内部 nodes 中
> ⚠️ 审批内层不需要显式声明 approval_start 节点（隐式存在）
> ⚠️ config.instruction → explain; config.submitText → submit_btn_name

### send_internal_notice（站内通知）

```json
{
  "nodeAlias": "notify",
  "nodeType": "send_internal_notice",
  "name": "通知",
  "config": {
    "accounts": [{"kind": "field", "node": "<记录alias>", "fieldId": "<人员字段ID>"}],
    "content": "通知文本内容，可引用 $trigger-字段名$ 和 $system-nowTime$"
  }
}
```

> ⚠️ 源码已修复：content 正确填充到 flowNodeMap.106.content

## filter 条件格式

```json
{
  "logic": "and",
  "items": [
    {
      "left": {"fieldId": "<fieldId>", "node": "<nodeAlias>", "_filedTypeId": <typeCode>},
      "op": "eq",
      "right": {"kind": "literal", "value": "<value>"}
    }
  ]
}
```

### 操作符

`eq` `ne` `gt` `gte` `lt` `lte` `in` `not_in` `empty` `not_empty` `contains`

### 常用 _filedTypeId

| 值 | 类型 |
|----|------|
| 2 | Text |
| 6 | Number |
| 9 | SingleSelect |
| 11 | Dropdown |
| 15 | Date |
| 16 | DateTime |
| 26 | Collaborator |

## 创建方式对照

| nodeType | typeId | 创建方式 |
|----------|--------|---------|
| get_relation | 6 | batch-add |
| get_single | 7 | batch-add |
| get_multiple | 13 | batch-add |
| update_record | 6 | batch-add |
| create_record | 6 | batch-add |
| delete_record | 6 | batch-add |
| branch | 1 | batch-add |
| approval_block | 26 | batch-add |
| approve | 4 | batch-add (inside approval_block) |
| fill_in | 3 | batch-add (inside approval_block) |
| sub_process | 16 | batch-add |
| rollup | 9 | batch-add |
| compute | 9 | batch-add |
| send_internal_notice | 27 | batch-add |
| cc | 5 | batch-add |
| send_email | 11 | batch-add |
| delay | 12 | **node add** (batch-add 不支持) |
| code | 14 | **node add** (batch-add 不支持) |

## 已知限制

| 限制 | 说明 |
|------|------|
| systemField/nowTime 在 update_record 字段值 | valueRef 翻译失败，需 UI 手动设 |
| schedule + get_multiple + filter | 此组合间歇 500 |
| notice 收件人 kind=role | CLI 不支持 role 解析，用 kind=field 或 UI 手动 |
| delay node add 含 phantom | node add 产生一对节点，需清理或 UI 手动删 |
| code 节点配置 | addNode 后需 saveNode 配置代码内容，CLI 支持有限 |
