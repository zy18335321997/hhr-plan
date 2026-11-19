#!/usr/bin/env python3
"""Readable editor configuration for every real workflow node.

getNodeDetail is where the workflow editor reads filters, and it writes them
back as operateCondition (hap-cli 0.9.14 ``_READ_TO_WRITE_KEYS``). A 查询工作表
node (type 7, action 406) keeps the screenshot's filter there, not in
findFields — findFields is the legacy key-field list for 查找并更新 (421).

Each condition uses the editor's own keys (pd-openweb TriggerCondition):
filedId / filedTypeId / filedValue / conditionId / conditionValues, plus
ignoreEmpty (条件异常时忽略) and ignoreValueEmpty (值为空时忽略). Grouped
且/或 lives in filters[{spliceType, conditions}]. spliceType 1 is 且 and
2 is 或. Inside one conditions array the inner list is 且 and the outer
list is 或.

executeType on a search node is 未获取到数据时: 0 中止, 1 新增后继续, 2 继续.
random is 忽略排序规则，随机获取. An empty branch arm with no next step is
the default/else path, not a missing fetch.
"""

import importlib.util
import json
import os

import field_mappings

_HELPER_TYPE_IDS = {100, 101, 1000, 1001}
_HELPER_ACTION_IDS = {405}
_QUERY_TYPE_IDS = {7, 13}
_QUERY_NODE_TYPES = {
    "get_single", "get_record", "search", "get_multiple", "get_more_record",
    "query_update",
}
_BRANCH_ITEM_TYPES = {"branch_item", "branch_item_node"}
_WORKSHEET_EVENT_KINDS = {"worksheet_event", "worksheet"}
_KNOWN_TRIGGER_KINDS = {
    "approval", "subprocess", "sub_process", "schedule", "webhook", "button",
    "date", "worksheet_event", "worksheet",
}
_DETAIL_READ = "_editorDetailRead"
_FORMULA_TOKEN = field_mappings._FORMULA_TOKEN

# Read-side names the editor saves under another key, plus the settings
# getNodeDetail returns and flowNode/get often leaves empty.
_EDITOR_KEYS = (
    "conditions", "filters", "operateCondition", "sorts", "findFields",
    "executeType", "random", "ignoreError", "destroy", "returnNew", "link",
    "execute", "numberFieldValue", "assignFieldIds", "assignFieldNames",
    "triggerId", "appId", "appName", "appType", "appTypeName",
    "selectNodeId", "selectNodeName", "selectNodeObj",
    "gatewayType", "flowIds", "resultFlow", "nextId",
    "fields", "formulaMap", "controls", "flowNodeList", "flowNodeAppDtos",
    "accounts", "formProperties", "url", "method", "headers", "body",
    "contentType", "subject", "content", "code", "inputDatas", "actionId",
    "fieldValue", "pushType", "executeTime", "time", "unit", "subProcessId",
    "prompt", "model", "viewId", "fileName", "sourceEntityName",
    "worksheetId", "worksheetName",
)
_EMPTY_LIST_KEYS = {
    "conditions", "filters", "operateCondition", "sorts", "findFields",
    "assignFieldIds", "assignFieldNames",
}

# pd-openweb CONDITION_TYPE. The text before % is the editor label.
_CONDITION_LABELS = {
    "1": "是其中一个",
    "2": "不是任何一个",
    "3": "包含",
    "4": "不包含",
    "5": "开头是",
    "6": "结尾是",
    "7": "不为空",
    "8": "为空",
    "9": "等于",
    "10": "不等于",
    "11": "小于",
    "12": "大于",
    "13": "小于等于",
    "14": "大于等于",
    "15": "在范围内",
    "16": "不在范围内",
    "17": "早于",
    "18": "晚于",
    "29": "选中",
    "30": "不选中",
    "31": "不为空",
    "32": "为空",
    "33": "是其中一个",
    "34": "不是任何一个",
    "35": "属于",
    "36": "不属于",
    "37": "在范围内",
    "38": "不在范围内",
    "39": "晚于",
    "40": "晚于等于",
    "41": "早于",
    "42": "早于等于",
    "43": "同时包含",
    "44": "开头不是",
    "45": "结尾不是",
    "48": "下级包含",
    "49": "下级不包含",
    "100": "包含其中一个",
    "101": "不包含任何一个",
}
_VALUELESS_CONDITIONS = {"7", "8", "31", "32"}

# Worksheet-event triggerId. pd-openweb TRIGGER_ID / WorksheetContent.
_TRIGGER_EVENTS = {
    "1": "仅新增记录时",
    "2": "新增或更新记录时",
    "3": "删除记录时",
    "4": "仅更新记录时",
}
_TRIGGER_KIND_LABELS = {
    "worksheet_event": "工作表事件",
    "worksheet": "工作表事件",
    "approval": "审批",
    "subprocess": "子流程",
    "sub_process": "子流程",
    "schedule": "定时",
    "webhook": "Webhook",
    "button": "按钮",
    "date": "日期字段",
}

# FindResult executeType radios.
_NOT_FOUND = {
    0: "中止流程，或继续执行查找结果分支",
    1: "在工作表中新增记录后继续执行",
    2: "继续执行",
}

