#!/usr/bin/env python3
"""Validate the business design IR embedded in execution_lock.json."""

import argparse
import json
import sys
from pathlib import Path


REQUIRED_SECTIONS = {
    "requirements",
    "actors",
    "scenarios",
    "entities",
    "state_machines",
    "business_rules",
    "permissions",
    "views",
    "buttons",
    "notifications",
    "assumptions",
    "traceability",
}
FIELD_DIMENSIONS = {
    "identity",
    "business",
    "status",
    "time",
    "ownership",
    "relations",
    "audit",
}
TRACE_KINDS = {
    "entity",
    "field",
    "state_machine",
    "workflow",
    "permission",
    "view",
    "button",
    "notification",
    "business_rule",
}


def _issue(
    issues: list[dict],
    path: str,
    detail: str,
    severity: str = "high",
) -> None:
    issues.append({"severity": severity, "path": path, "detail": detail})


def _ids(
    items: object,
    path: str,
    issues: list[dict],
) -> set[str]:
    if not isinstance(items, list):
        _issue(issues, path, f"{path} 必须是数组")
        return set()
    result = set()
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            _issue(issues, item_path, "条目必须是对象")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            _issue(issues, f"{item_path}.id", "缺少稳定 id")
            continue
        if item_id in result:
            _issue(issues, f"{item_path}.id", f"id 重复: {item_id}")
        result.add(item_id)
    return result


