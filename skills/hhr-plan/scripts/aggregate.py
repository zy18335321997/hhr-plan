#!/usr/bin/env python3
"""
Hu Haoran Methodology Distiller - Phase 0 & Phase 1
Aggregates project data and produces 7 structured JSON reports.

Usage:
    python3 scripts/aggregate.py <project_root_path> [output_dir]
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_load_json(path):
    try:
        return load_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Phase 0: Project Manifest ─────────────────────────────────────────────

def phase0_manifest(project_root):
    """Validate project structure and build manifest."""
    root = Path(project_root)
    result = {
        "project_name": root.name,
        "root_path": str(root),
        "index_exists": (root / "INDEX.md").exists(),
        "all_pids_exists": (root / "_all_pids.json").exists(),
        "workflow_discovery_exists": (root / "workflow_discovery.json").exists(),
        "worksheet_wfs_exists": (root / "_worksheet_wfs.json").exists(),
    }

    modules = []
    total_worksheets = 0
    ws_with_fields = 0
    ws_with_workflows = 0
    total_workflow_dirs = 0
    total_fields = 0
    missing_fields = []
    missing_node_configs = []

    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue

        mod_entry = {
            "name": mod_dir.name,
            "worksheets": [],
            "worksheet_count": 0,
            "workflow_count": 0,
            "field_count": 0,
        }

        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue

            ws_entry = {
                "name": ws_dir.name,
                "has_fields": (ws_dir / "fields.json").exists(),
                "has_workflows_json": (ws_dir / "workflows.json").exists(),
                "has_readme": (ws_dir / "README.md").exists(),
            }

            if ws_entry["has_fields"]:
                fields_data = load_json(ws_dir / "fields.json")
                ws_entry["field_count"] = len(fields_data.get("fields", []))
                ws_entry["sheet_label"] = fields_data.get("name", "")
                total_fields += ws_entry["field_count"]
            else:
                ws_entry["field_count"] = 0
                missing_fields.append(f"{mod_dir.name}/{ws_dir.name}")

            wf_subdirs = []
            wf_dir = ws_dir / "工作流"
            if wf_dir.exists():
                for wf_sub in sorted(wf_dir.iterdir()):
                    if wf_sub.is_dir():
                        has_nc = (wf_sub / "node_configs.json").exists()
                        wf_subdirs.append({"name": wf_sub.name, "has_node_configs": has_nc})
                        if not has_nc:
                            missing_node_configs.append(f"{mod_dir.name}/{ws_dir.name}/工作流/{wf_sub.name}")
                        total_workflow_dirs += 1

            ws_entry["workflow_subdirs"] = wf_subdirs
            ws_entry["workflow_count"] = len(wf_subdirs)
            mod_entry["worksheets"].append(ws_entry)

        mod_entry["worksheet_count"] = len(mod_entry["worksheets"])
        mod_entry["workflow_count"] = sum(ws["workflow_count"] for ws in mod_entry["worksheets"])
        mod_entry["field_count"] = sum(ws["field_count"] for ws in mod_entry["worksheets"])
        modules.append(mod_entry)
        total_worksheets += mod_entry["worksheet_count"]
        ws_with_fields += sum(1 for ws in mod_entry["worksheets"] if ws["has_fields"])
        ws_with_workflows += sum(1 for ws in mod_entry["worksheets"] if ws["workflow_count"] > 0)

    if total_worksheets >= 200:
        scale = "enterprise"
    elif total_worksheets >= 100:
        scale = "large"
    elif total_worksheets >= 50:
        scale = "medium"
    else:
        scale = "small"

    scale_labels = {"enterprise": "企业级 (>200工作表)", "large": "大型 (100-200)", "medium": "中型 (50-100)", "small": "小型 (<50)"}

    result.update({
        "total_modules": len(modules),
        "total_worksheets": total_worksheets,
        "worksheets_with_fields": ws_with_fields,
        "worksheets_with_workflows": ws_with_workflows,
        "total_workflow_dirs": total_workflow_dirs,
        "total_fields": total_fields,
        "scale": scale,
        "scale_label": scale_labels[scale],
        "data_completeness": {
            "fields_coverage_pct": round(ws_with_fields / total_worksheets * 100, 1) if total_worksheets > 0 else 0,
            "missing_fields": missing_fields[:30],
            "missing_node_configs": missing_node_configs[:30],
            "missing_fields_count": len(missing_fields),
            "missing_node_configs_count": len(missing_node_configs),
        },
        "modules": modules,
    })

    # Verify against workflow_discovery.json
    wf_disc = safe_load_json(root / "workflow_discovery.json")
    if wf_disc:
        result["workflow_discovery_modules"] = list(wf_disc.keys())

    return result


# ── Data Collection Helpers ───────────────────────────────────────────────

def collect_all_fields(project_root):
    """Collect all fields from all worksheets. Returns list of dicts with module, worksheet, field."""
    root = Path(project_root)
    all_fields = []
    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue
            fp = ws_dir / "fields.json"
            if not fp.exists():
                continue
            data = load_json(fp)
            ws_name = data.get("name", ws_dir.name)
            for f in data.get("fields", []):
                all_fields.append({"module": mod_dir.name, "worksheet": ws_name, "field": f})
    return all_fields


def collect_all_workflows(project_root):
    """Collect all workflow configs. Returns list of dicts with module, worksheet, wf_name, nodes."""
    root = Path(project_root)
    all_wfs = []
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
                nodes = load_json(nc_path)
                all_wfs.append({
                    "module": mod_dir.name,
                    "worksheet": ws_dir.name,
                    "wf_name": wf_sub.name,
                    "nodes": nodes,
                })
    return all_wfs


def parse_trigger_from_name(wf_name):
    for key in ["工作表事件", "自定义动作", "审批", "子流程", "时间"]:
        if key in wf_name:
            if key == "审批":
                return "审批"
            if key == "子流程":
                return "子流程"
            return key
    return "未知"


def parse_node_type(node_text):
    if not isinstance(node_text, str):
        return "未知节点"
    if "发起" in node_text and ("审批" in node_text or "流程" in node_text):
        return "流程发起节点"
    if "审批" in node_text and "发起" not in node_text:
        return "审批节点"
    if "填写" in node_text:
        return "填写节点"
    if "子流程" in node_text:
        return "子流程节点"
    if "代码块" in node_text or "脚本" in node_text:
        return "代码块节点"
    if "发送" in node_text or "通知" in node_text:
        return "通知节点"
    if "新增" in node_text or "更新" in node_text or "删除" in node_text:
        return "数据操作节点"
    if "查询" in node_text or "获取" in node_text:
        return "查询节点"
    if "延时" in node_text or "等待" in node_text:
        return "延时节点"
    if "条件" in node_text or "分支" in node_text:
        return "条件分支节点"
    if "连接" in node_text or "集成" in node_text:
        return "集成节点"
    return "其他节点"


# ── Report 01: Data Model ─────────────────────────────────────────────────

def analyze_data_model(all_fields):
    """Produce 01_data_model.json"""
    fields_list = [x["field"] for x in all_fields]

    # Type distribution
    type_counter = Counter()
    type_name_map = {}
    for f in fields_list:
        t = f.get("type", 0)
        type_counter[t] += 1
        if t not in type_name_map:
            type_name_map[t] = f.get("type_name", str(t))

    type_distribution = [
        {"type_code": t, "type_name": type_name_map.get(t, str(t)), "count": c}
        for t, c in type_counter.most_common()
    ]

    # Fields per worksheet
    ws_field_count = Counter()
    ws_field_names = defaultdict(set)
    for x in all_fields:
        key = (x["module"], x["worksheet"])
        ws_field_count[key] += 1
        ws_field_names[key].add(x["field"]["controlName"])

    # Field frequency across worksheets
    total_ws = len(ws_field_count)
    field_freq = Counter()
    for names in ws_field_names.values():
        for name in names:
            field_freq[name] += 1

    standard_fields = [
        {"name": name, "count": cnt, "pct": round(cnt / total_ws * 100, 1)}
        for name, cnt in field_freq.most_common(50)
        if cnt / total_ws * 100 >= 30
    ]

    # Field count histogram
    count_buckets = Counter()
    for cnt in ws_field_count.values():
        if cnt <= 5:       count_buckets["1-5"] += 1
        elif cnt <= 10:    count_buckets["6-10"] += 1
        elif cnt <= 20:    count_buckets["11-20"] += 1
        elif cnt <= 30:    count_buckets["21-30"] += 1
        elif cnt <= 50:    count_buckets["31-50"] += 1
        elif cnt <= 100:   count_buckets["51-100"] += 1
        else:              count_buckets["101+"] += 1

    def bucket_sort_key(item):
        return int(item[0].split("-")[0].rstrip("+"))

    field_count_histogram = [
        {"range": k, "worksheet_count": v}
        for k, v in sorted(count_buckets.items(), key=bucket_sort_key)
    ]

    field_count_stats = {}
    if ws_field_count:
        counts = list(ws_field_count.values())
        counts.sort()
        field_count_stats = {
            "min": counts[0],
            "max": counts[-1],
            "mean": round(sum(counts) / len(counts), 1),
            "median": counts[len(counts) // 2],
        }

    # Required fields
    required_by_type = Counter()
    ws_required_count = Counter()
    for x in all_fields:
        if x["field"].get("required"):
            required_by_type[x["field"].get("type_name", "?")] += 1
            ws_required_count[(x["module"], x["worksheet"])] += 1

    avg_required = round(sum(ws_required_count.values()) / len(ws_required_count), 1) if ws_required_count else 0

    # Auto-number formats
    auto_number_formats = []
    for f in fields_list:
        if f.get("type") != 33:
            continue
        adv = f.get("advancedSetting", {})
        if isinstance(adv, str):
            try: adv = json.loads(adv)
            except json.JSONDecodeError: adv = {}
        increase = adv.get("increase", "")
        if isinstance(increase, str):
            try: increase = json.loads(increase)
            except json.JSONDecodeError: increase = []
        if isinstance(increase, list):
            for inc in increase:
                if isinstance(inc, dict):
                    auto_number_formats.append({
                        "field_name": f.get("controlName", ""),
                        "format": inc.get("format"),
                        "length": inc.get("length"),
                        "start": inc.get("start"),
                        "controlId": inc.get("controlId"),
                        "controlName": inc.get("controlName"),
                    })

    # Option color patterns
    option_colors = Counter()
    option_examples = []
    for f in fields_list:
        options = f.get("options", [])
        if options:
            for opt in options:
                option_colors[opt.get("color", "N/A")] += 1
            if len(option_examples) < 15:
                option_examples.append({
                    "field_name": f.get("controlName", ""),
                    "type_name": f.get("type_name", ""),
                    "options": [{"value": o.get("value", ""), "color": o.get("color", "")} for o in options[:5]],
                })

    # Sub-table & relation usage
    subtable_count = sum(1 for x in all_fields if x["field"].get("type") == 34)
    relation_counts = Counter()
    for x in all_fields:
        t = x["field"].get("type")
        if t == 29: relation_counts["关联表(29)"] += 1
        if t == 30: relation_counts["他表字段(30)"] += 1
        if t == 31: relation_counts["公式他表(31)"] += 1

    # First field ordering
    ws_first_fields = defaultdict(list)
    for x in all_fields:
        ws_first_fields[(x["module"], x["worksheet"])].append(x["field"])

    first_field_counter = Counter()
    field_order_samples = []
    for (mod, ws_name), fields in ws_first_fields.items():
        sorted_fields = sorted(fields, key=lambda f: (f.get("row", 0), f.get("col", 0)))
        first_names = [f.get("controlName", "") for f in sorted_fields[:3]]
        if first_names:
            first_field_counter[first_names[0]] += 1
        if len(field_order_samples) < 30:
            field_order_samples.append({"worksheet": f"{mod}/{ws_name}", "first_3_fields": first_names})

    return {
        "summary": {
            "total_fields": len(fields_list),
            "total_worksheets": total_ws,
            "avg_fields_per_ws": round(len(fields_list) / total_ws, 1) if total_ws > 0 else 0,
        },
        "type_distribution": type_distribution,
        "standard_field_clusters": standard_fields,
        "field_count_histogram": field_count_histogram,
        "field_count_stats": field_count_stats,
        "required_field_patterns": {
            "by_type_top15": required_by_type.most_common(15),
            "avg_required_per_ws": avg_required,
            "total_ws_with_required": len(ws_required_count),
        },
        "auto_number_formats": auto_number_formats[:30],
        "option_color_standards": option_colors.most_common(15),
        "option_examples": option_examples,
        "subtable_and_relations": {
            "subtable_fields_total": subtable_count,
            "relation_fields_by_type": dict(relation_counts),
        },
        "field_ordering": {
            "common_first_fields_top10": first_field_counter.most_common(10),
            "sample_worksheets": field_order_samples,
        },
    }


# ── Report 02: Workflow Topology ──────────────────────────────────────────

def analyze_workflow_topology(all_wfs, project_root):
    """Produce 02_workflow_topology.json"""
    root = Path(project_root)

    # Trigger from directory names
    trigger_counter = Counter()
    for wf in all_wfs:
        trigger_counter[parse_trigger_from_name(wf["wf_name"])] += 1

    # Trigger from _worksheet_wfs.json
    wf_list_data = safe_load_json(root / "_worksheet_wfs.json") or {}
    wf_detail_triggers = Counter()
    wf_detail_status = Counter()
    for wf_list in wf_list_data.values():
        if isinstance(wf_list, list):
            for wf in wf_list:
                if isinstance(wf, dict):
                    wf_detail_triggers[wf.get("trigger", "未知")] += 1
                    wf_detail_status[wf.get("status", "未知")] += 1

    # Node type frequency
    node_type_counter = Counter()
    total_nodes = 0
    for wf in all_wfs:
        for node in wf["nodes"]:
            if isinstance(node, dict):
                node_type_counter[parse_node_type(node.get("node", ""))] += 1
                total_nodes += 1

    # Node chains (n-grams)
    ngram_2 = Counter()
    ngram_3 = Counter()
    ngram_4 = Counter()
    for wf in all_wfs:
        chain = [parse_node_type(n.get("node", "")) for n in wf["nodes"] if isinstance(n, dict)]
        for i in range(len(chain) - 1):
            ngram_2[(chain[i], chain[i + 1])] += 1
        for i in range(len(chain) - 2):
            ngram_3[(chain[i], chain[i + 1], chain[i + 2])] += 1
        for i in range(len(chain) - 3):
            ngram_4[(chain[i], chain[i + 1], chain[i + 2], chain[i + 3])] += 1

    # Subprocess nesting depth
    depth_counter = Counter()
    depth_examples = []
    for wf in all_wfs:
        depth = wf["wf_name"].count("⟩")
        depth_counter[depth] += 1
        if depth >= 2 and len(depth_examples) < 15:
            depth_examples.append({
                "name": wf["wf_name"], "depth": depth,
                "worksheet": wf["worksheet"], "module": wf["module"],
            })

    # Complexity classification
    complexity_counter = Counter()
    complexity_examples = defaultdict(list)
    for wf in all_wfs:
        n = len(wf["nodes"])
        if n <= 2: cat = "simple"
        elif n <= 6: cat = "standard"
        elif n <= 10: cat = "complex"
        else: cat = "very_complex"
        complexity_counter[cat] += 1
        if len(complexity_examples[cat]) < 5:
            complexity_examples[cat].append({"name": wf["wf_name"], "node_count": n, "module": wf["module"]})

    # Approval workflows
    approval_wfs = [wf for wf in all_wfs if "审批" in wf["wf_name"]]
    approval_counts = [len(wf["nodes"]) for wf in approval_wfs]

    # Naming patterns
    bracket_names = []
    plain_names = []
    for wf in all_wfs:
        brackets = re.findall(r'[（(]([^）)]+)[）)]', wf["wf_name"])
        if brackets:
            bracket_names.append({"name": wf["wf_name"], "trigger_hint": brackets[-1]})
        else:
            plain_names.append(wf["wf_name"])

    # Node count distribution
    node_count_dist = Counter(len(wf["nodes"]) for wf in all_wfs)

    return {
        "summary": {
            "total_workflows": len(all_wfs),
            "total_nodes": total_nodes,
            "avg_nodes_per_wf": round(total_nodes / len(all_wfs), 1) if all_wfs else 0,
        },
        "trigger_type": {
            "from_dir_names": dict(trigger_counter.most_common()),
            "from_worksheet_wfs_json": dict(wf_detail_triggers.most_common()),
        },
        "node_type_frequency": node_type_counter.most_common(),
        "common_node_chains": {
            "bigram": [{"chain": list(k), "count": v} for k, v in ngram_2.most_common(20) if v >= 2],
            "trigram": [{"chain": list(k), "count": v} for k, v in ngram_3.most_common(15) if v >= 2],
            "quadgram": [{"chain": list(k), "count": v} for k, v in ngram_4.most_common(10) if v >= 2],
        },
        "subprocess_nesting": {
            "depth_distribution": dict(depth_counter),
            "max_depth": max(depth_counter.keys()) if depth_counter else 0,
            "examples_deep_nesting": depth_examples,
        },
        "complexity": {
            "distribution": dict(complexity_counter),
            "labels": {"simple": "2-3节点", "standard": "4-6节点", "complex": "7-10节点", "very_complex": "11+节点"},
            "examples": {k: v for k, v in complexity_examples.items()},
            "approval_wf_avg_nodes": round(sum(approval_counts) / len(approval_counts), 1) if approval_counts else 0,
            "approval_wf_count": len(approval_wfs),
        },
        "naming": {
            "bracket_hint_count": len(bracket_names),
            "plain_count": len(plain_names),
            "bracket_samples": [x["name"] for x in bracket_names[:15]],
            "plain_samples": plain_names[:15],
        },
        "enabled_vs_disabled": {
            "enabled": wf_detail_status.get("开启", 0),
            "disabled": wf_detail_status.get("关闭", 0),
            "enabled_ratio": round(wf_detail_status.get("开启", 0) / max(sum(wf_detail_status.values()), 1) * 100, 1),
        },
        "node_count_distribution": {str(k): v for k, v in sorted(node_count_dist.items())},
    }


# ── Report 03: Relation Graph ─────────────────────────────────────────────

def analyze_relation_graph(all_fields):
    """Produce 03_relation_graph.json"""
    ws_module = {}
    for x in all_fields:
        ws_module[x["worksheet"]] = x["module"]

    relations = []
    ws_relation_count = defaultdict(lambda: {"关联表": 0, "他表字段": 0, "子表": 0, "total": 0})
    referenced_by = defaultdict(set)

    for x in all_fields:
        f = x["field"]
        t = f.get("type")

        if t == 29:  # 关联表
            target = f.get("dataSource", "")
            rel = {"source_ws": x["worksheet"], "source_module": x["module"],
                   "target_ws": target, "type": "关联表", "field": f.get("controlName", "")}
            relations.append(rel)
            ws_relation_count[x["worksheet"]]["关联表"] += 1
            ws_relation_count[x["worksheet"]]["total"] += 1
            if target:
                referenced_by[target].add((x["worksheet"], "关联表"))

        elif t == 30:  # 他表字段
            target = f.get("sourceControlId", "")
            rel = {"source_ws": x["worksheet"], "source_module": x["module"],
                   "target_ref": target, "type": "他表字段", "field": f.get("controlName", "")}
            relations.append(rel)
            ws_relation_count[x["worksheet"]]["他表字段"] += 1
            ws_relation_count[x["worksheet"]]["total"] += 1
            if target:
                referenced_by[target].add((x["worksheet"], "他表字段"))

        elif t == 34:  # 子表
            target = f.get("dataSource", "")
            rel = {"source_ws": x["worksheet"], "source_module": x["module"],
                   "target_ws": target, "type": "子表", "field": f.get("controlName", "")}
            relations.append(rel)
            ws_relation_count[x["worksheet"]]["子表"] += 1
            ws_relation_count[x["worksheet"]]["total"] += 1
            if target:
                referenced_by[target].add((x["worksheet"], "子表"))

    # Hub worksheets
    hub_worksheets = [
        {"worksheet": ws, "referenced_by_count": len(refs),
         "referenced_by_sample": [{"ws": r[0], "type": r[1]} for r in list(refs)[:10]]}
        for ws, refs in sorted(referenced_by.items(), key=lambda x: -len(x[1]))[:20]
    ]

    # Bidirectional pairs
    ws_targets = defaultdict(set)
    for rel in relations:
        tgt = rel.get("target_ws", "")
        if tgt:
            ws_targets[rel["source_ws"]].add(tgt)

    bidirectional = []
    seen = set()
    for ws_a, targets in ws_targets.items():
        for ws_b in targets:
            if ws_a in ws_targets.get(ws_b, set()):
                pair = tuple(sorted([ws_a, ws_b]))
                if pair not in seen:
                    seen.add(pair)
                    bidirectional.append(list(pair))

    # Cross-module relations
    cross_module = []
    cross_pairs = Counter()
    for rel in relations:
        tgt = rel.get("target_ws", "")
        src_mod = rel["source_module"]
        tgt_mod = ws_module.get(tgt, "unknown")
        if tgt_mod != "unknown" and tgt_mod != src_mod:
            cross_module.append(rel)
            cross_pairs[tuple(sorted([src_mod, tgt_mod]))] += 1

    # Top connected worksheets
    top_connected = [
        {"worksheet": ws, "relations": dict(info)}
        for ws, info in sorted(ws_relation_count.items(), key=lambda x: -x[1]["total"])[:20]
    ]

    return {
        "summary": {
            "total_relations": len(relations),
            "worksheets_with_relations": len(ws_relation_count),
            "avg_relations_per_ws": round(len(relations) / len(ws_relation_count), 1) if ws_relation_count else 0,
        },
        "relation_type_counts": {
            "关联表": sum(1 for r in relations if r["type"] == "关联表"),
            "他表字段": sum(1 for r in relations if r["type"] == "他表字段"),
            "子表": sum(1 for r in relations if r["type"] == "子表"),
        },
        "hub_worksheets": hub_worksheets,
        "bidirectional_relations": {"count": len(bidirectional), "pairs": bidirectional[:15]},
        "cross_module": {
            "total": len(cross_module),
            "module_pairs": [{"pair": list(p), "count": c} for p, c in cross_pairs.most_common(15)],
            "examples": cross_module[:15],
        },
        "top_connected_worksheets": top_connected,
    }


# ── Report 04: Module Boundaries ──────────────────────────────────────────

def analyze_module_boundaries(all_fields, all_wfs):
    """Produce 04_module_boundaries.json"""
    # Field type per module
    mod_field_types = defaultdict(Counter)
    mod_field_total = Counter()
    ws_module_map = {}

    for x in all_fields:
        mod = x["module"]
        tn = x["field"].get("type_name", str(x["field"].get("type", "")))
        mod_field_types[mod][tn] += 1
        mod_field_total[mod] += 1
        ws_module_map[x["worksheet"]] = mod

    # Workflow stats
    mod_wf_count = Counter()
    mod_wf_nodes = defaultdict(list)
    for wf in all_wfs:
        mod_wf_count[wf["module"]] += 1
        mod_wf_nodes[wf["module"]].append(len(wf["nodes"]))

    # Global type frequency for comparison
    global_type_total = sum(mod_field_total.values())
    global_type_freq = Counter()
    for mod, types in mod_field_types.items():
        for t, c in types.items():
            global_type_freq[t] += c

    # Module specialization
    mod_specializations = {}
    for mod in mod_field_types:
        specs = []
        for t, c in mod_field_types[mod].most_common(10):
            mod_pct = c / max(mod_field_total[mod], 1) * 100
            global_pct = global_type_freq[t] / max(global_type_total, 1) * 100
            if global_pct > 0 and mod_pct / global_pct > 1.5 and c >= 3:
                specs.append({"type": t, "mod_pct": round(mod_pct, 1),
                              "global_pct": round(global_pct, 1), "ratio": round(mod_pct / global_pct, 1)})
        mod_specializations[mod] = specs[:5]

    # Cohesion
    internal = defaultdict(int)
    external = defaultdict(int)
    for x in all_fields:
        t = x["field"].get("type")
        if t in [29, 34]:
            target = x["field"].get("dataSource", "")
            if target and target in ws_module_map:
                if ws_module_map[target] == x["module"]:
                    internal[x["module"]] += 1
                else:
                    external[x["module"]] += 1

    cohesion = {}
    for mod in set(list(internal.keys()) + list(external.keys())):
        total_refs = internal[mod] + external[mod]
        cohesion[mod] = {
            "internal": internal[mod], "external": external[mod],
            "cohesion_ratio": round(internal[mod] / max(total_refs, 1), 2),
        }

    # Module sizes
    mod_sizes = []
    all_modules = set(list(mod_field_total.keys()) + list(mod_wf_count.keys()))
    for mod in sorted(all_modules):
        nodes_list = mod_wf_nodes.get(mod, [])
        mod_sizes.append({
            "module": mod,
            "field_count": mod_field_total.get(mod, 0),
            "workflow_count": mod_wf_count.get(mod, 0),
            "avg_nodes_per_wf": round(sum(nodes_list) / max(len(nodes_list), 1), 1),
            "max_nodes_in_wf": max(nodes_list) if nodes_list else 0,
        })
    mod_sizes.sort(key=lambda x: -x["field_count"])

    return {
        "module_sizes": mod_sizes,
        "module_specializations": mod_specializations,
        "module_cohesion": cohesion,
    }


# ── Report 05: Naming DNA ─────────────────────────────────────────────────

def analyze_naming_dna(all_fields, all_wfs):
    """Produce 05_naming_dna.json"""
    # Worksheet names
    ws_names = sorted(set(x["worksheet"] for x in all_fields))
    ws_bracket = []
    ws_plain = []
    for name in ws_names:
        brackets = re.findall(r'[（(]([^）)]+)[）)]', name)
        if brackets:
            ws_bracket.append({"name": name, "qualifier": brackets[-1]})
        else:
            ws_plain.append(name)

    # Field names
    all_field_names = [x["field"].get("controlName", "") for x in all_fields]
    field_name_freq = Counter(all_field_names)

    # Bracket-tagged fields 【】
    bracket_fields = []
    for name in set(all_field_names):
        tags = re.findall(r'【([^】]+)】', name)
        if tags:
            bracket_fields.append({"name": name, "tags": tags})

    bracket_tag_counter = Counter()
    for bf in bracket_fields:
        for tag in bf["tags"]:
            bracket_tag_counter[tag] += 1

    # Prefix/suffix patterns
    patterns = Counter()
    for name in set(all_field_names):
        if name.endswith("人") or name.endswith("负责人"): patterns["负责人/人结尾"] += 1
        if name.endswith("日期") or name.endswith("时间"): patterns["日期/时间结尾"] += 1
        if name.endswith("金额") or name.endswith("费用") or name.endswith("成本"): patterns["金额/费用/成本结尾"] += 1
        if name.startswith("是否"): patterns["是否开头(布尔)"] += 1
        if name.endswith("编号"): patterns["编号结尾"] += 1
        if "【" in name: patterns["含【】标记"] += 1

    # Workflow naming
    wf_names = [wf["wf_name"] for wf in all_wfs]
    wf_bracket = []
    wf_nested = []
    wf_action = []
    for name in wf_names:
        brackets = re.findall(r'[（(]([^）)]+)[）)]', name)
        if brackets:
            wf_bracket.append({"name": name, "trigger_hint": brackets})
        if "⟩" in name:
            wf_nested.append(name)
        if any(kw in name for kw in ["新增", "更新", "修改", "删除", "自动", "同步"]):
            wf_action.append(name)

    # Option value patterns
    option_freq = Counter()
    for x in all_fields:
        for opt in x["field"].get("options", []):
            option_freq[opt.get("value", "")] += 1

    return {
        "worksheet_naming": {
            "total": len(ws_names),
            "with_parenthetical": len(ws_bracket),
            "without_parenthetical": len(ws_plain),
            "parenthetical_examples": ws_bracket[:20],
            "plain_examples": ws_plain[:20],
        },
        "field_naming": {
            "total_unique": len(set(all_field_names)),
            "most_common": field_name_freq.most_common(40),
            "bracket_tagged_count": len(bracket_fields),
            "bracket_tags": bracket_tag_counter.most_common(15),
            "bracket_examples": bracket_fields[:15],
            "affix_patterns": dict(patterns),
        },
        "workflow_naming": {
            "total": len(wf_names),
            "bracket_hint_count": len(wf_bracket),
            "bracket_hint_examples": [x["name"] for x in wf_bracket[:15]],
            "nested_subprocess_count": len(wf_nested),
            "nested_examples": wf_nested[:10],
            "action_verb_examples": wf_action[:15],
        },
        "option_value_naming": {
            "total_unique": len(option_freq),
            "most_common_values": option_freq.most_common(30),
        },
    }


# ── Report 06: Inventory ──────────────────────────────────────────────────

def analyze_inventory(project_root, all_fields, all_wfs, manifest):
    """Produce 06_inventory.json"""
    root = Path(project_root)

    ws_dirs = []
    for mod_dir in root.iterdir():
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        for ws_dir in mod_dir.iterdir():
            if ws_dir.is_dir() and not ws_dir.name.startswith("."):
                ws_dirs.append(ws_dir)

    with_fields = sum(1 for ws in ws_dirs if (ws / "fields.json").exists())
    with_wf_dir = sum(1 for ws in ws_dirs if (ws / "工作流").exists())
    total_nc = sum(
        sum(1 for sub in (ws / "工作流").iterdir() if sub.is_dir() and (sub / "node_configs.json").exists())
        for ws in ws_dirs if (ws / "工作流").exists()
    )

    # Orphans: worksheets without workflows
    orphans = []
    for ws in ws_dirs:
        wf_dir = ws / "工作流"
        has_wf = wf_dir.exists() and any(
            d.is_dir() and (d / "node_configs.json").exists() for d in wf_dir.iterdir()
        )
        if not has_wf:
            orphans.append(str(ws.relative_to(root)))

    # Phantom refs: referenced worksheets that don't exist
    all_ws_names = {ws.name for ws in ws_dirs}
    refs = set()
    for x in all_fields:
        ds = x["field"].get("dataSource", "")
        if ds:
            refs.add(ds)
    phantoms = refs - all_ws_names

    return {
        "exact_counts": {
            "modules": manifest["total_modules"],
            "worksheet_directories": len(ws_dirs),
            "worksheets_with_fields": with_fields,
            "worksheets_with_workflow_dir": with_wf_dir,
            "total_fields": len(all_fields),
            "total_workflow_configs": total_nc,
            "total_nodes": sum(len(wf["nodes"]) for wf in all_wfs),
        },
        "data_completeness": {
            "fields_coverage_pct": round(with_fields / max(len(ws_dirs), 1) * 100, 1),
            "orphan_worksheets_no_workflows": len(orphans),
            "orphan_worksheets_sample": orphans[:30],
            "phantom_references_count": len(phantoms),
            "phantom_references_sample": list(phantoms)[:10],
        },
        "scale": {
            "level": manifest["scale"],
            "label": manifest["scale_label"],
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 aggregate.py <project_root> [output_dir]")
        sys.exit(1)

    project_root = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports"
    )

    if not os.path.isdir(project_root):
        print(f"Error: {project_root} is not a valid directory")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    print(f"Project: {project_root}")
    print(f"Output:  {output_dir}\n")

    # Phase 0
    print("=== Phase 0: Project Manifest ===")
    manifest = phase0_manifest(project_root)
    with open(os.path.join(output_dir, "00_project_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Modules: {manifest['total_modules']}, Worksheets: {manifest['total_worksheets']}")
    print(f"  Workflow dirs: {manifest['total_workflow_dirs']}, Fields: {manifest['total_fields']}")
    print(f"  Scale: {manifest['scale_label']}")

    # Collect data
    print("\n=== Collecting Data ===")
    all_fields = collect_all_fields(project_root)
    all_wfs = collect_all_workflows(project_root)
    print(f"  Fields: {len(all_fields)}, Workflows: {len(all_wfs)}, Nodes: {sum(len(w['nodes']) for w in all_wfs)}")

    # Phase 1 - 6 reports
    print("\n=== Phase 1: 6-Pronged Analysis ===")

    reports = [
        ("01_data_model.json", analyze_data_model(all_fields)),
        ("02_workflow_topology.json", analyze_workflow_topology(all_wfs, project_root)),
        ("03_relation_graph.json", analyze_relation_graph(all_fields)),
        ("04_module_boundaries.json", analyze_module_boundaries(all_fields, all_wfs)),
        ("05_naming_dna.json", analyze_naming_dna(all_fields, all_wfs)),
        ("06_inventory.json", analyze_inventory(project_root, all_fields, all_wfs, manifest)),
    ]

    for filename, report in reports:
        print(f"  Writing {filename}...")
        with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n=== Done. All 7 reports in {output_dir} ===")


if __name__ == "__main__":
    main()
