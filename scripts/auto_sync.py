#!/usr/bin/env python3
"""
Auto-sync all derived data (index, graph, topology).
Only rebuilds what's changed. Idempotent — safe to run anytime.

Usage:
    python3 scripts/auto_sync.py              # sync all projects
    python3 scripts/auto_sync.py --check-only  # report what's stale, don't rebuild
    python3 scripts/auto_sync.py 几建          # sync single project

Called by:
    - extract-project.py (after extraction)
    - explicit repair/sync when doctor or freshness checks report stale data
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.expanduser("~/Documents/workflow-output")
REGISTRY = os.path.join(BASE, "projects_registry.json")
INDEX_DB = os.path.join(BASE, "_search_index.db")


def file_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def sources_mtime(project_name, project_path=None):
    """Get the newest modification time among all source files for a project."""
    proj_dir = project_path or os.path.join(BASE, project_name)
    sources = [
        os.path.join(proj_dir, "_node_data.json"),
        os.path.join(proj_dir, "nodes.json"),
        os.path.join(proj_dir, "_all_workflows.json"),
        os.path.join(proj_dir, "business-flow-manifest.json"),
        os.path.join(proj_dir, "project_context.json"),
        os.path.join(proj_dir, "aliases.json"),
    ]
    return max(file_mtime(p) for p in sources)


def node_sources_mtime(project_name, project_path=None):
    """Newest raw input used to derive _node_data.json."""
    proj_dir = project_path or os.path.join(BASE, project_name)
    sources = [
        os.path.join(proj_dir, "nodes.json"),
        os.path.join(proj_dir, "_all_workflows.json"),
        os.path.join(proj_dir, "business-flow-manifest.json"),
        os.path.join(proj_dir, "project_context.json"),
    ]
    return max(file_mtime(path) for path in sources)


def check_node_data(project_name, project_path=None):
    proj_dir = project_path or os.path.join(BASE, project_name)
    node_data = os.path.join(proj_dir, "_node_data.json")
    return node_sources_mtime(project_name, proj_dir) > file_mtime(node_data)


def discover_projects(project_name=None):
    """Find projects with data from registry."""
    if not os.path.exists(REGISTRY):
        return []
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    projects = []
    for name, meta in reg.get("projects", {}).items():
        if project_name and name != project_name:
            continue
        if not meta.get("context_ready"):
            continue
        proj_path = meta.get("path", os.path.join(BASE, name))
        proj_path = os.path.expanduser(proj_path)
        if not os.path.isdir(proj_path):
            continue
        projects.append((name, proj_path))
    return projects


def check_index(projects):
    """Check per-project source mtime and completeness in the shared index."""
    if file_mtime(INDEX_DB) == 0:
        return [p[0] for p in projects]  # no index exists

    stale = []
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(projects)")
        }
        if "source_mtime" not in columns:
            conn.close()
            return [p[0] for p in projects]
        for proj_name, proj_path in projects:
            row = conn.execute(
                "SELECT source_mtime FROM projects WHERE name=?",
                (proj_name,),
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) FROM search_fts WHERE project=?",
                (proj_name,),
            ).fetchone()[0]
            if (
                row is None
                or sources_mtime(proj_name, proj_path) > float(row[0] or 0)
                or count == 0
            ):
                stale.append(proj_name)
        conn.close()
    except Exception:
        return [p[0] for p in projects]

    return stale


def check_graph(project_name, project_path=None):
    """Check if dependency graph needs rebuild."""
    proj_dir = project_path or os.path.join(BASE, project_name)
    graph_path = os.path.join(proj_dir, "dependency_graph.json")
    graph_mtime = file_mtime(graph_path)
    src_time = sources_mtime(project_name, proj_dir)
    return src_time > graph_mtime


def rebuild_index(stale_projects=None, all_projects=False):
    """Rebuild search index with build_search_index.py."""
    script = os.path.join(SKILL_DIR, "build_search_index.py")
    if all_projects:
        label = "all projects"
        print(f"[sync] Rebuilding search index ({label})...")
        subprocess.run([sys.executable, script, "--all"], check=True)
    elif stale_projects:
        print(f"[sync] Rebuilding search index (stale: {stale_projects})...")
        for project_name in stale_projects:
            subprocess.run([sys.executable, script, project_name], check=True)
    else:
        print("[sync] Search index is up to date.")


def rebuild_graph(project_name, project_path=None):
    """Rebuild dependency graph with rebuild_graph.py."""
    script = os.path.join(SKILL_DIR, "rebuild_graph.py")
    print(f"[sync] Rebuilding dependency graph for: {project_name}")
    command = [sys.executable, script, project_name]
    if project_path:
        command.extend(["--project-path", project_path])
    subprocess.run(command, check=True)


def rebuild_node_data(stale_projects, project_paths=None):
    """Force-regenerate only stale node-data projects."""
    script = os.path.join(SKILL_DIR, "generate_node_data.py")
    for project_name in stale_projects:
        command = [sys.executable, script, project_name, "--force"]
        project_path = (project_paths or {}).get(project_name)
        if project_path:
            command.extend(["--project-path", project_path])
        subprocess.run(command, check=True)


def main():
    check_only = "--check-only" in sys.argv
    project_name = None
    for a in sys.argv[1:]:
        if not a.startswith("--"):
            project_name = a
            break

    projects = discover_projects(project_name)
    if not projects:
        print("[sync] No projects found.")
        return

    # ── Step 1: Check derived node data ──
    stale_node_data = [
        proj_name
        for proj_name, proj_path in projects
        if check_node_data(proj_name, proj_path)
    ]
    # Index/graph freshness is recomputed after node-data generation.
    stale_index = check_index(projects)
    stale_graphs = []
    for proj_name, proj_path in projects:
        if check_graph(proj_name, proj_path):
            stale_graphs.append(proj_name)

    if check_only:
        print("[sync] --check-only mode")
        print(f"  Node data stale projects: {stale_node_data or 'none'}")
        print(f"  Index stale projects: {stale_index or 'none'}")
        print(f"  Graph stale projects: {stale_graphs or 'none'}")
        return

    # ── Step 2: Generate only stale _node_data.json ──
    project_paths = dict(projects)
    rebuild_node_data(stale_node_data, project_paths)

    stale_index = check_index(projects)
    stale_graphs = [
        proj_name
        for proj_name, proj_path in projects
        if check_graph(proj_name, proj_path)
    ]

    # ── Step 3: Rebuild what's stale ──
    rebuilt_any = False

    if stale_index:
        rebuild_index(stale_projects=stale_index)
        rebuilt_any = True
    else:
        print("[sync] Search index is up to date.")

    for proj_name in stale_graphs:
        rebuild_graph(proj_name, project_paths.get(proj_name))
        rebuilt_any = True
    if not stale_graphs:
        print(f"[sync] Dependency graphs are up to date.")

    if rebuilt_any:
        # Regenerate only topology documents whose graph changed.
        topo_script = os.path.join(SKILL_DIR, "generate_topology.py")
        for proj_name in stale_graphs:
            subprocess.run(
                [sys.executable, topo_script, proj_name],
                check=False,
            )

        print()
        print("[sync] ✓ Derived data synced.")
        print("[sync] → search_index.db + dependency_graph.json + topology-<project>.md are fresh.")
    else:
        print("[sync] ✓ Everything is up to date. No rebuild needed.")


if __name__ == "__main__":
    main()
