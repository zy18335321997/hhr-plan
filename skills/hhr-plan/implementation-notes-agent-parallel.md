# implementation-notes: Agent 并行校验

## 目标
让现有的 3 个 Agent 定义从"文档引用"变成"实际执行的并行子代理"。

## 现状
- Agent 定义已存在：logic-verify / platform-verify / audit-scanner
- Mode A Step 7 说"启动 Agent 1 + Agent 2"但没有实际执行机制
- Mode D 说"启动 Agent 3"同样没有实际执行

## 方案

### 核心机制
不是写 Python 脚本——Agent 校验需要 LLM 推理能力（检测永假命题、判断逻辑完备性）。方案是：

1. **verification-orchestrator.md** — 编排协议，主 Agent 在 Step 7 时加载
2. **预处理器脚本** — 将 execution_lock.json 压缩为 Agent 可读的简洁格式
3. **并行调用** — 主 Agent 同时启动 logic-verify 和 platform-verify 作为 sub-agent
4. **结果合并** — 两个 Agent 的 JSON 输出合并为一个统一裁决

### 调用流程
```
主 Agent 在 Mode A Step 7:
  1. 加载 verification-orchestrator.md
  2. 运行 agent_prepare.py 生成 agent 上下文包
  3. 并行调用 Agent(logic-verify) + Agent(platform-verify)
  4. 收集两个 JSON 结果
  5. 合并裁决：双 pass → 自动输出 / 任一 fail → 修正后重检
```

### 与 ppt-master 的对应
- ppt-master: svg_quality_checker.py 自动检测 SVG 违规
- hhr-plan: Agent 并行校验替代自动脚本（因为需要 LLM 推理）

### 偏离
- Agent 1 (logic-verify) 的部分检查项（Gate 4 字段存在性）已被 design_validator.py 覆盖——Agent 加载验证器结果，不重复跑
