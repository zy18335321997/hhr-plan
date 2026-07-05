#!/usr/bin/env python3
"""
Build FTS5 search index for hhr-plan project data.

Usage:
    python3 scripts/build_search_index.py --all
    python3 scripts/build_search_index.py 几建

Input:  project_context.json + business-flow-manifest.json + _node_data.json + aliases.json
Output: ~/Documents/workflow-output/_search_index.db
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path


BASE_DIR = os.path.expanduser("~/Documents/workflow-output")
DB_PATH = os.path.join(BASE_DIR, "_search_index.db")


def tokenize_chinese(text):
    """Convert Chinese text to space-separated overlapping bigrams + unigrams for FTS5."""
    if not text:
        return ""
    chars = list(text)
    tokens = []
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    tokens.extend(chars)
    return " ".join(tokens)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_projects(project_name=None):
    """Find all projects with usable data from the registry."""
    reg_path = os.path.join(BASE_DIR, "projects_registry.json")
    if not os.path.exists(reg_path):
        print(f"Registry not found: {reg_path}")
        return []

    reg = load_json(reg_path)
    projects = []

    for name, meta in reg.get("projects", {}).items():
        if project_name and name != project_name:
            continue
        if not meta.get("context_ready"):
            continue
        proj_path = meta.get("path", os.path.join(BASE_DIR, name))
        proj_path = os.path.expanduser(proj_path)
        if not os.path.isdir(proj_path):
            continue
        projects.append((name, proj_path))

    return projects


def build_index(projects):
    """Build sqlite3 FTS5 index from all project data sources.

    Uses incremental upsert: deletes old data for the projects being rebuilt,
    then inserts fresh data. Other projects in the DB are untouched.
    """
    db_exists = os.path.exists(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # If DB already exists, purge old rows for the projects being rebuilt
    if db_exists:
        proj_names = [p[0] for p in projects]
        for table in ("search_fts", "workflows", "sheet_ops", "fields_index", "aliases"):
            for pn in proj_names:
                conn.execute(f"DELETE FROM {table} WHERE project=?", (pn,))
        placeholders = ",".join("?" * len(proj_names))
        conn.execute(f"DELETE FROM projects WHERE name IN ({placeholders})", proj_names)
        conn.commit()

    # -- Layer 1: relational tables --
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            name TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            worksheets INTEGER,
            workflows INTEGER,
            built_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS workflows (
            pid TEXT NOT NULL,
            project TEXT NOT NULL REFERENCES projects(name),
            name TEXT NOT NULL,
            worksheet TEXT NOT NULL,
            trigger_type TEXT,
            node_count INTEGER,
            PRIMARY KEY (pid, project)
        );

        CREATE TABLE IF NOT EXISTS sheet_ops (
            workflow_pid TEXT NOT NULL,
            project TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            op TEXT NOT NULL CHECK(op IN ('r','w')),
            PRIMARY KEY (workflow_pid, project, sheet_name, op)
        );
        CREATE INDEX IF NOT EXISTS idx_sheet_ops_lookup ON sheet_ops(project, sheet_name, op);

        CREATE TABLE IF NOT EXISTS fields_index (
            control_id TEXT NOT NULL,
            project TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_type TEXT,
            is_title INTEGER DEFAULT 0,
            PRIMARY KEY (control_id, project)
        );
        CREATE INDEX IF NOT EXISTS idx_fields_sheet ON fields_index(project, sheet_name);

        CREATE TABLE IF NOT EXISTS aliases (
            project TEXT NOT NULL,
            alias_type TEXT NOT NULL CHECK(alias_type IN ('sheet','workflow','field')),
            alias TEXT NOT NULL,
            canonical TEXT NOT NULL,
            PRIMARY KEY (project, alias_type, alias)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
            project,
            entity_type,
            entity_name,
            entity_id,
            parent_context,
            search_text,
            extra_json,
            tokenize='unicode61'
        );
    """)

    total_wf = 0
    total_sheets = 0
    total_fields = 0

    for proj_name, proj_path in projects:
        print(f"Indexing: {proj_name} ...")

        # Load source files
        ctx_path = os.path.join(proj_path, "project_context.json")
        manifest_path = os.path.join(proj_path, "business-flow-manifest.json")
        node_data_path = os.path.join(proj_path, "_node_data.json")
        aliases_path = os.path.join(proj_path, "aliases.json")

        ctx = load_json(ctx_path) if os.path.exists(ctx_path) else {}
        manifest = load_json(manifest_path) if os.path.exists(manifest_path) else {}
        node_data = load_json(node_data_path) if os.path.exists(node_data_path) else {}
        aliases_data = load_json(aliases_path) if os.path.exists(aliases_path) else {}

        worksheets = ctx.get("worksheets", {})

        # Fallback: if project_context has no worksheet definitions, extract sheet
        # names from the manifest's table keys so they can still be searched.
        sheet_names_from_manifest = []
        if not worksheets and manifest:
            sheet_names_from_manifest = list(manifest.get("tables", {}).keys())

        ws_count = ctx.get("project", {}).get("total_worksheets", 0) or len(worksheets) or len(sheet_names_from_manifest)
        wf_count = ctx.get("project", {}).get("total_workflows", 0) or len(node_data)

        conn.execute(
            "INSERT OR REPLACE INTO projects(name, path, worksheets, workflows) VALUES(?,?,?,?)",
            (proj_name, proj_path, ws_count, wf_count),
        )

        # -- Worksheets + Fields --
        # Index sheets from project_context if available; otherwise from manifest keys
        if worksheets:
            sheet_iter = worksheets.items()
        else:
            sheet_iter = ((name, {}) for name in sheet_names_from_manifest)

        for ws_name, ws_info in sheet_iter:
            total_sheets += 1
            sheet_id = ws_info.get("id", "")
            tokenized = tokenize_chinese(ws_name)
            conn.execute(
                "INSERT INTO search_fts(project, entity_type, entity_name, entity_id, parent_context, search_text, extra_json) VALUES(?,?,?,?,?,?,?)",
                (proj_name, "sheet", ws_name, sheet_id, "", tokenized, "{}"),
            )
            for field in ws_info.get("fields", []):
                total_fields += 1
                fid = field.get("id", "")
                fname = field.get("name", "")
                ftype = field.get("type", "")
                is_title = 1 if field.get("isTitle") else 0
                conn.execute(
                    "INSERT OR REPLACE INTO fields_index(control_id, project, sheet_name, field_name, field_type, is_title) VALUES(?,?,?,?,?,?)",
                    (fid, proj_name, ws_name, fname, ftype, is_title),
                )
                tokenized_f = tokenize_chinese(fname)
                conn.execute(
                    "INSERT INTO search_fts(project, entity_type, entity_name, entity_id, parent_context, search_text, extra_json) VALUES(?,?,?,?,?,?,?)",
                    (proj_name, "field", fname, fid, ws_name, tokenized_f, json.dumps({"type": ftype}, ensure_ascii=False)),
                )

        # -- Workflows (node_data preferred, manifest as fallback) --
        if node_data:
            workflows_source = "node_data"
            wf_iter = ((pid, info) for pid, info in node_data.items())
        elif manifest:
            # Fallback: extract flat workflow list from manifest's tables dict
            workflows_source = "manifest"
            seen_pids = set()
            flat_list = []
            for sheet_name, wfs in manifest.get("tables", {}).items():
                for wf in wfs:
                    pid = wf.get("pid", "")
                    if pid and pid not in seen_pids:
                        seen_pids.add(pid)
                        flat_list.append((pid, {
                            "name": wf.get("wf", ""),
                            "worksheet": sheet_name,
                            "trigger": wf.get("trigger", ""),
                            "node_count": wf.get("node_count", 0),
                            "reads": wf.get("r", []) or [],
                            "writes": wf.get("w", []) or [],
                        }))
            wf_iter = iter(flat_list)
        else:
            wf_iter = iter([])

        for pid, wf_info in wf_iter:
            total_wf += 1
            wf_name = wf_info.get("name", "")
            worksheet = wf_info.get("worksheet", "")
            trigger = wf_info.get("trigger", "")
            node_count = wf_info.get("node_count", 0)

            conn.execute(
                "INSERT OR REPLACE INTO workflows(pid, project, name, worksheet, trigger_type, node_count) VALUES(?,?,?,?,?,?)",
                (pid, proj_name, wf_name, worksheet, trigger, node_count),
            )

            # Read ops
            for sheet in wf_info.get("reads", []) or []:
                conn.execute(
                    "INSERT OR REPLACE INTO sheet_ops(workflow_pid, project, sheet_name, op) VALUES(?,?,?,?)",
                    (pid, proj_name, sheet, "r"),
                )
            # Write ops
            for sheet in wf_info.get("writes", []) or []:
                conn.execute(
                    "INSERT OR REPLACE INTO sheet_ops(workflow_pid, project, sheet_name, op) VALUES(?,?,?,?)",
                    (pid, proj_name, sheet, "w"),
                )

            # FTS entry
            tokenized = tokenize_chinese(wf_name)
            search_context = worksheet  # parent sheet
            extra = json.dumps({"trigger": trigger, "node_count": node_count}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO search_fts(project, entity_type, entity_name, entity_id, parent_context, search_text, extra_json) VALUES(?,?,?,?,?,?,?)",
                (proj_name, "workflow", wf_name, pid, search_context, tokenized, extra),
            )

        # -- Aliases --
        # aliases.json can have two formats:
        #   Format A: {"worksheets": {...}, "workflows": {...}, "fields": {...}}
        #   Format B: {"mappings": {...}} where values are lists
        alias_map = aliases_data.get("mappings", {})
        if not alias_map:
            for atype in ("worksheets", "workflows", "fields"):
                alias_map.update(aliases_data.get(atype, {}))

        atype_remap = {"worksheets": "sheet", "workflows": "workflow", "fields": "field", "mappings": "sheet"}
        for alias, canonical in alias_map.items():
            # canonical can be a string or a list; normalize to string
            if isinstance(canonical, list):
                canonical = canonical[0] if canonical else ""
            if not canonical or not isinstance(canonical, str):
                continue
            if alias == canonical:
                continue
            # Determine type from which dict it came from
            for atype_src in ("worksheets", "workflows", "fields", "mappings"):
                if alias in aliases_data.get(atype_src, {}):
                    conn.execute(
                        "INSERT OR REPLACE INTO aliases(project, alias_type, alias, canonical) VALUES(?,?,?,?)",
                        (proj_name, atype_remap.get(atype_src, "sheet"), alias, canonical),
                    )
                    break

        print(f"  Sheets: {ws_count}  Workflows: {wf_count}  Fields: {total_fields}")

    # Optimize
    conn.execute("ANALYZE")
    conn.commit()

    size_kb = os.path.getsize(DB_PATH) / 1024
    print(f"\nIndex built: {DB_PATH}")
    print(f"Size: {size_kb:.0f} KB")
    print(f"Projects: {len(projects)}")
    print(f"Total: {total_wf} workflows, {total_sheets} sheets, {total_fields} fields")

    conn.close()


def main():
    project_name = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--all":
            project_name = None
        elif arg.startswith("-"):
            print(__doc__)
            sys.exit(1)
        else:
            project_name = arg

    projects = discover_projects(project_name)
    if not projects:
        print("No projects found. Run workflow extraction first.")
        sys.exit(1)

    build_index(projects)


if __name__ == "__main__":
    main()
