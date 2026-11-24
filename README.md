# hhr-plan

明道云 APaaS 设计、诊断与审计 Skill。它用统一公理约束绿地设计、棕地改造、根因诊断和健康审计，并通过确定性脚本与独立 Agent 阻断不完整方案。

## 使用方式

```text
/hhr-plan 帮我从零设计一个采购审批模块
/hhr-plan 在现有项目里修改付款工作流
/hhr-plan 为什么付款金额不对
/hhr-plan 审计这个项目
```

入口会先区分轻量事实查询与全量任务，再显式路由：

- Mode A：绿地设计
- Mode B：棕地改造
- Mode C：诊断排查
- Mode D：健康审计

路由和加载顺序见 `SKILL.md`。公理、定理、详细门控和工具命令分别以
`system-prompt.md`、`references/theorems-and-protocols.md`、
`references/unified-design-spec.md` 和 `references/tool-dispatch.md` 为真源。

## 安装与健康检查

```bash
git clone https://github.com/zy18335321997/hhr-plan.git \
  ~/.claude/skills/hhr-plan
bash ~/.claude/skills/hhr-plan/scripts/doctor.sh
```

Python 脚本以 Python 3.10+ 为目标。实时平台查询可选依赖 hap-bridge。浏览器提取的可选依赖钉在 `pyproject.toml` 的 `live` extra（`browser_cookie3`、Playwright）：

```bash
pip install '.[live]'
```

Chrome / AppleScript 实时提取只在 macOS 上可用。节点类型以 `scripts/verify-platform.py` 的 `TYPE_NAMES` 为准；此映射修正后，已经落在 `~/Documents/workflow-output/` 的清单必须重新提取，旧 manifest 不能继续当字段级证据。

公开历史里曾经包含一条默认 HAP AppKey/Sign。当前树已删除该默认值，但旧提交里的凭证在你吊销并（可选）自行重写历史之前仍然可以恢复。本仓库不会代为轮换或改写历史。

## 安全提取项目

仓库不提供默认 MCP URL，也不保存 AppKey、Sign 或凭证化查询参数。非
`--skip-mcp` 模式必须使用以下任一方式：

```bash
python3 scripts/extract-project.py "<项目名>" \
  --mcp-url "https://your-host.example/mcp?<credentials>"
```

或：

```bash
HAP_MCP_URL="https://your-host.example/mcp?<credentials>" \
  python3 scripts/extract-project.py "<项目名>"
```

只使用本地浏览器提取物时：

```bash
python3 scripts/extract-project.py "<项目名>" \
  --skip-mcp \
  --pids-file "/absolute/path/to/pids.json" \
  --nodes-file "/absolute/path/to/nodes.json" \
  --base-url "https://your-hap-host.example"
```

脚本日志只显示 MCP origin；快照与项目 registry 不写入完整 MCP URL。运行新版脚本更新 registry 时，也会移除旧版本遗留的 `mcp_url` 字段。

`get_workflow_details` 只返回触发流程的 id、name、inputParameters、outputParameters，没有节点结构，也不能当作节点配置。节点内部配置先走 MCP `get_workflow_structure`：`initialize` 和 `tools/list` 之后按该工具的 inputSchema 传 `workflow_id` 或 `process_id`。`approval_block` / `sub_process` 不内联内部节点，块上的 `config.process.processId` 要再用同一个工具递归拉取。

这不是唯一的官方路径。hap-cli 的 `hap workflow structure` 使用 legacy `GET /api/workflow/flowNode/get`（v3 `get_process_structure` 当前会 404）。审批块和子流程的内部 id 在这张 `flowNodeMap` 上：typeId 16 读 `subProcessId`（同节点的 `appId` 是工作表，不是内部流程），typeId 26 读 `processNode.id`，内部图可能已经内联在 `processNode.flowNodeMap`。MCP 没有结构工具、调用失败，或 V3 节点没有 `config.process.processId` 时，提取改走这条 `flowNode/get` 递归，包含更深一层的审批块和子流程。Chrome `getNodeDetail` 补仍然为空的节点 config。结构里筛选条件、分支条件、触发事件或「将字段 / 设为」还是空占位、未解析的 `$nodeId-controlId$` 时，再对那个节点调一次 `getNodeDetail`。可读结果在 `_node_configs.json` 的 `editor_config.lines`；创建/更新节点仍保留 `field_mappings`。原始 fieldId 与 token 留在旁边。立刻结束且条件为空的分支项是默认分支，不会当成拉取失败。延时时长和代码块正文若详情里仍然没有，会写成 `editor_config.gaps`，而不是悄悄丢掉。结构缺口仍在 `_workflow_structures.json` 的 `gaps`。只拉一个流程时加 `--process-id`，或把 `--base-url` 设成 `https://your-hap-host.example/workflowedit/<processId>`。

多平台（明道云私有部署）提取不写死域名：`scripts/platform_router.py parse/probe`
解析与探测用户提供的平台 URL，`wf_fetch.py --url` 按该平台路由内部 API；
`<项目>/platform.json` 只记录 origin 与 app_id，不含 Cookie、Token 或 HAP 凭证。
详见 `references/tool-dispatch.md` 的「平台路由」一节。

## 项目数据命名

项目目录默认位于 `~/Documents/workflow-output/<项目名>/`，各数据文件的命名与用途以 `SKILL.md` §4 为唯一真源。

## 两阶段合约

Mode A/B 不直接编写执行合约：

```text
design_spec.md（人读）
        │
        ▼
execution_lock.json（设计阶段唯一机器真源）
        │  确定性校验 + Agent 1/2 + verification_merge
        ▼
lock_to_contract.py
        │
        ▼
execution_contracts/<safe-workflow-name>.json（hap-flow-exec 派生输入，一个工作流一个文件）
```

命令与顺序见 `SKILL.md` §7；门控与语义裁决规则见 `SKILL.md` §5。

用户确认设计前，不得把执行合约交给 `hap-flow-exec`。

## 描述符与注册表

`agents/descriptors/*.yaml` 是可发现接口真源，`references/skill-registry.json`
是生成物：

```bash
python3 scripts/skill_discovery.py generate \
  -o references/skill-registry.json
python3 scripts/skill_discovery.py validate
```

发现器会校验 descriptor 的 `requires`、`instructions`、
`verification.schema` 和脚本工具路径，并在 registry 中使用相对 `skill_dir`。

## 贡献

新增或修改 Mode、Agent 或模式时：

1. 修改源 descriptor，不手改 registry。
2. 重新生成 registry。
3. 运行项目验证、全库引用检查和 `git diff --check`。

参见 `CONTRIBUTING.md`。

## License

[Apache 2.0](LICENSE)
