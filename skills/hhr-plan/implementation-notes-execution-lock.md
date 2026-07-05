# implementation-notes: execution_lock.json

## 目标
设计方案输出时同步生成机器可读合约文件，对抗上下文漂移。

## 设计决策

### Schema 设计
对标 ppt-master 的 spec_lock.md 设计思路：
- 不是"设计文档的 JSON 版"——是"执行合约"
- 只包含可验证、不可变的设计决策
- 字段值锁定态（px / HEX 级精度）

### 核心段
1. **meta** — 项目/模式/日期/公理覆盖
2. **naming** — 编号前缀/工作流动词/字段约定（锁定后不允许偏离）
3. **sheets** — 每张表的：名称/模块/是否Hub/字段列表（名称+类型+默认值+必填）
4. **workflows** — 每个工作流的：名称/触发方式/节点链(T0..Tn)/时序约束
5. **associations** — 关联方向（从表→目标表/类型/公理依据）
6. **gates** — 门控结果（pass/fail + issues）

### 与 design_validator.py 的关系
- design_validator.py 验证 execution_lock.json 中引用的表/字段是否存在于 project_context.json
- execution_lock.json 本身是设计方案的"锁定快照"
- 工作流：AI 设计 → 生成 execution_lock.json → design_validator.py 验证 → 通过后输出给用户

### 生成 vs 验证
- 主要做"生成"：AI 在设计输出时同步写入 execution_lock.json
- 辅助做"验证"：execution_lock.json 可以被 design_validator.py 校验
- 重读恢复：后续会话可以加载 execution_lock.json 恢复设计状态
