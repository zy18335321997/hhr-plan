#!/usr/bin/env python3
"""
Generate _node_data.json with enriched trigger types + node-level summary.

Data sources (priority order):
  1. _all_workflows.json (Browser extraction with trigger names + node details)
  2. business-flow-manifest.json (fallback for older extraction)

Output _node_data.json:
  {pid: {name, worksheet, trigger, node_count, reads, writes, nodes_summary}}

Also outputs _node_details.json for axiom audits:
  {pid: {trigger_name, trigger_type, nodes: [{typeId, typeName, name}]}}

Usage:
    python3 scripts/generate_node_data.py --all
    python3 scripts/generate_node_data.py 尚策
    python3 scripts/generate_node_data.py --force 尚策   # overwrite existing
"""

import json
import os
import sys
from collections import Counter

BASE = os.path.expanduser("~/Documents/workflow-output")
field_map = None  # loaded lazily by generate_from_* functions

TRIGGER_NAME_MAP = {
    "按钮触发": "自定义动作",
    "工作表事件触发": "工作表事件",
    "子流程": "子流程",
    "发起审批": "审批流程",
    "定时触发": "定时触发",
    "封装业务流程": "封装业务流程",
    "按日期字段触发": "定时触发",
    "循环": "子流程",
    "流程发起节点": "审批流程",
}

TRIGGER_ID_MAP = {
    "1": "新增记录触发",
    "2": "编辑记录触发",
    "3": "删除记录触发",
    "4": "编辑记录触发",
}

# Internal API typeId → Chinese display name.
# The internal workflow data API uses a different numbering scheme than the
# frontend NODE_TYPE enum in pd-openweb.  This map is cross-referenced against
# the source: src/pages/workflow/WorkflowSettings/enum.js (NODE_TYPE / SUPPORT_HREF).
NODE_TYPE_NAME = {
    0:  "开始",
    1:  "分支",
    2:  "分支条件",
    3:  "填写",           # form fill node (workflow form step)
    4:  "审批",
    5:  "抄送",
    6:  None,            # CRUD → resolved by node name below
    7:  "查询",
    8:  "发送自定义请求",  # custom webhook/API (different from typeId=13)
    9:  "延时",
    13: "发送API请求",    # internal API id=13, frontend WEBHOOK=8
    14: "代码块",         # JavaScript / Python code block
    15: "获取链接",       # get record share link
    16: "子流程",
    17: "界面推送",
    18: "获取记录打印文件", # get record print file
    20: "封装业务流程",
    26: "发起审批",
    27: "站内通知",
    29: "满足条件时循环",   # loop while condition is met
    30: "中止流程",        # terminate workflow
    100:"系统",
    1000:"系统(获取单条)",
    1001:"系统(获取多条)",
}

# Node-level name refinements for typeId=6 (CRUD/ACTION).
# The internal API uses the node's `name` field for the concrete action.
ACTION_NODE_NAMES = {
    "新增记录": "新增记录",
    "更新记录": "更新记录",
    "删除记录": "删除记录",
    "获取关联记录": "获取关联记录",
    "获取多条关联记录": "获取多条关联记录",
    "查询工作表": "查询工作表",
    "发起审批": "发起审批流程",
    "自定义动作": "自定义动作",
}


def _node_display_name(type_id, type_name, node_name):
    """Return the Chinese display name for a workflow node.

    Falls back through: NODE_TYPE_NAME → ACTION_NODE_NAMES → node_name → type_name.
    """
    base = NODE_TYPE_NAME.get(type_id)
    if base is not None:
        return base
    # typeId=6: resolve via node name
    if type_id == 6:
        return ACTION_NODE_NAMES.get(node_name, node_name or "数据操作")
    # typeId known but not in map → use the raw type name
    if type_name and type_name not in ("Unknown(100)", ""):
        return type_name
    return f"未知节点(typeId={type_id})"


