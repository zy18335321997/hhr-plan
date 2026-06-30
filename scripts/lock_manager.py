#!/usr/bin/env python3
"""execution_lock.json 管理器 — 生成骨架、验证、合并更新。

Usage:
    # 从项目上下文 + 设计输出生成 lock 骨架
    python3 lock_manager.py init 几建 --mode A --output path/to/execution_lock.json

    # 验证 lock 文件（表/字段存在性 + 关联环路）
    python3 lock_manager.py validate 几建 path/to/execution_lock.json

    # 合并更新（Mode B 增量修改后更新 lock）
    python3 lock_manager.py merge path/to/execution_lock.json --update path/to/update.json

Output: JSON (always) + human summary (stderr)
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

DATA_DIR = Path.home() / "Documents" / "workflow-output"
SKILL_DIR = Path(__file__).resolve().parent
LOCK_SCHEMA_REF = SKILL_DIR.parent / "references" / "templates" / "execution-lock-schema.md"


# ── Skeleton generation ──────────────────────────────────────────────

def generate_skeleton(project: str, mode: str) -> dict:
    """Generate a minimal execution_lock.json skeleton from project context."""
    ctx = _load_project_context(project)
    sheets = ctx.get("worksheets", {})
    naming = ctx.get("naming", {}) if isinstance(ctx.get("naming"), dict) else {}

    sheet_list = []
    for name, info in sheets.items():
        if not isinstance(info, dict):
            continue
        fields = []
        for f in info.get("fields", []):
            if isinstance(f, dict):
                fields.append({
                    "name": f.get("name", ""),
                    "type": f.get("type", ""),
                    "default_value": None,
                    "required": f.get("required", False),
                    "unique": False,
                    "axiom_ref": "",
                    "note": ""
                })

        hub_tables = ctx.get("hub_tables", [])
        is_hub = name in hub_tables if isinstance(hub_tables, list) else False

        sheet_list.append({
            "name": name,
            "module": info.get("module", ""),
            "is_hub": is_hub,
            "hub_reference": None,
            "field_count": info.get("field_count", len(fields)),
            "fields": fields
        })

    skeleton = {
        "meta": {
            "project": project,
            "mode": mode,
            "created": date.today().isoformat(),
            "updated": date.today().isoformat(),
            "axioms_covered": [],
            "confidence": "MEDIUM"
        },
        "naming": {
            "auto_number_prefix": naming.get("auto_number_prefixes", [""])[0] if naming.get("auto_number_prefixes") else "",
            "workflow_verb_prefixes": naming.get("workflow_verb_prefixes", []),
            "worksheet_suffix_format": "子表（父表/操作类型）",
            "bool_field_prefix": "是否",
            "field_ordering": ["身份标识", "业务属性", "关联引用", "计算汇总"]
        },
        "sheets": sheet_list,
        "associations": [],
        "workflows": [],
        "gates": {
            "gate_1_dependency": {"result": "pending", "issues": []},
            "gate_2_logic": {"result": "pending", "issues": []},
            "gate_3_timing": {"result": "pending", "issues": []},
            "gate_4_fields": {"result": "pending", "issues": []},
            "gate_5_platform": {"result": "pending", "issues": []},
            "gate_6_reasoning": {"result": "pending", "issues": []}
        }
    }
    return skeleton


# ── Validation ────────────────────────────────────────────────────────

def validate_lock(project: str, lock_path: str) -> dict:
    """Validate a lock file against the project context."""
    lock = _load_lock(lock_path)
    ctx = _load_project_context(project)
    sheets = ctx.get("worksheets", {})

    issues = []
    stats = {"sheets_checked": 0, "fields_checked": 0, "workflows_checked": 0, "associations_checked": 0}

    # Check sheet/field existence
    for s in lock.get("sheets", []):
        sheet_name = s.get("name", "")
        stats["sheets_checked"] += 1
        if sheet_name not in sheets:
            issues.append({
                "severity": "error",
                "type": "sheet_not_found",
                "sheet": sheet_name,
                "detail": f"Sheet '{sheet_name}' not in project_context.json"
            })
            continue

        real_fields = {f["name"]: f for f in sheets[sheet_name].get("fields", []) if isinstance(f, dict)}
        for lf in s.get("fields", []):
            stats["fields_checked"] += 1
            fn = lf.get("name", "")
            if fn not in real_fields:
                issues.append({
                    "severity": "warning",
                    "type": "field_not_found",
                    "sheet": sheet_name,
                    "field": fn,
                    "detail": f"Field '{fn}' not found in sheet '{sheet_name}'"
                })

    # Check workflow references
    for wf in lock.get("workflows", []):
        stats["workflows_checked"] += 1
        trigger_sheet = wf.get("trigger_sheet", "")
        if trigger_sheet and trigger_sheet not in sheets:
            issues.append({
                "severity": "error",
                "type": "workflow_sheet_not_found",
                "workflow": wf.get("name", "?"),
                "sheet": trigger_sheet,
                "detail": f"Workflow '{wf.get('name')}' references missing sheet '{trigger_sheet}'"
            })

    # Check associations
    from design_validator import load_dependency_graph, check_proposed_edge
    graph = load_dependency_graph(project)
    for assoc in lock.get("associations", []):
        stats["associations_checked"] += 1
        frm = assoc.get("from_sheet", "")
        to = assoc.get("to_sheet", "")
        if frm and to:
            result = check_proposed_edge(project, frm, to)
            if result["verdict"] == "fail":
                for i in result.get("issues", []):
                    issues.append({
                        "severity": "error",
                        "type": "association_cycle",
                        "from": frm,
                        "to": to,
                        "detail": i["detail"]
                    })

    # Gate status summary
    gate_summary = {}
    for gate_key, gate_val in lock.get("gates", {}).items():
        gate_summary[gate_key] = gate_val.get("result", "unknown")

    verdict = "pass" if not any(i["severity"] == "error" for i in issues) else "fail"

    return {
        "verdict": verdict,
        "lock_file": lock_path,
        "meta": lock.get("meta", {}),
        "stats": stats,
        "gate_summary": gate_summary,
        "issues": issues
    }


# ── Merge ─────────────────────────────────────────────────────────────

def merge_lock(lock_path: str, update_path: str) -> dict:
    """Merge an update (partial lock JSON) into the existing lock file."""
    lock = _load_lock(lock_path)
    update = _load_lock(update_path)

    # Deep merge strategy: update top-level lists by name key
    for key in ["sheets", "workflows", "associations"]:
        if key not in update:
            continue
        existing_items = {item.get("name", ""): item for item in lock.get(key, [])}
        for new_item in update[key]:
            name = new_item.get("name", "")
            if name in existing_items:
                existing_items[name].update(new_item)
            else:
                existing_items[name] = new_item
        lock[key] = list(existing_items.values())

    # Merge meta
    lock["meta"]["updated"] = date.today().isoformat()
    if "confidence" in update.get("meta", {}):
        lock["meta"]["confidence"] = update["meta"]["confidence"]

    # Merge gates
    for gate_key, gate_val in update.get("gates", {}).items():
        if gate_key in lock.get("gates", {}):
            lock["gates"][gate_key] = gate_val

    return lock


# ── Helpers ───────────────────────────────────────────────────────────

def _load_project_context(project: str) -> dict:
    path = DATA_DIR / project / "project_context.json"
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def _load_lock(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(p) as f:
        return json.load(f)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="execution_lock.json 管理器")
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="从项目上下文生成锁骨架")
    init_p.add_argument("project")
    init_p.add_argument("--mode", default="A", help="Mode A 或 B")
    init_p.add_argument("--output", default=None, help="输出路径（默认 stdout 打印）")

    validate_p = sub.add_parser("validate", help="验证锁文件")
    validate_p.add_argument("project")
    validate_p.add_argument("lock_path")

    merge_p = sub.add_parser("merge", help="合并更新到锁文件")
    merge_p.add_argument("lock_path")
    merge_p.add_argument("--update", required=True, help="增量更新 JSON 文件路径")

    args = parser.parse_args()

    if args.command == "init":
        skel = generate_skeleton(args.project, args.mode)
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(skel, ensure_ascii=False, indent=2))
            print(f"✅ Skeleton written to {args.output}", file=sys.stderr)
            print(f"   {skel['meta']['sheets_count']} sheets with {sum(len(s.get('fields',[])) for s in skel['sheets'])} fields", file=sys.stderr)
        else:
            print(json.dumps(skel, ensure_ascii=False, indent=2))

    elif args.command == "validate":
        result = validate_lock(args.project, args.lock_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["verdict"] == "fail":
            errors = [i for i in result["issues"] if i["severity"] == "error"]
            warnings = [i for i in result["issues"] if i["severity"] == "warning"]
            print(f"\n❌ Validation FAILED: {len(errors)} errors, {len(warnings)} warnings", file=sys.stderr)
            for i in errors:
                print(f"  [error] {i['detail']}", file=sys.stderr)
            for i in warnings[:10]:
                print(f"  [warn]  {i['detail']}", file=sys.stderr)
        else:
            print(f"\n✅ Validation PASSED ({result['stats']})", file=sys.stderr)

    elif args.command == "merge":
        merged = merge_lock(args.lock_path, args.update)
        out_path = Path(args.lock_path)
        out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
        print(f"✅ Merged into {args.lock_path}", file=sys.stderr)
        print(json.dumps(merged, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
