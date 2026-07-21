#!/usr/bin/env python3
"""验证 Agent 1/2/3 统一输出 envelope 的完整性。

本脚本只把 JSON/协议问题算作格式失败。结构完整但 ``verdict=fail`` 的
Agent 输出是有效的语义失败，验证命令仍返回 0，并在 ``semantic_failures``
中报告。合并器据此区分“Agent 没按协议输出”和“Agent 判断方案不通过”。

用法:
  python3 validate-agent-output.py --agent1 agent1.json --agent2 agent2.json
  python3 validate-agent-output.py --agent3 agent3.json
  python3 validate-agent-output.py --input output.json
  python3 validate-agent-output.py --selftest

退出码:
  0 = 所有输入格式完整（允许语义 verdict=fail）
  1 = 至少一个输入格式不完整
  2 = 命令行用法错误
"""

import argparse
import copy
import json
import sys
from pathlib import Path


SCHEMA_VERSION = "1.0"
AGENT_IDS = {
    "agent1": "agent_1_logic",
    "agent2": "agent_2_platform",
    "agent3": "agent_3_audit",
}
FAILURE_CODES = {
    "agent_1_logic": "A1_LOGIC_FAILED",
    "agent_2_platform": "A2_PLATFORM_FAILED",
    "agent_3_audit": "A3_AUDIT_COVERAGE_INCOMPLETE",
}
ENVELOPE_KEYS = {
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
}
SUMMARY_KEYS = {"total_checks", "passed", "failed", "uncertain"}
FIX_GUIDE_CATEGORIES = {"easy", "medium", "hard"}
VALID_SEVERITIES = {"high", "medium", "low", "warn"}
VALID_RESULTS = {"pass", "fail", "uncertain", "n/a", "warn"}
AGENT1_SECTIONS = {
    "axiom_compliance",
    "timeline",
    "naming_and_fields",
    "logic",
    "signals",
}
AGENT2_CHECKS = {
    "type_exists",
    "sub_mode",
    "data_link",
    "batch_limit",
    "no_data_policy",
    "fetch_mode",
}
AGENT2_TOPOLOGY = {
    "total_nodes",
    "nesting_depth",
    "concurrent_triggers",
    "data_races",
    "branch_coverage",
    "subprocess_cycles",
}
AGENT3_PAYLOAD_KEYS = {
    "missed_dimensions",
    "uncovered_constraints",
    "false_negatives",
}


def _failure(path, code, detail):
    return {"path": path, "code": code, "detail": detail}


def _missing_and_extra(value, required, path, failures):
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    for key in missing:
        failures.append(
            _failure(
                f"{path}.{key}",
                "FORMAT_REQUIRED_FIELD_MISSING",
                f"缺少必需字段: {key}",
            )
        )
    for key in extra:
        failures.append(
            _failure(
                f"{path}.{key}",
                "FORMAT_UNEXPECTED_FIELD",
                f"存在未声明字段: {key}",
            )
        )


def _validate_string_list(value, path, failures):
    if not isinstance(value, list):
        failures.append(
            _failure(path, "FORMAT_TYPE_MISMATCH", "必须是字符串数组")
        )
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            failures.append(
                _failure(
                    f"{path}[{index}]",
                    "FORMAT_TYPE_MISMATCH",
                    "必须是非空字符串",
                )
            )


def _validate_check_result(value, path, failures):
    if not isinstance(value, dict):
        failures.append(_failure(path, "FORMAT_TYPE_MISMATCH", "检查结果必须是对象"))
        return None
    result = value.get("result")
    if result not in VALID_RESULTS:
        failures.append(
            _failure(
                f"{path}.result",
                "FORMAT_INVALID_VALUE",
                f"result 必须是 {sorted(VALID_RESULTS)} 之一",
            )
        )
    if result == "fail":
        evidence = value.get("detail") or value.get("violations") or value.get("warnings")
        if not evidence:
            failures.append(
                _failure(
                    path,
                    "FORMAT_FAILURE_WITHOUT_EVIDENCE",
                    "result=fail 时必须提供 detail、violations 或 warnings",
                )
            )
    return result


