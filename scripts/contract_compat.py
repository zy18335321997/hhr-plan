#!/usr/bin/env python3
"""合约兼容性验证 — 验证 execution_contract.json 与 hap-flow-exec 的 schema 兼容性。

用法:
  python3 contract_compat.py validate execution_contract.json
  python3 contract_compat.py validate execution_contract.json --quiet
  python3 contract_compat.py check-schema
  python3 contract_compat.py --all-projects validate   # 验证所有项目的合约

设计:
  - 验证逻辑用 Python 直接实现 (required keys + valid values), 不用 jsonschema 库
  - check-schema 交叉验证 VALID_TYPE_IDS 在 schema 和 verify-platform.py 中一致
  - CI 用 inline heredoc 创建测试数据, 覆盖 valid + invalid 两种情况
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "references" / "schemas" / "execution-contract-schema.json"
WORKFLOW_OUTPUT = os.path.expanduser("~/Documents/workflow-output")


def load_schema():
    """加载合约 schema 定义。"""
    with open(SCHEMA_PATH) as f:
        return json.load(f)


# ── 从 verify-platform.py 提取 VALID_TYPE_IDS ──

def extract_valid_type_ids_from_verify_platform() -> set:
    """从 verify-platform.py 源码中提取 VALID_TYPE_IDS 集合。"""
    vp_path = SKILL_DIR / "scripts" / "verify-platform.py"
    with open(vp_path) as f:
        content = f.read()

    # 匹配 VALID_TYPE_IDS = { ... } 块
    m = re.search(r'VALID_TYPE_IDS\s*=\s*\{(.*?)\}', content, re.DOTALL)
    if not m:
        return set()

    ids_str = m.group(1)
    ids = set()
    for num in re.findall(r'\d+', ids_str):
        ids.add(int(num))
    return ids


# ── 合约验证 ──

def collect_violations(violations: list, severity: str, path: str, detail: str):
    violations.append({"severity": severity, "path": path, "detail": detail})
    return violations


def validate_contract(data: dict, schema: dict = None) -> list:
    """验证 execution_contract.json 的结构完整性。返回 violations 列表。"""
    if schema is None:
        schema = load_schema()

    v = []

    # ── 顶级 required keys ──
    for key in schema.get("required_top_keys", []):
        if key not in data:
            v = collect_violations(v, "high", f"$.{key}", f"缺少顶级字段: {key}")
            continue

    # ── meta ──
    meta = data.get("meta", {})
    if isinstance(meta, dict):
        meta_schema = schema.get("meta", {})
        for key in meta_schema.get("required_keys", []):
            if key not in meta:
                v = collect_violations(v, "high", f"$.meta.{key}", f"meta 缺少字段: {key}")

        mode = meta.get("mode")
        if mode and mode not in meta_schema.get("valid_modes", []):
            v = collect_violations(v, "medium", "$.meta.mode",
                                   f"mode 值无效: {mode} (有效值: {meta_schema.get('valid_modes')})")

        confidence = meta.get("confidence")
        if confidence and confidence not in meta_schema.get("valid_confidence", []):
            v = collect_violations(v, "low", "$.meta.confidence",
                                   f"confidence 值无效: {confidence}")

    else:
        v = collect_violations(v, "high", "$.meta", "meta 不是 dict 或缺失")

    # ── naming ──
    naming = data.get("naming", {})
    if isinstance(naming, dict):
        naming_schema = schema.get("naming", {})
        for key in naming_schema.get("required_keys", []):
            if key not in naming:
                v = collect_violations(v, "medium", f"$.naming.{key}", f"naming 缺少字段: {key}")
    else:
        v = collect_violations(v, "medium", "$.naming", "naming 不是 dict 或缺失")

    # ── sheets ──
    sheets = data.get("sheets", [])
    sheets_schema = schema.get("sheets", {})
    if not isinstance(sheets, list):
        v = collect_violations(v, "high", "$.sheets", "sheets 不是数组")
    else:
        for i, sheet in enumerate(sheets):
            if not isinstance(sheet, dict):
                v = collect_violations(v, "medium", f"$.sheets[{i}]", f"sheet[{i}] 不是 dict")
                continue
            for key in sheets_schema.get("required_keys", []):
                if key not in sheet:
                    v = collect_violations(v, "high", f"$.sheets[{i}].{key}",
                                           f"sheet[{i}] ({sheet.get('name', '?')}) 缺少字段: {key}")

            # 检查 fields
            fields = sheet.get("fields", [])
            if isinstance(fields, list):
                field_req = sheets_schema.get("fields_required_keys", [])
                valid_types = sheets_schema.get("valid_field_types", [])
                for j, field in enumerate(fields):
                    if not isinstance(field, dict):
                        continue
                    for fk in field_req:
                        if fk not in field:
                            v = collect_violations(v, "medium", f"$.sheets[{i}].fields[{j}].{fk}",
                                                   f"sheet[{i}] field[{j}] 缺少字段: {fk}")
                    ftype = field.get("type")
                    if ftype and valid_types and ftype not in valid_types:
                        v = collect_violations(v, "low", f"$.sheets[{i}].fields[{j}].type",
                                               f"field type 值: {ftype} (不在预定义列表中)")

    # ── associations ──
    associations = data.get("associations", [])
    assoc_schema = schema.get("associations", {})
    if not isinstance(associations, list):
        v = collect_violations(v, "medium", "$.associations", "associations 不是数组")
    else:
        for i, assoc in enumerate(associations):
            if not isinstance(assoc, dict):
                continue
            for key in assoc_schema.get("required_keys", []):
                if key not in assoc:
                    v = collect_violations(v, "medium", f"$.associations[{i}].{key}",
                                           f"association[{i}] 缺少字段: {key}")
            atype = assoc.get("type")
            valid_assoc_types = sheets_schema.get("valid_association_types", [])
            if atype is not None and valid_assoc_types and atype not in valid_assoc_types:
                v = collect_violations(v, "low", f"$.associations[{i}].type",
                                       f"association type 值: {atype} (有效值: {valid_assoc_types})")

    # ── workflows ──
    workflows = data.get("workflows", [])
    wf_schema = schema.get("workflows", {})
    if not isinstance(workflows, list):
        v = collect_violations(v, "high", "$.workflows", "workflows 不是数组")
    else:
        for i, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                v = collect_violations(v, "medium", f"$.workflows[{i}]", f"workflow[{i}] 不是 dict")
                continue
            for key in wf_schema.get("required_keys", []):
                if key not in wf:
                    v = collect_violations(v, "high", f"$.workflows[{i}].{key}",
                                           f"workflow[{i}] ({wf.get('name', '?')}) 缺少字段: {key}")

            trigger_type = wf.get("trigger_type")
            if trigger_type and trigger_type not in wf_schema.get("valid_trigger_types", []):
                v = collect_violations(v, "medium", f"$.workflows[{i}].trigger_type",
                                       f"trigger_type 值无效: {trigger_type}")

            # 检查 node_chain
            node_chain = wf.get("node_chain", [])
            if not isinstance(node_chain, list):
                v = collect_violations(v, "high", f"$.workflows[{i}].node_chain",
                                       f"workflow[{i}] node_chain 不是数组")
            else:
                nc_req = wf_schema.get("node_chain_required_keys", [])
                valid_type_ids = set(wf_schema.get("valid_type_ids", []))
                for j, node in enumerate(node_chain):
                    if not isinstance(node, dict):
                        continue
                    for nk in nc_req:
                        if nk not in node:
                            v = collect_violations(v, "medium", f"$.workflows[{i}].node_chain[{j}].{nk}",
                                                   f"node[{j}] 缺少字段: {nk}")
                    tid = node.get("type_id")
                    if tid is not None and valid_type_ids and tid not in valid_type_ids:
                        v = collect_violations(v, "high", f"$.workflows[{i}].node_chain[{j}].type_id",
                                               f"type_id={tid} 不在有效列表中")

    # ── gates ──
    gates = data.get("gates", {})
    gates_schema = schema.get("gates", {})
    if isinstance(gates, dict):
        for key in gates_schema.get("required_keys", []):
            if key not in gates:
                v = collect_violations(v, "medium", f"$.gates.{key}", f"gates 缺少: {key}")
            else:
                gate = gates[key]
                if isinstance(gate, dict):
                    result = gate.get("result")
                    valid_results = gates_schema.get("valid_gate_results", [])
                    if result and result not in valid_results:
                        v = collect_violations(v, "low", f"$.gates.{key}.result",
                                               f"gate result 值无效: {result}")
    else:
        v = collect_violations(v, "medium", "$.gates", "gates 不是 dict 或缺失")

    return v


# ── Schema 交叉验证 ──

def cmd_check_schema():
    """交叉验证 VALID_TYPE_IDS 在 schema 和 verify-platform.py 中一致。"""
    violations = []

    # 从 schema 中读取
    schema = load_schema()
    schema_ids = set(schema.get("workflows", {}).get("valid_type_ids", []))

    # 从 verify-platform.py 中提取
    vp_ids = extract_valid_type_ids_from_verify_platform()

    if not schema_ids:
        violations.append({"severity": "high", "detail": "schema 中 valid_type_ids 为空"})
    if not vp_ids:
        violations.append({"severity": "high", "detail": "无法从 verify-platform.py 提取 VALID_TYPE_IDS"})

    # 比较
    only_in_schema = schema_ids - vp_ids
    only_in_vp = vp_ids - schema_ids

    if only_in_schema:
        violations.append({
            "severity": "high",
            "detail": f"仅在 schema 中的 type_id: {sorted(only_in_schema)}"
        })
    if only_in_vp:
        violations.append({
            "severity": "high",
            "detail": f"仅在 verify-platform.py 中的 type_id: {sorted(only_in_vp)}"
        })

    if not violations:
        violations.append({
            "severity": "pass",
            "detail": f"VALID_TYPE_IDS 一致: {len(schema_ids)} 个 type IDs 匹配"
        })

    verdict = "pass" if all(v["severity"] == "pass" for v in violations) else "fail"

    output = {
        "verdict": verdict,
        "source": "contract_compat.py check-schema",
        "schema_path": str(SCHEMA_PATH),
        "verify_platform_path": str(SKILL_DIR / "scripts" / "verify-platform.py"),
        "schema_type_ids_count": len(schema_ids),
        "verify_platform_type_ids_count": len(vp_ids),
        "results": violations,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


# ── 合约验证命令 ──

def cmd_validate(contract_path: str, quiet: bool = False):
    """验证单个 execution_contract.json 文件。"""
    try:
        with open(contract_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(json.dumps({"verdict": "fail", "error": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({"verdict": "fail", "error": f"文件不存在: {contract_path}"}, ensure_ascii=False))
        sys.exit(1)

    violations = validate_contract(data)
    verdict = "pass" if len(violations) == 0 else "fail"

    high = sum(1 for v in violations if v["severity"] == "high")
    medium = sum(1 for v in violations if v["severity"] == "medium")
    low = sum(1 for v in violations if v["severity"] == "low")

    output = {
        "verdict": verdict,
        "source": "contract_compat.py validate",
        "contract_path": contract_path,
        "total_violations": len(violations),
        "high": high,
        "medium": medium,
        "low": low,
        "violations": violations,
    }

    if quiet:
        print(json.dumps({"verdict": verdict, "total_violations": len(violations)}, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


def cmd_validate_all(quiet: bool = False):
    """验证所有项目的 execution_contract.json (如果存在)。"""
    results = {}
    all_pass = True

    # 扫描 workflow-output 目录寻找 execution_contract.json
    if not os.path.isdir(WORKFLOW_OUTPUT):
        print(json.dumps({"verdict": "fail", "error": f"workflow-output 目录不存在: {WORKFLOW_OUTPUT}"},
                         ensure_ascii=False))
        sys.exit(1)

    for project_dir in sorted(os.listdir(WORKFLOW_OUTPUT)):
        proj_path = os.path.join(WORKFLOW_OUTPUT, project_dir)
        if not os.path.isdir(proj_path):
            continue
        contract_file = os.path.join(proj_path, "execution_contract.json")
        if not os.path.isfile(contract_file):
            continue

        try:
            with open(contract_file) as f:
                data = json.load(f)
            violations = validate_contract(data)
            results[project_dir] = {
                "verdict": "pass" if len(violations) == 0 else "fail",
                "total_violations": len(violations),
            }
            if len(violations) > 0:
                all_pass = False
        except Exception as e:
            results[project_dir] = {"verdict": "error", "error": str(e)}
            all_pass = False

    verdict = "pass" if all_pass and results else ("fail" if not all_pass else "warn")
    output = {
        "verdict": verdict,
        "source": "contract_compat.py validate --all-projects",
        "projects_checked": len(results),
        "results": results,
    }

    if quiet:
        print(json.dumps({"verdict": verdict, "projects_checked": len(results)}, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict in ("pass", "warn") else 1)


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="合约兼容性验证")
    sub = parser.add_subparsers(dest="command", help="子命令")

    val = sub.add_parser("validate", help="验证 execution_contract.json")
    val.add_argument("contract_path", nargs="?", help="合约文件路径")
    val.add_argument("--quiet", action="store_true", help="精简输出")
    val.add_argument("--all-projects", action="store_true", dest="all_projects",
                     help="验证所有项目的合约")

    cs = sub.add_parser("check-schema", help="交叉验证 schema 与 verify-platform.py 的 VALID_TYPE_IDS")

    args = parser.parse_args()

    if args.command == "validate":
        if args.all_projects:
            cmd_validate_all(quiet=args.quiet)
        elif args.contract_path:
            cmd_validate(args.contract_path, quiet=args.quiet)
        else:
            print(json.dumps({"verdict": "fail", "error": "需要 contract_path 或 --all-projects"},
                             ensure_ascii=False))
            sys.exit(2)
    elif args.command == "check-schema":
        cmd_check_schema()
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
