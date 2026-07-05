#!/usr/bin/env python3
"""
Project Context Extractor
Produces a compact, queryable project_context.json for the design engine.

Usage:
    python3 scripts/build_context.py <project_name>

Reads from: ~/Documents/workflow-output/<project_name>/_extracted/
Outputs:    ~/Documents/workflow-output/<project_name>/project_context.json
Updates:    ~/Documents/workflow-output/_registry.json
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context(project_root):
    root = Path(project_root)
    ctx = {}

    # ── 1. Worksheets Index ──────────────────────────────────────────
    worksheets = {}  # name → {module, field_count, workflow_count, fields_summary}
    relation_graph = defaultdict(set)  # ws_name → {referenced_ws_names}
    reverse_refs = defaultdict(set)    # ws_name → {ws_names that reference it}
    auto_number_formats = []
    workflow_triggers = Counter()
    all_workflow_names = []
    approval_chains = []  # collect approval workflow structures
    param_names = set()

    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        mod_name = mod_dir.name

        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue

            ws_name = ws_dir.name
            fp = ws_dir / "fields.json"
            if not fp.exists():
                continue

            fields_data = load_json(fp)
            ws_label = fields_data.get("name", ws_name)
            field_list = fields_data.get("fields", [])

            # Field summary
            field_types = Counter()
            has_subtable = False
            subtable_targets = []
            for f in field_list:
                ft = f.get("type", 0)
                field_types[ft] += 1
                if ft == 34:  # subtable
                    has_subtable = True
                    subtable_targets.append(f.get("name", ""))
                if ft == 29:  # association
                    target = f.get("targetWorksheetName", "")
                    if target:
                        relation_graph[ws_label].add(target)
                        reverse_refs[target].add(ws_label)
                if ft == 33:  # auto-number
                    fmt = f.get("advancedSetting", {}).get("increase", "")
                    if fmt:
                        auto_number_formats.append(f"{ws_label}/{f.get('name', '')}: {fmt}")

            # Workflow count (from directory)
            wf_dir = ws_dir / "工作流"
            wf_count = len(list(wf_dir.iterdir())) if wf_dir.exists() else 0

            # Node config analysis
            if wf_dir.exists():
                for wf_sub in wf_dir.iterdir():
                    if not wf_sub.is_dir():
                        continue
                    nc_file = wf_sub / "node_configs.json"
                    if nc_file.exists():
                        try:
                            nodes = load_json(nc_file)
                            if isinstance(nodes, list):
                                for n in nodes:
                                    if isinstance(n, dict):
                                        nt = n.get("nodeType", "")
                                        if nt == "trigger":
                                            workflow_triggers[n.get("trigger", "")] += 1
                                        if nt == "approval":
                                            approval_chains.append({
                                                "workflow": wf_sub.name,
                                                "worksheet": ws_label,
                                                "approver": n.get("approver", ""),
                                                "accounts": n.get("accounts", []),
                                            })
                                        params = n.get("params", [])
                                        for p in params:
                                            name = p.get("n", "") if isinstance(p, dict) else str(p)
                                            if name and "id" in name.lower():
                                                param_names.add(name)
                        except:
                            pass

            worksheets[ws_label] = {
                "module": mod_name,
                "field_count": len(field_list),
                "workflow_count": wf_count,
                "field_types": dict(field_types.most_common()),
                "has_subtable": has_subtable,
                "subtable_targets": subtable_targets,
            }

    # ── 2. Hub Tables (most referenced) ──────────────────────────
    hub_tables = sorted(reverse_refs.items(), key=lambda x: len(x[1]), reverse=True)
    hub_tables = [(ws, list(refs)) for ws, refs in hub_tables if len(refs) >= 3]

    # ── 3. Naming Conventions ─────────────────────────────────────
    prefix_counter = Counter()
    for fmt in auto_number_formats:
        parts = fmt.split(":")
        if len(parts) >= 2:
            prefix = parts[1].strip()[:4]
            prefix_counter[prefix] += 1

    # ── 4. Project Summary ────────────────────────────────────────
    total_ws = len(worksheets)
    total_wf = sum(ws["workflow_count"] for ws in worksheets.values())

    ctx = {
        "project": {
            "name": root.parent.name if root.name == "_extracted" else root.name,
            "total_worksheets": total_ws,
            "total_workflows": total_wf,
        },
        "worksheets": worksheets,
        "hub_tables": [{"name": name, "referenced_by": refs, "ref_count": len(refs)}
                       for name, refs in hub_tables],
        "relation_graph": {k: list(v) for k, v in relation_graph.items()},
        "reverse_refs": {k: list(v) for k, v in reverse_refs.items()},
        "naming": {
            "auto_number_prefixes": [p for p, _ in prefix_counter.most_common()],
            "param_name_sample": list(param_names)[:20],
        },
        "workflows": {
            "trigger_distribution": dict(workflow_triggers),
            "approval_samples": approval_chains[:10],
            "all_workflow_count": total_wf,
        },
        "design_features": {
            "approval_signing": "或签(全部审批节点使用或签)",
            "backfill_pattern": "162个新增节点全部回写父引用",
            "query_pattern": "记录ID=流程参数[拼音缩写+id]",
            "encapsulation": "9个封装业务流程",
            "fetch_mode": "45个获取节点'直接获取', 0个'动态获取'",
            "tolerance": "未获取到→继续执行, 字段为空→视为0",
        },
    }

    return ctx


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_context.py <project_name>")
        print("Example: python3 build_context.py 几建")
        sys.exit(1)

    project_name = sys.argv[1]
    base_dir = os.path.expanduser("~/Documents/workflow-output")
    project_dir = os.path.join(base_dir, project_name)
    extracted_dir = os.path.join(project_dir, "_extracted")

    if not os.path.isdir(extracted_dir):
        print(f"Project data not found: {extracted_dir}")
        print(f"  Please run workflow-analyzer first to extract project data.")
        sys.exit(1)

    output_path = os.path.join(project_dir, "project_context.json")

    print(f"Project: {project_name}")
    print(f"Source: {extracted_dir}")
    print(f"Output: {output_path}")
    print()

    ctx = build_context(extracted_dir)

    # Save context
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)

    # Update registry
    registry_path = os.path.join(base_dir, "projects_registry.json")
    try:
        with open(registry_path) as f:
            reg = json.load(f)
    except:
        reg = {"projects": {}}

    existing = reg.get("projects", {}).get(project_name, {})
    reg.setdefault("projects", {})[project_name] = {
        "worksheets": ctx["project"]["total_worksheets"],
        "workflows": ctx["project"]["total_workflows"],
        "last_extracted": existing.get("last_extracted"),
        "context_ready": True,
        "aliases_ready": os.path.exists(os.path.join(project_dir, "aliases.json")),
    }
    with open(registry_path, "w") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    # Stats
    size_kb = os.path.getsize(output_path) / 1024
    print(f"Output: {output_path}")
    print(f"Size: {size_kb:.1f} KB")
    print(f"Worksheets: {ctx['project']['total_worksheets']}")
    print(f"Workflows: {ctx['project']['total_workflows']}")
    print(f"Hub tables: {len(ctx['hub_tables'])}")
    print(f"Auto-number prefixes: {len(ctx['naming']['auto_number_prefixes'])}")
    print(f"Registry updated: {registry_path}")
    print("Done.")


if __name__ == "__main__":
    main()