def _validate_common(data, expected_agent_id=None):
    failures = []
    if not isinstance(data, dict):
        return [
            _failure("$", "FORMAT_TOP_LEVEL_NOT_OBJECT", "顶级 JSON 必须是对象")
        ]

    _missing_and_extra(data, ENVELOPE_KEYS, "$", failures)

    if data.get("schema_version") != SCHEMA_VERSION:
        failures.append(
            _failure(
                "$.schema_version",
                "FORMAT_SCHEMA_VERSION_UNSUPPORTED",
                f"schema_version 必须为 {SCHEMA_VERSION}",
            )
        )

    agent_id = data.get("agent_id")
    if agent_id not in FAILURE_CODES:
        failures.append(
            _failure(
                "$.agent_id",
                "FORMAT_AGENT_ID_UNKNOWN",
                f"未知 agent_id: {agent_id}",
            )
        )
    elif expected_agent_id and agent_id != expected_agent_id:
        failures.append(
            _failure(
                "$.agent_id",
                "FORMAT_AGENT_ID_MISMATCH",
                f"文件应由 {expected_agent_id} 输出，实际为 {agent_id}",
            )
        )

    input_digest = data.get("input_digest")
    if (
        not isinstance(input_digest, str)
        or len(input_digest) != 64
        or any(character not in "0123456789abcdef" for character in input_digest)
    ):
        failures.append(
            _failure(
                "$.input_digest",
                "FORMAT_INPUT_DIGEST_INVALID",
                "input_digest 必须是 64 位小写 SHA-256 十六进制字符串",
            )
        )

    verdict = data.get("verdict")
    if verdict not in {"pass", "fail"}:
        failures.append(
            _failure(
                "$.verdict",
                "FORMAT_INVALID_VALUE",
                "verdict 必须是 pass 或 fail",
            )
        )

    failure_code = data.get("failure_code")
    if verdict == "pass" and failure_code is not None:
        failures.append(
            _failure(
                "$.failure_code",
                "FORMAT_VERDICT_CODE_CONFLICT",
                "verdict=pass 时 failure_code 必须为 null",
            )
        )
    elif verdict == "fail" and agent_id in FAILURE_CODES:
        expected_code = FAILURE_CODES[agent_id]
        if failure_code != expected_code:
            failures.append(
                _failure(
                    "$.failure_code",
                    "FORMAT_VERDICT_CODE_CONFLICT",
                    f"{agent_id} 失败时 failure_code 必须为 {expected_code}",
                )
            )

    summary = data.get("summary")
    if not isinstance(summary, dict):
        failures.append(
            _failure("$.summary", "FORMAT_TYPE_MISMATCH", "summary 必须是对象")
        )
    else:
        missing = SUMMARY_KEYS - set(summary)
        for key in sorted(missing):
            failures.append(
                _failure(
                    f"$.summary.{key}",
                    "FORMAT_REQUIRED_FIELD_MISSING",
                    f"summary 缺少字段: {key}",
                )
            )
        values = {}
        for key in SUMMARY_KEYS:
            value = summary.get(key)
            if type(value) is not int or value < 0:
                failures.append(
                    _failure(
                        f"$.summary.{key}",
                        "FORMAT_TYPE_MISMATCH",
                        "必须是非负整数",
                    )
                )
            else:
                values[key] = value
        if len(values) == len(SUMMARY_KEYS):
            subtotal = values["passed"] + values["failed"] + values["uncertain"]
            if values["total_checks"] != subtotal:
                failures.append(
                    _failure(
                        "$.summary",
                        "FORMAT_SUMMARY_COUNT_CONFLICT",
                        "total_checks 必须等于 passed + failed + uncertain",
                    )
                )
            if verdict == "pass" and values["failed"] != 0:
                failures.append(
                    _failure(
                        "$.summary.failed",
                        "FORMAT_VERDICT_SUMMARY_CONFLICT",
                        "verdict=pass 时 failed 必须为 0",
                    )
                )
            if verdict == "fail" and values["failed"] == 0:
                failures.append(
                    _failure(
                        "$.summary.failed",
                        "FORMAT_VERDICT_SUMMARY_CONFLICT",
                        "verdict=fail 时 failed 必须大于 0",
                    )
                )

    issues = data.get("issues")
    if not isinstance(issues, list):
        failures.append(
            _failure("$.issues", "FORMAT_TYPE_MISMATCH", "issues 必须是数组")
        )
    else:
        if verdict == "fail" and not issues:
            failures.append(
                _failure(
                    "$.issues",
                    "FORMAT_FAILURE_WITHOUT_EVIDENCE",
                    "verdict=fail 时 issues 不得为空",
                )
            )
        if verdict == "pass" and any(
            isinstance(issue, dict) and issue.get("severity") == "high"
            for issue in issues
        ):
            failures.append(
                _failure(
                    "$.issues",
                    "FORMAT_VERDICT_ISSUES_CONFLICT",
                    "verdict=pass 时不得包含 high severity issue",
                )
            )
        for index, issue in enumerate(issues):
            path = f"$.issues[{index}]"
            if not isinstance(issue, dict):
                failures.append(
                    _failure(path, "FORMAT_TYPE_MISMATCH", "issue 必须是对象")
                )
                continue
            for key in ("severity", "description", "fix"):
                if key not in issue:
                    failures.append(
                        _failure(
                            f"{path}.{key}",
                            "FORMAT_REQUIRED_FIELD_MISSING",
                            f"issue 缺少字段: {key}",
                        )
                    )
            if issue.get("severity") not in VALID_SEVERITIES:
                failures.append(
                    _failure(
                        f"{path}.severity",
                        "FORMAT_INVALID_VALUE",
                        f"severity 必须是 {sorted(VALID_SEVERITIES)} 之一",
                    )
                )
            for key in ("description", "fix"):
                if key in issue and (
                    not isinstance(issue[key], str) or not issue[key].strip()
                ):
                    failures.append(
                        _failure(
                            f"{path}.{key}",
                            "FORMAT_TYPE_MISMATCH",
                            "必须是非空字符串",
                        )
                    )

    fix_guide = data.get("fix_guide")
    if not isinstance(fix_guide, dict):
        failures.append(
            _failure("$.fix_guide", "FORMAT_TYPE_MISMATCH", "fix_guide 必须是对象")
        )
    else:
        _missing_and_extra(fix_guide, FIX_GUIDE_CATEGORIES, "$.fix_guide", failures)
        for category in FIX_GUIDE_CATEGORIES:
            items = fix_guide.get(category)
            if not isinstance(items, list):
                if category in fix_guide:
                    failures.append(
                        _failure(
                            f"$.fix_guide.{category}",
                            "FORMAT_TYPE_MISMATCH",
                            "修复分组必须是数组",
                        )
                    )
                continue
            for index, item in enumerate(items):
                path = f"$.fix_guide.{category}[{index}]"
                if not isinstance(item, dict):
                    failures.append(
                        _failure(path, "FORMAT_TYPE_MISMATCH", "修复项必须是对象")
                    )
                    continue
                for key in ("issue", "action"):
                    if key not in item:
                        failures.append(
                            _failure(
                                f"{path}.{key}",
                                "FORMAT_REQUIRED_FIELD_MISSING",
                                f"修复项缺少字段: {key}",
                            )
                        )
                    elif not isinstance(item[key], str) or not item[key].strip():
                        failures.append(
                            _failure(
                                f"{path}.{key}",
                                "FORMAT_TYPE_MISMATCH",
                                "必须是非空字符串",
                            )
                        )

    uncertain_items = data.get("uncertain_items")
    if not isinstance(uncertain_items, list):
        failures.append(
            _failure(
                "$.uncertain_items",
                "FORMAT_TYPE_MISMATCH",
                "uncertain_items 必须是数组",
            )
        )
    else:
        for index, item in enumerate(uncertain_items):
            path = f"$.uncertain_items[{index}]"
            if not isinstance(item, dict):
                failures.append(
                    _failure(path, "FORMAT_TYPE_MISMATCH", "不确定项必须是对象")
                )
                continue
            for key in ("item", "reason"):
                if key not in item:
                    failures.append(
                        _failure(
                            f"{path}.{key}",
                            "FORMAT_REQUIRED_FIELD_MISSING",
                            f"不确定项缺少字段: {key}",
                        )
                    )
                elif not isinstance(item[key], str) or not item[key].strip():
                    failures.append(
                        _failure(
                            f"{path}.{key}",
                            "FORMAT_TYPE_MISMATCH",
                            "必须是非空字符串",
                        )
                    )

    if not isinstance(data.get("payload"), dict):
        failures.append(
            _failure("$.payload", "FORMAT_TYPE_MISMATCH", "payload 必须是对象")
        )
    return failures


