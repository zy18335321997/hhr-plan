# 通过 hap CLI 创建工作流 — 完整验证指南

## 前置条件

```bash
pip install hap-cli
hap auth login
```

## 核心命令

```bash
# 创建工作流外壳
hap workflow create -c <orgId> -n "名称" -a <appId> --type <触发类型> -d "描述"

# 一次性配置触发+所有节点
hap workflow node batch-add <pid> [触发配置] --trigger-alias trigger --nodes '<JSON>'

# 发布
hap workflow publish <pid>
```

## 已验证稳定的触发方式

### 按钮触发（推荐）

```bash
# 1. 创建按钮 + 影子工作流
hap worksheet create-custom-action <wsId> \
  --app-id <appId> \
  --action-spec '{"name":"按钮名","type":"triggerWorkflow"}'
# 返回: {actionId, processId, triggerNodeId}

# 2. 配置节点
hap workflow node batch-add <processId> \
  --trigger-alias trigger --nodes '[...]'
```

### 工作表事件触发

```bash
hap workflow create ... --type worksheet_event

hap workflow node batch-add <pid> \
  --trigger-worksheet <wsId> \
  --trigger-event create \
  --trigger-alias trigger --nodes '[...]'
```

### 定时触发

```bash
hap workflow create ... --type schedule

hap workflow node batch-add <pid> \
  --trigger-schedule '{"repeat":"day","interval":1,"start_time":"00:00"}' \
  --trigger-alias trigger --nodes '[...]'
```

> ⚠️ get_multiple 带 filter 时 saveNode 间歇 500，建议去掉 filter，在 UI 手动补。

## 支持的全部节点类型（18 种）

| nodeType | typeId | 说明 | 创建方式 | 验证状态 |
|----------|--------|------|---------|:--:|
| `get_relation` | 6 | 获取关联记录 | batch-add | ✅ |
| `get_single` | 7 | 查询单条 | batch-add | ✅ |
| `get_multiple` | 13 | 查询多条 | batch-add | ✅ |
| `update_record` | 6 | 更新记录 | batch-add | ✅ |
| `create_record` | 6 | 新增记录 | batch-add | ✅ |
| `delete_record` | 6 | 删除记录 | batch-add | ✅ |
| `branch` | 1 | 条件分支 | batch-add | ✅ |
| `approval_block` | 26 | 审批块 | batch-add | ✅ |
| `approve` | 4 | 审批步骤(内层) | batch-add | ✅ |
| `fill_in` | 3 | 审批填写(内层) | batch-add | ✅ |
| `sub_process` | 16 | 子流程 | batch-add | ✅ |
| `rollup` | 9 | 汇总统计 | batch-add | ✅ |
| `compute` | 9 | 数值/日期计算 | batch-add | ✅ |
| `send_internal_notice` | 27 | 站内通知 | batch-add | ✅ |
| `cc` | 5 | 记录详情通知 | batch-add | ✅ |
| `send_email` | 11 | 邮件通知 | batch-add | ✅ |
| `delay` | 12 | 延时等待 | **node add** | ✅ |
| `code` | 14 | 代码块 | **node add** | ✅ |

> ⚠️ `delay` 和 `code` 源码显式拒绝 batch-add，必须用 `node add --after` + `node save` 分步创建。

## 节点 DSL 格式

### get_relation

```json
{"nodeAlias":"get_book","nodeType":"get_relation","name":"获取关联图书",
 "config":{"worksheet":"<源表ID>","target":{"node":"<上游alias>"},
           "fields":[{"fieldId":"<关联字段ID>"}]}}
```

### get_single

```json
{"nodeAlias":"find_book","nodeType":"get_single","name":"查找图书",
 "config":{"worksheet":"<目标表ID>","target":{"node":"<上游alias>"},
           "ifEmpty":"continue"}}
```

**带 filter：**

```json
"filter":{"logic":"and","items":[
  {"left":{"fieldId":"<字段ID>","node":"<本节点alias>","_filedTypeId":9},
   "op":"eq","right":{"kind":"literal","value":"<optionKey>"}}
]}
```

### get_multiple

```json
{"nodeAlias":"find","nodeType":"get_multiple","name":"查询","config":{"worksheet":"<wsId>","ifEmpty":"continue"}}
```

### rollup

```json
{"nodeAlias":"count","nodeType":"rollup","name":"统计",
 "config":{"target":{"node":"<上游alias>"},
           "aggregations":[{"alias":"total","fieldId":"rowid","func":"COUNT"}]}}
```

