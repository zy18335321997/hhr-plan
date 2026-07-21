# hhr-plan vs RepoPrompt CE — 安全网差距分析

> 2026-07-02 | 核心问题: "不该出错的地方就用脚本"

## RepoPrompt CE 的 11 层安全网

| 层 | 实现 | 防止什么错误 |
|----|------|------------|
| 1. 源文件布局检查 | `source_layout_guardrails.sh` (317行) | 文件放错目录、退役代码回归、测例泄漏到产品代码 |
| 2. 第三方完整性 | `swiftpm_notice_guardrails.sh` | 依赖变更后漏更新 license 声明 |
| 3. 贡献者准入 | `contributor_allowlist_guardrails.sh` | 未授权用户提交 PR |
| 4. 依赖版本锁定 | `Package.swift` exact + revision pins | 浮动版本导致构建不可复现 |
| 5. 格式化/Lint | SwiftFormat + SwiftLint (15规则+1自定义) | 代码风格不一致 |
| 6. 提交前检查 | `preflight.sh` (commit/push 双模式) | 带 secret 的代码被提交、guardrails 被跳过 |
| 7. 密钥扫描 | gitleaks (staged-index + outgoing-range) | 密钥泄露到 git 历史 |
| 8. CI/CD | GitHub Actions (3 并行 job) | PR 合并前未通过构建/测试/style检查 |
| 9. Conductor 守护进程 | `conductor.py` (38K tokens) | 并发构建互相覆盖、测试hang住 |
| 10. 测试合约台账 | `test-suite-contract-ledger.tsv` | 测试被意外删除、合约回归 |
| 11. 环境健康检查 | `doctor.sh` (7阶段) | 工具链未就绪 |

## hhr-plan 当前安全网

| 层 | hhr-plan 实现 | 覆盖度 |
|----|-------------|:--:|
| 1. 源文件布局 | ❌ 无 | 0% |
| 2. 第三方完整性 | ❌ 无 (无外部依赖) | N/A |
| 3. 贡献者准入 | ❌ 无 | 0% |
| 4. 依赖版本锁定 | ❌ 无 | 0% |
| 5. 格式化/Lint | ❌ 无 | 0% |
| 6. 提交前检查 | ⚠️ stop-gate-check.py (仅 Stop hook) | 20% |
| 7. 密钥扫描 | ❌ 无 (手工清理) | 0% |
| 8. CI/CD | ❌ 无 | 0% |
| 9. 守护进程 | N/A (单 Agent, 不需要) | N/A |
| 10. 测试合约 | ⚠️ coverage-ledger.tsv (无测试) | 30% |
| 11. 环境健康检查 | ✅ doctor.sh (5层) | 90% |
| 验证闸门 | ✅ verify-platform.py + validate-agent-output.py | 80% |

## 差距清单：应该现在就加脚本的

### Gap 1: 提交前检查 (优先级最高)

RepoPrompt CE 的 `preflight.sh` 在每次 commit/push 前跑。hhr-plan 需要等价物。

**应该加的脚本**: `scripts/preflight.sh`
```bash
# commit 模式
bash scripts/preflight.sh commit
  → 检查敏感信息 (gitleaks or grep patterns)
  → 验证 SKILL.md 格式完整
  → 验证所有 .md 文件中无硬编码用户目录
  → 运行 verify-ledger.py

# push 模式
bash scripts/preflight.sh push
  → commit 模式的所有检查
  → 检查工作区干净
  → 运行 doctor.sh
  → 运行 verify-platform.py 自测
```

### Gap 2: 密钥/敏感信息扫描

当前手工清理了 macOS 用户目录硬编码和个人信息，但无法防止未来再引入。

**应该加的检查**:
```bash
# 敏感模式清单
- /Users/[a-z]+/              # 硬编码用户路径
- sk-.*                       # API key 前缀
- gho_.*                      # GitHub token
- HAP-Appkey=                 # 除非在 .env 中
- Bearer\s+[A-Za-z0-9+/=]{20} # Bearer token
```

### Gap 3: CI/CD

RepoPrompt CE 每次 PR 自动跑 style + build + test + secret-scan。

hhr-plan 可以加的 GitHub Actions:
```yaml
# .github/workflows/ci.yml
- doctor.sh                    # 环境检查
- verify-ledger.py             # 台账完整性
- verify-platform.py --selftest # 平台校验自测
- validate-agent-output.py --selftest # 格式校验自测
```

### Gap 4: 格式化检查

Python 脚本应该有基本的格式一致性。

**应该加的**:
```bash
# 检查 Python 脚本中无 bare except
# 检查 .md 文件中无 trailing whitespace
# 运行 python3 -m py_compile 确保语法正确
```

### Gap 5: 文件布局检查

当前 hhr-plan 没有源文件布局规范。应该定义并检查：
- `scripts/` 下所有 .py 文件必须有 `--help`
- `agents/` 下所有 .md 文件必须有 `## 输出格式` section
- `references/` 下无 implementation-notes

## 优先级排序

```
P0 (今天能做):
  1. preflight.sh (commit 模式)
  2. 敏感信息扫描 patterns
  3. Python 脚本语法检查

P1 (本周):
  4. CI/CD (GitHub Actions)
  5. preflight.sh (push 模式)
  6. 文件布局检查

P2 (后续):
  7. 格式化自动化 (black/isort for Python)
  8. 贡献者准入 (如需要)
```
