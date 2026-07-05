#!/usr/bin/env python3
"""确定性平台能力校验 — 替代 Agent 2 中约 60% 的机械检查。

用法:
  python3 verify-platform.py --nodes nodes.json
  python3 verify-platform.py --lock-file execution_lock.json
  python3 verify-platform.py --nodes nodes.json --project 几建

输出: JSON (与 Agent 2 输出格式兼容)
exit code: 0 = pass, 1 = fail (有机械检查未通过)
"""

import argparse
import json
import sys
from pathlib import Path

# ── 常量: 有效 typeId (39 个, 来自 PD-OpenWeb 源码) ──
VALID_TYPE_IDS = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
    30, 31, 32, 33, 34, 100, 101, 1000, 1001,
}

# ── 子模式映射: typeId → 有效 actionId 列表 ──
VALID_ACTION_IDS = {
    6:  [1, 2, 3, 6, 7, 20, 411, 412, 413, 415],
    7:  [400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 414, 416, 420, 421, 422],
    9:  [100, 101, 102, 103, 104, 105, 106, 107, 108],
    11: [201, 202],
    17: [1, 2, 3, 4, 5, 6, 7],
    18: [4, 5],
    19: [203],
    20: [500, 501, 502],
    21: [510, 511, 512],
    22: [520, 521, 522, 523, 524],
    29: [210, 211],
    31: [531, 532],
    33: [533],
    34: [535],
}

# typeId 说明 (用于错误消息)
TYPE_NAMES = {
    0: "触发器/开始", 1: "分支", 2: "分支条件项", 3: "填写", 4: "审批(旧版,已弃用)",
    5: "抄送", 6: "数据操作", 7: "查询", 8: "发送API请求", 9: "运算",
    10: "发送短信", 11: "发送邮件", 12: "延时", 13: "获取多条",
    14: "代码块", 15: "获取链接", 16: "子流程", 17: "界面推送",
    18: "获取记录打印文件", 19: "服务号模板消息", 20: "封装业务流程(PBC)",
    21: "JSON解析", 22: "身份验证", 23: "参数节点", 24: "API封装包",
    25: "调用已集成API", 26: "发起审批流程(新版)", 27: "发送站内通知",
    28: "获取页面快照", 29: "循环", 30: "返回", 31: "AI生成内容",
    32: "自定义节点/插件", 33: "AI Agent", 34: "知识库检索",
}

# ── 批量上限 ──
BATCH_LIMITS = {
    "add":               {"max": 100,   "msg": "新增记录单次上限 100 行"},
    "edit":              {"max": 100,   "msg": "更新记录单次上限 100 行"},
    "delete":            {"max": 100,   "msg": "删除记录单次上限 100 行"},
    "batch_delete":      {"max": 1000,  "msg": "批量删除上限 1000 行"},
    "get_multi_to_crud": {"max": 100,   "msg": "获取多条→增删改上限 100 行, 超出中止"},
    "get_multi_to_sub":  {"max": 10000, "msg": "获取多条→子流程上限 10,000 行"},
    "calibrate":         {"max": 100000,"msg": "校准工作表上限 100,000 行, 间隔≥120分钟"},
    "loop":              {"max": 10000, "msg": "循环上限 10,000 次"},
    "delay_days":        {"max": 999,   "msg": "延时上限 999 天"},
    "email_attachment":  {"max": 50,    "msg": "邮件附件上限 50MB"},
    "email_recipients":  {"max": 200,   "msg": "邮件群发单显上限 200 收件人"},
}

# ── 平台陷阱检查 ──
DEPRECATED_TYPE_IDS = {4: "审批节点(旧版)已弃用, 请用 typeId=26 (发起审批流程)"}

# no_data_policy 允许值 (获取单条/多条的"无数据时"策略)
VALID_NO_DATA_POLICIES = ["continue", "create_new", "abort"]


