#!/usr/bin/env python3
"""Token 预算版摘要 — 将 Agent 1/2 的完整 JSON 压缩为 Agent 可消费的简短格式。

用法:
  python3 summarize-output.py --agent1 agent1_output.json
  python3 summarize-output.py --agent2 agent2_output.json
  python3 summarize-output.py --agent1 a1.json --agent2 a2.json > summary.json

输出限制: ～2000 字符 (远远低于 RepoPrompt CE 的 16000)
"""

import argparse
import json
import sys

# ── 摘要参数 ──
MAX_EASY_ITEMS = 10
MAX_MEDIUM_ITEMS = 5
MAX_HARD_ITEMS = None   # 全部列出
MAX_TOP_FAILURES = 5     # 最严重的 N 个问题
TARGET_CHARS = 2000


def extract_agent1_summary(data: dict) -> dict:
    """从 Agent 1 输出提取摘要。"""
    summary = {
        "verdict": data.get("verdict", "?"),
        "source": "agent1",
    }

    stats = data.get("summary", {})
    summary["checks"] = f"{stats.get('passed',0)}/{stats.get('total_checks',0)} passed, {stats.get('failed',0)} failed"

    # 只列出 fail 的 section
    failed_sections = []
    for sec_name, sec in data.get("sections", {}).items():
        if isinstance(sec, dict) and sec.get("result") == "fail":
            violations = sec.get("violations", sec.get("warnings", []))
            failed_sections.append({
                "section": sec_name,
                "violations": len(violations),
                "sample": violations[0].get("detail", "")[:80] if violations else ""
            })

    if failed_sections:
        summary["failed_sections"] = failed_sections

    # Issues 按 severity 汇总
    issues = data.get("issues", [])
    sev_count = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        sev_count[i.get("severity", "low")] = sev_count.get(i.get("severity", "low"), 0) + 1
    summary["issues_by_severity"] = sev_count

    # Top failures
    top = sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity"), 3))
    summary["top_issues"] = [
        {"s": i.get("severity"), "a": i.get("axiom", ""), "d": i.get("description", "")[:100]}
        for i in top[:MAX_TOP_FAILURES]
    ]

    # Fix guide (压缩版)
    fg = data.get("fix_guide", {})
    summary["fix_guide"] = {
        "easy": [{"d": x.get("issue", "")[:80]} for x in fg.get("easy", [])[:MAX_EASY_ITEMS]],
        "medium": [{"d": x.get("issue", "")[:80]} for x in fg.get("medium", [])[:MAX_MEDIUM_ITEMS]],
        "hard": [{"d": x.get("issue", "")[:80]} for x in fg.get("hard", [])[:MAX_HARD_ITEMS or 999]],
    }

    return summary


