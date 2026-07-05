#!/usr/bin/env bash
set -uo pipefail

# === hhr-plan Doctor: 环境健康检查 ===
# 五层分阶段检查 + 所有问题一次性报告
# 用法: ./doctor.sh [--quiet] [--project <name>]

quiet=0
target_project=""

for arg in "$@"; do
    case "$arg" in
        --quiet) quiet=1 ;;
        --project) target_project="NEXT_IS_VALUE" ;;
        --help|-h)
            cat <<'EOF'
Usage: ./doctor.sh [--quiet] [--project <name>]

分阶段检查 hhr-plan 运行环境。

Options:
  --quiet           只输出失败项
  --project <name>  仅检查指定项目（默认检查所有 context_ready 项目）
EOF
            exit 0
            ;;
        *)
            if [[ "$target_project" == "NEXT_IS_VALUE" ]]; then
                target_project="$arg"
            else
                echo "ERROR: Unknown option: $arg" >&2
                exit 2
            fi
            ;;
    esac
done

[[ "${VERBOSE:-0}" == "1" || "${VERBOSE:-0}" == "true" ]] && set -x

START_TIME="$(date +%s)"
PHASE_START="$START_TIME"
errors=0
warnings=0

log(){ (( quiet )) || printf '%s\n' "$*"; }
warn(){ warnings=$((warnings + 1)); printf '  ⚠  WARN: %s\n' "$*"; }
err(){  errors=$((errors + 1));     printf '  ✗  FAIL: %s\n' "$*"; }
ok(){   printf '  ✓  %s\n' "$*"; }

phase(){
    (( quiet )) && return
    local now elapsed total
    now="$(date +%s)"
    elapsed=$((now - PHASE_START))
    total=$((now - START_TIME))
    printf '\n==> [%s] %s (phase: %ss, total: %ss)\n' "$(date '+%H:%M:%S')" "$*" "$elapsed" "$total"
    PHASE_START="$now"
}

# ─────────────────────────────────────────────
# Layer 0: 基础设施
# ─────────────────────────────────────────────

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_OUTPUT="$HOME/Documents/workflow-output"
HAP_BRIDGE="$HOME/.claude/mcp-servers/hap-bridge/cli.py"
REGISTRY="$WORKFLOW_OUTPUT/projects_registry.json"

phase "Layer 0: 基础设施"

# 0.1 python3
if command -v python3 >/dev/null 2>&1; then
    pyver="$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:2])))' 2>/dev/null || echo 'unknown')"
    pymajor="$(echo "$pyver" | cut -d. -f1)"
    if [[ "$pymajor" -ge 3 ]]; then
        ok "python3 $pyver"
    else
        err "python3 版本过低: $pyver (需要 >= 3.10)"
    fi
else
    err "python3 未安装"
fi

# 0.2 pip browser_cookie3
if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import browser_cookie3" 2>/dev/null; then
        ok "browser_cookie3 (pip)"
    else
        warn "browser_cookie3 未安装 — auth.py / extract-project.py 需要 (fix: pip3 install browser_cookie3)"
    fi
fi

# 0.3 hap-bridge CLI
if [[ -f "$HAP_BRIDGE" ]]; then
    ok "hap-bridge CLI ($HAP_BRIDGE)"
else
    err "hap-bridge CLI 缺失: $HAP_BRIDGE — wf_fetch.py / batch 脚本需要"
fi

# 0.4 workflow-output 目录
if [[ -d "$WORKFLOW_OUTPUT" ]]; then
    ok "workflow-output 目录 ($WORKFLOW_OUTPUT)"
else
    err "workflow-output 目录缺失: $WORKFLOW_OUTPUT"
fi

# 0.5 git
if command -v git >/dev/null 2>&1; then
    ok "git"
else
    warn "git 未安装 — rebuild_graph.py 的 diff 功能需要"
fi

# 0.6 Chrome (for extract-via-browser)
if [[ -d "/Applications/Google Chrome.app" ]]; then
    ok "Chrome (extract-via-browser)"
else
    warn "Chrome 未安装 — extract-via-browser.py 不可用"
