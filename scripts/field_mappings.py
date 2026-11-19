#!/usr/bin/env python3
"""Readable 「将字段 / 设为」 mappings for workflow create and update nodes.

flowNode/get often stores the update target as selectNodeName plus appName, a
relation assignment as nodeName plus a bare fieldId, and a text assignment as
``$<nodeId>-<controlId>$``. getNodeDetail adds selectNodeObj, formulaMap, and
controls. The editor renders that combination as:

- 更新对象：当前流程中的节点对象 工作表事件触发 / 工作表 EmpAwards_员工奖项
- 将字段 [关联表] EmpBasicInfo_员工基本信息 设为 查询工作表 / 工作表 EmpBasicInfo_员工基本信息
- 将字段 [文本] MainID 设为 查询工作表 / 员工工号

Raw fieldId, nodeId, and the original token stay beside the readable line.
"""

import re

# Bracket labels the workflow editor shows. 2 and 29 are the ones the update
# screen uses for 文本 and 关联表; the others are the same control-type ids.
CONTROL_TYPE_LABELS = {
    2: "文本",
    3: "手机",
    5: "邮箱",
    6: "数值",
    8: "金额",
    9: "单选",
    10: "多选",
    11: "下拉",
    14: "附件",
    15: "日期",
    26: "成员",
    27: "部门",
    29: "关联表",
    34: "子表",
}

_CREATE_ACTIONS = {1, 21}
_UPDATE_ACTIONS = {2, 412}
_CREATE_NODE_TYPES = {"create_record", "add_record", "batch_create"}
_UPDATE_NODE_TYPES = {"update_record", "batch_update"}
_FORMULA_TOKEN = re.compile(r"\$([^$\s]+)\$")
_DETAIL_KEYS = (
    "fields",
    "formulaMap",
    "controls",
    "selectNodeObj",
    "selectNodeId",
    "selectNodeName",
    "appName",
    "appTypeName",
    "flowNodeList",
    "flowNodeAppDtos",
)


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first(source, *keys) -> str:
    if not isinstance(source, dict):
        return ""
    for key in keys:
        text = _text(source.get(key))
        if text:
            return text
    return ""


