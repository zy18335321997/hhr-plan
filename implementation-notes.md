# implementation-notes: hhr-plan 全面治理

## 目标
- 以 `execution_lock.json` 作为设计阶段唯一真源。
- 严格转换生成 `hap-flow-exec` 消费的 `execution_contract.json`。
- 让 Agent 1/2/3 的输出校验、裁决合并和失败阻断形成闭环。
- 修复路由、路径、凭证、CI 与重复文档问题。

## 设计决策
- 保留两阶段合约；`execution_contract.json` 是不可手改的衍生物。
- 转换器不猜测字段 ID、选项 key、分支条件或节点配置；输入不足时 Hard Stop。
- Agent 输出使用统一信封和 failure code；格式校验通过后才允许写回 lock。
- 确定性 CI 失败必须阻断；依赖本机项目数据的检查只能显式跳过。
- 详细门控、公理和定理各自只保留一个真源，`SKILL.md` 只保留入口与路由。

## 兼容策略
- 输入端暂时兼容旧 `typeId/actionId`，规范输出统一为 `type_id/action_id`。
- 合约校验器自动识别 lock 与 exec contract；旧命令保留兼容入口并给出迁移提示。
- 删除文件前先确认无引用且内容已被现有真源覆盖。

## 路由与文档治理决策
- `SKILL.md` 只维护轻量/全量分流、Mode 路由、按需加载、Outcome Contract、
  checkpoint 和两阶段交接。
- `system-prompt.md` 只维护元公理、五条设计公理、冲突优先级和诚实边界。
- 三层详细门控仅以 `references/unified-design-spec.md` 为真源；定理仅以
  `references/theorems-and-protocols.md` 为真源；工具命令仅以
  `references/tool-dispatch.md` 为真源。
- 项目节点文件按用途区分：`nodes.json` 原始节点、`_node_configs.json`
  字段级详情、`_node_data.json` 标准化索引、`node_configs.json` 单流旧缓存。
- Mode D 只验证审计完整性；用户批准修复后显式路由 Mode B，再生成执行合约。

## Agent 并行校验结论（合并自旧笔记）
- Agent 1/2/3 必须由主 Agent 通过独立 Subagent 调用；Python 脚本不能模拟
  LLM 校验。
- `agent_prepare.py` 只压缩只读输入。
- Agent 1/2 必须并行取得结果；`validate-agent-output.py` 只判格式完整性，
  `verification_merge.py` 负责语义裁决和原子写 gates。
- Agent 1 的字段存在性与 `design_validator.py` 有重叠时，Agent 使用确定性结果
  作为证据，不重复伪造检查。
- `design_validator.py` 输出绑定当前 lock 的 `input_digest`；`agent_prepare.py`
  只接受 verdict=pass 且摘要一致的结果，并写入
  `deterministic_evidence.design_validator`，从机制上落实上述分工。
- Agent 1/2 的 `input_digest` 绑定规范化 lock 设计内容：基础 Gate 1-6 参与摘要，
  派生的顶层 `verification` 与 Agent gates 不参与，避免写回裁决后出现自引用哈希。
- Agent 3 的 `input_digest` 绑定审计报告原始字节；audit 合并必须显式传
  `--source` 复核，旧输出不能重放到新报告。
- `gates` 只保存有 `result` 的基础 Gate 与 Agent Gate；完整性裁决和修复计划统一
  写入顶层 `verification.verification_agents` 与 `verification.fix_plan`。

## 本轮只读审查修复决策

- `lock_to_contract.py` 在转换前强制 Gate 1-6（Gate 3 可 `n/a`）、Agent 1/2、
  语义裁决和当前 lock 摘要全部通过；缺失、pending、fail 均 Hard Stop。
- lock 固定 `meta.schema_version=2.0`，执行合约固定 `1.0`；触发类型、触发字段
  一致性以及执行节点 `type_id/action_id` 均在兼容校验器中确定性验证。
- `lock_manager validate` 不再把低/中严重度 schema violation 降级成 warning；
  `init --source-design` 改为必填，禁止生成无法追溯来源的 lock。
- 用户显式检查图、lock 含 association 或传 `--new-edge` 时，依赖图缺失返回
  结构化 fail；只有不涉及图的调用才能跳过。
- `platform-validate.py` 在没有真实只读 validate API 前固定 `skipped`/exit 2，
  且不调用发布、保存或任何平台写操作。真实写入验证只在用户确认后交给
  `hap-flow-exec`。
- 多工作流执行合约统一输出到
  `execution_contracts/<safe-workflow-name>.json`，防止后一个工作流覆盖前一个。
- preflight 同时扫描工作树和 staged blob，敏感规则覆盖 fine-grained GitHub
  token、JWT 与大小写 bearer；只精确豁免扫描器自身。
- whitespace 同时检查 staged/unstaged；CI 按 PR base 或 push before SHA
  检查提交范围，不再依赖 clean checkout 的空 diff。
- descriptor 中任何含 `/` 或已知扩展名的 `requires` 都按路径处理；路径 resolve
  后必须留在 skill root 且为普通文件。instructions 与 schema 同样拒绝目录、
  拼写错误和越界符号链接。
