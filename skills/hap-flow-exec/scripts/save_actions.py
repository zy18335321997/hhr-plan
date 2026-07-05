#!/usr/bin/env python3
"""
Parallel save for action nodes + query filters in an execution contract.

Reads a contract JSON and a batch-add alias→nodeId mapping, then:
  - Saves update_record / create_record / delete_record field configs (save_action_node)
  - Saves get_single / get_multiple filter configs (filters format, bug #036489)

Usage:
  python3 save_actions.py --contract execution_contract.json \\
      --batch-output '<batch-add JSON>'
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from hap_cli.core.session import Session
from hap_cli.core.flow_node import (
    save_action_node,
    save_search_node,
    save_get_more_record_node,
)

NODE_TYPE_ACTION = {
    "update_record": "2",
    "create_record": "1",
    "delete_record": "3",
}

# builder op → wire conditionId (pd-openweb CONDITION_TYPE enum.js)
OP_TO_COND: dict[str, str] = {
    "in": "1", "not_in": "2",
    "empty": "8", "not_empty": "3",
    "eq": "9", "ne": "10",
    "gt": "12", "gte": "14",
    "lt": "11", "lte": "13",
    "contains": "15", "not_contains": "16",
    "starts_with": "17", "ends_with": "18",
    "checked": "5", "unchecked": "6",
}

# Date/DateTime fields use date-specific operators in the workflow filter system —
# NOT the generic numeric 11/12/13/14. Ground truth: workflow enum.js
# CONDITION_TYPE (17=早于, 18=晚于, 40=晚于等于, 42=早于等于).
_DATE_FIELD_TYPES = {15, 16}
_DATE_OPERATOR_CONDITION_ID: dict[str, str] = {
    "lt": "17",   # 早于
    "lte": "42",  # 早于等于
    "gt": "18",   # 晚于
    "gte": "40",  # 晚于等于
}

# systemField values → 系统 node fieldId (workflow_node_dsl.py:2093)
_SYSTEM_FIELD_IDS = {
    "now": "nowTime", "current_time": "nowTime",
    "nowTime": "nowTime",
}

# Fixed system node ID for runtime-value comparisons
_SYSTEM_NODE_ID = "5d39140d381d42d20db0c4da"


def load_contract(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _normalize_fields(fields: list[dict]) -> list[dict]:
    out = []
    for f in (fields or []):
        out.append({
            "fieldId": f.get("fieldId") or f.get("controlId", ""),
            "type": f.get("type", 2),
            "fieldValue": f.get("value") or f.get("fieldValue", ""),
        })
    return out


def _build_filter_wire(filt: dict, alias_to_id: dict[str, str]) -> list[dict]:
    """Convert builder filter {logic, items} → wire filters format.

    Server bug #036489: flat operateCondition arrays are silently dropped.
    The web UI saves conditions as:
      filters: [{conditions: [[cond, ...]], spliceType: 2}]
    """
    items = filt.get("items", [])
    if not items:
        return []

    logic = filt.get("logic", "and")
    # "and" → spliceType 2 (all conditions in one group);
    # "or"  → each item is a separate group
    if logic == "and":
        groups = []
        for item in items:
            wire = _condition_to_wire(item, alias_to_id)
            if wire:
                groups.append(wire)
        return [{"conditions": [groups], "spliceType": 2}] if groups else []
    else:
        return [
            {"conditions": [[_condition_to_wire(item, alias_to_id)]], "spliceType": 2}
            for item in items
        ]


def _condition_to_wire(cond: dict, alias_to_id: dict[str, str]) -> dict | None:
    """Convert one builder Condition {left, op, right} → wire filter item.

    Uses date-specific conditionIds for Date/DateTime fields (17=早于/18=晚于/…)
    and resolves systemField/nowTime → the fixed 系统 node reference.
    """
    left = cond.get("left", {})
    op = cond.get("op", "eq")
    right = cond.get("right") or {}
    field_id = left.get("fieldId", "")
    filed_type_id = left.get("_filedTypeId", left.get("type", 0))
    node_id = alias_to_id.get(left.get("node", ""), "")

    # Date + comparison op → date-specific conditionId
    if filed_type_id in _DATE_FIELD_TYPES and op in _DATE_OPERATOR_CONDITION_ID:
        cond_id = _DATE_OPERATOR_CONDITION_ID[op]
    else:
        cond_id = OP_TO_COND.get(op, "9")

    # systemField/nowTime as the right-hand value → reference 系统 node
    if right.get("kind") == "systemField" and right.get("fieldId") in _SYSTEM_FIELD_IDS:
        sys_field = _SYSTEM_FIELD_IDS[right.get("fieldId", "nowTime")]
        return {
            "filedId": field_id,
            "nodeId": node_id,
            "filedTypeId": filed_type_id,
            "conditionId": cond_id,
            "conditionValues": [{"controlId": sys_field, "nodeId": _SYSTEM_NODE_ID,
                                  "appType": 100, "nodeType": 100}],
            "sourceType": 0,
        }

    value = right.get("value", "")
    if isinstance(value, list):
        return {
            "filedId": field_id,
            "nodeId": node_id,
            "filedTypeId": filed_type_id,
            "conditionId": cond_id,
            "conditionValues": [{"value": v} for v in value],
            "sourceType": 0,
        }

    return {
        "filedId": field_id,
        "nodeId": node_id,
        "filedTypeId": filed_type_id,
        "conditionId": cond_id,
        "conditionValues": [{"value": value}],
        "sourceType": 0,
    }


class Task:
    """A save task (action node or query filter)."""

    __slots__ = ("kind", "alias", "pid", "node_id", "data")
    # kind: "action" | "search" | "get_more_record"


def collect_tasks(nodes: list[dict], alias_to_id: dict[str, str],
                  pid: str, inner_pids: dict[str, str]) -> list[Task]:
    """Walk the node tree and collect all save tasks."""
    tasks: list[Task] = []

    def walk(node_list: list[dict], current_pid: str):
        for node in node_list:
            nt = node.get("nodeType", "")
            alias = node.get("nodeAlias", "")
            config = node.get("config", {}) or {}
            node_id = alias_to_id.get(alias, "")

            # ── action nodes (update/create/delete) ──
            if nt in NODE_TYPE_ACTION:
                target = config.get("target", {}) or {}
                source_alias = target.get("node", "")
                t = Task()
                t.kind = "action"
                t.alias = alias
                t.pid = current_pid
                t.node_id = node_id
                t.data = {
                    "action_id": NODE_TYPE_ACTION[nt],
                    "name": node.get("name", alias),
                    "worksheet_id": config.get("worksheet", ""),
                    "source_node_id": alias_to_id.get(source_alias, ""),
                    "fields": _normalize_fields(config.get("fields", [])),
                }
                tasks.append(t)

            # ── query nodes with filter ──
            if nt in ("get_single", "get_multiple") and config.get("filter"):
                filt = config["filter"]
                wire_filters = _build_filter_wire(filt, alias_to_id)
                if wire_filters:
                    t = Task()
                    t.alias = alias
                    t.pid = current_pid
                    t.node_id = node_id
                    t.data = {
                        "name": node.get("name", alias),
                        "worksheet_id": config.get("worksheet", ""),
                        "target": config.get("target"),
                        "filters": wire_filters,
                        "select_node_id": alias_to_id.get(
                            (config.get("target") or {}).get("node", ""), ""),
                    }
                    if nt == "get_multiple":
                        t.kind = "get_more_record"
                    else:
                        t.kind = "search"
                    tasks.append(t)

            # Recurse into branch paths
            for path in config.get("paths", []):
                walk(path.get("nodes", []), current_pid)

            # Recurse into approval_block / sub_process inner nodes
            process = config.get("process", {}) or {}
            inner_nodes = process.get("nodes", [])
            if inner_nodes:
                inner_pid = inner_pids.get(alias, current_pid)
                walk(inner_nodes, inner_pid)

    walk(nodes, pid)
    return tasks


def execute_task(session: Session, task: Task) -> dict:
    """Execute one task. Returns {alias, ok, error}."""
    try:
        if task.kind == "action":
            save_action_node(
                session,
                process_id=task.pid,
                node_id=task.node_id,
                action_id=task.data["action_id"],
                app_id=task.data["worksheet_id"],
                fields=task.data["fields"],
                name=task.data["name"],
                select_node_id=task.data.get("source_node_id", ""),
            )
        elif task.kind == "get_more_record":
            save_get_more_record_node(
                session,
                process_id=task.pid,
                node_id=task.node_id,
                action_id="400",
                app_id=task.data["worksheet_id"],
                name=task.data["name"],
                select_node_id=task.data.get("select_node_id", ""),
                filters=task.data["filters"],
            )
        elif task.kind == "search":
            save_search_node(
                session,
                process_id=task.pid,
                node_id=task.node_id,
                action_id="406",
                app_id=task.data["worksheet_id"],
                name=task.data["name"],
                select_node_id=task.data.get("select_node_id", ""),
                filters=task.data["filters"],
            )
        return {"alias": task.alias, "ok": True}
    except Exception as e:
        return {"alias": task.alias, "ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Parallel save: action node fields + query node filters")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--batch-output", help="batch-add JSON output")
    parser.add_argument("--mapping", help='Inline JSON: {"alias":"nodeId",...}')
    parser.add_argument("--pid", help="Process ID (overrides contract)")
    parser.add_argument("--inner-pids", help='Inline JSON: {"alias":"innerPid",...}')
    args = parser.parse_args()

    contract = load_contract(args.contract)

    alias_to_id: dict[str, str] = {}
    if args.mapping:
        alias_to_id.update(json.loads(args.mapping))
    if args.batch_output:
        bo = json.loads(args.batch_output)
        alias_to_id.update(bo.get("aliasToNodeId", {}))

    inner_pids: dict[str, str] = {}
    if args.inner_pids:
        inner_pids.update(json.loads(args.inner_pids))
    if args.batch_output:
        bo = json.loads(args.batch_output)
        for c in bo.get("created", []):
            ip = c.get("innerProcessId", "")
            if ip:
                inner_pids[c.get("alias", "")] = ip

    pid = args.pid or contract.get("workflow", {}).get("pid", "")
    nodes = contract.get("nodes", [])

    tasks = collect_tasks(nodes, alias_to_id, pid, inner_pids)

    if not tasks:
        print("No save tasks found in contract.")
        return

    kinds = {}
    for t in tasks:
        kinds[t.kind] = kinds.get(t.kind, 0) + 1
    print(f"Saving {len(tasks)} items ({', '.join(f'{v} {k}' for k,v in kinds.items())}) on PID={pid} ...")
    t0 = time.time()

    session = Session.load()

    with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as ex:
        futures = {ex.submit(execute_task, session, t): t for t in tasks}

    ok, fail = 0, 0
    for f in as_completed(futures):
        r = f.result()
        if r["ok"]:
            ok += 1
            print(f"  \u2713 {r['alias']}")
        else:
            fail += 1
            print(f"  \u2717 {r['alias']}: {r['error']}", file=sys.stderr)

    t1 = time.time()
    print(f"\n{ok}/{len(tasks)} saved in {t1 - t0:.2f}s")
    if fail:
        print(f"  {fail} failed — check stderr above")
        sys.exit(1)


if __name__ == "__main__":
    main()