### branch

**条件分支：**

```json
{"nodeAlias":"check","nodeType":"branch","name":"判断",
 "config":{"target":{"node":"<数据源alias>"},"mode":"firstMatch","paths":[
   {"name":"条件A","condition":{"left":{"fieldId":"<字段ID>","node":"<数据源alias>","_filedTypeId":<类型>},
             "op":"eq","right":{"kind":"literal","value":"<值>"}},
    "nodes":[...]},
   {"name":"默认","nodes":[]}
 ]}}
```

**审批结果分支：**

```json
{"nodeAlias":"check","nodeType":"branch","name":"审批结果",
 "config":{"resultFlow":true,"paths":[
   {"name":"通过","result_type":"pass","nodes":[...]},
   {"name":"否决","result_type":"reject","nodes":[...]}
 ]}}
```

> ⚠️ 分支 condition 的 `left.node` 填**数据源节点 alias**，不是分支自身。

### approval_block

```json
{"nodeAlias":"approval","nodeType":"approval_block","name":"审批",
 "config":{"target":{"node":"<记录alias>"},
   "initiators":[{"kind":"triggerUser"}],
   "process":{"mode":"create","name":"审批流程","nodes":[
     {"nodeAlias":"step","nodeType":"approve","name":"审批步骤",
      "config":{"target":{"node":"approval_start"},"approvers":[{"kind":"triggerUser"}],"allowReject":true}}
   ]}}}
```

### sub_process

```json
{"nodeAlias":"sp","nodeType":"sub_process","name":"子流程",
 "config":{"target":{"node":"<数据源alias>"},
   "executionMode":"sequential_each_continue_on_error",
   "process":{"mode":"create","name":"内层名称","nodes":[...]}}}
```

> 子流程内层用 `sub_trigger` 引用当前遍历的记录。

### update_record

```json
{"nodeAlias":"update","nodeType":"update_record","name":"更新",
 "config":{"worksheet":"<wsId>","target":{"node":"<记录alias>"},
           "fields":[{"fieldId":"<字段ID>","value":"<值>"}]}}
```

### send_internal_notice

```json
{"nodeAlias":"notify","nodeType":"send_internal_notice","name":"通知",
 "config":{"accounts":[{"kind":"field","node":"<记录alias>","fieldId":"<人员字段ID>"}],
           "content":"通知文本内容"}}
```

### compute

```json
{"nodeAlias":"calc","nodeType":"compute","name":"计算",
 "config":{"computeType":"dateDiff",
           "startTime":{"kind":"systemField","fieldId":"nowTime"},
           "endTime":{"kind":"field","node":"<上游alias>","fieldId":"<日期字段ID>"},
           "outputUnit":"d"}}
```

> 三种 computeType: `number`（数值公式）、`dateDiff`（日期差值，unit: Y/M/d/h/m）、`dateOffset`（日期偏移，offsetExpression: `"+30d"`）

### cc

```json
{"nodeAlias":"notify_cc","nodeType":"cc","name":"抄送",
 "config":{"target":{"node":"<记录alias>"},
           "accounts":[{"kind":"field","node":"<记录alias>","fieldId":"<人员字段ID>"}],
           "showRecordTitle":true}}
```

> ⚠️ cc 必须有 target 记录，发送多条时包裹在 sub_process 内

### send_email

```json
{"nodeAlias":"notify_email","nodeType":"send_email","name":"邮件",
 "config":{"accounts":[{"kind":"triggerUser"}],
           "subject":"邮件主题","body":"邮件正文","bodyType":"html"}}
```

### fill_in

```json
{"nodeAlias":"fill","nodeType":"fill_in","name":"补充信息",
 "config":{"accounts":[{"kind":"triggerUser"}],
           "formProperties":[{"fieldId":"<字段ID>","name":"备注","required":false,"editable":true}]}}
```

> ⚠️ fill_in 只能放在 approval_block 内部 nodes 中；审批内层**不需要**显式声明 approval_start 节点（隐式存在）

### delay

```bash
hap workflow node add <pid> --type 12 --name "延时" --after <上游nodeId>
```

> ⚠️ 不支持 batch-add；node add 会产生 phantom 节点

### code

```bash
hap workflow node add <pid> --type 14 --name "代码" --after <上游nodeId>
```

