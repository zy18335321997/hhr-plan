#!/usr/bin/env python3
"""后置闸门 — 验证 Agent 1/2/3 输出格式的完整性和一致性。

只检查输出格式是否完整（所有 section 都跑了、没有跳过项、JSON 结构正确），
不判断 Agent 结论的正确性。

用法:
  python3 validate-agent-output.py --agent1 agent1_output.json
  python3 validate-agent-output.py --agent2 agent2_output.json
  python3 validate-agent-output.py --agent1 a1.json --agent2 a2.json
  python3 validate-agent-output.py --agent3 audit_result.json

exit code: 0 = 格式完整, 1 = 格式有缺失
"""

import argparse
import json
import sys
from pathlib import Path


# ── Agent 1 必须的 section 名 ──
AGENT1_REQUIRED_SECTIONS = [
    "axiom_compliance", "timeline", "naming_and_fields", "logic", "signals"
]

# ── Agent 1 顶级必须字段 ──
AGENT1_TOP_KEYS = {"verdict", "summary", "sections", "issues", "fix_guide", "uncertain_items"}

# ── Agent 2 每个节点必须的 check 字段 ──
AGENT2_REQUIRED_CHECKS = [
    "type_exists", "sub_mode", "data_link", "batch_limit", "no_data_policy", "fetch_mode"
]

# ── Agent 2 顶级必须字段 ──
AGENT2_TOP_KEYS = {"verdict", "summary", "node_checks", "issues", "fix_guide", "topology_checks", "uncertain_items"}

# ── issue 必须字段 ──
ISSUE_REQUIRED_KEYS = {"severity", "description", "fix"}

# ── fix_guide 必须的三个分组 ──
FIX_GUIDE_CATEGORIES = ["easy", "medium", "hard"]

# ── severity 有效值 ──
VALID_SEVERITIES = {"high", "medium", "low", "warn"}

# ── section result 有效值 ──
VALID_RESULTS = {"pass", "fail", "n/a", "delegated", "warn"}


def collect_violations(violations: list, severity: str, section: str, detail: str):
    """累积式错误收集 — 不提前退出。"""
    violations.append({"severity": severity, "section": section, "detail": detail})
    return violations


