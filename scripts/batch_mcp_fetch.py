#!/usr/bin/env python3
"""MCP 批量拉取所有工作流名称+基本信息 → 重建 name_index.json + sheet_workflows.json

Usage:
    python3 batch_mcp_fetch.py <项目名>
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HAP = Path.home() / ".claude" / "mcp-servers" / "hap-bridge" / "cli.py"
DATA = Path.home() / "Documents" / "workflow-output"


def get_all_pids(project: str) -> list[str]:
    """Get all workflow PIDs from business-flow-manifest.json."""
    manifest = DATA / project / "business-flow-manifest.json"
    if not manifest.exists():
        print(f"No manifest for {project}", file=sys.stderr)
        return []
    d = json.loads(manifest.read_text())
    pids = set()
    for tname, wfs in d.get("tables", {}).items():
        if isinstance(wfs, list):
            for wf in wfs:
                if isinstance(wf, dict):
                    pid = wf.get("pid", "") or wf.get("id", "")
                    if pid: pids.add(pid)
    return sorted(pids)


def mcp_get_details(pid: str) -> dict | None:
    """MCP get_workflow_details for a single PID."""
    try:
        r = subprocess.run(
            ["python3", str(HAP), "call", "get_workflow_details",
             json.dumps({"process_id": pid})],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            inner = data.get("data", data)
            if isinstance(inner, dict):
                return inner
    except Exception:
        pass
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 batch_mcp_fetch.py <项目名>", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    pids = get_all_pids(project)
    print(f"[batch] {len(pids)} PIDs from manifest", file=sys.stderr)

    name_index = {}
    sheet_index = {}
    success = 0
    failed = 0

    for i, pid in enumerate(pids):
        details = mcp_get_details(pid)
        if not details:
            failed += 1
            continue

        name = details.get("name", "")
        if not name:
            failed += 1
            continue

        success += 1
        name_index[name] = pid

        # Try to get trigger info from MCP (limited — no T0 node data)
        # inputParameters may hint at trigger sheet
        inputs = details.get("inputParameters", [])
        trigger_sheet = ""
        for inp in inputs:
            if isinstance(inp, dict) and inp.get("type") == "Relation":
                trigger_sheet = inp.get("name", "")
                break

        if not trigger_sheet:
            trigger_sheet = "未分类"

        if trigger_sheet not in sheet_index:
            sheet_index[trigger_sheet] = []
        existing = [e["pid"] for e in sheet_index[trigger_sheet]]
        if pid not in existing:
            sheet_index[trigger_sheet].append({
                "pid": pid,
                "name": name,
                "trigger_type": "",
                "node_count": 0,
                "verified": True,
                "source": "mcp",
                "cached_at": date.today().isoformat(),
            })

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(pids)}: {success} ok, {failed} fail", file=sys.stderr)

    # Save name_index.json
    ni_path = DATA / project / "name_index.json"
    existing_ni = {}
    if ni_path.exists():
        try:
            existing_ni = json.loads(ni_path.read_text())
        except Exception:
            pass
    existing_ni.update(name_index)
    ni_path.write_text(json.dumps(existing_ni, ensure_ascii=False, indent=2))
    print(f"[name_index] {len(existing_ni)} names → {ni_path}", file=sys.stderr)

    # Save sheet_workflows.json (MCP-derived, basic)
    sw_path = DATA / project / "sheet_workflows.json"
    sw_path.write_text(json.dumps(sheet_index, ensure_ascii=False, indent=2))
    print(f"[sheet_index] {len(sheet_index)} sheets → {sw_path}", file=sys.stderr)

    print(f"\nDone: {success} success, {failed} failed out of {len(pids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
