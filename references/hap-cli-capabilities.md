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

### 节点配置 (node save) — 已验证可用 ✅

**关键发现**: `saveNode` API 需要 **FLAT JSON 格式** (所有字段平铺, 不包裹在 `flowNode` 里), 且必须包含**完整蓝本** (controls/appList/selectNodeObj/formulaMap/flowNodeList 等支持数组)。

**调用方式**: 必须绕过 CLI, 直接调内部 API:
```python
import urllib.request, json
hdrs = auth.get_auth_headers()
hdrs["Content-Type"] = "application/json"
config = {**full_node_blueprint, "processId": pid, "nodeId": nid, "name": "新名称", ...}
body = json.dumps(config).encode()
req = urllib.request.Request(f"{BASE}/api/workflow/flowNode/saveNode", data=body, headers=hdrs, method="POST")
```

**完整流程**:
1. `batch-add` 创建节点壳 (获得 nodeId)
2. 从已有生产工作流 `node get` 获取同类型节点的完整 JSON 作蓝本
3. 修改蓝本中的 `name`/`appId`/`fields`/`controls` 等
4. 直接调 `saveNode` (flat format + 完整蓝本) 写入配置

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

### 不可用 (CLI) / 可通过直接 API 补救

| nodeType | CLI batch-add | 直接 saveNode API | 说明 |
|----------|:--:|:--:|------|
| get_single | 500 | **待验证** | 用 get_multiple 壳 + saveNode 改 actionId=406 |
| get_relation | 500 | **待验证** | 同上, 改 actionId=20 |
| node add --after (数据节点) | 500 | N/A | 数据节点(6/7)用 batch-add 创建壳, 再 saveNode 配置 |

### 已验证完整的 saveNode API 调用格式

```python
# WORKING: flat format with complete blueprint
config = copy.deepcopy(blueprint_from_real_node)
config["processId"] = pid
config["nodeId"] = node_id
config["name"] = "新名称"
config["appId"] = "target_ws_id"
config["appName"] = "target_ws_name"
config["fields"] = [{...}]  # from blueprint, with modified values
# MUST keep: controls, appList, selectNodeObj, formulaMap, flowNodeList

# FAILING: CLI wrapper or missing supporting arrays
# hap workflow node save ... --config '{...}'  → always 500
# sending fields without controls/appList → fields silently dropped
