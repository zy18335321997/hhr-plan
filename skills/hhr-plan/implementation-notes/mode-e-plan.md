# Mode E 自动构建 — 推进方案

## 实测结论

经过多轮在几建(self-hosted)上的创建测试，API 能力的结论是确定的：

**稳定可用**: `create-custom-action`, `node add`(线性链), `saveNode config.paths`(分支路径)
**不稳定/不可用**: `saveNode subProcessId=""`(子流程，前期成功后期 500), `saveNode` 创建新节点(始终 500), `batch-add` 对子流程(始终 500)

根因很可能是 **session/auth 状态衰减** — saveNode 在会话早期可用，后期持续 500。几建 self-hosted 的 session 管理与 SaaS 版不同。

## 两条路

### 路 A: 浏览器注入 (推荐)

类比 `inject_all.js` 提取数据，编写 `build_workflow.js` 用浏览器 console 创建工作流。

**优势**:
- 完全绕过服务端 API 的 session 问题
- 可以访问 DOM 中的完整节点配置 API
- 与数据提取走同一条技术栈

**实现步骤**:
1. 分析浏览器中创建工作流的网络请求（Chrome DevTools Network tab）
2. 提取节点创建、配置、发布的 API 调用模式
3. 编写 `build_workflow.js` 从 execution_lock.json 读取设计 → 调内部 API 创建
4. 处理分支子节点挂载、子流程内节点创建

### 路 B: hap-bridge MCP 扩展

当前 hap-bridge 的 MCP 代理有 41 个工具，但大多是数据操作，工作流创建的覆盖不足。

**需要新增的 MCP 工具**:
- `batch_create_process_nodes` — 支持 parentNode 的批量节点创建
- `save_flow_node` — 稳定的节点配置 API（带重试和 session 刷新）
- `publish_process_with_inner` — 自动处理子流程→主流程的发布顺序

## 当前 hhr-plan Mode A 可以做到

设计阶段完全不受 API 限制影响。Mode A Step 4 产出的节点链设计是完整和正确的。只是构建执行需要在 UI 中手动完成或者走浏览器注入路径。

## hap-app-builder 为什么能做到

hap-app-builder 用的是 `api3.mingdao.com/mcp` (SaaS 沙箱)，端点是预配置的，且 MCP 协议自带 session 管理。几建是 self-hosted 部署，没有暴露相同的 MCP 端点。

## 建议优先级

1. **短期**: Mode A Step 4 设计输出增加 `implementation_path: API|UI` 标注
2. **中期**: 编写 `build_workflow.js` 浏览器注入脚本
3. **长期**: 扩展 hap-bridge MCP 代理的工作流创建能力