def validate_agent1(data):
    """返回 Agent 1 envelope 的格式失败列表。"""
    failures = _validate_common(data, AGENT_IDS["agent1"])
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return failures
    _missing_and_extra(payload, {"sections"}, "$.payload", failures)
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        failures.append(
            _failure(
                "$.payload.sections",
                "FORMAT_TYPE_MISMATCH",
                "Agent 1 sections 必须是对象",
            )
        )
        return failures
    _missing_and_extra(
        sections, AGENT1_SECTIONS, "$.payload.sections", failures
    )
    failed_sections = 0
    for name in AGENT1_SECTIONS:
        if name in sections:
            result = _validate_check_result(
                sections[name], f"$.payload.sections.{name}", failures
            )
            failed_sections += int(result == "fail")
    if (
        data.get("verdict") == "pass"
        and failed_sections
    ):
        failures.append(
            _failure(
                "$.verdict",
                "FORMAT_PAYLOAD_VERDICT_CONFLICT",
                "Agent 1 payload 含 fail section，envelope 不得判 pass",
            )
        )
    return failures


def validate_agent2(data):
    """返回 Agent 2 envelope 的格式失败列表。"""
    failures = _validate_common(data, AGENT_IDS["agent2"])
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return failures
    _missing_and_extra(
        payload, {"node_checks", "topology_checks"}, "$.payload", failures
    )

    failed_checks = 0
    node_checks = payload.get("node_checks")
    if not isinstance(node_checks, list):
        failures.append(
            _failure(
                "$.payload.node_checks",
                "FORMAT_TYPE_MISMATCH",
                "node_checks 必须是数组",
            )
        )
    else:
        for index, node in enumerate(node_checks):
            path = f"$.payload.node_checks[{index}]"
            if not isinstance(node, dict):
                failures.append(
                    _failure(path, "FORMAT_TYPE_MISMATCH", "节点检查必须是对象")
                )
                continue
            for key in ("node_name", "node_type", "checks"):
                if key not in node:
                    failures.append(
                        _failure(
                            f"{path}.{key}",
                            "FORMAT_REQUIRED_FIELD_MISSING",
                            f"节点检查缺少字段: {key}",
                        )
                    )
            checks = node.get("checks")
            if not isinstance(checks, dict):
                failures.append(
                    _failure(
                        f"{path}.checks",
                        "FORMAT_TYPE_MISMATCH",
                        "checks 必须是对象",
                    )
                )
                continue
            _missing_and_extra(checks, AGENT2_CHECKS, f"{path}.checks", failures)
            for name in AGENT2_CHECKS:
                if name in checks:
                    result = _validate_check_result(
                        checks[name], f"{path}.checks.{name}", failures
                    )
                    failed_checks += int(result == "fail")

    topology = payload.get("topology_checks")
    if not isinstance(topology, dict):
        failures.append(
            _failure(
                "$.payload.topology_checks",
                "FORMAT_TYPE_MISMATCH",
                "topology_checks 必须是对象",
            )
        )
    else:
        _missing_and_extra(
            topology, AGENT2_TOPOLOGY, "$.payload.topology_checks", failures
        )
        for name in AGENT2_TOPOLOGY:
            if name in topology:
                result = _validate_check_result(
                    topology[name], f"$.payload.topology_checks.{name}", failures
                )
                failed_checks += int(result == "fail")

    if data.get("verdict") == "pass" and failed_checks:
        failures.append(
            _failure(
                "$.verdict",
                "FORMAT_PAYLOAD_VERDICT_CONFLICT",
                "Agent 2 payload 含 fail check，envelope 不得判 pass",
            )
        )
    return failures


