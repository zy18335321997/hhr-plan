#!/usr/bin/env python3
"""Sheet → Workflows 反向索引查询（含 search.py 交叉校验）

Usage:
    python3 sheet_workflows.py <项目名> <表名>
    python3 sheet_workflows.py <项目名> --list
    python3 sheet_workflows.py <项目名> --rebuild   # 重建索引（含校验）
"""

import json
import subprocess
import sys
from pathlib import Path

DATA = Path.home() / "Documents" / "workflow-output"
SKILL = Path.home() / ".claude" / "skills" / "hhr-plan" / "scripts"

_TRIGGER_MAP = {0: "工作表事件", 1: "自定义动作", 2: "定时触发",
                3: "审批流程", 4: "子流程", 5: "封装业务流程"}
_APP_TYPE_MAP = {8: "自定义动作", 2: "工作表事件", 3: "审批流程", 5: "子流程", 6: "封装业务流程"}


def load_index(project: str) -> dict:
    path = DATA / project / "sheet_workflows.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _find_trigger_node(data: list) -> dict | None:
    """Find the actual trigger node. Priority: typeId==0 → any with appName → first."""
    if not data:
        return None
    # 1) Scan ALL nodes for typeId==0 (true trigger, may be at end for subprocesses)
    for n in data:
        if n.get("typeId") == 0:
            return n
    # 2) First node with appName (CRUD/subprocess with context)
    for n in data:
        if n.get("appName"):
            return n
    # 3) Last resort
    return data[0]

def _extract_trigger(data: list) -> tuple[str, str]:
    """Return (trigger_sheet, trigger_type) from T0 node. Handles both formats."""
    if not data:
        return "", ""
    t0 = _find_trigger_node(data)
    if not t0:
        return "未分类", ""
    # Browser format
    s = t0.get("structured", {})
    a = t0.get("_api_node", {})
    sheet = s.get("worksheet") or a.get("appName") or ""
    ttype = s.get("trigger") or s.get("buttonName") or ""
    if not ttype:
        ttype = _TRIGGER_MAP.get(a.get("typeId"), "")
    # CLI API flat format
    if not sheet:
        sheet = t0.get("appName", "")
    if not ttype or ttype in ("按钮触发", "工作表事件触发", "触发"):
        app_type = t0.get("appType") if "appType" in t0 else t0.get("typeId")
        ttype = _APP_TYPE_MAP.get(app_type, _TRIGGER_MAP.get(app_type, ttype))
    # Subprocesses with no appName → group under "子流程"
    if not sheet:
        app_type = t0.get("appType") if "appType" in t0 else t0.get("typeId")
        is_sub = app_type in (5, 13)  # 子流程 / 封装
        sheet = "子流程" if is_sub else "未分类"
    return sheet, ttype