> ⚠️ 不支持 batch-add；创建后需 saveNode 配置代码内容

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

## 关键规则

- **所有 ID 用真实 controlId/worksheetId**，不编造
- **选项字段 value 填 key**（UUID），不填文字
- **`batch-add` 一次性创建节点骨架**，不用 `node add` + `save-action` 分步
- **`batch-add` 后必须 `save-action`** — action 节点的 fields 被 saveNode 静默丢弃
- **分支 path 的 nodes 必须内联完整节点定义**，不能用 alias 字符串引用
- **分支 condition 的 `left.node` 填数据源 alias**，不填分支自身
- **审批内层用 `approval_start`**，approve 的 approvers 只能引用 approval_start 作用域
- **子流程内层用 `sub_trigger`**
- **发布顺序**: inner approval → inner subprocess → main workflow
- **get_single 可不设 filter**，靠 `target` 引用上游节点获取记录

## save_actions.py 补救

batch-add 创建节点骨架后，用脚本并行保存所有配置：

```bash
python3 ~/.claude/skills/hap-flow-exec/scripts/save_actions.py \
  --contract execution_contract.json \
  --batch-output '<batch-add 的 JSON 输出>'
```

脚本自动处理：
- update_record / create_record / delete_record 的字段配置
- get_single / get_multiple 的 filter 配置（用 `filters` 格式，避开 bug #036489）
- 递归遍历 branch paths / approval_block 内层 / sub_process 内层
- ThreadPool 并行，全部节点 ~0.2s

> 手动用 CLI 也行：`-a 1`=AddRecord, `-a 2`=EditRecord, `-a 3`=DeleteRecord
> type: 2=Text, 9=SingleSelect, 11=Dropdown, 15=Date

## get_multiple filter 格式

必须用 `filters` 格式，不能用 `operateCondition`（服务器 bug #036489 静默丢弃）。

```json
{
  "filters": [{
    "conditions": [[
      {"filedId": "<fieldId>", "filedTypeId": 9, "conditionId": "9",
       "conditionValues": [{"value": "<optionKey>"}], "sourceType": 0},
      {"filedId": "<dateFieldId>", "filedTypeId": 15, "conditionId": "17",
       "conditionValues": [{"controlId": "nowTime", "nodeId": "5d39140d381d42d20db0c4da",
                             "appType": 100, "nodeType": 100}], "sourceType": 0}
    ]],
    "spliceType": 2
  }]
}
```

> `save_actions.py` 自动翻译，设计合约里正常写 `{"kind": "systemField", "fieldId": "nowTime"}` 即可

### conditionId 操作符映射

**通用操作符**（所有字段类型）：

| op | condId | 含义 |
|----|--------|------|
| eq | 9 | 等于 |
| ne | 10 | 不等于 |
| in | 1 | 是其中一个 |
| not_in | 2 | 不是任何一个 |
| empty | 8 | 为空 |
| not_empty | 3 | 不为空 |
| contains | 15 | 包含 |
| checked | 29 | 选中/是 |
| unchecked | 30 | 不选中/否 |

**Date/DateTime 专用**（`filedTypeId`=15/16，不用通用数值 ID）：

| op | condId | 含义 |
|----|--------|------|
| lt | **17** | 早于 |
| lte | **42** | 早于等于 |
| gt | **18** | 晚于 |
| gte | **40** | 晚于等于 |

### systemField/nowTime 在 filter 中的写法

`kind: systemField` / `fieldId: nowTime` → wire 格式为：

```json
{"controlId": "nowTime", "nodeId": "5d39140d381d42d20db0c4da",
 "appType": 100, "nodeType": 100}
```

> 系统节点 ID `5d39140d381d42d20db0c4da` 是平台固定值，所有项目通用。

## 已知限制

| 限制 | 说明 | 绕行 |
|------|------|------|
| `systemField/nowTime` 在 update_record 字段值 | valueRef 翻译失败 | UI 手动设触发时间 |
| `wfstatus` (系统流程状态) 无法写入 | 平台只读系统字段 | 用自定义单选字段代替 |
| get_multiple filter 不能用 operateCondition | 服务器 bug #036489 | 用 `filters` 格式，`save_actions.py` 自动处理 |
| delay node add 含 phantom | 每次产生一对节点，需清理 | 事后 UI 删 phantom |
| notice 收件人 kind=role | CLI 不支持 role 解析 | 用 kind=field 或 UI 手动 |