def validate_agent3(data):
    """返回 Agent 3 envelope 的格式失败列表。"""
    failures = _validate_common(data, AGENT_IDS["agent3"])
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return failures
    _missing_and_extra(
        payload, AGENT3_PAYLOAD_KEYS, "$.payload", failures
    )
    for key in AGENT3_PAYLOAD_KEYS:
        if key in payload:
            _validate_string_list(payload[key], f"$.payload.{key}", failures)

    lists = [payload.get(key) for key in AGENT3_PAYLOAD_KEYS]
    if all(isinstance(value, list) for value in lists):
        has_misses = any(lists)
        if data.get("verdict") == "pass" and has_misses:
            failures.append(
                _failure(
                    "$.payload.missed_dimensions",
                    "FORMAT_PAYLOAD_VERDICT_CONFLICT",
                    "Agent 3 存在漏检项时不得判 pass",
                )
            )
        if data.get("verdict") == "fail" and not has_misses:
            failures.append(
                _failure(
                    "$.payload.missed_dimensions",
                    "FORMAT_FAILURE_WITHOUT_EVIDENCE",
                    "Agent 3 判 fail 时至少一个漏检数组必须非空",
                )
            )
    return failures


VALIDATORS = {
    AGENT_IDS["agent1"]: validate_agent1,
    AGENT_IDS["agent2"]: validate_agent2,
    AGENT_IDS["agent3"]: validate_agent3,
}


