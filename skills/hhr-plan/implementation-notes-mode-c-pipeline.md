# implementation-notes: Mode C Pipeline 改造

**状态**: ✅ 完成 (2026-06-26)

## 目标
给 Mode C 加 ppt-master 风格的 Pipeline Step 标记和 BLOCKING 点。

## 已完成改动

### Pipeline Overview (文件顶部)
- 添加 ASCII 流图: `Step 0 → Step 1 → Step 2 → Step 2.5 → Step 3 → Step 4 → [Step 5] → Output`
- 每个 Step 标注类型 (⛔ BLOCKING / AUTO / 条件触发)
- 添加 Step 表格（名称+类型+产出物）
- 添加执行纪律声明

### 每步格式统一
- 🚧 **GATE**：入站条件，上一步产出物就绪
- Action：原有逻辑保持不动
- ✅ **Checkpoint**：出站验证清单，阻断不完整推进

### ⛔ BLOCKING 点
1. **Step 0 术语映射**：歧义时停等用户确认（含 PID 多匹配）
2. **Step 3 Hard Stop**：连续 3 假说不成立（保留原有机制）

### 执行纪律
- 非 BLOCKING 步自动连续推进
- Step 1→2→2.5→3→4 为连续 AUTO 链，一步完成立即进入下一步

## 设计决策

### Pipeline 结构
```
Step 0: 术语映射        ⛔BLOCKING(歧义时)
Step 1: 问题路由        → 1a(去哪里查) 或 1b(为什么不迭)
Step 2: 数据流追踪
Step 2.5: 执行状态检查
Step 3: 根因分析
Step 4: 影响面评估
Step 5: 收拢协议        (条件触发)
→ 输出 + 门控自检       ⛔BLOCKING(连续3假说失败时Hard Stop)
```

### BLOCKING 点判断
- Step 0 术语歧义 → ⛔ 必须停，用户澄清后再继续
- Step 0 PID 多匹配 → ⛔ 必须停，用户选择后再继续（已在 system-prompt.md 定义，此处引用）
- 连续 3 假说不成立 → Hard Stop（已有，保留）

### 非 BLOCKING 步：自动推进
- Step 1a/1b: 纯数据查询，无需用户输入
- Step 2 + 2.5: 内部分析 + API 调用，自动推进
- Step 3 + 4: 内部推理，自动推进
- Step 5: 条件触发，自动推进

### 每步格式
🚧 GATE → Action → ✅ Checkpoint

### 偏离
- 保留了原有的 "Hard Stop" 机制（3假说失败），这是 Mode C 特有的，ppt-master 没有等价物
- Gate 1-4 输出前自检保留为最终 Pipeline Step 的内嵌检查，而非独立步骤
- Step 编号从 0 开始保持不变（0/0.5/1a/1b 是当前文档的命名约定），但统一为 Pipeline Step 编号

### 取舍
- 不在输出前加 BLOCKING（诊断结果就是最终交付物，不是中间确认）
- Step 0.5 不独立为 Pipeline Step（它只是 Step 1 的内部路由判断）

### 待确认
- 是否需要在诊断结论输出前加一个 BLOCKING 点让用户确认？当前判断：不需要。Mode C 的用户期望是"给我答案"，不是"让我确认你的分析"。如果根因不确定，通过置信度标注来表达。
