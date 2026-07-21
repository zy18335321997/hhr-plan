#!/usr/bin/env python3
"""Agent 上下文预处理器 — 从 execution_lock.json 生成只读校验摘要。

Usage:
    python3 agent_prepare.py path/to/execution_lock.json \
      --validator-result /tmp/hhr_design_validation.json \
      --output /tmp/hhr_agent_brief.json

该脚本只准备上下文，不调用 LLM，也不写 execution_lock.json。
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path


SCHEMA_VERSION = "1.0"
DESIGN_AGENT_IDS = ("agent_1_logic", "agent_2_platform")
BASIC_GATE_NAMES = {
    "gate_1_dependency",
    "gate_2_logic",
    "gate_3_timing",
    "gate_4_fields",
    "gate_5_platform",
    "gate_6_reasoning",
}


def normalized_lock_for_digest(lock: dict) -> dict:
    """Return the design-only projection used for Agent input binding."""
    normalized = copy.deepcopy(lock)
    normalized.pop("verification", None)
    gates = normalized.get("gates")
    if isinstance(gates, dict):
        normalized["gates"] = {
            name: gate
            for name, gate in gates.items()
            if name in BASIC_GATE_NAMES
        }
    return normalized


def compute_lock_digest(lock: dict) -> str:
    """SHA-256 of canonical lock design content, excluding derived verdicts."""
    canonical = json.dumps(
        normalized_lock_for_digest(lock),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compute_file_digest(path: str | Path) -> str:
    """SHA-256 of an arbitrary source file's exact bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_validator_evidence(
    validator_result_path: str,
    expected_digest: str,
) -> dict:
    """Load a passing design-validator result bound to the current lock."""
    with open(validator_result_path, encoding="utf-8") as file:
        result = json.load(file)
    if not isinstance(result, dict):
        raise ValueError("design_validator 结果顶级必须是对象")
    if result.get("overall_verdict") != "pass":
        raise ValueError("design_validator 未通过，不能准备 Agent brief")
    if result.get("input_digest") != expected_digest:
        raise ValueError(
            "design_validator 结果与当前 execution_lock 摘要不一致"
        )
    return {
        "source": validator_result_path,
        "overall_verdict": "pass",
        "input_digest": expected_digest,
        "results": result.get("results", []),
    }


def prepare_brief(lock_path: str, validator_result_path: str) -> dict:
    """Extract only what agents need from execution_lock.json."""
    with open(lock_path, encoding="utf-8") as f:
        lock = json.load(f)
    input_digest = compute_lock_digest(lock)
    validator_evidence = load_validator_evidence(
        validator_result_path,
        input_digest,
    )

    # Meta — just the essentials
    brief = {
        "_source": lock_path,
        "_prepared_for": list(DESIGN_AGENT_IDS),
        "input_digest": input_digest,
        "deterministic_evidence": {
            "design_validator": validator_evidence,
        },
        "verification_contract": {
            "schema_version": SCHEMA_VERSION,
            "schema": "references/schemas/agent-verification-output.schema.json",
            "required_envelope": [
                "schema_version",
                "agent_id",
                "input_digest",
                "verdict",
                "failure_code",
                "summary",
                "issues",
                "fix_guide",
                "uncertain_items",
                "payload",
            ],
            "agent_ids": list(DESIGN_AGENT_IDS),
        },
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
        # Workflows — node chain with platform and logic checks' required inputs
        "workflows": [],
    }

    for s in lock.get("sheets", []):
        brief["sheets"].append({
            "name": s.get("name", ""),
            "is_hub": s.get("is_hub", False),
            "module": s.get("module", ""),
            "fields": [
                {
                    "name": f.get("name", ""),
                    "type": f.get("type", ""),
                    "required": f.get("required", False),
                    "unique": f.get("unique", False),
                    "options": f.get("options", []),
                }
                for f in s.get("fields", [])
                if isinstance(f, dict)
            ],
        })

    for wf in lock.get("workflows", []):
        node_chain_slim = []
        for n in wf.get("node_chain", []):
            node_chain_slim.append({
                "index": n.get("index", ""),
                "node_name": n.get("node_name", n.get("name", "")),
                "node_type": n.get("node_type", ""),
                "type_id": n.get("type_id"),
                "action_id": n.get("action_id"),
                "sub_mode": n.get("sub_mode"),
                "target_sheet": n.get("target_sheet"),
                "writes_fields": n.get("writes_fields", []),
                "reads_fields": n.get("reads_fields", []),
                "empty_strategy": n.get("empty_strategy"),
                "fetch_mode": n.get("fetch_mode"),
                "batch_limit": n.get("batch_limit"),
                "timeline": n.get("timeline", n.get("time")),
                "approval_mode": (n.get("approval_config") or {}).get("mode"),
                "subprocess_exec": (n.get("subprocess_config") or {}).get("execution_mode"),
                "subprocess_abort": (n.get("subprocess_config") or {}).get("abort_strategy"),
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
    parser.add_argument(
        "--validator-result",
        required=True,
        help="与当前 lock 摘要绑定且 verdict=pass 的 design_validator JSON",
    )
    parser.add_argument("--output", default=None, help="输出路径（默认 stdout）")
    args = parser.parse_args()

    try:
        brief = prepare_brief(args.lock_path, args.validator_result)
    except FileNotFoundError as exc:
        print(
            json.dumps(
                {"verdict": "fail", "error": f"文件不存在: {exc.filename}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(
            json.dumps(
                {"verdict": "fail", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"verdict": "fail", "error": f"JSON 解析失败: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(brief, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sheet_count = len(brief.get("sheets", []))
        wf_count = len(brief.get("workflows", []))
        print(f"Agent brief written: {sheet_count} sheets, {wf_count} workflows → {args.output}", file=sys.stderr)
    else:
        print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