def _as_int(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sources(node, detail=None):
    sources = []
    if isinstance(node, dict):
        sources.append(node)
        config = node.get("config")
        if isinstance(config, dict):
            sources.append(config)
    if isinstance(detail, dict):
        sources.append(detail)
    return sources


def _controls_from_dtos(source) -> list:
    found = []
    if not isinstance(source, dict):
        return found
    dtos = source.get("flowNodeAppDtos")
    if not isinstance(dtos, list):
        return found
    for dto in dtos:
        controls = dto.get("controls") if isinstance(dto, dict) else None
        if isinstance(controls, list):
            found.extend(item for item in controls if isinstance(item, dict))
    return found


def _control_list(source) -> list:
    if not isinstance(source, dict):
        return []
    controls = source.get("controls")
    found = [item for item in controls if isinstance(item, dict)] if isinstance(controls, list) else []
    if found:
        return found
    return _controls_from_dtos(source)


def prepare_detail(payload) -> dict:
    """Unwrap getNodeDetail and lift controls out of flowNodeAppDtos."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    flow_node = data.get("flowNode") if isinstance(data.get("flowNode"), dict) else None
    if flow_node is not None:
        merged = dict(flow_node)
        for key in _DETAIL_KEYS:
            if not merged.get(key) and data.get(key):
                merged[key] = data[key]
        data = merged
    lifted = dict(data)
    if not _control_list(lifted):
        controls = _controls_from_dtos(data)
        if controls:
            lifted["controls"] = controls
    return lifted


def _copy_present(target, detail) -> None:
    for key in _DETAIL_KEYS:
        value = detail.get(key)
        if value in (None, "", [], {}):
            continue
        target[key] = value


def merge_detail_into(node, detail) -> dict:
    """Copy formulaMap, controls, and selectNodeObj onto a structure node."""
    if not isinstance(node, dict):
        return {}
    flat = prepare_detail(detail)
    _copy_present(node, flat)
    config = node.get("config")
    if isinstance(config, dict):
        _copy_present(config, flat)
    return node


def _type_id(node) -> int | None:
    for source in _sources(node):
        type_id = _as_int(source.get("typeId"))
        if type_id is None:
            type_id = _as_int(source.get("type_id"))
        if type_id is not None:
            return type_id
    return None


def _action_id(node) -> int | None:
    for source in _sources(node):
        action_id = _as_int(source.get("actionId"))
        if action_id is None:
            action_id = _as_int(source.get("action_id"))
        if action_id is not None:
            return action_id
    return None


def _node_type(node) -> str:
    if not isinstance(node, dict):
        return ""
    return _text(node.get("nodeType") or node.get("triggerType")).lower()


def _node_name(node) -> str:
    if not isinstance(node, dict):
        return ""
    return _text(node.get("name") or node.get("node_name"))


def assignment_fields(node, detail=None) -> list:
    """Field rows from the node, its config, then getNodeDetail. Last non-empty wins."""
    chosen = []
    for source in _sources(node, detail):
        fields = source.get("fields")
        if isinstance(fields, list):
            rows = [item for item in fields if isinstance(item, dict)]
            if rows:
                chosen = rows
    return chosen


def is_field_assignment_node(node) -> bool:
    """Create/update nodes, plus any node that already has the 将字段 rows."""
    if assignment_fields(node):
        return True
    node_type = _node_type(node)
    if node_type in _CREATE_NODE_TYPES or node_type in _UPDATE_NODE_TYPES:
        return True
    if _type_id(node) != 6:
        return False
    action_id = _action_id(node)
    if action_id in _CREATE_ACTIONS or action_id in _UPDATE_ACTIONS:
        return True
    name = _node_name(node)
    return "新增" in name or "更新" in name


def _object_label(node) -> str:
    node_type = _node_type(node)
    name = _node_name(node)
    action_id = _action_id(node)
    if action_id in _CREATE_ACTIONS or node_type in _CREATE_NODE_TYPES or ("新增" in name and "更新" not in name):
        return "新增对象"
    if action_id in _UPDATE_ACTIONS or node_type in _UPDATE_NODE_TYPES or "更新" in name:
        return "更新对象"
    return "目标对象"


def _controls_by_id(sources) -> dict:
    found = {}
    for source in sources:
        for control in _control_list(source):
            control_id = _first(control, "controlId", "id")
            if control_id:
                found[control_id] = control
    return found


def _remember_node(index, node_id, name="", worksheet="", app_type_name="") -> None:
    node_id = _text(node_id)
    if not node_id:
        return
    slot = index.setdefault(node_id, {})
    if name:
        slot["name"] = name
    if worksheet:
        slot["worksheet"] = worksheet
    if app_type_name:
        slot["app_type_name"] = app_type_name


def _node_index(sources, fields) -> dict:
    index = {}
    for source in sources:
        listed = source.get("flowNodeList")
        if not isinstance(listed, list):
            continue
        for item in listed:
            if not isinstance(item, dict):
                continue
            _remember_node(
                index,
                _first(item, "nodeId", "id"),
                _first(item, "nodeName", "name"),
                _first(item, "appName", "worksheetName", "sourceEntityName"),
                _first(item, "appTypeName"),
            )
    for field in fields:
        _remember_node(
            index,
            _first(field, "nodeId"),
            _first(field, "nodeName"),
            _first(field, "nodeAppName", "worksheetName", "sourceEntityName"),
            _first(field, "appTypeName"),
        )
    return index


def _formula_entry(formula_map, inner):
    if not isinstance(formula_map, dict):
        return None
    for key in (inner, f"${inner}$"):
        if key in formula_map:
            return formula_map[key]
    return None


def _split_ref(inner) -> tuple:
    if "-" not in inner:
        return inner, ""
    node_id, control_id = inner.split("-", 1)
    return node_id, control_id


def _names_from_entry(entry) -> tuple:
    if isinstance(entry, str):
        text = entry.strip()
        if " / " in text:
            node_name, field_name = text.split(" / ", 1)
            return node_name.strip(), field_name.strip()
        return "", text
    if not isinstance(entry, dict):
        return "", ""
    node_name = _first(entry, "nodeName", "sourceName", "node_name", "sourceNodeName")
    field_name = _first(entry, "controlName", "fieldName", "fieldValueName", "control_name", "name")
    if node_name and field_name.startswith(node_name + "-"):
        field_name = field_name[len(node_name) + 1:]
    elif node_name and field_name.startswith(node_name + " / "):
        field_name = field_name[len(node_name) + 3:]
    return node_name, field_name


def _lookup_formula(inner, formula_map, node_index) -> tuple:
    """Return display, resolved, node_id, control_id, node_name, field_name."""
    node_id, control_id = _split_ref(inner)
    node_name, field_name = _names_from_entry(_formula_entry(formula_map, inner))
    if not node_name and node_id:
        node_name = (node_index.get(node_id) or {}).get("name") or ""
    if node_name and field_name:
        return f"{node_name} / {field_name}", True, node_id, control_id, node_name, field_name
    if not control_id and node_name:
        return node_name, True, node_id, control_id, node_name, field_name
    shown = field_name or node_name or f"${inner}$"
    return shown, False, node_id, control_id, node_name, field_name


def _render_formula(value, formula_map, node_index) -> tuple:
    parts = []
    resolved = True
    first = None

    def replace(match):
        nonlocal resolved, first
        display, ok, node_id, control_id, node_name, field_name = _lookup_formula(
            match.group(1), formula_map, node_index,
        )
        if first is None:
            first = (node_id, control_id, node_name, field_name, match.group(0))
        if not ok:
            resolved = False
            return match.group(0)
        return display

    rendered = _FORMULA_TOKEN.sub(replace, value)
    if _FORMULA_TOKEN.search(rendered):
        resolved = False
    if first is None:
        return rendered, False, "", "", "", "", ""
    node_id, control_id, node_name, field_name, token = first
    return rendered, resolved, node_id, control_id, node_name, field_name, token


def _formula_map(sources) -> dict:
    found = {}
    for source in sources:
        current = source.get("formulaMap")
        if isinstance(current, dict) and current:
            found.update(current)
    return found


def _sheet_bits(name, worksheet, app_type_name) -> str:
    sheet = " ".join(part for part in (app_type_name, worksheet) if part)
    if name and sheet:
        return f"{name} / {sheet}"
    return name or sheet


def _update_object(sources) -> dict:
    select = {}
    for source in sources:
        current = source.get("selectNodeObj")
        if isinstance(current, dict) and current:
            select = current
    node_name = _first(select, "nodeName", "name")
    node_id = _first(select, "nodeId", "id")
    worksheet = _first(select, "appName")
    app_type_name = _first(select, "appTypeName")
    for source in sources:
        node_name = node_name or _first(source, "selectNodeName")
        node_id = node_id or _first(source, "selectNodeId")
        worksheet = worksheet or _first(source, "appName")
        app_type_name = app_type_name or _first(source, "appTypeName")
    scope = "当前流程中的节点对象" if node_id or node_name else ""
    return {
        "scope": scope,
        "node_id": node_id,
        "node_name": node_name,
        "worksheet": worksheet,
        "app_type_name": app_type_name,
        "display": _sheet_bits(node_name, worksheet, app_type_name),
    }


def _field_value(field) -> str:
    if "fieldValue" in field and field.get("fieldValue") is not None:
        return _text(field.get("fieldValue"))
    return _text(field.get("value"))


def _is_relation(field, type_id, value) -> bool:
    if type_id == 29:
        return True
    if _FORMULA_TOKEN.search(value):
        return False
    if value:
        return False
    return bool(_first(field, "nodeId") or _first(field, "nodeName"))


def _assignment(field, controls, formula_map, node_index) -> dict:
    field_id = _first(field, "fieldId", "controlId", "id")
    control = controls.get(field_id) or {}
    type_id = _as_int(field.get("type"))
    if type_id is None:
        type_id = _as_int(control.get("type"))
    type_label = CONTROL_TYPE_LABELS.get(type_id, "")
    field_name = _first(field, "fieldName", "controlName") or _first(control, "controlName", "name") or field_id
    value = _field_value(field)
    raw = {"fieldId": field_id, "fieldValue": value}
    if _first(field, "nodeId"):
        raw["nodeId"] = _first(field, "nodeId")
    if _first(field, "nodeName"):
        raw["nodeName"] = _first(field, "nodeName")
    if type_id is not None:
        raw["type"] = type_id

    if field.get("isClear") is True and not value:
        set_to = {"kind": "clear"}
        display = "清空"
        unresolved = False
    elif _FORMULA_TOKEN.search(value):
        rendered, resolved, node_id, control_id, node_name, source_field, token = _render_formula(
            value, formula_map, node_index,
        )
        set_to = {
            "kind": "formula",
            "token": token or value,
            "node_id": node_id,
            "control_id": control_id,
            "node_name": node_name,
            "field_name": source_field,
        }
        display = rendered
        unresolved = not resolved
    elif _is_relation(field, type_id, value):
        node_id = _first(field, "nodeId")
        indexed = node_index.get(node_id) or {}
        node_name = _first(field, "nodeName") or indexed.get("name") or ""
        worksheet = (
            _first(field, "nodeAppName", "worksheetName", "sourceEntityName")
            or indexed.get("worksheet")
            or _first(control, "sourceEntityName", "worksheetName", "dataSourceName")
        )
        app_type_name = _first(field, "appTypeName") or indexed.get("app_type_name") or ""
        if worksheet and not app_type_name:
            app_type_name = "工作表"
        set_to = {
            "kind": "node",
            "node_id": node_id,
            "node_name": node_name,
            "worksheet": worksheet,
            "app_type_name": app_type_name,
        }
        display = _sheet_bits(node_name, worksheet, app_type_name)
        unresolved = (not field_name or field_name == field_id or not node_name)
    else:
        named = _first(field, "fieldValueName")
        node_name = _first(field, "nodeName")
        if named and node_name:
            display = f"{node_name} / {named}"
            set_to = {
                "kind": "field_ref",
                "node_id": _first(field, "nodeId"),
                "node_name": node_name,
                "field_name": named,
                "control_id": _first(field, "fieldValueId"),
            }
            unresolved = False
        else:
            display = value or "（空）"
            set_to = {"kind": "literal", "value": value}
            unresolved = False

    label = f"[{type_label}] {field_name}" if type_label else field_name
    assignment = {
        "action": "设为",
        "field_id": field_id,
        "field_name": field_name,
        "field_label": label,
        "set_to_display": display,
        "set_to": set_to,
        "raw": raw,
    }
    if type_id is not None:
        assignment["field_type"] = type_id
    if type_label:
        assignment["field_type_label"] = type_label
    if unresolved:
        assignment["unresolved"] = True
    return assignment


def resolve_field_mappings(node, detail=None) -> dict | None:
    """Build the editor lines for one node. ``detail`` is a getNodeDetail body."""
    if not isinstance(node, dict):
        return None
    flat_detail = prepare_detail(detail) if detail else None
    if flat_detail == {}:
        flat_detail = None
    if not is_field_assignment_node(node) and not assignment_fields(node, flat_detail):
        return None
    sources = _sources(node, flat_detail)
    fields = assignment_fields(node, flat_detail)
    formula_map = _formula_map(sources)
    node_index = _node_index(sources, fields)
    controls = _controls_by_id(sources)
    assignments = [_assignment(field, controls, formula_map, node_index) for field in fields]
    update_object = _update_object(sources)
    if not assignments and not update_object.get("display"):
        return None
    lines = []
    if update_object.get("display"):
        label = _object_label(node)
        scope = update_object.get("scope") or ""
        if scope:
            lines.append(f"{label}：{scope} {update_object['display']}")
        else:
            lines.append(f"{label}：{update_object['display']}")
    for item in assignments:
        lines.append(f"将字段 {item['field_label']} 设为 {item['set_to_display']}")
    return {
        "object_label": _object_label(node),
        "update_object": update_object,
        "assignments": assignments,
        "lines": lines,
    }


def needs_node_detail(node) -> bool:
    """True when flowNode/get left a formula token or a relation field unnamed.

    Literal values such as ``done`` stay on the structure response. Calling
    getNodeDetail for those would repeat work the structure fetch already finished.
    """
    if not assignment_fields(node):
        return False
    mapping = resolve_field_mappings(node)
    if not mapping:
        return False
    return any(item.get("unresolved") for item in mapping.get("assignments") or [])


def raw_assignment_summary(mapping) -> list:
    rows = []
    for item in (mapping or {}).get("assignments") or []:
        raw = item.get("raw") or {}
        rows.append(f"{raw.get('fieldId', '')}:{str(raw.get('fieldValue', ''))[:50]}")
    return rows
