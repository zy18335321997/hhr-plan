#!/usr/bin/env python3
"""
Generate references/topology-<project>.md from dependency_graph.json.

Usage:
    python3 scripts/generate_topology.py 几建
    python3 scripts/generate_topology.py --all
"""

import json
import os
import sys
from collections import defaultdict

BASE = os.path.expanduser("~/Documents/workflow-output")
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TOPOLOGY_DIR = os.path.join(os.path.dirname(SKILL_DIR), "references")


def topology_path(project_name):
    return os.path.join(TOPOLOGY_DIR, f"topology-{project_name}.md")

# Threshold: sheets with total r/w >= MIN_ACTIVITY get lifecycle details
MIN_ACTIVITY = 4
# Max sheets to show lifecycle for (keeps doc readable)
MAX_LIFECYCLE = 20

# Internal operation nodes that are NOT real worksheets
INTERNAL_OPS = {
    "获取关联记录", "获取多条关联记录", "查询工作表", "查询并批量更新",
    "从工作表获取记录", "从关联字段获取", "从多条获取单条",
    "按钮触发", "工作表事件触发", "子流程", "本流程参数", "全局变量",
    "系统", "填写内容", "人工节点操作明细", "发送API请求",
    "未分类", "获取关联记录",
}


def is_business_sheet(name):
    """Real business worksheets only — filter out internal workflow operation nodes."""
    return name not in INTERNAL_OPS


def build_sheet_index(nodes, edges):
    """Build enriched sheet index from nodes + edges. Filters out internal ops."""
    index = {}
    for name, nd in nodes.items():
        if not is_business_sheet(name):
            continue
        index[name] = {
            "module": nd.get("module", ""),
            "reader_pids": set(nd.get("read_by", [])),
            "writer_pids": set(nd.get("written_by", [])),
            "readers": [],
            "writers": [],
        }

    # Resolve PID -> workflow name from edges
    pid_to_name = {}
    for e in edges:
        pid = e.get("pid", "")
        wf = e.get("workflow", "")
        if pid and wf:
            pid_to_name[pid] = wf

    for name, info in index.items():
        info["readers"] = sorted(
            [(pid_to_name.get(p, p[:16]), p) for p in info["reader_pids"]],
            key=lambda x: x[0],
        )
        info["writers"] = sorted(
            [(pid_to_name.get(p, p[:16]), p) for p in info["writer_pids"]],
            key=lambda x: x[0],
        )
        info["reader_count"] = len(info["reader_pids"])
        info["writer_count"] = len(info["writer_pids"])
        info["total_activity"] = info["reader_count"] + info["writer_count"]

    return index


def build_downstream(edges):
    """Build downstream index: sheet -> [(to_sheet, op, workflow, pid)]. Filters internal ops from targets."""
    downstream = defaultdict(list)
    for e in edges:
        from_sheet = e.get("from_sheet", "")
        to_sheet = e.get("to_sheet", "")
        if from_sheet and is_business_sheet(from_sheet):
            downstream[from_sheet].append(e)
    return downstream


def pick_core_sheets(index, downstream):
    """Pick the top sheets by activity for lifecycle details."""
    active = [(name, info) for name, info in index.items()
              if info["total_activity"] >= MIN_ACTIVITY]
    active.sort(key=lambda x: -x[1]["total_activity"])
    return active[:MAX_LIFECYCLE]


