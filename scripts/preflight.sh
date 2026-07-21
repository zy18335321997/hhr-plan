#!/usr/bin/env bash
set -euo pipefail
# hhr-plan preflight — 提交前确定性检查
# 用法: bash scripts/preflight.sh [commit|push]

MODE="${1:-commit}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIOLATIONS=0

case "$MODE" in
    commit|push) ;;
    *)
        printf 'Usage: bash scripts/preflight.sh [commit|push]\n' >&2
        exit 2
        ;;
esac

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
fail()  { red "✗  $*"; VIOLATIONS=$((VIOLATIONS + 1)); }
ok()    { green "✓  $*"; }
skip()  { yellow "↷  SKIP: $*"; }

printf '=== hhr-plan preflight (%s) ===\n\n' "$MODE"

# ── 所有模式: 密钥/敏感信息扫描 ──
echo "[1] 敏感信息扫描"
if python3 - "$SKILL_DIR" <<'PY'
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
suffixes = {".json", ".md", ".py", ".sh", ".yaml", ".yml"}
excluded_paths = {
    "scripts/preflight.sh",
}
files = [
    path
    for path in root.rglob("*")
    if path.is_file()
    and path.suffix in suffixes
    and path.relative_to(root).as_posix() not in excluded_paths
    and ".git" not in path.parts
]

line_patterns = (
    ("OpenAI key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("GitHub personal token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    (
        "JWT",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
        ),
    ),
    (
        "Bearer token",
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
    ),
)
hap_pairs = (
    re.compile(
        r"""HAP-Appkey\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?"""
        r""".{0,512}?HAP-Sign\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?""",
        re.DOTALL,
    ),
    re.compile(
        r"""HAP-Sign\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?"""
        r""".{0,512}?HAP-Appkey\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?""",
        re.DOTALL,
    ),
)
user_path = re.compile(r"/Users/[a-z][a-z0-9]*/")
hits = []

def scan_text(relative, text, source):
    for match in user_path.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        hits.append((source, str(relative), line, "硬编码用户路径"))
    for label, pattern in line_patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append((source, str(relative), line, label))
    for pattern in hap_pairs:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append((source, str(relative), line, "HAP Appkey/Sign 凭证对"))

for path in files:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    scan_text(path.relative_to(root), text, "worktree")

staged = subprocess.run(
    [
        "git",
        "-C",
        str(root),
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
    ],
    check=True,
    capture_output=True,
).stdout.split(b"\0")
for raw_relative in staged:
    if not raw_relative:
        continue
    relative = Path(raw_relative.decode("utf-8", errors="surrogateescape"))
    if relative.as_posix() in excluded_paths or relative.suffix not in suffixes:
        continue
    blob = subprocess.run(
        ["git", "-C", str(root), "show", f":{relative.as_posix()}"],
        check=True,
        capture_output=True,
    ).stdout
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        continue
    scan_text(relative, text, "staged")

if hits:
    print("发现疑似敏感信息（值已隐藏）:", file=sys.stderr)
    for source, path, line, label in sorted(set(hits)):
        print(f"  [{source}] {path}:{line}: {label}", file=sys.stderr)
    raise SystemExit(1)
PY
then
    ok "无硬编码用户路径或疑似凭证"
else
    fail "敏感信息扫描失败"
fi

