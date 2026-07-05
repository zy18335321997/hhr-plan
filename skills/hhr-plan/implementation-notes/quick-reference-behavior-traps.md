# implementation-notes: quick-reference-behavior-traps

## 目标

给 system-prompt.md 加两个新 section，借鉴 RepoPrompt CE AGENTS.md 的"精确命令 + 行为陷阱"模式。

## 来源分析

| RepoPrompt CE 模式 | hhr-plan 对应物 | 现有位置 |
|---|---|---|
| `make doctor` | `scripts/doctor.sh` | 新建，未在 system-prompt 中引用 |
| `make dev-build` | `python3 scripts/auto_sync.py` | 基础层第6步 |
| `make dev-test FILTER=X` | `python3 scripts/search.py "词"` | 搜索速查(L59-69) |
| "Do not assume..." bullets | 禁止的行为(L110), Hard Stops(L275-286) | 分散在多处 |
| "Prefer X... The fallback is Y" | 无 | 缺失 |

## 设计决策

### 1. Quick Reference 放在最顶部
在 "第零层：元公理" 之前插入。这是 LLM 每次加载 system-prompt 时最早看到的——确保它知道"该执行什么命令"而不是先读到理论。

### 2. Behavior Traps 从分散的警告中提取
从以下来源提取：
- L110 "禁止的行为"
- L275-286 Hard Stops
- L289-304 诚实边界/未解张力
- lessons-learned.md 中的实际排查教训
- MEMORY.md 中的"客户问题诊断方法论"

合并为紧凑的要点列表，每个点都用 "Do not assume..." 或 "Prefer...over..." 开头。

### 3. 不删改现有内容
两个新 section 是插入的，不修改现有公理体系。现有内容保持原样，只做位置调整。

### 4. 改动范围
- system-prompt.md: +Quick Reference (顶部), +Behavior Traps (Hard Stops 之前)
