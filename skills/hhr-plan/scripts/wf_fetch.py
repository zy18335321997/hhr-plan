#!/usr/bin/env python3
"""工作流节点获取（本地优先 + 自动缓存 + 名称/PID/触发表绑定）

Usage:
    python3 wf_fetch.py <项目名> <PID或工作流名>
    python3 wf_fetch.py <项目名> <PID> --force-remote    # 强制远程刷新
    python3 wf_fetch.py <项目名> --rebuild-names          # 从 MCP 补全所有缓存的名称

缓存时自动: ①节点 ②meta(PID+名称+触发表) ③sheet_workflows.json ④name_index.json
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HAP = Path.home() / ".claude" / "mcp-servers" / "hap-bridge" / "cli.py"
DATA = Path.home() / "Documents" / "workflow-output"
SKILL = Path.home() / ".claude" / "skills" / "hhr-plan" / "scripts"


_TRIGGER_MAP = {0: "工作表事件", 1: "自定义动作", 2: "定时触发", 3: "审批流程", 4: "子流程", 5: "封装业务流程"}
_APP_TYPE_MAP = {8: "自定义动作", 2: "工作表事件", 3: "审批流程", 5: "子流程", 6: "封装业务流程"}

def _find_trigger_node(nodes: list[dict]) -> dict | None:
    """Find the actual trigger node. Priority: typeId==0 → any with appName → first."""
    if not nodes:
        return None
    # 1) Scan ALL for typeId==0 (may be at end for subprocesses)
    for n in nodes:
        if n.get("typeId") == 0:
            return n
    # 2) First with appName
    for n in nodes:
        if n.get("appName"):
            return n
    return nodes[0] if nodes else None

def _extract_trigger(nodes: list[dict]) -> dict:
    if not nodes:
        return {}
    t0 = _find_trigger_node(nodes)
    if not t0:
        return {"trigger_sheet": "", "trigger_type": "", "button_name": ""}

    # Try Browser extraction format first (structured + _api_node)
    s = t0.get("structured", {})
    a = t0.get("_api_node", {})
    trigger_sheet = s.get("worksheet") or a.get("appName") or ""
    trigger_type = s.get("trigger") or s.get("buttonName") or ""

    # Fallback: CLI API flat format (fields directly on node dict)
    if not trigger_sheet:
        trigger_sheet = t0.get("appName", "")
    if not trigger_type:
        trigger_type = t0.get("triggerName", "")
    if not trigger_type:
        trigger_type = t0.get("name", "")
    # Infer type from API appType/typeId
    if not trigger_type or trigger_type in ("按钮触发", "工作表事件触发", "触发"):
        app_type = t0.get("appType") if "appType" in t0 else t0.get("typeId")
        trigger_type = _APP_TYPE_MAP.get(app_type, _TRIGGER_MAP.get(app_type, trigger_type))

    return {
        "trigger_sheet": trigger_sheet,
        "trigger_type": trigger_type,
        "button_name": s.get("buttonName", "") or t0.get("triggerName", ""),
    }


def _mcp_call(method: str, params: dict) -> dict | None:
    try:
        r = subprocess.run(["python3", str(HAP), "call", method, json.dumps(params)],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def fetch_workflow_name_by_pid(pid: str) -> str:
    """Get name via MCP get_workflow_details (needs real workflow PID)."""
    data = _mcp_call("get_workflow_details", {"process_id": pid})
    if data:
        inner = data.get("data", data)
        name = inner.get("name", "")
        if name:
            return name
    return ""


def fetch_all_workflow_names() -> dict[str, str]:
    """Get ALL workflow PID→name mappings via MCP get_workflow_list."""
    data = _mcp_call("get_workflow_list", {})
    if not data:
        return {}
    inner = data.get("data", data)
    result = {}
    items = inner if isinstance(inner, list) else inner.get("workflows", inner.get("items", []))
    for item in items:
        pid = item.get("id", item.get("processId", item.get("process_id", "")))
        name = item.get("name", "")
        if pid and name:
            result[pid] = name
    return result


def _update_name_index(project: str, pid: str, name: str):
    if not name:
        return
    path = DATA / project / "name_index.json"
    index = {}
    if path.exists():
        try:
            index = json.loads(path.read_text())
        except Exception:
            pass
    index[name] = pid
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2))


def _update_sheet_index(project: str, pid: str, meta: dict):
    sheet = meta.get("trigger_sheet", "")
    if not sheet or sheet == "未分类":
        return
    ipath = DATA / project / "sheet_workflows.json"
    index = {}
    if ipath.exists():
        try:
            index = json.loads(ipath.read_text())
        except Exception:
            pass
    if sheet not in index:
        index[sheet] = []
    existing = [e for e in index[sheet] if e.get("pid") != pid]
    existing.append({
        "pid": pid, "name": meta.get("name", ""),
        "trigger_type": meta.get("trigger_type", ""),
        "node_count": meta.get("node_count", 0),
        "cached_at": meta.get("cached_at", ""),
    })
    index[sheet] = existing
    ipath.write_text(json.dumps(index, ensure_ascii=False, indent=2))


def find_local_cache(project: str, pid_or_name: str) -> Path | None:
    base = DATA / project
    if not base.exists():
        return None
    # 1) name index
    ni = base / "name_index.json"
    if ni.exists():
        try:
            idx = json.loads(ni.read_text())
            pid = idx.get(pid_or_name)
            if pid:
                c = _find_pid_cache(base, pid)
                if c: return c
        except Exception:
            pass
    # 2) direct PID
    return _find_pid_cache(base, pid_or_name)


def _find_pid_cache(base: Path, pid: str) -> Path | None:
    for p in [f"**/{pid}/node_configs.json", f"*{pid}*/node_configs.json"]:
        for h in sorted(base.glob(p)):
            try:
                d = json.loads(h.read_text())
                if isinstance(d, list) and len(d) > 0:
                    return h
            except Exception:
                continue
    return None


def _is_hex_pid(s: str) -> bool:
    return len(s) >= 24 and all(c in "0123456789abcdef" for c in s.lower())


def save_cache(project: str, pid: str, nodes: list[dict], wf_name: str = "") -> tuple[Path, dict]:
    d = DATA / project / pid
    d.mkdir(parents=True, exist_ok=True)
    cf = d / "node_configs.json"
    cf.write_text(json.dumps(nodes, ensure_ascii=False, indent=2))
    trigger = _extract_trigger(nodes)
    if not wf_name:
        wf_name = fetch_workflow_name_by_pid(pid)
    meta = {
        "pid": pid, "name": wf_name, "node_count": len(nodes),
        "trigger_sheet": trigger.get("trigger_sheet", ""),
        "trigger_type": trigger.get("trigger_type", ""),
        "cached_at": date.today().isoformat(),
    }
    (d / "workflow_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    _update_sheet_index(project, pid, meta)
    _update_name_index(project, pid, wf_name)
    print(f"[name] {wf_name or '(unknown)'}", file=sys.stderr)
    return cf, meta


def rebuild_names(project: str):
    """Bulk Name Recovery:
    1. Call MCP get_workflow_list ONCE → name→PID map
    2. For each cached node_configs, extract T0 appName as the workflow name
    3. Match against MCP map by name → get real PID → write meta + indexes
    """
    base = DATA / project
    print("[rebuild-names] fetching all workflow names from MCP...", file=sys.stderr)
    pid_to_name = fetch_all_workflow_names()
    name_to_pid = {v: k for k, v in pid_to_name.items()}
    print(f"[rebuild-names] got {len(pid_to_name)} workflows from MCP", file=sys.stderr)

    count = 0
    for cf in base.glob("**/node_configs.json"):
        try:
            data = json.loads(cf.read_text())
            if not isinstance(data, list) or len(data) == 0:
                continue
        except Exception:
            continue

        dir_name = cf.parent.name
        meta_path = cf.parent / "workflow_meta.json"

        # Determine PID
        if _is_hex_pid(dir_name):
            pid = dir_name
            # Skip if already has name
            if meta_path.exists():
                try:
                    if json.loads(meta_path.read_text()).get("name"):
                        continue
                except Exception:
                    pass
            name = pid_to_name.get(pid, "")
        else:
            # Chinese-named directory: match by directory name in MCP map
            name = dir_name
            pid = name_to_pid.get(name, "")
            if not pid:
                continue

        if not pid or not name:
            continue

        trigger = _extract_trigger(data)
        meta = {
            "pid": pid, "name": name, "node_count": len(data),
            "trigger_sheet": trigger.get("trigger_sheet", ""),
            "trigger_type": trigger.get("trigger_type", ""),
            "cached_at": date.today().isoformat(),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        _update_name_index(project, pid, name)
        _update_sheet_index(project, pid, meta)
        count += 1
        if count % 20 == 0:
            print(f"  ... {count} names filled", file=sys.stderr)

    print(f"[rebuild-names] {count} names filled", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 wf_fetch.py <项目名> <PID或工作流名> [--force-remote]", file=sys.stderr)
        print("       python3 wf_fetch.py <项目名> --rebuild-names", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]

    if len(sys.argv) > 2 and sys.argv[2] == "--rebuild-names":
        rebuild_names(project)
        return

    if len(sys.argv) < 3:
        sys.exit(1)

    pid_or_name = sys.argv[2]
    force = "--force-remote" in sys.argv

    if not force:
        cached = find_local_cache(project, pid_or_name)
        if cached:
            data = json.loads(cached.read_text())
            trigger = _extract_trigger(data)
            mp = cached.parent / "workflow_meta.json"
            wf_name = ""
            if mp.exists():
                try:
                    wf_name = json.loads(mp.read_text()).get("name", "")
                except Exception:
                    pass
            print(json.dumps({
                "source": "local_cache", "path": str(cached),
                "node_count": len(data), "wf_name": wf_name,
                "trigger": trigger, "nodes": data
            }, ensure_ascii=False, indent=2))
            print(f"[local cache] {wf_name or pid_or_name} ({trigger.get('trigger_sheet','?')} ← {len(data)} nodes)", file=sys.stderr)
            return

    nodes = None
    try:
        r = subprocess.run(["python3", str(HAP), "wf-nodes", "--raw", pid_or_name],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            raw = json.loads(r.stdout)
            # CLI --raw returns {status, data: {flowNodeMap: {...}}}
            if isinstance(raw, dict):
                inner = raw.get("data", raw)
                if isinstance(inner, dict) and "flowNodeMap" in inner:
                    fm = inner["flowNodeMap"]
                    nodes = list(fm.values()) if isinstance(fm, dict) else fm
                elif isinstance(inner, list):
                    nodes = inner
            elif isinstance(raw, list):
                nodes = raw
    except Exception:
        pass

    if nodes:
        cp, meta = save_cache(project, pid_or_name, nodes)
        trigger = _extract_trigger(nodes)
        print(json.dumps({
            "source": "cli_wf-nodes", "cached_to": str(cp),
            "node_count": len(nodes), "wf_name": meta.get("name",""),
            "trigger": trigger, "nodes": nodes
        }, ensure_ascii=False, indent=2))
        print(f"[cli] {meta.get('name','?')} ({trigger.get('trigger_sheet','?')} ← {len(nodes)} nodes)", file=sys.stderr)
        return

    mcp_data = _mcp_call("get_workflow_details", {"process_id": pid_or_name})
    if mcp_data:
        print(json.dumps({"source": "mcp_fallback", "node_count": None,
                          "data": mcp_data}, ensure_ascii=False, indent=2))
        print("[mcp] basic info only", file=sys.stderr)
        return

    print(json.dumps({"source": "none", "error": f"No data for {pid_or_name}"}, ensure_ascii=False, indent=2))
    print(f"[none] No data for {pid_or_name}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