def generate(project_name, force=False):
    proj_dir = os.path.join(BASE, project_name)
    node_data_path = os.path.join(proj_dir, "_node_data.json")
    all_wf_path = os.path.join(proj_dir, "_all_workflows.json")
    manifest_path = os.path.join(proj_dir, "business-flow-manifest.json")

    # Check existing _node_data.json
    needs_regen = force or not os.path.exists(node_data_path)
    if not needs_regen:
        nd = json.load(open(node_data_path, encoding="utf-8"))
        enriched = sum(1 for v in nd.values() if v.get("trigger") not in ("", "unknown"))
        # Also check if node_chain is populated (not just manifest skeleton)
        has_node_chain = sum(1 for v in nd.values() if v.get("node_chain"))
        if enriched > len(nd) * 0.5:
            # Check for worksheet mismatches against API data
            api_worksheets = _load_api_worksheets(project_name, proj_dir)
            if api_worksheets:
                mismatches = 0
                for pid, info in nd.items():
                    api_ws = api_worksheets.get(pid)
                    if api_ws and api_ws != info.get("worksheet", ""):
                        mismatches += 1
                if mismatches > 0:
                    print(f"  {project_name}: {mismatches} worksheet mismatches detected, forcing regeneration")
                    needs_regen = True
                elif has_node_chain < len(nd) * 0.3:
                    print(f"  {project_name}: enriched but node_chain missing ({has_node_chain}/{len(nd)}), forcing regeneration")
                    needs_regen = True
                else:
                    print(f"  {project_name}: already enriched ({enriched}/{len(nd)} have trigger types), worksheet names verified")
                    return False
            elif has_node_chain < len(nd) * 0.3:
                print(f"  {project_name}: enriched but node_chain missing ({has_node_chain}/{len(nd)}), forcing regeneration")
                needs_regen = True
            else:
                print(f"  {project_name}: already enriched ({enriched}/{len(nd)} have trigger types)")
                return False

    # ── Source 1: _all_workflows.json (Browser extraction, full) ──
    if os.path.exists(all_wf_path):
        return generate_from_browser(project_name, all_wf_path, manifest_path, node_data_path, force)

    # ── Source 2: nodes.json only (Browser extraction, node-level) ──
    nodes_json_path = os.path.join(proj_dir, "nodes.json")
    if os.path.exists(nodes_json_path):
        return generate_from_nodes_json(project_name, nodes_json_path, manifest_path, node_data_path)

    # ── Source 2.5: PID directories (workflow-analyzer Browser extraction) ──
    pid_dirs = _discover_pid_dirs(proj_dir)
    if pid_dirs:
        return generate_from_pid_dirs(project_name, pid_dirs, manifest_path, node_data_path)

    # ── Source 3: manifest fallback ──
    if os.path.exists(manifest_path):
        return generate_from_manifest(project_name, manifest_path, node_data_path)

    print(f"  {project_name}: no data source found")
    return False


ACTION_ID_NAME = {
    "1":  "新增记录",
    "2":  "更新记录",
    "3":  "删除记录",
    "4":  "创建文件",
    "5":  "创建记录",
    "6":  "刷新单条数据",
    "7":  "退款",
    "20": "获取关联记录",
    "21": "批量新增",
    "100":"数值公式",
    "101":"日期公式",
    "102":"JavaScript",
    "103":"Python",
    "406":"查询工作表",
    "407":"从多条获取单条",
    "411":"批量操作",
    "412":"批量更新",
    "413":"批量删除",
    "420":"记录链接获取",
    "421":"查一条并更新",
    "422":"查一条并删除",
    "500":"PBC",
}

APPROVAL_ACCOUNT_TYPES = {1: "人员", 2: "角色", 6: "字段", 7: "文本", 8: "部门", 9: "职位", 10: "组织角色"}

CONDITION_NAMES = {
    "1": "是其中一个", "2": "不是任何一个",
    "3": "包含", "4": "不包含",
    "5": "开头是", "6": "结尾是",
    "7": "不为空", "8": "为空",
    "9": "等于", "10": "不等于",
    "11": "小于", "12": "大于",
    "13": "小于等于", "14": "大于等于",
    "15": "在范围内", "16": "不在范围内",
    "17": "早于", "18": "晚于",
    "29": "是(选中)", "30": "否(不选中)",
    "31": "不为空", "32": "为空",
    "35": "属于", "36": "不属于",
    "39": "晚于", "41": "早于",
    "43": "同时包含",
}


def _translate_condition(cond):
    """Translate a single operateCondition item to readable Chinese.

    Example input:
      {"conditionId":"11", "filedValue":"剩余待发数量", "conditionValues":[{"value":"0"}], "filedTypeId":6}
    Output:
      "剩余待发数量 小于 0"
    """
    if not isinstance(cond, dict):
        return str(cond)
    cid = str(cond.get("conditionId", ""))
    op = CONDITION_NAMES.get(cid, f"条件{cid}")
    field = cond.get("filedValue", "") or cond.get("filedId", "")
    vals = cond.get("conditionValues", []) or []
    if not vals:
        return f"{field} {op}"
    # Collect values
    val_strs = []
    for v in vals:
        vv = v.get("value", "") or v.get("controlName", "") or ""
        if vv:
            val_strs.append(str(vv))
    val_part = ", ".join(val_strs) if val_strs else "?"
    return f"{field} {op} {val_part}"


