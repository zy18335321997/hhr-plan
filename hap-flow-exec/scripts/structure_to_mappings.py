#!/usr/bin/env python3
"""Extract PID-scoped alias→nodeId mappings from read-only workflow structure."""

import argparse
import json
import sys
from pathlib import Path


def _alias(node: dict) -> str:
    return node.get("nodeAlias") or node.get("alias") or ""


def _node_id(node: dict) -> str:
    return node.get("nodeId") or node.get("id") or ""


def extract_scoped_mappings(structure: object) -> dict[str, dict[str, str]]:
    mappings: dict[str, dict[str, str]] = {}

    def walk(value: object, inherited_pid: str | None = None) -> None:
        if isinstance(value, list):
            for child in value:
                walk(child, inherited_pid)
            return
        if not isinstance(value, dict):
            return
        pid = (
            value.get("processId")
            or value.get("pid")
            or value.get("innerProcessId")
            or inherited_pid
        )
        flow_node_map = value.get("flowNodeMap")
        if isinstance(flow_node_map, dict) and pid:
            scope = mappings.setdefault(pid, {})
            start_event_id = value.get("startEventId")
            for map_node_id, node in flow_node_map.items():
                if not isinstance(node, dict):
                    continue
                alias = _alias(node)
                node_id = _node_id(node) or map_node_id
                if not alias and node_id == start_event_id:
                    alias = "trigger"
                if alias and node_id:
                    scope[alias] = node_id
                process_node = node.get("processNode")
                inner_pid = (
                    node.get("innerProcessId")
                    or (
                        process_node.get("processId")
                        if isinstance(process_node, dict)
                        else None
                    )
                )
                if process_node:
                    walk(process_node, inner_pid or pid)
        nodes = value.get("nodes")
        if isinstance(nodes, list) and pid:
            scope = mappings.setdefault(pid, {})
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                alias = _alias(node)
                node_id = _node_id(node)
                if alias and node_id:
                    scope[alias] = node_id
                walk(node, pid)
        for key, child in value.items():
            if key != "nodes":
                walk(child, pid)

    walk(structure)
    return mappings


def extract_batch_scoped_mappings(
    contract: dict,
    batch_output: dict,
) -> dict[str, dict[str, str]]:
    main_pid = batch_output.get("pid") or batch_output.get("processId")
    if not main_pid:
        return {}
    mappings = {
        main_pid: dict(batch_output.get("aliasToNodeId", {}))
    }
    created_by_alias = {}
    inner_pid_by_alias = {}
    for item in batch_output.get("created", []):
        if not isinstance(item, dict):
            continue
        alias = item.get("alias")
        node_id = item.get("nodeId")
        if alias and node_id:
            created_by_alias.setdefault(alias, []).append(node_id)
        if alias and item.get("innerProcessId"):
            inner_pid_by_alias[alias] = item["innerProcessId"]

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            alias = node.get("alias") or node.get("nodeAlias")
            process = (node.get("config") or {}).get("process") or {}
            inner_nodes = process.get("nodes") or []
            if inner_nodes:
                inner_pid = inner_pid_by_alias.get(alias)
                if inner_pid:
                    scope = mappings.setdefault(inner_pid, {})
                    for inner_node in inner_nodes:
                        if not isinstance(inner_node, dict):
                            continue
                        inner_alias = (
                            inner_node.get("alias")
                            or inner_node.get("nodeAlias")
                        )
                        if inner_alias in {"approval_start", "sub_trigger"}:
                            continue
                        candidates = created_by_alias.get(inner_alias, [])
                        if len(candidates) == 1:
                            scope[inner_alias] = candidates[0]
                    walk(inner_nodes)
            for path in (node.get("config") or {}).get("paths", []):
                path_nodes = [
                    child for child in path.get("nodes", [])
                    if isinstance(child, dict)
                ]
                walk(path_nodes)

    walk(contract.get("nodes", []))
    return mappings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 workflow structure JSON 提取按 PID 分域的 alias 映射"
    )
    parser.add_argument(
        "structure_files",
        nargs="*",
        help="主流程及各 inner PID 的 structure JSON",
    )
    parser.add_argument("--contract", help="execution contract JSON")
    parser.add_argument("--batch-output", help="batch-add output JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        mappings = {}
        for structure_file in args.structure_files:
            structure = json.loads(
                Path(structure_file).read_text(encoding="utf-8")
            )
            for pid, alias_map in extract_scoped_mappings(structure).items():
                mappings.setdefault(pid, {}).update(alias_map)
        if args.contract and args.batch_output:
            contract = json.loads(
                Path(args.contract).read_text(encoding="utf-8")
            )
            batch_output = json.loads(
                Path(args.batch_output).read_text(encoding="utf-8")
            )
            for pid, alias_map in extract_batch_scoped_mappings(
                contract,
                batch_output,
            ).items():
                mappings.setdefault(pid, {}).update(alias_map)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"verdict": "fail", "code": "STRUCTURE_READ_FAILED",
                 "detail": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    if not mappings:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "code": "STRUCTURE_ALIAS_MAPPING_EMPTY",
                    "detail": "structure 中没有 PID-scoped alias 映射",
                },
                ensure_ascii=False,
            )
        )
        return 1
    Path(args.output).write_text(
        json.dumps(mappings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"verdict": "pass", "scopes": len(mappings)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
