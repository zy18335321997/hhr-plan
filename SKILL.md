---
name: hhr-plan
description: 明道云 APaaS 设计引擎。当用户需要解释工作流、分析实体生命周期、查依赖关系、设计新功能、排查问题、审计配置、说明业务流程、改工作流、工作表设计或数据模型设计时使用。
user_invocable: true
version: 2.1.0
lifecycle: validated
references:
  - system-prompt.md
---

# hhr-plan 2.1.0

明道云 APaaS 设计、诊断与审计入口。这里只定义分流、加载顺序、完成条件和交接边界；公理、定理、详细门控和工具命令分别由各自真源维护。

## 1. 先分流：轻量查询或全量任务

### 轻量查询

仅当以下条件全部成立时使用：

1. 用户只问一个可直接查证的事实，例如工作流用途、表字段、工作流清单或两张表的关系。
2. 不需要解释原因、提出改造、评估影响面或执行审计。
3. 不需要应用公理和门控。

加载 `references/tool-dispatch.md`，只读取命中对象所需的最小本地数据。回答后停止，不运行 `auto_sync.py`，不加载完整节点集，也不自动升级任务。

用户追问“为什么”“怎么改”“帮我排查”时，升级为全量任务。

### 全量任务

设计、改造、诊断根因或健康审计均属于全量任务。先确定 Mode，再按第 3 节加载。

## 2. 显式 Mode 路由

| 意图 | Mode | 指令真源 |
|---|---|---|
| 从零设计新应用、新模块或新数据模型 | A 绿地设计 | `built-in-skills/mode-a-greenfield.md` |
| 修改现有表、字段、工作流或审批链 | B 棕地改造 | `built-in-skills/mode-b-brownfield.md` |
| 解释异常、定位根因、追踪错误数据 | C 诊断排查 | `built-in-skills/mode-c-diagnose.md` |
| 全项目合规扫描、健康检查或评分 | D 健康审计 | `built-in-skills/mode-d-audit.md` |

边界规则：

- 用户只问“值不值得做/有没有必要”，先路由到价值判断能力，不直接进入 Mode A。
- 诊断确认需要修改时，从 Mode C 显式切换到 Mode B，不在诊断流程内直接写设计。
- Mode D 发现问题后先交付审计；需要修复时显式切换到 Mode B。
- 意图或项目身份不清会改变结果时，只问一个最小澄清问题，不静默猜 Mode。

## 3. 按需加载

### 所有全量 Mode

1. `system-prompt.md`：元公理、设计公理、冲突优先级和诚实边界。
2. 对应 Mode 指令文件：步骤、阻断点、产出。
3. `references/tool-dispatch.md`：仅在需要查本地项目数据或调用平台时加载。

### Mode A/B

额外加载：

- `references/theorems-and-protocols.md`：定理与执行协议。
- `references/unified-design-spec.md`：完整度、正确性、可构建性详细门控的唯一真源。
- `agents/verification-orchestrator.md`：独立 Agent 调用、格式校验与裁决合并。
- `references/templates/execution-lock-schema.md`：设计锁和执行合约交接。

字段、工作流、平台能力和行业参考只在对应步骤命中时加载，不预加载整个 `references/`。

### Mode C/D

只加载目标项目和当前问题所需的数据。Mode D 使用 `references/unified-design-spec.md` 作为扫描维度真源；历史审计报告不能替代当前规范。

## 4. 真源与规范命名

| 事项 | 唯一真源 |
|---|---|
| 元公理与五条设计公理 | `system-prompt.md` |
| 八条定理与执行协议 | `references/theorems-and-protocols.md` |
| 三层详细门控 | `references/unified-design-spec.md` |
| 工具选择、命令和本地优先级 | `references/tool-dispatch.md` |
| Mode 步骤与阻断规则 | 对应 `built-in-skills/mode-*.md` |
| Agent 输出格式与合并 | Schema + `agents/verification-orchestrator.md` |
| 客户需求到系统设计语言 | `execution_lock.json.design_ir` |
| 设计阶段机器真源 | `execution_lock.json` |
| 执行阶段派生输入 | `execution_contract.json`，只能由 `lock_to_contract.py` 生成 |
| 可发现接口 | `agents/descriptors/*.yaml`；`references/skill-registry.json` 是生成物 |

