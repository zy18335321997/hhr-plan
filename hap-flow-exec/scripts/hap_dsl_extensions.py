#!/usr/bin/env python3
"""Executor-owned extensions for HAP workflow node DSL gaps.

The installed hap CLI exposes the required wire helpers, but its public DSL
does not yet map code, PBP call/output, or interface-push nodes. This module
adds those mappings for one in-process batch build without modifying the
installed package.
"""

from __future__ import annotations

import base64
import copy
from contextlib import contextmanager
from typing import Any, Iterator


EXTENDED_NODE_TYPES = frozenset(
    {"code", "pbp_call", "pbp_output", "interface_push"}
)

_FORMULA_ACTION_IDS = {
    "number": "100",
    "date": "101",
    "date_diff": "104",
    "function": "106",
}
_OUTPUT_TYPE_IDS = {
    "text": 2,
    "number": 6,
    "date": 15,
    "datetime": 16,
}


def contains_extended_nodes(nodes: list[dict]) -> bool:
    """Return whether a node tree needs the executor-owned DSL extension."""

    def walk(items: object) -> bool:
        if not isinstance(items, list):
            return False
        for node in items:
            if not isinstance(node, dict):
                continue
            if node.get("nodeType") in EXTENDED_NODE_TYPES:
                return True
            config = node.get("config") or {}
            for path in config.get("paths") or []:
                if walk(path.get("nodes")):
                    return True
            if walk((config.get("process") or {}).get("nodes")):
                return True
        return False

    return walk(nodes)


def _index_node_specs(nodes: list[dict]) -> dict[str, dict]:
    """Index aliases across the outer graph and nested node containers."""

    result: dict[str, dict] = {}

    def walk(items: object) -> None:
        if not isinstance(items, list):
            return
        for node in items:
            if not isinstance(node, dict):
                continue
            alias = node.get("nodeAlias") or node.get("alias")
            if alias:
                result[str(alias)] = node
            config = node.get("config") or {}
            for path in config.get("paths") or []:
                walk(path.get("nodes"))
            walk((config.get("process") or {}).get("nodes"))

    walk(nodes)
    return result


def index_node_specs(nodes: list[dict]) -> dict[str, dict]:
    """Return the alias index used by downstream save-action lowering."""

    return _index_node_specs(nodes)


def _dynamic_source_metadata(node: dict, field_id: str) -> dict[str, Any]:
    """Return the source blueprint required by HAP dynamic field wires."""

    node_type = node.get("nodeType")
    config = node.get("config") or {}
    name = node.get("name", "")
    if node_type == "compute":
        mode = str(config.get("mode") or "number")
        output_type = _OUTPUT_TYPE_IDS.get(
            str(config.get("output_type") or "number").lower(),
            6,
        )
        return {
            # HAP exposes action 106's numeric-looking function result under
            # string_fx_id. The UI writes this ID even when the value type is
            # Number; number/date arithmetic actions retain their own IDs.
            "fieldValueId": (
                "string_fx_id" if mode == "function" else field_id
            ),
            "nodeAppType": 11,
            "fieldValueType": str(output_type),
            "nodeName": name,
            "fieldValueName": "结果",
            "nodeTypeId": 9,
            "nodeActionId": _FORMULA_ACTION_IDS.get(mode, "100"),
            "sourceType": 0,
            "isSourceApp": False,
        }
    if node_type == "rollup":
        action_id = "105" if config.get("data_source") or config.get("source") else "107"
        return {
            "nodeAppType": 11 if action_id == "105" else 1,
            "fieldValueType": "6",
            "nodeName": name,
            "fieldValueName": "结果",
            "nodeTypeId": 9,
            "nodeActionId": action_id,
            "sourceType": 0,
            "isSourceApp": False,
        }
    if node_type == "code":
        output = next(
            (
                item
                for item in config.get("outputs") or []
                if item.get("fieldId") == field_id
            ),
            {},
        )
        language = str(config.get("language") or "javascript").lower()
        return {
            "nodeAppType": 12,
            "fieldValueType": str(output.get("type", 2)),
            "nodeName": name,
            "fieldValueName": output.get("fieldName") or field_id,
            "nodeTypeId": 14,
            "nodeActionId": "103" if language in {"python", "py"} else "102",
            "sourceType": 0,
            "isSourceApp": False,
        }
    if node_type == "pbp_call":
        output = next(
            (
                item
                for item in config.get("outputs") or []
                if item.get("fieldId") == field_id
            ),
            {},
        )
        return {
            "nodeAppType": 17,
            "nodeAppId": config.get("processId") or config.get("appId", ""),
            "fieldValueType": str(output.get("type", 2)),
            "nodeName": name,
            "fieldValueName": output.get("fieldName") or field_id,
            "nodeTypeId": 20,
            "nodeActionId": "500",
            "sourceType": 0,
            "isSourceApp": False,
        }
    return {}