def validate_design_ir(lock: dict) -> list[dict]:
    issues: list[dict] = []
    design_ir = lock.get("design_ir")
    if not isinstance(design_ir, dict):
        return [
            {
                "severity": "high",
                "path": "$.design_ir",
                "detail": "缺少 design_ir 业务设计语言",
            }
        ]
    for section in sorted(REQUIRED_SECTIONS - set(design_ir)):
        _issue(issues, f"$.design_ir.{section}", f"缺少 section: {section}")

    requirement_ids = _ids(
        design_ir.get("requirements"),
        "$.design_ir.requirements",
        issues,
    )
    actor_ids = _ids(
        design_ir.get("actors"),
        "$.design_ir.actors",
        issues,
    )
    scenario_ids = _ids(
        design_ir.get("scenarios"),
        "$.design_ir.scenarios",
        issues,
    )
    entity_ids = _ids(
        design_ir.get("entities"),
        "$.design_ir.entities",
        issues,
    )
    _ids(
        design_ir.get("business_rules"),
        "$.design_ir.business_rules",
        issues,
    )

    if not requirement_ids:
        _issue(issues, "$.design_ir.requirements", "至少需要一个客户需求")
    if not actor_ids:
        _issue(issues, "$.design_ir.actors", "至少需要一个业务角色")
    if not scenario_ids:
        _issue(issues, "$.design_ir.scenarios", "至少需要一个业务场景")
    if not entity_ids:
        _issue(issues, "$.design_ir.entities", "至少需要一个业务实体")

    for index, requirement in enumerate(design_ir.get("requirements", [])):
        if not isinstance(requirement, dict):
            continue
        path = f"$.design_ir.requirements[{index}]"
        for key in ("statement", "priority", "acceptance_criteria"):
            if not requirement.get(key):
                _issue(issues, f"{path}.{key}", f"需求缺少 {key}")

    for index, actor in enumerate(design_ir.get("actors", [])):
        if not isinstance(actor, dict):
            continue
        path = f"$.design_ir.actors[{index}]"
        if not actor.get("name"):
            _issue(issues, f"{path}.name", "角色缺少 name")
        if not actor.get("responsibilities"):
            _issue(issues, f"{path}.responsibilities", "角色缺少职责")

    for index, scenario in enumerate(design_ir.get("scenarios", [])):
        if not isinstance(scenario, dict):
            continue
        path = f"$.design_ir.scenarios[{index}]"
        for actor_id in scenario.get("actor_ids", []):
            if actor_id not in actor_ids:
                _issue(
                    issues,
                    f"{path}.actor_ids",
                    f"场景引用未知 actor: {actor_id}",
                )
        for key in ("trigger", "outcome"):
            if not scenario.get(key):
                _issue(issues, f"{path}.{key}", f"场景缺少 {key}")

    for index, entity in enumerate(design_ir.get("entities", [])):
        if not isinstance(entity, dict):
            continue
        path = f"$.design_ir.entities[{index}]"
        if not entity.get("table_name"):
            _issue(issues, f"{path}.table_name", "实体缺少落地工作表")
        dimensions = entity.get("field_dimensions")
        if not isinstance(dimensions, dict):
            _issue(issues, f"{path}.field_dimensions", "缺少七维字段映射")
            continue
        for dimension in sorted(FIELD_DIMENSIONS - set(dimensions)):
            _issue(
                issues,
                f"{path}.field_dimensions.{dimension}",
                f"缺少字段维度: {dimension}",
            )
        if not dimensions.get("business"):
            _issue(issues, f"{path}.field_dimensions.business", "核心业务属性不能为空")
        if not dimensions.get("status"):
            _issue(issues, f"{path}.field_dimensions.status", "状态维度不能为空")

    sheet_fields = {
        sheet.get("name"): {
            value
            for field in sheet.get("fields", [])
            if isinstance(field, dict)
            for value in (field.get("field_id"), field.get("name"))
            if value
        }
        for sheet in lock.get("sheets", [])
        if isinstance(sheet, dict) and sheet.get("name")
    }
    all_field_refs = (
        set().union(*sheet_fields.values()) if sheet_fields else set()
    )
    workflow_names = {
        workflow.get("name")
        for workflow in lock.get("workflows", [])
        if isinstance(workflow, dict)
    }
    state_machine_entities = set()
    for index, machine in enumerate(design_ir.get("state_machines", [])):
        path = f"$.design_ir.state_machines[{index}]"
        if not isinstance(machine, dict):
            _issue(issues, path, "状态机必须是对象")
            continue
        if machine.get("entity_id") not in entity_ids:
            _issue(issues, f"{path}.entity_id", "状态机引用未知实体")
        elif machine.get("entity_id"):
            state_machine_entities.add(machine["entity_id"])
        if machine.get("state_field_id") not in all_field_refs:
            _issue(
                issues,
                f"{path}.state_field_id",
                "状态机引用不存在的状态字段",
            )
        states = machine.get("states")
        transitions = machine.get("transitions")
        if not isinstance(states, list) or not states:
            _issue(issues, f"{path}.states", "状态机必须有 states")
            continue
        if not isinstance(transitions, list) or not transitions:
            _issue(issues, f"{path}.transitions", "状态机必须有 transitions")
            continue
        state_keys = {
            state.get("key")
            for state in states
            if isinstance(state, dict) and state.get("key")
        }
        terminal = {
            state.get("key")
            for state in states
            if isinstance(state, dict) and state.get("terminal")
        }
        outgoing = set()
        for transition_index, transition in enumerate(transitions):
            transition_path = f"{path}.transitions[{transition_index}]"
            if not isinstance(transition, dict):
                _issue(issues, transition_path, "transition 必须是对象")
                continue
            source = transition.get("from")
            target = transition.get("to")
            if source not in state_keys or target not in state_keys:
                _issue(issues, transition_path, "transition 引用未知状态")
            outgoing.add(source)
            if transition.get("actor_id") not in actor_ids:
                _issue(issues, f"{transition_path}.actor_id", "transition 引用未知角色")
            workflow = transition.get("workflow")
            if workflow and workflow not in workflow_names:
                _issue(
                    issues,
                    f"{transition_path}.workflow",
                    f"transition 引用未知工作流: {workflow}",
                )
            if not transition.get("trigger"):
                _issue(issues, f"{transition_path}.trigger", "transition 缺少触发条件")
        for state in state_keys - terminal - outgoing:
            _issue(
                issues,
                f"{path}.states",
                f"非终态 {state!r} 没有任何出向转换",
            )
    for entity in design_ir.get("entities", []):
        if not isinstance(entity, dict):
            continue
        dimensions = entity.get("field_dimensions", {})
        if dimensions.get("status") and entity.get("id") not in state_machine_entities:
            _issue(
                issues,
                "$.design_ir.state_machines",
                f"有状态实体 {entity.get('id')} 缺少独立状态机",
            )

    permission_actors = {
        item.get("actor_id")
        for item in design_ir.get("permissions", [])
        if isinstance(item, dict)
    }
    view_actors = {
        item.get("actor_id")
        for item in design_ir.get("views", [])
        if isinstance(item, dict)
    }
    interactive_actors = {
        actor.get("id")
        for actor in design_ir.get("actors", [])
        if isinstance(actor, dict) and actor.get("interactive", True)
    }
    for actor_id in interactive_actors - permission_actors:
        _issue(issues, "$.design_ir.permissions", f"角色 {actor_id} 无权限落点")
    for actor_id in interactive_actors - view_actors:
        _issue(issues, "$.design_ir.views", f"角色 {actor_id} 无视图落点")

    for index, permission in enumerate(design_ir.get("permissions", [])):
        if not isinstance(permission, dict):
            continue
        path = f"$.design_ir.permissions[{index}]"
        if permission.get("actor_id") not in actor_ids:
            _issue(issues, f"{path}.actor_id", "权限引用未知角色")
        if permission.get("table") not in sheet_fields:
            _issue(issues, f"{path}.table", "权限引用不存在的工作表")
    for index, view in enumerate(design_ir.get("views", [])):
        if not isinstance(view, dict):
            continue
        path = f"$.design_ir.views[{index}]"
        table = view.get("table")
        if view.get("actor_id") not in actor_ids:
            _issue(issues, f"{path}.actor_id", "视图引用未知角色")
        if table not in sheet_fields:
            _issue(issues, f"{path}.table", "视图引用不存在的工作表")
        else:
            for field in view.get("fields", []):
                if field not in sheet_fields[table]:
                    _issue(
                        issues,
                        f"{path}.fields",
                        f"视图引用不存在的字段: {field}",
                    )
    for index, button in enumerate(design_ir.get("buttons", [])):
        if not isinstance(button, dict):
            continue
        path = f"$.design_ir.buttons[{index}]"
        if button.get("table") not in sheet_fields:
            _issue(issues, f"{path}.table", "按钮引用不存在的工作表")
        if button.get("workflow") not in workflow_names:
            _issue(issues, f"{path}.workflow", "按钮引用不存在的工作流")
        for actor_id in button.get("actor_ids", []):
            if actor_id not in actor_ids:
                _issue(issues, f"{path}.actor_ids", "按钮引用未知角色")

    field_refs = all_field_refs
    artifact_refs = {
        "entity": entity_ids,
        "field": field_refs,
        "state_machine": {
            item.get("id")
            for item in design_ir.get("state_machines", [])
            if isinstance(item, dict) and item.get("id")
        },
        "workflow": workflow_names,
        "permission": {
            item.get("id") or f"{item.get('actor_id')}:{item.get('table')}"
            for item in design_ir.get("permissions", [])
            if isinstance(item, dict)
        },
        "view": {
            item.get("id")
            for item in design_ir.get("views", [])
            if isinstance(item, dict) and item.get("id")
        },
        "button": {
            item.get("id")
            for item in design_ir.get("buttons", [])
            if isinstance(item, dict) and item.get("id")
        },
        "notification": {
            item.get("id")
            for item in design_ir.get("notifications", [])
            if isinstance(item, dict) and item.get("id")
        },
        "business_rule": {
            item.get("id")
            for item in design_ir.get("business_rules", [])
            if isinstance(item, dict) and item.get("id")
        },
    }
    traced = set()
    trace_kinds: dict[str, set[str]] = {}
    for index, trace in enumerate(design_ir.get("traceability", [])):
        path = f"$.design_ir.traceability[{index}]"
        if not isinstance(trace, dict):
            _issue(issues, path, "traceability 条目必须是对象")
            continue
        requirement_id = trace.get("requirement_id")
        if requirement_id not in requirement_ids:
            _issue(issues, f"{path}.requirement_id", "追踪引用未知需求")
        traced.add(requirement_id)
        trace_kinds.setdefault(requirement_id, set())
        artifacts = trace.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            _issue(issues, f"{path}.artifacts", "需求没有任何系统落点")
            continue
        for artifact_index, artifact in enumerate(artifacts):
            artifact_path = f"{path}.artifacts[{artifact_index}]"
            if not isinstance(artifact, dict):
                _issue(issues, artifact_path, "artifact 必须是对象")
                continue
            if artifact.get("kind") not in TRACE_KINDS:
                _issue(issues, f"{artifact_path}.kind", "artifact kind 无效")
            kind = artifact.get("kind")
            ref = artifact.get("ref")
            if not ref:
                _issue(issues, f"{artifact_path}.ref", "artifact 缺少 ref")
            elif kind in artifact_refs and ref not in artifact_refs[kind]:
                _issue(
                    issues,
                    f"{artifact_path}.ref",
                    f"artifact 引用不存在: {kind}:{ref}",
                )
            if kind:
                trace_kinds[requirement_id].add(kind)
    for requirement_id in requirement_ids - traced:
        _issue(
            issues,
            "$.design_ir.traceability",
            f"需求 {requirement_id} 未追踪到系统设计",
        )
    data_kinds = {"entity", "field"}
    behavior_kinds = {
        "state_machine",
        "workflow",
        "view",
        "button",
        "notification",
        "business_rule",
    }
    for requirement_id in requirement_ids:
        kinds = trace_kinds.get(requirement_id, set())
        if not kinds.intersection(data_kinds):
            _issue(
                issues,
                "$.design_ir.traceability",
                f"需求 {requirement_id} 缺少数据落点(entity/field)",
            )
        if not kinds.intersection(behavior_kinds):
            _issue(
                issues,
                "$.design_ir.traceability",
                f"需求 {requirement_id} 缺少行为落点",
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 execution_lock.design_ir")
    parser.add_argument("lock_file")
    args = parser.parse_args()
    try:
        lock = json.loads(Path(args.lock_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}, ensure_ascii=False))
        return 2
    issues = validate_design_ir(lock)
    print(
        json.dumps(
            {"verdict": "fail" if issues else "pass", "issues": issues},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
