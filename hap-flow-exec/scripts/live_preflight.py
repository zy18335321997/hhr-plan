#!/usr/bin/env python3
"""Read-only platform preflight for worksheet fields and option keys."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

FIELD_TYPE_IDS = {
    "Text": {2},
    "SingleSelect": {9},
    "MultiSelect": {10},
    "Dropdown": {11},
    "Date": {15},
    "DateTime": {16},
    "Relation": {29},
}


def _field_id(field: dict) -> str:
    return (
        field.get("fieldId")
        or field.get("controlId")
        or field.get("id")
        or ""
    )


def _find_fields(value: object) -> list[dict]:
    if isinstance(value, dict):
        for key in ("fields", "controls"):
            candidate = value.get(key)
            if (
                isinstance(candidate, list)
                and all(isinstance(item, dict) for item in candidate)
            ):
                return candidate
        for child in value.values():
            found = _find_fields(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_fields(child)
            if found:
                return found
    return []


def _collect_values(value: object, key_name: str) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == key_name and isinstance(child, str) and child:
                found.add(child)
            found.update(_collect_values(child, key_name))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_values(child, key_name))
    return found


def _collect_field_ids(value: object) -> set[str]:
    found = set()
    if isinstance(value, dict):
        if value.get("kind") == "systemField":
            return found
        field_id = value.get("fieldId")
        if isinstance(field_id, str) and field_id:
            found.add(field_id)
        for child in value.values():
            found.update(_collect_field_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_field_ids(child))
    return found


def _collect_field_usages(
    nodes: list[dict],
    references_by_id: dict[str, dict],
) -> list[tuple[str | None, str]]:
    alias_to_worksheet = {}

    def index_aliases(value: object):
        if isinstance(value, dict):
            alias = value.get("alias") or value.get("nodeAlias")
            config = value.get("config")
            if alias and isinstance(config, dict):
                worksheet = config.get("worksheet")
                if value.get("nodeType") == "get_relation":
                    relation_fields = config.get("fields", [])
                    relation_field_id = (
                        relation_fields[0].get("fieldId")
                        if relation_fields
                        and isinstance(relation_fields[0], dict)
                        else None
                    )
                    relation_reference = references_by_id.get(
                        relation_field_id,
                        {},
                    )
                    worksheet = (
                        relation_reference.get("relation_worksheet_id")
                        or worksheet
                    )
                if worksheet:
                    alias_to_worksheet[alias] = worksheet
            for child in value.values():
                index_aliases(child)
        elif isinstance(value, list):
            for child in value:
                index_aliases(child)

    index_aliases(nodes)
    usages = []

    def walk(value: object, worksheet: str | None = None):
        if isinstance(value, dict):
            if value.get("kind") == "systemField":
                return
            local_worksheet = value.get("worksheet") or worksheet
            field_id = value.get("fieldId")
            if isinstance(field_id, str) and field_id:
                source_alias = value.get("node")
                field_worksheet = (
                    alias_to_worksheet.get(source_alias)
                    or local_worksheet
                )
                usages.append((field_worksheet, field_id))
            for child in value.values():
                walk(child, local_worksheet)
        elif isinstance(value, list):
            for child in value:
                walk(child, worksheet)

    walk(nodes)
    return usages


def _app_id(value: object) -> str:
    if isinstance(value, dict):
        for key in ("appId", "app_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            found = _app_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _app_id(child)
            if found:
                return found
    return ""


def _load_info(
    worksheet_id: str,
    snapshot_dir: str | None,
    hap_bin: str,
    app_id: str | None = None,
) -> dict:
    if snapshot_dir:
        path = Path(snapshot_dir) / f"{worksheet_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))
    command = [hap_bin, "--json", "worksheet", "info", worksheet_id]
    if app_id:
        command.extend(["--app-id", app_id])
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"hap worksheet info failed: {worksheet_id}"
        )
    return json.loads(completed.stdout)


def _load_app_info(
    app_id: str,
    snapshot_dir: str | None,
    hap_bin: str,
) -> dict:
    if snapshot_dir:
        path = Path(snapshot_dir) / f"app-{app_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))
    completed = subprocess.run(
        [hap_bin, "--json", "app", "info", "--app-id", app_id],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"hap app info failed: {app_id}"
        )
    return json.loads(completed.stdout)


def validate_live(
    contract: dict,
    snapshot_dir: str | None = None,
    hap_bin: str = "hap",
) -> list[dict]:
    errors = []
    references = contract.get("field_references", [])
    references_by_id = {
        reference.get("fieldId"): reference
        for reference in references
        if isinstance(reference, dict) and reference.get("fieldId")
    }
    field_usages = _collect_field_usages(
        contract.get("nodes", []),
        references_by_id,
    )
    used_field_ids = {field_id for _, field_id in field_usages}
    for field_id in sorted(used_field_ids - set(references_by_id)):
        errors.append(
            {
                "code": "CONTRACT_FIELD_REFERENCE_MISSING",
                "field_id": field_id,
                "detail": (
                    "节点配置引用了 fieldId，但 field_references 未登记，"
                    "无法进行 live preflight"
                ),
            }
        )
    for worksheet_id, field_id in field_usages:
        reference = references_by_id.get(field_id)
        if (
            reference
            and worksheet_id
            and reference.get("worksheet") != worksheet_id
        ):
            errors.append(
                {
                    "code": "CONTRACT_FIELD_WORKSHEET_MISMATCH",
                    "worksheet_id": worksheet_id,
                    "field_id": field_id,
                    "detail": (
                        "节点使用字段的 worksheet 与 field_references "
                        f"不一致: {reference.get('worksheet')!r}"
                    ),
                }
            )
    worksheet_ids = {
        reference.get("worksheet")
        for reference in references
        if isinstance(reference, dict) and reference.get("worksheet")
    }
    worksheet_ids.update(
        _collect_values(contract.get("nodes", []), "worksheet")
    )
    target_worksheet = contract.get("target", {}).get("worksheet_id")
    if target_worksheet:
        worksheet_ids.add(target_worksheet)
    target_app = contract.get("target", {}).get("app_id")
    if target_app:
        try:
            app_info = _load_app_info(target_app, snapshot_dir, hap_bin)
            if _app_id(app_info) != target_app:
                errors.append(
                    {
                        "code": "LIVE_APP_ID_MISMATCH",
                        "app_id": target_app,
                        "detail": "hap app info 返回的 app ID 与 contract 不一致",
                    }
                )
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            errors.append(
                {
                    "code": "LIVE_APP_LOOKUP_FAILED",
                    "app_id": target_app,
                    "detail": str(exc),
                }
            )
    info_by_worksheet = {}
    for worksheet_id in sorted(worksheet_ids):
        try:
            info_by_worksheet[worksheet_id] = _load_info(
                worksheet_id,
                snapshot_dir,
                hap_bin,
                target_app,
            )
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            errors.append(
                {
                    "code": "LIVE_WORKSHEET_LOOKUP_FAILED",
                    "worksheet_id": worksheet_id,
                    "detail": str(exc),
                }
            )

    for reference in references:
        if not isinstance(reference, dict):
            continue
        worksheet_id = reference.get("worksheet")
        field_id = reference.get("fieldId")
        info = info_by_worksheet.get(worksheet_id)
        if info is None:
            continue
        fields = {_field_id(field): field for field in _find_fields(info)}
        worksheet_app = (
            info.get("appId")
            or info.get("app_id")
            or info.get("data", {}).get("appId")
        )
        if target_app and worksheet_app and worksheet_app != target_app:
            errors.append(
                {
                    "code": "LIVE_WORKSHEET_APP_MISMATCH",
                    "worksheet_id": worksheet_id,
                    "detail": (
                        f"worksheet 属于 app={worksheet_app!r}，"
                        f"contract target.app_id={target_app!r}"
                    ),
                }
            )
        field = fields.get(field_id)
        if field is None:
            errors.append(
                {
                    "code": "LIVE_FIELD_ID_NOT_FOUND",
                    "worksheet_id": worksheet_id,
                    "field_id": field_id,
                    "detail": f"平台不存在字段 {reference.get('fieldName')}",
                }
            )
            continue
        actual_type = field.get("type") or field.get("typeId")
        expected_types = FIELD_TYPE_IDS.get(reference.get("type"))
        if expected_types and actual_type not in expected_types:
            errors.append(
                {
                    "code": "LIVE_FIELD_TYPE_MISMATCH",
                    "worksheet_id": worksheet_id,
                    "field_id": field_id,
                    "detail": (
                        f"字段类型不一致: contract={reference.get('type')!r}, "
                        f"platform={actual_type!r}"
                    ),
                }
            )
        expected_relation = reference.get("relation_worksheet_id")
        actual_relation = (
            field.get("relationWorksheetId")
            or field.get("dataSource")
            or field.get("sourceWorksheetId")
        )
        if expected_relation and actual_relation != expected_relation:
            errors.append(
                {
                    "code": "LIVE_RELATION_TARGET_MISMATCH",
                    "worksheet_id": worksheet_id,
                    "field_id": field_id,
                    "detail": (
                        f"关联目标不一致: contract={expected_relation!r}, "
                        f"platform={actual_relation!r}"
                    ),
                }
            )
        actual_options = {
            option.get("key"): option.get("value") or option.get("label")
            for option in field.get("options", [])
            if isinstance(option, dict) and option.get("key")
        }
        for option in reference.get("expected_options", []):
            if not isinstance(option, dict):
                continue
            key = option.get("key")
            label = option.get("label")
            if key not in actual_options:
                errors.append(
                    {
                        "code": "LIVE_OPTION_KEY_NOT_FOUND",
                        "worksheet_id": worksheet_id,
                        "field_id": field_id,
                        "option_key": key,
                        "detail": f"平台字段缺少选项 {label!r}",
                    }
                )
            elif actual_options[key] and actual_options[key] != label:
                errors.append(
                    {
                        "code": "LIVE_OPTION_LABEL_MISMATCH",
                        "worksheet_id": worksheet_id,
                        "field_id": field_id,
                        "option_key": key,
                        "detail": (
                            f"option label 不一致: 设计={label!r}, "
                            f"平台={actual_options[key]!r}"
                        ),
                    }
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只读调用 HAP worksheet info 校验 fieldId 与 option key"
    )
    parser.add_argument("contract", help="execution_contract.json")
    parser.add_argument(
        "--snapshot-dir",
        help="测试用 worksheet info JSON 目录；提供后不调用 hap CLI",
    )
    parser.add_argument("--hap-bin", default="hap", help="hap CLI 可执行文件")
    args = parser.parse_args()

    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"verdict": "fail", "errors": [
                    {"code": "CONTRACT_READ_FAILED", "detail": str(exc)}
                ]},
                ensure_ascii=False,
            )
        )
        return 2

    errors = validate_live(contract, args.snapshot_dir, args.hap_bin)
    print(
        json.dumps(
            {
                "verdict": "fail" if errors else "pass",
                "source": "snapshot" if args.snapshot_dir else "hap worksheet info",
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
