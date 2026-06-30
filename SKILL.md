---
name: hhr-plan
description: 明道云 APaaS 设计引擎。当用户需要：解释工作流、分析实体生命周期、查依赖关系、设计新功能、排查问题、审计配置、说明业务流程、画泳道图、改工作流、工作表设计、数据模型设计时使用。覆盖绿地设计、棕地改造、诊断排查、健康审计四种工作模式。支持搜索索引秒定位 + 依赖图全景视角 + 实体生命周期提取。
user_invocable: true
version: 1.3.0
lifecycle: validated
references:
  - system-prompt.md
  - references/global-topology.md
  - scripts/search.py
  - scripts/build_search_index.py
  - scripts/rebuild_graph.py
  - scripts/extract-via-browser.py
  - scripts/doctor.sh
  - scripts/verify-platform.py
  - scripts/validate-agent-output.py
  - scripts/summarize-output.py
  - scripts/verify-ledger.py
  - agents/descriptors/
  - references/lessons-learned.md
  - references/data-model-derivation.md
  - references/workflow-design-derivation.md
  - references/design-review-protocol.md
  - references/templates/output-template.md
---

# Mingdao APaaS 设计引擎 v5.0

> 从「几建」项目（76工作表含工作流/321工作流/12业务域）反向蒸馏。
> 2 条元公理 + 5 条设计公理 → 8 条定理 → 双门控验证 → 四种工作模式。
> 生命周期: `validated` — 6 个项目 Mode D 审计完成，公理2/3=100%，公理1/4/5 领域敏感。

> **统一命题**：给定任何 APaaS 场景，以五条公理为标尺，输出公理一致的设计或诊断。四种模式（绿地/棕地/诊断/审计）是同一把尺子的四种用法。

## 引擎加载

### 1. 始终加载
`system-prompt.md` — 完整推理框架、约束表、平台限制清单、公理冲突处理规则。

### 2. 识别模式并加载
- Mode A (绿地设计): 从需求直接推导数据模型+工作流
- Mode B (棕地改造): 在现有表上扩展，遵守公理4（单向依赖）
- Mode C (诊断排查): 给定问题现象，追溯到根因+影响面
- Mode D (健康审计): 五公理全覆盖扫描，输出评分卡+问题清单

### 3. 按需加载附加技能
按 `system-prompt.md` 中的 Mode→Skill 映射表加载。

### 4. 按模式加载项目上下文
- Mode A/B/C: 加载目标项目的 `project_context.json` + `business-flow-manifest.json`
- Mode D: 加载全部已提取项目的 manifest

### 5. 项目上下文加载顺序

分两层：**基础层**（所有模式共享，有构建依赖）→ **执行路径**（诊断/设计用相反顺序）。

**启动时自动同步：**
```bash
python3 ~/.claude/skills/hhr-plan/scripts/auto_sync.py
# 按 mtime 增量判定，只重建过期的索引和图，过期的跳过
```

**基础层：**
```
1-5 数据源（无顺序依赖）：
  1. aliases.json → 术语映射
  2. project_context.json → 工作表+字段（136表/1165字段）
  3. business-flow-manifest.json → r/w链路（321工作流）
  4. nodes.json → 节点配置（Browser提取）
  5. lessons.json → 历史经验（可选）

6-7 有构建依赖，必须按序：
  6-9 的构建由 auto_sync.py 统一调度（按 mtime 增量，只重建过期的）：
     python3 ~/.claude/skills/hhr-plan/scripts/auto_sync.py

  6. _search_index.db（依赖 1-3）→ auto_sync 判断后调用 build_search_index.py
  7. dependency_graph.json（依赖 2-3）→ auto_sync 判断后调用 rebuild_graph.py
  8. 实体生命周期（依赖 7）→ 按需动态提取，始终最新
  9. references/global-topology.md → 静态参照，auto_sync 重建后提示检查
```

**两名执行路径：**

```
诊断路径（从具体到全局）            设计路径（从全局到具体）
Mode C / 排查 / 解释工作流         Mode A/B / 改造 / 新增

① 步骤6 search 工作流名称         ① 步骤7 依赖图看全景
② 步骤8 lifecycle 查创建者/消费者  ② 步骤8 lifecycle 看插入位置
③ 步骤4 读 node_configs.json     ③ 步骤6 search 找相似模式
④ 步骤7 依赖图评估下游影响面        ④ 步骤2+3 表+字段+工作流设计
```

