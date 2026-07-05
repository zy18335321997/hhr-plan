#!/usr/bin/env python3
"""
Step 2 预检脚本：验证执行合约中所有 ID 在平台上存在。

用法:
  python3 preflight.py <execution_contract.json>

产出:
  - 全部通过 → exit 0，输出验证通过摘要
  - 任一不通过 → exit 1，输出逐项错误清单

不调用 hap CLI，只做静态校验。hap CLI 的 worksheet info 调用在主会话中完成。
"""

import json
import sys
import re
from pathlib import Path


def load_contract(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_field_refs(contract: dict) -> list[dict]:
    """从合约中提取所有字段引用。"""
    refs = contract.get("field_references", [])
    return refs


def extract_option_refs(nodes: list[dict]) -> list[dict]:
    """从节点配置中提取所有 option key 引用。"""
    refs = []

    for node in nodes:
        config = node.get("config", {})

        # filter 中的 option 值
        filt = config.get("filter")
        if filt:
            for item in filt.get("items", []):
                right = item.get("right", {})
                if right.get("kind") == "literal":
                    refs.append({
                        "node_alias": node["alias"],
                        "field_id": item["left"].get("fieldId"),
                        "value": right.get("value"),
                        "context": f"filter in {node['alias']}"
                    })

        # branch condition 中的 option 值
        for path in config.get("paths", []):
            cond = path.get("condition")
            if cond:
                right = cond.get("right", {})
                if right.get("kind") == "literal":
                    refs.append({
                        "node_alias": node["alias"],
                        "field_id": cond["left"].get("fieldId"),
                        "value": right.get("value"),
                        "context": f"branch path '{path.get('name')}' in {node['alias']}"
                    })

        # update_record fields 中的 option 值
        for field in config.get("fields", []):
            value = field.get("value")
            if isinstance(value, str) and is_uuid(value):
                refs.append({
                    "node_alias": node["alias"],
                    "field_id": field.get("fieldId"),
                    "value": value,
                    "context": f"update field in {node['alias']}"
                })

    return refs


def is_uuid(s: str) -> bool:
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', s, re.I))


def validate_static(contract: dict) -> tuple[bool, list[str]]:
    """静态校验（不需 hap CLI）。"""
    errors = []
    meta = contract.get("meta", {})
    target = contract.get("target", {})
    trigger = contract.get("trigger", {})
    nodes = contract.get("nodes", [])
    refs = contract.get("field_references", [])

    # 1. 必填字段
    if not target.get("org_id"):
        errors.append("target.org_id 缺失")
    if not target.get("app_id"):
        errors.append("target.app_id 缺失")
    if not meta.get("workflow_name"):
        errors.append("meta.workflow_name 缺失")
    if not nodes:
        errors.append("nodes 为空")

    # 2. alias 唯一性
    aliases = [n["alias"] for n in nodes]
    dupes = [a for a in aliases if aliases.count(a) > 1]
    if dupes:
        errors.append(f"nodeAlias 重复: {list(set(dupes))}")

    # 3. 每个节点有必需字段
    for node in nodes:
        if "alias" not in node:
            errors.append(f"节点缺少 alias: {node}")
            continue
        if "nodeType" not in node:
            errors.append(f"节点 {node['alias']} 缺少 nodeType")
        if "config" not in node:
            errors.append(f"节点 {node['alias']} 缺少 config")

    # 4. 分支条件 left.node 检查
    for node in nodes:
        if node.get("nodeType") == "branch":
            config = node.get("config", {})
            # resultFlow 分支不需要 left.node
            if config.get("resultFlow"):
                continue
            for path in config.get("paths", []):
                cond = path.get("condition")
                if not cond:
                    continue
                left = cond.get("left", {})
                left_node = left.get("node", "")
                if left_node == node["alias"]:
                    errors.append(
                        f"分支 {node['alias']} 路径 '{path.get('name')}' 的 "
                        f"condition.left.node 引用了分支自身 ({node['alias']})，"
                        f"应引用数据源节点"
                    )
                if left_node not in aliases:
                    errors.append(
                        f"分支 {node['alias']} 路径 '{path.get('name')}' 的 "
                        f"condition.left.node='{left_node}'，"
                        f"但 '{left_node}' 不在节点 alias 列表中"
                    )

    # 5. 作用域隔离检查
    for node in nodes:
        if node.get("nodeType") == "approve":
            target_node = node.get("config", {}).get("target", {}).get("node", "")
            if target_node and target_node != "approval_start":
                errors.append(
                    f"审批步骤 {node['alias']} target.node='{target_node}'，"
                    f"应为 'approval_start'"
                )

    # 6. 子流程内部检查
    for node in nodes:
        if node.get("nodeType") == "sub_process":
            inner_nodes = node.get("config", {}).get("process", {}).get("nodes", [])
            for in_node in inner_nodes:
                if in_node.get("nodeAlias") == "sub_trigger":
                    continue
                if in_node.get("nodeAlias") == "approval_start":
                    continue
                target_node = in_node.get("config", {}).get("target", {}).get("node", "")
                if target_node == "sub_trigger":
                    continue
                if target_node == "approval_start":
                    continue
                if target_node not in [n.get("nodeAlias") for n in inner_nodes]:
                    pass  # 可能引用外部，不在此检查

    # 7. 字段引用格式检查
    for ref in refs:
        fid = ref.get("fieldId", "")
        if not fid:
            errors.append(f"field_references 中缺少 fieldId: {ref}")

    return len(errors) == 0, errors


def print_results(passed: bool, static_errors: list[str]):
    """输出预检结果。"""
    print()
    print("=" * 60)
    print("  HAP Workflow Preflight Check")
    print("=" * 60)
    print()

    if passed and not static_errors:
        print("✅ 静态校验全部通过")
        print()
        print("下一步：运行 hap CLI 验证以下 ID 在平台上存在：")
        print("  hap worksheet info WORKSHEET_ID --json")
        print()
        sys.exit(0)

    if static_errors:
        print(f"❌ 静态校验失败 ({len(static_errors)} 项)：")
        for i, err in enumerate(static_errors, 1):
            print(f"  {i}. {err}")
        print()

    print("修正执行合约后重新运行预检。")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 preflight.py <execution_contract.json>")
        sys.exit(1)

    contract_path = sys.argv[1]
    if not Path(contract_path).exists():
        print(f"文件不存在: {contract_path}")
        sys.exit(1)

    contract = load_contract(contract_path)

    print(f"合约: {contract['meta'].get('workflow_name', 'Unknown')}")
    print(f"节点数: {len(contract.get('nodes', []))}")
    print(f"字段引用: {len(contract.get('field_references', []))}")

    passed, errors = validate_static(contract)

    # 提取 option 引用
    option_refs = extract_option_refs(contract.get("nodes", []))
    if option_refs:
        print(f"option 引用: {len(option_refs)}")
        for ref in option_refs:
            print(f"  - {ref['context']}: fieldId={ref['field_id']}, value={ref['value']}")

    print_results(passed, errors)


if __name__ == "__main__":
    main()
