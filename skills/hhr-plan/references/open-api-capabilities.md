# Mingdao Open API — 能力参考

> 来源: `https://apifox.mingdao.com` — 明道云 HAP 平台开放 API 文档 (42 端点)
> 鉴权: AppKey + Sign (HMAC 签名)
> 基础 URL: `https://api.mingdao.com` (推测, 需确认具体域名)

## 鉴权

```
所有请求需携带:
  Header: AppKey: <your_app_key>
  Header: Sign: <HMAC_SHA256_signature>

Sign 算法: HMAC-SHA256(AppSecret, requestBody || queryString)
```

详见 Apifox 文档中的"鉴权信息"页。

## API 端点对照表

### 应用管理 (3)

| 方法 | 路径 | 说明 | hhr-plan 用途 |
|------|------|------|-------------|
| GET | `/v3/app` | 获取应用信息 | 项目上下文加载 |
| POST | `/v3/app/items/batch` | 批量创建应用项 | Mode A 自动建模块 |
| POST | `/v3/app/sections/batch` | 批量创建应用项分组 | Mode A 自动建分组 |
| GET | `/v3/app/knowledge/list` | 获取知识库列表 | 查询 AI 知识库 |
| GET | `/v3/app/knowledge/search` | 搜索知识库 | 检索 AI 知识 |

### 工作表 (7)

| 方法 | 路径 | 说明 | hhr-plan 用途 |
|------|------|------|-------------|
| GET | `/v3/app/worksheets/list` | 获取工作表列表 | 项目扫描 |
| GET | `/v3/app/worksheets` | 获取工作表列表 (分页) | 项目扫描 |
| POST | `/v3/app/worksheets` | **新建工作表** | Mode A 自动建表 |
| GET | `/v3/app/worksheets/{id}` | **获取工作表结构** (含 Rollup/Lookup/Formula 完整配置) | 核心! 替代 MD 格式的 `get_worksheet_structure` |
| PUT | `/v3/app/worksheets/{id}` | **更新工作表结构** | Mode B 自动改字段 |
| DELETE | `/v3/app/worksheets/{id}` | 删除工作表 | 清理 |

### 行记录 (11)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v3/app/worksheets/{id}/rows` | 新建行记录 |
| GET | `/v3/app/worksheets/{id}/rows/list` | 获取行记录列表 |
| GET | `/v3/app/worksheets/{id}/rows/{row_id}` | 获取行记录详情 |
| PUT | `/v3/app/worksheets/{id}/rows/{row_id}` | 更新行记录 |
| DELETE | `/v3/app/worksheets/{id}/rows/{row_id}` | 删除行记录 |
| POST | `/v3/app/worksheets/{id}/rows/batch` | 批量新增行记录 |
| PUT | `/v3/app/worksheets/{id}/rows/batch` | 批量更新行记录 |
| DELETE | `/v3/app/worksheets/{id}/rows/batch` | 批量删除行记录 |
| GET | `/v3/app/worksheets/{id}/rows/{row_id}/relations/{field}` | 获取关联记录 |
| GET | `/v3/app/worksheets/{id}/rows/pivot` | 获取行记录透视数据 |
| GET | `/v3/app/worksheets/{id}/rows/{row_id}/share-link` | 获取记录分享链接 |
| GET | `/v3/app/worksheets/{id}/rows/{row_id}/logs` | 获取行记录日志 |
| GET | `/v3/app/worksheets/{id}/rows/{row_id}/discussions` | 获取行记录讨论 |

### 工作流 — 读 (5)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v3/app/workflows` | 获取工作流列表 |
| GET | `/v3/app/workflows/{id}` | 获取工作流结构详情 |
| GET | `/v3/app/workflow/processes` | 获取触发流程列表 |
| GET | `/v3/app/workflow/processes/{id}` | 获取触发流程详情 |
| GET | `/v3/app/workflow/hooks/{process_id}` | 获取工作流 Hook 列表 |
| GET | `/v3/app/workflow/{ws_id}/rows/{row_id}/approval/list` | 根据行记录获取审批流程执行列表 |
| GET | `/v3/app/workflow/{ws_id}/rows/{row_id}/approval/{id}` | 获取审批流程执行详情 |

