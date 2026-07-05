#!/usr/bin/env python3
"""
Query the FTS5 search index for hhr-plan project data.

Usage:
    # Fuzzy search workflows by name
    python3 scripts/search.py "采购需求" --type workflow --project 几建

    # Reverse lookup: which workflows write to a sheet?
    python3 scripts/search.py "采购需求" --writes-to --project 几建

    # Reverse lookup: which workflows read from a sheet?
    python3 scripts/search.py "任务清单" --reads-from --project 几建

    # Find sheets containing a field
    python3 scripts/search.py "合同编号" --field-search --project 几建

    # Search across all projects
    python3 scripts/search.py "采购" --type workflow --all-projects

    # JSON output for programmatic consumption
    python3 scripts/search.py "采购需求" --type workflow --project 几建 --format json

    # Show all sheets in a project
    python3 scripts/search.py --list-sheets --project 几建

    # Exact workflow name lookup (bypasses FTS, fast path)
    python3 scripts/search.py "生成询价表" --exact-name --project 几建

    # Direct PID lookup
    python3 scripts/search.py 69af8e0bdd5e32da42401a8a --pid --project 几建

    # Deep search: FTS hits + node_chain + entity lifecycle in one call
    python3 scripts/search.py "付款计划" --deep --project 几建
    python3 scripts/search.py "付款计划" --deep -p 几建 -f json  # JSON output for agents
"""

import json
import os
import re
import sqlite3
import sys


BASE_DIR = os.path.expanduser("~/Documents/workflow-output")
DB_PATH = os.path.join(BASE_DIR, "_search_index.db")


def tokenize_chinese(text):
    """Same tokenizer as build_search_index.py."""
    if not text:
        return ""
    chars = list(text)
    tokens = []
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    tokens.extend(chars)
    return " ".join(tokens)