def _translate_conditions(conditions):
    """Translate conditions array (possibly nested) to list of readable strings."""
    if not conditions:
        return []
    result = []
    for group in conditions:
        if isinstance(group, list):
            # AND group
            parts = []
            for cond in group:
                if isinstance(cond, dict):
                    parts.append(_translate_condition(cond))
            if parts:
                result.append(" 且 ".join(parts))
        elif isinstance(group, dict):
            result.append(_translate_condition(group))
    return result


def _build_node_chain_from_detail(wf_nodes):
    """Build an ordered node chain from nodes.json detail data.

    Uses BFS from the trigger node (typeId=0), following nextId for linear
    segments and flowIds for branch segments. Branch nodes are explored
    depth-first per flow path.

    Returns (node_chain, axiom_stats).
    """
    node_map = {}
    for nid, n in wf_nodes.items():
        if isinstance(n, dict):
            node_map[nid] = n

    if not node_map:
        return [], {"create_total": 0, "create_backfill": 0, "query_total": 0, "query_continue": 0}

    # Find trigger node (typeId=0)
    start_id = None
    for nid, n in node_map.items():
        if n.get("typeId") == 0:
            start_id = nid
            break
    if not start_id:
        # Fallback: node with no prveId
        for nid, n in node_map.items():
            prve = n.get("prveId", "")
            if not prve or prve not in node_map:
                start_id = nid
                break
    if not start_id:
        start_id = next(iter(node_map))

    # BFS to order nodes
    visited = set()
    chain = []
    queue = [start_id]

    while queue:
        nid = queue.pop(0)
        if nid in visited or nid not in node_map:
            continue
        visited.add(nid)
        n = node_map[nid]
        chain.append(_summarize_node(n))

        # Enqueue next nodes
        nxt = n.get("nextId", "")
        if nxt and nxt in node_map and nxt not in visited:
            queue.append(nxt)

        # Enqueue branch flows
        flow_ids = n.get("flowIds", []) or []
        for fid in flow_ids:
            if fid and fid in node_map and fid not in visited:
                queue.append(fid)

    # Orphan nodes not reached by BFS
    for nid in node_map:
        if nid not in visited:
            chain.append(_summarize_node(node_map[nid], orphan=True))

    # Axiom stats
    stats = {"create_total": 0, "create_backfill": 0, "query_total": 0, "query_continue": 0}
    for n in node_map.values():
        if not isinstance(n, dict):
            continue
        tid = n.get("typeId", 0)
        nd_name = n.get("name", "")
        if tid == 6 and nd_name == "新增记录":
            stats["create_total"] += 1
            fields = n.get("fields", []) or []
            types = Counter(f.get("type", 0) for f in fields)
            has_dynamic = types.get(27, 0) > 0
            if has_dynamic and len(fields) >= 2:
                stats["create_backfill"] += 1
            err = n.get("errorFields", []) or []
            if err:
                stats["query_continue"] += 1
        if tid == 6:
            err = n.get("errorFields", []) or []
            if err:
                stats["query_continue"] += 1
        if tid == 7:
            stats["query_total"] += 1
            abort = n.get("abortOnEmpty", True)
            err = n.get("errorFields", []) or []
            if not abort or err:
                stats["query_continue"] += 1

    return chain, stats