_ACTION_LABELS = {
    1: "新增记录",
    2: "更新记录",
    3: "删除记录",
    6: "刷新单条数据",
    20: "获取关联记录",
    21: "批量新增",
    400: "从工作表获取多条",
    401: "从记录获取多条",
    402: "从新增节点获取",
    403: "从数组获取",
    404: "从代码块数组获取",
    406: "查询工作表",
    407: "从多条数据中获取",
    411: "批量操作",
    412: "批量更新",
    413: "批量删除",
    420: "获取记录链接",
    421: "查找并更新",
    422: "查找并删除",
    100: "数值运算",
    101: "日期运算",
    102: "JavaScript",
    103: "Python",
    210: "条件循环",
    211: "次数循环",
}

_NODE_TYPE_IDS = {
    "trigger": 0, "worksheet_event": 0, "worksheet": 0, "approval": 0,
    "subprocess": 0, "schedule": 0, "webhook": 0, "button": 0, "date": 0,
    "start": 0, "type_0": 0,
    "branch": 1, "branch_item": 2,
    "fill_in": 3, "approve": 4, "cc": 5,
    "create_record": 6, "add_record": 6, "update_record": 6,
    "delete_record": 6, "batch_create": 6, "batch_update": 6,
    "get_relation": 6, "data_op": 6,
    "get_single": 7, "get_record": 7, "search": 7, "query_update": 7,
    "webhook_node": 8, "compute": 9, "rollup": 9,
    "send_sms": 10, "send_email": 11, "delay": 12,
    "get_multiple": 13, "get_more_record": 13,
    "code": 14, "link": 15, "sub_process": 16,
    "push": 17, "print_file": 18,
    "pbc": 20, "pbp": 20, "json_parse": 21,
    "approval_block": 26, "send_internal_notice": 27,
    "snapshot": 28, "loop": 29, "return": 30,
    "aigc": 31, "plugin": 32, "agent": 33, "vector_search": 34,
}

_EXTRA_TYPE_LABELS = {
    1: "文本",
    4: "座机",
    7: "证件",
    16: "日期时间",
    19: "地区",
    31: "公式",
    32: "文本组合",
    33: "自动编号",
    36: "检查框",
    37: "汇总",
    38: "日期公式",
    46: "时间",
}

_PUSH_LABELS = {
    "1": "弹出提示", "2": "打开记录创建", "3": "打开详情", "4": "打开视图",
    "5": "打开自定义页面", "6": "打开链接", "7": "卡片通知", "8": "声音播放",
}

_ACCOUNT_TYPES = {
    1: "人员", 2: "角色", 6: "字段", 7: "文本", 8: "部门",
    9: "职位", 10: "组织角色",
}


def _load_type_names() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify-platform.py")
    spec = importlib.util.spec_from_file_location("verify_platform_editor_types", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TYPE_NAMES


TYPE_NAMES = _load_type_names()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value):
    return field_mappings._as_int(value)


def _sources(node, detail=None):
    return field_mappings._sources(node, detail)


def _first(source, *keys) -> str:
    return field_mappings._first(source, *keys)


def _pick(sources, *keys):
    """Last non-empty value across the node, its config, and a detail body."""
    found = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            if key not in source:
                continue
            value = source.get(key)
            if value in (None, "", [], {}):
                if found is None:
                    found = value
                continue
            found = value
    return found


def _type_id(node) -> int | None:
    return field_mappings._type_id(node)


def _action_id(node) -> int | None:
    return field_mappings._action_id(node)


def _kind(node) -> str:
    if not isinstance(node, dict):
        return ""
    return _text(node.get("triggerType") or node.get("nodeType") or node.get("node_type")).lower()


def flow_node_type(node) -> int:
    """typeId the editor sends as flowNodeType. Unknown kinds stay on 6."""
    type_id = _type_id(node)
    if type_id is not None:
        return type_id
    return _NODE_TYPE_IDS.get(_kind(node), 6)


def _type_label(type_id) -> str:
    if type_id is None:
        return ""
    return field_mappings.CONTROL_TYPE_LABELS.get(type_id) or _EXTRA_TYPE_LABELS.get(type_id, "")


def _flag_on(value) -> bool:
    return value in (1, "1", True)


def _controls(sources) -> dict:
    return field_mappings._controls_by_id(sources)


def _formula_map(sources) -> dict:
    return field_mappings._formula_map(sources)


def _node_index(sources) -> dict:
    return field_mappings._node_index(sources, [])


def _detail_was_read(node) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get(_DETAIL_READ):
        return True
    config = node.get("config")
    return isinstance(config, dict) and bool(config.get(_DETAIL_READ))


def is_helper_node(node) -> bool:
    """Platform bookkeeping and the unused 获取多条人工项 (action 405)."""
    if not isinstance(node, dict):
        return False
    if flow_node_type(node) in _HELPER_TYPE_IDS:
        return True
    if flow_node_type(node) == 13 and _action_id(node) in _HELPER_ACTION_IDS:
        return True
    return _kind(node) in {"system", "tools"}


def config_is_empty(node) -> bool:
    """True when the node has a config object and nothing editor-facing on it.

    An empty shell is filled by the empty-config getNodeDetail pass. Nodes
    that already carry a worksheet, a filter, or field rows are not shells.
    """
    if not isinstance(node, dict):
        return False
    config = node.get("config")
    if not isinstance(config, dict) or config:
        return False
    for key in ("fields", "appName", "appId", "conditions", "filters", "operateCondition", "worksheetId"):
        if node.get(key) not in (None, "", [], {}):
            return False
    return True


