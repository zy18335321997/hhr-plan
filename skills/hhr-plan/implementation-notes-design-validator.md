# implementation-notes: design_validator.py

## 目标
写一个脚本，自动执行 Gate 1（依赖图检查）和 Gate 4（字段存在性检查），替代人工 □ 自检。

## 设计决策

### 输入
- project_context.json — 表名/字段名全集
- dependency_graph.json — 依赖边，用于检测双向依赖和 DAG 环
- 用户方案文件（Markdown 或 spec JSON）— 解析出引用的表名/字段名

### 检查项

**Gate 4（字段与实体存在性）**：
- 方案引用的每个表名在 project_context.worksheets 中存在？
- 方案引用的每个字段名在对应表的 fields 中存在？

**Gate 1（依赖图检查 — 部分自动化）**：
- 新增关联是否产生双向依赖？
- 新增关联是否产生 DAG 环路？

### 输出
JSON 格式的检查结果，pass/fail + issues 列表。

### 限制
- 方案解析依赖 Markdown 表格格式（按 output-template.md 的规范）
- 如果方案格式不规范，回退到人工检查提示
- Gate 1 的"受影响工作流列表"仍需要查 search.py（无法从此脚本替代）
