# 验证通过的节点 DSL 格式

> 来源：2026-07-05 至 2026-07-22 的本地回归与沙箱实机验证。
> 16 种节点类型已通过可发布、可执行验证；delay / code 仅验证了部分底层能力，
> 当前执行器仍不能把它们持久化为可发布节点。

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
    "fields": [
      {"fieldId": "<字段ID>", "value": "<值>"}
    ]
  }
}
```

纯 literal 新增不设置 `target`/`selectNodeId`；只有字段值实际引用上游节点时才提供
`target.node`。实机验证表明，literal 新增错误绑定 trigger 会导致 publish
`warningType=103`。

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
            "approvers": [
              {"kind": "field", "node": "approval_start", "fieldId": "ownerid"}
            ],
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
> ⚠️ 审批人不能直接引用外层 `triggerUser`；使用
> `{"kind":"field","node":"approval_start","fieldId":"ownerid"}` 或其他
> approval_start 可见字段。
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

> 以下两种节点类型不支持 batch-add。`node add` 或测试接口只能验证部分能力，
> 当前都不能由执行器创建为可发布、可执行节点。

### delay（延时等待）

```bash
hap workflow node add PID --type 12 --name "延时等待" --after UPSTREAM_NODE_ID
```

平台配置字段：
- `executeTimeType`: 0=固定时长, 1=截止时间
- `number`: 时长数值
- `unit`: 1=分钟, 2=小时, 3=天

> ⚠️ 实机 `node add` 只创建一个节点，没有 phantom。
> ⚠️ 使用 `number` 或 `executeTime` 保存后，时长都被平台重置为 0；节点保持
> `isException=true`，不能发布。因此当前只算结构创建通过，不算执行能力通过。
> ⚠️ batch-add 仍由 `_normalize_v3_node` 显式拒绝。

### code（代码块）

```bash
hap workflow node add PID --type 14 --name "代码块" --after UPSTREAM_NODE_ID
```

代码测试接口：
- `code`: JS/Python 代码字符串
- `language`: "javascript" (默认) 或 "python"

> ⚠️ `test-code` 执行 `return { result: 2 };` 成功并返回 `result=2`，证明代码引擎可用。
> ⚠️ 节点保存连续两次返回 500（包括补充 `actionId/version` 的尝试），不能持久化为
> 可发布节点。因此当前只算引擎测试通过，不算节点执行能力通过。
> ⚠️ batch-add 仍由 `_normalize_v3_node` 显式拒绝。

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
      {"fieldId": "<字段ID>", "type": 2, "name": "备注", "permission": "editable"}
    ],
    "submitText": "提交"
  }
}
```

> ⚠️ fill_in 只能放在 approval_block 内部 nodes 中
> ⚠️ 审批内层不需要显式声明 approval_start 节点（隐式存在）
> ⚠️ 创建审批块前必须先把触发节点绑定到实体工作表；空 trigger 的 `appId` 为空，
> 平台会静默丢弃填写表单字段。
> ⚠️ 执行合约必须同时提供 `fieldId`、数值字段 `type`、`name` 和
> `permission`；转换器会生成平台要求的 `id + type + name + property` 完整表单项。
> 只发送 `fieldId` 或 `controlId` 时平台会返回成功但静默丢弃填写字段。
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

> ⚠️ 验收应检查节点顶层 `sendContent`。正常的已发布通知节点中
> `flowNodeMap.106.content` 可以为空，不能据此判定通知内容丢失。

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
| delay | 12 | node add 仅建结构；配置不能持久化，当前不可发布 |
| code | 14 | test-code 可运行；节点保存 500，当前不可发布 |

## 已知限制

| 限制 | 说明 |
|------|------|
| systemField/nowTime 在 update_record 字段值 | valueRef 翻译失败，需 UI 手动设 |
| schedule + get_multiple + filter | 此组合间歇 500 |
| notice 收件人 kind=role | CLI 不支持 role 解析，用 kind=field 或 UI 手动 |
| delay 节点配置 | node add 成功，但时长保存后归零且节点异常；当前只能建结构 |
| code 节点配置 | test-code 可运行，但节点 save 连续 500；当前不能持久化 |
