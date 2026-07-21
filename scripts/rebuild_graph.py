#!/usr/bin/env python3
"""
Rebuild dependency graph from extracted workflow data.

Supports two data sources:
  - MCP extraction: reads _node_data.json (pre-computed reads/writes)
  - Browser injection: reads _nodes_all.json + _workflows_flat.json
    (extracts R/W from raw node typeId/actionId/selectNodeName)

Usage:
    python3 scripts/rebuild_graph.py 几建
    python3 scripts/rebuild_graph.py 几建 --lifecycle 采购需求  # read-only query
"""

import json, os, sys, re
from collections import defaultdict, Counter

BASE = os.path.expanduser("~/Documents/workflow-output")

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _parse_browser_edges(proj_dir, ctx):
    """Extract edges from Browser-injected raw node data."""
    nodes_all = load_json(os.path.join(proj_dir, "_nodes_all.json"))
    wfs_flat = load_json(os.path.join(proj_dir, "_workflows_flat.json"))

    sheets = ctx.get("worksheets", {})
    ws_id_to_name = {v['id']: name for name, v in sheets.items()}

    pid_to_ws_id = {}
    pid_to_wf_name = {}
    for wf in wfs_flat:
        pid = wf.get('id', '')
        if pid:
            pid_to_ws_id[pid] = wf.get('appId', '')
            pid_to_wf_name[pid] = wf.get('name', '')

    edges = []
    all_sheet_names = set(sheets.keys())
    sheet_readers = defaultdict(set)
    sheet_writers = defaultdict(set)

    # R/W classification by typeId + actionId
    READ_ACTIONS = {5, 6, 20, 405, 406}   # get_single, get_multiple, get_record, query variants
    WRITE_ACTIONS = {1, 2, 3}               # create, update, delete

    for wf in nodes_all:
        pid = wf.get('_pid', '')
        wf_name = pid_to_wf_name.get(pid, f"?({pid[:8]})")
        from_ws_id = pid_to_ws_id.get(pid, '')
        from_ws = ws_id_to_name.get(from_ws_id, '')

        if not from_ws:
            # Try matching by group name or fallback
            from_ws = f"(pid:{pid[:8]})"

        is_child = wf.get('child', False)
        all_sheet_names.add(from_ws)

        for nid, node in wf.get('flowNodeMap', {}).items():
            tid = node.get('typeId', -1)
            if tid not in (6, 7):
                continue

            # Target sheet: prefer appName > selectNodeName > sourceEntityName
            to_ws = (node.get('appName', '') or
                     node.get('selectNodeName', '') or
                     node.get('sourceEntityName', ''))
            if not to_ws:
                continue

            # Skip clearly invalid target names (workflow names leaking in)
            if to_ws in ('按钮触发', '工作表事件', '系统', '组织事件'):
                # Try appId as fallback: if the node has an appId, map it
                aid_sheet = node.get('appId', '')
                mapped = ws_id_to_name.get(aid_sheet, '')
                if mapped:
                    to_ws = mapped
                else:
                    continue

            all_sheet_names.add(to_ws)

            # Determine R vs W
            aid = node.get('actionId', -1)
            if tid == 7 or aid in READ_ACTIONS:
                op = "r"
                sheet_readers[to_ws].add(wf_name)
            elif aid in WRITE_ACTIONS:
                op = "w"
                sheet_writers[to_ws].add(wf_name)
            else:
                op = "w"  # default: CRUD node without recognized action
                sheet_writers[to_ws].add(wf_name)

            edges.append({
                "from_sheet": from_ws,
                "to_sheet": to_ws,
                "op": op,
                "workflow": wf_name,
                "pid": pid,
            })

    return edges, sheet_readers, sheet_writers, all_sheet_names


def _parse_mcp_edges(node_data, all_sheet_names):
    """Extract edges from MCP-extracted _node_data.json."""
    edges = []
    sheet_readers = defaultdict(set)
    sheet_writers = defaultdict(set)

    for pid, wf in node_data.items():
        name = wf.get("name", "")
        worksheet = wf.get("worksheet", "")
        reads = wf.get("reads", []) or []
        writes = wf.get("writes", []) or []

        all_sheet_names.add(worksheet)

        for r_sheet in reads:
            all_sheet_names.add(r_sheet)
            sheet_readers[r_sheet].add(name)
            edges.append({
                "from_sheet": r_sheet, "to_sheet": worksheet,
                "op": "r", "workflow": name, "pid": pid,
            })
            for w_sheet in writes:
                if w_sheet != r_sheet:
                    edges.append({
                        "from_sheet": r_sheet, "to_sheet": w_sheet,
                        "op": "rw_chain", "workflow": name, "pid": pid,
                    })

        for w_sheet in writes:
            all_sheet_names.add(w_sheet)
            sheet_writers[w_sheet].add(name)
            edges.append({
                "from_sheet": worksheet, "to_sheet": w_sheet,
                "op": "w", "workflow": name, "pid": pid,
            })

    return edges, sheet_readers, sheet_writers, all_sheet_names


