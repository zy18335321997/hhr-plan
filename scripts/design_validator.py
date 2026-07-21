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

from agent_prepare import compute_lock_digest
from design_ir_validator import validate_design_ir

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path.home() / "Documents" / "workflow-output"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_project_context(project: str, context_file: str | None = None) -> dict:
    """Load project context, with an injectable file for deterministic tests."""
    path = Path(context_file) if context_file else DATA_DIR / project / "project_context.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return _load_json(path)


def load_dependency_graph(
    project: str,
    graph_file: str | None = None,
    required: bool = False,
) -> dict:
    """Load dependency graph, optionally from an injected fixture."""
    path = Path(graph_file) if graph_file else DATA_DIR / project / "dependency_graph.json"
    if not path.exists():
        if not required:
            print(f"WARNING: {path} not found — Gate 1 checks skipped", file=sys.stderr)
        return {
            "nodes": [],
            "edges": [],
            "_missing_graph": str(path),
        }
    return _load_json(path)


def _missing_graph_result(graph: dict, gate: str) -> dict | None:
    missing_path = graph.get("_missing_graph")
    if not missing_path:
        return None
    return {
        "gate": gate,
        "verdict": "fail",
        "issues": [
            {
                "severity": "error",
                "type": "dependency_graph_missing",
                "path": missing_path,
                "detail": (
                    "依赖图是本次显式图校验的必需输入，"
                    f"但文件不存在: {missing_path}"
                ),
            }
        ],
    }


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


def _extract_refs_from_lock(lock: dict) -> list[tuple[str, list[str]]]:
    """Extract all named worksheet/field references from execution_lock."""
    grouped: dict[str, set[str]] = {}

    def add(sheet: object, fields: object = None) -> None:
        if not isinstance(sheet, str) or not sheet:
            return
        bucket = grouped.setdefault(sheet, set())
        if isinstance(fields, list):
            bucket.update(
                field for field in fields
                if isinstance(field, str) and field
            )

    for sheet in lock.get("sheets", []):
        if not isinstance(sheet, dict):
            continue
        add(
            sheet.get("name"),
            [
                field.get("name")
                for field in sheet.get("fields", [])
                if isinstance(field, dict)
            ],
        )

    for association in lock.get("associations", []):
        if not isinstance(association, dict):
            continue
        add(association.get("from_sheet"), [association.get("field_name")])
        add(association.get("to_sheet"))

    for workflow in lock.get("workflows", []):
        if not isinstance(workflow, dict):
            continue
        add(workflow.get("trigger_sheet"))
        for node in workflow.get("node_chain", []):
            if not isinstance(node, dict):
                continue
            add(node.get("target_sheet"), node.get("writes_fields", []))
            add(node.get("target_sheet"), node.get("reads_fields", []))

    return [(sheet, sorted(fields)) for sheet, fields in sorted(grouped.items())]


def check_field_existence(
    project: str,
    checks: list[tuple[str, list[str]]],
    context: dict | None = None,
    context_file: str | None = None,
) -> dict:
    """Gate 4: Validate sheet names and field names exist in project_context."""
    ctx = context if context is not None else load_project_context(project, context_file)
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


def check_bidirectional_edges(
    project: str,
    graph: dict | None = None,
    graph_file: str | None = None,
) -> dict:
    """Gate 1a: Detect bidirectional edge pairs (A->B AND B->A)."""
    graph = graph if graph is not None else load_dependency_graph(
        project, graph_file, required=True
    )
    missing = _missing_graph_result(graph, "Gate 1a — 双向依赖检查")
    if missing:
        return missing
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


def check_proposed_edge(
    project: str,
    from_sheet: str,
    to_sheet: str,
    graph: dict | None = None,
    graph_file: str | None = None,
) -> dict:
    """Gate 1b: Check if adding a proposed edge creates a cycle or bidirectional dep."""
    graph = graph if graph is not None else load_dependency_graph(
        project, graph_file, required=True
    )
    gate = f"Gate 1b — 新增关联检查 ({from_sheet}→{to_sheet})"
    missing = _missing_graph_result(graph, gate)
    if missing:
        return missing
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
        "gate": gate,
        "verdict": "pass" if not issues else "fail",
        "issues": issues
    }
    return result


