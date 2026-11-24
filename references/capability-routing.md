# Capability Routing — 能力域交接协议

hhr-plan 作为统一入口，把应用搭建、线上运营、Compute 应用、HAP 前端与 API、hap 命令行五类意图交接给对应能力。本文件是交接协议与边界的唯一真源；交接后由目标技能自身的真源与门控继续，hhr-plan 不复述其内部规则。

## 交接方式总则

- 交接 = 用 Skill 工具调用目标技能（`hap-mcp-app-builder` / `hap-compute-app` / `hap-api-website` / `hap-apiv3-data` / `hap-view-plugin` / `hap-cli` 系列），把当前已确认的上下文（appId/orgId/项目路径/用户意图）随对话传递；不复制目标技能的步骤正文到本入口。
- 目标技能不可用（Skill 不存在、MCP 未加载、CLI 缺失）时，如实告知用户缺什么、怎么补（见各能力「不可用降级」），不冒充能力存在，不静默降级到不完整的手工实现。
- 凭证边界：不在对话、日志、checkpoint 或任何文件中回显 PAT、Cookie、登录回调信息；`platform.json` 与 checkpoint 规则不变。

## 能力一：HAP 应用助手（明道云 HAP 应用的全生命周期）

**触发意图**：搭建/继续搭建/恢复搭建 HAP 应用；存量应用的修改重构与结构伴随洗数（数据迁移）；线上配置查看与故障修复；日常数据查询统计、记录增删改、审批待办处理、触发业务流程（PBP）。用户发来明道云链接或明确在 HAP 上下文操作应用、工作表、字段、视图、角色、工作流、业务记录/审批单据时。

**交接目标**：Skill `hap-mcp-app-builder`；其工具底座是 MCP `hap_personal_mcp`（api.mingdao.com/mcp，PAT Bearer 认证，用户级配置已写入 `~/.claude.json`）。

**hhr-plan 侧要求**：

- 直接交接，不替它做前置检查（MCP 识别、工具数量门禁、org 连通性校验都是它自己的步骤）。
- 若 hhr-plan 已有该项目的本地数据（`project_context.json`、`_node_data.json` 等），交接时告知可用路径，供其参考，但不得阻止它用线上实时配置为真值。

**与 Mode 的边界**：

| 情形 | 去向 |
|---|---|
| 本地项目数据 + 结构/流程级根因（工作流逻辑、字段联动、依赖关系） | hhr-plan Mode C |
| 线上实时配置、记录数据、或需要直接改线上/执行写操作 | 交接 `hap-mcp-app-builder` |
| 设计规格（design_ir / execution_lock 等）确认后的全应用物理搭建 | 交接 `hap-mcp-app-builder`；仅工作流创建仍走既有 `hap-flow-exec` 交接 |
| 用户意图同时含设计与搭建 | 先 hhr-plan Mode A/B 设计并确认，再按上行走交接 |

**不可用降级**：`hap_personal_mcp` 未加载（本会话未重启过）→ 提示重启客户端或 `/mcp` 重连；PAT 失效 → 让用户在明道云「连接 AI」重新生成令牌更新配置（按 hap-mcp-app-builder 的 MCP_SETUP.md 场景二）。

## 能力二：HAP Compute（网站 / PostgreSQL 数据应用 / 业务函数 / 登录页）

**触发意图**：创建、修改、部署 Compute 网站、PostgreSQL 数据应用、业务函数与应用登录页；Compute 的安装/接入/更新、切换环境、登录组织、状态用量查询。

**交接目标**：Skill `hap-compute-app`；其 CLI 为 `~/.local/bin/hap-compute`（prod 环境，服务 https://compute.mingdao.com；说明包 `~/.local/share/hap-compute/environments/prod/guide`，受管理自动更新已启用）。

**hhr-plan 侧要求**：

- 直接交接；环境选择、版本核对、426 处理、审计说明展示都是 hap-compute-app 自己的协议，hhr-plan 不复述。
- HAP Compute 是独立应用平台（网站/PG/函数），与明道云 APaaS 工作表/工作流不重叠；不把 Compute 意图路由到 Mode A/B。

**登录边界**：安装/接入类任务不要求登录成功才算完成；CLI 未登录（`hap-compute connection` 非零）时单独报告「未登录」，引导用户本人执行：

```bash
hap-compute login --server https://compute.mingdao.com --org <组织ID>
```

浏览器授权由用户本人完成，Agent 不代办、不猜测组织 ID。

**不可用降级**：CLI 缺失 → 按其入口 Skill 的安装流程重装（`/api/skills/install.txt` 直连下载、SHA256 校验、`install-cli.sh`）；入口 Skill 缺失 → 从 `~/.agents/skills/hap-compute-app`（安装器共享入口）恢复薄入口到宿主技能目录。

