# hhr-plan 2.1.0

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
git clone https://github.com/YOUR_USER/hhr-plan.git \
  ~/.claude/skills/hhr-plan
bash ~/.claude/skills/hhr-plan/scripts/doctor.sh
```

Python 脚本以 Python 3.10+ 为目标。实时平台查询可选依赖 hap-bridge；浏览器提取可选依赖 Playwright 和 `browser_cookie3`。

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

## 项目数据命名

项目目录默认位于 `~/Documents/workflow-output/<项目名>/`：

- `project_context.json`：表、字段、关联和命名上下文
- `business-flow-manifest.json`：工作流读写清单
- `nodes.json`：原始节点响应
- `_node_configs.json`：字段级节点详情
- `_node_data.json`：供搜索和依赖图消费的标准化节点索引
- `node_configs.json`：旧提取器或单工作流缓存，只通过 `wf_fetch.py` 按 PID 使用

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
execution_contract.json（hap-flow-exec 派生输入）
```

基本闭环：

```bash
python3 scripts/contract_compat.py validate-lock execution_lock.json
python3 scripts/design_validator.py "<项目名>" \
  --lock-file execution_lock.json \
  --context-file project_context.json \
  --graph-file dependency_graph.json \
  --check-graph
python3 scripts/verify-platform.py --lock-file execution_lock.json

# Agent 输出由 agents/verification-orchestrator.md 指导取得
python3 scripts/validate-agent-output.py \
  --agent1 /tmp/hhr_agent1_output.json \
  --agent2 /tmp/hhr_agent2_output.json
python3 scripts/verification_merge.py \
  --target execution_lock.json \
  --agent1 /tmp/hhr_agent1_output.json \
  --agent2 /tmp/hhr_agent2_output.json \
  --mode design

python3 scripts/lock_to_contract.py execution_lock.json \
  --workflow "<精确工作流名称>" \
  --output "execution_contracts/<safe-workflow-name>.json"
python3 scripts/contract_compat.py validate-exec \
  "execution_contracts/<safe-workflow-name>.json"
```

任一格式、语义、平台机械校验或转换失败都必须阻断。`validate-agent-output.py`
返回 0 只表示 Agent 输出格式完整，仍需检查 `semantic_verdict`。多工作流必须使用
不同的安全文件名，禁止覆盖同一个执行合约。

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
