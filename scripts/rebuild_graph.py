#!/usr/bin/env python3
"""
Rebuild dependency graph from _node_data.json + project_context.json.
Covers ALL sheets (not just 18). Also extracts entity lifecycle chains.

Usage:
    python3 scripts/rebuild_graph.py 几建
    python3 scripts/rebuild_graph.py 几建 --lifecycle 采购需求
"""

import json
import os
import sys
from collections import defaultdict

BASE = os.path.expanduser("~/Documents/workflow-output")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rebuild_graph(project_name):
    proj_dir = os.path.join(BASE, project_name)
    node_data = load_json(os.path.join(proj_dir, "_node_data.json"))
    ctx = load_json(os.path.join(proj_dir, "project_context.json"))

    sheets = ctx.get("worksheets", {})
    all_sheet_names = set(sheets.keys())

    # -- Build graph --
    graph = {"nodes": {}, "edges": []}
    sheet_readers = defaultdict(set)   # sheet -> {workflow names that read it}
    sheet_writers = defaultdict(set)   # sheet -> {workflow names that write it}

    for pid, wf in node_data.items():
        name = wf.get("name", "")
        worksheet = wf.get("worksheet", "")
        trigger = wf.get("trigger", "")
        reads = wf.get("reads", []) or []
        writes = wf.get("writes", []) or []

        all_sheet_names.add(worksheet)

        for r_sheet in reads:
            all_sheet_names.add(r_sheet)
            sheet_readers[r_sheet].add(name)
            graph["edges"].append({
                "from_sheet": r_sheet,
                "to_sheet": worksheet,
                "op": "r",
                "workflow": name,
                "pid": pid,
            })
            # Also check if workflow writes to another sheet from here
            for w_sheet in writes:
                if w_sheet != r_sheet:
                    graph["edges"].append({
                        "from_sheet": r_sheet,
                        "to_sheet": w_sheet,
                        "op": "rw_chain",
                        "workflow": name,
                        "pid": pid,
                    })

        for w_sheet in writes:
            all_sheet_names.add(w_sheet)
            sheet_writers[w_sheet].add(name)
            graph["edges"].append({
                "from_sheet": worksheet,
                "to_sheet": w_sheet,
                "op": "w",
                "workflow": name,
                "pid": pid,
            })

    # -- Build nodes --
    for sname in sorted(all_sheet_names):
        sheet_info = sheets.get(sname, {})
        graph["nodes"][sname] = {
            "field_count": sheet_info.get("field_count", 0),
            "module": sheet_info.get("module", ""),
            "read_by": sorted(sheet_readers.get(sname, [])),
            "written_by": sorted(sheet_writers.get(sname, [])),
            "reader_count": len(sheet_readers.get(sname, [])),
            "writer_count": len(sheet_writers.get(sname, [])),
        }

    # -- Stats --
    graph["stats"] = {
        "total_sheets": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "total_workflows": len(node_data),
        "sheets_read_only": sum(1 for s in graph["nodes"].values() if s["reader_count"] > 0 and s["writer_count"] == 0),
        "sheets_written_only": sum(1 for s in graph["nodes"].values() if s["writer_count"] > 0 and s["reader_count"] == 0),
        "sheets_both": sum(1 for s in graph["nodes"].values() if s["reader_count"] > 0 and s["writer_count"] > 0),
        "sheets_orphan": sum(1 for s in graph["nodes"].values() if s["reader_count"] == 0 and s["writer_count"] == 0),
    }

    # -- Save --
    out_path = os.path.join(proj_dir, "dependency_graph.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"Dependency graph rebuilt: {out_path}")
    print(f"  Sheets: {graph['stats']['total_sheets']}")
    print(f"  Edges: {graph['stats']['total_edges']}")
    print(f"  Read-only sheets: {graph['stats']['sheets_read_only']}")
    print(f"  Written-only sheets: {graph['stats']['sheets_written_only']}")
    print(f"  Both: {graph['stats']['sheets_both']}")
    print(f"  Orphan (no r/w): {graph['stats']['sheets_orphan']}")
    return graph


def extract_lifecycle(graph, entity_name):
    """Extract the full lifecycle of an entity from the dependency graph."""
    node = graph["nodes"].get(entity_name)
    if not node:
        print(f"Entity '{entity_name}' not found in graph")
        return None

    # Find all edges involving this entity
    edges_in = [e for e in graph["edges"] if e["to_sheet"] == entity_name and e["op"] in ("w", "rw_chain")]
    edges_out = [e for e in graph["edges"] if e["from_sheet"] == entity_name and e["op"] == "r"]
    edges_self = [e for e in graph["edges"] if e["from_sheet"] == entity_name and e["to_sheet"] == entity_name and e["op"] == "w"]

    # Group by workflow
    wf_map = {}
    for e in edges_in + edges_out:
        wf_map.setdefault(e["pid"], {
            "name": e["workflow"],
            "reads": set(),
            "writes": set(),
            "edges": [],
        })
        wf_map[e["pid"]]["edges"].append(e)
        if e["op"] in ("w", "rw_chain") and e["to_sheet"] != entity_name:
            wf_map[e["pid"]]["writes"].add(e["to_sheet"])
        if e["op"] == "r" and e["from_sheet"] != entity_name:
            wf_map[e["pid"]]["reads"].add(e["from_sheet"])

    # Add from node metadata
    for pid, info in wf_map.items():
        node_data_pid = pid
        # Get reads/writes from graph node metadata
        for e in edges_in + edges_out:
            if e["pid"] == pid:
                if e["op"] in ("w", "rw_chain") and e["to_sheet"] == entity_name:
                    info["writes"].add(entity_name)
                if e["op"] == "r" and e["from_sheet"] == entity_name:
                    info["reads"].add(entity_name)

    lifecycle = {
        "entity": entity_name,
        "reader_count": node["reader_count"],
        "writer_count": node["writer_count"],
        "read_by": node["read_by"],
        "written_by": node["written_by"],
        "workflows": {},
    }

    for pid, info in wf_map.items():
        lifecycle["workflows"][pid] = {
            "name": info["name"],
            "reads": sorted(info["reads"]),
            "writes": sorted(info["writes"]),
        }

    return lifecycle


def print_lifecycle(lifecycle):
    """Pretty-print the lifecycle."""
    entity = lifecycle["entity"]
    print(f"\n{'='*60}")
    print(f"  生命周期: {entity}")
    print(f"  被 {lifecycle['reader_count']} 个工作流读, 被 {lifecycle['writer_count']} 个工作流写")
    print(f"{'='*60}")

    # Categorize: creation, update, read/consume
    creators = []
    updaters = []
    consumers = []

    for pid, info in lifecycle["workflows"].items():
        name = info["name"]
        reads = info["reads"]
        writes = info["writes"]
        if entity in writes and name in lifecycle["written_by"]:
            if entity not in reads:
                creators.append((pid, info))
            else:
                updaters.append((pid, info))
        else:
            consumers.append((pid, info))

    print(f"\n── 创建者 (create) ──")
    for pid, info in creators:
        print(f"  {info['name']}  (PID: {pid})")
        print(f"    读取: {info['reads']}  写入: {info['writes']}")

    print(f"\n── 更新者 (update/transit) ──")
    for pid, info in updaters:
        print(f"  {info['name']}  (PID: {pid})")
        print(f"    读取: {info['reads']}  写入: {info['writes']}")

    print(f"\n── 消费者 (read-only) ──")
    for pid, info in consumers:
        print(f"  {info['name']}  (PID: {pid})")
        print(f"    读取: {info['reads']}")

    # Downstream: who consumes what this entity produces?
    print(f"\n── 下游影响链 (entity → downstream) ──")
    all_written = set()
    for pid, info in lifecycle["workflows"].items():
        all_written.update(info["writes"])
    all_written.discard(entity)

    downstream_map = defaultdict(set)
    for downstream_sheet in sorted(all_written):
        # Find who reads this downstream sheet
        if downstream_sheet in graph["nodes"]:
            for reader_wf in graph["nodes"][downstream_sheet].get("read_by", []):
                downstream_map[downstream_sheet].add(reader_wf)
            for writer_wf in graph["nodes"][downstream_sheet].get("written_by", []):
                downstream_map[downstream_sheet].add(f"[W] {writer_wf}")

    for sheet, consumers in sorted(downstream_map.items()):
        shown = list(consumers)[:3]
        more = f" ...+{len(consumers)-3}" if len(consumers) > 3 else ""
        print(f"  {entity} → {sheet} → {', '.join(shown)}{more}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 rebuild_graph.py <project> [--lifecycle <entity>]")
        sys.exit(1)

    project = sys.argv[1]
    graph = rebuild_graph(project)

    if len(sys.argv) >= 4 and sys.argv[2] == "--lifecycle":
        entity = sys.argv[3]
        lc = extract_lifecycle(graph, entity)
        if lc:
            print_lifecycle(lc)
