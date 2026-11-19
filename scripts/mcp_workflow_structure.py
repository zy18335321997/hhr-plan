#!/usr/bin/env python3
"""Fetch workflow node config through MCP get_workflow_structure.

get_workflow_details only returns trigger-process metadata. Node structure and
per-node config come from get_workflow_structure. approval_block and
sub_process do not inline inner nodes; the inner process id is
config.process.processId and is fetched with the same tool.
"""

import json
import os
import re

STRUCTURE_TOOL = "get_workflow_structure"
NESTED_NODE_TYPES = {"approval_block", "sub_process"}
SNAPSHOT_NAME = "_workflow_structures.json"
_ARGUMENT_CANDIDATES = ("workflow_id", "process_id", "workflowId", "processId")


def select_structure_tool(tools):
    """Return the structure tool from tools/list, preferring the official name."""
    if not isinstance(tools, list):
        return None
    exact = []
    equivalent = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = (tool.get("name") or "").strip()
        folded = name.lower().replace("-", "_")
        if name == STRUCTURE_TOOL or folded == STRUCTURE_TOOL:
            exact.append(tool)
        elif folded.endswith("workflow_structure") or folded == "getworkflowstructure":
            equivalent.append(tool)
    if exact:
        return exact[0]
    return equivalent[0] if equivalent else None


def _input_schema(tool):
    if not isinstance(tool, dict):
        return {}
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return schema if isinstance(schema, dict) else {}


def argument_name_for_process(tool):
    """Pick workflow_id or process_id from the tool's actual input schema."""
    schema = _input_schema(tool)
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [name for name in schema.get("required") or [] if isinstance(name, str)]
    for name in required:
        if name in properties and name in _ARGUMENT_CANDIDATES:
            return name
    for name in _ARGUMENT_CANDIDATES:
        if name in properties:
            return name
    return "workflow_id"


