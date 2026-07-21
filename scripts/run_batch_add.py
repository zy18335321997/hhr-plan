#!/usr/bin/env python3
"""Run HAP batch-add and atomically persist validated runtime output."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


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
