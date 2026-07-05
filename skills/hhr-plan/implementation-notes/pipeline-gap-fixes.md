# implementation-notes: pipeline-gap-fixes

## 修复的 6 个缺口

### 1. Mode A Step 7 缺少 verify-platform.py 预检
Mode B Step 3 先跑 design_validator.py + verify-platform.py 再进 Agent 校验，Mode A 缺失这步。
→ 在 Mode A Step 7 开头加：先跑 verify-platform.py 和 design_validator.py

### 2. "修正→重检"无回退指向
当 Agent fail 时，不知道回到哪个设计步骤。
→ 在 verification-orchestrator.md 加回退映射表

### 3. Agent 2 缺 workflow-nodes-complete-guide.md
编排器的 Agent 2 prompt 没传节点指南路径。
→ prompt 中加输入文件路径

### 4. "修正2次仍fail"行为模糊
→ 明确：输出 LOW 置信度方案 + 醒目的争议点标注，由用户决策

### 5. Agent 1 timeline 条件性
timeline 校验依赖 T0→Tn 标注，但非所有修改都产出标注。
→ 加条件判断：设计方案包含标注→执行timeline；否则→标记n/a

### 6. execution_lock.json 无版本
→ 在 schema 和 lock_manager.py 中加 version 字段
