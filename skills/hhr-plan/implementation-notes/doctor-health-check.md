# implementation-notes: doctor-health-check

## 目标

为 hhr-plan 创建 `scripts/doctor.sh`，提供分阶段的环境健康检查，从 RepoPrompt CE 的 doctor.sh 借鉴结构和从 guardrails 借鉴累积式错误收集。

## 设计决策

### 1. 累积式失败 vs 提前退出
RepoPrompt CE 的 doctor.sh 每个阶段 fail() 调用 exit 1。hhr-plan 改用累积式：
- 错误计数器（errors）和警告计数器（warnings）
- 所有阶段跑完再退出
- 给用户完整的问题清单，而不是一个一个修

这是从 RepoPrompt CE 的 guardrails 脚本（source_layout_guardrails.sh）借的模式，不是它的 doctor.sh。

### 2. 五层检查
- Layer 0: 基础设施（python3, pip, hap-bridge, 目录, git）
- Layer 1: 注册表（projects_registry.json 存在+有效，至少一个项目 context_ready）
- Layer 2: 项目核心文件（project_context.json, business-flow-manifest.json, aliases.json）
- Layer 3: 派生数据（_node_data.json, dependency_graph.json, _search_index.db, project-snapshot.md）
- Layer 4: 数据一致性（worksheet/workflow 计数交叉验证，双向边检测）

### 3. 依赖自发现
doctor.sh 不维护单独的依赖清单。Layer 0 的依赖信息从实际脚本的 import 语句中自动提取是过度工程化——直接用探索得到的硬编码清单：
- 唯一的外部 pip 包: browser_cookie3（auth.py 需要）
- 唯一的外部工具: ~/.claude/mcp-servers/hap-bridge/cli.py
- 所有其他脚本都是 stdlib only

### 4. 项目迭代
Layer 2-4 只检查 projects_registry.json 中 context_ready=true 的项目。
如果没有任何项目的 context_ready，这是一个警告（不是错误）——项目可能还没完成首次提取。

### 5. Mtime 新鲜度检查
- _node_data.json 的 mtime 应该 > business-flow-manifest.json 的 mtime（因为它是从 manifest 派生的）
- dependency_graph.json 的 mtime 应该 > _node_data.json 的 mtime
- 不用精确时间窗口——只要有合理的先后顺序即可

### 6. FTS5 索引检查
检查 _search_index.db 中的 search_fts 表：
- 表存在
- 每个 context_ready 项目至少有一条记录
- 不做深度数据验证（那属于 rebuild 的范畴）

### 7. 输出格式
- 每阶段打印耗时（从 RepoPrompt CE 借的 phase() 模式）
- 每个检查项：✓ pass / ✗ FAIL / ⚠ WARN
- 最后打印汇总 + 修复命令
- --quiet 标志跳过非必要输出

## 待确认问题
- doctor.sh 应该放在 scripts/ 下还是项目根目录？→ 放在 scripts/ 下与现有结构一致
- 是否需要 --fix 模式自动修复？→ 先不做，v1 只做诊断。自动修复需要更多设计

## 实施完成 (2026-06-30)

### 产出
- `scripts/doctor.sh` — 五层健康检查 (共 280 行)
- SKILL.md 已更新 references 列表

### 首次运行结果 (10 projects)
- **0 errors**: 基础设施、注册表、搜索索引全通过
- **5 errors**: 4 个项目的 project_context.json worksheets 为空 (城市运营/赫立-合同/赫立-人事/赫立-研发), 1 个 _node_data.json 为空 (经济开发区)
- **13 warnings**: dependency_graph 过期 (多个小项目), worksheet 计数异常 (ctx vs manifest 引用数不同)

### 已发现的问题
- dependency_graph.json 格式假设: nodes 是 dict (keyed by ID) 而非 list — 已在检查代码中适配
- readarray 在 macOS 默认 bash 中不可用 → 改用 while-read 循环

