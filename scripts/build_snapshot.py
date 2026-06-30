#!/usr/bin/env python3
"""
Project Snapshot Builder
Synthesizes a human-readable project-snapshot.md from existing JSON data.

Usage:
    python3 scripts/build_snapshot.py <project_root_path> [output_path]

Reads from:
    <project_root>/project_context.json
    <project_root>/business-flow-manifest.json  (or ../references/)
    <project_root>/workflow-node-index-compact.json  (optional, for node counts)

Outputs:
    <project_root>/project-snapshot.md  (or specified output_path)
"""

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

FIELD_TYPE_NAMES = {
    1: "文本", 2: "文本", 3: "手机", 4: "座机", 5: "邮箱", 6: "数值", 7: "证件", 8: "金额",
    9: "单选", 10: "多选", 11: "单选", 14: "附件", 15: "日期", 16: "日期时间",
    17: "日期段", 18: "日期时间段", 19: "地区", 20: "公式", 21: "自由连接",
    22: "分段", 23: "地区", 24: "地区", 25: "大写金额", 26: "成员", 27: "部门",
    28: "等级", 29: "关联表", 30: "他表字段", 31: "公式", 32: "文本组合",
    33: "自动编号", 34: "子表", 35: "级联选择", 36: "开关", 37: "汇总",
    38: "公式", 40: "定位", 41: "富文本", 42: "签名", 43: "文本识别",
    44: "角色", 45: "嵌入", 46: "时间", 47: "条码", 48: "组织角色",
    49: "API查询", 50: "API查询", 51: "查询记录", 52: "标签页", 53: "函数",
    54: "自定义字段", 10010: "备注",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_load_json(path):
    try:
        return load_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Data Loading ─────────────────────────────────────────────────────────


def load_project_data(project_root):
    root = Path(project_root)
    ctx = load_json(root / "project_context.json")

    # manifest: per-project only, no fallback to skill references
    manifest = safe_load_json(root / "business-flow-manifest.json")

    # compact: per-project only (optional)
    compact = safe_load_json(root / "workflow-node-index-compact.json")

    return ctx, manifest, compact


# ── Section 1: System Overview ───────────────────────────────────────────


def build_domain_map(ctx):
    lines = ["## 1. 系统概览", "", "### 业务域地图", ""]
    lines.append("| 业务域 | 工作表数 | 工作流数 | 核心表(Top 3) |")
    lines.append("|--------|---------|---------|--------------|")

    # Group worksheets by module
    modules = defaultdict(lambda: {"ws": 0, "wf": 0, "tables": []})
    for ws_name, ws in ctx["worksheets"].items():
        mod = ws.get("module", "未分类")
        modules[mod]["ws"] += 1
        modules[mod]["wf"] += ws.get("workflow_count", 0)
        modules[mod]["tables"].append(
            (ws_name, ws.get("hub_score", 0), ws.get("field_count", 0))
        )

    # Sort modules by worksheet count desc
    for mod, data in sorted(modules.items(), key=lambda x: -x[1]["ws"]):
        # Top 3 tables: prefer hub_score > 0, then by field_count
        top = sorted(data["tables"], key=lambda t: (-t[1], -t[2]))[:3]
        top_names = "、".join(t[0] for t in top)
        lines.append(f"| {mod} | {data['ws']} | {data['wf']} | {top_names} |")

    # Hub tables
    lines.extend(["", "### Hub 枢纽表", ""])
    lines.append("| 排名 | 表名 | 被引用次数 | 引用方(前5) | 所属域 |")
    lines.append("|------|------|-----------|------------|--------|")

    ws_module = {ws: d["module"] for ws, d in ctx["worksheets"].items()}

    for i, hub in enumerate(ctx.get("hub_tables", [])[:10], 1):
        name = hub.get("resolved_name", hub.get("name", "?"))
        refs = hub.get("referenced_by", 0)
        sample = hub.get("referenced_by_sample", [])[:5]
        sample_str = "、".join(sample) if sample else "—"
        mod = ws_module.get(name) or ws_module.get(hub.get("name", ""), "—")
        lines.append(f"| {i} | {name} | {refs} | {sample_str} | {mod} |")

    return "\n".join(lines)


# ── Section 2: Data Flow Chains ──────────────────────────────────────────


def build_data_flow_chains(manifest, ctx):
    lines = ["## 2. 数据流转链路", "", "### 端到端业务链", ""]

    tables_data = manifest.get("tables", {}) if manifest else {}
    ws_module = {ws: d["module"] for ws, d in ctx["worksheets"].items()}

    if not tables_data:
        lines.append("（该项目暂无工作流数据，无法追踪数据流转链路）")
        lines.append("")
        return "\n".join(lines)

    # Build write-graph: table → set of tables its workflows write to
    write_graph = defaultdict(set)  # source → {targets}
    write_edges = defaultdict(list)  # (source, target) → [workflow names]
    in_degree = defaultdict(int)
    out_degree = defaultdict(int)

    for table, wfs in tables_data.items():
        if table == "?":
            continue
        for wf in wfs:
            for w in wf.get("w", []):
                if w and w != table and w != "?" and w != "—":
                    write_graph[table].add(w)
                    write_edges[(table, w)].append(wf.get("wf", ""))

    for src, targets in write_graph.items():
        out_degree[src] = len(targets)
        for t in targets:
            in_degree[t] += 1

    # Find source tables (write to others, nobody writes to them)
    sources = [t for t in write_graph if in_degree.get(t, 0) == 0]
    sources.sort(key=lambda t: -out_degree.get(t, 0))

    # BFS from each source to trace chains
    chains = []
    global_visited = set()

    for src in sources[:15]:  # Cap sources to avoid too many chains
        visited = {src}
        path = [src]
        current = src

        # Greedy: follow the edge with most onward connections
        for _ in range(7):  # Max 8 nodes per chain
            neighbors = write_graph.get(current, set()) - visited
            if not neighbors:
                break
            # Prefer neighbors that also have outgoing edges (longer chains)
            nxt = max(neighbors, key=lambda n: out_degree.get(n, 0))
            visited.add(nxt)
            path.append(nxt)
            current = nxt

        if len(path) >= 3:  # Only show meaningful chains (3+ tables)
            chains.append(path)
            global_visited.update(path)

    # Deduplicate: if two chains share 60%+ tables, keep the longer one
    final_chains = []
    for chain in sorted(chains, key=len, reverse=True):
        chain_set = set(chain)
        duplicate = False
        for existing in final_chains:
            overlap = len(chain_set & set(existing)) / min(len(chain), len(existing))
            if overlap > 0.6:
                duplicate = True
                break
        if not duplicate:
            final_chains.append(chain)

    for i, chain in enumerate(final_chains[:8], 1):
        src_mod = ws_module.get(chain[0], "")
        chain_label = f"{src_mod}链" if src_mod else f"链路{i}"
        steps = []
        for j, table in enumerate(chain):
            if j > 0:
                wfs = write_edges.get((chain[j - 1], table), [])
                wf_hint = wfs[0].split("-")[0] if wfs else ""
                steps.append(f" →[{wf_hint}]→ " if wf_hint else " → ")
            steps.append(table)
        lines.append(f"**{chain_label}**: {''.join(steps)}")
        lines.append("")

    if not final_chains:
        lines.append("（数据不足，无法追踪完整链路）")
        lines.append("")

    # Data role classification
    all_tables = set(tables_data.keys()) - {"?"}
    all_written = set()
    for targets in write_graph.values():
        all_written.update(targets)

    roles = []
    for t in sorted(all_tables | all_written):
        i_deg = in_degree.get(t, 0)
        o_deg = out_degree.get(t, 0)
        if o_deg > 0 and i_deg == 0:
            role = "源头"
        elif i_deg >= 3 and o_deg >= 2:
            role = "枢纽"
        elif i_deg > 0 and o_deg == 0:
            role = "汇聚"
        elif o_deg > 0 and i_deg > 0:
            role = "中转"
        else:
            continue  # Skip tables with no flow involvement
        roles.append((t, o_deg, i_deg, role))

    lines.extend(["### 数据角色分类", ""])
    lines.append("| 表名 | 写出到(表数) | 被写入(表数) | 角色 |")
    lines.append("|------|------------|------------|------|")
    # Show hubs and sources first, then sinks
    role_order = {"枢纽": 0, "源头": 1, "中转": 2, "汇聚": 3}
    for t, o, i, r in sorted(roles, key=lambda x: (role_order.get(x[3], 9), -x[1] - x[2]))[:20]:
        lines.append(f"| {t} | {o} | {i} | {r} |")

    return "\n".join(lines)


# ── Section 3: Roles & Approval ──────────────────────────────────────────


def build_role_matrix(ctx):
    lines = ["## 3. 角色与审批", "", "### 成员字段分布", ""]

    # Count member fields per module
    module_members = defaultdict(int)
    total_member_fields = 0
    ws_with_members = 0

    for ws_name, ws in ctx["worksheets"].items():
        # field_types keys are type IDs (strings like "26"), not names
        ft = ws.get("field_types", {})
        member_count = int(ft.get("26", 0))
        if member_count > 0:
            ws_with_members += 1
            total_member_fields += member_count
            mod = ws.get("module", "未分类")
            module_members[mod] += member_count

    lines.append(f"- 总成员字段数: **{total_member_fields}**（分布在 {ws_with_members} 张表中）")
    lines.append(f"- 平均每表: **{total_member_fields / max(ws_with_members, 1):.1f}** 个成员字段")
    lines.append("")

    lines.append("| 业务域 | 成员字段数 | 含义推断 |")
    lines.append("|--------|----------|---------|")
    for mod, count in sorted(module_members.items(), key=lambda x: -x[1]):
        hint = "审批密集" if count > 20 else "协作型" if count > 10 else "轻协作"
        lines.append(f"| {mod} | {count} | {hint} |")

    # Approval patterns
    lines.extend(["", "### 审批模式", ""])
    patterns = ctx.get("patterns", {})
    approval_mode = patterns.get("approval_mode", "")
    if approval_mode:
        lines.append(f"项目约定: **{approval_mode}**")
    else:
        lines.append("（未提取到审批模式信息）")

    triggers = ctx.get("workflows", {}).get("trigger_distribution", {})
    if triggers:
        lines.extend(["", "### 工作流触发分布", ""])
        lines.append("| 触发方式 | 数量 | 占比 |")
        lines.append("|---------|------|------|")
        total = sum(triggers.values())
        for trig, count in sorted(triggers.items(), key=lambda x: -x[1]):
            pct = count / max(total, 1) * 100
            lines.append(f"| {trig} | {count} | {pct:.1f}% |")

    return "\n".join(lines)


# ── Section 4: Complexity Heatmap ────────────────────────────────────────


def build_complexity_heatmap(ctx, manifest, compact):
    lines = ["## 4. 复杂度热力图", ""]

    # Top Hub tables
    lines.extend(["### Top Hub 表（按被引用数）", ""])
    for i, hub in enumerate(ctx.get("hub_tables", [])[:5], 1):
        name = hub.get("resolved_name", hub.get("name", "?"))
        refs = hub.get("referenced_by", 0)
        lines.append(f"{i}. **{name}** — 被 {refs} 张表引用")
    lines.append("")

    # Top complex workflows (from compact index if available)
    if compact:
        lines.extend(["### Top 复杂工作流（按节点数）", ""])
        all_wfs = []
        for table, wfs in compact.items():
            if table == "_meta":
                continue
            if isinstance(wfs, list):
                for wf in wfs:
                    if isinstance(wf, dict) and "n" in wf:
                        all_wfs.append((wf.get("wf", "?"), wf["n"], table))
        all_wfs.sort(key=lambda x: -x[1])
        lines.append("| 排名 | 工作流 | 节点数 | 所属表 |")
        lines.append("|------|--------|--------|--------|")
        for i, (wf_name, n, table) in enumerate(all_wfs[:10], 1):
            # Truncate long subprocess names
            display = wf_name[:40] + "..." if len(wf_name) > 40 else wf_name
            lines.append(f"| {i} | {display} | {n} | {table} |")
        lines.append("")

        # Complexity distribution (matching workflow-design-derivation.md brackets)
        brackets = {"简单(2-3)": 0, "标准(4-6)": 0, "复杂(7-10)": 0, "极复杂(11+)": 0}
        for wf_name, n, table in all_wfs:
            if n <= 3:
                brackets["简单(2-3)"] += 1
            elif n <= 6:
                brackets["标准(4-6)"] += 1
            elif n <= 10:
                brackets["复杂(7-10)"] += 1
            else:
                brackets["极复杂(11+)"] += 1
        total_wf = len(all_wfs)
        lines.extend(["### 复杂度分布", ""])
        lines.append("| 级别 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for label, count in brackets.items():
            pct = count / max(total_wf, 1) * 100
            lines.append(f"| {label} | {count} | {pct:.1f}% |")
        lines.append("")

    # Module density (workflows per worksheet)
    modules = defaultdict(lambda: {"ws": 0, "wf": 0})
    for ws_name, ws in ctx["worksheets"].items():
        mod = ws.get("module", "未分类")
        modules[mod]["ws"] += 1
        modules[mod]["wf"] += ws.get("workflow_count", 0)

    lines.extend(["### 模块工作流密度", ""])
    lines.append("| 业务域 | 工作表数 | 工作流数 | 密度(流/表) |")
    lines.append("|--------|---------|---------|------------|")
    for mod, data in sorted(modules.items(), key=lambda x: -x[1]["wf"] / max(x[1]["ws"], 1)):
        density = data["wf"] / max(data["ws"], 1)
        if data["wf"] > 0:
            lines.append(f"| {mod} | {data['ws']} | {data['wf']} | {density:.1f} |")

    return "\n".join(lines)


# ── Section 5: Health Scores ─────────────────────────────────────────────


def grade(pct, thresholds):
    """Return grade based on thresholds (A, B, C, D)."""
    a, b, c = thresholds
    if pct >= a:
        return "A"
    elif pct >= b:
        return "B"
    elif pct >= c:
        return "C"
    return "D"


def build_health_scores(ctx, manifest):
    lines = ["## 5. 健康度评分", "", "### 评分卡", ""]

    total = len(ctx["worksheets"])
    if total == 0:
        lines.append("（无工作表数据）")
        return "\n".join(lines)

    # Metric 1: Data completeness (worksheets with fields > 0)
    with_fields = sum(1 for ws in ctx["worksheets"].values() if ws.get("field_count", 0) > 0)
    pct_fields = with_fields / total * 100

    # Metric 2: Workflow coverage
    with_wf = sum(1 for ws in ctx["worksheets"].values() if ws.get("workflow_count", 0) > 0)
    pct_wf = with_wf / total * 100

    # Metric 3: Naming (worksheets with auto-number field)
    with_autonumber = sum(
        1 for ws in ctx["worksheets"].values()
        if ws.get("field_types", {}).get("自动编号", 0) > 0
    )
    pct_naming = with_autonumber / total * 100

    # Metric 4: Relation completeness (use global relation_graph)
    relation_graph = ctx.get("relation_graph", {})
    with_relation = sum(
        1 for ws_name, ws in ctx["worksheets"].items()
        if ws.get("relation_targets") or ws.get("subtable_targets")
        or ws_name in relation_graph
    )
    pct_relation = with_relation / total * 100

    lines.append("| 维度 | 指标 | 数值 | 评级 |")
    lines.append("|------|------|------|------|")
    lines.append(f"| 数据完整性 | 有字段的表/总表 | {with_fields}/{total} ({pct_fields:.0f}%) | {grade(pct_fields, (90, 70, 50))} |")
    lines.append(f"| 工作流覆盖 | 有工作流的表/总表 | {with_wf}/{total} ({pct_wf:.0f}%) | {grade(pct_wf, (60, 40, 20))} |")
    lines.append(f"| 命名规范 | 有自动编号的表/总表 | {with_autonumber}/{total} ({pct_naming:.0f}%) | {grade(pct_naming, (50, 30, 15))} |")
    lines.append(f"| 关联完整性 | 有关联/子表的表/总表 | {with_relation}/{total} ({pct_relation:.0f}%) | {grade(pct_relation, (70, 50, 30))} |")

    # Design pattern summary
    patterns = ctx.get("patterns", {})
    if patterns:
        lines.extend(["", "### 设计模式约定", ""])
        for key, val in patterns.items():
            lines.append(f"- **{key}**: {val}")

    return "\n".join(lines)


# ── Section 6: Stats ─────────────────────────────────────────────────────


def build_stats(ctx, manifest):
    lines = ["## 6. 精确统计", ""]

    project = ctx.get("project", {})
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 项目名称 | {project.get('name', '—')} |")
    lines.append(f"| 工作表总数 | {project.get('total_worksheets', '—')} |")
    lines.append(f"| 工作流总数 | {project.get('total_workflows', '—')} |")
    lines.append(f"| 业务域数 | {project.get('total_modules', '—')} |")
    lines.append(f"| Hub 表数 | {len(ctx.get('hub_tables', []))} |")

    flat = manifest.get("flat", []) if manifest else []
    if flat:
        with_approval = sum(1 for e in flat if "审批" in e.get("特性", ""))
        with_notify = sum(1 for e in flat if "通知" in e.get("特性", ""))
        lines.append(f"| 含审批的工作流 | {with_approval} |")
        lines.append(f"| 含通知的工作流 | {with_notify} |")
        tables_in_manifest = len(manifest.get("tables", {}))
        lines.append(f"| 有工作流的表(manifest) | {tables_in_manifest} |")

    # Field type summary
    type_totals = defaultdict(int)
    for ws in ctx["worksheets"].values():
        for ft, count in ws.get("field_types", {}).items():
            type_totals[ft] += count
    total_fields = sum(type_totals.values())
    lines.append(f"| 字段总数 | {total_fields} |")
    lines.extend(["", "### 字段类型分布", ""])
    lines.append("| 字段类型 | 数量 | 占比 |")
    lines.append("|---------|------|------|")
    for ft, count in sorted(type_totals.items(), key=lambda x: -x[1])[:12]:
        pct = count / max(total_fields, 1) * 100
        type_name = FIELD_TYPE_NAMES.get(int(ft), f"type{ft}") if ft.isdigit() else ft
        lines.append(f"| {type_name}({ft}) | {count} | {pct:.1f}% |")

    return "\n".join(lines)


# ── Section 7: Appendix ──────────────────────────────────────────────────


def build_appendix(project_root):
    root = Path(project_root)
    lines = ["## 7. 数据源", ""]
    lines.append("| 文件 | 用途 |")
    lines.append("|------|------|")
    lines.append(f"| `{root / 'project_context.json'}` | 工作表索引、Hub表、关联图 |")
    lines.append(f"| `{root / 'business-flow-manifest.json'}` | 工作流读写映射 |")

    compact_path = root / "workflow-node-index-compact.json"
    if compact_path.exists():
        lines.append(f"| `{compact_path}` | 节点数和节点链 |")

    lines.extend(["", f"> 由 `build_snapshot.py` 自动生成于 {date.today().isoformat()}"])

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_snapshot.py <project_root> [output_path]")
        sys.exit(1)

    project_root = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else str(Path(project_root) / "project-snapshot.md")

    print(f"Loading data from {project_root}...")
    ctx, manifest, compact = load_project_data(project_root)

    project = ctx.get("project", {})
    name = project.get("name", Path(project_root).name)
    total_ws = project.get("total_worksheets", len(ctx.get("worksheets", {})))
    total_wf = project.get("total_workflows", "?")
    total_mod = project.get("total_modules", "?")

    # Scale label
    if isinstance(total_ws, int):
        if total_ws > 100:
            scale = "大型项目"
        elif total_ws > 50:
            scale = "中型项目"
        else:
            scale = "小型项目"
    else:
        scale = "—"

    header = [
        f"# {name} 项目全景快照",
        f"> {scale} | {total_ws}工作表 | {total_wf}工作流 | {total_mod}业务域 | 生成于 {date.today().isoformat()}",
        "",
        "---",
        "",
    ]

    print("Building sections...")
    sections = [
        "\n".join(header),
        build_domain_map(ctx),
        build_data_flow_chains(manifest, ctx),
        build_role_matrix(ctx),
        build_complexity_heatmap(ctx, manifest, compact),
        build_health_scores(ctx, manifest),
        build_stats(ctx, manifest),
        build_appendix(project_root),
    ]

    output = "\n\n---\n\n".join(sections) + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Snapshot written to {output_path}")
    print(f"  {len(output)} chars, {output.count(chr(10))} lines")


if __name__ == "__main__":
    main()