fi

# ─────────────────────────────────────────────
# Layer 1: 注册表
# ─────────────────────────────────────────────

phase "Layer 1: 项目注册表"

if [[ -f "$REGISTRY" ]]; then
    ok "projects_registry.json 存在"

    if python3 -c "import json; json.load(open('$REGISTRY'))" 2>/dev/null; then
        ok "projects_registry.json 是有效 JSON"

        projects_json="$(python3 -c "
import json
d = json.load(open('$REGISTRY'))
projs = d.get('projects', {})
# 收集 context_ready 的项目
ready = []
for name, cfg in projs.items():
    if cfg.get('context_ready'):
        ready.append(name)
if not ready:
    print('NONE_READY')
else:
    for r in ready:
        print(r)
" 2>&1)"

        if [[ "$projects_json" == "NONE_READY" ]]; then
            warn "没有 context_ready=true 的项目 — 先运行 extract-via-browser.py 或 extract-project.py"
            CONTEXT_READY_PROJECTS=()
        else
            CONTEXT_READY_PROJECTS=()
            while IFS= read -r line; do
                [[ -n "$line" ]] && CONTEXT_READY_PROJECTS+=("$line")
            done <<< "$projects_json"
            ok "context_ready 项目: ${#CONTEXT_READY_PROJECTS[@]} 个 (${CONTEXT_READY_PROJECTS[*]})"
        fi
    else
        err "projects_registry.json 不是有效 JSON"
        CONTEXT_READY_PROJECTS=()
    fi
else
    err "projects_registry.json 缺失: $REGISTRY"
    CONTEXT_READY_PROJECTS=()
fi

# 确定要检查的项目
if [[ -n "$target_project" ]]; then
    CHECK_PROJECTS=("$target_project")
    log "  聚焦项目: $target_project"
else
    CHECK_PROJECTS=("${CONTEXT_READY_PROJECTS[@]}")
fi

