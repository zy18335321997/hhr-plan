# implementation-notes: platform-validate-gate

## 目标

创建 Gate 4: 平台原生校验，作为"地面真相"层。

## 设计决策

### 1. 为什么是 Gate 4 而非 Gate 0
- Gate 1-3 是 LOCAL 检查（免费、快速、不需要平台连接）
- Gate 4 需要平台连接（Chrome cookies 或 AppKey+Sign）
- 逻辑上先跑本地检查，通过后再跑平台检查（节省平台资源）

### 2. 认证路径
- Primary: hap-bridge internal API (Chrome cookies, `md_pss_id`)
- Fallback: Open API (AppKey + Sign) — 需要先在 apifox.mingdao.com 获取凭证

### 3. 实现方式
`scripts/platform-validate.py`:
- 接收 workflow_id 或 execution_lock.json
- 调用平台验证 API
- 返回平台原生校验结果
- 如果没有认证 → 输出 "SKIPPED: no platform auth" (不阻断)

### 4. 为什么跳过时不阻断
平台校验是增强而非必需。如果用户没有配置认证，不应该阻止 hhr-plan 工作。
但当认证可用时，平台校验的结果优先级高于 Agent 1/2 的判断。
