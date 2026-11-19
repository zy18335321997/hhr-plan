# Tool Dispatch Card — 工具调度速查

> hap-bridge CLI: `HAP=~/.claude/mcp-servers/hap-bridge/cli.py`
> 项目数据: `DATA=~/Documents/workflow-output`
> Skill 脚本: `SKILL=~/.claude/skills/hhr-plan/scripts`

## 核心原则

```
默认路径 = 本地数据。远程调用 = 用户明确要求或本地不存在时才触发。

├─ 本地数据始终优先（search.py 索引 + project_context.json + node_configs.json）
├─ 需要远程时明确告知用户"正在调 XX"，不静默降级
├─ 远程结果自动缓存到本地，下次本地命中
└─ 远程失败不阻塞——汇报现状 + 已获取的数据，继续回答
```

## 快速定位流程

```
用户: "查XX工作流" / "XX表有哪些流" / "XX字段在哪"

  第 1 轮 — 4 条命令并行（全部本地，秒返）:
  ┌─ search.py "XX" --type workflow -p <项目名>         → PID + 触发表 + 节点数
  ├─ search.py "XX" --exact-name -p <项目名>              → 精确匹配
  ├─ rebuild_graph.py <项目名> --lifecycle <表名>          → 只读现有图，查创建者/更新者/消费者
  └─ search.py "表名" --writes-to -p <项目名>              → 上游 + 下游
        --reads-from -p <项目名>

  第 2 轮 — 需要节点详情时:
  ┌─ wf_fetch.py <项目名> <PID>          → 本地缓存优先，取不到自动调远程
  │   源码: ~/.claude/skills/hhr-plan/scripts/wf_fetch.py
  │   行为: ①查本地 node_configs.json → ②调 cli.py wf-nodes → ③调 MCP → ④写入缓存
  │   用户说"刷新"或"拉最新"时加 --force-remote
  │
  └─ 需要线上实时数据时（审批状态/记录日志/当前值）:
      └─ cli.py call get_approval_list_by_row / get_record_list / get_record_logs
         → 这些只有线上有，缓存不了，每次都是实时请求
```

## 搜索层（本地 FTS5 索引）

| 需要 | 命令 |
|------|------|
| 搜工作流（关键词） | `python3 $SKILL/search.py "关键词" --type workflow -p <项目名>` |
| 精确名 | `python3 $SKILL/search.py "工作流名" --exact-name -p <项目名>` |
| 已知 PID | `python3 $SKILL/search.py "PID" --pid -p <项目名>` |
| 谁写这张表 | `python3 $SKILL/search.py "表名" --writes-to -p <项目名>` |
| 谁读这张表 | `python3 $SKILL/search.py "表名" --reads-from -p <项目名>` |
| 字段在哪 | `python3 $SKILL/search.py "字段名" --field-search -p <项目名>` |

> 搜索全部走本地索引，秒返。❌ 禁止 grep 翻 JSON。

## 表→工作流反向索引（本地，秒返）

| 需要 | 命令 |
|------|------|
| 查某表有哪些工作流 | `python3 $SKILL/sheet_workflows.py <项目名> <表名>` |
| 列出所有有工作流的表 | `python3 $SKILL/sheet_workflows.py <项目名> --list` |
| 重建反向索引 | `python3 $SKILL/sheet_workflows.py <项目名> --rebuild` |

> **比 search.py 更准**：search.py 按名称搜，sheet_workflows.py 直接从缓存的 T0 节点提取触发表，覆盖全部已拉取过节点的工作流。
> 索引由 `wf_fetch.py` 自动维护，每次拉取工作流节点时同步更新。

## 依赖层（本地计算）

| 需要 | 命令 |
|------|------|
| 实体生命周期 | `python3 $SKILL/rebuild_graph.py <项目名> --lifecycle <表名>`（不重建、不写文件） |
| 重建索引+图 | `python3 $SKILL/auto_sync.py <项目名>`（只同步 stale 项目） |

## 节点获取（wf_fetch.py 一站式）