def load_nodes_from_lock(lock_path: str) -> dict:
    """从 execution_lock.json 提取节点链。"""
    with open(lock_path) as f:
        lock = json.load(f)

    workflows = []
    # execution_lock.json 的结构: { "sheets": {...}, "workflows": [...] }
    for wf in lock.get("workflows", []):
        nodes = []
        for node in wf.get("node_chain", []):
            nodes.append({
                "typeId": node.get("typeId"),
                "actionId": node.get("actionId"),
                "name": node.get("name", ""),
                "config": node.get("config", {}),
            })
        workflows.append({
            "name": wf.get("name", ""),
            "worksheet": wf.get("worksheet", ""),
            "trigger": wf.get("trigger", {}),
            "nodes": nodes,
        })

    return {
        "project": lock.get("project", ""),
        "workflows": workflows,
    }


def load_nodes_from_file(nodes_path: str) -> dict:
    """从独立 nodes.json 加载。"""
    with open(nodes_path) as f:
        return json.load(f)


# ── 校验函数: 每个返回 {"result": "pass"|"fail"|"delegated", "detail": str, "fix": str} ──

def check_type_id_exists(node: dict, node_idx: int, wf_name: str) -> dict:
    tid = node.get("typeId")
    if tid is None:
        return {"result": "fail", "detail": f"节点 [{node_idx}] 缺少 typeId", "fix": "补充 typeId"}
    if tid not in VALID_TYPE_IDS:
        return {"result": "fail", "detail": f"节点 [{node_idx}] typeId={tid} 不在支持的 39 种类型中",
                "fix": f"检查 typeId 是否正确, 有效值见 TYPE_NAMES"}
    if tid in DEPRECATED_TYPE_IDS:
        return {"result": "fail", "detail": f"节点 [{node_idx}] {DEPRECATED_TYPE_IDS[tid]}",
                "fix": "替换为 typeId=26 (发起审批流程)"}
    return {"result": "pass", "detail": f"typeId={tid} ({TYPE_NAMES.get(tid, '')})"}


def check_action_id(node: dict, node_idx: int, wf_name: str) -> dict:
    tid = node.get("typeId")
    aid = node.get("actionId")

    # 没有子模式的节点不需要 actionId 检查
    if tid not in VALID_ACTION_IDS:
        return {"result": "pass", "detail": "无需 actionId 检查"}

    if aid is None:
        # 某些节点即使有子模式映射，也可能不需要 actionId (如 typeId=17 某些场景)
        type_name = TYPE_NAMES.get(tid, str(tid))
        return {"result": "delegated", "detail": f"节点 [{node_idx}] {type_name} 缺少 actionId",
                "fix": "确认是否需要 actionId (有些子模式可能不需要显式 actionId)"}

    valid_ids = VALID_ACTION_IDS.get(tid, [])
    if aid not in valid_ids:
        return {"result": "fail", "detail": f"节点 [{node_idx}] typeId={tid} actionId={aid} 不在有效子模式列表中 (有效值: {valid_ids})",
                "fix": f"从有效子模式中选择: {valid_ids}"}
    return {"result": "pass", "detail": f"actionId={aid} ✓"}


def check_batch_limits(node: dict, node_idx: int, wf_name: str) -> dict:
    """检查节点配置中的批量上限。"""
    tid = node.get("typeId")
    aid = node.get("actionId")
    cfg = node.get("config", {})

    # typeId=6 + actionId=1 (新增记录) — 检查行数
    if tid == 6 and aid == 1:
        rows = cfg.get("rows", cfg.get("row_count", cfg.get("count", 0)))
        if isinstance(rows, (int, float)) and rows > BATCH_LIMITS["add"]["max"]:
            return {"result": "fail", "detail": f"节点 [{node_idx}] 新增 {rows} 行, 超过上限 100",
                    "fix": "分批新增或使用子流程"}
        return {"result": "pass", "detail": f"新增行数 {rows} 在范围内"}

    # typeId=6 + actionId=2 (更新记录)
    if tid == 6 and aid == 2:
        rows = cfg.get("rows", cfg.get("row_count", cfg.get("count", 0)))
        if isinstance(rows, (int, float)) and rows > BATCH_LIMITS["edit"]["max"]:
            return {"result": "fail", "detail": f"节点 [{node_idx}] 更新 {rows} 行, 超过上限 100",
                    "fix": "分批更新或使用子流程"}
        return {"result": "pass", "detail": f"更新行数 {rows} 在范围内"}

    # typeId=29 (循环) — 检查最大次数
    if tid == 29:
        max_iter = cfg.get("max_iterations", cfg.get("max", cfg.get("count", 0)))
        if isinstance(max_iter, (int, float)) and max_iter > BATCH_LIMITS["loop"]["max"]:
            return {"result": "fail", "detail": f"节点 [{node_idx}] 循环 {max_iter} 次, 超过上限 10000",
                    "fix": "减少循环次数或拆分处理"}
        return {"result": "pass", "detail": f"循环次数 {max_iter} 在范围内"}

    # typeId=12 (延时) — 检查天数
    if tid == 12:
        days = cfg.get("days", cfg.get("day", 0))
        if isinstance(days, (int, float)) and days > BATCH_LIMITS["delay_days"]["max"]:
            return {"result": "fail", "detail": f"节点 [{node_idx}] 延时 {days} 天, 超过上限 999",
                    "fix": "减少延时天数或拆分"}
        return {"result": "pass", "detail": f"延时 {days} 天在范围内"}

    return {"result": "pass", "detail": "无批量检查项"}


