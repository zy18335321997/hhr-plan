#!/usr/bin/env python3
"""Validate execution locks and derived hap-flow-exec contracts.

Commands:
  contract_compat.py validate-lock execution_lock.json
  contract_compat.py validate-exec execution_contract.json
  contract_compat.py validate FILE.json
  contract_compat.py check-schema

``validate`` auto-detects the document kind.  The lock is the design source of
truth; an execution contract is a derived, workflow-specific artifact.
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = (
    SKILL_DIR
    / "references"
    / "schemas"
    / "execution-lock-validation-schema.json"
)
WORKFLOW_OUTPUT = Path(os.path.expanduser("~/Documents/workflow-output"))
AGENT_GATE_NAMES = {
    "agent_1_logic",
    "agent_2_platform",
    "agent_3_audit",
}


def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as file:
        return json.load(file)


def collect_violation(
    violations: list[dict],
    severity: str,
    path: str,
    detail: str,
) -> None:
    violations.append({"severity": severity, "path": path, "detail": detail})


def _required_keys(
    value: object,
    required: list[str],
    path: str,
    violations: list[dict],
    severity: str = "high",
) -> None:
    if not isinstance(value, dict):
        collect_violation(violations, severity, path, f"{path} 必须是对象")
        return
    for key in required:
        if key not in value:
            collect_violation(
                violations,
                severity,
                f"{path}.{key}",
                f"缺少字段: {key}",
            )


def _require_nonempty(
    value: object,
    path: str,
    violations: list[dict],
    severity: str = "high",
) -> None:
    if not isinstance(value, str) or not value.strip():
        collect_violation(violations, severity, path, f"{path} 缺失或为空")


def _canonical_node_id(
    node: dict,
    canonical: str,
    legacy: str,
    path: str,
    violations: list[dict],
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
        collect_violation(
            violations,
            "high",
            f"{path}.{canonical}",
            (
                f"{canonical}={canonical_value} 与兼容字段 "
                f"{legacy}={legacy_value} 冲突"
            ),
        )
    return canonical_value if canonical_value is not None else legacy_value


def validate_lock(data: dict, schema: dict | None = None) -> list[dict]:
    """Validate canonical execution_lock structure.

    ``typeId`` and ``actionId`` are accepted only as legacy input aliases.
    Conflicting canonical and legacy values are rejected.
    """
    schema = schema or load_schema()
    violations: list[dict] = []
    if not isinstance(data, dict):
        return [
            {
                "severity": "high",
                "path": "$",
                "detail": "execution_lock 顶层必须是对象",
            }
        ]

    _required_keys(data, schema.get("required_top_keys", []), "$", violations)

    meta = data.get("meta")
    meta_schema = schema.get("meta", {})
    _required_keys(
        meta,
        meta_schema.get("required_keys", []),
        "$.meta",
        violations,
    )
    if isinstance(meta, dict):
        expected_schema_version = schema.get("schema_version")
        if meta.get("schema_version") != expected_schema_version:
            collect_violation(
                violations,
                "high",
                "$.meta.schema_version",
                (
                    f"lock schema_version 必须为 {expected_schema_version}，"
                    f"实际为 {meta.get('schema_version')!r}"
                ),
            )
        if meta.get("mode") not in meta_schema.get("valid_modes", []):
            collect_violation(
                violations,
                "medium",
                "$.meta.mode",
                f"mode 值无效: {meta.get('mode')}",
            )
        if meta.get("confidence") not in meta_schema.get(
            "valid_confidence", []
        ):
            collect_violation(
                violations,
                "medium",
                "$.meta.confidence",
                f"confidence 值无效: {meta.get('confidence')}",
            )
        for key in ("project", "source_design"):
            _require_nonempty(meta.get(key), f"$.meta.{key}", violations)

    target = data.get("target")
    target_schema = schema.get("target", {})
    _required_keys(
        target,
        target_schema.get("required_keys", []),
        "$.target",
        violations,
    )
    if isinstance(target, dict):
        for key in target_schema.get("required_keys", []):
            _require_nonempty(target.get(key), f"$.target.{key}", violations)

    naming = data.get("naming")
    _required_keys(
        naming,
        schema.get("naming", {}).get("required_keys", []),
        "$.naming",
        violations,
        severity="medium",
    )

    sheets = data.get("sheets")
    sheets_schema = schema.get("sheets", {})
    if not isinstance(sheets, list):
        collect_violation(violations, "high", "$.sheets", "sheets 必须是数组")
    else:
        for index, sheet in enumerate(sheets):
            path = f"$.sheets[{index}]"
            _required_keys(
                sheet,
                sheets_schema.get("required_keys", []),
                path,
                violations,
            )
            if not isinstance(sheet, dict):
                continue
            _require_nonempty(sheet.get("name"), f"{path}.name", violations)
            _require_nonempty(
                sheet.get("worksheet_id"),
                f"{path}.worksheet_id",
                violations,
            )
            fields = sheet.get("fields")
            if not isinstance(fields, list):
                collect_violation(
                    violations,
                    "high",
                    f"{path}.fields",
                    "fields 必须是数组",
                )
                continue
            for field_index, field in enumerate(fields):
                field_path = f"{path}.fields[{field_index}]"
                _required_keys(
                    field,
                    sheets_schema.get("fields_required_keys", []),
                    field_path,
                    violations,
                    severity="medium",
                )
                if not isinstance(field, dict):
                    continue
                _require_nonempty(
                    field.get("field_id"),
                    f"{field_path}.field_id",
                    violations,
                )
                field_type = field.get("type")
                valid_types = sheets_schema.get("valid_field_types", [])
                if field_type and valid_types and field_type not in valid_types:
                    collect_violation(
                        violations,
                        "low",
                        f"{field_path}.type",
                        f"未登记的字段类型: {field_type}",
                    )

    associations = data.get("associations")
    association_schema = schema.get("associations", {})
    if not isinstance(associations, list):
        collect_violation(
            violations,
            "high",
            "$.associations",
            "associations 必须是数组",
        )
    else:
        for index, association in enumerate(associations):
            path = f"$.associations[{index}]"
            _required_keys(
                association,
                association_schema.get("required_keys", []),
                path,
                violations,
                severity="medium",
            )
            if isinstance(association, dict):
                _require_nonempty(
                    association.get("field_id"),
                    f"{path}.field_id",
                    violations,
                )

    workflows = data.get("workflows")
    workflow_schema = schema.get("workflows", {})
    valid_type_ids = set(workflow_schema.get("valid_type_ids", []))
    valid_action_ids = {
        int(type_id): set(action_ids)
        for type_id, action_ids in workflow_schema.get(
            "valid_action_ids", {}
        ).items()
    }
    if not isinstance(workflows, list):
        collect_violation(
            violations,
            "high",
            "$.workflows",
            "workflows 必须是数组",
        )
    else:
        for workflow_index, workflow in enumerate(workflows):
            path = f"$.workflows[{workflow_index}]"
            _required_keys(
                workflow,
                workflow_schema.get("required_keys", []),
                path,
                violations,
            )
            if not isinstance(workflow, dict):
                continue
            for key in ("name", "worksheet_id"):
                _require_nonempty(
                    workflow.get(key),
                    f"{path}.{key}",
                    violations,
                )
            trigger = workflow.get("trigger")
            _required_keys(
                trigger,
                ["type", "config"],
                f"{path}.trigger",
                violations,
            )
            if isinstance(trigger, dict):
                trigger_type = trigger.get("type")
                valid_trigger_types = workflow_schema.get(
                    "valid_trigger_types", []
                )
                if trigger_type not in valid_trigger_types:
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.trigger.type",
                        f"trigger.type 值无效: {trigger_type!r}",
                    )
                if workflow.get("trigger_type") != trigger_type:
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.trigger_type",
                        (
                            "trigger_type 必须与 trigger.type 一致，"
                            f"实际为 {workflow.get('trigger_type')!r} / "
                            f"{trigger_type!r}"
                        ),
                    )
                trigger_config = trigger.get("config")
                if not isinstance(trigger_config, dict):
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.trigger.config",
                        "trigger.config 必须是对象",
                    )
                else:
                    for key in ("worksheet_id", "app_id"):
                        _require_nonempty(
                            trigger_config.get(key),
                            f"{path}.trigger.config.{key}",
                            violations,
                        )

            node_chain = workflow.get("node_chain")
            if not isinstance(node_chain, list):
                collect_violation(
                    violations,
                    "high",
                    f"{path}.node_chain",
                    "node_chain 必须是数组",
                )
                continue
            if workflow.get("node_count") != len(node_chain):
                collect_violation(
                    violations,
                    "high",
                    f"{path}.node_count",
                    (
                        f"node_count={workflow.get('node_count')} 与 "
                        f"node_chain 长度 {len(node_chain)} 不一致"
                    ),
                )
            aliases: set[str] = set()
            for node_index, node in enumerate(node_chain):
                node_path = f"{path}.node_chain[{node_index}]"
                if not isinstance(node, dict):
                    collect_violation(
                        violations,
                        "high",
                        node_path,
                        "节点必须是对象",
                    )
                    continue
                for key in workflow_schema.get(
                    "node_chain_required_keys", []
                ):
                    if key == "type_id":
                        continue
                    if key not in node:
                        collect_violation(
                            violations,
                            "high",
                            f"{node_path}.{key}",
                            f"节点缺少字段: {key}",
                        )
                alias = node.get("alias")
                _require_nonempty(alias, f"{node_path}.alias", violations)
                if isinstance(alias, str) and alias:
                    if alias in aliases:
                        collect_violation(
                            violations,
                            "high",
                            f"{node_path}.alias",
                            f"节点 alias 重复: {alias}",
                        )
                    aliases.add(alias)

                type_id = _canonical_node_id(
                    node,
                    "type_id",
                    "typeId",
                    node_path,
                    violations,
                )
                if type_id is None:
                    collect_violation(
                        violations,
                        "high",
                        f"{node_path}.type_id",
                        "节点缺少 type_id（兼容读取 typeId）",
                    )
                elif not isinstance(type_id, int) or type_id not in valid_type_ids:
                    collect_violation(
                        violations,
                        "high",
                        f"{node_path}.type_id",
                        f"type_id={type_id} 不在有效列表中",
                    )
                elif type_id == 4:
                    collect_violation(
                        violations,
                        "high",
                        f"{node_path}.type_id",
                        "type_id=4 已弃用，必须使用 type_id=26",
                    )

                action_id = _canonical_node_id(
                    node,
                    "action_id",
                    "actionId",
                    node_path,
                    violations,
                )
                if type_id in valid_action_ids:
                    if action_id is None:
                        collect_violation(
                            violations,
                            "high",
                            f"{node_path}.action_id",
                            "该节点缺少必需的 action_id",
                        )
                    elif action_id not in valid_action_ids[type_id]:
                        collect_violation(
                            violations,
                            "high",
                            f"{node_path}.action_id",
                            (
                                f"action_id={action_id} 对 type_id={type_id} "
                                "无效"
                            ),
                        )
                if "config" not in node:
                    collect_violation(
                        violations,
                        "high",
                        f"{node_path}.config",
                        "节点缺少 config；不能由转换器猜测",
                    )
                elif not isinstance(node.get("config"), dict):
                    collect_violation(
                        violations,
                        "high",
                        f"{node_path}.config",
                        "config 必须是对象",
                    )

            references = workflow.get("field_references")
            if not isinstance(references, list):
                collect_violation(
                    violations,
                    "high",
                    f"{path}.field_references",
                    "field_references 必须是数组",
                )
            else:
                for ref_index, reference in enumerate(references):
                    ref_path = f"{path}.field_references[{ref_index}]"
                    _required_keys(
                        reference,
                        workflow_schema.get(
                            "field_reference_required_keys", []
                        ),
                        ref_path,
                        violations,
                    )
                    if isinstance(reference, dict):
                        for key in ("field_id", "worksheet_id"):
                            _require_nonempty(
                                reference.get(key),
                                f"{ref_path}.{key}",
                                violations,
                            )

    gates = data.get("gates")
    gate_schema = schema.get("gates", {})
    _required_keys(
        gates,
        gate_schema.get("required_keys", []),
        "$.gates",
        violations,
        severity="medium",
    )
    if isinstance(gates, dict):
        defined_gate_names = set(gate_schema.get("required_keys", []))
        allowed_gate_names = defined_gate_names | AGENT_GATE_NAMES
        for gate_name in sorted(set(gates) - allowed_gate_names):
            collect_violation(
                violations,
                "medium",
                f"$.gates.{gate_name}",
                f"未定义 gate: {gate_name}",
            )
        for gate_name in sorted(set(gates) & allowed_gate_names):
            gate = gates[gate_name]
            if not isinstance(gate, dict):
                collect_violation(
                    violations,
                    "medium",
                    f"$.gates.{gate_name}",
                    "gate 必须是对象",
                )
                continue
            result = gate.get("result")
            if result not in gate_schema.get("valid_gate_results", []):
                collect_violation(
                    violations,
                    "medium",
                    f"$.gates.{gate_name}.result",
                    f"gate result 值无效: {result}",
                )
    return violations


def validate_exec(data: dict) -> list[dict]:
    """Validate the workflow-specific contract consumed by hap-flow-exec."""
    violations: list[dict] = []
    workflow_schema = load_schema().get("workflows", {})
    valid_type_ids = set(workflow_schema.get("valid_type_ids", []))
    valid_action_ids = {
        int(type_id): set(action_ids)
        for type_id, action_ids in workflow_schema.get(
            "valid_action_ids", {}
        ).items()
    }
    if not isinstance(data, dict):
        return [
            {
                "severity": "high",
                "path": "$",
                "detail": "execution_contract 顶层必须是对象",
            }
        ]
    required_top = [
        "meta",
        "target",
        "trigger",
        "nodes",
        "field_references",
        "dependencies",
        "publish_order",
    ]
    _required_keys(data, required_top, "$", violations)

    meta = data.get("meta")
    _required_keys(
        meta,
        [
            "schema_version",
            "source_design",
            "project",
            "created",
            "workflow_name",
            "node_count",
        ],
        "$.meta",
        violations,
    )
    if isinstance(meta, dict):
        if meta.get("schema_version") != "1.0":
            collect_violation(
                violations,
                "high",
                "$.meta.schema_version",
                (
                    "execution contract schema_version 必须为 '1.0'，"
                    f"实际为 {meta.get('schema_version')!r}"
                ),
            )
        for key in ("source_design", "project", "workflow_name"):
            _require_nonempty(meta.get(key), f"$.meta.{key}", violations)

    target = data.get("target")
    _required_keys(
        target,
        ["org_id", "app_id", "worksheet_id"],
        "$.target",
        violations,
    )
    if isinstance(target, dict):
        for key in ("org_id", "app_id", "worksheet_id"):
            _require_nonempty(target.get(key), f"$.target.{key}", violations)

    trigger = data.get("trigger")
    _required_keys(trigger, ["type", "config"], "$.trigger", violations)
    if isinstance(trigger, dict):
        trigger_type = trigger.get("type")
        if trigger_type not in workflow_schema.get("valid_trigger_types", []):
            collect_violation(
                violations,
                "high",
                "$.trigger.type",
                f"trigger.type 值无效: {trigger_type!r}",
            )
        if not isinstance(trigger.get("config"), dict):
            collect_violation(
                violations,
                "high",
                "$.trigger.config",
                "trigger.config 必须是对象",
            )

    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        collect_violation(violations, "high", "$.nodes", "nodes 必须是数组")
    else:
        if not nodes:
            collect_violation(violations, "high", "$.nodes", "nodes 不能为空")
        if isinstance(meta, dict) and meta.get("node_count") != len(nodes):
            collect_violation(
                violations,
                "high",
                "$.meta.node_count",
                (
                    f"node_count={meta.get('node_count')} 与 nodes 长度 "
                    f"{len(nodes)} 不一致"
                ),
            )
        aliases: set[str] = set()
        for index, node in enumerate(nodes):
            path = f"$.nodes[{index}]"
            _required_keys(
                node,
                ["seq", "alias", "nodeType", "type_id", "name", "config"],
                path,
                violations,
            )
            if not isinstance(node, dict):
                continue
            alias = node.get("alias")
            _require_nonempty(alias, f"{path}.alias", violations)
            if isinstance(alias, str) and alias:
                if alias in aliases:
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.alias",
                        f"节点 alias 重复: {alias}",
                    )
                aliases.add(alias)
            _require_nonempty(node.get("nodeType"), f"{path}.nodeType", violations)
            type_id = node.get("type_id")
            if type(type_id) is not int or type_id not in valid_type_ids:
                collect_violation(
                    violations,
                    "high",
                    f"{path}.type_id",
                    f"type_id={type_id!r} 不在有效列表中",
                )
            action_id = node.get("action_id")
            if type_id in valid_action_ids:
                if type(action_id) is not int:
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.action_id",
                        "该节点缺少有效的 action_id",
                    )
                elif action_id not in valid_action_ids[type_id]:
                    collect_violation(
                        violations,
                        "high",
                        f"{path}.action_id",
                        (
                            f"action_id={action_id} 对 type_id={type_id} "
                            "无效"
                        ),
                    )
            if not isinstance(node.get("config"), dict):
                collect_violation(
                    violations,
                    "high",
                    f"{path}.config",
                    "config 必须是对象",
                )

    references = data.get("field_references")
    if not isinstance(references, list):
        collect_violation(
            violations,
            "high",
            "$.field_references",
            "field_references 必须是数组",
        )
    else:
        for index, reference in enumerate(references):
            path = f"$.field_references[{index}]"
            _required_keys(
                reference,
                ["fieldId", "worksheet", "fieldName", "type"],
                path,
                violations,
            )
            if isinstance(reference, dict):
                for key in ("fieldId", "worksheet"):
                    _require_nonempty(
                        reference.get(key),
                        f"{path}.{key}",
                        violations,
                    )
    if not isinstance(data.get("dependencies"), dict):
        collect_violation(
            violations,
            "high",
            "$.dependencies",
            "dependencies 必须是对象",
        )
    if not isinstance(data.get("publish_order"), list):
        collect_violation(
            violations,
            "high",
            "$.publish_order",
            "publish_order 必须是数组",
        )
    return violations


# Backward-compatible function name used by older callers.
validate_contract = validate_lock


def detect_document_kind(data: dict) -> str | None:
    lock_markers = {"workflows", "sheets", "gates"}
    exec_markers = {"target", "trigger", "nodes", "field_references"}
    is_lock = lock_markers.issubset(data)
    is_exec = exec_markers.issubset(data)
    if is_lock and not is_exec:
        return "lock"
    if is_exec and not is_lock:
        return "exec"
    return None


def _extract_platform_constant(name: str) -> object:
    path = SKILL_DIR / "scripts" / "verify-platform.py"
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    return None


def extract_valid_type_ids_from_verify_platform() -> set[int]:
    value = _extract_platform_constant("VALID_TYPE_IDS")
    return set(value) if isinstance(value, set) else set()


def extract_valid_action_ids_from_verify_platform() -> dict[int, set[int]]:
    value = _extract_platform_constant("VALID_ACTION_IDS")
    if not isinstance(value, dict):
        return {}
    return {int(type_id): set(action_ids) for type_id, action_ids in value.items()}


def _load_document(path: str) -> tuple[dict | None, str | None]:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file), None
    except FileNotFoundError:
        return None, f"文件不存在: {path}"
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败: {exc}"
    except OSError as exc:
        return None, f"无法读取文件: {exc}"


def _validation_output(kind: str, path: str, violations: list[dict]) -> dict:
    return {
        "verdict": "pass" if not violations else "fail",
        "source": f"contract_compat.py validate-{kind}",
        "document_kind": kind,
        "path": path,
        "total_violations": len(violations),
        "high": sum(v["severity"] == "high" for v in violations),
        "medium": sum(v["severity"] == "medium" for v in violations),
        "low": sum(v["severity"] == "low" for v in violations),
        "violations": violations,
    }


def cmd_validate(path: str, requested_kind: str | None, quiet: bool) -> int:
    data, error = _load_document(path)
    if error:
        print(json.dumps({"verdict": "fail", "error": error}, ensure_ascii=False))
        return 1
    assert data is not None
    kind = requested_kind or detect_document_kind(data)
    if kind is None:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": (
                        "无法唯一识别文件类型；lock 需包含 workflows/sheets/gates，"
                        "exec contract 需包含 target/trigger/nodes/field_references"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 1
    violations = validate_lock(data) if kind == "lock" else validate_exec(data)
    output = _validation_output(kind, path, violations)
    if quiet:
        output = {
            "verdict": output["verdict"],
            "document_kind": kind,
            "total_violations": len(violations),
        }
    print(json.dumps(output, ensure_ascii=False, indent=None if quiet else 2))
    return 0 if not violations else 1


def cmd_validate_all(quiet: bool) -> int:
    if not WORKFLOW_OUTPUT.is_dir():
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": f"workflow-output 目录不存在: {WORKFLOW_OUTPUT}",
                },
                ensure_ascii=False,
            )
        )
        return 1
    results = {}
    for project_dir in sorted(WORKFLOW_OUTPUT.iterdir()):
        if not project_dir.is_dir():
            continue
        for filename in ("execution_lock.json", "execution_contract.json"):
            path = project_dir / filename
            if not path.is_file():
                continue
            data, error = _load_document(str(path))
            if error or data is None:
                results[str(path)] = {"verdict": "fail", "error": error}
                continue
            kind = detect_document_kind(data)
            violations = (
                validate_lock(data)
                if kind == "lock"
                else validate_exec(data)
                if kind == "exec"
                else [{"severity": "high", "detail": "无法识别文件类型"}]
            )
            results[str(path)] = {
                "verdict": "pass" if not violations else "fail",
                "document_kind": kind,
                "total_violations": len(violations),
            }
    verdict = (
        "warn"
        if not results
        else "pass"
        if all(item["verdict"] == "pass" for item in results.values())
        else "fail"
    )
    output = {
        "verdict": verdict,
        "source": "contract_compat.py validate --all-projects",
        "files_checked": len(results),
        "results": results,
    }
    if quiet:
        output = {"verdict": verdict, "files_checked": len(results)}
    print(json.dumps(output, ensure_ascii=False, indent=None if quiet else 2))
    return 0 if verdict in ("pass", "warn") else 1


def cmd_check_schema() -> int:
    workflow_schema = load_schema().get("workflows", {})
    schema_ids = set(workflow_schema.get("valid_type_ids", []))
    platform_ids = extract_valid_type_ids_from_verify_platform()
    schema_actions = {
        int(type_id): set(action_ids)
        for type_id, action_ids in workflow_schema.get(
            "valid_action_ids", {}
        ).items()
    }
    platform_actions = extract_valid_action_ids_from_verify_platform()
    only_schema = sorted(schema_ids - platform_ids)
    only_platform = sorted(platform_ids - schema_ids)
    violations = []
    if only_schema:
        violations.append(
            {"severity": "high", "detail": f"仅在 lock schema: {only_schema}"}
        )
    if only_platform:
        violations.append(
            {
                "severity": "high",
                "detail": f"仅在 verify-platform.py: {only_platform}",
            }
        )
    if schema_actions != platform_actions:
        violations.append(
            {
                "severity": "high",
                "detail": "valid_action_ids 与 verify-platform.py 不一致",
            }
        )
    output = {
        "verdict": "pass" if not violations else "fail",
        "source": "contract_compat.py check-schema",
        "schema_path": str(SCHEMA_PATH),
        "schema_type_ids_count": len(schema_ids),
        "verify_platform_type_ids_count": len(platform_ids),
        "schema_action_type_count": len(schema_actions),
        "verify_platform_action_type_count": len(platform_actions),
        "results": violations
        or [
            {
                "severity": "pass",
                "detail": f"VALID_TYPE_IDS 一致: {len(schema_ids)} 个",
            }
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="execution lock/contract 兼容验证")
    subparsers = parser.add_subparsers(dest="command")

    for command, help_text in (
        ("validate", "自动识别并验证 lock 或 exec contract"),
        ("validate-lock", "验证 execution_lock.json"),
        ("validate-exec", "验证 hap-flow-exec execution_contract.json"),
    ):
        subparser = subparsers.add_parser(command, help=help_text)
        subparser.add_argument("path", nargs="?", help="JSON 文件路径")
        subparser.add_argument("--quiet", action="store_true")
        if command == "validate":
            subparser.add_argument("--all-projects", action="store_true")

    subparsers.add_parser(
        "check-schema",
        help="交叉验证 lock schema 与 verify-platform type IDs",
    )
    args = parser.parse_args()

    if args.command == "check-schema":
        raise SystemExit(cmd_check_schema())
    if args.command in ("validate", "validate-lock", "validate-exec"):
        if args.command == "validate" and args.all_projects:
            raise SystemExit(cmd_validate_all(args.quiet))
        if not args.path:
            print(
                json.dumps(
                    {"verdict": "fail", "error": "需要 JSON 文件路径"},
                    ensure_ascii=False,
                )
            )
            raise SystemExit(2)
        requested_kind = {
            "validate-lock": "lock",
            "validate-exec": "exec",
        }.get(args.command)
        raise SystemExit(cmd_validate(args.path, requested_kind, args.quiet))
    parser.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
