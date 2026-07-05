# implementation-notes: verify-platform-py

## 目标

创建 `scripts/verify-platform.py`，用确定性 bash/Python 控制流替代 Agent 2 中约 60% 的机械检查项。

## 设计决策

### 1. 输入格式
接受两种输入：
- `--lock-file execution_lock.json` — 从 hhr-plan 设计方案中提取工作流节点链
- `--nodes nodes.json` — 直接的节点链 JSON（更灵活）

nodes.json 格式：
```json
{
  "workflows": [
    {
      "name": "工作流名",
      "worksheet": "所在工作表",
      "trigger": {"typeId": 8, "actionId": null},
      "nodes": [
        {"typeId": 7, "actionId": 406, "name": "节点名", "config": {...}},
        ...
      ]
    }
  ],
  "project": "项目名"
}
```

### 2. 可脚本化的检查项 (从 Agent 2 中提取)

| 检查项 | 实现方式 |
|--------|---------|
| 节点 typeId 有效性 | 对照 39 个有效 typeId 的集合 |
| 弃用节点 (typeId=4) | 直接匹配，fail |
| actionId 有效性 (对有子模式的节点) | 对照 typeId→valid_actionIds 的映射表 |
| 批量上限 | parse config 中的数值参数，对比已知上限 |
| 获取模式 (直接 vs 动态) | parse config 字段，字符串匹配 |
| 界面推送重复检测 | 遍历节点链，统计 typeId=17 的数量 |
| 节点总数 | count(nodes) |
| 嵌套深度 | 递归解析子流程引用 |
| 拓扑循环检测 | 邻接表 + DFS |

### 3. 不可脚本化的检查项 (留给 Agent 2)
- 数据链路语义正确性 (节点间数据传递是否合法)
- 无数据策略是否符合公理 5 (需要语义判断)
- 分支覆盖完备性 (需要理解"所有可能值")
- 代码块内容能否完成任务
- API 响应格式能否被后续节点正确解析

### 4. 累积式失败 (RepoPrompt CE 模式)
- 使用 `failures` 列表，不提前退出
- 所有检查跑完后输出汇总 JSON
- exit code 0 = pass, exit code 1 = fail

### 5. 输出格式
与 Agent 2 的输出格式兼容，但只包含机械检查的结果。语义检查项标记为 "delegated"。
