# hhr-plan vs RepoPrompt CE — v2 深度对比

> 2026-07-02 | 基于 RepoPrompt CE v1.0.22 源码分析 + hhr-plan v1.3.0 完整验证

## 一、定位差异

| 维度 | RepoPrompt CE | hhr-plan |
|------|-------------|----------|
| 解决什么问题 | "AI 编程助手该看什么代码" | "明道云低代码平台该怎么设计/排查" |
| 用户 | 任何用 AI 编程助手的开发者 | 明道云实施顾问/开发者 |
| 形态 | macOS 原生 App (Swift) | Claude Code Skill (Markdown + Python) |
| 平台绑定 | 无 (任何 Git 仓库) | 深度绑定明道云 HAP 平台 |
| 输出 | 精选的代码上下文 | 设计文档 + 诊断报告 + 工作流配置 |

## 二、架构对比

| 层 | RepoPrompt CE | hhr-plan |
|----|-------------|----------|
| 入口 | `AGENTS.md` (400+ 行) | `SKILL.md` + `system-prompt.md` (410 行) |
| 方法论 | 无公理体系 (实用工具) | 2 元公理 + 5 设计公理 → 8 定理 |
| 验证 | Sparkle 自动更新验证 + CI | **4 道确定性闸门** + 2 个 LLM Agent |
| 写操作 | Agent 编排 (运行外部 CLI) | hap-cli + 直接 API (创建工作流/节点) |
| 扩展性 | Provider 插件 (Claude/OpenAI) | 4 模式 (A/B/C/D) + 7 子技能 |
| 合约 | 无 (代码即真相) | execution_lock.json (设计合约) |

## 三、验证闸门 — 核心差异

### RepoPrompt CE
```
conductor daemon → lane-serialized build queue
  → Swift compiler → XCTest suite → smoke checks
  → Sparkle appcast verification → release signing
```
- 验证对象: **代码编译+测试通过**
- 门控方式: bash/Python 脚本 + CI pipeline
- 确定性: 100% (编译器输出)

### hhr-plan
```
设计方案
  → Gate 1: verify-platform.py   (确定性: typeId/上限/拓扑)
  → Agent 1 + Agent 2 (并行)     (LLM启发式: 公理/命名/逻辑)
  → Gate 2: validate-agent-output (确定性: 格式完整性)
  → Gate 3: stop-gate hook        (外部防线: 双门控标记)
  → Gate 4: platform-validate.py  (地面真相: 平台原生验证)
```
- 验证对象: **设计合理性和平台合规性**
- 门控方式: Python 脚本 + LLM Agent + 平台 API
- 确定性: Gate 1/2/3 = 100%, Agent = 启发式, Gate 4 = 地面真相

## 四、借了什么、没借什么

### 已借鉴并实现

| RepoPrompt CE | → hhr-plan | 实现 |
|--------------|-----------|------|
| `Scripts/doctor.sh` (分阶段健康检查) | `scripts/doctor.sh` (5层+10项目自动发现) | ✅ |
| `Scripts/source_layout_guardrails.sh` (累积式fail) | Agent 1/2 累积式校验纪律 + violations 列表 | ✅ |
| `AGENTS.md` 精确命令 + 行为陷阱 | `system-prompt.md` Quick Ref + Behavior Traps | ✅ |
| `agents/openai.yaml` 接口描述符 | `agents/descriptors/*.yaml` (7个模式) | ✅ |
| `test-suite-contract-ledger.tsv` | `coverage-ledger.tsv` (44条约束) + verify-ledger.py | ✅ |
| `OutputSummarizer` (token预算) | `summarize-output.py` (2000 chars) | ✅ |
| `conductor.py` (lane-serialized daemon) | — 不适用 (单 Agent) | N/A |
| git worktree 隔离 | — 不适用 (无并发构建) | N/A |
| agent orchestration (Agent Mode) | — 不同场景 (编排LLM Agent vs 编排CLI工具) | N/A |

### RepoPrompt CE 有但 hhr-plan 不需要的

| 能力 | 为什么不需要 |
|------|------------|
| macOS 原生 UI (SwiftUI) | Claude Code 本身就是交互界面 |
| Sparkle 自动更新 | Claude Code Skill 通过 git pull 更新 |
| Provider 插件 (Claude/OpenAI/Codex) | 由 Claude Code 平台统一管理 |
| Test suite + CI pipeline | Skill 无编译概念，验证通过 live API 调用 |
| MCP Server (自建) | 已有 hap-bridge MCP + hap-cli 双通道 |

## 五、写能力 — 关键突破 (v2 新增)