def generate_topology_md(project_name):
    """Generate one project-scoped topology document."""
    proj_dir = os.path.join(BASE, project_name)
    graph_path = os.path.join(proj_dir, "dependency_graph.json")

    if not os.path.exists(graph_path):
        print(f"ERROR: {graph_path} not found. Run auto_sync first.", file=sys.stderr)
        return None

    with open(graph_path, encoding="utf-8") as f:
        g = json.load(f)

    nodes = g.get("nodes", {})
    edges = g.get("edges", [])
    stats = g.get("stats", {})

    index = build_sheet_index(nodes, edges)
    downstream = build_downstream(edges)
    core = pick_core_sheets(index, downstream)

    # ── Metadata ──
    meta_pids = set()
    for name in list(index.keys())[:3]:
        for _, pid in index[name]["readers"] + index[name]["writers"]:
            meta_pids.add(pid)

    # ── Generate Markdown ──
    lines = []
    lines.append(f"# {project_name} 全局业务拓扑")
    lines.append("")
    lines.append(f"> 从 dependency_graph.json 自动生成。"
                 f" {stats.get('total_sheets', '?')} 表 / {stats.get('total_edges', '?')} 边 /"
                 f" {stats.get('total_workflows', '?')} 工作流。")
    lines.append(f"> 只读表: {stats.get('sheets_read_only', '?')} |"
                 f" 只写表: {stats.get('sheets_written_only', '?')} |"
                 f" 双向: {stats.get('sheets_both', '?')} |"
                 f" 孤立: {stats.get('sheets_orphan', '?')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Core Entity Role Summary ──
    lines.append("## 核心实体角色速查")
    lines.append("")
    lines.append("| 实体 | r/w | 角色 | 核心工作流 |")
    lines.append("|------|-----|------|-----------|")

    for name, info in core:
        r = info["reader_count"]
        w = info["writer_count"]
        # Pick top 5 workflows
        top_wfs = [n for n, _ in info["writers"][:5]]
        if not top_wfs:
            top_wfs = [n for n, _ in info["readers"][:3]]
        wf_str = "、".join(top_wfs[:4]) if top_wfs else "—"
        # Role heuristic
        if w > r * 2 and w >= 5:
            role = "数据生产者"
        elif r > w * 2 and r >= 5:
            role = "数据消费者"
        elif r >= 5 and w >= 5:
            role = "业务Hub"
        elif r >= 3 or w >= 3:
            role = "流程节点"
        else:
            role = "辅助表"
        lines.append(f"| **{name}** | {w}/{r} | {role} | {wf_str} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Entity Lifecycle Details ──
    lines.append("## 各实体生命周期明细")
    lines.append("")

    for name, info in core:
        r = info["reader_count"]
        w = info["writer_count"]
        lines.append(f"### {name} ({w}写/{r}读)")
        lines.append("")

        # Writers
        if info["writers"]:
            lines.append("**创建/更新者**:")
            for wf_name, wf_pid in info["writers"][:8]:
                lines.append(f"- {wf_name} `{wf_pid[:16]}`")
        else:
            lines.append("**创建/更新者**: — (表单直接编辑或外部系统)")

        lines.append("")

        # Readers
        if info["readers"]:
            lines.append("**消费者**:")
            for wf_name, wf_pid in info["readers"][:10]:
                lines.append(f"- {wf_name} `{wf_pid[:16]}`")

        lines.append("")

        # Downstream
        ds = downstream.get(name, [])
        if ds:
            # Group by op
            by_op = defaultdict(list)
            for e in ds:
                to_sheet = e.get("to_sheet", "")
                wf_name = e.get("workflow", "")
                by_op[e.get("op", "?")].append((to_sheet, wf_name))

            lines.append("**下游写入**:")
            if by_op.get("w"):
                shown = 0
                for to_sheet, wf_name in by_op["w"]:
                    if is_business_sheet(to_sheet):
                        lines.append(f"- → `{to_sheet}` ({wf_name})")
                        shown += 1
                        if shown >= 5:
                            break
            if by_op.get("rw_chain"):
                targets = {t for t, _ in by_op["rw_chain"] if is_business_sheet(t)}
                shown = sorted(targets)[:8]
                if shown:
                    lines.append(f"- → 链式影响: {', '.join(f'`{t}`' for t in shown)}"
                                 f"{' ...' if len(targets) > 8 else ''}")

        lines.append("")

    # ── Stats footer ──
    lines.append("---")
    lines.append("")
    lines.append(f"*自动生成于 {project_name} | "
                 f"覆盖率: {len(core)}/{len(index)} 核心实体 |"
                 f" 按 activity >= {MIN_ACTIVITY} 筛选*")

    return "\n".join(lines)


def main():
    project_names = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not project_names or "--all" in sys.argv:
        reg_path = os.path.join(BASE, "projects_registry.json")
        if os.path.exists(reg_path):
            with open(reg_path, encoding="utf-8") as f:
                reg = json.load(f)
            project_names = [name for name, meta in reg.get("projects", {}).items()
                             if meta.get("context_ready")]
        else:
            print("ERROR: No projects registry found.", file=sys.stderr)
            sys.exit(1)

    for pn in project_names:
        md = generate_topology_md(pn)
        if md:
            out_path = topology_path(pn)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"{pn}: topology-{pn}.md regenerated ({len(md):,} chars)")


if __name__ == "__main__":
    main()