def extract_agent2_summary(data: dict) -> dict:
    """从 Agent 2 输出提取摘要。"""
    summary = {
        "verdict": data.get("verdict", "?"),
        "source": "agent2",
    }

    stats = data.get("summary", {})
    summary["checks"] = f"{stats.get('nodes_checked',0)} nodes, {stats.get('checks_passed',0)}/{stats.get('checks_passed',0)+stats.get('checks_failed',0)} passed"

    # 只列出有 fail 的节点
    failed_nodes = []
    for node in data.get("node_checks", []):
        node_fails = []
        for check_name, check in node.get("checks", {}).items():
            if isinstance(check, dict) and check.get("result") == "fail":
                node_fails.append({"check": check_name, "detail": check.get("detail", "")[:60]})

        if node_fails:
            failed_nodes.append({
                "node": node.get("node_name", "?")[:40],
                "fails": node_fails[:3],  # 每个节点最多 3 条 fail
            })

    if failed_nodes:
        summary["failed_nodes"] = failed_nodes[:10]  # 最多 10 个失败节点

    # Topology issues
    topo = data.get("topology_checks", {})
    topo_fails = []
    for tk, tv in topo.items():
        if isinstance(tv, dict) and tv.get("result") in ("fail", "warn"):
            topo_fails.append({"check": tk, "detail": tv.get("detail", "")[:80]})

    if topo_fails:
        summary["topology_issues"] = topo_fails

    # Issues
    issues = data.get("issues", [])
    sev_count = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        sev_count[i.get("severity", "low")] = sev_count.get(i.get("severity", "low"), 0) + 1
    summary["issues_by_severity"] = sev_count

    # Top failures
    top = sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity"), 3))
    summary["top_issues"] = [
        {"s": i.get("severity"), "n": i.get("node", "")[:30], "d": i.get("description", "")[:80]}
        for i in top[:MAX_TOP_FAILURES]
    ]

    # Fix guide
    fg = data.get("fix_guide", {})
    summary["fix_guide"] = {
        "easy": [{"d": x.get("issue", "")[:80]} for x in fg.get("easy", [])[:MAX_EASY_ITEMS]],
        "medium": [{"d": x.get("issue", "")[:80]} for x in fg.get("medium", [])[:MAX_MEDIUM_ITEMS]],
        "hard": [{"d": x.get("issue", "")[:80]} for x in fg.get("hard", [])[:MAX_HARD_ITEMS or 999]],
    }

    # Delegated items (需要 Agent 2 做语义判断的项)
    delegated = data.get("delegated_to_agent_2", [])
    if delegated:
        summary["delegated"] = delegated[:5]  # 最多 5 条委托项

    return summary


def main():
    parser = argparse.ArgumentParser(description="Token 预算版摘要")
    parser.add_argument("--agent1", help="Agent 1 JSON")
    parser.add_argument("--agent2", help="Agent 2 JSON")
    parser.add_argument("--quiet", action="store_true", help="压缩到最小输出")
    args = parser.parse_args()

    merged = {"merged_verdict": "pass", "total_issues": 0}

    if args.agent1:
        with open(args.agent1) as f:
            a1 = json.load(f)
        s1 = extract_agent1_summary(a1)
        merged["agent1"] = s1
        if s1["verdict"] == "fail":
            merged["merged_verdict"] = "fail"
            merged["total_issues"] += s1.get("issues_by_severity", {}).get("high", 0)

    if args.agent2:
        with open(args.agent2) as f:
            a2 = json.load(f)
        s2 = extract_agent2_summary(a2)
        merged["agent2"] = s2
        if s2["verdict"] == "fail":
            merged["merged_verdict"] = "fail"
            merged["total_issues"] += s2.get("issues_by_severity", {}).get("high", 0)

    if not args.agent1 and not args.agent2:
        print(json.dumps({"error": "需要 --agent1 或 --agent2"}, ensure_ascii=False))
        sys.exit(2)

    # 检查输出长度，如果超过目标则进一步压缩
    output = json.dumps(merged, ensure_ascii=False, indent=None if args.quiet else 2)
    if len(output) > TARGET_CHARS and not args.quiet:
        merged["_truncated"] = f"output {len(output)} chars, target {TARGET_CHARS}"
        merged["_full_output_at"] = [args.agent1, args.agent2]
        output = json.dumps(merged, ensure_ascii=False)
        if len(output) > TARGET_CHARS * 2:
            # 激进压缩: 只保留 verdict + top issues
            minimal = {
                "verdict": merged["merged_verdict"],
                "total_issues": merged["total_issues"],
            }
            if "agent1" in merged:
                minimal["a1"] = {
                    "v": merged["agent1"]["verdict"],
                    "top": merged["agent1"].get("top_issues", [])[:3]
                }
            if "agent2" in merged:
                minimal["a2"] = {
                    "v": merged["agent2"]["verdict"],
                    "top": merged["agent2"].get("top_issues", [])[:3]
                }
            output = json.dumps(minimal, ensure_ascii=False)

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
