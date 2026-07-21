#!/usr/bin/env python3
"""Deterministically convert an execution contract to HAP batch-add nodes."""

import argparse
import copy
import json
import sys
from pathlib import Path


class AdapterError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("execution contract 无法转换为 batch DSL")
        self.errors = errors


def _error(errors: list[dict], path: str, code: str, detail: str) -> None:
    errors.append({"path": path, "code": code, "detail": detail})


def _normalize_values(value: object) -> object:
    if isinstance(value, list):
        return [_normalize_values(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    if (
        isinstance(value.get("key"), str)
        and value.get("key")
        and isinstance(value.get("label"), str)
    ):
        return value["key"]
    return {key: _normalize_values(child) for key, child in value.items()}


def build_batch_nodes(
    contract: dict,
    trigger_node_id: str | None = None,
) -> list[dict]:
    nodes = contract.get("nodes")
    errors: list[dict] = []
    if not isinstance(nodes, list) or not nodes:
        raise AdapterError(
            [{"path": "$.nodes", "code": "CONTRACT_NODES_MISSING",
              "detail": "nodes 必须是非空数组"}]
        )

    def replace_trigger(value: object, current_path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{current_path}.{key}"
                if key == "node" and child == "trigger":
                    if trigger_node_id:
                        value[key] = trigger_node_id
                    else:
                        _error(
                            errors,
                            child_path,
                            "RUNTIME_TRIGGER_ID_REQUIRED",
                            (
                                "配置引用 trigger；生成可执行 batch DSL "
                                "必须提供 --trigger-node-id"
                            ),
                        )
                else:
                    replace_trigger(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                replace_trigger(child, f"{current_path}[{index}]")

    def build_scope(
        scope_nodes: list[dict],
        scope_path: str,
        reserved_aliases: set[str] | None = None,
    ) -> list[dict]:
        reserved_aliases = reserved_aliases or set()
        node_map: dict[str, dict] = {}
        for index, node in enumerate(scope_nodes):
            path = f"{scope_path}[{index}]"
            if not isinstance(node, dict):
                _error(errors, path, "CONTRACT_NODE_INVALID", "节点必须是对象")
                continue
            alias = node.get("alias") or node.get("nodeAlias")
            if not isinstance(alias, str) or not alias:
                _error(errors, f"{path}.alias", "CONTRACT_ALIAS_MISSING", "节点缺少 alias")
                continue
            if alias in reserved_aliases:
                continue
            node_type = node.get("nodeType") or node.get("node_type")
            if node_type in {"delay", "code"}:
                _error(
                    errors,
                    f"{path}.nodeType",
                    "BATCH_UNSUPPORTED_NODE_TYPE",
                    (
                        f"{node_type} 不支持 batch-add；必须在创建骨架前"
                        "拆分为受控的后置 node-add 计划"
                    ),
                )
            if alias in node_map:
                _error(
                    errors,
                    f"{path}.alias",
                    "CONTRACT_ALIAS_DUPLICATE",
                    f"节点 alias 重复: {alias}",
                )
            node_map[alias] = node

        nested_aliases: set[str] = set()
        parent_counts: dict[str, int] = {}
        adjacency: dict[str, list[str]] = {alias: [] for alias in node_map}
        for alias, node in node_map.items():
            config = node.get("config", {}) or {}
            for path_index, branch_path in enumerate(config.get("paths", [])):
                for child_index, child in enumerate(branch_path.get("nodes", [])):
                    child_path = (
                        f"{scope_path}.{alias}.config.paths[{path_index}]"
                        f".nodes[{child_index}]"
                    )
                    if isinstance(child, str):
                        if child not in node_map:
                            _error(
                                errors,
                                child_path,
                                "BRANCH_ALIAS_UNKNOWN",
                                f"分支引用未知 alias: {child}",
                            )
                        else:
                            adjacency[alias].append(child)
                            parent_counts[child] = parent_counts.get(child, 0) + 1
                        nested_aliases.add(child)
        for alias, count in parent_counts.items():
            if count > 1:
                _error(
                    errors,
                    scope_path,
                    "BRANCH_ALIAS_MULTIPLE_PARENTS",
                    f"节点 {alias} 被 {count} 个分支路径引用，会被重复创建",
                )

        visit_state: dict[str, int] = {}

        def visit(alias: str, trail: list[str]) -> None:
            state = visit_state.get(alias, 0)
            if state == 1:
                _error(
                    errors,
                    scope_path,
                    "BRANCH_ALIAS_CYCLE",
                    "分支引用形成环路: " + " -> ".join(trail + [alias]),
                )
                return
            if state == 2:
                return
            visit_state[alias] = 1
            for child in adjacency.get(alias, []):
                visit(child, trail + [alias])
            visit_state[alias] = 2

        for alias in node_map:
            visit(alias, [])
        roots = [alias for alias in node_map if alias not in nested_aliases]
        if node_map and not roots:
            _error(
                errors,
                scope_path,
                "BRANCH_ROOT_MISSING",
                "没有可执行根节点；分支引用可能形成闭环",
            )

        visiting: set[str] = set()

        def convert_node(node: dict, path: str) -> dict:
            alias = node.get("alias") or node.get("nodeAlias")
            if alias in visiting:
                _error(
                    errors,
                    path,
                    "BRANCH_ALIAS_CYCLE",
                    f"分支节点引用形成环路: {alias}",
                )
                return {}
            visiting.add(alias)
            converted = {
                "nodeAlias": alias,
                "nodeType": node.get("nodeType") or node.get("node_type"),
                "name": node.get("name") or alias,
                "config": _normalize_values(node.get("config", {})),
            }
            config = converted["config"]
            replace_trigger(config, f"{path}.config")
            for path_index, branch_path in enumerate(config.get("paths", [])):
                inlined = []
                for child_index, child in enumerate(branch_path.get("nodes", [])):
                    child_path = (
                        f"{path}.config.paths[{path_index}].nodes[{child_index}]"
                    )
                    if isinstance(child, str):
                        child_node = node_map.get(child)
                        if child_node:
                            inlined.append(convert_node(child_node, child_path))
                    elif isinstance(child, dict):
                        inlined.append(convert_node(child, child_path))
                    else:
                        _error(
                            errors,
                            child_path,
                            "BRANCH_NODE_INVALID",
                            "分支 path.nodes 只能是 alias 或节点对象",
                        )
                branch_path["nodes"] = inlined
            process = config.get("process")
            if isinstance(process, dict) and isinstance(process.get("nodes"), list):
                process["nodes"] = build_scope(
                    process["nodes"],
                    f"{path}.config.process.nodes",
                    reserved_aliases={"approval_start", "sub_trigger"},
                )
            visiting.discard(alias)
            return converted

        return [
            convert_node(node_map[alias], f"{scope_path}.{alias}")
            for alias in roots
        ]

    root_nodes = build_scope(nodes, "$.nodes")
    if errors:
        raise AdapterError(errors)
    return root_nodes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="execution_contract → HAP batch-add --nodes JSON"
    )
    parser.add_argument("contract", help="execution_contract.json")
    parser.add_argument(
        "--trigger-node-id",
        help="工作流骨架创建后返回的物理触发节点 ID",
    )
    parser.add_argument("--output", help="输出 JSON 文件；默认 stdout")
    args = parser.parse_args()

    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        nodes = build_batch_nodes(contract, args.trigger_node_id)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"verdict": "fail", "code": "CONTRACT_READ_FAILED",
                 "detail": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    except AdapterError as exc:
        print(
            json.dumps(
                {"verdict": "fail", "errors": exc.errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    output = json.dumps(nodes, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