def _summarize_node(n, orphan=False):
    """Extract detailed configuration from a workflow node.

    Different node types have completely different configuration schemas
    (cross-referenced against pd-openweb Detail components).
    """
    tid = n.get("typeId", 0)
    tname = n.get("typeName", "")
    nd_name = n.get("name", "")
    display = _node_display_name(tid, tname, nd_name)
    entry = {"typeId": tid, "typeName": display, "name": nd_name}
    if orphan:
        entry["_orphan"] = True

    # ===== typeId=6: CRUD / ACTION nodes =====
    # Sub-modes via actionId: 1=新增, 2=更新, 3=删除, 20=获取关联, 21=批量新增, ...
    if tid == 6:
        aid = str(n.get("actionId", 0) or 0)
        mode = ACTION_ID_NAME.get(aid, f"操作(aid={aid})" if aid != "0" else "")
        entry["mode"] = mode

        target = n.get("selectNodeName", "") or n.get("appName", "") or n.get("sourceEntityName", "")
        if target:
            entry["target"] = target

        # Field mappings: each field maps target_col ← source_value
        fields = n.get("fields", []) or []
        if fields:
            mapped = []
            for f in fields:
                fid = f.get("fieldId", "") or f.get("controlId", "")
                fname = f.get("fieldName", "") or f.get("controlName", "") or ""
                # Resolve from field_map if available
                if not fname and fid and field_map:
                    fmeta = field_map.get(fid, {})
                    if isinstance(fmeta, dict):
                        fname = fmeta.get("name", "") or fmeta.get("controlName", "")
                    elif isinstance(fmeta, str):
                        fname = fmeta
                if not fname:
                    fname = fid  # fallback to ID
                ftype = f.get("type", 0)
                if ftype == 2:
                    val = f.get("enumDefault", "") or f.get("value", "") or "(固定值)"
                    mapped.append(f"{fname}={val}" if fname and val else str(val))
                elif ftype == 27:
                    mapped.append(f"{fname}=<动态引用>")
                elif ftype == 0:
                    mapped.append(f"{fname}=<空>")
                else:
                    mapped.append(fname)
            if mapped:
                entry["fields"] = mapped

        # Error handling
        err = n.get("errorFields", []) or []
        entry["onError"] = "继续执行" if err else "中止"
        if n.get("isException"):
            entry["isException"] = True

    # ===== typeId=7: Query / SEARCH nodes =====
    elif tid == 7:
        aid = str(n.get("actionId", 0) or 0)
        mode = ACTION_ID_NAME.get(aid, f"查询(aid={aid})" if aid != "0" else "")
        entry["mode"] = mode

        # Target worksheet or source node
        app_name = n.get("appName", "")
        sel_name = n.get("selectNodeName", "")
        if app_name:
            entry["target"] = app_name
        elif sel_name:
            entry["source"] = sel_name

        # Execute type: 2=仅查询, 1=未查到则新增
        exec_type = n.get("executeType", 2)
        entry["executeType"] = "未查到则新增" if exec_type == 1 else "仅查询"

        # Filter conditions (operateCondition)
        conditions = n.get("operateCondition", []) or []
        if conditions:
            translated = _translate_conditions(conditions)
            if translated:
                entry["conditions"] = translated

        # Error handling
        entry["onEmpty"] = "继续执行" if n.get("isException") else "中止"

    # ===== typeId=4: Approval nodes =====
    elif tid == 4:
        accounts = n.get("accounts", []) or []
        approvers = []
        for a in accounts:
            atype = a.get("type", 0)
            label = APPROVAL_ACCOUNT_TYPES.get(atype, f"type{atype}")
            name = a.get("roleName", "") or a.get("entityName", "") or ""
            if name:
                approvers.append(f"{label}:{name}")
            else:
                approvers.append(label)
        entry["approvers"] = approvers

        if n.get("countersign"):
            ctype = n.get("countersignType", 3)
            entry["mode"] = "会签" if ctype == 3 else "或签"
        else:
            entry["mode"] = "或签"

        if n.get("isCallBack"):
            entry["canReturn"] = True

    # ===== typeId=26: Approval Process (发起审批) =====
    elif tid == 26:
        sel = n.get("selectNodeName", "")
        if sel:
            entry["target"] = sel

    # ===== typeId=1: Branch =====
    elif tid == 1:
        flow_ids = n.get("flowIds", []) or []
        entry["branches"] = len(flow_ids)

    # ===== typeId=2: Branch Item (分支条件) =====
    elif tid == 2:
        conditions = n.get("operateCondition", []) or []
        if conditions:
            translated = _translate_conditions(conditions)
            if translated:
                entry["conditions"] = translated

    # ===== typeId=9: Delay =====
    elif tid == 9:
        exec_time = n.get("executeTime", "")
        if exec_time:
            entry["delay"] = exec_time

    # ===== typeId=0: Trigger (开始) =====
    elif tid == 0:
        trigger_id = n.get("triggerId", "")
        app_name = n.get("appName", "")
        if app_name:
            entry["worksheet"] = app_name
        if trigger_id:
            TID_MAP = {"1": "新增记录时", "2": "新增或编辑时", "3": "删除记录时", "4": "编辑记录时"}
            entry["trigger"] = TID_MAP.get(str(trigger_id), f"triggerId={trigger_id}")

    # ===== typeId=13: Webhook / API request =====
    elif tid == 13:
        method = n.get("method", "")
        url = n.get("url", "") or ""
        if method or url:
            entry["api"] = f"{method} {url}" if method else url

    # ===== typeId=16: Sub-process =====
    elif tid == 16:
        exec_type = n.get("executeType", "")
        if str(exec_type) == "1":
            entry["executeType"] = "逐条执行"

    # ===== typeId=17: Push / 界面推送 =====
    elif tid == 17:
        push_type = n.get("pushType", "")
        PUSH_NAMES = {"1": "弹出提示", "2": "打开记录创建", "3": "打开详情", "4": "打开视图", "5": "打开自定义页面", "6": "打开链接", "7": "卡片通知", "8": "声音播放"}
        if push_type:
            entry["push"] = PUSH_NAMES.get(str(push_type), f"pushType={push_type}")

    # ===== typeId=100: System nodes =====
    elif tid in (100, 1000, 1001):
        entry["systemNode"] = True

    return entry


