#!/usr/bin/env python3
"""CLI 批量拉取全量工作流节点数据 → 覆盖旧缓存 → 重建所有索引

Usage:
    python3 batch_cli_fetch.py <项目名>
"""

import json
import subprocess
import sys
from pathlib import Path

HAP = Path.home() / ".claude" / "mcp-servers" / "hap-bridge" / "cli.py"
DATA = Path.home() / "Documents" / "workflow-output"
SKILL = Path.home() / ".claude" / "skills" / "hhr-plan" / "scripts"


def get_all_pids(project: str) -> list[str]:
    manifest = DATA / project / "business-flow-manifest.json"
    if not manifest.exists():
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 batch_cli_fetch.py <项目名>", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    pids = get_all_pids(project)
    print(f"[batch] {len(pids)} workflows to fetch", file=sys.stderr)

    success = 0
    failed = 0

    for i, pid in enumerate(pids):
        try:
            r = subprocess.run(
                ["python3", str(SKILL / "wf_fetch.py"), project, pid, "--force-remote"],
                capture_output=True, text=True, timeout=40
            )
            if r.returncode == 0 and '"source": "cli_wf-nodes"' in r.stdout:
                success += 1
            else:
                failed += 1
        except subprocess.TimeoutExpired:
            failed += 1

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(pids)}: {success} ok, {failed} fail", file=sys.stderr)

    print(f"\n[batch] Done: {success} ok, {failed} fail", file=sys.stderr)

    # Rebuild sheet index from fresh caches
    print("[rebuild] Rebuilding sheet_workflows.json...", file=sys.stderr)
    subprocess.run(["python3", str(SKILL / "sheet_workflows.py"), project, "--rebuild"])


if __name__ == "__main__":
    main()