def build_action_fields(
    fields: list[dict],
    alias_to_id: dict[str, str],
    source_nodes: dict[str, dict],
    field_types: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Lower record writes without losing dynamic value references."""
    from hap_cli.core import workflow_node_dsl as dsl

    patches = copy.deepcopy(fields or [])
    for patch in patches:
        field_id = patch.get("fieldId") or patch.get("controlId", "")
        patch["fieldId"] = field_id
        patch.pop("controlId", None)
        if patch.get("type") is None and (field_types or {}).get(field_id) is not None:
            patch["type"] = field_types[field_id]
        value = patch.get("value")
        if isinstance(value, dict) and value.get("key"):
            patch["value"] = value["key"]
        elif isinstance(value, list):
            normalized = [
                item.get("key") if isinstance(item, dict) else item
                for item in value
            ]
            if patch.get("type") == 29 and len(normalized) == 1:
                patch["value"] = normalized[0]
            else:
                patch["value"] = normalized
        value_ref = patch.get("valueRef")
        if (
            isinstance(value_ref, dict)
            and isinstance(value_ref.get("node"), str)
        ):
            value_ref["node"] = {"nodeAlias": value_ref["node"]}

    translated = dsl.translate_field_patches(patches, alias_to_id)
    for original, wire in zip(fields, translated):
        value_ref = original.get("valueRef")
        if not isinstance(value_ref, dict):
            value = original.get("value")
            value_ref = value if isinstance(value, dict) else None
        if not isinstance(value_ref, dict) or value_ref.get("kind") not in {
            "field",
            "nodeField",
        }:
            continue
        alias = value_ref.get("node")
        if isinstance(alias, dict):
            alias = alias.get("nodeAlias")
        source_node = source_nodes.get(str(alias or ""))
        if source_node:
            wire.update(
                _dynamic_source_metadata(
                    source_node,
                    str(value_ref.get("fieldId") or ""),
                )
            )
            wire["sureNodeId"] = wire.get("nodeId", "")
    return translated


def _value_to_template(value: object, alias_to_id: dict[str, str]) -> object:
    from hap_cli.core import workflow_node_dsl as dsl

    if isinstance(value, str):
        return dsl.resolve_template(value, alias_to_id)
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    kind = value.get("kind")
    if kind == "literal":
        return copy.deepcopy(value.get("value"))
    if kind in {"field", "nodeField"}:
        node_id = dsl._resolve_node_id(value.get("node"), alias_to_id)
        return f"${node_id}-{value.get('fieldId', '')}$"
    if kind in {"system", "systemField"}:
        field_id = value.get("field") or value.get("fieldId", "")
        field_id = dsl._SYSTEM_VALUE_FIELDS.get(field_id, field_id)
        return f"${dsl.SYSTEM_NODE_ID}-{field_id}$"
    return copy.deepcopy(value)


def build_code_wire(
    node: dict,
    alias_to_id: dict[str, str],
) -> dict[str, Any]:
    """Build the exact saveNode payload used by pd-openweb's Code editor."""
    config = node.get("config") or {}
    language = str(config.get("language") or "javascript").lower()
    action_id = "103" if language in {"python", "py"} else "102"
    source = str(config.get("source") or "").replace("\t", "    ")
    code_value = str(config.get("code") or "")
    code_encoding = str(config.get("codeEncoding") or "source").lower()
    if code_encoding in {"base64", "utf8_base64"}:
        try:
            decoded = base64.b64decode(
                code_value.encode("ascii"),
                validate=True,
            ).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("code is not valid UTF-8 Base64") from exc
        if source and decoded != source:
            raise ValueError("code Base64 value does not match config.source")
        encoded = code_value
    else:
        source = str(config.get("code") or source).replace("\t", "    ")
        encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    inputs = []
    for item in config.get("inputs") or config.get("inputDatas") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        normalized = copy.deepcopy(item)
        normalized["value"] = _value_to_template(
            normalized.get("value", ""),
            alias_to_id,
        )
        inputs.append(normalized)
    return {
        "actionId": action_id,
        "inputDatas": inputs,
        "code": encoded,
        "testMap": copy.deepcopy(config.get("testMap") or {}),
        "version": config.get("version", ""),
        "maxRetries": int(config.get("maxRetries", 1)),
    }


def build_pbp_fields(
    fields: list[dict],
    alias_to_id: dict[str, str],
    source_nodes: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """Lower PBP input/output values while retaining parameter metadata."""
    from hap_cli.core import workflow_node_dsl as dsl

    normalized_fields = copy.deepcopy(fields)
    for field in normalized_fields:
        value_ref = field.get("valueRef") if isinstance(field, dict) else None
        if isinstance(value_ref, dict) and isinstance(value_ref.get("node"), str):
            value_ref["node"] = {"nodeAlias": value_ref["node"]}
        value = field.get("value") if isinstance(field, dict) else None
        if (
            isinstance(value, dict)
            and value.get("kind") in {"field", "nodeField"}
            and isinstance(value.get("node"), str)
        ):
            value["node"] = {"nodeAlias": value["node"]}
    translated = dsl.translate_field_patches(
        normalized_fields,
        alias_to_id,
    )
    result = []
    for source, wire in zip(fields, translated):
        wire.pop("addType", None)
        for key in ("fieldName", "desc", "alias", "dataSource"):
            if key in source:
                wire[key] = copy.deepcopy(source[key])
        value_ref = source.get("valueRef") or source.get("value")
        if isinstance(value_ref, dict) and value_ref.get("kind") in {
            "field",
            "nodeField",
        }:
            alias = value_ref.get("node")
            if isinstance(alias, dict):
                alias = alias.get("nodeAlias")
            source_node = (source_nodes or {}).get(str(alias or ""))
            if source_node:
                wire.update(
                    _dynamic_source_metadata(
                        source_node,
                        str(value_ref.get("fieldId") or ""),
                    )
                )
                wire["sureNodeId"] = wire.get("nodeId", "")
        result.append(wire)
    return result


def build_push_wire(
    node: dict,
    alias_to_id: dict[str, str],
) -> dict[str, Any]:
    """Build the complete interface-push save payload with stable defaults."""
    from hap_cli.core import workflow_node_dsl as dsl

    config = copy.deepcopy(node.get("config") or {})
    content = dsl.resolve_template(str(config.get("content") or ""), alias_to_id)
    return {
        "promptType": int(config.get("promptType", 2)),
        "pushType": int(config.get("pushType", 1)),
        "openMode": config.get("openMode"),
        "appId": config.get("appId"),
        "selectNodeId": dsl._resolve_node_id(
            config.get("selectNodeId") or config.get("target", {}).get("node"),
            alias_to_id,
        ),
        "viewId": config.get("viewId", ""),
        "content": content,
        "duration": int(config.get("duration", 5)),
        "title": config.get("title"),
        "buttons": copy.deepcopy(config.get("buttons") or []),
        "actionId": config.get("actionId", ""),
        "fields": copy.deepcopy(config.get("fields") or []),
        "promptSound": copy.deepcopy(config.get("promptSound")),
        "accounts": dsl.translate_accounts(
            config.get("accounts") or [],
            alias_to_id,
        ),
        "windowSize": config.get("windowSize"),
    }


def _existing_pbp_output_id(session, process_id: str) -> str:
    """Return the single output node that HAP pre-creates for every PBP."""
    from hap_cli.core import flow_node as flow

    structure = flow.get_nodes(session, process_id)
    if isinstance(structure, dict) and isinstance(structure.get("data"), dict):
        structure = structure["data"]
    node_map = structure.get("flowNodeMap", {}) if isinstance(structure, dict) else {}
    output_ids = [
        node_id
        for node_id, item in node_map.items()
        if isinstance(item, dict)
        and str(item.get("typeId")) == "20"
        and str(item.get("actionId")) == "502"
    ]
    if len(output_ids) != 1:
        raise ValueError(
            "PBP must contain exactly one pre-created output node; "
            f"found {len(output_ids)}"
        )
    return output_ids[0]


@contextmanager
def installed_extensions(nodes: list[dict] | None = None) -> Iterator[None]:
    """Temporarily extend hap_cli's private builder for one batch call."""
    from hap_cli.core import flow_node as flow
    from hap_cli.core import workflow_node_dsl as dsl

    original_map = dict(dsl.NODETYPE_MAP)
    original_add = dsl._add_one_node
    original_save = dsl._save_generic_node
    original_pbp_control = dsl._pbp_control
    original_normalize = dsl._normalize_v3_node
    original_translate_fields = dsl.translate_field_patches
    source_nodes = _index_node_specs(nodes or [])

    dsl.NODETYPE_MAP.update(
        {
            "code": (14, None),
            "pbp_call": (20, "500"),
            "pbp_output": (20, "502"),
            "interface_push": (17, None),
        }
    )

    def pbp_control(spec, *, data_source=""):
        control = original_pbp_control(spec, data_source=data_source)
        if spec.get("controlId"):
            control["controlId"] = spec["controlId"]
        return control

    def normalize_v3_node(node):
        if isinstance(node, dict) and node.get("nodeType") in EXTENDED_NODE_TYPES:
            return copy.deepcopy(node)
        return original_normalize(node)

    def translate_fields(fields, alias_to_id):
        normalized = copy.deepcopy(fields or [])
        for field in normalized:
            if not isinstance(field, dict):
                continue
            for key in ("valueRef", "value"):
                value_ref = field.get(key)
                if (
                    isinstance(value_ref, dict)
                    and value_ref.get("kind") in {"field", "nodeField"}
                    and isinstance(value_ref.get("node"), str)
                ):
                    value_ref["node"] = {
                        "nodeAlias": value_ref["node"],
                    }
        return original_translate_fields(normalized, alias_to_id)

    def add_one(
        session,
        process_id,
        node,
        flow_node_type,
        action_id,
        prev_id,
        parent_id,
        app_id,
        alias_to_id=None,
    ):
        node_type = node.get("nodeType")
        if node_type not in EXTENDED_NODE_TYPES:
            return original_add(
                session,
                process_id,
                node,
                flow_node_type,
                action_id,
                prev_id,
                parent_id,
                app_id,
                alias_to_id=alias_to_id,
            )
        config = node.get("config") or {}
        if node_type == "pbp_output":
            # A PBP skeleton already owns one terminal action-502 node. Adding
            # another produces duplicate outputs, so bind the contract alias
            # to the platform-owned node and configure it in save_generic.
            return _existing_pbp_output_id(session, process_id)
        if node_type == "code":
            language = str(config.get("language") or "javascript").lower()
            action_id = "103" if language in {"python", "py"} else "102"
        extra = {"parentId": parent_id} if parent_id else {}
        if node_type == "interface_push":
            extra["pushType"] = int(config.get("pushType", 1))
        target_app_id = ""
        if node_type == "pbp_call":
            target_app_id = config.get("processId") or config.get("appId", "")
        response = flow.add_node(
            session,
            process_id,
            flow_node_type,
            prev_id,
            name=node.get("name", ""),
            action_id=action_id or "",
            app_id=target_app_id,
            app_type=17 if node_type == "pbp_call" else None,
            extra=extra or None,
        )
        return dsl._extract_added_node_id(response)

    def save_generic(
        session,
        process_id,
        node_id,
        node,
        flow_node_type,
        action_id,
        alias_to_id,
    ):
        node_type = node.get("nodeType")
        config = node.get("config") or {}
        if node_type == "code":
            wire = build_code_wire(node, alias_to_id)
        elif node_type == "pbp_call":
            wire = {
                "appId": config.get("processId") or config.get("appId", ""),
                "fields": build_pbp_fields(
                    config.get("inputs") or config.get("fields") or [],
                    alias_to_id,
                    source_nodes,
                ),
                "executeType": int(config.get("executeType", 0)),
                "number": copy.deepcopy(
                    config.get("number") or {"fieldValue": "1"}
                ),
                "selectNodeId": dsl._resolve_node_id(
                    config.get("selectNodeId")
                    or (config.get("data_source") or {}).get("node"),
                    alias_to_id,
                ),
                "nextExecute": bool(config.get("nextExecute", True)),
                "fromTrigger": bool(config.get("fromTrigger", True)),
            }
        elif node_type == "pbp_output":
            wire = {
                "fields": build_pbp_fields(
                    config.get("outputs") or config.get("fields") or [],
                    alias_to_id,
                    source_nodes,
                )
            }
        elif node_type == "interface_push":
            wire = build_push_wire(node, alias_to_id)
        else:
            return original_save(
                session,
                process_id,
                node_id,
                node,
                flow_node_type,
                action_id,
                alias_to_id,
            )
        return flow.save_node(
            session,
            process_id,
            node_id,
            flow_node_type,
            wire,
            name=node.get("name", ""),
        )

    dsl._add_one_node = add_one
    dsl._save_generic_node = save_generic
    dsl._pbp_control = pbp_control
    dsl._normalize_v3_node = normalize_v3_node
    dsl.translate_field_patches = translate_fields
    try:
        yield
    finally:
        dsl.NODETYPE_MAP.clear()
        dsl.NODETYPE_MAP.update(original_map)
        dsl._add_one_node = original_add
        dsl._save_generic_node = original_save
        dsl._pbp_control = original_pbp_control
        dsl._normalize_v3_node = original_normalize
        dsl.translate_field_patches = original_translate_fields


def run_extended_batch_add(
    pid: str,
    nodes: list[dict],
    *,
    trigger_alias: str = "trigger",
    trigger_pbp: dict | None = None,
) -> dict[str, Any]:
    """Build an extended node tree through the authenticated hap session."""
    from hap_cli.core.session import Session
    from hap_cli.core import workflow_node_dsl as dsl

    with installed_extensions(nodes):
        return dsl.build_workflow_nodes(
            Session.load(),
            pid,
            nodes,
            trigger_alias=trigger_alias,
            trigger_pbp=trigger_pbp,
        )
