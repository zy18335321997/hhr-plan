#!/usr/bin/env python3
"""Shared computation for the derived project_context.json sections.

Both context builders use this module:

- ``build_context.py`` walks the legacy ``_extracted/<module>/<worksheet>/fields.json``
  layout (workflow-analyzer output) and calls :func:`compute_context_fields`.
- ``extract-project.py`` builds the same sections from its MCP ``ws_map`` and
  ``node_data``. Modern extraction format keeps only id/name/type/required/isTitle
  per field, so association targets and auto-number increase formats are often
  absent. In that case the caller falls back to
  :func:`compute_workflow_edges` (workflow read/write edges) and
  :func:`auto_number_prefixes_from_field_names`.

Field types appear as HAP control-type ids (29 / 33 / 34) in the legacy layout
and as English names ("Relation" / "AutoNumber" / "SubTable") in MCP output.
Both spellings are accepted; the legacy output stays byte-for-byte the same.
"""

from collections import Counter, defaultdict

RELATION_TYPE_IDS = {29}
RELATION_TYPE_NAMES = {"Relation"}
AUTO_NUMBER_TYPE_IDS = {33}
AUTO_NUMBER_TYPE_NAMES = {"AutoNumber"}

HUB_MIN_REFS = 3
_HEX_CHARS = set("0123456789abcdef")
# Placeholder worksheet name written by extraction tools when the real trigger
# sheet cannot be resolved; it is not a table. Other scripts filter it too
# (sheet_workflows.py, search.py, generate_topology.py).
_PLACEHOLDER_SHEETS = {"未分类"}
# Suffixes projects append to an auto-number field name ("客户编号" -> "客户").
_AUTO_NUMBER_NAME_SUFFIXES = ("编号", "单号", "序号", "号码", "号", "码")
# The platform's default auto-number control name, not a project convention.
_DEFAULT_AUTO_NUMBER_NAMES = {"自动编号"}


def _field_name(field):
    return field.get("name") or field.get("controlName") or ""


def is_relation_field(field):
    if not isinstance(field, dict):
        return False
    field_type = field.get("type")
    return field_type in RELATION_TYPE_IDS or field_type in RELATION_TYPE_NAMES


def is_auto_number_field(field):
    if not isinstance(field, dict):
        return False
    field_type = field.get("type")
    return field_type in AUTO_NUMBER_TYPE_IDS or field_type in AUTO_NUMBER_TYPE_NAMES


def resolve_ref_name(key, ws_id_to_name):
    """Resolve a key that might be a worksheetId (24 hex chars) to its name."""
    if len(key) == 24 and all(c in _HEX_CHARS for c in key):
        return ws_id_to_name.get(key, key)
    return key


def compute_relation_graph(worksheets):
    """Worksheet-to-worksheet edges from association fields.

    ``worksheets`` is an iterable of mappings with ``name``, optional
    ``worksheet_id``, and ``fields``. Targets come from ``targetWorksheetName``
    or ``dataSource``; hex ``dataSource`` ids resolve through the
    worksheet_id -> name map. Returns ``(relation_graph, reverse_refs)`` as
    dicts of sets.
    """
    records = list(worksheets)
    ws_id_to_name = {}
    for ws in records:
        ws_id = ws.get("worksheet_id") or ws.get("id")
        if ws_id:
            ws_id_to_name[ws_id] = ws.get("name", ws_id)

    relation_graph = defaultdict(set)
    reverse_refs = defaultdict(set)
    for ws in records:
        name = ws.get("name", "")
        for field in ws.get("fields") or []:
            if not is_relation_field(field):
                continue
            target = field.get("targetWorksheetName") or field.get("dataSource") or ""
            if target:
                relation_graph[name].add(target)
                reverse_refs[target].add(name)

    resolved_graph = {}
    for src, targets in relation_graph.items():
        resolved_graph[src] = {resolve_ref_name(t, ws_id_to_name) for t in targets}
    resolved_reverse = {}
    for src, refs in reverse_refs.items():
        resolved_reverse[resolve_ref_name(src, ws_id_to_name)] = {
            resolve_ref_name(ref, ws_id_to_name) for ref in refs
        }
    return resolved_graph, resolved_reverse