def auto_detect_agent(data):
    """从统一 envelope 的 agent_id 检测 Agent 类型。"""
    if not isinstance(data, dict):
        return "unknown"
    agent_id = data.get("agent_id")
    for short_name, known_id in AGENT_IDS.items():
        if agent_id == known_id:
            return short_name
    return "unknown"


def validate_output(data, expected_agent_id=None):
    """验证单个输出，返回格式与语义分离的结果。"""
    agent_id = data.get("agent_id") if isinstance(data, dict) else None
    validator = VALIDATORS.get(expected_agent_id or agent_id)
    if validator is None:
        failures = _validate_common(data, expected_agent_id)
    else:
        failures = validator(data)
        if expected_agent_id and isinstance(data, dict) and agent_id != expected_agent_id:
            # 对应 validator 已检查 mismatch；这里不重复追加。
            pass

    format_verdict = "pass" if not failures else "fail"
    semantic_verdict = (
        data.get("verdict")
        if format_verdict == "pass" and isinstance(data, dict)
        else "not_evaluated"
    )
    semantic_failures = []
    if semantic_verdict == "fail":
        semantic_failures.append(
            {
                "agent_id": agent_id,
                "failure_code": data.get("failure_code"),
                "summary": data.get("summary"),
                "issues": data.get("issues"),
            }
        )
    return {
        "agent_id": agent_id,
        "format_verdict": format_verdict,
        "semantic_verdict": semantic_verdict,
        "format_failures": failures,
        "semantic_failures": semantic_failures,
    }


def _base_envelope(agent_id):
    return {
        "schema_version": SCHEMA_VERSION,
        "agent_id": agent_id,
        "input_digest": "0" * 64,
        "verdict": "pass",
        "failure_code": None,
        "summary": {
            "total_checks": 1,
            "passed": 1,
            "failed": 0,
            "uncertain": 0,
        },
        "issues": [],
        "fix_guide": {"easy": [], "medium": [], "hard": []},
        "uncertain_items": [],
        "payload": {},
    }


def _selftest_cases():
    check = {"result": "pass", "detail": "已检查"}

    agent1 = _base_envelope(AGENT_IDS["agent1"])
    agent1["payload"] = {
        "sections": {name: copy.deepcopy(check) for name in AGENT1_SECTIONS}
    }

    agent2 = _base_envelope(AGENT_IDS["agent2"])
    agent2["payload"] = {
        "node_checks": [
            {
                "node_name": "触发",
                "node_type": "trigger(typeId=0)",
                "checks": {
                    name: copy.deepcopy(check) for name in AGENT2_CHECKS
                },
            }
        ],
        "topology_checks": {
            name: copy.deepcopy(check) for name in AGENT2_TOPOLOGY
        },
    }

    agent3 = _base_envelope(AGENT_IDS["agent3"])
    agent3["payload"] = {
        "missed_dimensions": [],
        "uncovered_constraints": [],
        "false_negatives": [],
    }

    cases = []
    for name, valid in (
        ("agent1", agent1),
        ("agent2", agent2),
        ("agent3", agent3),
    ):
        cases.append((f"{name}_pass", valid, True, "pass"))

        semantic_fail = copy.deepcopy(valid)
        semantic_fail["verdict"] = "fail"
        semantic_fail["failure_code"] = FAILURE_CODES[semantic_fail["agent_id"]]
        semantic_fail["summary"] = {
            "total_checks": 1,
            "passed": 0,
            "failed": 1,
            "uncertain": 0,
        }
        semantic_fail["issues"] = [
            {
                "severity": "high",
                "description": "自测语义失败",
                "fix": "修正自测输入",
            }
        ]
        if name == "agent1":
            semantic_fail["payload"]["sections"]["logic"] = {
                "result": "fail",
                "detail": "自测失败",
            }
        elif name == "agent2":
            semantic_fail["payload"]["topology_checks"]["total_nodes"] = {
                "result": "fail",
                "detail": "自测失败",
            }
        else:
            semantic_fail["payload"]["missed_dimensions"] = ["公理5"]
        cases.append((f"{name}_semantic_fail", semantic_fail, True, "fail"))

        invalid = copy.deepcopy(valid)
        invalid.pop("summary")
        cases.append((f"{name}_invalid", invalid, False, "not_evaluated"))
    return cases