- `references/platform/node-capabilities.md` 是 Agent 2 默认自包含真源，完整登记
  39 个 `type_id`、全部已知 `action_id` 和批量限制，不再引用不存在的指南。

## 安全决策
- `extract-project.py` 不提供默认 MCP URL，只接受 `--mcp-url` 或
  `HAP_MCP_URL`。
- 日志只显示 MCP origin；快照和项目 registry 不保存完整凭证化 URL。
- `--skip-mcp` 可完全使用本地节点文件；需要按 PID 实时拉节点时必须显式提供
  `--base-url` 或可推导 origin 的 MCP URL。

## 重复与历史文件治理
- 删除 `agents/scripts/diagnose.py`：与 `scripts/diagnose.py` 字节级相同且全库无引用。
- 删除 `agents/scripts/build_context.py`：全库无引用，`scripts/build_context.py`
  是包含字段 ID 解析修复的后继真源。
- 删除 `references/global-topology.md`：与 `references/topology-几建.md`
  字节级相同；生成器的规范产物是 `topology-<project>.md`。
- 保留 `scripts/inject_nodes_v2.js`：无运行时引用，但它支持 `inject_all.js`
  不覆盖的旧 API 兼容/PID 列表路径；继续不进入默认加载链。
- 保留 `references/mode-d-audit-2026-06-18.md` 与
  `references/hhr-plan-vs-repoprompt-ce-v2.md`：它们是历史证据而非当前真源，
  已显式标记为不进入运行时加载链。

## 验证目标
- lock schema、字段/依赖、平台机械检查均可独立运行。
- lock → contract → hap-flow-exec preflight roundtrip 通过。
- Agent 1/2/3 正反例、裁决合并与失败语义测试通过。
- registry 路径、preflight、ledger strict、回归 fixture 和 CI 全部通过。

## 开放问题
- 真实复杂工作流若缺少执行 DSL，转换器会停止并报告缺口；不会自动补写业务语义。
- 已泄露凭证的轮换与 Git 历史清理需要仓库所有者确认并手工执行；本轮不自动轮换、
  不重写历史，也不记录任何凭证值。

## 本机 Doctor 外部运行时数据问题

2026-07-21 只读运行 `bash scripts/doctor.sh --quiet` 得到 3 个错误。这些都位于
`~/Documents/workflow-output` 的外部运行时数据，本轮按要求只记录、不修改：

1. `城市运营` 的 `project_context.json` 无有效 worksheets。
2. `经济开发区城市运营中心` 的 `_node_data.json` 无效或为空。
3. `莱尔德` 的 `_node_data.json` 为 427 个工作流，而 manifest 为 0，计数严重不一致。
- 已从当前工作树移除的 HAP 凭证仍可能存在于 Git 历史。凭证轮换、吊销或历史
  重写属于仓库外/破坏性操作，本次未自动执行，维护者必须单独处理。
- 本机 `doctor.sh --quiet` 发现 3 个运行时数据问题：`城市运营` 的
  `project_context.json` 无有效 worksheets、`经济开发区城市运营中心` 的
  `_node_data.json` 为空、`莱尔德` 的节点数与 manifest 严重不一致。这些文件位于
  `~/Documents/workflow-output`，不属于本次仓库治理范围。

## 实施记录
- 2026-07-21：方案获批；工作树已有合约与 Agent 未提交改动，本次保留并接线。
- 2026-07-21：完成路由、真源、Agent 门控、两阶段合约和 MCP 凭证治理接线。
- 2026-07-21：CI 确定性门禁不再吞错；本机 workflow-output 与可选
  hap-flow-exec sibling 集成在缺失时只做显式 SKIP，不伪装成已验证。
- 2026-07-21：回归测试支持自包含 fixture 和注入数据根目录；仓库内
  `ci-minimal` fixture 同时覆盖两种 dependency edge 字段格式。
- 2026-07-21：preflight 只执行带 `__main__` 且使用 argparse 的 CLI
  `--help`，并加入 schema、registry 路径、unittest、凭证和 diff 门禁。
- 2026-07-21：完成 input digest 防重放、merge→convert 硬门控、只读平台边界、
  图缺失阻断、descriptor 路径收紧、staged/CI 范围检查及对应回归测试。
- 2026-07-21：Agent 输出绑定输入 SHA-256；lock 变化后旧裁决不可重放。
  转换器强制六个基础 gate、Agent 1/2 gate 和摘要一致性全部通过。
- 2026-07-21：禁用 `platform-validate.py` 的发布式“校验”；只读 API 未确认前
  固定返回 skipped，平台写入验证留给用户确认后的 `hap-flow-exec`。
- 2026-07-21：补齐 Agent 1 的确定性证据接线，修正 Agent 3 项目上下文路径；
  Mode A/B 现在先保存带 lock 摘要的 design-validator 结果，再生成 Agent brief。
- 2026-07-21：使用仓库自包含 fixture 实际并行调用 Cursor Agent 1/2；两个输出均
  通过统一 Schema、摘要绑定和语义校验，`verification_merge.py --dry-run`
  返回 format/semantic 双 pass。Agent 1 报告明确复用了 design-validator 证据。