def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Search index not found at {DB_PATH}", file=sys.stderr)
        print("Run: python3 scripts/build_search_index.py --all", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── query functions ─────────────────────────────────────────────

def search_fts(conn, query, entity_type=None, project=None, limit=20):
    """Fuzzy search using FTS5."""
    tokens = tokenize_chinese(query)
    if not tokens:
        return []

    conditions = [f"search_fts MATCH '{tokens}'"]
    params = []

    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if project:
        conditions.append("project = ?")
        params.append(project)

    where = " AND ".join(conditions)
    sql = f"SELECT project, entity_type, entity_name, entity_id, parent_context, extra_json, rank FROM search_fts WHERE {where} ORDER BY rank LIMIT ?"
    params.append(limit)

    return conn.execute(sql, params).fetchall()


def search_writes_to(conn, sheet_name, project=None):
    """Find workflows that write to a given sheet."""
    if project:
        rows = conn.execute(
            """SELECT w.pid, w.name, w.worksheet, w.trigger_type, w.node_count, w.project
               FROM sheet_ops s JOIN workflows w ON s.workflow_pid = w.pid AND s.project = w.project
               WHERE s.sheet_name = ? AND s.op = 'w' AND s.project = ?
               ORDER BY w.name""",
            (sheet_name, project),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT w.pid, w.name, w.worksheet, w.trigger_type, w.node_count, w.project
               FROM sheet_ops s JOIN workflows w ON s.workflow_pid = w.pid AND s.project = w.project
               WHERE s.sheet_name = ? AND s.op = 'w'
               ORDER BY w.project, w.name""",
            (sheet_name,),
        ).fetchall()
    return rows


def search_reads_from(conn, sheet_name, project=None):
    """Find workflows that read from a given sheet."""
    if project:
        rows = conn.execute(
            """SELECT w.pid, w.name, w.worksheet, w.trigger_type, w.node_count, w.project
               FROM sheet_ops s JOIN workflows w ON s.workflow_pid = w.pid AND s.project = w.project
               WHERE s.sheet_name = ? AND s.op = 'r' AND s.project = ?
               ORDER BY w.name""",
            (sheet_name, project),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT w.pid, w.name, w.worksheet, w.trigger_type, w.node_count, w.project
               FROM sheet_ops s JOIN workflows w ON s.workflow_pid = w.pid AND s.project = w.project
               WHERE s.sheet_name = ? AND s.op = 'r'
               ORDER BY w.project, w.name""",
            (sheet_name,),
        ).fetchall()
    return rows


def search_field(conn, field_name, project=None):
    """Find sheets that contain a field with the given name."""
    if project:
        rows = conn.execute(
            """SELECT DISTINCT sheet_name, field_name, field_type, project
               FROM fields_index
               WHERE field_name LIKE ? AND project = ?
               ORDER BY sheet_name""",
            (f"%{field_name}%", project),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT DISTINCT sheet_name, field_name, field_type, project
               FROM fields_index
               WHERE field_name LIKE ?
               ORDER BY project, sheet_name""",
            (f"%{field_name}%",),
        ).fetchall()
    return rows


def list_sheets(conn, project):
    """List all sheets in a project."""
    return conn.execute(
        "SELECT DISTINCT entity_name FROM search_fts WHERE entity_type='sheet' AND project=? ORDER BY entity_name",
        (project,),
    ).fetchall()


def resolve_alias(conn, alias, project=None):
    """Resolve an alias to canonical name."""
    if project:
        return conn.execute(
            "SELECT alias_type, canonical FROM aliases WHERE alias=? AND project=?",
            (alias, project),
        ).fetchall()
    return conn.execute(
        "SELECT project, alias_type, canonical FROM aliases WHERE alias=?",
        (alias,),
    ).fetchall()


def get_wf_reads_writes(conn, pid, project):
    """Get full r/w lists for a specific workflow."""
    ops = conn.execute(
        "SELECT sheet_name, op FROM sheet_ops WHERE workflow_pid=? AND project=?",
        (pid, project),
    ).fetchall()
    reads = [r["sheet_name"] for r in ops if r["op"] == "r"]
    writes = [r["sheet_name"] for r in ops if r["op"] == "w"]
    return reads, writes


def search_exact_name(conn, name, project=None, entity_type=None):
    """Exact name lookup bypassing FTS — fast, no tokenization issues."""
    conditions = ["entity_name LIKE ?"]
    params = [f"%{name}%"]

    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if project:
        conditions.append("project = ?")
        params.append(project)

    where = " AND ".join(conditions)
    sql = f"SELECT project, entity_type, entity_name, entity_id, parent_context, extra_json FROM search_fts WHERE {where} ORDER BY entity_name LIMIT 30"
    return conn.execute(sql, params).fetchall()


def lookup_pid(conn, pid, project):
    """Direct PID lookup from workflows table — bypasses FTS entirely."""
    if project:
        return conn.execute(
            "SELECT pid, project, name, worksheet, trigger_type, node_count FROM workflows WHERE pid=? AND project=?",
            (pid, project),
        ).fetchall()
    return conn.execute(
        "SELECT pid, project, name, worksheet, trigger_type, node_count FROM workflows WHERE pid=?",
        (pid,),
    ).fetchall()


def verify_index_integrity(conn, project):
    """Check if a project's data is actually in the index. Returns (in_index, count)."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM search_fts WHERE project=?",
        (project,),
    ).fetchone()
    cnt = row["cnt"] if row else 0
    return cnt > 0, cnt


# ── deep search ─────────────────────────────────────────────────

def search_deep(conn, query, project):
    """Deep search: FTS hits + full node_chain + entity lifecycle in one call.

    Returns a dict ready for JSON output:
      {hits: [...], lifecycle: {sheet, creators, updaters, consumers, downstream}}
    """
    # Step 1: FTS search for workflows
    wf_rows = search_fts(conn, query, "workflow", project, limit=50)
    if not wf_rows:
        return {"hits": [], "lifecycle": {}}

    proj_dir = os.path.join(BASE_DIR, project)

    # Step 2: Load _node_data.json for node_chain per PID
    nd_path = os.path.join(proj_dir, "_node_data.json")
    node_data = {}
    if os.path.exists(nd_path):
        with open(nd_path, encoding="utf-8") as f:
            node_data = json.load(f)

    # Step 3: Load dependency_graph.json for lifecycle
    graph_path = os.path.join(proj_dir, "dependency_graph.json")
    dep_edges = []
    if os.path.exists(graph_path):
        with open(graph_path, encoding="utf-8") as f:
            g = json.load(f)
        dep_edges = g.get("edges", [])

    # Step 4: Enrich each workflow hit
    hits = []
    seen_pids = set()
    for r in wf_rows:
        pid = r["entity_id"]
        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        nd = node_data.get(pid, {})
        hit = {
            "pid": pid,
            "name": r["entity_name"],
            "worksheet": nd.get("worksheet", r["parent_context"] or ""),
            "trigger": nd.get("trigger", ""),
            "node_count": nd.get("node_count", 0),
            "reads": nd.get("reads", []),
            "writes": nd.get("writes", []),
            "nodes_summary": nd.get("nodes_summary", {}),
            "node_chain": nd.get("node_chain", []),
        }
        hits.append(hit)

    # Step 5: Build lifecycle — find all sheets referenced by hits
    # Collect all sheet names that are targets of the query
    target_sheets = set()
    for h in hits:
        ws = h["worksheet"]
        if ws and ws != "未分类":
            target_sheets.add(ws)
    # Also use the query itself as a possible sheet name
    target_sheets.add(query)

    # Build lifecycle: creators, updaters, consumers, downstream by PID
    creators = []
    updaters = []
    consumers = []
    downstream = []
    creator_pids = set()
    updater_pids = set()
    consumer_pids = set()

    for edge in dep_edges:
        from_sheet = edge.get("from_sheet", "")
        to_sheet = edge.get("to_sheet", "")
        op = edge.get("op", "")
        wf_name = edge.get("workflow", "")
        wf_pid = edge.get("pid", "")

        # Edge touches a target sheet?
        if from_sheet not in target_sheets and to_sheet not in target_sheets:
            continue

        if from_sheet in target_sheets:
            downstream.append({
                "from": from_sheet,
                "to": to_sheet,
                "op": op,
                "workflow": wf_name,
                "pid": wf_pid,
            })

        # Collect creators/updaters/consumers for target sheets
        if to_sheet in target_sheets:
            if op == "w":
                if wf_pid and wf_pid not in creator_pids:
                    updater_pids.add(wf_pid)
            elif op == "r":
                if wf_pid and wf_pid not in consumer_pids:
                    consumers.append({"workflow": wf_name, "pid": wf_pid, "from": from_sheet})
                    consumer_pids.add(wf_pid)

    # Deduplicate downstream
    seen_down = set()
    uniq_down = []
    for d in downstream:
        key = (d.get("from"), d.get("to"), d.get("pid"))
        if key not in seen_down:
            seen_down.add(key)
            uniq_down.append(d)

    lifecycle = {
        "sheets": sorted(target_sheets),
        "creators": creators,
        "updaters": updaters,
        "consumers": consumers,
        "downstream": uniq_down,
        "_note": "creators/updaters from dep graph; 'updaters' may overlap with 'consumers'",
    }

    return {"hits": hits, "lifecycle": lifecycle}


def format_deep(results, fmt="human"):
    """Output deep search results in human or JSON format."""
    if fmt == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    hits = results.get("hits", [])
    lifecycle = results.get("lifecycle", {})

    if not hits:
        print("No results found.")
        return

    # ── Hits ──
    print(f"\n{'='*60}")
    print(f"  {len(hits)} workflow(s) matched")
    print(f"{'='*60}")

    for i, h in enumerate(hits):
        print(f"\n--- [{i+1}] {h['name']} ---")
        print(f"  PID:       {h['pid']}")
        print(f"  Worksheet: {h['worksheet']}")
        print(f"  Trigger:   {h['trigger']}")
        print(f"  Nodes:     {h['node_count']}")
        print(f"  Summary:   create={h['nodes_summary'].get('create',0)} update={h['nodes_summary'].get('update',0)} query={h['nodes_summary'].get('query',0)} approval={h['nodes_summary'].get('approval',0)}")

        # Node chain
        chain = h.get("node_chain", [])
        if chain:
            print(f"  Node chain ({len(chain)}):")
            for j, nc in enumerate(chain):
                orphan = " [orphan]" if nc.get("_orphan") else ""
                mode = nc.get("mode", "")
                target = nc.get("target", "")
                detail = f" → {mode}" if mode else ""
                if target:
                    detail += f" {target}"
                conditions = nc.get("conditions", [])
                cond_str = ""
                if conditions:
                    cond_str = f"  |  {'; '.join(conditions[:2])}"
                fields = nc.get("fields", [])
                field_str = ""
                if fields:
                    field_str = f"  |  {', '.join(fields[:4])}"
                delay = nc.get("delay", "")
                delay_str = f"  |  ⏱{delay}" if delay else ""
                print(f"    [{j}] {nc.get('typeName','?')}: {nc.get('name','?')}{orphan}{detail}{cond_str}{field_str}{delay_str}")

        # Reads / Writes
        if h.get("reads"):
            print(f"  Reads:  {', '.join(h['reads'])}")
        if h.get("writes"):
            print(f"  Writes: {', '.join(h['writes'])}")

    # ── Lifecycle ──
    if lifecycle:
        print(f"\n{'='*60}")
        print(f"  Entity Lifecycle")
        print(f"{'='*60}")
        sheets = lifecycle.get("sheets", [])
        print(f"  Sheets: {', '.join(sheets)}")

        updaters = lifecycle.get("updaters", [])
        if updaters:
            print(f"  Updaters ({len(updaters)}): {', '.join(updaters)}")

        consumers = lifecycle.get("consumers", [])
        if consumers:
            print(f"\n  Consumers ({len(consumers)}):")
            for c in consumers:
                print(f"    {c['workflow']}  [pid:{c['pid']}]  (from {c.get('from','?')})")

        downstream = lifecycle.get("downstream", [])
        if downstream:
            print(f"\n  Downstream chains ({len(downstream)}):")
            for d in downstream:
                op_label = {"r": "→(read)", "w": "→(write)", "rw_chain": "→(chain)"}.get(d.get("op",""), d.get("op",""))
                print(f"    {d.get('from','?')} {op_label} {d.get('to','?')}  [{d.get('workflow','?')}]")


# ── output formatting ───────────────────────────────────────────

def format_human(results, mode, query):
    """Human-readable output."""
    if not results:
        print(f"No results found.")
        return

    by_project = {}
    for r in results:
        proj = r["project"]
        by_project.setdefault(proj, []).append(r)

    for proj, rows in by_project.items():
        print(f"\n=== {proj} ({len(rows)} results) ===")

        if mode == "fts" or mode == "exact_name":
            for r in rows:
                extra = json.loads(r["extra_json"]) if r["extra_json"] else {}
                ctx = f" [{r['parent_context']}]" if r["parent_context"] else ""
                print(f"  [{r['entity_type']}] {r['entity_name']}{ctx}")
                rank_str = f"  rank: {r['rank']:.2f}" if "rank" in r.keys() else ""
                print(f"          id: {r['entity_id']}{rank_str}")
                if extra:
                    detail = ", ".join(f"{k}={v}" for k, v in extra.items())
                    print(f"          {detail}")

        elif mode in ("writes_to", "reads_from", "pid_lookup"):
            for r in rows:
                print(f"  {r['name']}  [pid:{r['pid']}]  {r['trigger_type']}  sheet:{r['worksheet']}  nodes:{r['node_count']}")

        elif mode == "field":
            for r in rows:
                print(f"  {r['sheet_name']}  →  {r['field_name']}  ({r['field_type']})")

        elif mode == "sheets":
            for r in rows:
                print(f"  {r['entity_name']}")

    print(f"\n--- Total: {len(results)} results ---")


def format_json_output(results, mode, query):
    """JSON output for agent consumption."""
    out = {"query": query, "mode": mode, "count": len(results), "results": []}
    for r in results:
        d = dict(r)
        if "extra_json" in d and d["extra_json"]:
            try:
                d["extra"] = json.loads(d["extra_json"])
            except:
                pass
            del d["extra_json"]
        out["results"].append(d)
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ── main ────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    args = sys.argv[1:]
    query = None
    mode = "fts"
    entity_type = None
    project = None
    fmt = "human"
    limit = 30

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--type", "-t"):
            i += 1
            entity_type = args[i]
        elif a in ("--project", "-p"):
            i += 1
            project = args[i]
        elif a == "--all-projects":
            project = None
        elif a in ("--writes-to",):
            mode = "writes_to"
        elif a in ("--reads-from",):
            mode = "reads_from"
        elif a in ("--field-search",):
            mode = "field"
        elif a in ("--exact-name",):
            mode = "exact_name"
        elif a in ("--pid",):
            mode = "pid_lookup"
        elif a in ("--list-sheets",):
            mode = "sheets"
        elif a in ("--resolve-alias",):
            mode = "alias"
        elif a in ("--deep",):
            mode = "deep"
        elif a in ("--check-index",):
            mode = "check_index"
        elif a in ("--format", "-f"):
            i += 1
            fmt = args[i]
        elif a in ("--limit", "-n"):
            i += 1
            limit = int(args[i])
        elif not a.startswith("-"):
            query = a
        i += 1

    if mode != "sheets" and not query:
        print("ERROR: Search query required.", file=sys.stderr)
        sys.exit(1)
    if mode != "sheets" and mode != "alias" and project is None and mode != "alias":
        # Without --all-projects or --project, search all
        pass

    conn = get_conn()

    if mode == "fts":
        results = search_fts(conn, query, entity_type, project, limit)
    elif mode == "exact_name":
        results = search_exact_name(conn, query, project, entity_type)
    elif mode == "pid_lookup":
        results = lookup_pid(conn, query, project)
    elif mode == "writes_to":
        results = search_writes_to(conn, query, project)
    elif mode == "reads_from":
        results = search_reads_from(conn, query, project)
    elif mode == "field":
        results = search_field(conn, query, project)
    elif mode == "sheets":
        if not project:
            print("ERROR: --project required for --list-sheets", file=sys.stderr)
            sys.exit(1)
        results = list_sheets(conn, project)
    elif mode == "deep":
        if project:
            results = search_deep(conn, query, project)
        else:
            # Cross-project deep: search all, then group by project
            wf_rows = search_fts(conn, query, "workflow", None, limit=100)
            by_project = {}
            for r in wf_rows:
                proj = r["project"]
                by_project.setdefault(proj, []).append(r)
            results = {"cross_project": True, "query": query, "projects": {}}
            for proj, rows in by_project.items():
                proj_results = search_deep(conn, query, proj)
                if proj_results.get("hits"):
                    results["projects"][proj] = proj_results
            if fmt == "json":
                print(json.dumps(results, ensure_ascii=False, indent=2))
            else:
                print(f"\n{'='*60}")
                print(f"  Cross-project deep search: \"{query}\"")
                print(f"{'='*60}")
                for proj, pr in results["projects"].items():
                    print(f"\n  === {proj} ({len(pr.get('hits',[]))} workflows) ===")
                    for h in pr.get("hits", []):
                        print(f"    {h['name']}  [{h['pid'][:16]}...]  {h['trigger']}  {h['node_count']}n")
            conn.close()
            return
    elif mode == "alias":
        results = resolve_alias(conn, query, project)
    elif mode == "check_index":
        in_index, cnt = verify_index_integrity(conn, query)
        results = [{"project": query, "in_index": in_index, "entry_count": cnt}]
        # Override format: check_index always uses its own output
        if in_index:
            print(f"OK: '{query}' has {cnt} entries in search index")
        else:
            print(f"MISSING: '{query}' has 0 entries in search index")
        conn.close()
        return

    if fmt == "json":
        if mode == "deep":
            # deep output is already structured JSON
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            format_json_output(results, mode, query)
    elif mode == "deep":
        format_deep(results, fmt="human")
    else:
        format_human(results, mode, query)

    conn.close()


if __name__ == "__main__":
    main()
