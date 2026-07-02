# hap-cli 能力参考

> 明道云官方 CLI (v0.8.19), pip install hap-cli

## 安装 & 登录

```bash
pip install hap-cli           # 或 pipx install hap-cli
hap auth login https://work.jijiansmart.com   # 私有部署
hap auth login mingdao         # SaaS
hap app select APP_ID          # 设置默认应用
```

## 已验证完整可用的能力

### 工作流生命周期

| 操作 | 命令 |
|------|------|
| 创建工作流 | `hap workflow create -c ORG_ID -n NAME -a APP_ID --type worksheet` |
| 删除工作流 | `hap workflow delete PID` |
| 列出工作流 | `hap workflow list` |
| 查看结构 | `hap --json workflow structure PID` |
| 发布 | `hap workflow publish PID` |

### 触发器

| 操作 | 命令 |
|------|------|
| 绑定工作表 | `hap workflow node batch-add PID --trigger-worksheet WS_ID --trigger-event create --nodes '[]'` |

### 节点 (batch-add 稳定可用)

| nodeType | 说明 | typeId |
|----------|------|--------|
| add_record | 新增记录 | 6 |
| update_record | 更新记录 | 6 |
| send_internal_notice | 站内通知 | 27 |
| compute | 运算 | 9 |
| branch | 分支 | 1 |
| fill_in | 填写 | 3 |
| approval_block | 审批 | 26 |
| get_multiple | 获取多条 | 13 |
| rollup | 汇总 | 9 |
| sub_process | 子流程 | 16 |

### 节点顺序链接

```bash
# 方式: node add --after (简单类型稳定)
hap workflow node add PID --type 27 --name "通知" --after PREV_NODE_ID
hap workflow node add PID --type 12 --name "延时" --after PREV_NODE_ID
```

### 节点配置 (node save)

node save 需要发送 node get 返回的**完整 JSON**, 不能只发送 subset。

**typeId=6 add_record 完整格式**:
```json
{
  "name": "新增记录", "typeId": 6, "actionId": "1",
  "appId": "WS_ID", "appType": 1, "appTypeName": "工作表",
  "appName": "工作表名",
  "selectNodeId": "", "selectNodeName": "",
  "selectNodeObj": {"nodeId":"","nodeName":"","appId":"","appName":"",
    "appType":-1,"appTypeName":"","nodeTypeId":-1,"countersign":false,"actionId":""},
  "fields": [{
    "fieldId": "control_id", "fieldName": "字段名",
    "value": "配置值", "type": 2,
    "sourceType": 0, "fieldValueType": "2",
    "fieldValue": "", "dataSource": "",
    "nodeAppType": 1, "nodeId": "", "nodeAppId": "",
    "fieldValueId": "", "fieldValueName": "",
    "isClear": false, "isSourceApp": false,
    "alias": "", "addType": 0, "allowAddOptions": false
  }],
  "controls": [...], "formulaMap": {},
  "flowNodeList": [], "appList": [...], "batchNodes": []
}
```

**typeId=7 get_single 完整格式**:
```json
{
  "name": "查询", "typeId": 7, "actionId": "406",
  "appId": "WS_ID", "appType": 1, "appTypeName": "工作表",
  "appName": "工作表名",
  "findFields": [], "findField": "", "isAdd": false,
  "executeType": 2, "selectNodeId": "", "selectNodeName": "",
  "controls": [...], "filters": [], "conditions": [], "sorts": [],
  "addControls": [...], "formulaMap": {}, "appList": [...],
  "random": false, "relation": false
}
```

**typeId=0 trigger 完整格式**:
```json
{
  "name": "工作表事件触发", "typeId": 0,
  "appId": "WS_ID", "appType": 1, "appTypeName": "工作表",
  "appName": "工作表名", "triggerId": "1",
  "assignFieldNames": [], "assignFieldName": "",
  "selectNodeId": "NODE_ID", "selectNodeName": "工作表事件触发",
  "isException": false,
  "operateCondition": [...], "assignFieldIds": [],
  "controls": [...], "filedControls": [...], "appList": [...]
}
```

### node get 返回的 fields 详细格式

```json
{
  "fieldId": "control_id",
  "fieldName": "字段名",
  "sourceControlType": 0,
  "desc": "",
  "type": 2,              // 字段类型编号
  "enumDefault": 1,
  "require": false,
  "hide": null,
  "nodeAppType": 1,
  "nodeId": "source_node_id",
  "nodeAppId": "source_app_id",
  "fieldValueId": "target_control_id",
  "fieldValueType": "2",
  "color": "",
  "fieldValue": "",
  "fieldValueDefault": null,
  "dataSource": "",
  "nodeName": "源节点名",
  "fieldValueName": "源字段名",
  "nodeTypeId": 6,
  "nodeActionId": "2",
  "sourceType": 0,         // 0=固定值, 1=节点值引用, 2=流程参数
  "isClear": false,
  "isSourceApp": false,
  "alias": "",
  "addType": 0,
  "allowAddOptions": false
}
```

### 不可用的类型

| nodeType | 现象 | 原因 |
|----------|------|------|
| get_single | batch-add 500 | 服务端不支持此类型通过 batch-add 创建 |
| get_relation | batch-add 500 | 同上 |

> 解决方案: 先用 batch-add 创建 get_multiple 节点, 然后用 node save 发完整 JSON 配置为 get_single 模式。