def validate_agent1(data: dict) -> list:
    """验证 Agent 1 (逻辑校验) 输出完整性。返回 violations 列表。"""
    v = []

    # --- 顶级字段 ---
    missing_top = AGENT1_TOP_KEYS - set(data.keys())
    if missing_top:
        v = collect_violations(v, "high", "structure",
                               f"缺少顶级字段: {missing_top}")

    # --- verdict ---
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        v = collect_violations(v, "high", "verdict",
                               f"verdict 值无效: {verdict} (期望 pass 或 fail)")

    # --- sections ---
    sections = data.get("sections", {})
    if not isinstance(sections, dict):
        v = collect_violations(v, "high", "sections",
                               "sections 字段不是 dict 或缺失")
        return v

    for sec_name in AGENT1_REQUIRED_SECTIONS:
        if sec_name not in sections:
            v = collect_violations(v, "high", f"sections.{sec_name}",
                                   f"缺少 section: {sec_name} — Agent 可能跳过了这个检查")
            continue

        sec = sections[sec_name]
        if not isinstance(sec, dict):
            v = collect_violations(v, "high", f"sections.{sec_name}",
                                   f"section {sec_name} 不是 dict, 类型: {type(sec).__name__}")
            continue

        result = sec.get("result")
        if result is None or result == "":
            v = collect_violations(v, "high", f"sections.{sec_name}",
                                   f"section {sec_name} 的 result 为空 — Agent 可能跳过了这个检查")
        elif result not in VALID_RESULTS:
            v = collect_violations(v, "medium", f"sections.{sec_name}",
                                   f"section {sec_name} 的 result 值无效: {result} (有效值: {VALID_RESULTS})")

        # 如果有 violations 字段, 检查其结构
        violations_list = sec.get("violations", sec.get("warnings", []))
        if result == "fail" and len(violations_list) == 0:
            v = collect_violations(v, "medium", f"sections.{sec_name}",
                                   f"section {sec_name} result=fail 但 violations 为空 — 应该至少有一条违规描述")

    # --- summary ---
    summary = data.get("summary", {})
    if isinstance(summary, dict):
        total = summary.get("total_checks", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        uncertain = summary.get("uncertain", 0)

        # 检查 summary 数值一致性
        if total > 0 and passed + failed + uncertain < total:
            v = collect_violations(v, "low", "summary",
                                   f"summary 数值不一致: total={total}, passed+failed+uncertain={passed+failed+uncertain}")

        # 检查 verdict 和 summary.failed 的一致性
        if failed > 0 and verdict == "pass":
            v = collect_violations(v, "high", "summary",
                                   f"verdict=pass 但 summary.failed={failed} — 矛盾的判定")
        if failed == 0 and verdict == "fail":
            # 可能是因为 uncertain items 或有 high severity issues
            pass  # 不强制 fail
    else:
        v = collect_violations(v, "medium", "summary",
                               "summary 字段缺失或不是 dict")

    # --- issues ---
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        v = collect_violations(v, "medium", "issues",
                               "issues 不是数组")
    else:
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                v = collect_violations(v, "medium", f"issues[{i}]",
                                       f"issue[{i}] 不是 dict")
                continue
            missing_keys = ISSUE_REQUIRED_KEYS - set(issue.keys())
            if missing_keys:
                v = collect_violations(v, "medium", f"issues[{i}]",
                                       f"issue[{i}] 缺少必需字段: {missing_keys}")
            if issue.get("severity") not in VALID_SEVERITIES:
                v = collect_violations(v, "low", f"issues[{i}]",
                                       f"issue[{i}] severity 无效: {issue.get('severity')}")

    # --- fix_guide ---
    fix_guide = data.get("fix_guide", {})
    if not isinstance(fix_guide, dict):
        v = collect_violations(v, "medium", "fix_guide",
                               "fix_guide 缺失或不是 dict")
    else:
        for cat in FIX_GUIDE_CATEGORIES:
            if cat not in fix_guide:
                v = collect_violations(v, "low", f"fix_guide.{cat}",
                                       f"fix_guide 缺少分类: {cat} (可以为空数组)")
            elif not isinstance(fix_guide[cat], list):
                v = collect_violations(v, "medium", f"fix_guide.{cat}",
                                       f"fix_guide.{cat} 不是数组")

    # --- uncertain_items ---
    uncertain = data.get("uncertain_items", [])
    if not isinstance(uncertain, list):
        v = collect_violations(v, "low", "uncertain_items",
                               "uncertain_items 不是数组")

    return v


def validate_agent2(data: dict) -> list:
    """验证 Agent 2 (平台校验) 输出完整性。返回 violations 列表。"""
    v = []

    # --- 顶级字段 ---
    missing_top = AGENT2_TOP_KEYS - set(data.keys())
    if missing_top:
        v = collect_violations(v, "high", "structure",
                               f"缺少顶级字段: {missing_top}")

    # --- verdict ---
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        v = collect_violations(v, "high", "verdict",
                               f"verdict 值无效: {verdict} (期望 pass 或 fail)")

    # --- node_checks ---
    node_checks = data.get("node_checks", [])
    if not isinstance(node_checks, list):
        v = collect_violations(v, "high", "node_checks",
                               "node_checks 不是数组或缺失")
        return v

    if len(node_checks) == 0:
        v = collect_violations(v, "high", "node_checks",
                               "node_checks 为空 — Agent 可能没有检查任何节点")

    for i, node in enumerate(node_checks):
        if not isinstance(node, dict):
            v = collect_violations(v, "medium", f"node_checks[{i}]",
                                   f"node_checks[{i}] 不是 dict")
            continue

        node_name = node.get("node_name", f"节点#{i}")

        # 检查 checks 字典
        checks = node.get("checks", {})
        if not isinstance(checks, dict):
            v = collect_violations(v, "high", f"node_checks[{i}].checks",
                                   f"{node_name}: checks 不是 dict")
            continue

        for check_name in AGENT2_REQUIRED_CHECKS:
            if check_name not in checks:
                v = collect_violations(v, "high", f"node_checks[{i}].checks.{check_name}",
                                       f"{node_name}: 缺少检查项 {check_name} — Agent 可能跳过了这个检查")
                continue

            check = checks[check_name]
            if not isinstance(check, dict):
                v = collect_violations(v, "medium", f"node_checks[{i}].checks.{check_name}",
                                       f"{node_name}.{check_name}: 不是 dict")
                continue

            result = check.get("result")
            if result is None or result == "":
                v = collect_violations(v, "high", f"node_checks[{i}].checks.{check_name}",
                                       f"{node_name}.{check_name}: result 为空 — Agent 跳过了这个检查")
            elif result not in VALID_RESULTS:
                v = collect_violations(v, "medium", f"node_checks[{i}].checks.{check_name}",
                                       f"{node_name}.{check_name}: result 值无效: {result}")

            # 如果 result=fail 但没有 detail, 这不合理
            if result == "fail" and not check.get("detail"):
                v = collect_violations(v, "low", f"node_checks[{i}].checks.{check_name}",
                                       f"{node_name}.{check_name}: result=fail 但没有 detail 说明")

    # --- topology_checks ---
    topology = data.get("topology_checks", {})
    if isinstance(topology, dict):
        topo_keys = ["total_nodes", "nesting_depth", "concurrent_triggers",
                     "data_races", "branch_coverage", "subprocess_cycles"]
        for tk in topo_keys:
            if tk not in topology:
                v = collect_violations(v, "medium", f"topology_checks.{tk}",
                                       f"缺少拓扑检查项: {tk}")
    else:
        v = collect_violations(v, "medium", "topology_checks",
                               "topology_checks 缺失")

    # --- summary ---
    summary = data.get("summary", {})
    if isinstance(summary, dict):
        nodes_checked = summary.get("nodes_checked", 0)
        checks_failed = summary.get("checks_failed", 0)

        if nodes_checked > 0 and len(node_checks) != nodes_checked:
            v = collect_violations(v, "low", "summary",
                                   f"summary.nodes_checked={nodes_checked} 但实际 node_checks 长度为 {len(node_checks)}")

        if checks_failed > 0 and verdict == "pass":
            v = collect_violations(v, "high", "summary",
                                   f"verdict=pass 但 summary.checks_failed={checks_failed}")

    # --- issues ---
    issues = data.get("issues", [])
    if isinstance(issues, list):
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                continue
            missing_keys = ISSUE_REQUIRED_KEYS - set(issue.keys())
            if missing_keys:
                v = collect_violations(v, "medium", f"issues[{i}]",
                                       f"issue[{i}] 缺少必需字段: {missing_keys}")

    # --- fix_guide ---
    fix_guide = data.get("fix_guide", {})
    if isinstance(fix_guide, dict):
        for cat in FIX_GUIDE_CATEGORIES:
            if cat not in fix_guide:
                v = collect_violations(v, "low", f"fix_guide.{cat}",
                                       f"fix_guide 缺少分类: {cat}")

    return v


def validate_agent3(data: dict) -> list:
    """验证 Agent 3 (审计扫描) 输出完整性。"""
    v = []

    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        v = collect_violations(v, "high", "verdict",
                               f"verdict 值无效: {verdict} (期望 pass 或 fail)")

    # Agent 3 格式比较简单, 主要检查 verdict 和是否有漏检项列表
    if verdict == "fail":
        missing = data.get("missing", data.get("missed", data.get("漏检项", [])))
        if not missing:
            v = collect_violations(v, "medium", "output",
                                   "verdict=fail 但没有列出漏检项")

    return v


def auto_detect_agent(data: dict) -> str:
    """自动检测 Agent 类型。"""
    if "sections" in data and "axiom_compliance" in data.get("sections", {}):
        return "agent1"
    if "node_checks" in data and "topology_checks" in data:
        return "agent2"
    if "verdict" in data and "sections" not in data and "node_checks" not in data:
        return "agent3"
    return "unknown"


def main():
    parser = argparse.ArgumentParser(description="后置闸门 — 验证 Agent 输出格式完整性")
    parser.add_argument("--agent1", help="Agent 1 (逻辑校验) JSON 输出文件")
    parser.add_argument("--agent2", help="Agent 2 (平台校验) JSON 输出文件")
    parser.add_argument("--agent3", help="Agent 3 (审计扫描) JSON 输出文件")
    parser.add_argument("--input", "-i", help="自动检测类型的 JSON 输入文件")
    parser.add_argument("--quiet", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    all_violations = []
    total_agents = 0
    agents_passed = 0

    inputs_to_check = []

    if args.agent1:
        inputs_to_check.append(("agent1", args.agent1))
    if args.agent2:
        inputs_to_check.append(("agent2", args.agent2))
    if args.agent3:
        inputs_to_check.append(("agent3", args.agent3))
    if args.input:
        inputs_to_check.append(("auto", args.input))

    if not inputs_to_check:
        print(json.dumps({"verdict": "fail", "error": "需要至少一个输入: --agent1, --agent2, --agent3, 或 --input"},
                         ensure_ascii=False))
        sys.exit(2)

    results = {}

    for agent_type, filepath in inputs_to_check:
        # 读取 JSON
        try:
            with open(filepath) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            all_violations.append({"severity": "high", "section": "parse",
                                   "detail": f"无法解析 {filepath}: {e}"})
            results[filepath] = {"agent_type": agent_type, "verdict": "fail", "violations_count": 1}
            continue
        except FileNotFoundError:
            all_violations.append({"severity": "high", "section": "parse",
                                   "detail": f"文件不存在: {filepath}"})
            results[filepath] = {"agent_type": agent_type, "verdict": "fail", "violations_count": 1}
            continue

        # 自动检测类型
        if agent_type == "auto":
            agent_type = auto_detect_agent(data)
            if agent_type == "unknown":
                all_violations.append({"severity": "high", "section": "detect",
                                       "detail": f"无法自动检测 {filepath} 的 Agent 类型 — 请用 --agent1/--agent2/--agent3 显式指定"})
                results[filepath] = {"agent_type": "unknown", "verdict": "fail", "violations_count": 1}
                continue

        # 根据类型验证
        if agent_type == "agent1":
            violations = validate_agent1(data)
        elif agent_type == "agent2":
            violations = validate_agent2(data)
        elif agent_type == "agent3":
            violations = validate_agent3(data)
        else:
            violations = [{"severity": "high", "section": "type",
                            "detail": f"未知 Agent 类型: {agent_type}"}]

        total_agents += 1
        if len(violations) == 0:
            agents_passed += 1

        all_violations.extend(violations)
        results[filepath] = {
            "agent_type": agent_type,
            "verdict": "pass" if len(violations) == 0 else "fail",
            "violations_count": len(violations),
        }

    # ── 汇总输出 ──
    gate_verdict = "pass" if len(all_violations) == 0 else "fail"

    # 分组 violations 为 fix_guide 格式
    fix_guide = {"easy": [], "medium": [], "hard": []}
    for violation in all_violations:
        sev = violation.get("severity", "medium")
        action = ""
        detail = violation.get("detail", "")

        if "缺少" in detail or "缺失" in detail or "为空" in detail:
            if sev == "high":
                action = "Agent 必须重新运行以完成所有检查"
            else:
                action = "检查 Agent 指令，确保所有 section 都被覆盖"

        entry = {"section": violation.get("section", ""), "issue": detail, "action": action}

        if sev == "high":
            fix_guide["hard"].append(entry)
        elif sev == "medium":
            fix_guide["medium"].append(entry)
        else:
            fix_guide["easy"].append(entry)

    summary = {
        "verdict": gate_verdict,
        "source": "validate-agent-output.py (post-hoc gate)",
        "total_agents": total_agents,
        "agents_passed": agents_passed,
        "agents_failed": total_agents - agents_passed,
        "total_violations": len(all_violations),
        "high": sum(1 for v in all_violations if v["severity"] == "high"),
        "medium": sum(1 for v in all_violations if v["severity"] == "medium"),
        "low": sum(1 for v in all_violations if v["severity"] == "low"),
        "violations": all_violations,
        "fix_guide": fix_guide,
        "results": results,
    }

    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"verdict": gate_verdict, "total_violations": len(all_violations)},
                         ensure_ascii=False))

    sys.exit(0 if gate_verdict == "pass" else 1)


if __name__ == "__main__":
    main()
