# implementation-notes: accumulated-guardrails

## 目标

将 Agent 1/2/3 从"逐条阻断"改为"累积式全量检查+汇总报告"，借鉴 RepoPrompt CE `source_layout_guardrails.sh` 的 `fail()` 计数器模式。

## 当前状态

三个 Agent 虽然输出格式有 issues 列表，但指令中没有明确要求"即使前面部分 fail 也要继续检查所有部分"。
Agent 可能在发现第一个 fail 后就不再继续后面的 section，导致用户需要多轮迭代才能看到全部问题。

## 设计决策

### 1. 引入"累积式校验纪律"显式指令

在 logic-verify.md 和 platform-verify.md 最前面加一段硬约束：
- "即使前面的部分发现 fail，也必须完成所有部分的检查"
- "你的价值在于一次性给出完整的问题清单，而不是分段阻断"

### 2. 增加修复指引

输出 JSON 中增加 `fix_guide` 字段，按修复难度分组：
- `easy`: 命名/编号修正（改个字符串）
- `medium`: 节点配置调整（改配置不改结构）
- `hard`: 架构/拓扑问题（需要重新设计）

按 easy → medium → hard 排序，让用户可以"先修简单的、再攻坚难的"。

### 3. 增加汇总统计

verdict 不再是简单的 pass/fail，加上：
- `total_checks`: 总共执行了多少项检查
- `passed`: 通过数量
- `failed`: 失败数量
- `uncertain`: 不确定数量

### 4. 编排器合并逻辑不变量

verification-orchestrator 的合并规则保持不变（AND gate），但增加一个步骤：
从 Agent 1 + Agent 2 的 fix_guide 生成合并的"修复行动计划"，按优先级排序。

### 5. 不需要改的东西
- stop-gate hook 的行为不变（仍然检查双门控标记）
- Agent 1/2 的独立上下文运行方式不变
- 输出 JSON 的主结构不变（向下兼容）

## 改动范围

| 文件 | 改动 |
|------|------|
| agents/logic-verify.md | +累积纪律 +fix_guide +汇总统计 |
| agents/platform-verify.md | +累积纪律 +fix_guide +汇总统计 |
| agents/verification-orchestrator.md | +修复计划生成步骤 |
| agents/audit-scanner.md | +累积纪律（与其他 Agent 一致） |

## 和 RepoPrompt CE 的对照

| RepoPrompt CE 模式 | hhr-plan 迁移 |
|---|---|
| `fail()` 函数计数器，不提前 exit | Agent 指令中显式声明"完成所有检查" |
| 所有 guardrail 检查跑完才 exit 1 | 所有 section 跑完才输出 verdict = fail |
| 错误输出附修复命令 | fix_guide 按难度分组，每组有具体修正建议 |
| 输出末尾打印 "N issue(s)" | 汇总统计 total_checks / passed / failed |

## 实施完成 (2026-06-30)

### 改动的文件

| 文件 | 改动 |
|------|------|
| `agents/logic-verify.md` | +累积式校验纪律（顶部显式指令）, +summary 统计, +fix_guide 输出, issues 中 +section 字段 |
| `agents/platform-verify.md` | +累积式校验纪律, +summary 统计, +fix_guide 输出 |
| `agents/verification-orchestrator.md` | +修复行动计划生成（Step 3 新增部分）, +fix_plan 写入 execution_lock.json |
| `agents/audit-scanner.md` | +累积式校验纪律 |

### 核心变化

1. **Agent 1/2/3 指令顶部新增"累积式校验纪律"** — 显式声明"即使前面部分 fail 也必须完成所有检查"
2. **输出格式新增 fix_guide** — 按 easy/medium/hard 三级分组，每组有具体的修正动作
3. **编排器新增"修复行动计划生成"** — 从两个 Agent 的 fix_guide 合并，写入 execution_lock.json
4. **向下兼容** — 输出 JSON 的主结构不变，旧代码只需要忽略新字段

### 和 RepoPrompt CE guardrails 的差异

RepoPrompt CE 用 bash `fail()` 计数器实现累积，hhr-plan 用**自然语言指令约束 Agent 行为**实现同样的效果。原理相同（全量检查→汇总报告），但手段不同（bash 控制流 vs LLM 指令约束）。

