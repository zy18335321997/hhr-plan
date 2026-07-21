#!/usr/bin/env python3
"""Persistent, deterministic execution state and failure policy."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


STEPS = [
    "static_preflight",
    "live_preflight",
    "create_skeleton",
    "batch_add",
    "save_actions",
    "structure_verify",
    "publish_inner",
    "publish_main",
    "complete",
]
TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
    "429",
    "502",
    "503",
    "504",
)
RUNTIME_DATA_MARKERS = (
    "fieldid",
    "option key",
    "worksheet",
    "not found",
    "不存在",
    "无效 id",
)
SEMANTIC_MARKERS = (
    "schema",
    "contract",
    "condition",
    "scope",
    "alias",
    "branch",
    "审批",
    "子流程",
)
MUTATING_STEPS = {
    "create_skeleton",
    "batch_add",
    "save_actions",
    "publish_inner",
    "publish_main",
}


def contract_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify_failure(message: str, step: str) -> str:
    lowered = message.lower()
    if step in MUTATING_STEPS:
        return "PARTIAL_WRITE"
    if any(marker in lowered for marker in TRANSIENT_MARKERS):
        return "TRANSIENT"
    if any(marker in lowered for marker in RUNTIME_DATA_MARKERS):
        return "RUNTIME_DATA"
    if any(marker in lowered for marker in SEMANTIC_MARKERS):
        return "SEMANTIC"
    return "SEMANTIC"


def new_state(contract_path: str, state_path: str) -> dict:
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0",
        "contract_path": str(Path(contract_path).resolve()),
        "contract_digest": contract_digest(contract_path),
        "workflow_name": contract.get("meta", {}).get("workflow_name"),
        "status": "ready",
        "current_step": "static_preflight",
        "completed_steps": [],
        "attempts": {},
        "in_progress_step": None,
        "operation_id": None,
        "runtime": {
            "pid": None,
            "trigger_node_id": None,
            "alias_to_node_id": {},
            "inner_pids": {},
        },
        "errors": [],
        "next_action": "run",
        "state_path": str(Path(state_path).resolve()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_state(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_write(path: str | Path, state: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
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
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def verify_contract_unchanged(state: dict) -> None:
    actual = contract_digest(state["contract_path"])
    if actual != state["contract_digest"]:
        raise ValueError(
            "execution_contract 已变化；旧 execution_state 不可继续，必须重新 init"
        )


def next_step_after(step: str) -> str:
    index = STEPS.index(step)
    return STEPS[min(index + 1, len(STEPS) - 1)]


def begin_step(state: dict, step: str) -> dict:
    verify_contract_unchanged(state)
    if step != state["current_step"]:
        raise ValueError(
            f"只能开始当前步骤: current={state['current_step']}, requested={step}"
        )
    if state.get("in_progress_step"):
        raise ValueError(
            "存在结果未知的 in-progress 写入；必须先只读探测平台状态，禁止重跑"
        )
    state["in_progress_step"] = step
    state["operation_id"] = str(uuid.uuid4())
    state["status"] = "running"
    state["next_action"] = "execute_current_step"
    return state


def advance(
    state: dict,
    step: str,
    runtime: dict | None = None,
) -> dict:
    verify_contract_unchanged(state)
    if step not in STEPS:
        raise ValueError(f"未知 step: {step}")
    if step in MUTATING_STEPS and state.get("in_progress_step") != step:
        raise ValueError(
            f"mutating step {step} 必须先 begin，防止崩溃窗口重复写入"
        )
    current_index = STEPS.index(state["current_step"])
    step_index = STEPS.index(step)
    if step_index < current_index and step in state["completed_steps"]:
        raise ValueError(f"step {step} 已完成；禁止重复执行产生重复节点")
    if step_index > current_index:
        raise ValueError(
            f"不能跳步：当前={state['current_step']}，请求={step}"
        )
    if step not in state["completed_steps"]:
        state["completed_steps"].append(step)
    if runtime:
        for key, value in runtime.items():
            if value not in (None, {}, ""):
                state["runtime"][key] = value
    runtime_requirements = {
        "create_skeleton": ("pid", "trigger_node_id"),
        "batch_add": ("pid", "alias_to_node_id"),
        "save_actions": ("pid", "alias_to_node_id"),
        "publish_main": ("pid",),
    }
    missing = [
        key
        for key in runtime_requirements.get(step, ())
        if state["runtime"].get(key) in (None, {}, "")
    ]
    if missing:
        raise ValueError(
            f"step {step} 缺少运行时产物: {', '.join(missing)}"
        )
    state["current_step"] = next_step_after(step)
    state["in_progress_step"] = None
    state["operation_id"] = None
    state["status"] = "completed" if step == "complete" else "ready"
    state["next_action"] = "done" if step == "complete" else "run"
    return state


def record_failure(
    state: dict,
    step: str,
    message: str,
    exit_code: int | None = None,
) -> tuple[dict, str]:
    verify_contract_unchanged(state)
    failure_class = classify_failure(message, step)
    attempts = state["attempts"].get(step, 0) + 1
    state["attempts"][step] = attempts
    decision = "hard_stop"
    if failure_class == "TRANSIENT":
        if attempts <= 3:
            decision = "retry"
            state["status"] = "retryable"
            state["next_action"] = "retry_same_step"
        else:
            decision = "hard_stop"
            state["status"] = "blocked"
            state["next_action"] = "inspect_repeated_transient_failure"
    elif failure_class == "RUNTIME_DATA":
        decision = "reprobe"
        state["status"] = "blocked"
        state["next_action"] = "run_live_preflight"
    elif failure_class == "SEMANTIC":
        decision = "mode_b_handoff"
        state["status"] = "blocked"
        state["next_action"] = "return_to_hhr_plan_mode_b"
    else:
        decision = "await_user"
        state["status"] = "partial"
        state["next_action"] = "review_compensation_plan"
    state["errors"].append(
        {
            "step": step,
            "class": failure_class,
            "message": message,
            "exit_code": exit_code,
            "attempt": attempts,
            "decision": decision,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    if failure_class != "PARTIAL_WRITE":
        state["in_progress_step"] = None
        state["operation_id"] = None
    return state, decision


def _load_json_argument(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        path = Path(raw)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        pass
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 HAP 工作流执行状态")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--contract", required=True)
    init_parser.add_argument("--state", required=True)
    init_parser.add_argument(
        "--reset",
        action="store_true",
        help="显式丢弃旧 checkpoint 并重新初始化",
    )

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state", required=True)

    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--state", required=True)
    begin_parser.add_argument("--step", choices=STEPS, required=True)

    advance_parser = subparsers.add_parser("advance")
    advance_parser.add_argument("--state", required=True)
    advance_parser.add_argument("--step", choices=STEPS, required=True)
    advance_parser.add_argument("--pid")
    advance_parser.add_argument("--trigger-node-id")
    advance_parser.add_argument("--batch-output")

    fail_parser = subparsers.add_parser("fail")
    fail_parser.add_argument("--state", required=True)
    fail_parser.add_argument("--step", choices=STEPS, required=True)
    fail_parser.add_argument("--message", required=True)
    fail_parser.add_argument("--exit-code", type=int)
    args = parser.parse_args()

    try:
        if args.command == "init":
            if Path(args.state).exists() and not args.reset:
                raise ValueError(
                    "execution_state 已存在；拒绝覆盖。确需重置时显式传 --reset"
                )
            state = new_state(args.contract, args.state)
            atomic_write(args.state, state)
            result = state
        elif args.command == "status":
            state = load_state(args.state)
            verify_contract_unchanged(state)
            result = state
        elif args.command == "begin":
            state = load_state(args.state)
            result = begin_step(state, args.step)
            atomic_write(args.state, result)
        elif args.command == "advance":
            state = load_state(args.state)
            batch_output = _load_json_argument(args.batch_output)
            runtime = {
                "pid": args.pid
                or batch_output.get("pid")
                or batch_output.get("processId"),
                "trigger_node_id": args.trigger_node_id
                or batch_output.get("triggerNodeId"),
                "alias_to_node_id": batch_output.get("aliasToNodeId", {}),
                "inner_pids": {
                    item.get("alias"): item.get("innerProcessId")
                    for item in batch_output.get("created", [])
                    if item.get("alias") and item.get("innerProcessId")
                },
            }
            result = advance(state, args.step, runtime)
            atomic_write(args.state, result)
        else:
            state = load_state(args.state)
            result, decision = record_failure(
                state,
                args.step,
                args.message,
                args.exit_code,
            )
            atomic_write(args.state, result)
            result = {"decision": decision, "state": result}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {"verdict": "fail", "code": "EXECUTION_STATE_ERROR",
                 "detail": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps({"verdict": "pass", "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