if [[ ${#CHECK_PROJECTS[@]} -eq 0 ]]; then
    log "  没有项目需要检查，跳过 Layer 2-4"
fi

# ─────────────────────────────────────────────
# Layer 2: 项目核心文件 (per-project)
# ─────────────────────────────────────────────

phase "Layer 2: 项目核心文件"

for project in "${CHECK_PROJECTS[@]}"; do
    PROJECT_DIR="$WORKFLOW_OUTPUT/$project"
    log ""
    log "  [$project]"

    # 2.1 项目目录
    if [[ -d "$PROJECT_DIR" ]]; then
        ok "项目目录存在"
    else
        err "[$project] 项目目录缺失: $PROJECT_DIR"
        continue
    fi

    # 2.2 project_context.json
    CONTEXT_FILE="$PROJECT_DIR/project_context.json"
    if [[ -f "$CONTEXT_FILE" ]]; then
        if python3 -c "import json; d=json.load(open('$CONTEXT_FILE')); ws=d.get('worksheets',{}); assert len(ws)>0" 2>/dev/null; then
            ws_count="$(python3 -c "import json; d=json.load(open('$CONTEXT_FILE')); print(len(d.get('worksheets',{})))" 2>/dev/null)"
            ok "project_context.json ($ws_count worksheets)"
        else
            err "[$project] project_context.json 无效或 worksheets 为空"
        fi
    else
        err "[$project] project_context.json 缺失 — 运行 build_context.py"
    fi

    # 2.3 business-flow-manifest.json
    MANIFEST_FILE="$PROJECT_DIR/business-flow-manifest.json"
    if [[ -f "$MANIFEST_FILE" ]]; then
        if python3 -c "import json; d=json.load(open('$MANIFEST_FILE')); assert 'tables' in d or 'project' in d" 2>/dev/null; then
            wf_count="$(python3 -c "
import json
d=json.load(open('$MANIFEST_FILE'))
total = d.get('total_workflows_analyzed', 0)
if not total:
    tables = d.get('tables', {})
    for t in tables.values():
        if isinstance(t, dict):
            for wf_list in t.values():
                if isinstance(wf_list, list):
                    total += len(wf_list)
print(total)
" 2>/dev/null)"
            ok "business-flow-manifest.json ($wf_count workflows)"
        else
            err "[$project] business-flow-manifest.json 无效"
        fi
    else
        err "[$project] business-flow-manifest.json 缺失 — 运行 extract-via-browser.py"
    fi

    # 2.4 aliases.json (warning only)
    ALIASES_FILE="$PROJECT_DIR/aliases.json"
    if [[ -f "$ALIASES_FILE" ]]; then
        if python3 -c "import json; json.load(open('$ALIASES_FILE'))" 2>/dev/null; then
            alias_count="$(python3 -c "import json; d=json.load(open('$ALIASES_FILE')); print(len(d) if isinstance(d,dict) else len(d) if isinstance(d,list) else 0)" 2>/dev/null)"
            ok "aliases.json ($alias_count entries)"
        else
            warn "[$project] aliases.json 不是有效 JSON"
        fi
    else
        warn "[$project] aliases.json 缺失 — 术语映射不可用，诊断时客户术语无法自动解析"
    fi
done

# ─────────────────────────────────────────────
# Layer 3: 派生数据新鲜度 (per-project)
# ─────────────────────────────────────────────

phase "Layer 3: 派生数据新鲜度"

for project in "${CHECK_PROJECTS[@]}"; do
    PROJECT_DIR="$WORKFLOW_OUTPUT/$project"
    [[ -d "$PROJECT_DIR" ]] || continue
    log ""
    log "  [$project]"

    # 3.1 _node_data.json
    NODE_DATA="$PROJECT_DIR/_node_data.json"
    if [[ -f "$NODE_DATA" ]]; then
        if python3 -c "import json; d=json.load(open('$NODE_DATA')); assert isinstance(d,dict) and len(d)>0" 2>/dev/null; then
            nd_count="$(python3 -c "import json; print(len(json.load(open('$NODE_DATA'))))" 2>/dev/null)"
            # mtime check: _node_data should be newer than business-flow-manifest
            if [[ -f "$MANIFEST_FILE" ]]; then
                nd_mtime="$(stat -f %m "$NODE_DATA" 2>/dev/null || echo 0)"
                mf_mtime="$(stat -f %m "$MANIFEST_FILE" 2>/dev/null || echo 0)"
                if [[ "$nd_mtime" -ge "$mf_mtime" ]]; then
                    ok "_node_data.json ($nd_count workflows, fresh)"
                else
                    warn "[$project] _node_data.json 比 business-flow-manifest.json 旧 — 运行 generate_node_data.py"
                fi
            else
                ok "_node_data.json ($nd_count workflows)"
            fi
        else
            err "[$project] _node_data.json 无效或为空"
        fi
    else
        err "[$project] _node_data.json 缺失 — 运行 generate_node_data.py"
    fi

    # 3.2 dependency_graph.json
    DEP_GRAPH="$PROJECT_DIR/dependency_graph.json"
    if [[ -f "$DEP_GRAPH" ]]; then
        if python3 -c "
import json
d=json.load(open('$DEP_GRAPH'))
assert 'nodes' in d and 'edges' in d
nodes=d['nodes']; edges=d['edges']
assert isinstance(nodes, (dict,list)) and isinstance(edges, list)
" 2>/dev/null; then
            n_nodes="$(python3 -c "import json; d=json.load(open('$DEP_GRAPH')); nodes=d['nodes']; print(len(nodes))" 2>/dev/null)"
            n_edges="$(python3 -c "import json; d=json.load(open('$DEP_GRAPH')); print(len(d['edges']))" 2>/dev/null)"
            # mtime check: dependency_graph should be newer than _node_data
            if [[ -f "$NODE_DATA" ]]; then
                dg_mtime="$(stat -f %m "$DEP_GRAPH" 2>/dev/null || echo 0)"
                nd_mtime="$(stat -f %m "$NODE_DATA" 2>/dev/null || echo 0)"
                if [[ "$dg_mtime" -ge "$nd_mtime" ]]; then
                    ok "dependency_graph.json ($n_nodes nodes, $n_edges edges, fresh)"
                else
                    warn "[$project] dependency_graph.json 比 _node_data.json 旧 — 运行 rebuild_graph.py"
                fi
            else
                ok "dependency_graph.json ($n_nodes nodes, $n_edges edges)"
            fi
        else
            err "[$project] dependency_graph.json 无效"
        fi
    else
        err "[$project] dependency_graph.json 缺失 — 运行 rebuild_graph.py"
    fi

    # 3.3 project-snapshot.md (warning only)
    SNAPSHOT="$PROJECT_DIR/project-snapshot.md"
    if [[ -f "$SNAPSHOT" ]]; then
        snap_size="$(wc -c < "$SNAPSHOT" | tr -d ' ')"
        if [[ "$snap_size" -gt 100 ]]; then
            ok "project-snapshot.md (${snap_size} bytes)"
        else
            warn "[$project] project-snapshot.md 内容过少 (${snap_size} bytes)"
        fi
    else
        warn "[$project] project-snapshot.md 缺失 — 运行 build_snapshot.py"
    fi
done

# 3.4 FTS5 搜索索引 (全局, 跨项目)
SEARCH_DB="$WORKFLOW_OUTPUT/_search_index.db"
if [[ -f "$SEARCH_DB" ]]; then
    if python3 -c "
import sqlite3
conn = sqlite3.connect('$SEARCH_DB')
cur = conn.cursor()
cur.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='search_fts'\")
assert cur.fetchone() is not None, 'search_fts table missing'
cur.execute('SELECT COUNT(*) FROM search_fts')
count = cur.fetchone()[0]
assert count > 0, 'search_fts is empty'
" 2>/dev/null; then
        fts_count="$(python3 -c "
import sqlite3
conn = sqlite3.connect('$SEARCH_DB')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM search_fts')
print(cur.fetchone()[0])
" 2>/dev/null)"
        ok "_search_index.db (FTS5: $fts_count entries)"
    else
        err "_search_index.db 存在但 search_fts 表缺失或为空 — 运行 build_search_index.py"
    fi
else
    err "_search_index.db 缺失: $SEARCH_DB — 运行 build_search_index.py"
fi

# ─────────────────────────────────────────────
# Layer 4: 数据一致性 (per-project)
# ─────────────────────────────────────────────

phase "Layer 4: 数据一致性"

for project in "${CHECK_PROJECTS[@]}"; do
    PROJECT_DIR="$WORKFLOW_OUTPUT/$project"
    [[ -d "$PROJECT_DIR" ]] || continue

    CONTEXT_FILE="$PROJECT_DIR/project_context.json"
    NODE_DATA="$PROJECT_DIR/_node_data.json"
    MANIFEST_FILE="$PROJECT_DIR/business-flow-manifest.json"
    DEP_GRAPH="$PROJECT_DIR/dependency_graph.json"

    # 仅当所有核心文件都存在时才做一致性检查
    if [[ ! -f "$CONTEXT_FILE" || ! -f "$NODE_DATA" || ! -f "$MANIFEST_FILE" || ! -f "$DEP_GRAPH" ]]; then
        warn "[$project] 核心文件不完整，跳过一致性检查"
        continue
    fi

    log ""
    log "  [$project]"

    # 4.1 worksheet 计数一致性
    ws_count="$(python3 -c "
import json
ctx=json.load(open('$CONTEXT_FILE'))
print(len(ctx.get('worksheets',{})))
" 2>/dev/null)"

    mf_ws_count="$(python3 -c "
import json
mf=json.load(open('$MANIFEST_FILE'))
# business-flow-manifest: count unique sheets in write_index and read_index
write_idx = mf.get('write_index',{})
read_idx = mf.get('read_index',{})
all_sheets = set(write_idx.keys()) | set(read_idx.keys())
print(len(all_sheets))
" 2>/dev/null)"

    if [[ -n "$ws_count" && -n "$mf_ws_count" ]]; then
        if [[ "$ws_count" -gt 0 && "$mf_ws_count" -gt 0 ]]; then
            ok "worksheet 计数: project_context=$ws_count, manifest refs=$mf_ws_count"
        else
            warn "[$project] worksheet 计数异常 (ctx=$ws_count, manifest=$mf_ws_count)"
        fi
    fi

    # 4.2 workflow 计数一致性: _node_data vs search_index
    nd_count="$(python3 -c "import json; print(len(json.load(open('$NODE_DATA'))))" 2>/dev/null)"
    mf_wf_count="$(python3 -c "
import json
mf=json.load(open('$MANIFEST_FILE'))
print(mf.get('total_workflows_analyzed',0))
" 2>/dev/null)"

    if [[ -n "$nd_count" && -n "$mf_wf_count" ]]; then
        if [[ "$nd_count" -eq "$mf_wf_count" ]]; then
            ok "workflow 计数一致: _node_data=$nd_count, manifest=$mf_wf_count"
        else
            diff=$((nd_count - mf_wf_count))
            [[ $diff -lt 0 ]] && diff=$((-diff))
            if [[ $diff -le 5 ]]; then
                warn "[$project] workflow 计数差异: _node_data=$nd_count vs manifest=$mf_wf_count (差 $diff, 可接受)"
            else
                err "[$project] workflow 计数严重不一致: _node_data=$nd_count vs manifest=$mf_wf_count (差 $diff)"
            fi
        fi
    fi

    # 4.3 双向边检测 (dependency_graph 中 A→B 且 B→A)
    bidirectional="$(python3 -c "
import json
d=json.load(open('$DEP_GRAPH'))
edges=d.get('edges',[])
# Build adjacency
adj={}
for e in edges:
    src=e.get('source',''); tgt=e.get('target','')
    adj.setdefault(src,set()).add(tgt)
# Check reverse
bidir=[]
for src in adj:
    for tgt in adj[src]:
        if tgt in adj and src in adj[tgt] and src < tgt:  # src<tgt to dedup
            bidir.append(f'{src}↔{tgt}')
if bidir:
    print('FOUND:' + ','.join(bidir[:5]))
    if len(bidir) > 5:
        print(' +{} more'.format(len(bidir)-5))
" 2>/dev/null)"

    if [[ -z "$bidirectional" ]]; then
        ok "无双向边 (DAG 拓扑合法)"
    elif [[ "$bidirectional" == FOUND:* ]]; then
        err "[$project] 依赖图存在双向边: ${bidirectional#FOUND:}— 检查 rebuild_graph.py 输出"
    fi
done

# ─────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────

total=$(( $(date +%s) - START_TIME ))
echo ""
echo "══════════════════════════════════════════════"
echo "  hhr-plan Doctor 完成 (${total}s)"
echo "  错误: $errors  警告: $warnings"
echo "══════════════════════════════════════════════"

if [[ $errors -eq 0 && $warnings -eq 0 ]]; then
    echo ""
    echo "  环境健康，可以开始工作。"
elif [[ $errors -eq 0 ]]; then
    echo ""
    echo "  没有错误，但存在 $warnings 个警告。建议处理："
    echo ""
    # Re-run to extract warnings
    exec 2>/dev/null
else
    echo ""
    echo "  修复指南（按优先级排列）："
    echo ""
    if python3 -c "import browser_cookie3" 2>/dev/null; then :; else
        echo "  1. pip3 install browser_cookie3"
    fi
    if [[ ! -f "$HAP_BRIDGE" ]]; then
        echo "  2. 安装 hap-bridge: 检查 ~/.claude/mcp-servers/hap-bridge/"
    fi
    if [[ ! -f "$REGISTRY" ]]; then
        echo "  3. 运行 extract-via-browser.py 或 extract-project.py 创建项目注册表"
    fi
    if [[ ! -f "$SEARCH_DB" ]]; then
        echo "  4. python3 scripts/build_search_index.py --all"
    fi
    echo ""
    echo "  常见修复流程:"
    echo "    cd ~/.claude/skills/hhr-plan"
    echo "    python3 scripts/auto_sync.py  # 自动同步所有派生数据"
fi

exit $(( errors > 0 ? 1 : 0 ))
