# implementation-notes: agent-consumable-output

## 目标

给 Agent 1/2 的输出加 token 预算版摘要，借鉴 RepoPrompt CE `OutputSummarizer` 的模式：
- 16000 字符硬限制
- 成功输出 ≤25 行，失败输出 ≤100 行
- 去重 + 尾部保留
- 供编排器和其他 Agent 消费时使用

## 设计决策

### 1. 不做完整的 OutputSummarizer
RepoPrompt CE 的 OutputSummarizer 是为编译器输出设计的（解析 Swift 错误、测试失败、样式发现问题），复杂度高。
hhr-plan 只需要对结构化 JSON 做摘要——这比解析自然语言输出简单得多。

### 2. 摘要策略
- 从 Agent 1/2 的 JSON 中提取 `fix_guide` 和 `issues` 作为摘要核心
- 去掉 `node_checks` 中的 pass 项（只保留 fail/delegated）
- 统计数字用一行表示
- easy 问题只列前 10 条，medium 前 5 条，hard 全部列出

### 3. 输出格式
```json
{
  "verdict": "fail",
  "total_issues": 12,
  "by_severity": {"high": 3, "medium": 5, "low": 4},
  "fix_guide": {"easy": [...前10], "medium": [...前5], "hard": [...全部]},
  "top_failures": [前5条 high severity issues],
  "delegated": ["data_link", "no_data_policy", ...]
}
```

### 4. 集成方式
`scripts/summarize-output.py --agent1 a1.json --agent2 a2.json > summary.json`
- 在编排器中，当完整输出超过 token 预算时，用摘要版本替代
- 摘要始终附带完整输出的文件路径，需要时再读取
