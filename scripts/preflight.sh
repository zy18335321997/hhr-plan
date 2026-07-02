#!/usr/bin/env bash
set -euo pipefail
# hhr-plan preflight — 提交前确定性检查
# 用法: bash scripts/preflight.sh [commit|push]

MODE="${1:-commit}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIOLATIONS=0

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
green(){ printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m⚠  %s\033[0m\n' "$*"; VIOLATIONS=$((VIOLATIONS + 1)); }
fail() { red "✗  $*"; VIOLATIONS=$((VIOLATIONS + 1)); }
ok()   { green "✓  $*"; }

echo "=== hhr-plan preflight (${MODE}) ==="
echo ""

# ── 所有模式: 密钥/敏感信息扫描 ──
echo "[1] 敏感信息扫描"

# 硬编码用户路径
USER_PATHS=$(grep -rn '/Users/[a-z][a-z0-9]*/' "$SKILL_DIR" \
  --include="*.py" --include="*.sh" --include="*.md" --include="*.yaml" \
  | grep -v "implementation-notes" | grep -v ".git" | grep -v "SKILL_DIR" \
  | grep -v "preflight.sh" | grep -v "safety-net-gap-analysis.md" || true)
if [[ -n "$USER_PATHS" ]]; then
    fail "发现硬编码用户路径:"
    echo "$USER_PATHS" | head -5
    echo "  → 替换为 \$HOME 或 \$SKILL_DIR"
else
    ok "无硬编码用户路径"
fi

# API key / token 模式
SECRET_PATTERNS=(
  'sk-[A-Za-z0-9]{20,}'
  'gho_[A-Za-z0-9]{20,}'
  'ghp_[A-Za-z0-9]{20,}'
  'Bearer [A-Za-z0-9+/=]{20,}'
  'HAP-Appkey=[A-Za-z0-9]+&HAP-Sign=[A-Za-z0-9]+'
)
for pattern in "${SECRET_PATTERNS[@]}"; do
    if grep -rEn "$pattern" "$SKILL_DIR" \
         --include="*.py" --include="*.sh" --include="*.md" \
         | grep -v "implementation-notes" | grep -v ".git" \
         | grep -v "safety-net-gap-analysis.md" | grep -v "preflight.sh" > /dev/null 2>&1; then
        HITS=$(grep -rEn "$pattern" "$SKILL_DIR" \
               --include="*.py" --include="*.sh" --include="*.md" \
               | grep -v "implementation-notes" | grep -v ".git" \
               | grep -v "safety-net-gap-analysis.md" | grep -v "preflight.sh" | head -3)
        fail "发现疑似 API key/token: $pattern"
        echo "$HITS"
    fi
done
ok "密钥扫描完成"

# ── 所有模式: Python 语法检查 ──
echo ""
echo "[2] Python 语法检查"
PYTHON_FILES=$(find "$SKILL_DIR/scripts" -name "*.py" | sort)
PY_ERRORS=0
for f in $PYTHON_FILES; do
    if ! python3 -m py_compile "$f" 2>/dev/null; then
        warn "$(basename "$f"): 语法错误"
        PY_ERRORS=$((PY_ERRORS + 1))
    fi
done
if [[ $PY_ERRORS -eq 0 ]]; then
    ok "所有 Python 脚本语法正确 (${PY_ERRORS} errors)"
fi

# ── 所有模式: SKILL.md 格式检查 ──
echo ""
echo "[3] SKILL.md 格式完整性"
if [[ -f "$SKILL_DIR/SKILL.md" ]]; then
    if grep -q "^name:" "$SKILL_DIR/SKILL.md" && grep -q "^description:" "$SKILL_DIR/SKILL.md"; then
        ok "SKILL.md 格式完整"
    else
        fail "SKILL.md 缺少 frontmatter 字段 (name/description)"
    fi
else
    fail "SKILL.md 文件不存在"
fi

# ── 所有模式: 台账验证 ──
echo ""
echo "[4] 合约台账验证"
if python3 "$SKILL_DIR/scripts/verify-ledger.py" 2>/dev/null; then
    ok "coverage-ledger.tsv 格式正确"
else
    fail "coverage-ledger.tsv 验证失败 — 运行 verify-ledger.py 查看详情"
fi

# ── 所有模式: Agent 文件完整性 ──
echo ""
echo "[5] 文件布局检查"

# scripts/ 下必须有 --help
echo "  Scripts --help check:"
SCRIPT_NO_HELP=0
for f in "$SKILL_DIR"/scripts/*.py; do
    fname=$(basename "$f")
    if ! grep -q "add_argument\|--help\|Usage:" "$f" 2>/dev/null; then
        warn "  $fname: 缺少 --help / argparse 定义"
        SCRIPT_NO_HELP=$((SCRIPT_NO_HELP + 1))
    fi
done
if [[ $SCRIPT_NO_HELP -eq 0 ]]; then
    ok "所有 Python 脚本有 --help 定义"
fi

# agents/ 下必须有输出格式
echo "  Agent output-format check:"
AGENT_FILES=(
    "agents/logic-verify.md"
    "agents/platform-verify.md"
    "agents/audit-scanner.md"
    "agents/verification-orchestrator.md"
)
for f in "${AGENT_FILES[@]}"; do
    if [[ -f "$SKILL_DIR/$f" ]]; then
        # 检查是否有"输出格式" section
        if grep -q "输出格式\|Output Format\|output format" "$SKILL_DIR/$f"; then
            ok "$(basename "$f"): 有输出格式定义"
        else
            warn "$(basename "$f"): 缺少输出格式定义"
        fi
    else
        fail "$f 文件不存在"
    fi
done

# ── push 模式额外检查 ──
if [[ "$MODE" == "push" ]]; then
    echo ""
    echo "[6] Push 模式: Doctor 检查"
    if bash "$SKILL_DIR/scripts/doctor.sh" --quiet 2>/dev/null; then
        ok "环境健康检查通过"
    else
        warn "环境健康检查有警告"
    fi

    echo ""
    echo "[7] Push 模式: 工作区状态"
    if git -C "$SKILL_DIR" diff --check 2>/dev/null; then
        ok "无空白字符问题"
    else
        warn "发现空白字符问题 (trailing whitespace)"
    fi
fi

# ── 汇总 ──
echo ""
echo "═══════════════════════════════════"
if [[ $VIOLATIONS -eq 0 ]]; then
    green "preflight 通过 — 0 violations"
    exit 0
else
    red "preflight 失败 — $VIOLATIONS violations"
    exit 1
fi
