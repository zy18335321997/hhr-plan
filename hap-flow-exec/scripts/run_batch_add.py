#!/usr/bin/env python3
"""Run HAP batch-add and atomically persist validated runtime output."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _expected_main_nodes(nodes: list[dict]) -> list[dict]:
    expected = []

    def walk(items: list[dict]) -> None:
        for node in items:
            if not isinstance(node, dict):
                continue
            expected.append(node)
            for path in (node.get("config") or {}).get("paths", []):
                walk(
                    [
                        child
                        for child in path.get("nodes", [])
                        if isinstance(child, dict)
                    ]
                )

    walk(nodes)
    return expected


def recover_from_structure(
    pid: str,
    nodes: list[dict],
    hap_bin: str,
    trigger_alias: str,
) -> dict | None:
    completed = subprocess.run(
        [hap_bin, "--json", "workflow", "structure", pid],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    try:
        structure = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    actual_by_name = {}
    for node in structure.get("flowNodeMap", {}).values():
        if not isinstance(node, dict) or not node.get("name"):
            continue
        actual_by_name.setdefault(node["name"], []).append(node)
    mapping = {trigger_alias: structure.get("startEventId")}
    created = []
    for expected in _expected_main_nodes(nodes):
        alias = expected.get("nodeAlias")
        name = expected.get("name")
        matches = actual_by_name.get(name, [])
        if not alias or not name or len(matches) != 1:
            return None
        actual = matches[0]
        mapping[alias] = actual.get("id")
        item = {
            "alias": alias,
            "nodeId": actual.get("id"),
            "nodeType": expected.get("nodeType"),
        }
        process = actual.get("processNode")
        if isinstance(process, dict) and process.get("id"):
            item["innerProcessId"] = process["id"]
        created.append(item)
    if not mapping.get(trigger_alias) or any(not value for value in mapping.values()):
        return None
    return {
        "aliasToNodeId": mapping,
        "created": created,
        "pid": pid,
        "verdict": "pass",
        "recovered_from_structure": True,
    }


def atomic_write(path: str | Path, data: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def run_batch_add(
    pid: str,
    nodes: list[dict],
    hap_bin: str = "hap",
    trigger_alias: str = "trigger",
) -> tuple[dict, int]:
    completed = subprocess.run(
        [
            hap_bin,
            "workflow",
            "node",
            "batch-add",
            pid,
            "--trigger-alias",
            trigger_alias,
            "--nodes",
            json.dumps(nodes, ensure_ascii=False, separators=(",", ":")),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        recovered = recover_from_structure(
            pid,
            nodes,
            hap_bin,
            trigger_alias,
        )
        if recovered:
            return recovered, 0
        return {
            "verdict": "fail",
            "code": "BATCH_ADD_FAILED",
            "pid": pid,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }, completed.returncode or 1
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "verdict": "fail",
            "code": "BATCH_OUTPUT_INVALID_JSON",
            "pid": pid,
            "detail": str(exc),
            "raw": completed.stdout,
        }, 2
    if not isinstance(output.get("aliasToNodeId"), dict):
        return {
            "verdict": "fail",
            "code": "BATCH_ALIAS_MAPPING_MISSING",
            "pid": pid,
            "raw": output,
        }, 2
    output["pid"] = pid
    output["verdict"] = "pass"
    return output, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="执行 batch-add 并原子保存 PID/alias 映射"
    )
    parser.add_argument("--pid", required=True)
    parser.add_argument("--nodes-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--trigger-alias", default="trigger")
    parser.add_argument("--hap-bin", default="hap")
    args = parser.parse_args()
    try:
        nodes = json.loads(Path(args.nodes_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"verdict": "fail", "code": "BATCH_NODES_READ_FAILED",
                 "detail": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    result, exit_code = run_batch_add(
        args.pid,
        nodes,
        args.hap_bin,
        args.trigger_alias,
    )
    if exit_code == 0:
        atomic_write(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
