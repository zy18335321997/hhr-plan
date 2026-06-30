#!/usr/bin/env python3
"""自动化设计验证器 — Gate 1 (依赖图) + Gate 4 (字段存在性)

Usage:
    # 仅检查 Gate 4（字段/表名存在性）
    python3 design_validator.py 几建 --check-fields "采购需求,采购审批意见表"
    python3 design_validator.py 几建 --check-fields "采购需求:审批状态,审批意见"

    # 仅检查 Gate 1（双向依赖 / DAG 环路）
    python3 design_validator.py 几建 --check-graph

    # 检查新增关联是否产生环路（指定新关联方向）
    python3 design_validator.py 几建 --new-edge "新表A→Hub表B"

    # 全部检查
    python3 design_validator.py 几建 --check-all

    # 从方案 Markdown 文件解析引用并检查
    python3 design_validator.py 几建 --plan-file path/to/plan.md

Output: JSON (always) + human summary (stderr)
"""

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path.home() / "Documents" / "workflow-output"


def load_project_context(project: str) -> dict:
    path = DATA_DIR / project / "project_context.json"
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def load_dependency_graph(project: str) -> dict:
    path = DATA_DIR / project / "dependency_graph.json"
    if not path.exists():
        print(f"WARNING: {path} not found — Gate 1 checks skipped", file=sys.stderr)
        return {"nodes": [], "edges": []}
    with open(path) as f:
        return json.load(f)


# ── Gate 4: 字段与实体存在性 ──────────────────────────────────────────

def _parse_field_check(raw: str) -> list[tuple[str, list[str]]]:
    """Parse '表名:字段1,字段2;表名2:字段3' format into [(sheet, [fields])].

    Use ';' to separate different sheet groups, ',' to separate fields within a sheet.
    """
    result = []
    for group in raw.split(";"):
        group = group.strip()
        if not group:
            continue
        if ":" in group:
            sheet, fields_str = group.split(":", 1)
            fields = [f.strip() for f in fields_str.split(",") if f.strip()]
            result.append((sheet.strip(), fields))
        else:
            result.append((group, []))
    return result


def _extract_refs_from_markdown(md_text: str) -> list[tuple[str, list[str]]]:
    """Extract sheet and field references from a plan Markdown file."""
    refs = []
    # Match markdown tables with sheet/field info per output-template.md format
    # Pattern: | 表名 | ... or table rows with sheet references
    sheet_pattern = re.findall(r'\|\s*(.+?)\s*\|', md_text)
    # Also match "引用:表名.字段名" and "关联到 表名" patterns
    field_refs = re.findall(r'(?:引用|关联到|目标表|来源|写入|读取)[：:\s]*([^\s|，,]+)', md_text)
    sheet_refs = set()
    for s in field_refs:
        s = s.strip()
        if s and s not in sheet_refs:
            sheet_refs.add(s)
    for s in sheet_refs:
        refs.append((s, []))
    return refs


def check_field_existence(project: str, checks: list[tuple[str, list[str]]]) -> dict:
    """Gate 4: Validate sheet names and field names exist in project_context."""
    ctx = load_project_context(project)
    sheets = ctx.get("worksheets", {})

    issues = []
    for sheet_name, field_names in checks:
        if sheet_name not in sheets:
            issues.append({
                "severity": "fail",
                "type": "sheet_not_found",
                "sheet": sheet_name,
                "detail": f"工作表 '{sheet_name}' 在 project_context.json 中不存在"
            })
            continue

        if not field_names:
            continue  # Only checking sheet existence

        sheet_fields = {f["name"] for f in sheets[sheet_name].get("fields", [])}
        for fn in field_names:
            if fn not in sheet_fields:
                issues.append({
                    "severity": "fail",
                    "type": "field_not_found",
                    "sheet": sheet_name,
                    "field": fn,
                    "detail": f"字段 '{fn}' 在工作表 '{sheet_name}' 中不存在"
                })

    result = {
        "gate": "Gate 4 — 字段与实体存在性",
        "verdict": "pass" if not any(i["severity"] == "fail" for i in issues) else "fail",
        "checks_performed": len(checks),
        "issues": issues
    }
    return result


