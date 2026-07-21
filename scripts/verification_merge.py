#!/usr/bin/env python3
"""校验 Agent 输出并原子写入目标 JSON 的 gates。

本脚本不调用 LLM。Cursor 主 Agent 负责通过 Subagent 工具取得 Agent 输出；
本脚本只执行确定性的完整性校验、语义裁决汇总和 gates 写入。

退出码:
  0 = 完整性通过，所有 Agent 语义通过，已写 gates
  1 = 完整性通过，至少一个 Agent 语义失败，已写 gates
  2 = 完整性/输入格式失败，未写 gates
"""

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATOR_PATH = SCRIPT_DIR / "validate-agent-output.py"
PREPARE_PATH = SCRIPT_DIR / "agent_prepare.py"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "hhr_validate_agent_output", VALIDATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载校验器: {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator_module()
AGENT_IDS = VALIDATOR.AGENT_IDS


def _load_prepare_module():
    spec = importlib.util.spec_from_file_location(
        "hhr_agent_prepare", PREPARE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载摘要计算器: {PREPARE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREPARE = _load_prepare_module()


def _format_failure(path, code, detail, file=None):
    failure = {"path": path, "code": code, "detail": detail}
    if file is not None:
        failure["file"] = str(file)
    return failure


def load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, _format_failure(
            "$", "FORMAT_FILE_NOT_FOUND", f"文件不存在: {path}", path
        )
    except json.JSONDecodeError as exc:
        return None, _format_failure(
            "$", "FORMAT_JSON_PARSE_ERROR", f"JSON 解析失败: {exc}", path
        )
    except OSError as exc:
        return None, _format_failure(
            "$", "FORMAT_FILE_READ_ERROR", f"读取文件失败: {exc}", path
        )


def required_agent_ids(mode):
    if mode == "design":
        return [AGENT_IDS["agent1"], AGENT_IDS["agent2"]]
    if mode == "audit":
        return [AGENT_IDS["agent3"]]
    if mode == "all":
        return [
            AGENT_IDS["agent1"],
            AGENT_IDS["agent2"],
            AGENT_IDS["agent3"],
        ]
    raise ValueError(f"未知 mode: {mode}")


def infer_mode(provided_ids):
    provided = set(provided_ids)
    design = {AGENT_IDS["agent1"], AGENT_IDS["agent2"]}
    audit = {AGENT_IDS["agent3"]}
    if provided == design:
        return "design"
    if provided == audit:
        return "audit"
    if provided == design | audit:
        return "all"
    return "design" if provided & design else "audit"


def validate_envelopes(envelopes, required_ids, expected_digests):
    """返回完整性失败和可安全合并的 envelope 映射。"""
    format_failures = []
    by_agent = {}

    for source, expected_agent_id, envelope in envelopes:
        if expected_agent_id in by_agent:
            format_failures.append(
                _format_failure(
                    "$.agent_id",
                    "FORMAT_DUPLICATE_AGENT_OUTPUT",
                    f"重复提供 Agent 输出: {expected_agent_id}",
                    source,
                )
            )
            continue
        result = VALIDATOR.validate_output(envelope, expected_agent_id)
        for failure in result["format_failures"]:
            format_failures.append(dict(failure, file=str(source)))
        if result["format_verdict"] == "pass":
            expected_digest = expected_digests.get(expected_agent_id)
            if envelope.get("input_digest") != expected_digest:
                format_failures.append(
                    _format_failure(
                        "$.input_digest",
                        "FORMAT_INPUT_DIGEST_MISMATCH",
                        (
                            f"{expected_agent_id} 的 input_digest 与当前校验输入"
                            "不一致；必须重新运行 Agent"
                        ),
                        source,
                    )
                )
                continue
            by_agent[expected_agent_id] = envelope

    for agent_id in required_ids:
        if agent_id not in by_agent:
            format_failures.append(
                _format_failure(
                    "$.agent_id",
                    "FORMAT_REQUIRED_AGENT_OUTPUT_MISSING",
                    f"缺少完整的 Agent 输出: {agent_id}",
                )
            )

    unexpected = sorted(set(by_agent) - set(required_ids))
    for agent_id in unexpected:
        format_failures.append(
            _format_failure(
                "$.agent_id",
                "FORMAT_UNEXPECTED_AGENT_OUTPUT",
                f"当前模式不接受 Agent 输出: {agent_id}",
            )
        )
    return format_failures, by_agent


def _dedupe_fix_items(envelopes):
    fix_plan = {"easy": [], "medium": [], "hard": [], "total_issues": 0}
    for category in ("easy", "medium", "hard"):
        seen = set()
        for envelope in envelopes:
            agent_id = envelope["agent_id"]
            for item in envelope["fix_guide"][category]:
                merged = dict(item)
                merged["agent_id"] = agent_id
                signature = json.dumps(merged, ensure_ascii=False, sort_keys=True)
                if signature not in seen:
                    seen.add(signature)
                    fix_plan[category].append(merged)
    fix_plan["total_issues"] = sum(
        len(envelope["issues"]) for envelope in envelopes
    )
    return fix_plan


def build_verification(envelopes, input_digest, source=None):
    """构建 Agent gates 与顶层 verification；调用方已完成完整性校验。"""
    gates = {}
    ordered = sorted(envelopes, key=lambda item: item["agent_id"])
    semantic_failures = []
    for envelope in ordered:
        agent_id = envelope["agent_id"]
        gates[agent_id] = {
            "schema_version": envelope["schema_version"],
            "result": envelope["verdict"],
            "failure_code": envelope["failure_code"],
            "summary": envelope["summary"],
            "issues": envelope["issues"],
            "fix_guide": envelope["fix_guide"],
            "uncertain_items": envelope["uncertain_items"],
        }
        if envelope["verdict"] == "fail":
            semantic_failures.append(
                {
                    "agent_id": agent_id,
                    "failure_code": envelope["failure_code"],
                    "issues": envelope["issues"],
                }
            )

    semantic_verdict = "fail" if semantic_failures else "pass"
    verification_agents = {
        "schema_version": VALIDATOR.SCHEMA_VERSION,
        "completeness": "pass",
        "semantic_verdict": semantic_verdict,
        "agents": [item["agent_id"] for item in ordered],
        "agent_input_digests": {
            item["agent_id"]: item["input_digest"] for item in ordered
        },
    }
    verification = {
        "input_digest": input_digest,
        "verification_agents": verification_agents,
        "fix_plan": _dedupe_fix_items(ordered),
    }
    if source is not None:
        verification["source"] = str(source)
    return gates, verification, semantic_failures


def merge_into_target(target, gates, verification):
    if not isinstance(target, dict):
        raise ValueError("目标 JSON 顶级必须是对象")
    existing_gates = target.get("gates")
    if existing_gates is None:
        target["gates"] = {}
    elif not isinstance(existing_gates, dict):
        raise ValueError("目标 JSON 的 gates 必须是对象")
    target["gates"].pop("verification_agents", None)
    target["gates"].pop("fix_plan", None)
    target["gates"].update(gates)
    target["verification"] = verification
    return target


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _result(
    format_verdict,
    semantic_verdict,
    written,
    mode,
    format_failures=None,
    semantic_failures=None,
    gates=None,
):
    return {
        "format_verdict": format_verdict,
        "semantic_verdict": semantic_verdict,
        "gates_written": written,
        "mode": mode,
        "format_failures": format_failures or [],
        "semantic_failures": semantic_failures or [],
        "gates": gates or {},
    }


def run_merge(
    target_path,
    input_paths,
    mode="auto",
    dry_run=False,
    source_path=None,
):
    envelopes = []
    load_failures = []
    for expected_agent_id, path in input_paths:
        data, failure = load_json(path)
        if failure:
            load_failures.append(failure)
        else:
            envelopes.append((path, expected_agent_id, data))

    provided_ids = [expected_agent_id for expected_agent_id, _ in input_paths]
    selected_mode = infer_mode(provided_ids) if mode == "auto" else mode
    target, target_failure = load_json(target_path)
    if target_failure:
        return _result(
            "fail",
            "not_evaluated",
            False,
            selected_mode,
            format_failures=[target_failure],
        ), 2
    if not isinstance(target, dict) or (
        "gates" in target and not isinstance(target["gates"], dict)
    ):
        failure = _format_failure(
            "$.gates",
            "FORMAT_TARGET_GATES_INVALID",
            "目标 JSON 顶级及 gates 必须是对象",
            target_path,
        )
        return _result(
            "fail",
            "not_evaluated",
            False,
            selected_mode,
            format_failures=[failure],
        ), 2

    target_digest = PREPARE.compute_lock_digest(target)
    source_digest = None
    source_failure = None
    if selected_mode in {"audit", "all"}:
        if not source_path:
            source_failure = _format_failure(
                "$.input_digest",
                "FORMAT_AUDIT_SOURCE_REQUIRED",
                "audit/all 模式必须用 --source 指向本次审计报告",
            )
        else:
            try:
                source_digest = PREPARE.compute_file_digest(source_path)
            except FileNotFoundError:
                source_failure = _format_failure(
                    "$.input_digest",
                    "FORMAT_FILE_NOT_FOUND",
                    f"审计源文件不存在: {source_path}",
                    source_path,
                )
            except OSError as exc:
                source_failure = _format_failure(
                    "$.input_digest",
                    "FORMAT_FILE_READ_ERROR",
                    f"无法读取审计源文件: {exc}",
                    source_path,
                )

    expected_digests = {
        AGENT_IDS["agent1"]: target_digest,
        AGENT_IDS["agent2"]: target_digest,
        AGENT_IDS["agent3"]: source_digest,
    }
    required_ids = required_agent_ids(selected_mode)
    format_failures, by_agent = validate_envelopes(
        envelopes,
        required_ids,
        expected_digests,
    )
    format_failures = load_failures + (
        [source_failure] if source_failure else []
    ) + format_failures
    if format_failures:
        return _result(
            "fail",
            "not_evaluated",
            False,
            selected_mode,
            format_failures=format_failures,
        ), 2

    ordered_envelopes = [by_agent[agent_id] for agent_id in required_ids]
    verification_digest = (
        source_digest if selected_mode == "audit" else target_digest
    )
    gates, verification, semantic_failures = build_verification(
        ordered_envelopes,
        verification_digest,
        source=source_path if selected_mode in {"audit", "all"} else None,
    )
    merged = merge_into_target(target, gates, verification)
    if not dry_run:
        atomic_write_json(target_path, merged)
    semantic_verdict = "fail" if semantic_failures else "pass"
    result = _result(
        "pass",
        semantic_verdict,
        not dry_run,
        selected_mode,
        semantic_failures=semantic_failures,
        gates=gates,
    )
    result["verification"] = verification
    if dry_run:
        result["would_write_gates"] = True
    return result, 1 if semantic_failures else 0


def main():
    parser = argparse.ArgumentParser(
        description="完整性通过后，将 Agent 语义裁决原子写入目标 JSON gates"
    )
    parser.add_argument(
        "--target",
        "--lock",
        dest="target",
        required=True,
        help="要更新 gates 的 execution_lock.json 或审计状态 JSON",
    )
    parser.add_argument(
        "--source",
        help="audit/all 模式必填：Agent 3 实际读取的审计报告",
    )
    parser.add_argument("--agent1", help="Agent 1 输出")
    parser.add_argument("--agent2", help="Agent 2 输出")
    parser.add_argument("--agent3", help="Agent 3 输出")
    parser.add_argument(
        "--mode",
        choices=("auto", "design", "audit", "all"),
        default="auto",
        help="design 需 Agent1+2；audit 需 Agent3；all 需 Agent1+2+3",
    )
    parser.add_argument("--dry-run", action="store_true", help="校验并预览，不写文件")
    parser.add_argument("--quiet", action="store_true", help="只输出关键字段")
    args = parser.parse_args()

    input_paths = []
    for short_name in ("agent1", "agent2", "agent3"):
        path = getattr(args, short_name)
        if path:
            input_paths.append((AGENT_IDS[short_name], path))
    if not input_paths:
        parser.error("至少提供一个 --agent1、--agent2 或 --agent3")

    result, exit_code = run_merge(
        args.target,
        input_paths,
        mode=args.mode,
        dry_run=args.dry_run,
        source_path=args.source,
    )
    if args.quiet:
        result = {
            "format_verdict": result["format_verdict"],
            "semantic_verdict": result["semantic_verdict"],
            "gates_written": result["gates_written"],
            "format_failure_count": len(result["format_failures"]),
            "semantic_failure_count": len(result["semantic_failures"]),
        }
    print(json.dumps(result, ensure_ascii=False, indent=None if args.quiet else 2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