项目数据统一使用以下名称：

- `project_context.json`：表、字段、关联和命名上下文。
- `business-flow-manifest.json`：工作流读写清单。
- `nodes.json`：浏览器或内部 API 提取的原始节点。
- `_node_configs.json`：`extract-project.py` 生成的字段级节点详情。
- `_node_data.json`：由 `generate_node_data.py` 从现有提取物生成的标准化节点索引，供搜索和依赖图消费。
- `node_configs.json`：旧提取器或单工作流缓存格式；只通过 `wf_fetch.py` 按 PID 读取，不把它与上述全项目文件混称。

## 5. Outcome Contract

| Mode | 完成条件 |
|---|---|
| A | 客户需求 100% 追踪到 design_ir；状态机、权限、视图和异常路径完整；设计与 lock 一致；三层门控和 Agent 1/2 通过；成功派生并校验执行合约，或因缺少精确 ID 明确 Hard Stop。 |
| B | 真实项目路径已确认；影响面、design_ir 增量和时序完整；修改后的 lock 通过确定性检查及 Agent 1/2；成功派生并校验执行合约，或明确阻断。 |
| C | 给出可复核的根因、证据链、影响面和排除项；连续假说失败时输出已知/未知清单并停止。 |
| D | 当前项目数据范围明确；扫描维度完整；Agent 3 输出通过格式和语义校验；报告按严重度排序。 |

“脚本退出 0”不自动等于设计通过：`validate-agent-output.py` 的退出 0 只表示格式完整，还必须检查 `semantic_verdict`。

## 6. Checkpoint

任务暂停或上下文过长时，输出最小可接续存档：

```yaml
project: <项目名>
project_path: <绝对路径>
mode: A|B|C|D
status: in-progress|resolved|blocked
confirmed: []
artifacts:
  project_context: <路径或 null>
  execution_lock: <路径或 null>
  execution_contract: <路径或 null>
excluded_hypotheses: []
next_action: <下一步动作>
blocker: <阻断原因或 null>
```

不得在 checkpoint 中复制密钥、MCP 查询参数或平台 Cookie。

## 7. 两阶段合约交接

Mode A/B 的固定交接顺序：

1. 设计写入 `execution_lock.json`；它是唯一可编辑机器真源。
2. 运行 design_ir、lock、项目字段/依赖和平台机械校验，并用
   `design_spec_linter.py` 检查人类文档与需求追踪。
3. 按 `agents/verification-orchestrator.md` 调用 Agent 1/2，运行 `validate-agent-output.py`，再由 `verification_merge.py` 原子写入 Agent gates 与顶层 `verification`。
4. 任一格式或语义失败都必须阻断；修正后重验，禁止手工把 gate 改为 pass。
5. gates 通过后运行 `lock_to_contract.py`，从 lock 逐个派生
   `execution_contracts/<safe-workflow-name>.json`。
6. 运行 `contract_compat.py validate-exec`。转换器缺少任何精确 ID、配置、依赖或发布顺序时 Hard Stop，不得猜值。
7. 向用户展示设计与门控结果并停等确认。只有用户确认后，才把已校验的执行合约交给 `hap-flow-exec`。

`design_spec.md` 是人类可读说明，不能覆盖 lock；`execution_contract.json` 是可重新生成的执行输入，不能手改。

## 8. 安全边界

- 项目提取必须显式提供 `--mcp-url` 或设置 `HAP_MCP_URL`；仓库不提供默认 MCP URL。
- 日志、快照、checkpoint、registry 和设计文档不得记录凭证化 URL。
- Mode B 的影响面超过规范阈值、项目路径不明确、节点数据与 PID 不匹配、Agent 失败、合约转换失败时均停止。
- 详细门控内容只引用 `references/unified-design-spec.md`，本入口不复制门控清单。