# ── Gate 1: 依赖图检查 ──────────────────────────────────────────────

def _build_adjacency(edges: list[dict]) -> dict[str, set[str]]:
    """Build adjacency map: A -> set of sheets A writes to."""
    adj = {}
    for e in edges:
        adj.setdefault(e["from_sheet"], set()).add(e["to_sheet"])
    return adj


def check_bidirectional_edges(project: str) -> dict:
    """Gate 1a: Detect bidirectional edge pairs (A->B AND B->A)."""
    graph = load_dependency_graph(project)
    edges = graph.get("edges", [])
    adj = _build_adjacency(edges)

    issues = []
    seen = set()
    for a, targets in adj.items():
        for b in targets:
            if a == b:
                continue
            pair = tuple(sorted([a, b]))
            if pair in seen:
                continue
            if b in adj and a in adj[b]:
                seen.add(pair)
                # Find the workflows causing this
                a_to_b = [e for e in edges if e["from_sheet"] == a and e["to_sheet"] == b]
                b_to_a = [e for e in edges if e["from_sheet"] == b and e["to_sheet"] == a]
                issues.append({
                    "severity": "error",
                    "type": "bidirectional_edge",
                    "sheet_a": a,
                    "sheet_b": b,
                    "a_to_b_flows": [e.get("workflow", "?") for e in a_to_b],
                    "b_to_a_flows": [e.get("workflow", "?") for e in b_to_a],
                    "detail": f"双向依赖: {a} ↔ {b}（违反公理4）"
                })

    result = {
        "gate": "Gate 1a — 双向依赖检查",
        "verdict": "pass" if not issues else "fail",
        "issues": issues
    }
    return result


def check_proposed_edge(project: str, from_sheet: str, to_sheet: str) -> dict:
    """Gate 1b: Check if adding a proposed edge creates a cycle or bidirectional dep."""
    graph = load_dependency_graph(project)
    edges = graph.get("edges", [])
    adj = _build_adjacency(edges)

    issues = []

    # Check 1: Already bidirectional?
    if to_sheet in adj and from_sheet in adj.get(to_sheet, set()):
        issues.append({
            "severity": "error",
            "type": "proposed_bidirectional",
            "detail": f"新增关联 {from_sheet}→{to_sheet} 会产生双向依赖（{to_sheet} 已有指向 {from_sheet} 的边），违反公理4"
        })

    # Check 2: Would create a cycle? (Kahn's algorithm on graph + proposed edge)
    adj.setdefault(from_sheet, set()).add(to_sheet)

    # Build in-degree
    in_deg = {}
    for u, targets in adj.items():
        in_deg.setdefault(u, 0)
        for v in targets:
            in_deg.setdefault(v, 0)
            in_deg[v] += 1

    queue = [n for n, d in in_deg.items() if d == 0]
    sorted_count = 0
    while queue:
        node = queue.pop()
        sorted_count += 1
        for neighbor in adj.get(node, set()):
            in_deg[neighbor] -= 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    if sorted_count < len(in_deg):
        issues.append({
            "severity": "error",
            "type": "proposed_cycle",
            "detail": f"新增关联 {from_sheet}→{to_sheet} 会产生 DAG 环路，违反公理4"
        })

    # Remove the temporary edge
    adj[from_sheet].discard(to_sheet)
    if not adj[from_sheet]:
        del adj[from_sheet]

    result = {
        "gate": f"Gate 1b — 新增关联检查 ({from_sheet}→{to_sheet})",
        "verdict": "pass" if not issues else "fail",
        "issues": issues
    }
    return result