## 能力三：HAP 前端与 API（hap-api-website / hap-apiv3-data / hap-view-plugin）

来源：github.com/mingdaocom/hap-skills `skills/api` 目录（2026-11-24 安装到 `~/.claude/skills/`）。

**触发意图**：

| 意图 | 交接目标 |
|---|---|
| HAP 作为数据底座的前端项目：官网、前后端分离、内容管理系统；涉及 HAP 后台配置、前端项目结构、API 集成与渲染 | Skill `hap-api-website` |
| HAP V3 开放 API 直接调用：Appkey/Sign/PAT/OAuth 鉴权、Filter 筛选、数据接口读写 | Skill `hap-apiv3-data` |
| HAP 自定义视图插件开发（mdye 脚手架、初始化视图项目、启动调试） | Skill `hap-view-plugin` |

**hhr-plan 侧要求**：

- 直接交接；前端项目结构、鉴权方案选择、脚手架命令都是目标技能自身的真源。
- 这三个技能是软件开发类能力（写前端代码），不进入 Mode A–D。

**与 hap-mcp-app-builder 的边界**：

- 「在明道云后台建表、配字段」是 APaaS 搭建，归属 `hap-mcp-app-builder`；「写前端代码消费这些数据」才路由到本节技能。
- 用户意图同时含后台数据结构与前端代码时（如「用 HAP 搭官网」），交给 `hap-api-website`（其内部会指导后台配置）；若用户意图只搭数据结构、不含前端，仍走 `hap-mcp-app-builder`。

**凭证边界**：V3 API 的 Appkey/Sign/PAT 不得在对话、日志或文件中回显；`hap-apiv3-data` 优先从已配置的 HAP MCP 配置中提取鉴权密钥，不向用户索要明文。

**不可用降级**：对应 Skill 缺失 → 从 hap-skills 仓库 `skills/api/` 重装（tarball 直连 `https://codeload.github.com/mingdaocom/hap-skills/tar.gz/refs/heads/main`，本机 git clone 该仓库直连经常超时）。

## 能力四：hap 命令行（hap-cli 系列）

来源：github.com/mingdaocom/hap-skills `skills/cli` 目录（2026-11-24 安装到 `~/.claude/skills/`）。工具底座是 `hap` CLI（本机已装 `/opt/homebrew/bin/hap`）。

**触发意图**：用 hap 命令操作 HAP 企业平台——通讯录/部门、聊天消息/群组、动态、日程、工作表记录增删改查、工作流与审批待办、自定义页面、角色权限、组织与应用管理、文件上传；已有应用的单点局部修改（加字段、改视图、改工作流、调权限）；复杂筛选与透视聚合统计；多环境/多账号切换或破坏性操作前的环境确认。

**交接目标**：Skill `hap-cli`（主入口）；子技能按需由其内部导航：`hap-cli-app-editor`（已有应用单点修改）、`hap-cli-data-query`（筛选/透视/统计，只读）、`hap-cli-environments`（多环境/多账号守则，破坏性操作前先确认环境）。

**hhr-plan 侧要求**：

- 直接交接；命令语法、筛选 JSON 写法、环境选择是 hap-cli 系列自己的真源，hhr-plan 不复述。
- 交接时如实告知当前已登录的 hap 环境/账号信息（如有），但凭证本身不回显。

**与 hap-mcp-app-builder 的分工**：

| 情形 | 去向 |
|---|---|
| 通讯录/聊天消息/动态/日程/文件上传（MCP 不覆盖） | `hap-cli` |
| 用户明确说「用命令行」「用 hap 命令」 | `hap-cli` 系列 |
| 已有应用的单点局部修改（一个字段/一个视图/一个权限）且用户偏好 CLI | `hap-cli-app-editor` |
| 其余应用搭建/修改、数据运营、审批处理 | 默认 `hap-mcp-app-builder`（hhr-plan 既有主路径） |

两系技能不互相替代；意图不明确且两系都能做时，默认 `hap-mcp-app-builder`，除非用户明示 CLI。

**与 Mode 的边界**：hap-cli 直接读写的业务记录/审批属于线上数据级操作，不进入 Mode C 的本地结构级诊断；本地项目结构/流程级根因分析仍走 Mode C。

**不可用降级**：`hap` 命令缺失 → `pip install hap-cli`（或按 hap-cli SKILL.md 的安装步骤）；目标组织的「CLI 访问策略」未开启 → 引导组织管理员在后台「安全 → 数据与访问 → CLI 访问策略」开启。

## 与 hap-flow-exec 的关系

hap-flow-exec 交接（Mode A/B 设计确认后的工作流创建执行）不变；它和 hap-mcp-app-builder 的分工：前者执行 hhr-plan 已校验的执行合约创建工作流，后者做全应用搭建/存量修改/数据运营。两者不互相替代。
