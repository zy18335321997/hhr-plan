# 验证通过的工作流创建流程

> 基于 hap-cli v0.8.19 + 直接 API 调用的完整验证链路

## 完整流程 (6 步)

```
Step 1: 创建工作流骨架
  → Step 2: 绑定工作表触发器
    → Step 3: 顺序添加节点链
      → Step 4: 配置数据节点字段 (save-action)
        → Step 5: 配置通知节点 (UI手动)
          → Step 6: 发布
```

## Step 1: 创建工作流

```bash
hap workflow create \
  -c ORG_ID \
  -n "工作流名称" \
  -a APP_ID \
  --type worksheet
```

返回 PID 和 triggerNodeId。

## Step 2: 绑定工作表触发器

```bash
hap workflow node batch-add PID \
  --trigger-worksheet WORKSHEET_ID \
  --trigger-event create \
  --nodes '[]'
```

> `--trigger-event` 选项: create, update, create_or_update, delete

## Step 3: 顺序添加节点链

```bash
# 获取 trigger node ID
TRIGGER=$(hap --json workflow structure PID | jq -r '.startEventId')

# add_record
N1=$(hap workflow node add PID --type 6 --name "新增记录" \
  --after $TRIGGER --action-id 1 --app-id WS_ID | jq -r '.addFlowNodes[0].id')

# update_record
N2=$(hap workflow node add PID --type 6 --name "更新记录" \
  --after $N1 --action-id 2 --app-id WS_ID | jq -r '.addFlowNodes[0].id')

# notice
N3=$(hap workflow node add PID --type 27 --name "通知" \
  --after $N2 | jq -r '.addFlowNodes[0].id')

# delay
N4=$(hap workflow node add PID --type 12 --name "延时" \
  --after $N3 | jq -r '.addFlowNodes[0].id')

# compute
N5=$(hap workflow node add PID --type 9 --name "计算" \
  --after $N4 --action-id 100 | jq -r '.addFlowNodes[0].id')
```

**已验证的节点类型** (`node add --after`):
- typeId=6 (add_record/update_record) — 需 `--action-id` + `--app-id`
- typeId=27 (notice)
- typeId=12 (delay)
- typeId=9 (compute) — 需 `--action-id`
- typeId=1 (branch)

## Step 4: 配置数据节点字段

```bash
# update_record: 必须传 -s (源节点ID)
hap workflow node save-action PID NODE_ID \
  -a 2 --app-id WS_ID -n "节点名称" -s TRIGGER_ID \
  -f '[
    {"fieldId":"FIELD_ID","type":15,"fieldValue":"UUID_KEY"},
    {"fieldId":"FIELD_ID","type":2,"fieldValue":"text value"}
  ]'

# add_record
hap workflow node save-action PID NODE_ID \
  -a 1 --app-id WS_ID -n "节点名称" \
  -f '[
    {"fieldId":"FIELD_ID","type":15,"fieldValue":"UUID_KEY"},
    {"fieldId":"FIELD_ID","type":2,"fieldValue":"text value"}
  ]'

# delete_record
hap workflow node save-action PID NODE_ID \
  -a 3 --app-id WS_ID -n "节点名称" -s TRIGGER_ID
```

**save-action 参数**:
- `-a`: 1=AddRecord, 2=EditRecord, 3=DeleteRecord
- `--app-id`: 目标工作表 ID
- `-s`: select-node-id (源数据节点, update/delete 必须)
- `-f`: JSON 数组 `[{"fieldId","type","fieldValue"}]`

## 关键发现

### 1. 下拉字段必须用 UUID key
```json
// 错误 ❌
{"fieldId":"xxx","type":15,"fieldValue":"离职"}

// 正确 ✅
{"fieldId":"xxx","type":15,"fieldValue":"4fc845ed-ab00-47c0-84f2-044245dc2b75"}
```

获取方式: `hap worksheet info WS_ID` 或 `get_worksheet_structure` (JSON) 找到 `options[].key`

### 2. save-action 不校验 fieldId 有效性
接受任何 fieldId 并返回 "saved", 但无效字段会被静默丢弃。必须从工作表结构中获取真实 fieldId。

### 3. batch-add vs node add --after
| 方法 | 优点 | 缺点 |
|------|------|------|
| batch-add | 一次调用创建多个节点 | 数据节点名称/appId 为空; 不保证顺序链 |
| node add --after | 正确设置名称/appId/顺序链 | 每个节点一次调用 |
| **推荐**: 触发器用 batch-add, 业务节点用 node add --after |

### 4. notice 节点 (typeId=27) 配置
`saveNode` API 对 notice 返回 500。收件人需在 UI 中手动配置。

### 5. saveNode 直接 API (高级)
对于需要完整 field config 的场景, 可绕过 CLI 直接调内部 API:
```python
config = {**blueprint, "processId": pid, "nodeId": nid, "name": "名称"}
config["fields"] = [...]
body = json.dumps(config).encode()
# flat format: 所有字段平铺在顶层 + processId + nodeId
req = urllib.request.Request(f"{BASE}/api/workflow/flowNode/saveNode",
    data=body, headers=hdrs, method="POST")
```

## 测试验证通过的工作流

**人员离职办理-hhrplan** (PID: `6a45f417f7ecf6d042af04bb`):
- 花名册 新增记录触发
- 更新离职信息 (update_record, 员工状态=离职 UUID key)
- 通知HR及部门负责人 (notice, 待UI配收件人)
- 新增离职记录 (add_record, 员工在位情况, 当前状态=已离职 UUID key)