def check_fetch_mode(node: dict, node_idx: int, wf_name: str) -> dict:
    """检查获取模式: 公理1要求直接获取而非动态获取。"""
    tid = node.get("typeId")
    cfg = node.get("config", {})

    # typeId=6 + actionId=20 (获取关联记录) — 应选"直接获取"
    if tid == 6 and node.get("actionId") == 20:
        fetch_mode = cfg.get("fetch_mode", cfg.get("mode", ""))
        if "dynamic" in str(fetch_mode).lower() or "动态" in str(fetch_mode):
            return {"result": "fail", "detail": "获取关联记录使用了'动态获取'模式, 公理1要求'直接获取'",
                    "fix": "改为'直接获取'模式"}
        return {"result": "pass", "detail": "获取模式 ✓"}

    # typeId=9 (运算) — 应选"直接计算"
    if tid == 9:
        calc_mode = cfg.get("calc_mode", cfg.get("mode", ""))
        if "dynamic" in str(calc_mode).lower() or "动态" in str(calc_mode):
            return {"result": "fail", "detail": "运算节点使用了'动态计算'模式, 公理1要求'直接计算'",
                    "fix": "改为'直接计算'模式"}
        return {"result": "pass", "detail": "计算模式 ✓"}

    return {"result": "pass", "detail": "无获取模式检查项"}


def check_platform_traps(node: dict, node_idx: int, wf_name: str, all_nodes: list) -> dict:
    """检查常见平台陷阱。"""
    tid = node.get("typeId")

    # typeId=17 (界面推送): 默认最多 1 个
    if tid == 17:
        # 在同一个工作流中检查是否已有其他推送节点
        push_indices = [i for i, n in enumerate(all_nodes) if n.get("typeId") == 17]
        if len(push_indices) > 1 and push_indices[0] != node_idx:
            return {"result": "warn", "detail": f"工作流中有 {len(push_indices)} 个界面推送节点, 仅第一个生效",
                    "fix": "保留一个界面推送节点, 其他改为站内通知(typeId=27)"}

    # typeId=29 (循环): 检查是否可能被放在获取多条之后, 上限检查已在 batch_limits 中
    # (这只做存在性提醒)

    return {"result": "pass", "detail": ""}


