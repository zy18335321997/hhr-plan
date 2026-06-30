#!/usr/bin/env python3
"""Agent 上下文预处理器 — 从 execution_lock.json 生成 Agent 可读的简洁摘要。

Usage:
    python3 agent_prepare.py path/to/execution_lock.json --output /tmp/hhr_agent_brief.json
"""

import argparse
import json
import sys
from pathlib import Path


def prepare_brief(lock_path: str) -> dict:
    """Extract only what agents need from execution_lock.json."""
    with open(lock_path) as f:
        lock = json.load(f)

    # Meta — just the essentials
    brief = {
        "_source": lock_path,
        "_prepared_for": "logic-verify + platform-verify agents",
        "meta": {
            "project": lock.get("meta", {}).get("project", ""),
            "mode": lock.get("meta", {}).get("mode", ""),
            "axioms_covered": lock.get("meta", {}).get("axioms_covered", []),
        },
        "naming": lock.get("naming", {}),
        # Sheets — only names, is_hub, and field names (agents don't need full config)
        "sheets": [],
        # Associations — full (needed for cycle detection)
        "associations": lock.get("associations", []),
        # Workflows — node chain with types and axiom refs
        "workflows": [],
        # Gate status
        "gates": lock.get("gates", {}),
    }

    for s in lock.get("sheets", []):
        brief["sheets"].append({
            "name": s.get("name", ""),
            "is_hub": s.get("is_hub", False),
            "module": s.get("module", ""),
            "field_names": [f.get("name", "") for f in s.get("fields", [])],
        })

    for wf in lock.get("workflows", []):
        node_chain_slim = []
        for n in wf.get("node_chain", []):
            node_chain_slim.append({
                "index": n.get("index", ""),
                "node_type": n.get("node_type", ""),
                "target_sheet": n.get("target_sheet"),
                "writes_fields": n.get("writes_fields", []),
                "reads_fields": n.get("reads_fields", []),
                "empty_strategy": n.get("empty_strategy"),
                "approval_mode": (n.get("approval_config") or {}).get("mode"),
                "subprocess_exec": (n.get("subprocess_config") or {}).get("execution_mode"),
            })

        brief["workflows"].append({
            "name": wf.get("name", ""),
            "trigger_sheet": wf.get("trigger_sheet", ""),
            "trigger_type": wf.get("trigger_type", ""),
            "node_count": len(node_chain_slim),
            "axiom_ref": wf.get("axiom_ref", ""),
            "node_chain": node_chain_slim,
        })

    return brief


def main():
    parser = argparse.ArgumentParser(description="Agent 上下文预处理器")
    parser.add_argument("lock_path", help="execution_lock.json 路径")
    parser.add_argument("--output", default=None, help="输出路径（默认 stdout）")
    args = parser.parse_args()

    brief = prepare_brief(args.lock_path)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        sheet_count = len(brief.get("sheets", []))
        wf_count = len(brief.get("workflows", []))
        print(f"Agent brief written: {sheet_count} sheets, {wf_count} workflows → {args.output}", file=sys.stderr)
    else:
        print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