def run_selftest():
    results = []
    passed = True
    for name, data, expect_format_pass, expect_semantic in _selftest_cases():
        result = validate_output(data)
        actual_format_pass = result["format_verdict"] == "pass"
        ok = (
            actual_format_pass == expect_format_pass
            and result["semantic_verdict"] == expect_semantic
        )
        passed = passed and ok
        results.append(
            {
                "case": name,
                "result": "pass" if ok else "fail",
                "format_verdict": result["format_verdict"],
                "semantic_verdict": result["semantic_verdict"],
                "format_failure_count": len(result["format_failures"]),
            }
        )
    output = {
        "verdict": "pass" if passed else "fail",
        "cases": results,
        "cases_passed": sum(item["result"] == "pass" for item in results),
        "cases_total": len(results),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def _load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, _failure(
            "$", "FORMAT_FILE_NOT_FOUND", f"文件不存在: {path}"
        )
    except json.JSONDecodeError as exc:
        return None, _failure(
            "$",
            "FORMAT_JSON_PARSE_ERROR",
            f"JSON 解析失败: {exc}",
        )
    except OSError as exc:
        return None, _failure(
            "$", "FORMAT_FILE_READ_ERROR", f"读取文件失败: {exc}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="验证 Agent 1/2/3 统一输出 envelope 的完整性"
    )
    parser.add_argument("--agent1", help="Agent 1 JSON 输出文件")
    parser.add_argument("--agent2", help="Agent 2 JSON 输出文件")
    parser.add_argument("--agent3", help="Agent 3 JSON 输出文件")
    parser.add_argument("--input", "-i", help="按 agent_id 自动检测的 JSON 文件")
    parser.add_argument("--quiet", action="store_true", help="输出精简 JSON")
    parser.add_argument("--selftest", action="store_true", help="运行内置正反例")
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()

    inputs = []
    for short_name in ("agent1", "agent2", "agent3"):
        path = getattr(args, short_name)
        if path:
            inputs.append((path, AGENT_IDS[short_name]))
    if args.input:
        inputs.append((args.input, None))
    if not inputs:
        parser.error("至少提供 --agent1、--agent2、--agent3 或 --input")

    results = {}
    all_format_failures = []
    all_semantic_failures = []
    for path, expected_agent_id in inputs:
        data, load_failure = _load_json(path)
        if load_failure:
            result = {
                "agent_id": expected_agent_id,
                "format_verdict": "fail",
                "semantic_verdict": "not_evaluated",
                "format_failures": [load_failure],
                "semantic_failures": [],
            }
        else:
            result = validate_output(data, expected_agent_id)
        results[path] = result
        all_format_failures.extend(
            dict(item, file=path) for item in result["format_failures"]
        )
        all_semantic_failures.extend(
            dict(item, file=path) for item in result["semantic_failures"]
        )

    format_verdict = "pass" if not all_format_failures else "fail"
    if all_format_failures:
        semantic_verdict = "not_evaluated"
    else:
        semantic_verdict = "fail" if all_semantic_failures else "pass"
    output = {
        "verdict": format_verdict,
        "format_verdict": format_verdict,
        "semantic_verdict": semantic_verdict,
        "files_checked": len(inputs),
        "format_failure_count": len(all_format_failures),
        "semantic_failure_count": len(all_semantic_failures),
        "format_failures": all_format_failures,
        "semantic_failures": all_semantic_failures,
        "results": results,
    }

    if args.quiet:
        output = {
            "format_verdict": format_verdict,
            "semantic_verdict": semantic_verdict,
            "format_failure_count": len(all_format_failures),
            "semantic_failure_count": len(all_semantic_failures),
        }
    print(json.dumps(output, ensure_ascii=False, indent=None if args.quiet else 2))
    return 0 if format_verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