### 工作流 — 写 (6) ⭐ 新增能力

| 方法 | 路径 | 说明 | hhr-plan 意义 |
|------|------|------|-------------|
| POST | `/v3/app/workflows` | **创建工作流** | Mode A 自动创建 |
| POST | `/v3/app/workflows/{id}/nodes/batch` | **批量添加工作流节点** | 设计方案直接写入 |
| DELETE | `/v3/app/workflows/{id}/nodes/{node_id}` | **删除工作流节点** | Mode B 自动清理 |
| POST | `/v3/app/workflows/{id}/validate` | **验证工作流** | 设计后自动校验 — 新门控 |
| POST | `/v3/app/workflows/{id}/publish` | **发布工作流** | 一键部署 |
| PUT | `/v3/app/workflows/{id}` | 更新工作流 | Mode B 修改 |

### 组织/人员 (6)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v3/app/roles` | 获取角色列表 |
| GET | `/v3/app/roles/{id}` | 获取角色详情 |
| POST | `/v3/app/roles/{id}/members` | 添加角色成员 |
| DELETE | `/v3/app/roles/{id}/members` | 移除角色成员 |
| DELETE | `/v3/app/roles/users/{user_id}` | 成员退出所有角色 |
| GET | `/v3/users/lookup` | 查找成员 |
| GET | `/v3/departments/lookup` | 查找部门 |
| GET | `/v3/regions` | 获取地区信息 |

### 视图/自定义页面/统计图 (4)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v3/app/worksheets/{id}/views/batch` | 批量创建视图 |
| PUT | `/v3/app/custom-pages/{id}` | 更新自定义页面 |
| POST | `/v3/app/worksheets/{id}/charts` | 创建统计图 |
| POST | `/v3/app/worksheets/{id}/custom-actions/batch` | 批量创建自定义动作 (按钮) |

### 对话机器人 (1)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v3/app/chatbots` | 新建对话机器人 |

### 选项集 (3)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v3/app/optionsets` | 获取选项集列表 |
| GET | `/v3/app/optionsets/{id}` | 获取选项集详情 |
| — | — | 创建/编辑/停用选项集 |

## 当前认证路径 vs Open API

| 路径 | 认证方式 | 覆盖范围 | 何时用 |
|------|---------|---------|--------|
| hap-bridge MCP 代理 | HAP-Appkey + HAP-Sign (URL 内嵌) | 41 个数据操作工具 (读+写) | 当前所有数据操作 |
| hap-bridge CLI (`wf-*`) | Chrome cookies (md_pss_id) | 工作流读操作 | 工作流节点/配置查询 |
| hap-bridge CLI (`wf-* --chrome`) | Chrome AppleScript | 工作流写操作 (CSRF bypass) | 工作流创建/删除/发布 |
| **Open API** | AppKey + Sign (HTTP Header) | **42 个 REST 端点** (读写全覆盖) | 未来: 独立 REST 调用, 不依赖 Chrome |

> **当前推荐**: 继续使用 hap-bridge (MCP + CLI) 做读写。Open API 是**未来升级路径**——当需要自动化创建工作流/节点/验证/发布时, 切换到 Open API 认证。

## 与 hhr-plan 验证管道的集成思路

```
当前:  设计方案 → Agent 1 + Agent 2 → 输出 Markdown (人工实施)

未来:  设计方案 → Agent 1 + Agent 2 → verify-platform.py
                  ↓ (通过后)
              POST /v3/app/workflows → 创建工作流
              POST .../nodes/batch → 写入节点链
              POST .../validate → 平台校验
              POST .../publish → 发布
                  ↓
              输出: "已部署" + 工作流 URL
```