这是本次对比的核心差异。v1 时 hhr-plan 只能读不能写。v2 验证了完整的工作流创建链路：

| 能力 | RepoPrompt CE | hhr-plan v2 |
|------|:--:|:--:|
| 读代码库上下文 | ✅ Swift/ObjC 原生 | — (不同领域) |
| 读明道云工作表/工作流 | — | ✅ hap-bridge + hap-cli |
| 创建工作流 | — | ✅ `hap workflow create` |
| 绑定工作表触发器 | — | ✅ `batch-add --trigger-worksheet` |
| 顺序链接节点 | — | ✅ `node add --after` |
| 配置节点字段 | — | ✅ `save-action -f` (需UUID key) |
| 读节点完整配置 | — | ✅ `node get` (部分不稳定) |
| 发布工作流 | — | ⚠️ 需节点配置完整 |
| 直接 API 调用 | — | ✅ saveNode flat格式 |
| 运行外部 Agent | ✅ Agent Mode | ✅ `hap workflow trigger` + `hap approval` |

## 六、今天修改的文件

### hhr-plan skill

| 文件 | 修改 |
|------|------|
| `system-prompt.md` | 工具能力边界表: 4盲点→0; +Open API 能力; +Quick Ref; +Behavior Traps |
| `agents/logic-verify.md` | +累积式校验纪律; +timeline条件执行; +fix_guide输出 |
| `agents/platform-verify.md` | +累积式校验纪律; +fix_guide; agent2 prompt补充文件依赖 |
| `agents/verification-orchestrator.md` | +修复回退映射; +Gate 4平台原生校验; +2x/3x fail行为明确 |
| `agents/audit-scanner.md` | +累积式校验纪律 |
| `agents/descriptors/*.yaml` | 7个模式接口描述符 (新建) |
| `scripts/doctor.sh` | 5层分阶段健康检查 (新建) |
| `scripts/verify-platform.py` | Gate 1: 39 typeId + actionId映射 + 批量上限 + 拓扑 (新建) |
| `scripts/validate-agent-output.py` | Gate 2: 后置格式完整性闸门 (新建) |
| `scripts/summarize-output.py` | Token预算摘要 (新建) |
| `scripts/verify-ledger.py` | 44条约束台账验证器 (新建) |
| `scripts/platform-validate.py` | Gate 4: 平台原生校验 (新建) |
| `references/open-api-capabilities.md` | 明道云 Open API 42端点完整参考 (新建) |
| `references/hap-cli-capabilities.md` | hap-cli 验证报告 + node save 格式 (新建) |
| `references/verified-workflow-creation.md` | 验证通过的工作流创建6步流程 (新建) |
| `references/runtime-probe.md` | +JSON格式说明 + fieldName交叉查表 |
| `references/axioms/coverage-ledger.tsv` | 44条约束合约台账 (新建) |
| `references/templates/execution-lock-schema.md` | +schema_version字段 |
| `built-in-skills/mode-a-greenfield.md` | +verify-platform.py 预检 + Gate 4 |
| `README.md` | 完整项目文档 (新建) |
| `LICENSE` | Apache 2.0 (新建) |
| `CONTRIBUTING.md` | 贡献指南 (新建) |
| `.gitignore` | 排除 implementation-notes (新建) |

### 新建: 25 文件 | 修改: 14 文件 | 总计: 39 文件变更

## 七、hap-cli 验证日志

```
安装: pip (venv) hap-cli v0.8.19
登录: hap auth login https://work.jijiansmart.com
用户: 张银 (org: 同技智能)

验证通过:
  ✅ workflow create/delete/list/structure/get
  ✅ workflow node batch-add (trigger binding + shell creation)
  ✅ workflow node add --after (sequential chaining, all types)
  ✅ workflow node save-action (field configuration with UUID keys)
  ✅ workflow node list-types (30 types)
  ✅ workflow publish (conditional on complete config)
  ✅ 创建工作流 10+ 次 (全部验证+清理)
  ✅ 人员离职办理 工作流 (完整创建+字段配置)

验证失败 (服务端限制):
  ❌ workflow node save (CLI) → 500
  ❌ saveNode API (notice typeId=27) → 500
  ❌ batch-add (get_single/get_relation) → 500
  ⚠️ save-action 不校验 fieldId 有效性 (静默丢弃)

关键发现:
  1. 下拉字段 fieldValue 必须是 UUID key (非显示文本)
  2. batch-add 创建数据节点壳 (名称/appId为空)
  3. node add --after 正确创建节点 (名称/appId完整)
  4. saveNode flat格式需要完整蓝本 (controls/appList等)
  5. save-action -f 格式: fieldValue (非 value)