def generate_from_browser(project_name, all_wf_path, manifest_path, node_data_path, force):
    awf = json.load(open(all_wf_path, encoding="utf-8"))
    wfs = awf.get("workflows", [])
    if not wfs:
        wfs = awf if isinstance(awf, list) else []

    # Try to load nodes.json for field-level detail
    nodes_json_path = os.path.join(BASE, project_name, "nodes.json")
    nodes_detail = {}
    if os.path.exists(nodes_json_path):
        nodes_detail = json.load(open(nodes_json_path, encoding="utf-8"))

    # Load fieldId→fieldName map (from inject_all.js output)
    field_map_path = os.path.join(BASE, project_name, "_field_map.json")
    field_map = {}
    if os.path.exists(field_map_path):
        fm = json.load(open(field_map_path, encoding="utf-8"))
        field_map = fm.get("fieldMap", fm)

    # Build manifest r/w lookup by PID
    manifest_rw = {}
    if os.path.exists(manifest_path):
        mf = json.load(open(manifest_path, encoding="utf-8"))
        for sheet, wf_list in mf.get("tables", {}).items():
            for wf in wf_list:
                pid = wf.get("pid", "")
                manifest_rw[pid] = {
                    "reads": wf.get("r", []) or [],
                    "writes": wf.get("w", []) or [],
                }

    node_data = {}
    node_details = {}
    trigger_stats = Counter()

    # Axiom stats
    axiom1_backfill = 0      # create nodes with owner/parent fields
    axiom1_total_create = 0
    axiom5_continue = 0       # query nodes set to continue on empty
    axiom5_total_query = 0

    for wf in wfs:
        pid = wf.get("processId", "")
        if not pid:
            continue

        # Trigger type from triggerName
        raw_trigger = wf.get("triggerName", "") or wf.get("selectNodeName", "")
        trigger = TRIGGER_NAME_MAP.get(raw_trigger, raw_trigger or "unknown")
        trigger_id = str(wf.get("triggerId", ""))
        if trigger == "工作表事件":
            trigger += f" ({TRIGGER_ID_MAP.get(trigger_id, trigger_id)})"

        trigger_stats[trigger] += 1

        # ── Build node chain from nodes.json (full detail) or _all_workflows.json (basic) ──
        wf_nodes_detail = nodes_detail.get(pid, {})
        has_detail = isinstance(wf_nodes_detail, dict) and len(wf_nodes_detail) > 0

        if has_detail:
            # nodes.json has full detail (fields, accounts, prveId/nextId, conditions)
            node_chain, axiom_delta = _build_node_chain_from_detail(wf_nodes_detail)
            axiom1_total_create += axiom_delta["create_total"]
            axiom1_backfill += axiom_delta["create_backfill"]
            axiom5_total_query += axiom_delta["query_total"]
            axiom5_continue += axiom_delta["query_continue"]
            nodes = list(wf_nodes_detail.values())
        else:
            # Fallback: basic info from _all_workflows.json
            nodes = wf.get("nodes", [])
            node_chain = []
            for n in nodes:
                tid = n.get("typeId", 0)
                tname = n.get("typeName", "")
                nd_name = n.get("name", "")
                node_chain.append({
                    "typeId": tid,
                    "typeName": _node_display_name(tid, tname, nd_name),
                    "name": nd_name,
                })

        # ── Summary counts from node chain ──
        create_nodes = update_nodes = query_nodes = approval_nodes = 0
        for nc in node_chain:
            tname = nc.get("typeName", "")
            if tname == "新增记录":
                create_nodes += 1
            elif tname == "更新记录":
                update_nodes += 1
            elif tname == "查询":
                query_nodes += 1
            elif tname in ("审批", "发起审批"):
                approval_nodes += 1

        # r/w from manifest
        rw = manifest_rw.get(pid, {})
        reads_list = sorted(rw.get("reads", []))
        writes_list = sorted(rw.get("writes", []))

        node_data[pid] = {
            "name": wf.get("name", ""),
            "worksheet": wf.get("worksheetName", ""),
            "trigger": trigger,
            "node_count": wf.get("nodeCount", len(node_chain)),
            "reads": reads_list,
            "writes": writes_list,
            "nodes_summary": {
                "create": create_nodes,
                "update": update_nodes,
                "query": query_nodes,
                "approval": approval_nodes,
            },
            "node_chain": node_chain,
        }

        node_details[pid] = {
            "name": wf.get("name", ""),
            "worksheet": wf.get("worksheetName", ""),
            "trigger": trigger,
            "raw_trigger": raw_trigger,
            "node_count": len(node_chain),
            "nodes": node_chain,
        }

    # ── Axiom audit summary ──
    axiom1_score = f"{axiom1_backfill}/{axiom1_total_create}" if axiom1_total_create > 0 else "N/A"
    axiom5_score = f"{axiom5_continue}/{axiom5_total_query}" if axiom5_total_query > 0 else "N/A"
    print(f"    公理1(回写): {axiom1_score} create节点有拥有者+父引用")
    print(f"    公理5(降级): {axiom5_score} query节点配置了errorFields")

    with open(node_data_path, "w", encoding="utf-8") as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)

    audit_path = os.path.join(BASE, project_name, "_axiom_audit.json")
    audit = {
        "project": project_name,
        "axiom1_backfill": {"total": axiom1_total_create, "with_backfill": axiom1_backfill},
        "axiom5_degradation": {"total": axiom5_total_query, "with_errorfields": axiom5_continue},
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    # Save node_details for axiom audits
    details_path = os.path.join(BASE, project_name, "_node_details.json")
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(node_details, f, ensure_ascii=False, indent=2)

    print(f"  {project_name}: enriched {len(node_data)} workflows from browser data")
    print(f"    Triggers: {dict(trigger_stats.most_common())}")
    return True


def generate_from_nodes_json(project_name, nodes_json_path, manifest_path, node_data_path):
    """Extract from nodes.json only (no _all_workflows.json)."""
    nodes_detail = json.load(open(nodes_json_path, encoding="utf-8"))

    # Build manifest r/w + name lookup
    manifest_rw = {}
    pid_to_name = {}
    if os.path.exists(manifest_path):
        mf = json.load(open(manifest_path, encoding="utf-8"))
        for sheet, wf_list in mf.get("tables", {}).items():
            for wf in wf_list:
                pid = wf.get("pid", "")
                manifest_rw[pid] = {
                    "reads": wf.get("r", []) or [],
                    "writes": wf.get("w", []) or [],
                }
                if wf.get("wf"):
                    pid_to_name[pid] = wf["wf"]

    node_data = {}
    trigger_stats = Counter()
    axiom1_total = axiom1_backfill = 0
    axiom5_total = axiom5_ok = 0

    for wf_pid, wf_nodes in nodes_detail.items():
        if not isinstance(wf_nodes, dict):
            continue

        # Find trigger node and accumulate node stats
        trigger_name = "unknown"
        worksheet = ""
        create_nodes = update_nodes = query_nodes = approval_nodes = 0
        total_nodes = len(wf_nodes)

        for nid, n in wf_nodes.items():
            if not isinstance(n, dict):
                continue
            tid = n.get("typeId")
            nd_name = n.get("name", "")

            if tid == 0:  # trigger
                raw_name = nd_name
                trigger_name = TRIGGER_NAME_MAP.get(raw_name, raw_name)
                worksheet = n.get("appName", "")
                trigger_stats[trigger_name] += 1
            elif tid == 6:
                if nd_name == "新增记录":
                    create_nodes += 1
                    axiom1_total += 1
                    fields = n.get("fields", []) or []
                    types = Counter(f.get("type", 0) for f in fields)
                    has_dynamic = types.get(27, 0) > 0
                    owner_kw = ["拥有者", "创建者", "负责人", "owner"]
                    parent_kw = ["项目", "合同", "采购", "任务", "客户", "供应商", "订单", "工单"]
                    has_owner = has_parent = False
                    for f in fields:
                        fn = str(f.get("fieldName", "") or f.get("n", "") or "")
                        if fn:
                            if any(k in fn for k in owner_kw): has_owner = True
                            if any(k in fn for k in parent_kw): has_parent = True
                    if (has_owner and has_parent) or (has_dynamic and len(fields) >= 2):
                        axiom1_backfill += 1
                    err = n.get("errorFields", []) or []
                    if err:
                        axiom5_ok += 1
                elif nd_name == "更新记录":
                    update_nodes += 1
                err = n.get("errorFields", []) or []
                if err:
                    axiom5_ok += 1
            elif tid == 7:
                query_nodes += 1
                axiom5_total += 1
                err = n.get("errorFields", []) or []
                if err:
                    axiom5_ok += 1
            elif tid in (4, 26):
                approval_nodes += 1

        rw = manifest_rw.get(wf_pid, {})
        node_data[wf_pid] = {
            "name": pid_to_name.get(wf_pid, wf_pid[:16]),
            "worksheet": worksheet,
            "trigger": trigger_name,
            "node_count": total_nodes,
            "reads": sorted(rw.get("reads", [])),
            "writes": sorted(rw.get("writes", [])),
            "nodes_summary": {
                "create": create_nodes, "update": update_nodes,
                "query": query_nodes, "approval": approval_nodes,
            },
        }

    with open(node_data_path, "w", encoding="utf-8") as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)

    audit_path = os.path.join(BASE, project_name, "_axiom_audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump({"project": project_name,
                   "axiom1_backfill": {"total": axiom1_total, "with_backfill": axiom1_backfill},
                   "axiom5_degradation": {"total": axiom5_total, "with_errorfields": axiom5_ok}}, f,
                  ensure_ascii=False, indent=2)

    print(f"  {project_name}: enriched {len(node_data)} workflows from nodes.json")
    print(f"    Triggers: {dict(trigger_stats.most_common())}")
    print(f"    公理1(回写): {axiom1_backfill}/{axiom1_total}")
    print(f"    公理5(降级): {axiom5_ok}/{axiom5_total}")
    return True