def _sheet_name(sources) -> str:
    return _text(_pick(
        sources, "appName", "worksheetName", "sourceEntityName", "worksheetId",
    ))


def _walk_conditions(value, found):
    if isinstance(value, dict):
        if value.get("filedId") or value.get("fieldId") or value.get("conditionId") or value.get("filedValue"):
            found.append(value)
        for child in value.values():
            _walk_conditions(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk_conditions(child, found)


def _real_conditions(sources) -> list:
    found = []
    for key in ("filters", "conditions", "operateCondition"):
        _walk_conditions(_pick(sources, key), found)
    # A bare placeholder dict inside an empty group is not a condition.
    return [
        item for item in found
        if item.get("filedId") or item.get("fieldId") or item.get("conditionId") or item.get("filedValue")
    ]


def _has_real_conditions(node, detail=None) -> bool:
    return bool(_real_conditions(_sources(node, detail)))


def _is_query_like(node) -> bool:
    if is_helper_node(node):
        return False
    if flow_node_type(node) in _QUERY_TYPE_IDS:
        return True
    return _kind(node) in _QUERY_NODE_TYPES


def _is_branch_item(node) -> bool:
    if flow_node_type(node) == 2:
        return True
    return _kind(node) in _BRANCH_ITEM_TYPES


def _next_id(node) -> str:
    for source in _sources(node):
        text = _first(source, "nextId", "next_id")
        if text:
            return text
    return ""


def _arm_ends_immediately(node, flow_nodes=None) -> bool:
    """An arm with nowhere to go is the editor's empty default/else path."""
    nxt = _next_id(node)
    if not nxt:
        return True
    if isinstance(flow_nodes, dict) and nxt not in flow_nodes:
        return True
    return False


def _trigger_id(sources) -> str:
    value = _pick(sources, "triggerId", "trigger_id", "event")
    return _text(value)


def _worksheet_trigger_missing_event(node) -> bool:
    """Legacy start nodes name a worksheet and leave triggerId for getNodeDetail.

    A V3 triggerType such as worksheet_event already says which family of
    trigger this is, so it is not refetched just to rediscover that label.
    """
    if is_helper_node(node):
        return False
    kind = _kind(node)
    if kind in _KNOWN_TRIGGER_KINDS:
        return False
    if flow_node_type(node) != 0 and kind not in {"trigger", "type_0", "start"}:
        return False
    sources = _sources(node)
    if not _sheet_name(sources) and not _text(_pick(sources, "appId", "worksheetId")):
        return False
    return not _trigger_id(sources)


def _assign_fields_unnamed(node) -> bool:
    sources = _sources(node)
    ids = _pick(sources, "assignFieldIds")
    if not isinstance(ids, list) or not ids:
        return False
    names = _pick(sources, "assignFieldNames")
    if isinstance(names, list) and any(_text(name) for name in names):
        return False
    controls = _controls(sources)
    for item in ids:
        if isinstance(item, str):
            field_id = item.strip()
        elif isinstance(item, dict):
            field_id = _first(item, "fieldId", "controlId", "id")
        else:
            field_id = ""
        control = controls.get(field_id) or {}
        if field_id and not (control.get("controlName") or control.get("name")):
            return True
    return False


def _has_unresolved_formula(node) -> bool:
    sources = _sources(node)
    formula_map = _formula_map(sources)
    index = _node_index(sources)
    try:
        blob = json.dumps(node, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    for match in _FORMULA_TOKEN.finditer(blob):
        _display, ok, *_rest = field_mappings._lookup_formula(match.group(1), formula_map, index)
        if not ok:
            return True
    return False


def _primary_missing(node) -> bool:
    """Delay duration and code body are the settings the official save drops."""
    type_id = flow_node_type(node)
    sources = _sources(node)
    if type_id == 12:
        return not any(_text(_pick(sources, key)) for key in ("executeTime", "time", "unit"))
    if type_id == 14:
        return not _text(_pick(sources, "code"))
    return False


def needs_editor_detail(node, flow_nodes=None) -> bool:
    """True when a readable editor line would otherwise be empty or unresolved.

    Empty config shells are left to the empty-config pass. A branch arm that
    ends immediately with no condition is the default/else path and is not
    fetched again. A query whose filters are still an empty placeholder is
    fetched, because flowNode/get stores that placeholder while the editor
    reads conditions from getNodeDetail.
    """
    if not isinstance(node, dict) or is_helper_node(node):
        return False
    if config_is_empty(node):
        return False
    if _detail_was_read(node):
        return field_mappings.needs_node_detail(node) or _has_unresolved_formula(node)
    if field_mappings.needs_node_detail(node) or _has_unresolved_formula(node):
        return True
    if _is_query_like(node) and not _has_real_conditions(node):
        return True
    if _is_branch_item(node) and not _has_real_conditions(node) and not _arm_ends_immediately(node, flow_nodes):
        return True
    if _worksheet_trigger_missing_event(node) or _assign_fields_unnamed(node):
        return True
    if _primary_missing(node):
        return True
    return False


def _lift_editor_keys(flat, detail) -> dict:
    """Keep conditions that sit beside flowNode, which prepare_detail drops."""
    lifted = dict(flat or {})
    raw = detail.get("data") if isinstance(detail, dict) and isinstance(detail.get("data"), dict) else detail
    if not isinstance(raw, dict):
        return lifted
    for key in _EDITOR_KEYS:
        if key not in raw:
            continue
        current = lifted.get(key)
        incoming = raw.get(key)
        if current in (None, "", [], {}) and incoming not in (None, "", [], {}):
            lifted[key] = incoming
        elif key in _EMPTY_LIST_KEYS and key not in lifted and isinstance(incoming, list):
            lifted[key] = incoming
    return lifted


def merge_detail_into(node, detail) -> dict:
    """Copy editor fields from getNodeDetail onto the structure node."""
    if not isinstance(node, dict):
        return {}
    flat = _lift_editor_keys(field_mappings.prepare_detail(detail), detail)
    field_mappings.merge_detail_into(node, flat)
    node[_DETAIL_READ] = True
    config = node.get("config")
    if isinstance(config, dict):
        config[_DETAIL_READ] = True
    for key in _EDITOR_KEYS:
        if key not in flat:
            continue
        value = flat.get(key)
        if value in (None, "", {}, []) and key not in _EMPTY_LIST_KEYS:
            continue
        node[key] = value
        if isinstance(config, dict):
            config[key] = value
    return node


def _condition_label(condition_id) -> str:
    key = _text(condition_id)
    if not key:
        return ""
    return _CONDITION_LABELS.get(key, f"条件{key}")


def _value_bits(entry, formula_map, index, controls):
    if not isinstance(entry, dict):
        text = _text(entry)
        return (text, True, "") if text else ("", True, "")
    node_id = _first(entry, "nodeId")
    control_id = _first(entry, "controlId", "fieldId")
    node_name = _first(entry, "nodeName") or (index.get(node_id) or {}).get("name") or ""
    control_name = _first(entry, "controlName", "fieldValueName")
    if not control_name and control_id:
        control = controls.get(control_id) or {}
        control_name = _first(control, "controlName", "name")
    raw_value = entry.get("value")
    if isinstance(raw_value, str) and _FORMULA_TOKEN.search(raw_value):
        rendered, resolved, *_rest = field_mappings._render_formula(raw_value, formula_map, index)
        return rendered, resolved, raw_value
    if node_name and control_name:
        return f"{node_name} / {control_name}", True, ""
    if node_name or control_name:
        resolved = not (control_id and not control_name)
        return node_name or control_name, resolved, ""
    if control_id and not control_name:
        return control_id, False, ""
    if raw_value not in (None, ""):
        return _text(raw_value), True, ""
    label = _first(entry, "value")
    return label, True, ""


def _render_condition(item, formula_map, index, controls) -> tuple:
    field_id = _first(item, "filedId", "fieldId")
    control = controls.get(field_id) or {}
    type_id = _as_int(item.get("filedTypeId"))
    if type_id is None:
        type_id = _as_int(item.get("type"))
    if type_id is None:
        type_id = _as_int(control.get("type"))
    field_name = _first(item, "filedValue", "fieldName") or _first(control, "controlName", "name") or field_id
    type_label = _type_label(type_id)
    label = f"[{type_label}] {field_name}" if type_label else field_name
    op = _condition_label(item.get("conditionId"))
    unresolved = bool(field_id and field_name == field_id and not _first(item, "filedValue") and not control)
    values = []
    tokens = []
    dynamic = False
    for entry in item.get("conditionValues") or []:
        if isinstance(entry, dict) and (entry.get("controlId") or entry.get("nodeId")):
            dynamic = True
        shown, ok, token = _value_bits(entry, formula_map, index, controls)
        if shown:
            values.append(shown)
        if token:
            tokens.append(token)
        if not ok:
            unresolved = True
    condition_id = _text(item.get("conditionId"))
    if condition_id in _VALUELESS_CONDITIONS or not values:
        body = f"{label} {op}".strip()
    else:
        body = f"{label} {op} {'、'.join(values)}".strip()
    flags = []
    if dynamic or "ignoreEmpty" in item:
        flags.append(f"条件异常时忽略：{'是' if _flag_on(item.get('ignoreEmpty')) else '否'}")
    if dynamic or "ignoreValueEmpty" in item:
        flags.append(f"值为空时忽略：{'是' if _flag_on(item.get('ignoreValueEmpty')) else '否'}")
    if "ignoreCase" in item:
        flags.append(f"忽略大小写：{'是' if _flag_on(item.get('ignoreCase')) else '否'}")
    if flags:
        body = f"{body}；{'；'.join(flags)}"
    return body, unresolved, tokens


def _and_group(group, formula_map, index, controls):
    parts = []
    unresolved = False
    tokens = []
    items = group if isinstance(group, list) else [group]
    for item in items:
        if not isinstance(item, dict) or not (
            item.get("filedId") or item.get("fieldId") or item.get("conditionId") or item.get("filedValue")
        ):
            continue
        text, pending, item_tokens = _render_condition(item, formula_map, index, controls)
        if text:
            parts.append(text)
        unresolved = unresolved or pending
        tokens.extend(item_tokens)
    if not parts:
        return "", unresolved, tokens
    if len(parts) == 1:
        return parts[0], unresolved, tokens
    return " 且 ".join(parts), unresolved, tokens


def _two_dimensional(value, formula_map, index, controls):
    groups = value if isinstance(value, list) else []
    # A flat list of condition dicts is one AND group.
    if groups and all(isinstance(item, dict) for item in groups):
        groups = [groups]
    rendered = []
    unresolved = False
    tokens = []
    for group in groups:
        text, pending, group_tokens = _and_group(group, formula_map, index, controls)
        if text:
            rendered.append(text)
        unresolved = unresolved or pending
        tokens.extend(group_tokens)
    if not rendered:
        return "", unresolved, tokens
    if len(rendered) == 1:
        return rendered[0], unresolved, tokens
    return " 或 ".join(f"（{part}）" for part in rendered), unresolved, tokens


def _render_filter(sources, formula_map, index, controls):
    """Prefer filters (且/或 groups). Fall back to conditions, then operateCondition."""
    filters = _pick(sources, "filters")
    chunks = []
    unresolved = False
    tokens = []
    if isinstance(filters, list) and filters and all(isinstance(item, dict) for item in filters):
        joiner = "且" if _as_int(filters[0].get("spliceType")) == 1 else "或"
        for group in filters:
            text, pending, group_tokens = _two_dimensional(
                group.get("conditions"), formula_map, index, controls,
            )
            if text:
                chunks.append(text)
            unresolved = unresolved or pending
            tokens.extend(group_tokens)
        if chunks:
            if len(chunks) == 1:
                return chunks[0], unresolved, tokens
            return f" {joiner} ".join(f"（{part}）" for part in chunks), unresolved, tokens
    for key in ("conditions", "operateCondition"):
        text, pending, group_tokens = _two_dimensional(_pick(sources, key), formula_map, index, controls)
        if text:
            return text, pending, group_tokens
    return "", False, []


def _sort_rule(type_id, is_asc) -> str:
    ascending = is_asc is True or is_asc in (1, "1", "true")
    if is_asc is None or is_asc == "":
        return "未选择规则"
    if type_id in (6, 8, 31, 29):
        return "1 → 9" if ascending else "9 → 1"
    if type_id == 2:
        return "A → Z" if ascending else "Z → A"
    if type_id == 46:
        return "最早的在前" if ascending else "最晚的在前"
    return "最旧的在前" if ascending else "最新的在前"


def _sort_lines(sources, controls, show_random) -> tuple:
    sorts = _pick(sources, "sorts")
    lines = []
    unresolved = False
    real = []
    if isinstance(sorts, list):
        real = [item for item in sorts if isinstance(item, dict) and (item.get("controlId") or item.get("fieldId"))]
    if not real:
        lines.append("排序规则：无")
    else:
        parts = []
        for item in real:
            control_id = _first(item, "controlId", "fieldId")
            control = controls.get(control_id) or {}
            name = _first(item, "controlName") or _first(control, "controlName", "name") or control_id
            type_id = _as_int(item.get("controlType"))
            if type_id is None:
                type_id = _as_int(control.get("type"))
            type_label = _type_label(type_id)
            prefix = f"[{type_label}] " if type_label else ""
            if control_id and name == control_id and not control:
                unresolved = True
            parts.append(f"{prefix}{name} {_sort_rule(type_id, item.get('isAsc'))}")
        lines.append("排序规则：" + "；".join(parts))
    if show_random:
        lines.append(f"忽略排序规则，随机获取：{'是' if _pick(sources, 'random') is True else '否'}")
    return lines, unresolved


def _not_found_lines(sources) -> list:
    execute_type = _as_int(_pick(sources, "executeType"))
    if execute_type is None:
        return ["未获取到数据时：未返回"]
    label = _NOT_FOUND.get(execute_type, f"executeType={execute_type}")
    lines = [f"未获取到数据时：{label}"]
    if execute_type == 1:
        lines.append(f"新增失败时继续执行：{'是' if _pick(sources, 'ignoreError') is True else '否'}")
    return lines


def _shows_random(action_id) -> bool:
    return action_id in (406, 407)


def _query_lines(node, sources, formula_map, index, controls, detail_seen) -> tuple:
    lines = []
    gaps = []
    unresolved = False
    action_id = _action_id(node)
    if action_id is not None and action_id in _ACTION_LABELS:
        lines.append(f"获取方式：{_ACTION_LABELS[action_id]}")
    sheet = _sheet_name(sources)
    select_name = _text(_pick(sources, "selectNodeName"))
    if sheet:
        lines.append(f"选择工作表：{sheet}")
    elif select_name:
        lines.append(f"选择多条数据节点：{select_name}")
    elif action_id == 420:
        link = _text(_pick(sources, "link"))
        lines.append(f"记录链接：{link or '未返回'}")
    filter_text, filter_pending, tokens = _render_filter(sources, formula_map, index, controls)
    unresolved = unresolved or filter_pending
    if filter_text:
        lines.append(f"筛选条件：{filter_text}")
    elif detail_seen:
        lines.append("筛选条件：无")
    else:
        lines.append("筛选条件：结构数据未包含筛选条件")
        gaps.append({
            "field": "conditions",
            "reason": "not_in_structure",
            "detail": "flowNode/get 的 operateCondition 可能是空占位；筛选条件在 getNodeDetail 的 conditions 或 filters",
        })
    if action_id == 421:
        find_fields = _pick(sources, "findFields")
        if isinstance(find_fields, list) and find_fields:
            names = []
            for item in find_fields:
                if isinstance(item, dict):
                    names.append(_first(item, "fieldName", "controlName", "fieldId"))
                elif _text(item):
                    names.append(_text(item))
            if names:
                lines.append("查找字段：" + "、".join(names))
        else:
            lines.append("查找字段：无")
    sort_lines, sort_pending = _sort_lines(
        sources, controls, _shows_random(action_id) or flow_node_type(node) == 13,
    )
    lines.extend(sort_lines)
    unresolved = unresolved or sort_pending
    if flow_node_type(node) == 7 or action_id in (406, 407, 420, 421, 422):
        lines.extend(_not_found_lines(sources))
    if action_id == 413:
        lines.append(f"彻底删除记录，不放入回收站：{'是' if _pick(sources, 'destroy') is True else '否'}")
    count = _pick(sources, "numberFieldValue")
    if isinstance(count, dict) and count.get("fieldValue") not in (None, ""):
        lines.append(f"获取条数：{count.get('fieldValue')}")
    if flow_node_type(node) == 13 and _pick(sources, "execute") is not None:
        lines.append(f"立即执行：{'是' if _pick(sources, 'execute') is True else '否'}")
    return lines, gaps, unresolved, tokens


def _branch_item_lines(node, sources, formula_map, index, controls, detail_seen, flow_nodes) -> tuple:
    text, pending, tokens = _render_filter(sources, formula_map, index, controls)
    if text:
        return [f"分支条件：{text}"], [], pending, tokens, False
    if _arm_ends_immediately(node, flow_nodes) or detail_seen:
        if _arm_ends_immediately(node, flow_nodes):
            line = "默认分支（其他）：条件为空，此分支在此结束"
        else:
            line = "默认分支（其他）：条件为空"
        return [line], [], False, [], True
    return (
        ["分支条件：结构数据未包含条件"],
        [{
            "field": "operateCondition",
            "reason": "not_in_structure",
            "detail": "分支项的 operateCondition 可能是空占位；条件在 getNodeDetail 的 conditions",
        }],
        False,
        [],
        False,
    )


def _gateway_lines(sources) -> list:
    gateway = _as_int(_pick(sources, "gatewayType"))
    if gateway == 1:
        lines = ["分支方式：并行分支（满足条件的路径都执行）"]
    elif gateway == 2:
        lines = ["分支方式：唯一分支（只走第一条满足的路径）"]
    else:
        lines = ["分支方式：未返回"]
    flow_ids = _pick(sources, "flowIds")
    if isinstance(flow_ids, list):
        lines.append(f"分支数：{len(flow_ids)}")
    result = _text(_pick(sources, "resultFlow"))
    if result:
        lines.append(f"结果分支：{result}")
    paths = None
    for source in sources:
        config = source.get("config") if isinstance(source.get("config"), dict) else source
        if isinstance(config, dict) and isinstance(config.get("paths"), list):
            paths = config.get("paths")
    if isinstance(paths, list) and paths:
        for index, path in enumerate(paths, start=1):
            if not isinstance(path, dict):
                continue
            name = _text(path.get("name") or path.get("alias")) or f"路径{index}"
            if path.get("condition"):
                lines.append(f"路径 {name}：已配置条件")
            elif path.get("result_type") or path.get("resultType"):
                lines.append(f"路径 {name}：结果 {path.get('result_type') or path.get('resultType')}")
            else:
                lines.append(f"路径 {name}：默认分支（其他）")
    return lines


def _field_names(ids, controls) -> tuple:
    names = []
    unresolved = False
    if not isinstance(ids, list):
        return names, False
    for item in ids:
        if isinstance(item, dict):
            field_id = _first(item, "fieldId", "controlId", "id")
            name = _first(item, "controlName", "fieldName", "name")
        else:
            field_id = _text(item)
            name = ""
        control = controls.get(field_id) or {}
        name = name or _first(control, "controlName", "name")
        if name:
            names.append(name)
        elif field_id:
            names.append(field_id)
            unresolved = True
    return names, unresolved


def _trigger_lines(node, sources, formula_map, index, controls, detail_seen) -> tuple:
    lines = []
    gaps = []
    unresolved = False
    kind = _kind(node)
    kind_label = _TRIGGER_KIND_LABELS.get(kind, "")
    if kind_label:
        lines.append(f"触发类型：{kind_label}")
    sheet = _sheet_name(sources)
    if sheet:
        lines.append(f"触发工作表：{sheet}")
    event_id = _trigger_id(sources)
    if event_id in _TRIGGER_EVENTS:
        lines.append(f"触发事件：{_TRIGGER_EVENTS[event_id]}")
    elif event_id:
        lines.append(f"触发事件：{event_id}")
    elif kind_label:
        lines.append(f"触发事件：{kind_label}")
    elif detail_seen:
        lines.append("触发事件：未返回")
        gaps.append({
            "field": "triggerId",
            "reason": "not_in_detail",
            "detail": "getNodeDetail 未返回 triggerId，无法区分新增、更新或删除",
        })
    else:
        lines.append("触发事件：结构数据未包含")
        gaps.append({
            "field": "triggerId",
            "reason": "not_in_structure",
            "detail": "工作表已绑定但结构没有 triggerId；事件在 getNodeDetail",
        })
    app_type = _as_int(_pick(sources, "appType"))
    if app_type == 5:
        repeat = _text(_pick(sources, "repeatType"))
        if repeat:
            lines.append(f"定时重复：{repeat}")
        when = _text(_pick(sources, "executeTime"))
        if when:
            lines.append(f"开始时间：{when}")
    names, pending = _field_names(_pick(sources, "assignFieldIds"), controls)
    named = _pick(sources, "assignFieldNames")
    if isinstance(named, list) and any(_text(item) for item in named):
        names = [_text(item) for item in named if _text(item)]
        pending = False
    unresolved = unresolved or pending
    worksheet_trigger = bool(
        sheet or event_id in _TRIGGER_EVENTS or kind in _WORKSHEET_EVENT_KINDS
        or kind in {"trigger", "type_0", "start"}
    )
    if names:
        lines.append("触发字段：" + "、".join(names))
    elif worksheet_trigger:
        lines.append("触发字段：不限")
    filter_text, filter_pending, tokens = _render_filter(sources, formula_map, index, controls)
    unresolved = unresolved or filter_pending
    if filter_text:
        lines.append(f"进入条件：{filter_text}")
    elif worksheet_trigger:
        lines.append("进入条件：无（全部记录进入）")
    return lines, gaps, unresolved, tokens


def _account_text(account) -> str:
    if not isinstance(account, dict):
        return _text(account)
    kind = _text(account.get("kind")) or _ACCOUNT_TYPES.get(_as_int(account.get("type")), "")
    name = _first(account, "entityName", "roleName", "name", "fullname", "email", "userId", "fieldId")
    return " ".join(part for part in (kind, name) if part)


def _assignment_lines(node, detail):
    mapping = field_mappings.resolve_field_mappings(node, detail)
    if not mapping:
        return [], False
    return list(mapping.get("lines") or []), any(
        item.get("unresolved") for item in mapping.get("assignments") or []
    )


def _generic_lines(sources) -> list:
    lines = []
    accounts = _pick(sources, "accounts")
    if isinstance(accounts, list) and accounts:
        rendered = [text for text in (_account_text(item) for item in accounts) if text]
        if rendered:
            lines.append("收件人：" + "、".join(rendered))
    pairs = (
        ("method", "请求方法"),
        ("url", "请求地址"),
        ("subject", "邮件主题"),
        ("content", "内容"),
        ("executeTime", "执行时间"),
        ("time", "延时"),
        ("unit", "延时单位"),
        ("fieldValue", "公式"),
        ("prompt", "提示词"),
        ("model", "模型"),
        ("subProcessId", "子流程"),
        ("fileName", "文件名"),
        ("link", "链接"),
        ("viewId", "视图"),
    )
    for key, label in pairs:
        value = _pick(sources, key)
        if isinstance(value, str) and value.strip():
            shown = value.strip()
            if len(shown) > 180:
                shown = shown[:180] + "…"
            lines.append(f"{label}：{shown}")
    push = _text(_pick(sources, "pushType"))
    if push:
        lines.append(f"推送：{_PUSH_LABELS.get(push, push)}")
    code = _pick(sources, "code")
    if isinstance(code, str) and code.strip():
        lines.append(f"代码：已配置（{len(code.strip())} 字符）")
    inputs = _pick(sources, "inputDatas")
    if isinstance(inputs, list) and inputs:
        lines.append(f"代码输入：{len(inputs)} 项")
    form = _pick(sources, "formProperties")
    if isinstance(form, list) and form:
        lines.append(f"填写字段：{len(form)} 项")
    process = None
    for source in sources:
        current = source.get("process")
        if isinstance(current, dict) and current.get("processId"):
            process = current
    if process:
        lines.append(f"内部流程：{process.get('processId')}")
    return lines


def _gap_for_missing_primary(type_id, detail_seen) -> tuple:
    if type_id == 12:
        if detail_seen:
            return (
                "缺口：延时时长未能从官方接口取得",
                {
                    "field": "executeTime",
                    "reason": "not_returned",
                    "detail": "延时时长在官方 saveNode 后可能归零，getNodeDetail 未返回 executeTime、time 或 unit",
                },
            )
        return (
            "延时：结构数据未包含时长",
            {
                "field": "executeTime",
                "reason": "not_in_structure",
                "detail": "结构没有延时时长；需要 getNodeDetail。若详情仍为空，则官方接口未返回该设置",
            },
        )
    if type_id == 14:
        if detail_seen:
            return (
                "缺口：代码块正文未能从官方接口取得",
                {
                    "field": "code",
                    "reason": "not_returned",
                    "detail": "代码块的官方保存会失败，getNodeDetail 未返回 code",
                },
            )
        return (
            "代码：结构数据未包含正文",
            {
                "field": "code",
                "reason": "not_in_structure",
                "detail": "结构没有代码正文；需要 getNodeDetail。若详情仍为空，则官方接口未返回该设置",
            },
        )
    return "", None


def _raw_view(node, sources, tokens) -> dict:
    raw = {
        "typeId": _type_id(node) if _type_id(node) is not None else flow_node_type(node),
        "actionId": _action_id(node),
        "appId": _text(_pick(sources, "appId", "worksheetId")),
        "appName": _sheet_name(sources),
        "executeType": _pick(sources, "executeType"),
        "random": _pick(sources, "random"),
        "triggerId": _trigger_id(sources) or None,
        "findFields": _pick(sources, "findFields") if isinstance(_pick(sources, "findFields"), list) else [],
        "sorts": _pick(sources, "sorts") if isinstance(_pick(sources, "sorts"), list) else [],
        "filters": _pick(sources, "filters") if isinstance(_pick(sources, "filters"), list) else [],
        "conditions": _pick(sources, "conditions") if isinstance(_pick(sources, "conditions"), list) else [],
        "operateCondition": _pick(sources, "operateCondition") if isinstance(_pick(sources, "operateCondition"), list) else [],
        "assignFieldIds": _pick(sources, "assignFieldIds") if isinstance(_pick(sources, "assignFieldIds"), list) else [],
        "tokens": tokens,
    }
    fields = _pick(sources, "fields")
    if isinstance(fields, list) and fields:
        raw["fields"] = fields
    return raw


def resolve_editor_config(node, detail=None, flow_nodes=None, detail_seen=None) -> dict | None:
    """Editor lines plus the raw ids and tokens they were rendered from."""
    if not isinstance(node, dict):
        return None
    flat = _lift_editor_keys(field_mappings.prepare_detail(detail), detail) if detail else None
    if flat == {}:
        flat = None
    sources = _sources(node, flat)
    if detail_seen is None:
        detail_seen = bool(flat) or _detail_was_read(node)
    type_id = flow_node_type(node)
    action_id = _action_id(node)
    formula_map = _formula_map(sources)
    index = _node_index(sources)
    controls = _controls(sources)
    kind = "node"
    default_branch = False
    gaps = []
    unresolved = False
    tokens = []

    if is_helper_node(node):
        if type_id == 13 and action_id in _HELPER_ACTION_IDS:
            label = "获取多条的人工项（actionId=405），编辑器不提供业务配置"
        else:
            label = TYPE_NAMES.get(type_id, _kind(node) or "平台保留节点")
        return {
            "kind": "helper",
            "helper": True,
            "type_id": type_id,
            "action_id": action_id,
            "lines": [f"非业务节点：{label}"],
            "raw": {"typeId": type_id, "actionId": action_id},
            "gaps": [],
        }

    lines = []
    if type_id == 0 or _kind(node) in _TRIGGER_KIND_LABELS or _kind(node) in {"trigger", "type_0", "start"}:
        kind = "trigger"
        trigger_lines, trigger_gaps, pending, trigger_tokens = _trigger_lines(
            node, sources, formula_map, index, controls, detail_seen,
        )
        lines.extend(trigger_lines)
        gaps.extend(trigger_gaps)
        unresolved = unresolved or pending
        tokens.extend(trigger_tokens)
    elif type_id == 1 or _kind(node) == "branch":
        kind = "branch"
        lines.extend(_gateway_lines(sources))
    elif _is_branch_item(node):
        kind = "branch_item"
        item_lines, item_gaps, pending, item_tokens, default_branch = _branch_item_lines(
            node, sources, formula_map, index, controls, detail_seen, flow_nodes,
        )
        lines.extend(item_lines)
        gaps.extend(item_gaps)
        unresolved = unresolved or pending
        tokens.extend(item_tokens)
    elif _is_query_like(node):
        kind = "query"
        query_lines, query_gaps, pending, query_tokens = _query_lines(
            node, sources, formula_map, index, controls, detail_seen,
        )
        lines.extend(query_lines)
        gaps.extend(query_gaps)
        unresolved = unresolved or pending
        tokens.extend(query_tokens)
        if action_id in (2, 412, 421, 1, 21):
            assignment_lines, pending = _assignment_lines(node, flat)
            lines.extend(assignment_lines)
            unresolved = unresolved or pending
    elif type_id == 6 or _kind(node) in {
        "create_record", "add_record", "update_record", "delete_record",
        "batch_create", "batch_update", "get_relation",
    }:
        kind = "data_op"
        if action_id in _ACTION_LABELS:
            lines.append(f"操作：{_ACTION_LABELS[action_id]}")
        assignment_lines, pending = _assignment_lines(node, flat)
        if assignment_lines:
            lines.extend(assignment_lines)
            unresolved = unresolved or pending
        elif _sheet_name(sources):
            lines.append(f"目标工作表：{_sheet_name(sources)}")
        if action_id == 3:
            lines.append(f"彻底删除记录，不放入回收站：{'是' if _pick(sources, 'destroy') is True else '否'}")
        filter_text, pending, filter_tokens = _render_filter(sources, formula_map, index, controls)
        if filter_text:
            lines.append(f"筛选条件：{filter_text}")
            unresolved = unresolved or pending
            tokens.extend(filter_tokens)
    else:
        kind = TYPE_NAMES.get(type_id, _kind(node) or "node")

    if type_id not in (0, 1, 2) and not _is_query_like(node):
        lines.extend(_generic_lines(sources))
    elif type_id in (16, 26) or _kind(node) in {"sub_process", "approval_block"}:
        lines.extend(_generic_lines(sources))

    if type_id in (12, 14) and _primary_missing(node):
        text, gap = _gap_for_missing_primary(type_id, detail_seen)
        if text:
            lines.append(text)
        if gap:
            gaps.append(gap)

    if not lines:
        lines.append(f"{TYPE_NAMES.get(type_id, '节点')}：结构未包含可显示的编辑项")
        if not detail_seen:
            gaps.append({
                "field": "config",
                "reason": "not_in_structure",
                "detail": "结构没有该节点的编辑项；需要 getNodeDetail",
            })

    result = {
        "kind": kind,
        "helper": False,
        "type_id": type_id,
        "action_id": action_id,
        "lines": lines,
        "raw": _raw_view(node, sources, tokens),
        "gaps": gaps,
    }
    if default_branch:
        result["default_branch"] = True
    if unresolved:
        result["unresolved"] = True
    return result