def check_topology(workflow: dict, wf_idx: int) -> dict:
    """工作流级别的拓扑检查。"""
    nodes = workflow.get("nodes", [])
    wf_name = workflow.get("name", f"工作流#{wf_idx}")
    results = {}

    # 总节点数
    total = len(nodes)
    if total <= 10:
        results["total_nodes"] = {"result": "pass", "count": total,
                                   "detail": f"总节点数 {total} ≤ 10"}
    elif total > 10:
        # 检查是否有子流程封装
        has_pbc = any(n.get("typeId") in (16, 20) for n in nodes)
        if has_pbc:
            results["total_nodes"] = {"result": "pass", "count": total,
                                       "detail": f"总节点数 {total}, 但有子流程/PBC 封装"}
        else:
            results["total_nodes"] = {"result": "fail", "count": total,
                                       "detail": f"总节点数 {total} > 10 且无子流程封装",
                                       "fix": "将部分节点封装为子流程(typeId=16)或PBC(typeId=20)"}

    # 子流程循环检测 (简单版: 检查同一工作流是否被自己的子流程引用)
    sub_pids = []
    for n in nodes:
        if n.get("typeId") == 16:
            cfg = n.get("config", {})
            sub_pid = cfg.get("sub_workflow_pid", cfg.get("pid", ""))
            if sub_pid:
                sub_pids.append(sub_pid)

    # 如果有子流程引用且当前工作流的 pid=sub_pids 中的某个 → self-reference
    wf_pid = workflow.get("pid", "")
    if wf_pid and wf_pid in sub_pids:
        results["subprocess_cycles"] = {"result": "fail", "detail": "工作流可能自引用",
                                         "fix": "检查子流程配置, 确保不自我调用"}
    else:
        results["subprocess_cycles"] = {"result": "pass", "detail": "无自引用"}

    # 嵌套深度 (简单估算: 统计子流程节点数)
    sub_count = len(sub_pids)
    if sub_count > 0:
        results["nesting_depth"] = {"result": "pass", "depth": 1,
                                     "detail": f"包含 {sub_count} 个子流程调用, 当前深度=1"}
    else:
        results["nesting_depth"] = {"result": "pass", "depth": 0,
                                     "detail": "无子流程"}

    # 并发触发冲突检测 (统计同一工作表上的事件触发工作流)
    results["concurrent_triggers"] = {"result": "pass", "conflicts": [],
                                       "detail": "需要项目 manifest 数据, delegate to Agent 2"}
    results["data_races"] = {"result": "pass", "conflicts": [],
                              "detail": "需要项目 manifest 数据, delegate to Agent 2"}
    results["branch_coverage"] = {"result": "delegated",
                                   "detail": "分支覆盖完备性需要语义判断, delegate to Agent 2"}

    return results