def _discover_pid_dirs(proj_dir):
    """Find PID directories containing node_configs.json + workflow_meta.json.

    PID directories are 32-char hex subdirectories directly under proj_dir.
    Returns list of (pid, dir_path) tuples.
    """
    pid_dirs = []
    for name in os.listdir(proj_dir):
        sub = os.path.join(proj_dir, name)
        if not os.path.isdir(sub):
            continue
        # PID directories are 24-char hex strings (明道云 processId format)
        if len(name) == 24 and all(c in '0123456789abcdef' for c in name):
            cfg = os.path.join(sub, 'node_configs.json')
            meta = os.path.join(sub, 'workflow_meta.json')
            if os.path.exists(cfg) and os.path.exists(meta):
                pid_dirs.append((name, sub))
    return pid_dirs


def generate_from_pid_dirs(project_name, pid_dirs, manifest_path, node_data_path):
    """Generate _node_data.json from PID directory node_configs.json + workflow_meta.json."""
    # Build manifest r/w lookup by PID
    manifest_rw = {}
    if os.path.exists(manifest_path):
        mf = json.load(open(manifest_path, encoding="utf-8"))
        for sheet, wf_list in mf.get("tables", {}).items():
            for wf in wf_list:
                pid = wf.get("pid", "")
                manifest_rw[pid] = {
                    "reads": wf.get("r", []) or [],
                    "writes": wf.get("w", []) or [],
                }

    # Load fieldId→fieldName map (set module-level for _summarize_node)
    global field_map
    field_map_path = os.path.join(BASE, project_name, "_field_map.json")
    field_map = {}
    if os.path.exists(field_map_path):
        fm_data = json.load(open(field_map_path, encoding="utf-8"))
        field_map = fm_data.get("fieldMap", fm_data)

    node_data = {}
    trigger_stats = Counter()
    axiom1_total = axiom1_backfill = 0
    axiom5_total = axiom5_ok = 0
    node_chain_wf = 0

    for pid, dir_path in pid_dirs:
        cfg_path = os.path.join(dir_path, "node_configs.json")
        meta_path = os.path.join(dir_path, "workflow_meta.json")

        try:
            with open(cfg_path, encoding="utf-8") as f:
                nodes_list = json.load(f)
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue

        if not isinstance(nodes_list, list):
            continue

        # Convert list to dict keyed by node id (format _build_node_chain_from_detail expects)
        wf_nodes = {}
        for n in nodes_list:
            nid = n.get("id", "")
            if nid:
                wf_nodes[nid] = n

        if not wf_nodes:
            continue

        # Build node chain + axiom stats
        node_chain, axiom_delta = _build_node_chain_from_detail(wf_nodes)
        axiom1_total += axiom_delta["create_total"]
        axiom1_backfill += axiom_delta["create_backfill"]
        axiom5_total += axiom_delta["query_total"]
        axiom5_ok += axiom_delta["query_continue"]
        if node_chain:
            node_chain_wf += 1

        # Trigger type from the trigger node
        trigger = "unknown"
        worksheet = meta.get("trigger_sheet", "")
        for n in nodes_list:
            if n.get("typeId") == 0:
                raw_name = n.get("name", "")
                trigger = TRIGGER_NAME_MAP.get(raw_name, raw_name)
                if trigger == "工作表事件":
                    tid = str(n.get("triggerId", ""))
                    trigger += f" ({TRIGGER_ID_MAP.get(tid, tid)})"
                if not worksheet:
                    worksheet = n.get("appName", "")
                break

        trigger_stats[trigger] += 1

        # Summary counts
        create_nodes = update_nodes = query_nodes = approval_nodes = 0
        for nc in node_chain:
            tname = nc.get("typeName", "")
            if tname == "新增记录":
                create_nodes += 1
            elif tname == "更新记录":
                update_nodes += 1
            elif tname == "查询":
                query_nodes += 1
            elif tname in ("审批", "发起审批"):
                approval_nodes += 1

        # r/w from manifest
        rw = manifest_rw.get(pid, {})
        reads_list = sorted(rw.get("reads", []))
        writes_list = sorted(rw.get("writes", []))

        wf_name = meta.get("name", "") or pid[:16]
        node_data[pid] = {
            "name": wf_name,
            "worksheet": worksheet or "未分类",
            "trigger": trigger,
            "node_count": len(nodes_list),
            "reads": reads_list,
            "writes": writes_list,
            "nodes_summary": {
                "create": create_nodes,
                "update": update_nodes,
                "query": query_nodes,
                "approval": approval_nodes,
            },
            "node_chain": node_chain,
        }

    with open(node_data_path, "w", encoding="utf-8") as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)

    axiom1_score = f"{axiom1_backfill}/{axiom1_total}" if axiom1_total > 0 else "N/A"
    axiom5_score = f"{axiom5_ok}/{axiom5_total}" if axiom5_total > 0 else "N/A"
    print(f"  {project_name}: enriched {len(node_data)} workflows from {len(pid_dirs)} PID dirs")
    print(f"    With node_chain: {node_chain_wf}")
    print(f"    Triggers: {dict(trigger_stats.most_common())}")
    print(f"    公理1(回写): {axiom1_score}")
    print(f"    公理5(降级): {axiom5_score}")
    return True