def check_dag_cycles(project: str) -> dict:
    """Gate 1c: Full DAG cycle detection using topological sort (Kahn's algorithm)."""
    graph = load_dependency_graph(project)
    edges = graph.get("edges", [])

    # Build adjacency and in-degree
    adj = {}
    in_degree = {}
    for e in edges:
        u, v = e["from_sheet"], e["to_sheet"]
        adj.setdefault(u, set()).add(v)
        in_degree.setdefault(u, 0)
        in_degree.setdefault(v, 0)
        in_degree[v] += 1

    # Kahn's algorithm
    queue = [n for n, d in in_degree.items() if d == 0]
    sorted_count = 0
    while queue:
        node = queue.pop()
        sorted_count += 1
        for neighbor in adj.get(node, set()):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    total_nodes = len(in_degree)
    issues = []

    if sorted_count < total_nodes:
        # Nodes remaining in in_degree with >0 are in cycles
        remaining = [n for n, d in in_degree.items() if d > 0]
        issues.append({
            "severity": "error",
            "type": "dag_cycle",
            "cycle_nodes": remaining,
            "node_count": len(remaining),
            "detail": f"DAG 环路检测: {len(remaining)}/{total_nodes} 个节点处于环路中（违反公理4）。环路涉及: {', '.join(remaining[:10])}{'...' if len(remaining) > 10 else ''}"
        })

    result = {
        "gate": "Gate 1c — DAG 环路检查",
        "verdict": "pass" if not issues else "fail",
        "total_nodes": total_nodes,
        "sorted_nodes": sorted_count,
        "issues": issues
    }
    return result


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="hhr-plan 自动化设计验证器")
    parser.add_argument("project", help="项目名（如 '几建'）")
    parser.add_argument("--check-fields", action="append", help="检查字段存在性: '表名:字段1,字段2' 或 '表名'（可多次使用）")
    parser.add_argument("--check-graph", action="store_true", help="检查已有依赖图的双向边和环路")
    parser.add_argument("--new-edge", action="append", help="检查新增关联: '源表→目标表'（可多次使用）")
    parser.add_argument("--check-all", action="store_true", help="执行所有检查")
    parser.add_argument("--plan-file", help="从方案 Markdown 文件提取引用并检查")
    args = parser.parse_args()

    results = []

    # Gate 4: Field/sheet existence
    if args.check_fields or args.check_all:
        all_checks = []
        if args.check_fields:
            for chunk in args.check_fields:
                all_checks.extend(_parse_field_check(chunk))
        if not all_checks and args.check_all:
            print("(Gate 4: no --check-fields specified, skipping)", file=sys.stderr)
        elif all_checks:
            results.append(check_field_existence(args.project, all_checks))

    # Gate 4 from plan file
    if args.plan_file:
        path = Path(args.plan_file)
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)
        md_text = path.read_text()
        checks = _extract_refs_from_markdown(md_text)
        if checks:
            results.append(check_field_existence(args.project, checks))

    # Gate 1a: Bidirectional edges
    if args.check_graph or args.check_all:
        results.append(check_bidirectional_edges(args.project))

    # Gate 1b: Proposed new edge(s)
    if args.new_edge:
        for edge_str in args.new_edge:
            parts = edge_str.split("→")
            if len(parts) != 2:
                print("ERROR: --new-edge format: '源表→目标表'", file=sys.stderr)
                sys.exit(1)
            results.append(check_proposed_edge(args.project, parts[0].strip(), parts[1].strip()))

    # Gate 1c: Full DAG cycle check
    if args.check_graph or args.check_all:
        results.append(check_dag_cycles(args.project))

    if not results:
        parser.print_help()
        sys.exit(1)

    # Output
    overall = "pass" if all(r["verdict"] == "pass" for r in results) else "fail"

    output = {
        "project": args.project,
        "overall_verdict": overall,
        "results": results
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    # Human summary to stderr
    failed = [r for r in results if r["verdict"] == "fail"]
    if failed:
        print(f"\n❌ {len(failed)}/{len(results)} 项检查未通过", file=sys.stderr)
        for r in failed:
            print(f"  [{r['gate']}]: {r['verdict']}", file=sys.stderr)
            for i in r.get("issues", []):
                print(f"    - {i['detail']}", file=sys.stderr)
    else:
        print(f"\n✅ 全部 {len(results)} 项检查通过", file=sys.stderr)


if __name__ == "__main__":
    main()