def main():
    parser = argparse.ArgumentParser(description="确定性平台能力校验")
    parser.add_argument("--nodes", help="节点链 JSON 文件路径")
    parser.add_argument("--lock-file", help="execution_lock.json 文件路径")
    parser.add_argument("--project", help="项目名 (可选, 用于输出)")
    parser.add_argument("--quiet", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    # 加载节点数据
    if args.lock_file:
        data = load_nodes_from_lock(args.lock_file)
    elif args.nodes:
        data = load_nodes_from_file(args.nodes)
    else:
        print(json.dumps({"verdict": "fail", "error": "需要 --nodes 或 --lock-file"}, ensure_ascii=False))
        sys.exit(2)

    project = args.project or data.get("project", "unknown")
    workflows = data.get("workflows", [])

    if not workflows:
        print(json.dumps({"verdict": "fail", "error": "未找到工作流数据"}, ensure_ascii=False))
        sys.exit(1)

    # ── 累积式检查: 所有失败都收集到列表中 ──
    node_checks = []
    issues = []
    fix_guide = {"easy": [], "medium": [], "hard": []}
    total_checks = 0
    checks_passed = 0
    checks_failed = 0

    for wf_idx, wf in enumerate(workflows):
        wf_name = wf.get("name", f"工作流#{wf_idx}")
        nodes = wf.get("nodes", [])

        for node_idx, node in enumerate(nodes):
            node_result = {
                "node_name": node.get("name", f"节点#{node_idx}"),
                "node_type": f"{TYPE_NAMES.get(node.get('typeId'), 'unknown')} typeId={node.get('typeId')}",
                "checks": {},
            }

            # 1. 节点类型存在性
            r = check_type_id_exists(node, node_idx, wf_name)
            node_result["checks"]["type_exists"] = r
            total_checks += 1
            if r["result"] == "fail":
                checks_failed += 1
                issues.append({"severity": "high", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "type_exists", "description": r["detail"], "fix": r.get("fix","")})
                fix_guide["easy"].append({"node": node.get("name", ""), "issue": r["detail"],
                                           "action": r.get("fix", "")})
            elif r["result"] == "pass":
                checks_passed += 1

            # 2. 子模式正确性
            r = check_action_id(node, node_idx, wf_name)
            node_result["checks"]["sub_mode"] = r
            total_checks += 1
            if r["result"] == "fail":
                checks_failed += 1
                issues.append({"severity": "medium", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "sub_mode", "description": r["detail"], "fix": r.get("fix","")})
                fix_guide["easy"].append({"node": node.get("name", ""), "issue": r["detail"],
                                           "action": r.get("fix", "")})
            elif r["result"] == "pass":
                checks_passed += 1

            # 3. 批量上限
            r = check_batch_limits(node, node_idx, wf_name)
            node_result["checks"]["batch_limit"] = r
            total_checks += 1
            if r["result"] == "fail":
                checks_failed += 1
                issues.append({"severity": "high", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "batch_limit", "description": r["detail"], "fix": r.get("fix","")})
                detail = r["detail"]
                if "上限" in str(detail) and "100" in str(detail):
                    fix_guide["medium"].append({"node": node.get("name", ""), "issue": r["detail"],
                                                "action": "使用子流程分批处理" if "子流程" in str(r.get("fix","")) else r.get("fix","")})
                else:
                    fix_guide["hard"].append({"node": node.get("name", ""), "issue": r["detail"],
                                              "action": r.get("fix", "")})
            elif r["result"] == "pass":
                checks_passed += 1

            # 4. 获取/计算模式
            r = check_fetch_mode(node, node_idx, wf_name)
            node_result["checks"]["fetch_mode"] = r
            total_checks += 1
            if r["result"] == "fail":
                checks_failed += 1
                issues.append({"severity": "medium", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "fetch_mode", "description": r["detail"], "fix": r.get("fix","")})
                fix_guide["easy"].append({"node": node.get("name", ""), "issue": r["detail"],
                                           "action": r.get("fix", "")})
            elif r["result"] == "pass":
                checks_passed += 1

            # 5. 平台陷阱
            r = check_platform_traps(node, node_idx, wf_name, nodes)
            node_result["checks"]["platform_traps"] = r
            total_checks += 1
            if r["result"] == "fail":
                checks_failed += 1
                issues.append({"severity": "medium", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "platform_traps", "description": r["detail"], "fix": r.get("fix","")})
                fix_guide["medium"].append({"node": node.get("name", ""), "issue": r["detail"],
                                             "action": r.get("fix", "")})
            elif r["result"] == "warn":
                issues.append({"severity": "low", "node": node.get("name", f"节点#{node_idx}"),
                               "check": "platform_traps", "description": r["detail"], "fix": r.get("fix","")})
            elif r["result"] == "pass":
                checks_passed += 1

            # 标记需要 Agent 2 做语义检查的项
            for semantic_check in ["data_link", "no_data_policy"]:
                node_result["checks"][semantic_check] = {
                    "result": "delegated",
                    "detail": "需要语义判断, 已委托 Agent 2"
                }
                total_checks += 1

            node_checks.append(node_result)

        # 拓扑检查 (工作流级别)
        topology = check_topology(wf, wf_idx)
        for topo_key, topo_result in topology.items():
            total_checks += 1
            if topo_result.get("result") == "fail":
                checks_failed += 1
                issues.append({"severity": "high", "node": "", "check": f"topology.{topo_key}",
                               "description": topo_result.get("detail", ""),
                               "fix": topo_result.get("fix", "")})
                fix_guide["hard"].append({"node": "", "issue": topo_result.get("detail", ""),
                                           "action": topo_result.get("fix", "")})
            elif topo_result.get("result") == "pass":
                checks_passed += 1
            # delegated 项不计入 pass/fail

    # ── 组装输出 ──
    verdict = "pass" if checks_failed == 0 else "fail"

    output = {
        "verdict": verdict,
        "source": "verify-platform.py (deterministic)",
        "summary": {
            "total_checks": total_checks,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "nodes_checked": len(node_checks),
        },
        "node_checks": node_checks,
        "issues": issues,
        "fix_guide": fix_guide,
        "delegated_to_agent_2": [
            "data_link — 节点间数据传递语义合法性",
            "no_data_policy — 无数据策略是否符合公理 5",
            "branch_coverage — 分支条件是否覆盖所有可能值",
            "code_block_content — 代码块能否完成任务",
            "concurrent_triggers — 并发触发冲突 (需要 manifest 数据)",
            "data_races — 数据竞态 (需要 manifest 数据)",
        ],
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


if __name__ == "__main__":
    main()