def rebuild_graph(project_name, project_path=None):
    proj_dir = project_path or os.path.join(BASE, project_name)
    ctx = load_json(os.path.join(proj_dir, "project_context.json"))

    sheets = ctx.get("worksheets", {})
    all_sheet_names = set(sheets.keys())

    # Detect data source: Browser injection has _nodes_all.json
    is_browser = os.path.exists(os.path.join(proj_dir, "_nodes_all.json"))

    if is_browser:
        print(f"[Browser injection mode] Using raw _nodes_all.json")
        node_data = load_json(os.path.join(proj_dir, "_nodes_all.json"))
        wf_count = len(node_data)
        edges, sheet_readers, sheet_writers, all_sheet_names = \
            _parse_browser_edges(proj_dir, ctx)
    else:
        print(f"[MCP extraction mode] Using _node_data.json")
        node_data = load_json(os.path.join(proj_dir, "_node_data.json"))
        wf_count = len(node_data)
        edges, sheet_readers, sheet_writers, all_sheet_names = \
            _parse_mcp_edges(node_data, all_sheet_names)

    # Build nodes
    graph = {"nodes": {}, "edges": edges}
    for sname in sorted(all_sheet_names):
        sheet_info = sheets.get(sname, {})
        graph["nodes"][sname] = {
            "field_count": sheet_info.get("field_count", 0) if isinstance(sheet_info, dict) else 0,
            "module": sheet_info.get("module", "") if isinstance(sheet_info, dict) else "",
            "read_by": sorted(sheet_readers.get(sname, [])),
            "written_by": sorted(sheet_writers.get(sname, [])),
            "reader_count": len(sheet_readers.get(sname, [])),
            "writer_count": len(sheet_writers.get(sname, [])),
        }

    # Stats
    r_edges = sum(1 for e in edges if e["op"] == "r")
    w_edges = sum(1 for e in edges if e["op"] == "w")
    c_edges = sum(1 for e in edges if e["op"] == "rw_chain")

    graph["stats"] = {
        "total_sheets": len(graph["nodes"]),
        "total_edges": len(edges),
        "total_workflows": wf_count,
        "r_edges": r_edges,
        "w_edges": w_edges,
        "rw_chain_edges": c_edges,
        "sheets_read_only": sum(1 for s in graph["nodes"].values() if s["reader_count"] > 0 and s["writer_count"] == 0),
        "sheets_written_only": sum(1 for s in graph["nodes"].values() if s["writer_count"] > 0 and s["reader_count"] == 0),
        "sheets_both": sum(1 for s in graph["nodes"].values() if s["reader_count"] > 0 and s["writer_count"] > 0),
        "sheets_orphan": sum(1 for s in graph["nodes"].values() if s["reader_count"] == 0 and s["writer_count"] == 0),
    }

    out_path = os.path.join(proj_dir, "dependency_graph.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"Dependency graph rebuilt: {out_path}")
    print(f"  Sheets: {graph['stats']['total_sheets']}")
    print(f"  Edges: {len(edges)} (r:{r_edges} w:{w_edges} chain:{c_edges})")
    print(f"  Read-only: {graph['stats']['sheets_read_only']}")
    print(f"  Written-only: {graph['stats']['sheets_written_only']}")
    print(f"  Both: {graph['stats']['sheets_both']}")
    print(f"  Orphan: {graph['stats']['sheets_orphan']}")
    return graph


def extract_lifecycle(graph, entity_name):
    node = graph["nodes"].get(entity_name)
    if not node:
        print(f"Entity '{entity_name}' not found in graph")
        return None

    edges_in = [e for e in graph["edges"] if e["to_sheet"] == entity_name and e["op"] in ("w", "rw_chain")]
    edges_out = [e for e in graph["edges"] if e["from_sheet"] == entity_name]

    wf_map = {}
    for e in edges_in + edges_out:
        wf_map.setdefault(e["pid"], {
            "name": e["workflow"], "reads": set(), "writes": set(), "edges": [],
        })
        wf_map[e["pid"]]["edges"].append(e)
        if e["op"] in ("w", "rw_chain") and e["to_sheet"] != entity_name:
            wf_map[e["pid"]]["writes"].add(e["to_sheet"])
        if e["op"] == "r" and e["from_sheet"] != entity_name:
            wf_map[e["pid"]]["reads"].add(e["from_sheet"])

    for pid, info in wf_map.items():
        for e in edges_in + edges_out:
            if e["pid"] == pid:
                if e["op"] in ("w", "rw_chain") and e["to_sheet"] == entity_name:
                    info["writes"].add(entity_name)
                if e["op"] == "r" and e["from_sheet"] == entity_name:
                    info["reads"].add(entity_name)

    return {
        "entity": entity_name,
        "reader_count": node["reader_count"],
        "writer_count": node["writer_count"],
        "read_by": node["read_by"],
        "written_by": node["written_by"],
        "workflows": {pid: {"name": i["name"], "reads": sorted(i["reads"]), "writes": sorted(i["writes"])}
                      for pid, i in wf_map.items()},
    }


def print_lifecycle(lifecycle):
    entity = lifecycle["entity"]
    print(f"\n{'='*60}")
    print(f"  生命周期: {entity}")
    print(f"  被 {lifecycle['reader_count']} 个工作流读, 被 {lifecycle['writer_count']} 个工作流写")
    print(f"{'='*60}")

    creators, updaters, consumers = [], [], []
    for pid, info in lifecycle["workflows"].items():
        if entity in info["writes"] and entity not in info["reads"]:
            creators.append((pid, info))
        elif entity in info["writes"]:
            updaters.append((pid, info))
        else:
            consumers.append((pid, info))

    print(f"\n── 创建者 ({len(creators)}) ──")
    for pid, info in creators:
        print(f"  {info['name']}  (PID: {pid})")
        if info['reads'] or info['writes']:
            print(f"    R: {info['reads']}  W: {info['writes']}")

    print(f"\n── 更新者 ({len(updaters)}) ──")
    for pid, info in updaters:
        print(f"  {info['name']}  (PID: {pid})")
        print(f"    R: {info['reads']}  W: {info['writes']}")

    print(f"\n── 消费者 ({len(consumers)}) ──")
    for pid, info in consumers:
        print(f"  {info['name']}  (PID: {pid})")
        print(f"    R: {info['reads']}")

    all_written = set()
    for pid, info in lifecycle["workflows"].items():
        all_written.update(info["writes"])
    all_written.discard(entity)

    if all_written:
        print(f"\n── 下游影响链 ──")
        downstream = defaultdict(set)
        for ds in sorted(all_written):
            if ds in graph["nodes"]:
                for r in graph["nodes"][ds].get("read_by", []):
                    downstream[ds].add(r)
                for w in graph["nodes"][ds].get("written_by", []):
                    downstream[ds].add(f"[W] {w}")
        for sheet, consumers_set in sorted(downstream.items()):
            shown = list(consumers_set)[:3]
            more = f" ...+{len(consumers_set)-3}" if len(consumers_set) > 3 else ""
            print(f"  {entity} -> {sheet} -> {', '.join(shown)}{more}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 rebuild_graph.py <project> [--lifecycle <entity>]")
        sys.exit(1)

    project = sys.argv[1]
    project_path = None
    if "--project-path" in sys.argv:
        path_index = sys.argv.index("--project-path")
        if path_index + 1 >= len(sys.argv):
            print("--project-path requires a value", file=sys.stderr)
            sys.exit(2)
        project_path = sys.argv[path_index + 1]
    if len(sys.argv) >= 4 and sys.argv[2] == "--lifecycle":
        graph_path = os.path.join(
            project_path or os.path.join(BASE, project),
            "dependency_graph.json",
        )
        if not os.path.exists(graph_path):
            print(
                f"Dependency graph missing: {graph_path}. "
                "Run rebuild_graph.py <project> first.",
                file=sys.stderr,
            )
            sys.exit(2)
        graph = load_json(graph_path)
        entity = sys.argv[3]
        lc = extract_lifecycle(graph, entity)
        if lc:
            print_lifecycle(lc)
    else:
        rebuild_graph(project, project_path)