def public_error(detail) -> str:
    """Drop URLs and credential-shaped query values before anything is saved."""
    text = re.sub(r"https?://\S+", "<url>", str(detail or ""))
    text = re.sub(
        r"(?i)(appkey|hap-sign|sign|token|authorization)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    return text[:180]


def structure_payload(result):
    """Unwrap a tool result to the official structure object, or None."""
    if not isinstance(result, dict):
        return None
    if result.get("success") is False:
        return None
    if result.get("error") and "data" not in result and "processId" not in result and "nodes" not in result:
        return None
    data = result.get("data", result)
    if not isinstance(data, dict):
        return None
    if "processId" in data or "nodes" in data or "trigger" in data:
        return data
    return None


def iter_structure_nodes(structure):
    """Yield the trigger and each business node. Inner processes are not inlined."""
    if not isinstance(structure, dict):
        return
    trigger = structure.get("trigger")
    if isinstance(trigger, dict):
        yield trigger
    nodes = structure.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                yield node


def nested_process_id(node) -> str:
    """Inner process id for approval_block / sub_process. Other nodes have none."""
    if not isinstance(node, dict):
        return ""
    if (node.get("nodeType") or "") not in NESTED_NODE_TYPES:
        return ""
    config = node.get("config")
    if not isinstance(config, dict):
        return ""
    process = config.get("process")
    if not isinstance(process, dict):
        return ""
    return str(process.get("processId") or "").strip()


def config_missing(node) -> bool:
    config = node.get("config") if isinstance(node, dict) else None
    return not isinstance(config, dict) or len(config) == 0


def _gap(process_id, reason, **extra):
    item = {"process_id": process_id, "reason": reason}
    item.update(extra)
    if "detail" in item:
        item["detail"] = public_error(item["detail"])
    return item


def _walk(process_id, tool_name, argument, call_tool, seen, processes, gaps, is_root):
    if not process_id or process_id in seen:
        return
    seen.add(process_id)
    try:
        raw = call_tool(tool_name, {argument: process_id})
    except Exception as exc:
        gaps.append(_gap(
            process_id,
            "fetch_failed" if is_root else "nested_fetch_failed",
            detail=exc,
        ))
        return
    structure = structure_payload(raw)
    if structure is None:
        detail = ""
        if isinstance(raw, dict):
            detail = raw.get("error") or raw.get("error_msg") or ""
        gaps.append(_gap(
            process_id,
            "fetch_failed" if is_root else "nested_fetch_failed",
            detail=detail,
        ))
        return
    processes[process_id] = structure
    for node in iter_structure_nodes(structure):
        node_id = node.get("nodeId") or ""
        node_type = node.get("nodeType") or node.get("triggerType") or ""
        if config_missing(node):
            gaps.append(_gap(process_id, "empty_config", node_id=node_id, node_type=node_type))
        if (node.get("nodeType") or "") in NESTED_NODE_TYPES:
            nested = nested_process_id(node)
            if not nested:
                gaps.append(_gap(
                    process_id,
                    "missing_nested_process_id",
                    node_id=node_id,
                    node_type=node.get("nodeType") or "",
                ))
            else:
                _walk(nested, tool_name, argument, call_tool, seen, processes, gaps, False)


def extract_structures(process_ids, tools, call_tool) -> dict:
    """Fetch each root process and every nested approval_block / sub_process."""
    tool = select_structure_tool(tools)
    if tool is None:
        return {
            "source": "mcp_get_workflow_structure",
            "tool": None,
            "argument": None,
            "incomplete": True,
            "gaps": [{"reason": "structure_tool_unavailable"}],
            "processes": {},
        }
    argument = argument_name_for_process(tool)
    tool_name = tool.get("name") or STRUCTURE_TOOL
    seen, processes, gaps = set(), {}, []
    for process_id in process_ids or []:
        _walk(str(process_id or "").strip(), tool_name, argument, call_tool, seen, processes, gaps, True)
    return {
        "source": "mcp_get_workflow_structure",
        "tool": tool_name,
        "argument": argument,
        "incomplete": bool(gaps),
        "gaps": gaps,
        "processes": processes,
    }


def _incomplete_flags(snapshot) -> dict:
    processes = snapshot.get("processes") or {}
    gaps = snapshot.get("gaps") or []
    if any(gap.get("reason") == "structure_tool_unavailable" for gap in gaps):
        return {}
    direct = {gap.get("process_id") for gap in gaps if gap.get("process_id")}
    memo = {}

    def visit(process_id, stack):
        if process_id in memo:
            return memo[process_id]
        if process_id in stack or process_id not in processes:
            memo[process_id] = True
            return True
        flag = process_id in direct
        for node in iter_structure_nodes(processes[process_id]):
            nested = nested_process_id(node)
            if nested and visit(nested, stack | {process_id}):
                flag = True
        memo[process_id] = flag
        return flag

    return {process_id: visit(process_id, set()) for process_id in processes}


def incomplete_process_ids(snapshot, requested) -> set:
    """Process ids that still need the cookie fallback."""
    gaps = snapshot.get("gaps") or []
    requested = {str(pid) for pid in requested or [] if pid}
    if any(gap.get("reason") == "structure_tool_unavailable" for gap in gaps):
        return set(requested)
    flags = _incomplete_flags(snapshot)
    missing = {pid for pid in requested if pid not in (snapshot.get("processes") or {})}
    nested_failed = {
        gap.get("process_id")
        for gap in gaps
        if gap.get("process_id") and gap.get("reason") in {"fetch_failed", "nested_fetch_failed"}
    }
    flagged = {pid for pid, incomplete in flags.items() if incomplete}
    return missing | nested_failed | flagged


def node_data_from_snapshot(snapshot, wf_list) -> dict:
    """Manifest rows. Reads/writes stay empty until a cookie extract fills them."""
    meta = {}
    for workflow in wf_list or []:
        if not isinstance(workflow, dict):
            continue
        pid = workflow.get("id") or workflow.get("processId") or ""
        if pid:
            meta[str(pid)] = workflow
    flags = _incomplete_flags(snapshot)
    processes = snapshot.get("processes") or {}
    pids = set(processes) | set(flags) | {
        gap.get("process_id") for gap in snapshot.get("gaps") or [] if gap.get("process_id")
    }
    rows = {}
    for pid in pids:
        structure = processes.get(pid) or {}
        nodes = list(iter_structure_nodes(structure))
        workflow = meta.get(pid, {})
        trigger = structure.get("trigger") if isinstance(structure.get("trigger"), dict) else {}
        rows[pid] = {
            "name": structure.get("name") or workflow.get("name") or "",
            "worksheet": workflow.get("worksheet") or workflow.get("appName") or "",
            "trigger": trigger.get("triggerType") or trigger.get("name") or workflow.get("trigger") or "",
            "trigger_type_id": -1,
            "node_count": len(nodes),
            "reads": [],
            "writes": [],
            "crud_field_mappings": [],
            "query_empty_actions": [],
            "approval_count": sum(1 for node in nodes if node.get("nodeType") == "approval_block"),
            "incomplete": flags.get(pid, pid not in processes),
            "source": "mcp_get_workflow_structure",
        }
    return rows


def nodes_document(snapshot) -> dict:
    """nodes.json shape: one map per process, metadata keys prefixed with '_'."""
    document = {}
    for pid, structure in (snapshot.get("processes") or {}).items():
        entry = {
            "_name": structure.get("name") or "",
            "_source": "mcp_get_workflow_structure",
            "_process_id": structure.get("processId") or pid,
        }
        for node in iter_structure_nodes(structure):
            node_id = node.get("nodeId")
            if node_id:
                entry[node_id] = node
        document[pid] = entry
    return document


def configs_document(snapshot) -> dict:
    """_node_configs.json rows. The whole node config is kept, not only field lists."""
    document = {}
    for pid, structure in (snapshot.get("processes") or {}).items():
        rows = []
        for node in iter_structure_nodes(structure):
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            node_type = node.get("nodeType") or node.get("triggerType") or ""
            rows.append({
                "pid": pid,
                "wf_name": structure.get("name") or "",
                "node_id": node.get("nodeId") or "",
                "node_name": node.get("name") or "",
                "node_type": node_type,
                "type_label": node_type,
                "config": config,
                "incomplete": not config,
                "source": "mcp_get_workflow_structure",
            })
        document[pid] = rows
    return document


def persist(project_dir, snapshot) -> None:
    """Write the structure snapshot plus nodes.json and _node_configs.json."""
    os.makedirs(project_dir, exist_ok=True)
    with open(os.path.join(project_dir, SNAPSHOT_NAME), "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(project_dir, "nodes.json"), "w", encoding="utf-8") as handle:
        json.dump(nodes_document(snapshot), handle, ensure_ascii=False, indent=2)
    with open(os.path.join(project_dir, "_node_configs.json"), "w", encoding="utf-8") as handle:
        json.dump(configs_document(snapshot), handle, ensure_ascii=False, indent=2)