def check_dag_cycles(
    project: str,
    graph: dict | None = None,
    graph_file: str | None = None,
) -> dict:
    """Gate 1c: Full DAG cycle detection using topological sort (Kahn's algorithm)."""
    graph = graph if graph is not None else load_dependency_graph(
        project, graph_file, required=True
    )
    missing = _missing_graph_result(graph, "Gate 1c — DAG 环路检查")
    if missing:
        return missing
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
    parser.add_argument(
        "--output",
        help="将机器可读 JSON 写入指定文件；省略时输出到 stdout",
    )
    parser.add_argument("--lock-file", help="从 execution_lock.json 提取引用并检查")
    parser.add_argument("--context-file", help="project_context.json 路径（覆盖 ~/Documents 默认路径）")
    parser.add_argument("--graph-file", help="dependency_graph.json 路径（覆盖 ~/Documents 默认路径）")
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
            results.append(
                check_field_existence(
                    args.project,
                    all_checks,
                    context_file=args.context_file,
                )
            )

    # Gate 4 from plan file
    if args.plan_file:
        path = Path(args.plan_file)
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)
        md_text = path.read_text()
        checks = _extract_refs_from_markdown(md_text)
        if checks:
            results.append(
                check_field_existence(
                    args.project,
                    checks,
                    context_file=args.context_file,
                )
            )

    lock_digest = None
    # Gate 4 + Gate 1b from execution_lock.json
    if args.lock_file:
        lock_path = Path(args.lock_file)
        if not lock_path.exists():
            print(f"ERROR: {lock_path} not found", file=sys.stderr)
            sys.exit(1)
        try:
            lock = _load_json(lock_path)
            lock_digest = compute_lock_digest(lock)
            ir_issues = validate_design_ir(lock)
            results.append(
                {
                    "gate": "Richness Gate — design_ir 完整度",
                    "verdict": "fail" if ir_issues else "pass",
                    "issues": ir_issues,
                }
            )
            checks = _extract_refs_from_lock(lock)
            if checks:
                results.append(
                    check_field_existence(
                        args.project,
                        checks,
                        context_file=args.context_file,
                    )
                )
            associations = lock.get("associations", [])
            graph = load_dependency_graph(
                args.project,
                args.graph_file,
                required=bool(associations),
            )
            for association in associations:
                if not isinstance(association, dict):
                    continue
                from_sheet = association.get("from_sheet")
                to_sheet = association.get("to_sheet")
                if from_sheet and to_sheet:
                    results.append(
                        check_proposed_edge(
                            args.project,
                            from_sheet,
                            to_sheet,
                            graph=graph,
                        )
                    )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"ERROR: 无法读取 lock 文件: {exc}", file=sys.stderr)
            sys.exit(1)

    # Gate 1a: Bidirectional edges
    if args.check_graph or args.check_all:
        results.append(
            check_bidirectional_edges(args.project, graph_file=args.graph_file)
        )

    # Gate 1b: Proposed new edge(s)
    if args.new_edge:
        for edge_str in args.new_edge:
            parts = edge_str.split("→")
            if len(parts) != 2:
                print("ERROR: --new-edge format: '源表→目标表'", file=sys.stderr)
                sys.exit(1)
            results.append(
                check_proposed_edge(
                    args.project,
                    parts[0].strip(),
                    parts[1].strip(),
                    graph_file=args.graph_file,
                )
            )

    # Gate 1c: Full DAG cycle check
    if args.check_graph or args.check_all:
        results.append(check_dag_cycles(args.project, graph_file=args.graph_file))

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
    if lock_digest is not None:
        output["input_digest"] = lock_digest

    serialized = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)

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
    raise SystemExit(0 if overall == "pass" else 1)


if __name__ == "__main__":
    main()