def _build_truth_map(project: str) -> dict[str, dict]:
    """Build {name: {pid}} from MCP-built name_index.json."""
    base = DATA / project
    ni_path = base / "name_index.json"
    truth = {}
    if ni_path.exists():
        try:
            name_index = json.loads(ni_path.read_text())
            for name, pid in name_index.items():
                truth[name] = {"pid": pid, "node_count": 0}  # node_count not available from name index alone
        except (json.JSONDecodeError, OSError):
            pass

    # Augment with search.py for node counts where available
    for ch in "新增 发布 修改 删除 审批 采购 任务 出库 入库 合同".split():
        try:
            r = subprocess.run(
                ["python3", str(SKILL / "search.py"), ch, "--type", "workflow",
                 "-p", project, "-f", "json"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                continue
            for item in json.loads(r.stdout).get("results", []):
                name = item.get("entity_name", "")
                nc = item.get("extra", {}).get("node_count", 0)
                trigger = item.get("extra", {}).get("trigger", "")
                if name in truth and nc:
                    truth[name]["node_count"] = nc
                    truth[name]["trigger_type"] = trigger
        except Exception:
            continue

    return truth


def rebuild_from_cache(project: str) -> dict:
    """Rebuild index with cross-validation against search.py."""
    base = DATA / project
    truth = _build_truth_map(project)
    print(f"[truth] {len(truth)} workflows from search.py", file=sys.stderr)

    index = {}
    validated = 0
    mismatches = 0
    unverified = 0

    for cache_file in base.glob("**/node_configs.json"):
        try:
            data = json.loads(cache_file.read_text())
            if not isinstance(data, list) or len(data) == 0:
                continue
        except (json.JSONDecodeError, OSError):
            continue

        dir_name = cache_file.parent.name
        trigger_sheet, trigger_type_cache = _extract_trigger(data)
        cache_node_count = len(data)
        t0_api = data[0].get("_api_node", {})
        cache_node_id = t0_api.get("id", "") or dir_name

        # Name from meta or directory
        meta_path = cache_file.parent / "workflow_meta.json"
        wf_name = ""
        if meta_path.exists():
            try:
                wf_name = json.loads(meta_path.read_text()).get("name", "")
            except Exception:
                pass
        if not wf_name:
            wf_name = dir_name

        # ── Cross-validate against search.py truth ──
        truth_entry = truth.get(wf_name)
        if truth_entry:
            truth_nc = truth_entry.get("node_count", 0)
            if truth_nc > 0 and abs(cache_node_count - truth_nc) > 2:
                # Node count mismatch: cache data is corrupted, but trigger_sheet is reliable
                mismatches += 1
            else:
                validated += 1
            pid = truth_entry["pid"]
            trigger_type = truth_entry.get("trigger_type") or trigger_type_cache
        else:
            pid = cache_node_id
            trigger_type = trigger_type_cache
            unverified += 1

        # ── Write to index ──
        if trigger_sheet not in index:
            index[trigger_sheet] = []
        existing_pids = [e.get("pid") for e in index[trigger_sheet]]
        if pid not in existing_pids:
            index[trigger_sheet].append({
                "pid": pid,
                "name": wf_name,
                "trigger_type": trigger_type,
                "node_count": cache_node_count,
                "verified": truth_entry is not None,
                "cached_at": "",
            })

    out_path = DATA / project / "sheet_workflows.json"
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))

    total = sum(len(v) for v in index.values())
    print(f"[rebuild] {total} workflows ({validated} verified, {unverified} unverified, {mismatches} mismatches skipped) across {len(index)} sheets", file=sys.stderr)
    return index


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 sheet_workflows.py <项目名> <表名>", file=sys.stderr)
        print("       python3 sheet_workflows.py <项目名> --list", file=sys.stderr)
        print("       python3 sheet_workflows.py <项目名> --rebuild", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    cmd = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "--rebuild":
        index = rebuild_from_cache(project)
        print(json.dumps(index, ensure_ascii=False, indent=2))
        return

    if cmd == "--list":
        index = load_index(project)
        if not index:
            print(f"No index for {project}. Run --rebuild first.", file=sys.stderr)
            sys.exit(1)
        for sheet, wfs in sorted(index.items()):
            print(f"{sheet}: {len(wfs)} workflows")
        return

    sheet_name = cmd
    index = load_index(project)
    if not index:
        print("No index. Rebuilding...", file=sys.stderr)
        index = rebuild_from_cache(project)

    wfs = index.get(sheet_name, [])
    if not wfs:
        matches = [(k, v) for k, v in index.items() if sheet_name in k]
        if matches:
            for k, v in matches[:5]:
                print(f"  {k}: {len(v)} workflows", file=sys.stderr)
                for wf in v:
                    vflag = "✓" if wf.get("verified") else "?"
                    print(f"    [{wf['trigger_type']}] {vflag} {wf['name'][:50]} ({wf['pid'][-12:]})")
        else:
            print(f"No workflows for '{sheet_name}'", file=sys.stderr)
        return

    print(json.dumps({
        "sheet": sheet_name,
        "workflow_count": len(wfs),
        "workflows": wfs
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
