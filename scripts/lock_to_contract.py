#!/usr/bin/env python3
"""Strictly derive one hap-flow-exec contract from execution_lock.json.

The converter only renames documented boundary fields.  It never invents IDs,
node aliases, action modes, node configs, dependencies, or publish order.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

from agent_prepare import compute_lock_digest
from contract_compat import validate_exec, validate_lock


WORKSHEET_NODE_TYPES = {
    "get_single",
    "get_multiple",
    "update_record",
    "create_record",
    "delete_record",
}
PROCESS_NODE_TYPES = {"approval_block", "sub_process"}
OPTION_FIELD_TYPES = {"SingleSelect", "MultiSelect", "Dropdown"}
BASIC_GATES = {
    "gate_1_dependency": {"pass"},
    "gate_2_logic": {"pass"},
    "gate_3_timing": {"pass", "n/a"},
    "gate_4_fields": {"pass"},
    "gate_5_platform": {"pass"},
    "gate_6_reasoning": {"pass"},
}
AGENT_GATES = ("agent_1_logic", "agent_2_platform")


class ConversionError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("execution_lock 无法严格转换")
        self.errors = errors


def _error(errors: list[dict], path: str, detail: str) -> None:
    errors.append({"path": path, "detail": detail})


def _validate_conversion_gates(lock: dict, errors: list[dict]) -> None:
    gates = lock.get("gates")
    if not isinstance(gates, dict):
        _error(errors, "$.gates", "gates 缺失或不是对象")
        return

    for gate_name, allowed_results in BASIC_GATES.items():
        gate = gates.get(gate_name)
        result = gate.get("result") if isinstance(gate, dict) else None
        if result not in allowed_results:
            _error(
                errors,
                f"$.gates.{gate_name}.result",
                (
                    f"{gate_name} 必须为 {sorted(allowed_results)}，"
                    f"实际为 {result!r}"
                ),
            )

    for gate_name in AGENT_GATES:
        gate = gates.get(gate_name)
        result = gate.get("result") if isinstance(gate, dict) else None
        if result != "pass":
            _error(
                errors,
                f"$.gates.{gate_name}.result",
                f"{gate_name} 必须为 pass，实际为 {result!r}",
            )

    verification = lock.get("verification")
    if not isinstance(verification, dict):
        _error(errors, "$.verification", "缺少顶层 verification 裁决")
        return
    agents = verification.get("verification_agents")
    semantic_verdict = (
        agents.get("semantic_verdict") if isinstance(agents, dict) else None
    )
    if semantic_verdict != "pass":
        _error(
            errors,
            "$.verification.verification_agents.semantic_verdict",
            (
                "Agent 语义裁决必须为 pass，"
                f"实际为 {semantic_verdict!r}"
            ),
        )
    expected_digest = compute_lock_digest(lock)
    if verification.get("input_digest") != expected_digest:
        _error(
            errors,
            "$.verification.input_digest",
            "verification 摘要与当前 execution_lock 设计内容不一致",
        )
    if isinstance(agents, dict):
        if agents.get("completeness") != "pass":
            _error(
                errors,
                "$.verification.verification_agents.completeness",
                "Agent 输出完整性必须为 pass",
            )
        required_agents = set(AGENT_GATES)
        actual_agents = set(agents.get("agents", []))
        if actual_agents != required_agents:
            _error(
                errors,
                "$.verification.verification_agents.agents",
                f"必须包含且仅包含 {sorted(required_agents)}",
            )
        digests = agents.get("agent_input_digests")
        if not isinstance(digests, dict):
            _error(
                errors,
                "$.verification.verification_agents.agent_input_digests",
                "缺少 Agent 输入摘要",
            )
        else:
            for agent_id in required_agents:
                if digests.get(agent_id) != expected_digest:
                    _error(
                        errors,
                        (
                            "$.verification.verification_agents."
                            f"agent_input_digests.{agent_id}"
                        ),
                        "Agent 摘要与当前 lock 不一致，必须重新运行 Agent",
                    )


def _canonical_id(
    node: dict,
    canonical: str,
    legacy: str,
    path: str,
    errors: list[dict],
) -> object:
    canonical_value = node.get(canonical)
    legacy_value = node.get(legacy)
    if isinstance(legacy_value, str) and legacy_value.isdigit():
        legacy_value = int(legacy_value)
    if (
        canonical_value is not None
        and legacy_value is not None
        and canonical_value != legacy_value
    ):
        _error(
            errors,
            f"{path}.{canonical}",
            (
                f"{canonical}={canonical_value} 与旧字段 "
                f"{legacy}={legacy_value} 冲突"
            ),
        )
    return canonical_value if canonical_value is not None else legacy_value


def _validate_exact_config(
    node: dict,
    path: str,
    errors: list[dict],
) -> None:
    config = node.get("config")
    if not isinstance(config, dict):
        _error(errors, f"{path}.config", "config 缺失或不是对象")
        return
    node_type = node.get("node_type")
    if node_type in WORKSHEET_NODE_TYPES:
        worksheet_id = config.get("worksheet")
        if not isinstance(worksheet_id, str) or not worksheet_id:
            _error(
                errors,
                f"{path}.config.worksheet",
                f"{node_type} 缺少精确 worksheet ID",
            )
    if node_type == "branch" and not isinstance(config.get("paths"), list):
        _error(
            errors,
            f"{path}.config.paths",
            "branch 缺少明确的 paths 配置",
        )
    if node_type in PROCESS_NODE_TYPES and not isinstance(
        config.get("process"), dict
    ):
        _error(
            errors,
            f"{path}.config.process",
            f"{node_type} 缺少明确的 process 配置",
        )
    if node_type in {"update_record", "create_record"}:
        fields = config.get("fields")
        if not isinstance(fields, list) or not fields:
            _error(
                errors,
                f"{path}.config.fields",
                f"{node_type} 缺少明确的字段写入配置",
            )
        else:
            for index, field in enumerate(fields):
                if not isinstance(field, dict) or not field.get("fieldId"):
                    _error(
                        errors,
                        f"{path}.config.fields[{index}].fieldId",
                        "写入字段缺少 fieldId",
                    )

    def walk(value: object, current_path: str) -> None:
        if isinstance(value, dict):
            if "left" in value and isinstance(value["left"], dict):
                left = value["left"]
                if not left.get("fieldId"):
                    _error(
                        errors,
                        f"{current_path}.left.fieldId",
                        "条件左值缺少 fieldId",
                    )
            for key, child in value.items():
                child_path = f"{current_path}.{key}"
                if key in (
                    "fieldId",
                    "worksheet",
                    "worksheet_id",
                    "app_id",
                ) and (not isinstance(child, str) or not child):
                    _error(errors, child_path, f"{key} ID 不能为空")
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{current_path}[{index}]")

    walk(config, f"{path}.config")


def _option_keys(
    value: object,
    field_type: str,
    path: str,
    errors: list[dict],
) -> object:
    values = value if isinstance(value, list) else [value]
    if field_type == "MultiSelect" and not isinstance(value, list):
        _error(errors, path, "MultiSelect 必须使用 {key, label} 数组")
    keys = []
    for index, item in enumerate(values):
        item_path = f"{path}[{index}]" if isinstance(value, list) else path
        if not isinstance(item, dict):
            _error(
                errors,
                item_path,
                "选项值必须是 {key, label}，转换器拒绝猜测中文 label",
            )
            continue
        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not key:
            _error(errors, f"{item_path}.key", "option key 缺失")
            continue
        if not isinstance(label, str) or not label:
            _error(errors, f"{item_path}.label", "option label 缺失")
        keys.append(key)
    if isinstance(value, list):
        return keys
    return keys[0] if keys else None


def _normalize_config_options(
    value: object,
    field_types: dict[str, str],
    path: str,
    errors: list[dict],
) -> object:
    if isinstance(value, list):
        return [
            _normalize_config_options(
                item,
                field_types,
                f"{path}[{index}]",
                errors,
            )
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        return copy.deepcopy(value)

    normalized = {}
    condition_field_id = None
    left = value.get("left")
    if isinstance(left, dict):
        condition_field_id = left.get("fieldId")
    for key, child in value.items():
        child_path = f"{path}.{key}"
        if key == "value" and value.get("fieldId") in field_types:
            field_type = field_types[value["fieldId"]]
            if field_type in OPTION_FIELD_TYPES:
                normalized[key] = _option_keys(
                    child,
                    field_type,
                    child_path,
                    errors,
                )
                continue
        if (
            key == "right"
            and condition_field_id in field_types
            and isinstance(child, dict)
            and child.get("kind") == "literal"
            and "value" in child
            and field_types[condition_field_id] in OPTION_FIELD_TYPES
        ):
            normalized_right = copy.deepcopy(child)
            normalized_right["value"] = _option_keys(
                child.get("value"),
                field_types[condition_field_id],
                f"{child_path}.value",
                errors,
            )
            normalized[key] = normalized_right
            continue
        normalized[key] = _normalize_config_options(
            child,
            field_types,
            child_path,
            errors,
        )
    return normalized


def _select_workflow(
    lock: dict,
    workflow_name: str | None,
    errors: list[dict],
) -> tuple[dict | None, int | None]:
    workflows = lock.get("workflows", [])
    if workflow_name:
        matches = [
            (index, workflow)
            for index, workflow in enumerate(workflows)
            if isinstance(workflow, dict)
            and workflow.get("name") == workflow_name
        ]
        if len(matches) != 1:
            _error(
                errors,
                "$.workflows",
                f"工作流名称必须唯一匹配，实际匹配 {len(matches)} 个",
            )
            return None, None
        index, workflow = matches[0]
        return workflow, index
    if len(workflows) != 1:
        _error(
            errors,
            "$.workflows",
            (
                f"lock 含 {len(workflows)} 个工作流；必须用 --workflow "
                "明确选择，转换器不会猜测"
            ),
        )
        return None, None
    workflow = workflows[0]
    if not isinstance(workflow, dict):
        _error(errors, "$.workflows[0]", "工作流必须是对象")
        return None, None
    return workflow, 0


def convert_lock(
    lock: dict,
    workflow_name: str | None = None,
) -> dict:
    """Convert a validated lock to one workflow execution contract."""
    errors = [
        {"path": item.get("path", "$"), "detail": item.get("detail", "")}
        for item in validate_lock(lock)
    ]
    _validate_conversion_gates(lock, errors)
    workflow, workflow_index = _select_workflow(lock, workflow_name, errors)
    if workflow is None or workflow_index is None:
        raise ConversionError(errors)

    workflow_path = f"$.workflows[{workflow_index}]"
    target = lock.get("target", {})
    worksheet_id = workflow.get("worksheet_id")
    trigger = workflow.get("trigger")

    sheets = [
        sheet
        for sheet in lock.get("sheets", [])
        if isinstance(sheet, dict)
        and sheet.get("name") == workflow.get("trigger_sheet")
    ]
    if len(sheets) != 1:
        _error(
            errors,
            f"{workflow_path}.trigger_sheet",
            (
                "trigger_sheet 必须唯一匹配 sheets；"
                f"实际匹配 {len(sheets)} 个"
            ),
        )
    elif sheets[0].get("worksheet_id") != worksheet_id:
        _error(
            errors,
            f"{workflow_path}.worksheet_id",
            "workflow.worksheet_id 与 trigger_sheet 的 worksheet_id 不一致",
        )

    if isinstance(trigger, dict) and isinstance(trigger.get("config"), dict):
        trigger_config = trigger["config"]
        if trigger_config.get("worksheet_id") != worksheet_id:
            _error(
                errors,
                f"{workflow_path}.trigger.config.worksheet_id",
                "触发器 worksheet_id 与工作流 worksheet_id 不一致",
            )
        if trigger_config.get("app_id") != target.get("app_id"):
            _error(
                errors,
                f"{workflow_path}.trigger.config.app_id",
                "触发器 app_id 与 lock.target.app_id 不一致",
            )

    field_types = {
        reference.get("field_id"): reference.get("type")
        for reference in workflow.get("field_references", [])
        if isinstance(reference, dict) and reference.get("field_id")
    }
    converted_nodes = []
    for node_index, node in enumerate(workflow.get("node_chain", [])):
        path = f"{workflow_path}.node_chain[{node_index}]"
        if not isinstance(node, dict):
            _error(errors, path, "节点必须是对象")
            continue
        type_id = _canonical_id(
            node,
            "type_id",
            "typeId",
            path,
            errors,
        )
        action_id = _canonical_id(
            node,
            "action_id",
            "actionId",
            path,
            errors,
        )
        _validate_exact_config(node, path, errors)
        normalized_config = _normalize_config_options(
            node.get("config"),
            field_types,
            f"{path}.config",
            errors,
        )
        converted = {
            "seq": node.get("index"),
            "alias": node.get("alias"),
            "nodeType": node.get("node_type"),
            "type_id": type_id,
            "name": node.get("name"),
            "config": normalized_config,
        }
        if action_id is not None:
            converted["action_id"] = action_id
        converted_nodes.append(converted)

    converted_references = []
    for reference in workflow.get("field_references", []):
        if not isinstance(reference, dict):
            continue
        converted_reference = {
            "fieldId": reference.get("field_id"),
            "worksheet": reference.get("worksheet_id"),
            "fieldName": reference.get("field_name"),
            "type": reference.get("type"),
        }
        if "expected_options" in reference:
            converted_reference["expected_options"] = copy.deepcopy(
                reference["expected_options"]
            )
        if "relation_worksheet_id" in reference:
            converted_reference["relation_worksheet_id"] = reference[
                "relation_worksheet_id"
            ]
        converted_references.append(converted_reference)

    meta = lock.get("meta", {})
    contract = {
        "meta": {
            "schema_version": "1.0",
            "source_design": meta.get("source_design"),
            "project": meta.get("project"),
            "created": meta.get("created"),
            "workflow_name": workflow.get("name"),
            "node_count": workflow.get("node_count"),
        },
        "target": {
            "org_id": target.get("org_id"),
            "app_id": target.get("app_id"),
            "worksheet_id": worksheet_id,
        },
        "trigger": copy.deepcopy(trigger),
        "nodes": converted_nodes,
        "field_references": converted_references,
        "dependencies": copy.deepcopy(workflow.get("dependencies")),
        "publish_order": copy.deepcopy(workflow.get("publish_order")),
    }

    for violation in validate_exec(contract):
        _error(
            errors,
            violation.get("path", "$"),
            violation.get("detail", ""),
        )
    if errors:
        # De-duplicate errors produced by lock and derived-contract validation.
        unique = []
        seen = set()
        for error in errors:
            key = (error["path"], error["detail"])
            if key not in seen:
                seen.add(key)
                unique.append(error)
        raise ConversionError(unique)
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(
        description="严格转换 execution_lock → hap-flow-exec contract"
    )
    parser.add_argument("lock_file", help="execution_lock.json 路径")
    parser.add_argument(
        "--workflow",
        help="多工作流 lock 中要转换的精确工作流名称",
    )
    parser.add_argument("--output", help="输出 execution_contract.json 路径")
    args = parser.parse_args()

    try:
        lock = json.loads(
            Path(args.lock_file).read_text(encoding="utf-8")
        )
        contract = convert_lock(lock, args.workflow)
    except FileNotFoundError:
        print(
            json.dumps(
                {"verdict": "fail", "error": f"文件不存在: {args.lock_file}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"verdict": "fail", "error": f"JSON 解析失败: {exc}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
    except ConversionError as exc:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "execution_lock 无法严格转换",
                    "violations": exc.errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    output = json.dumps(contract, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "verdict": "pass",
                    "output": str(output_path),
                    "workflow": contract["meta"]["workflow_name"],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(output)


if __name__ == "__main__":
    main()
