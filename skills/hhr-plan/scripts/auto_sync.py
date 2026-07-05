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
    - hhr-plan skill startup (before loading context)
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


def sources_mtime(project_name):
    """Get the newest modification time among all source files for a project."""
    proj_dir = os.path.join(BASE, project_name)
    sources = [
        os.path.join(proj_dir, "_node_data.json"),
        os.path.join(proj_dir, "business-flow-manifest.json"),
        os.path.join(proj_dir, "project_context.json"),
        os.path.join(proj_dir, "aliases.json"),
    ]
    return max(file_mtime(p) for p in sources)


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
    """Check if search index needs rebuild (freshness + completeness). Returns list of stale project names."""
    index_mtime = file_mtime(INDEX_DB)
    if index_mtime == 0:
        return [p[0] for p in projects]  # no index exists

    stale = []
    for proj_name, _ in projects:
        src_time = sources_mtime(proj_name)
        if src_time > index_mtime:
            stale.append(proj_name)

    # Completeness check: verify each project has entries in the index
    if not stale:
        import sqlite3
        try:
            conn = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
            for proj_name, _ in projects:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM search_fts WHERE project=?", (proj_name,)
                ).fetchone()[0]
                if cnt == 0:
                    stale.append(proj_name)
            conn.close()
        except Exception:
            pass  # if DB is unreadable, fall through to stale list from mtime check

    return stale


def check_graph(project_name):
    """Check if dependency graph needs rebuild."""
    graph_path = os.path.join(BASE, project_name, "dependency_graph.json")
    graph_mtime = file_mtime(graph_path)
    src_time = sources_mtime(project_name)
    return src_time > graph_mtime


def rebuild_index(stale_projects=None, all_projects=False):
    """Rebuild search index with build_search_index.py."""
    script = os.path.join(SKILL_DIR, "build_search_index.py")
    if all_projects or stale_projects:
        label = "all projects" if all_projects else f"stale: {stale_projects}"
        print(f"[sync] Rebuilding search index ({label})...")
        subprocess.run([sys.executable, script, "--all"], check=True)
    else:
        print("[sync] Search index is up to date.")


def rebuild_graph(project_name):
    """Rebuild dependency graph with rebuild_graph.py."""
    script = os.path.join(SKILL_DIR, "rebuild_graph.py")
    print(f"[sync] Rebuilding dependency graph for: {project_name}")
    subprocess.run([sys.executable, script, project_name], check=True)


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

    # ── Step 1: Check index freshness ──
    stale_index = check_index(projects)
    stale_graphs = []
    for proj_name, _ in projects:
        if check_graph(proj_name):
            stale_graphs.append(proj_name)

    if check_only:
        print("[sync] --check-only mode")
        print(f"  Index stale projects: {stale_index or 'none'}")
        print(f"  Graph stale projects: {stale_graphs or 'none'}")
        return

    # ── Step 2: Ensure _node_data.json exists for all projects ──
    gen_script = os.path.join(SKILL_DIR, "generate_node_data.py")
    subprocess.run([sys.executable, gen_script, "--all"], check=False)

    # ── Step 3: Rebuild what's stale ──
    rebuilt_any = False

    if stale_index:
        rebuild_index(stale_projects=stale_index)
        rebuilt_any = True
    else:
        print("[sync] Search index is up to date.")

    for proj_name in stale_graphs:
        rebuild_graph(proj_name)
        rebuilt_any = True
    if not stale_graphs:
        print(f"[sync] Dependency graphs are up to date.")

    if rebuilt_any:
        # Regenerate global topology
        topo_script = os.path.join(SKILL_DIR, "generate_topology.py")
        subprocess.run([sys.executable, topo_script, "--all"], check=False)

        print()
        print("[sync] ✓ Derived data synced.")
        print("[sync] → search_index.db + dependency_graph.json + global-topology.md are fresh.")
    else:
        print("[sync] ✓ Everything is up to date. No rebuild needed.")


if __name__ == "__main__":
    main()