**搜索速查：**
```bash
SRCH=~/.claude/skills/hhr-plan/scripts/search.py
$SRCH "关键词" --type workflow -p 几建        # 模糊搜工作流
$SRCH "工作流名" --exact-name -p 几建          # 精确名查找（用户告知名称时优先用）
$SRCH "PID" --pid -p 几建                      # 直接PID查（用户给了PID直接用）
$SRCH "表名" --writes-to -p 几建              # 反查谁写这张表
$SRCH "表名" --reads-from -p 几建             # 反查谁读这张表
$SRCH "字段名" --field-search -p 几建          # 找哪个表有这字段
$SRCH "关键词" --type workflow --all-projects  # 跨项目搜
$SRCH "关键词" --type workflow -p 几建 -f json # JSON输出（给agent）
$SRCH "几建" --check-index                     # 检查索引完整性
```

**工作流定位优先级（从快到慢）：**
1. 用户给了 PID → `--pid` 直查（绕过 FTS，最快）
2. 用户给了工作流名 → `--exact-name`（绕过 FTS，次快）
3. 用户给了关键词 → `--type workflow`（FTS 模糊搜索）
4. 仍找不到 → `--reads-from`/`--writes-to` 反向定位

### 6. 跨项目索引 + 项目初始化

#### 路径 A：Browser 注入（默认，适用于所有项目）
Chrome 登录明道云 → 打开目标应用 → F12 Console → 粘贴执行:
```
~/.claude/skills/hhr-plan/scripts/inject_all.js
```
产出两个文件自动下载: `{项目}_all_workflows.json` + `{项目}_field_map.json`，放入 `~/Documents/workflow-output/{项目名}/`，然后运行：
```bash
python3 scripts/extract-project.py {项目名} --skip-mcp \
  --pids-file ~/Documents/workflow-output/{项目名}/pids.json \
  --nodes-file ~/Documents/workflow-output/{项目名}/nodes.json \
  --base-url "http://{项目域名}"
```
> 新脚本 `inject_all.js` 同时提取工作流节点 + 工作表字段定义（fieldId→fieldName 映射），
> 解决旧脚本 `fieldName: null` 的问题。`generate_node_data.py` 也会自动加载 `_field_map.json` 补全字段名。

#### 路径 B：MCP 代理（需要凭证）
```bash
python3 scripts/extract-project.py {项目名}
```
默认 MCP URL (几建/同技智能): `https://work.jijiansmart.com/mcp?HAP-Appkey=4ba6553626bb83cc&HAP-Sign=...`
其他项目需通过 `--mcp-url` 或环境变量 `MCP_URL` 指定。

---

## 门控协议（内联自检）

设计方案或诊断结论准备输出前，**必须逐条完成以下自检**。任一不通过 → 修正方案 → 重检，全部通过才能输出。

### Gate 1: 依赖图检查（Mode B/C 强制）

```
□ 查过 dependency_graph.json？
  - 涉及多表改动 → 列出入向依赖（谁写这张表）+ 出向依赖（这张表写谁）
  - 新增关联 → 是否产生 DAG 环路？（公理4）
  - 修改字段 → 列出所有读写该字段的工作流
□ 影响面评估完成？
  - 受影响工作流 ≤3 → 列出名称+依赖类型
  - 4-10 → 输出依赖关系图
  - >10 → Hard Stop，等待用户决策
```

> 执行: `python3 ~/.claude/skills/hhr-plan/scripts/rebuild_graph.py 几建 --lifecycle 表名` 查实体生命周期。查 `dependency_graph.json` 的 `edges` 看上下游。

### Gate 2: 逻辑校验

```
□ 数据血缘（公理1）: 新增记录回写父引用？主子表先主后子？查询用记录ID精确查？
□ 人在回路（公理2）: 人工决策→按钮触发（不用定时触发）？审批=或签+退回仅发起节点？审批人为空→拥有者代理？
□ 自文档化（公理3）: 编号=拼音前缀+日期+流水号？布尔字段=是否XX？参数名≠param1/recordId？
□ 单向依赖（公理4）: 新关联是否产生环路？Hub表集中属性？他表字段仅用于只读？
□ 优雅降级（公理5）: 查询空→继续执行？子流程→逐条+中止继续？状态/日期/拥有者→默认值？
```

### Gate 3: 时序校验（涉及工作流修改时强制执行）

```
□ 标注了完整时序 T0(触发)→T1→T2→...→Tn？
□ 列出了每个节点的写入字段？
□ 新节点读取的字段在其插入位置 Tk 时是否已存在？
  - 已知错误模式: T0 就查"流程状态""审批状态" → 这些是后面节点才写入的 → ❌
```

### Gate 4: 字段与实体存在性

```
□ 方案引用的每个字段名在工作表中存在？（查 project_context.json）
□ 方案引用的每个工作表名存在？
□ 新表名/工作流名不与已有名称重复？
□ 新编号前缀不与已有前缀冲突？
```

### Gate 5: 平台可行性