# ── 所有模式: Python 语法检查 ──
echo ""
echo "[2] Python 语法检查"
PY_ERRORS=0
for file in "$SKILL_DIR"/scripts/*.py; do
    if ! python3 -m py_compile "$file"; then
        fail "$(basename "$file"): 语法错误"
        PY_ERRORS=$((PY_ERRORS + 1))
    fi
done
if [[ $PY_ERRORS -eq 0 ]]; then
    ok "所有 Python 脚本语法正确"
fi

# ── 所有模式: SKILL.md 格式检查 ──
echo ""
echo "[3] SKILL.md 格式完整性"
if python3 - "$SKILL_DIR/SKILL.md" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8") if path.is_file() else ""
raise SystemExit(0 if "\nname:" in f"\n{text}" and "\ndescription:" in f"\n{text}" else 1)
PY
then
    ok "SKILL.md 格式完整"
else
    fail "SKILL.md 缺失或缺少 frontmatter 字段 (name/description)"
fi

# ── 所有模式: 台账验证 ──
echo ""
echo "[4] 合约台账验证"
if python3 "$SKILL_DIR/scripts/verify-ledger.py"; then
    ok "coverage-ledger.tsv 格式正确"
else
    fail "coverage-ledger.tsv 验证失败"
fi

# ── 所有模式: 技能注册表一致性 + 引用路径 ──
echo ""
echo "[5] 技能注册表与路径一致性"
REGISTRY_PATH="$SKILL_DIR/references/skill-registry.json"
if python3 - "$REGISTRY_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
with path.open(encoding="utf-8") as file:
    json.load(file)
PY
then
    ok "references/skill-registry.json 存在且 JSON 有效"
else
    fail "references/skill-registry.json 缺失或 JSON 无效"
fi
if python3 "$SKILL_DIR/scripts/skill_discovery.py" validate --strict; then
    ok "skill registry 严格一致，描述符引用路径均存在"
else
    fail "skill registry 或描述符引用路径不一致"
fi

# ── 所有模式: Lock/Agent schema 检查 ──
echo ""
echo "[6] Lock 与 Agent Schema 检查"
LOCK_SCHEMA="$SKILL_DIR/references/schemas/execution-lock-validation-schema.json"
AGENT_SCHEMA="$SKILL_DIR/references/schemas/agent-verification-output.schema.json"
SCHEMA_ERRORS=0
for schema in "$LOCK_SCHEMA" "$AGENT_SCHEMA"; do
    if python3 - "$schema" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
with path.open(encoding="utf-8") as file:
    json.load(file)
PY
    then
        ok "$(basename "$schema") 存在且 JSON 有效"
    else
        fail "$(basename "$schema") 缺失或 JSON 无效"
        SCHEMA_ERRORS=$((SCHEMA_ERRORS + 1))
    fi
done
if [[ $SCHEMA_ERRORS -eq 0 ]]; then
    if python3 "$SKILL_DIR/scripts/contract_compat.py" check-schema; then
        ok "execution lock schema 与 verify-platform.py 一致"
    else
        fail "execution lock schema 与 verify-platform.py 不一致"
    fi
fi

# ── 所有模式: 仅探测 argparse CLI 的 --help ──
echo ""
echo "[7] argparse CLI --help 检查"
if python3 - "$SKILL_DIR" <<'PY'
import ast
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
failures = []

def has_main_guard(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
            continue
        if any(
            isinstance(value, ast.Constant) and value.value == "__main__"
            for value in test.comparators
        ):
            return True
    return False

def uses_argparse(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "argparse" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == "argparse":
            return True
    return False

checked = 0
for path in sorted((root / "scripts").glob("*.py")):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as error:
        failures.append((path.name, f"AST 解析失败: {error}"))
        continue
    if not (has_main_guard(tree) and uses_argparse(tree)):
        continue
    checked += 1
    completed = subprocess.run(
        [sys.executable, str(path), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr or completed.stdout or "无输出"
        failures.append((path.name, detail.strip()))

print(f"已检查 {checked} 个 argparse CLI")
if failures:
    for name, detail in failures:
        print(f"{name}: --help 失败\n{detail}", file=sys.stderr)
    raise SystemExit(1)
PY
then
    ok "argparse CLI --help 均可执行"
else
    fail "一个或多个 argparse CLI --help 执行失败"
fi

# ── 所有模式: Agent 文件完整性 ──
echo ""
echo "[8] Agent 输出格式检查"
if python3 - "$SKILL_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
agent_files = (
    "agents/logic-verify.md",
    "agents/platform-verify.md",
    "agents/audit-scanner.md",
    "agents/verification-orchestrator.md",
)
failures = []
markers = ("输出格式", "固定输出契约", "Output Format", "output format")
for relative in agent_files:
    path = root / relative
    if not path.is_file():
        failures.append(f"{relative}: 文件不存在")
        continue
    text = path.read_text(encoding="utf-8")
    if not any(marker in text for marker in markers):
        failures.append(f"{relative}: 缺少输出格式定义")
if failures:
    print("\n".join(failures), file=sys.stderr)
    raise SystemExit(1)
PY
then
    ok "Agent 文件均有输出格式定义"
else
    fail "Agent 文件布局或输出格式不完整"
fi

# ── 所有模式: 标准库 unittest ──
echo ""
echo "[9] Python unittest"
if (
    cd "$SKILL_DIR"
    python3 -m unittest discover -s tests -p 'test_*.py'
); then
    ok "全部 unittest 通过"
else
    fail "unittest 失败"
fi

# ── 所有模式: Git whitespace 检查 ──
echo ""
echo "[10] Git diff 检查"
if git -C "$SKILL_DIR" diff --check; then
    ok "git diff --check（未暂存）通过"
else
    fail "未暂存改动存在空白字符错误"
fi
if git -C "$SKILL_DIR" diff --cached --check; then
    ok "git diff --cached --check（已暂存）通过"
else
    fail "已暂存改动存在空白字符错误"
fi

# ── push 模式: 本地环境 Doctor ──
if [[ "$MODE" == "push" ]]; then
    echo ""
    echo "[11] Push 模式: Doctor 环境检查"
    if [[ -d "$HOME/Documents/workflow-output" ]]; then
        if bash "$SKILL_DIR/scripts/doctor.sh" --quiet; then
            ok "本地环境 Doctor 无确定性错误"
        else
            fail "本地环境 Doctor 发现错误"
        fi
    else
        skip "$HOME/Documents/workflow-output 不存在；本地环境层检查未运行"
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
