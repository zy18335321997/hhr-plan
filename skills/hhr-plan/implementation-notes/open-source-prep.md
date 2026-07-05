# implementation-notes: open-source-prep

## 目标

将 hhr-plan skill 开源到 GitHub，参考 RepoPrompt CE 的开源结构。

## 敏感扫描结果

| 类型 | 位置 | 处理方式 |
|------|------|---------|
| `/Users/mac/` 硬编码路径 | agents/*.md, verification-orchestrator.md, runtime-probe.md, mode-d-audit.md | 替换为 `$SKILL_DIR` 或 `~/.claude/skills/hhr-plan` |
| "胡浩然" 个人信息 | SKILL.md, system-prompt.md | 替换为通用名 "Mingdao APaaS 设计引擎" |
| "huhaoran-perspective" | (仅在 references,已不存在) | — |
| zy-signflow 外部依赖 | platform-verify.md | 改为环境变量 `$WORKFLOW_NODES_GUIDE_PATH`，文档说明 |
| 项目名 (几建/尚策/赫立) | references/topology-*.md | 保留（作为示例数据），加 EXAMPLE 标记 |
| implementation-notes/ | 全部 | 加入 .gitignore |
| API keys / tokens | 未发现 | — |

## 需要创建的文件

1. `README.md` — 项目介绍、安装、使用
2. `LICENSE` — Apache 2.0 (同 RepoPrompt CE)
3. `CONTRIBUTING.md` — 贡献指南
4. `.gitignore` — 排除 implementation-notes, .DS_Store, 临时文件
5. `docs/architecture/` — 架构概览（从 system-prompt 摘要）

## 需要修改的文件

1. agents/verification-orchestrator.md — 路径替换
2. agents/platform-verify.md — 路径替换 + zy-signflow 依赖
3. agents/audit-scanner.md — 路径替换
4. built-in-skills/mode-d-audit.md — 路径替换
5. references/runtime-probe.md — 路径替换
6. SKILL.md — 去个人信息
7. system-prompt.md — 去个人信息

## 处理外部依赖 (zy-signflow)

platform-verify.md 引用了 `/Users/mac/.claude/skills/zy-signflow/references/workflow-nodes-complete-guide.md`。
这个文件是明道云官方节点指南，对平台校验至关重要。

方案: 将其作为可选依赖文档化。在 README 中说明：
```
# 安装依赖
## 必需
- Python 3.10+
- hap-bridge CLI

## 可选（平台校验 Agent）
- 明道云官方节点指南: 将 workflow-nodes-complete-guide.md 放到任意路径，
  通过 WORKFLOW_NODES_GUIDE_PATH 环境变量指定
```

## 开源 checklist

- [x] 扫描敏感信息
- [ ] 创建 README.md
- [ ] 创建 LICENSE (Apache 2.0)
- [ ] 创建 CONTRIBUTING.md
- [ ] 创建 .gitignore
- [ ] 修改所有硬编码路径
- [ ] 去个人信息
- [ ] 处理外部依赖引用
- [ ] 验证所有脚本可运行