```
python3 $SKILL/wf_fetch.py <项目名> <PID或工作流名> [--url <平台URL>]

优先级:
  ① 本地 node_configs.json 命中 → 直接返回（离线秒返）
  ② 平台路由内部 API（<项目>/platform.json 绑定或 --url 指定平台，
     且输入为 24 位 hex PID）→ 直接调该平台 /api/workflow/flowNode/get
     → 自动写缓存 + 写绑定（source=platform_internal）
  ③ 无平台绑定时 → cli.py wf-nodes（legacy，内部 BASE 写死 work.example.com）
  ④ 前两者不可用 → MCP get_workflow_details 兜底（名称+入参，无节点）

`get_workflow_details` 不是节点配置。完整节点 config 用 `extract-project.py` 的 MCP `get_workflow_structure`（按 tools/list 的 inputSchema 传 workflow_id 或 process_id；approval_block / sub_process 用 config.process.processId 递归）。工具不存在或结果不完整时才回退 Chrome `getNodeDetail`。
  ⑤ --force-remote → 跳过本地缓存，强制从远程拉取并更新缓存
```

## 平台路由（多明道云私有部署）

hhr-plan 原生支持任意明道云私有部署：用户给 URL，自动推导 origin/域名、
读该域 Chrome Cookie（md_pss_id → Authorization）、调该平台内部 API。
不写死任何域名，按用户提供的输入路由。

| 需要 | 命令 |
|------|------|
| 解析平台 URL | `python3 $SKILL/platform_router.py parse <平台URL>` |
| 探测可达性 | `python3 $SKILL/platform_router.py probe <平台URL> [--pid <PID>]` |
| 路由拉取节点 | `python3 $SKILL/wf_fetch.py <项目名> <PID> --url <平台URL>` |
| 复用绑定拉取 | `python3 $SKILL/wf_fetch.py <项目名> <PID>`（读 <项目>/platform.json） |

URL 形态: `http://<host>/app/<app_id>/workflow` 或
`http://<host>/workflowedit/<pid>`。首次建议用 `/app/<app_id>/workflow`
形态——workflowedit 形态没有 app_id，列表/count 接口无法路由。

工作流列表接口按序探测（各平台版本不一，首个"形状可识别"的胜出并缓存，
空列表 = 成功 = 应用没流）：

1. `GET /api/workflow/v1/process/listAll?relationId=<app_id>`
2. `POST /api/process/getProcessList {"appId","pageIndex":1,"pageSize":1000}`
3. `GET /api/workflow/v1/process/list?relationId=<app>&pageSize=500`

平台绑定 `<项目>/platform.json` 只记录 origin/domain/app_id/pid/source/saved_at，
不含 Cookie、Token 或 HAP 凭证。`--url` 优先于文件；路由成功才落盘，
失败不污染绑定（防错绑）。

## 线上实时数据（MCP，始终可用）

这些只有线上有当前值，每次都是实时请求：

| 需要 | 命令 |
|------|------|
| 审批链状态 | `python3 $HAP call get_approval_list_by_row '{"worksheet_id":"<wsid>","row_id":"<rowid>"}'` |
| 操作日志 | `python3 $HAP call get_record_logs '{"worksheet_id":"<wsid>","row_id":"<rowid>"}'` |
| 表中记录 | `python3 $HAP call get_record_list '{"worksheet_id":"<wsid>","limit":5}'` |
| 字段结构 | `python3 $HAP call get_worksheet_structure '{"worksheet_id":"<wsid>"}'` |
| 工作流节点配置 | `python3 $SKILL/extract-project.py <项目名> --mcp-url "$HAP_MCP_URL" --process-id <processId>`（`get_workflow_structure`；`get_workflow_details` 不含节点） |

## 工作流写操作（需要 Chrome 登录）

| 需要 | 命令 |
|------|------|
| 创建/删除/启停 | `python3 $HAP wf-create / wf-delete / wf-status` |
| 保存配置 | `python3 $HAP wf-save '<pid>' '<config>' --chrome` |

## 禁止

```
❌ grep/rg 翻 JSON 找 PID               → search.py（本地索引秒返）
❌ 逐步试错（搜→失败→换方法→失败…）    → 第 1 轮全量并行
❌ 远程失败自己判"Chrome 未登录"就跳过   → 明确告知，不静默降级
❌ 远程结果不缓存                        → wf_fetch.py 自动写本地
❌ 本地不需要调远程的时候调远程           → 默认本地，--force-remote 才刷新
```
