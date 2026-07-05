# implementation-notes: contract-ledger

## 目标

创建覆盖台账 (TSV) 替代当前的 evidence-matrix.md，借鉴 RepoPrompt CE `test-suite-contract-ledger.tsv` 模式：
- 每条公理约束一行，带精确 ID
- 增量更新（只修改变化行，不重新生成）
- 可被脚本验证格式完整性

## 设计决策

### 1. TSV 格式
选择 TSV (tab-separated values) 而非 YAML/JSON，原因：
- 简单、diff 友好、git 可合并
- RepoPrompt CE 同样用 TSV
- 可以在 Excel/Numbers 中打开编辑

### 2. 列定义
```
axiom_id | constraint_id | constraint_type | description | evidence_source | positive_cases | known_failures | validated_projects | last_validated | status
```

### 3. 和 RepoPrompt CE 的对应

| RepoPrompt CE ledger | hhr-plan coverage ledger |
|---|---|
| test_id (exact XCTest ID) | constraint_id (e.g., "1.1", "4.3") |
| domain, layer | axiom_id (1-5) |
| primary_contract | constraint_type + description |
| scenario_count | positive_cases |
| oracle | known_failures |
| failure_risk | (implicit in known_failures) |
| runtime_cost | (not applicable) |

### 4. 验证脚本
`scripts/verify-ledger.py` — 验证 TSV 格式、检查所有公理约束都被覆盖、无重复 ID。