def _load_api_worksheets(project_name, proj_dir):
    """Scan workflow-analyzer extraction output for authoritative trigger worksheet names.

    Reads node_configs.json files in {proj_dir}/*/工作流名/node_configs.json
    Returns {pid: actual_worksheet_name} mapping.
    """
    api_map = {}
    # Scan for node_configs.json files from workflow-analyzer extractions
    for root, dirs, files in os.walk(proj_dir):
        if "node_configs.json" in files and "工作流" in root:
            try:
                nodes = json.load(open(os.path.join(root, "node_configs.json"), encoding="utf-8"))
                if isinstance(nodes, list) and len(nodes) > 0:
                    trigger = nodes[0]
                    api_node = trigger.get("_api_node", {})
                    pid = api_node.get("triggerId") or api_node.get("id", "")
                    app_name = api_node.get("appName", "")
                    if pid and app_name:
                        api_map[pid] = app_name
            except Exception:
                pass
    return api_map


def generate_from_manifest(project_name, manifest_path, node_data_path):
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    tables = manifest.get("tables", {})
    node_data = {}
    seen = set()
    corrections = 0

    # Load API-verified worksheet names for cross-validation
    proj_dir = os.path.join(BASE, project_name)
    api_worksheets = _load_api_worksheets(project_name, proj_dir)

    for sheet_name, wfs in tables.items():
        for wf in wfs:
            pid = wf.get("pid", "")
            if not pid or pid in seen:
                continue
            seen.add(pid)

            # API-verified worksheet takes priority over manifest grouping
            actual_worksheet = api_worksheets.get(pid, sheet_name)
            if actual_worksheet != sheet_name:
                corrections += 1

            node_data[pid] = {
                "name": wf.get("wf", ""),
                "worksheet": actual_worksheet,
                "trigger": wf.get("trigger", "unknown"),
                "node_count": wf.get("node_count", 0),
                "reads": wf.get("r", []) or [],
                "writes": wf.get("w", []) or [],
            }

    with open(node_data_path, "w", encoding="utf-8") as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)

    print(f"  {project_name}: generated {len(node_data)} workflows from manifest")
    if corrections:
        print(f"    ⚠ Corrected {corrections} worksheet assignments using API data")
    if api_worksheets:
        print(f"    ✓ Cross-validated against {len(api_worksheets)} API-extracted workflows")
    return True


def main():
    force = "--force" in sys.argv
    project_names = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not project_names or "--all" in sys.argv:
        reg_path = os.path.join(BASE, "projects_registry.json")
        if os.path.exists(reg_path):
            reg = json.load(open(reg_path, encoding="utf-8"))
            for name, meta in reg.get("projects", {}).items():
                if meta.get("context_ready"):
                    generate(name, force=force)
        return

    for name in project_names:
        generate(name, force=force)


if __name__ == "__main__":
    main()
