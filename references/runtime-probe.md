# Runtime Probe Protocol — hhr-plan ↔ hap-bridge 集成

> 当预计算 manifest/context 不可用、不完整、或结果可疑时，降级到 hap-bridge 实时查询。
> hap-bridge CLI: `python3 ~/.claude/mcp-servers/hap-bridge/cli.py`

## 降级触发条件

满足任一条件时，从 manifest 模式切换到 runtime probe 模式：

| 条件 | 信号 |
|------|------|
| manifest 缺失 | `business-flow-manifest.json` 文件不存在 |
| manifest 过期 | `generated_at` 超过 30 天 或 项目有新提取 |
| manifest 空结果 | 查 manifest 返回 0 条匹配工作流，但用户坚称流程存在 |
| 上下文不完整 | `project_context.json` 缺失 或 project-snapshot.md 不存在 |
| 用户质疑 | "manifest 里怎么没有？""这个数据是准的吗？" |
| 主动要求 | "直接查一下线上""别用缓存的" |

## 数据层面降级：manifest → hap-bridge MCP 代理

hhr-plan 通过 hap-bridge 的 MCP stdio 服务器（已注册在 `~/.claude/mcp.json`）直接调用 41 个 HAP 工具。

### 工作表查询

| 需要 | manifest 字段 | hap-bridge MCP 工具 |
|------|-------------|-------------------|
| 所有工作表列表 | `tables` keys | `get_app_worksheets_list` — `responseFormat: "md"` |
| 工作表字段结构 | `project_context.json` > worksheets | `get_worksheet_structure` — `worksheet_id` |
| 工作表记录数 | — | `get_record_list` — `worksheet_id`, `limit: 1` (看 total) |

### 工作流查询

| 需要 | manifest 字段 | hap-bridge 替代 |
|------|-------------|-----------------|
| 某表的所有工作流 | `tables[table_name]` | `get_workflow_list` (MCP 工具，需应用上下文) |
| 工作流节点链路 | `node_configs.json` | `cli.py wf-nodes <process_id>` |
| 工作流完整配置 | `dependency_graph.json` | `cli.py wf-config <process_id>` |
| 工作流读写清单 | `tables[].r / .w` | `cli.py wf-config <pid>` → 解析 nodes 中的 query/crud 节点 |

### 记录查询

| 需要 | hap-bridge MCP 工具 |
|------|-------------------|
| 查某表记录 | `get_record_list` — `worksheet_id`, `limit`, `filter` |
| 单条记录详情 | `get_record_details` — `worksheet_id`, `row_id` |
| 记录操作日志 | `get_record_logs` — `worksheet_id`, `row_id` |
| 透视汇总 | `get_record_pivot_data` — `worksheet_id` |

## Mode C 降级诊断流

当 manifest 不可用时，按以下顺序执行：

```
Step 0: 术语映射
  → 无 aliases.json? → get_app_worksheets_list (responseFormat: md) → 关键词模糊搜索

Step 1: 工作流定位
  → 无 manifest? → get_workflow_list → 按名称匹配 → 找到 process_id
  → 确认: cli.py wf-info <pid>

Step 2: 节点链路加载
  → 无 node_configs.json? → cli.py wf-nodes <pid>
  → 需要节点细节 → cli.py wf-config <pid>

Step 3: 运行时验证
  → 查记录确认数据是否存在: get_record_list (查涉事表)
  → 查日志确认工作流是否触发: get_record_logs (查触发源表)
  → 查审批状态: get_approval_list_by_row

Step 4: 根因推断
  → 同上（Mode C 的根因表），但证据来自实时查询而非预计算数据
```

### Mode C 诊断命令速查

```bash
# 定位涉事工作表
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_app_worksheets_list '{"responseFormat":"md"}'

# 定位工作表结构
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_worksheet_structure '{"worksheet_id":"xxx"}'

# 定位工作流（需要一个已加载应用的上下文，通常通过 get_app_info）
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_workflow_list '{}'

# 查看工作流节点
python3 ~/.claude/mcp-servers/hap-bridge/cli.py wf-nodes "<process_id>"

# 查记录确认数据是否存在
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_record_list '{"worksheet_id":"xxx","limit":5}'

# 查审批链
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_approval_list_by_row '{"worksheet_id":"xxx","row_id":"xxx"}'
```

## Mode D 降级审计流

当 manifest 不完整时，逐表走实时查询：

```
1. get_app_worksheets_list → 全量工作表列表
2. 逐表（或抽样关键表）→ get_worksheet_structure → 检查字段命名、类型、关联方向
3. 逐表 → get_workflow_list → 检查触发器类型、审批配置
4. 逐工作流 → cli.py wf-nodes <pid> → 检查查询节点 onEmpty、子流程 execMode
5. 抽查记录 → get_record_list → 检查默认值、拥有者字段
```

**性能约束**: 全量表扫描不可行（132 表 × N 工作流），按以下优先级抽样：
- Hub 表优先（`project_context.json` > `hub_tables` 或从字段关联密度推断）
- 高频写入表（manifest `write_index` 中 refcount 最高的）
- 用户指定的模块/表

## 混合模式：最佳实践

manifest 和 runtime probe 互补使用：

| 场景 | 使用 |
|------|------|
| 查"有哪些工作流、各自读写什么" | manifest（快，一次性） |
| 查"这个工作流现在是什么状态" | runtime probe（实时） |
| 查"这个字段当前值是什么" | runtime probe（只有线上有） |
| 查"这个流程最近有没有触发过" | runtime probe → get_record_logs |
| 验证"manifest 里说的写入目标对不对" | runtime probe → wf-config 对比 |
| manifest 说"写入<表A>"但表A没记录 | runtime probe 双重确认 |

## 认证要求

| 操作层 | 认证方式 | 就绪条件 |
|--------|---------|---------|
| MCP 代理 (数据操作) | HAP-Appkey + HAP-Sign (URL内嵌) | 始终可用 |
| CLI wf-* (工作流) | Chrome cookies (md_pss_id) | Chrome 登录 work.jijiansmart.com |
| CLI wf-* --chrome (CSRF写操作) | Chrome AppleScript | Chrome 运行中 + 页面打开 |

```bash
# 验证两层的认证状态
python3 ~/.claude/mcp-servers/hap-bridge/cli.py call get_time '{}'  # MCP层
python3 ~/.claude/mcp-servers/hap-bridge/cli.py auth-check          # 工作流层
```
