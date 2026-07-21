# Behavior Traps — 来自真实失败记录

> 以下每一条都在 2026-07-05 session 中实际发生过。不遵守就会重复这些错误。

## 创建陷阱

### T1: 分步 node add + save-action 产生 phantom nodes
- **现象**: 每次 `node add` 调用产生一对节点（一个可见 + 一个隐藏），导致工作流中出现大量"节点删除"标记
- **根因**: 服务器对 addNode 的处理不是幂等的
- **正确做法**: 只用 `batch-add` 一次性创建全部节点

### T2: saveNode 返回 ok 但字段被静默丢弃
- **现象**: saveNode 返回 "saved"，但 appId、fields、selectNodeId、content 等字段实际未保存
- **根因**: 服务器 side 对部分字段做了过滤，但返回 200
- **正确做法**: 创建后拉 `flowNode/get` 验证关键字段已保存

### T3: 分支 condition.left.node 填错
- **现象**: 分支条件显示"节点删除"或无法引用字段
- **根因**: `left.node` 填了分支自身的 alias，而非数据源节点的 alias
- **正确做法**: `left.node` 始终填**数据来源节点**的 alias（如 get_borrow_record）

### T4: option 字段用中文文字而非 UUID key
- **现象**: 下拉/状态字段更新后值不生效
- **根因**: 平台存储的是 UUID key，不是显示文字
- **正确做法**: 查 `hap worksheet info WS_ID --json` 获取 `options[].key`

### T5: 审批/子流程内部 target.node 用了错误的引用
- **现象**: 审批内部节点无法引用审批记录
- **根因**: 审批内部必须用固定 alias "approval_start"，子流程内部必须用 "sub_trigger"
- **正确做法**: 严格使用固定 alias，不自行命名

### T6: workflow list 看不到刚创建的工作流
- **现象**: `hap workflow list` 返回空或缺少新工作流
- **根因**: 触发器的 saveNode 用 `appList` 而非 `appId` 时，工作流不关联到应用
- **正确做法**: batch-add 时确保 trigger 的 saveNode 使用 `appId`

### T7: 删工作流时 filter 太宽误删
- **现象**: 用关键词搜索并批量删除时，误删了名称中包含该关键词的已有工作流
- **根因**: 未精确匹配 PID 或完整名称
- **正确做法**: 删除前先 list → 精确匹配 → 逐条确认 → 再删除

### T8: batch-add 后 update_record 字段为空
- **现象**: batch-add 创建了 update_record 节点，但 UI 里"更新字段"显示"添加字段"（空）
- **根因**: batch-add 内的 saveNode 静默丢弃 fields。节点骨架创建成功，字段配置丢了
- **正确做法**: Step 4 batch-add 后，用 `scripts/save_actions.py` 并行保存所有 action 字段 + query filter

### T9: 分支 path 的 nodes 不能引用 alias 字符串
- **现象**: `"nodes": ["mark_approving"]` 报错 "string indices must be integers"
- **根因**: batch-add DSL 不支持 path 的 nodes 用 alias 字符串引用 flat array 中的节点
- **正确做法**: 所有分支路径下的节点必须**内联完整定义**在 path.nodes 中

### T10: 审批内层 approve 节点不能引用外部 scope
- **现象**: approve 的 approvers 用 `kind: "field", node: "get_borrow_record"` → 发布失败
- **根因**: approval_block 内部是隔离作用域，只能引用 approval_start
- **正确做法**: approvers 用 `{"kind": "field", "node": "approval_start", "fieldId": "ownerid"}`

### T11: 发布顺序必须先 inner 后 main
- **现象**: 直接 publish 主流程失败
- **根因**: 含 approval_block (mode:create) 和 sub_process (mode:create) 时，内部流程必须先发布
- **正确做法**: 先 publish inner PID（approval → subprocess），最后 publish 主流程

### T12: get_multiple filter 必须用 filters 格式（非 operateCondition）
- **现象**: batch-add 的 filter 配置在 get_multiple 节点上不生效，`operateCondition` 和 `filters` 都为空
- **根因**: 服务器 bug #036489 — 对 `operateCondition` 格式静默丢弃。UI 用的 `filters: [{conditions: [[...]], spliceType: 2}]` 格式才能保存
- **正确做法**: 用 `scripts/save_actions.py`，脚本自动使用 `filters` 格式

### T13: systemField/nowTime 在 get_multiple filter 中可用
- **现象**: 之前认为 schedule + get_multiple + systemField/nowTime 间歇 500
- **根因**: 真正的问题不是 systemField，而是 `operateCondition` 格式。用 `filters` 格式 + conditionId "7" + value "today" 可以正常保存
- **正确做法**: `{"conditionId": "7", "conditionValues": [{"value": "today"}], "filedTypeId": 15}`

### T14: wfstatus 是系统只读字段，不可写入
- **现象**: save-action 返回 "saved" 但 `wfstatus` 的字段配置实际为空
- **根因**: wfstatus 是平台管理的系统字段，所有 CLI 方式都无法写入
- **正确做法**: 用自定义单选字段代替 wfstatus，如"审批状态"字段

## 行为陷阱

### B1: 擅自简化设计方案
- **现象**: 觉得设计太复杂，自己"优化"成更简单的版本
- **后果**: 用户看到的与设计方案不一致，需要反复纠正
- **规则**: 设计方案是权威输入。觉得设计有问题 → 报告，不自行修改

### B2: 不验证就声称完成
- **现象**: hap CLI 返回成功就告诉用户"完成了"
- **后果**: 实际配置缺失，用户打开发现不对
- **规则**: Step 5 结构验证通过才能声称完成

### B3: 对失败用重试替代排查
- **现象**: batch-add 失败 → 重试 → 又失败 → 再重试
- **后果**: 掩盖根因，浪费时间，可能产生垃圾数据
- **规则**: 失败 → Hard Stop → 分析错误 → 修正 → 重新执行

### B4: 同时操作多个工作流
- **现象**: 创建 A 工作流的同时也创建 B 工作流
- **后果**: 上下文混淆，可能操作错误的 PID
- **规则**: 一次只处理一个工作流
