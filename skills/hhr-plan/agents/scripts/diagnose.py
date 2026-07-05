#!/usr/bin/env python3
"""
Customer Diagnostic Assistant
Maps customer language to system terms, then traces data flow to find root cause.

Usage:
    python3 scripts/diagnose.py <project_root> "<客户问题描述>"

Example:
    python3 scripts/diagnose.py "/path/to/project" "任务流转里点提交品检，入库单的入库明细为什么没数据"

Requires: references/project_context.json (run build_context.py first)
          references/aliases.json (manual alias mappings)
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_aliases(script_dir):
    """Load customer→system alias mappings."""
    alias_path = os.path.join(os.path.dirname(script_dir), "references", "aliases.json")
    if os.path.exists(alias_path):
        return load_json(alias_path)
    return {}


def fuzzy_match(query, candidates, aliases=None):
    """Match customer query to system terms, using aliases first then fuzzy matching."""
    if aliases:
        for category in ["工作表", "工作流", "字段", "操作"]:
            alias_map = aliases.get(category, {})
            for cust_term, sys_term in alias_map.items():
                if cust_term in query:
                    return {"term": sys_term, "customer_term": cust_term, "source": f"aliases.json/{category}"}

    # Fuzzy: longest substring match among candidates
    best = None
    best_len = 0
    for c in candidates:
        if c in query:
            if len(c) > best_len:
                best = c
                best_len = len(c)
    if best and best_len >= 2:
        return {"term": best, "customer_term": best, "source": "fuzzy"}
    return None


def search_workflows(project_root, query, term_mappings, aliases):
    """Find workflows matching a customer query. Uses alias-mapped terms for smarter matching."""
    root = Path(project_root)
    results = []

    # Build search keywords from mapped terms + original query bigrams
    search_terms = set()
    for mapped in term_mappings.values():
        search_terms.add(mapped)
    # Also add 2-char bigrams from query for fuzzy coverage
    for i in range(len(query) - 1):
        bigram = query[i:i+2]
        if not re.match(r'[\u4e00-\u9fff]{2}', bigram):
            continue
        search_terms.add(bigram)
    # Add full query keywords for 工作流 alias matching
    for category in ["工作流"]:
        pass  # workflow aliases handled in term_mappings

    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue
            wf_dir = ws_dir / "工作流"
            if not wf_dir.exists():
                continue
            for wf_sub in sorted(wf_dir.iterdir()):
                if not wf_sub.is_dir():
                    continue
                nc_path = wf_sub / "node_configs.json"
                if not nc_path.exists():
                    continue
                wf_name = wf_sub.name
                try:
                    nodes = load_json(nc_path)
                    match_reason = []
                    # Priority 1: Exact workflow alias match
                    wf_aliases = aliases.get("工作流", {})
                    for cust_term, sys_term in wf_aliases.items():
                        if cust_term in query and sys_term in wf_name:
                            match_reason.append(f"工作流别名匹配: '{cust_term}'→'{sys_term}'")
                            break
                    # Priority 2: Mapped term in workflow name
                    if not match_reason:
                        for term in search_terms:
                            if term in wf_name:
                                match_reason.append(f"工作流名称含'{term}'")
                                break
                    # Priority 3: Check node configs
                    if not match_reason:
                        for n in nodes:
                            if isinstance(n, dict):
                                cfg = n.get("config", "") + n.get("node", "")
                                for term in search_terms:
                                    if len(term) >= 2 and term in cfg:
                                        match_reason.append(f"节点含'{term}'")
                                        break
                            if match_reason:
                                break

                    if match_reason:
                        results.append({
                            "module": mod_dir.name,
                            "worksheet": ws_dir.name,
                            "workflow": wf_name,
                            "node_count": len(nodes),
                            "match_reason": list(set(match_reason)),
                            "nodes": nodes,
                        })
                except:
                    pass

    return results


def trace_data_flow(nodes, target_keywords):
    """Trace how data flows through a workflow, looking for target keywords."""
    flow = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            continue
        node_name = n.get("node", "")
        cfg = n.get("config", "")

        step = {"index": i, "node": node_name[:100]}

        if "按钮触发" in node_name or "发起" in node_name:
            step["type"] = "trigger"
            step["desc"] = "用户操作触发"
        elif "新增记录" in node_name:
            step["type"] = "create"
            for kw in target_keywords:
                if kw in cfg:
                    step["creates"] = kw
            # Find what worksheet
            m = re.search(r'选择工作表(.+?)新增', cfg)
            if m:
                step["target_ws"] = m.group(1).strip()
        elif "更新记录" in node_name:
            step["type"] = "update"
        elif "获取关联记录" in node_name or "查询工作表" in node_name:
            step["type"] = "fetch"
            if "多条" in cfg:
                step["detail"] = "批量获取记录（作为后续子流程的数据源）"
            else:
                step["detail"] = "获取单条关联记录"
        elif "子流程" in node_name:
            step["type"] = "subprocess"
            m = re.search(r'选择已有流程(.+?)执行完毕', cfg)
            if m:
                step["subprocess_name"] = m.group(1).strip()
            # Check params
            params = re.findall(r'将参数\[\w+\](\w+)设为(.+?)(?:添加参数|保存)', cfg)
            if params:
                step["params"] = [{"name": p[0], "value": p[1].strip()[:60]} for p in params]
        elif "分支" in node_name:
            step["type"] = "branch"
            step["condition"] = node_name.replace("分支", "").strip()
        elif "抄送" in node_name or "通知" in cfg[:50]:
            step["type"] = "notify"
        elif "同意" in node_name:
            step["type"] = "pass"
        elif "拒绝" in node_name:
            step["type"] = "reject"
        else:
            step["type"] = "other"

        flow.append(step)

    return flow


def diagnose(project_root, query, aliases):
    """Main diagnostic logic."""
    lines = []

    # Step 1: Terminology mapping
    lines.append("## 术语映射\n")
    ctx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "references", "project_context.json")

    ctx = {}
    if os.path.exists(ctx_path):
        ctx = load_json(ctx_path)

    ws_names = list(ctx.get("worksheets", {}).keys())

    lines.append(f"客户原话: {query}\n")
    lines.append("| 客户说的 | 系统名称 | 来源 |")
    lines.append("|---------|---------|------|")

    mappings = {}
    # First pass: alias matching (prioritize exact alias matches)
    for category in ["工作表", "工作流", "字段", "操作"]:
        alias_map = aliases.get(category, {})
        for cust_term, sys_term in alias_map.items():
            if cust_term in query and cust_term not in mappings:
                lines.append(f"| {cust_term} | {sys_term} | aliases.json/{category} |")
                mappings[cust_term] = sys_term

    # Second pass: fuzzy match for terms NOT covered by aliases
    for term in re.findall(r'[\u4e00-\u9fff]{2,}', query):
        if term not in mappings:
            match = fuzzy_match(term, ws_names)
            if match and match["term"] not in mappings.values():
                lines.append(f"| {match['customer_term']} | {match['term']} | {match['source']} |")
                mappings[term] = match["term"]

    lines.append("")

    # Step 2: Find relevant workflows
    lines.append("## 工作流追踪\n")
    wf_results = search_workflows(project_root, query, mappings, aliases)

    if not wf_results:
        lines.append("未找到相关的工作流配置。\n")
        return "\n".join(lines)

    # Find the most relevant workflow
    # Score: alias match = +100, name match = +10, node match = +1
    def wf_score(wf):
        score = 0
        for reason in wf["match_reason"]:
            if "别名匹配" in reason:
                score += 100
            elif "工作流名称含" in reason:
                score += 10
            else:
                score += 1
        return score
    wf_results.sort(key=wf_score, reverse=True)
    best_wf = wf_results[0]

    lines.append(f"匹配到工作流: **{best_wf['worksheet']} → {best_wf['workflow']}**")
    lines.append(f"匹配原因: {', '.join(best_wf['match_reason'])}\n")

    # Step 3: Trace data flow
    lines.append("## 数据流追踪\n")

    # Extract target keywords from query (what the customer is asking about)
    target_kws = [kw for kw in query if len(kw) >= 2 and any(
        kw in best_wf['workflow'] or
        any(kw in (n.get('config','') + n.get('node','')) for n in best_wf['nodes'] if isinstance(n, dict))
    )]

    flow = trace_data_flow(best_wf["nodes"], list(mappings.values()))

    for step in flow:
        i = step["index"]
        stype = step["type"]

        if stype == "trigger":
            lines.append(f"{i+1}. **触发**: {step['desc']}")
        elif stype == "branch":
            lines.append(f"\n> 如果**{step['condition']}**:\n")
        elif stype == "create":
            ws = step.get("target_ws", step.get("creates", "记录"))
            lines.append(f"{i+1}. **创建** {ws} ← 这里生成了客户说的记录")
        elif stype == "fetch":
            detail = step.get("detail", "获取数据")
            lines.append(f"{i+1}. **获取数据**: {detail} ← **关键节点**")
        elif stype == "subprocess":
            name = step.get("subprocess_name", "子流程")
            lines.append(f"{i+1}. **子流程** → {name}")
            params = step.get("params", [])
            if params:
                for p in params:
                    lines.append(f"   - 传参: `{p['name']}` = {p['value']}")
        elif stype == "pass":
            lines.append(f"   → ✅ 通过")
        elif stype == "reject":
            lines.append(f"   → ❌ 退回")
        elif stype == "notify":
            lines.append(f"{i+1}. **通知** — 完成后通知相关人员")

    lines.append("")

    # Step 4: Root cause analysis
    lines.append("## 根因分析\n")

    # Find potential failure points
    fetch_nodes = [s for s in flow if s["type"] == "fetch"]
    subproc_nodes = [s for s in flow if s["type"] == "subprocess"]
    create_nodes = [s for s in flow if s["type"] == "create"]

    causes = []

    # Check 1: fetch nodes before subprocess
    for fn in fetch_nodes:
        # Find what comes after this fetch
        idx = flow.index(fn)
        if idx + 1 < len(flow) and flow[idx + 1]["type"] == "subprocess":
            causes.append({
                "probability": "高",
                "cause": f"Node {fn['index']+1} 获取数据 → 如果源数据为空，后续子流程没有数据源，会导致子记录不生成",
                "check": "检查源工作表上对应的关联字段是否已填写、关联的记录是否符合筛选条件",
            })

    # Check 2: subprocess failure tolerance
    for sn in subproc_nodes:
        causes.append({
            "probability": "中",
            "cause": f"子流程 {sn.get('subprocess_name', '')} 如果执行失败，按'中止时继续下一条'规则会跳过，不报错",
            "check": f"检查子流程「{sn.get('subprocess_name', '')}」是否已启用（开启状态）",
        })

    if not causes:
        causes.append({
            "probability": "待确认",
            "cause": "未在数据流中检测到明显的容错跳过节点，需要人工检查工作流中每个节点的配置",
            "check": "逐一检查工作流节点的筛选条件和容错设置",
        })

    for i, c in enumerate(causes):
        lines.append(f"### 可能原因 {i+1}（概率: {c['probability']}）\n")
        lines.append(f"**{c['cause']}**\n")
        lines.append(f"> 请检查: {c['check']}\n")

    # Step 5: Impact analysis
    lines.append("## 影响面分析\n")
    lines.append("此问题修复或变更可能影响以下模块：\n")

    # Find related workflows that share the same subprocess or fetch targets
    impacts = set()
    for node in best_wf["nodes"]:
        if not isinstance(node, dict):
            continue
        cfg = node.get("config", "")
        # Subprocess references
        sp_matches = re.findall(r'选择已有流程(.+?)执行完毕', cfg)
        for sp_name in sp_matches:
            impacts.add(f"子流程「{sp_name.strip()}」被本工作流调用，修改它会影响所有调用方")

        # Worksheet references (新增/更新节点)
        ws_matches = re.findall(r'选择工作表(.+?)(?:新增|更新)', cfg)
        for ws_name in ws_matches:
            clean = ws_name.strip()[:30]  # Truncate OCR garbage
            # Find other workflows that also reference this worksheet
            count = 0
            for wf_result in wf_results:
                if wf_result["workflow"] != best_wf["workflow"]:
                    for n in wf_result.get("nodes", []):
                        if isinstance(n, dict) and clean in n.get("config", ""):
                            count += 1
                            break
            if count > 0:
                impacts.add(f"工作表「{clean}」也被 {count} 个其他工作流使用，修改字段需同步检查")

    if impacts:
        for imp in sorted(impacts)[:10]:  # Limit to top 10
            lines.append(f"- {imp}")
        if len(impacts) > 10:
            lines.append(f"- ... 以及其他 {len(impacts) - 10} 项影响")
    else:
        lines.append("- 此问题仅影响当前工作流，未检测到其他工作流或工作表依赖此节点。")
    lines.append("")

    return "\n".join(lines)


def save_issue(project_name, query, result):
    """保存诊断记录到 _issues/YYYY-MM-DD/ 目录"""
    from datetime import datetime
    base_dir = os.path.expanduser(f"~/Documents/workflow-output/{project_name}/_issues")
    date_str = datetime.now().strftime("%Y-%m-%d")
    issue_dir = os.path.join(base_dir, date_str)
    os.makedirs(issue_dir, exist_ok=True)

    # 用问题前 30 字做文件名
    safe_name = query[:30].replace("/", "-").replace(" ", "_")
    filepath = os.path.join(issue_dir, f"{safe_name}.md")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"""# {query}

> 记录时间: {timestamp}
> 项目: {project_name}

{result}

---
*此记录由 diagnose.py 自动保存*
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 diagnose.py <project_name> \"<客户问题>\"")
        print("Example: python3 diagnose.py 几建 \"入库单明细为什么没数据\"")
        sys.exit(1)

    project_name = sys.argv[1]
    query = sys.argv[2]

    # Read from unified directory
    base_dir = os.path.expanduser("~/Documents/workflow-output")
    project_dir = os.path.join(base_dir, project_name)
    extracted_dir = os.path.join(project_dir, "_extracted")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    aliases_file = os.path.join(project_dir, "aliases.json")
    if os.path.exists(aliases_file):
        with open(aliases_file) as f:
            aliases = json.load(f)
    else:
        aliases = load_aliases(script_dir)

    result = diagnose(extracted_dir, query, aliases)
    print(result)

    # 自动保存到 _issues
    issue_path = save_issue(project_name, query, result)
    print(f"\n诊断记录已保存: {issue_path}")


if __name__ == "__main__":
    main()