def compute_workflow_edges(node_data):
    """Worksheet-to-worksheet edges from workflow reads/writes.

    Fallback for extraction formats that keep no association targets. The
    source of an edge is the sheet the workflow is triggered from
    (``trigger_sheet``), then its owning worksheet; the targets are the
    worksheets it reads and writes. The placeholder sheet "未分类" is skipped
    on both sides. Returns ``(relation_graph, reverse_refs)`` as dicts of sets.
    """
    relation_graph = defaultdict(set)
    reverse_refs = defaultdict(set)
    for info in (node_data or {}).values():
        if not isinstance(info, dict):
            continue
        source = info.get("trigger_sheet") or info.get("worksheet") or ""
        if not source or source in _PLACEHOLDER_SHEETS:
            continue
        targets = list(info.get("reads") or []) + list(info.get("writes") or [])
        for target in targets:
            if target and target != source and target not in _PLACEHOLDER_SHEETS:
                relation_graph[source].add(target)
                reverse_refs[target].add(source)
    return dict(relation_graph), dict(reverse_refs)


def compute_hub_tables(reverse_refs):
    """Most-referenced worksheets, capped by the legacy >= 3 refs threshold."""
    ordered = sorted(reverse_refs.items(), key=lambda x: len(x[1]), reverse=True)
    return [
        {"name": name, "referenced_by": list(refs), "ref_count": len(refs)}
        for name, refs in ordered
        if len(refs) >= HUB_MIN_REFS
    ]


def _auto_number_formats(worksheets):
    formats = []
    for ws in worksheets:
        name = ws.get("name", "")
        for field in ws.get("fields") or []:
            if not is_auto_number_field(field):
                continue
            advanced = field.get("advancedSetting") or {}
            fmt = advanced.get("increase", "") if isinstance(advanced, dict) else ""
            if fmt:
                formats.append(f"{name}/{_field_name(field)}: {fmt}")
    return formats


def compute_naming(worksheets, param_names=()):
    """Naming conventions: auto-number prefixes plus a workflow-param sample.

    Prefix extraction keeps the legacy behavior: split each
    "worksheet/field: format" line on ':' and count the first 4 chars after it.
    """
    prefix_counter = Counter()
    for fmt in _auto_number_formats(worksheets):
        parts = fmt.split(":")
        if len(parts) >= 2:
            prefix = parts[1].strip()[:4]
            prefix_counter[prefix] += 1
    return {
        "auto_number_prefixes": [p for p, _ in prefix_counter.most_common()],
        "param_name_sample": list(param_names)[:20],
    }


def auto_number_prefixes_from_field_names(worksheets):
    """Fallback naming signal when increase formats are not in the extraction.

    Derives prefixes from auto-number field names ("客户编号" -> "客户").
    The platform default name "自动编号" is ignored. First-seen order, capped
    at 4 chars, same cap as the legacy format extraction.
    """
    prefix_counter = Counter()
    for ws in worksheets:
        for field in ws.get("fields") or []:
            if not is_auto_number_field(field):
                continue
            name = _field_name(field).strip()
            if not name or name in _DEFAULT_AUTO_NUMBER_NAMES:
                continue
            prefix = name
            for suffix in _AUTO_NUMBER_NAME_SUFFIXES:
                if name.endswith(suffix) and len(name) > len(suffix):
                    prefix = name[:-len(suffix)]
                    break
            prefix_counter[prefix[:4]] += 1
    return [p for p, _ in prefix_counter.most_common()]


def compute_context_fields(worksheets, param_names=()):
    """Compute relation_graph / reverse_refs / hub_tables / naming together.

    Output lists are plain lists (JSON-ready), keyed exactly like the legacy
    build_context.py sections.
    """
    relation_graph, reverse_refs = compute_relation_graph(worksheets)
    return {
        "relation_graph": {k: list(v) for k, v in relation_graph.items()},
        "reverse_refs": {k: list(v) for k, v in reverse_refs.items()},
        "hub_tables": compute_hub_tables(reverse_refs),
        "naming": compute_naming(worksheets, param_names),
    }