```
□ 涉及的节点类型    → 明道云支持？
□ 涉及的关联方式    → 支持？
□ 子流程嵌套深度    → ≤2层？
□ 总节点数          → ≤10 或已拆分子流程？
□ 同一表多事件触发  → 有并发冲突风险？
```

### Gate 6: 推理质量

```
□ 方案是否过度设计？能否删掉一半节点？
□ 是否有隐藏假设未标注？（标注置信度 HIGH/MEDIUM/LOW）
□ 方案所有决策是否追溯到了公理编号？
□ 是否存在"我推断应该有这个字段"但未验证的情况？
```

任何 Gate 的 □ 未勾完 → **不输出**，先补证据。

Mode D 审计输出前，额外查 `references/mode-d-audit-2026-06-18.md` 确认扫描维度完整。

---

## 默认输出物（三项）

引擎完成工作后，按 `references/templates/output-template.md` 统一格式输出。所有模式（A/B/C/D）共用同一套文档骨架：结论 → 方案概览(表格) → 上下文分析 → 详细配置(表格) → 门控结果。

## Outcome Contract

| 模式 | Done 条件 |
|------|---------|
| Mode A | 表+字段+工作流节点链完整，每条决策追溯公理，Gate 1-6 全部通过 |
| Mode B | 上下文查询 + 依赖图检查 + 影响面评估（Gate 1 强制）+ 时序校验 + Gate 1-6 全部通过 |
| Mode C | 术语映射 + 依赖图影响面 + 根因一句话(概率) + 证据链 + 排除假说；或 Hard Stop: 连续3假说不成立→输出排除清单+已知/未知清单 |
| Mode D | 五维度扫描完成 + 评分卡 + 问题清单(按严重度排序) + Gate 6 通过 |

## 生命周期演进路线

| 状态 | 条件 | 当前 |
|------|------|------|
| `observed` | 1 个项目，公理待交叉验证 | ✅ 已通过（几建：136表/321流） |
| `validating` | 2+ 项目已提取，公理交叉验证进行中 | ✅ 已通过 (6项目审计完成) |
| `validated` | 2+ 项目交叉验证完成，≥80% 公理一致 | ← **当前位置** |
| `locked` | 5+ 项目，公理稳定 | ⬜ |

### 交叉验证矩阵

> 上次更新: 2026-06-18 | 方法: Mode D 审计（Browser 提取升级至 node 级别 + 字段级公理检测）
> 尚策已完成完整审计, 其余 Browser 项目待 node 数据补充后验证

| 公理 | 几建(321流) | 尚策(490流) | 城市运营(324流) | 赫立-合同(41流) | 赫立-人事(26流) | 赫立-研发(25流) |
|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 公理1 数据血缘 | ✅ | ✅ 38/132 | ✅ 29/95 | ⚠️ 0/9 | ✅ 4/11 | ⚠️ 3/9 |
| 公理2 人在回路 | ✅ | ✅ 240/7 | ✅ 130/45 | ✅ 17/2 | ✅ 8/0 | ✅ 7/1 |
| 公理3 自文档化 | ✅ | ✅ 96%中文 | ✅ 政务标准 | ✅ 合同体系 | ✅ 人事体系 | ✅ 研发流程 |
| 公理4 单向依赖 | ✅ 0双向 | ❌ 9对跨域 | ⚠️ 1对(闭环) | ✅ 0双向 | ✅ 0双向 | ✅ 0双向 |
| 公理5 优雅降级 | ✅ | ⚠️ 20/344 | ⚠️ 3/160 | ⚠️ 0/10 | ⚠️ 2/14 | ⚠️ 4/15 |
| **通过** | **4/5** | **3/5** | **3/5** | **3/5** | **4/5** | **3/5** |

**六个项目共识：**
- 公理2(人在回路) 六项目全 ✅ — 最稳定的跨领域公理
- 公理3(自文档化) 六项目全 ✅ — 明道云平台天然支持中文命名
- 公理4(单向依赖) 五项目 ✅/⚠️, 仅尚策 ❌ — 制造供需循环是唯一硬伤
- 公理1/5 Browser提取项目总体偏低, 与几建MCP提取差距明显 — 可能是nodes.json字段序列化深度不同

> 验证方法：对每个项目运行 `hhr-plan` Mode D 审计 → 检查公理约束的 MUST/MUST NOT 在该项目中是否成立 → 标记 ✅/⚠️/❌。2+ 个项目 ≥80% ✅ 时升 `validated`。

## Checkpoint / 接力机制

上下文过长时输出接力提示：

```markdown
# Checkpoint — {项目名} — {日期}
## 当前任务: [简述+进度]
## 已决策事项: [不需要重新确认的结论]
## 关键文件路径: [上下文/工作流]
## 下一步: [1-2句话]
```
