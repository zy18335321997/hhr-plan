import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import contract_to_batch_dsl  # noqa: E402
import execution_state  # noqa: E402
import hap_dsl_extensions  # noqa: E402
import live_preflight  # noqa: E402
import preflight  # noqa: E402
import run_batch_add  # noqa: E402
import save_actions  # noqa: E402
import structure_to_mappings  # noqa: E402


def load_contract():
    return json.loads(
        (FIXTURES / "complex-contract.json").read_text(encoding="utf-8")
    )


class BatchDslTests(unittest.TestCase):
    def test_branch_aliases_are_inlined_and_trigger_is_physical(self):
        nodes = contract_to_batch_dsl.build_batch_nodes(
            load_contract(),
            trigger_node_id="physical-trigger-id",
        )
        self.assertEqual(
            ["mark_submitted", "check_amount"],
            [node["nodeAlias"] for node in nodes],
        )
        self.assertEqual(
            "physical-trigger-id",
            nodes[0]["config"]["target"]["node"],
        )
        nested = nodes[1]["config"]["paths"][0]["nodes"]
        self.assertEqual(
            ["approval", "archive_subprocess"],
            [node["nodeAlias"] for node in nested],
        )
        self.assertTrue(all(isinstance(node, dict) for node in nested))
        approval_nodes = nested[0]["config"]["process"]["nodes"]
        self.assertEqual(
            ["approve_step"],
            [node["nodeAlias"] for node in approval_nodes],
        )

    def test_symbolic_trigger_requires_runtime_id(self):
        with self.assertRaises(contract_to_batch_dsl.AdapterError) as raised:
            contract_to_batch_dsl.build_batch_nodes(load_contract())
        self.assertTrue(
            any(
                error["code"] == "RUNTIME_TRIGGER_ID_REQUIRED"
                for error in raised.exception.errors
            )
        )

    def test_branch_reference_cycle_and_multiple_parents_fail(self):
        cyclic = load_contract()
        cyclic["nodes"] = [
            {
                "alias": "a",
                "nodeType": "branch",
                "name": "A",
                "config": {"paths": [{"name": "p", "nodes": ["b"]}]},
            },
            {
                "alias": "b",
                "nodeType": "branch",
                "name": "B",
                "config": {"paths": [{"name": "p", "nodes": ["a"]}]},
            },
        ]
        with self.assertRaises(contract_to_batch_dsl.AdapterError) as raised:
            contract_to_batch_dsl.build_batch_nodes(cyclic)
        codes = {error["code"] for error in raised.exception.errors}
        self.assertIn("BRANCH_ALIAS_CYCLE", codes)
        self.assertIn("BRANCH_ROOT_MISSING", codes)

        multiple = load_contract()
        multiple["nodes"].append(
            {
                "alias": "second_branch",
                "nodeType": "branch",
                "name": "第二分支",
                "config": {
                    "paths": [{"name": "p", "nodes": ["approval"]}]
                },
            }
        )
        with self.assertRaises(contract_to_batch_dsl.AdapterError) as raised:
            contract_to_batch_dsl.build_batch_nodes(
                multiple,
                trigger_node_id="trigger-id",
            )
        self.assertTrue(
            any(
                error["code"] == "BRANCH_ALIAS_MULTIPLE_PARENTS"
                for error in raised.exception.errors
            )
        )

    def test_inner_process_branch_uses_its_own_scope(self):
        contract = load_contract()
        process = contract["nodes"][2]["config"]["process"]
        process["nodes"] = [
            {
                "nodeAlias": "inner_branch",
                "nodeType": "branch",
                "name": "内部判断",
                "config": {
                    "paths": [{"name": "通过", "nodes": ["inner_update"]}]
                },
            },
            {
                "nodeAlias": "inner_update",
                "nodeType": "update_record",
                "name": "内部更新",
                "config": {
                    "worksheet": "ws-purchase",
                    "target": {"node": "approval_start"},
                    "fields": [
                        {
                            "fieldId": "field-status",
                            "value": "22222222-2222-2222-2222-222222222222",
                        }
                    ],
                },
            },
        ]
        nodes = contract_to_batch_dsl.build_batch_nodes(
            contract,
            trigger_node_id="trigger-id",
        )
        approval = nodes[1]["config"]["paths"][0]["nodes"][0]
        inner_nodes = approval["config"]["process"]["nodes"]
        self.assertEqual(["inner_branch"], [node["nodeAlias"] for node in inner_nodes])
        self.assertEqual(
            "inner_update",
            inner_nodes[0]["config"]["paths"][0]["nodes"][0]["nodeAlias"],
        )

    def test_batch_unsupported_delay_is_blocked_before_write(self):
        contract = load_contract()
        contract["nodes"].append(
            {
                "alias": "wait",
                "nodeType": "delay",
                "name": "等待",
                "config": {"duration": 1},
            }
        )
        with self.assertRaises(contract_to_batch_dsl.AdapterError) as raised:
            contract_to_batch_dsl.build_batch_nodes(
                contract,
                trigger_node_id="trigger-id",
            )
        self.assertTrue(
            any(
                error["code"] == "BATCH_UNSUPPORTED_NODE_TYPE"
                for error in raised.exception.errors
            )
        )

    def test_laird_extension_nodes_are_lowered_without_loss(self):
        contract = load_contract()
        contract["nodes"] = [
            {
                "alias": "normalize_old",
                "nodeType": "code",
                "name": "旧数量",
                "config": {
                    "language": "javascript",
                    "inputs": [
                        {
                            "name": "old",
                            "value": {
                                "kind": "field",
                                "node": "trigger",
                                "fieldId": "old-value",
                            },
                        }
                    ],
                    "code": "output = { result: input.old || 0 };",
                },
            },
            {
                "alias": "absolute",
                "nodeType": "compute",
                "name": "绝对值",
                "config": {
                    "mode": "function",
                    "formula": "ABS($normalize_old-result$)",
                    "output_type": "number",
                },
            },
            {
                "alias": "result",
                "nodeType": "pbp_output",
                "name": "输出参数",
                "config": {
                    "outputs": [
                        {
                            "fieldId": "result-id",
                            "fieldName": "normalized_value",
                            "type": 6,
                            "valueRef": {
                                "kind": "field",
                                "node": "absolute",
                                "fieldId": "number_fx_id",
                            },
                        }
                    ]
                },
            },
        ]
        nodes = contract_to_batch_dsl.build_batch_nodes(
            contract,
            trigger_node_id="physical-trigger",
        )
        self.assertEqual(
            ["code", "compute", "pbp_output"],
            [node["nodeType"] for node in nodes],
        )
        self.assertEqual(
            "physical-trigger",
            nodes[0]["config"]["inputs"][0]["value"]["node"],
        )

    def test_fill_form_field_id_is_lowered_to_complete_wire_item(self):
        contract = load_contract()
        contract["nodes"] = [
            {
                "alias": "fill_self",
                "nodeType": "fill_in",
                "name": "本人填写",
                "config": {
                    "assignee": {"kind": "user", "userId": "user-1"},
                    "formProperties": [
                        {
                            "fieldId": "field-description",
                            "type": 2,
                            "name": "描述",
                            "permission": "editable",
                        }
                    ],
                },
            }
        ]
        nodes = contract_to_batch_dsl.build_batch_nodes(
            contract,
            trigger_node_id="trigger-id",
        )
        form_property = nodes[0]["config"]["formProperties"][0]
        self.assertEqual("field-description", form_property["id"])
        self.assertEqual(2, form_property["type"])
        self.assertEqual("描述", form_property["name"])
        self.assertEqual("editable", form_property["permission"])
        self.assertEqual(0, form_property["showCard"])
        self.assertNotIn("fieldId", form_property)

    def test_incomplete_fill_form_property_is_blocked_before_write(self):
        contract = load_contract()
        contract["nodes"] = [
            {
                "alias": "fill_self",
                "nodeType": "fill_in",
                "name": "本人填写",
                "config": {
                    "formProperties": [{"fieldId": "field-description"}],
                },
            }
        ]
        with self.assertRaises(contract_to_batch_dsl.AdapterError) as raised:
            contract_to_batch_dsl.build_batch_nodes(
                contract,
                trigger_node_id="trigger-id",
            )
        missing_paths = {
            error["path"]
            for error in raised.exception.errors
            if error["code"] == "FILL_FORM_PROPERTY_INCOMPLETE"
        }
        self.assertTrue(any(path.endswith(".type") for path in missing_paths))
        self.assertTrue(any(path.endswith(".name") for path in missing_paths))
        self.assertTrue(any(path.endswith(".permission") for path in missing_paths))



class LivePreflightTests(unittest.TestCase):
    def test_snapshot_field_and_options_pass(self):
        errors = live_preflight.validate_live(
            load_contract(),
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertEqual([], errors)

    def test_missing_option_key_fails(self):
        contract = copy.deepcopy(load_contract())
        contract["field_references"][0]["expected_options"][0]["key"] = (
            "99999999-9999-9999-9999-999999999999"
        )
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(error["code"] == "LIVE_OPTION_KEY_NOT_FOUND" for error in errors)
        )

    def test_node_field_must_be_registered_for_live_preflight(self):
        contract = copy.deepcopy(load_contract())
        contract["nodes"][0]["config"]["fields"].append(
            {"fieldId": "field-unregistered", "value": "x"}
        )
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(
                error["code"] == "CONTRACT_FIELD_REFERENCE_MISSING"
                for error in errors
            )
        )

    def test_pbp_controls_and_process_outputs_are_not_worksheet_fields(self):
        contract = copy.deepcopy(load_contract())
        contract["trigger"] = {
            "type": "pbp",
            "config": {
                "inputs": [
                    {"controlId": "pbp-input", "name": "old_value"}
                ]
            },
        }
        contract["field_references"] = []
        contract["nodes"] = [
            {
                "alias": "normalize",
                "nodeType": "code",
                "config": {
                    "inputs": [
                        {
                            "name": "old",
                            "value": {
                                "kind": "field",
                                "node": "trigger",
                                "fieldId": "pbp-input",
                            },
                        }
                    ],
                    "outputs": [{"fieldId": "result"}],
                },
            },
            {
                "alias": "return_value",
                "nodeType": "pbp_output",
                "config": {
                    "outputs": [
                        {
                            "fieldId": "pbp-output",
                            "valueRef": {
                                "kind": "field",
                                "node": "normalize",
                                "fieldId": "result",
                            },
                        }
                    ]
                },
            },
        ]
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertFalse(
            any(
                error["code"] == "CONTRACT_FIELD_REFERENCE_MISSING"
                for error in errors
            )
        )
        self.assertFalse(
            any(
                error["code"] == "CONTRACT_PBP_CONTROL_NOT_FOUND"
                for error in errors
            )
        )

    def test_unknown_pbp_trigger_control_fails(self):
        contract = copy.deepcopy(load_contract())
        contract["trigger"] = {
            "type": "pbp",
            "config": {"inputs": []},
        }
        contract["nodes"] = [
            {
                "alias": "normalize",
                "nodeType": "code",
                "config": {
                    "inputs": [
                        {
                            "name": "old",
                            "value": {
                                "kind": "field",
                                "node": "trigger",
                                "fieldId": "missing-pbp-input",
                            },
                        }
                    ]
                },
            }
        ]
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(
                error["code"] == "CONTRACT_PBP_CONTROL_NOT_FOUND"
                for error in errors
            )
        )

    def test_live_preflight_checks_type_and_app_but_ignores_system_field(self):
        contract = copy.deepcopy(load_contract())
        contract["field_references"][0]["type"] = "Date"
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(error["code"] == "LIVE_FIELD_TYPE_MISMATCH" for error in errors)
        )

        contract = copy.deepcopy(load_contract())
        contract["target"]["app_id"] = "missing-app"
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(error["code"] == "LIVE_APP_LOOKUP_FAILED" for error in errors)
        )

        contract = copy.deepcopy(load_contract())
        contract["nodes"][1]["config"]["paths"][0]["condition"]["right"] = {
            "kind": "systemField",
            "fieldId": "nowTime",
        }
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertFalse(
            any(
                error.get("field_id") == "nowTime"
                and error["code"] == "CONTRACT_FIELD_REFERENCE_MISSING"
                for error in errors
            )
        )

    def test_live_preflight_binds_field_usage_to_node_worksheet(self):
        contract = copy.deepcopy(load_contract())
        contract["nodes"][0]["config"]["worksheet"] = "ws-other"
        errors = live_preflight.validate_live(
            contract,
            snapshot_dir=str(FIXTURES / "worksheet-info"),
        )
        self.assertTrue(
            any(
                error["code"] == "CONTRACT_FIELD_WORKSHEET_MISMATCH"
                for error in errors
            )
        )

    def test_get_relation_output_fields_use_relation_target_scope(self):
        references = {
            "relation-field": {
                "fieldId": "relation-field",
                "worksheet": "ws-source",
                "type": "Relation",
                "relation_worksheet_id": "ws-target",
            },
            "target-status": {
                "fieldId": "target-status",
                "worksheet": "ws-target",
                "type": "SingleSelect",
            },
        }
        nodes = [
            {
                "alias": "get_target",
                "nodeType": "get_relation",
                "config": {
                    "worksheet": "ws-source",
                    "fields": [{"fieldId": "relation-field"}],
                },
            },
            {
                "alias": "check",
                "nodeType": "branch",
                "config": {
                    "paths": [
                        {
                            "condition": {
                                "left": {
                                    "fieldId": "target-status",
                                    "node": "get_target",
                                },
                                "right": {"kind": "literal", "value": "x"},
                            },
                            "nodes": [],
                        }
                    ]
                },
            },
        ]
        usages = live_preflight._collect_field_usages(nodes, references)
        self.assertIn(("ws-target", "target-status"), usages)

    def test_get_relation_records_field_uses_source_scope(self):
        references = {
            "relation-field": {
                "fieldId": "relation-field",
                "worksheet": "ws-source",
                "type": "Relation",
                "relation_worksheet_id": "ws-target",
            }
        }
        nodes = [
            {
                "alias": "fetch_targets",
                "nodeType": "get_relation_records",
                "config": {
                    "worksheet": "ws-target",
                    "target": {"node": "trigger"},
                    "fields": [{"fieldId": "relation-field"}],
                },
            }
        ]

        usages = live_preflight._collect_field_usages(
            nodes,
            references,
            trigger_worksheet="ws-source",
        )

        self.assertIn(("ws-source", "relation-field"), usages)
        self.assertNotIn(("ws-target", "relation-field"), usages)

    def test_relation_reference_requires_and_checks_target(self):
        contract = copy.deepcopy(load_contract())
        reference = contract["field_references"][0]
        reference["type"] = "Relation"
        reference.pop("expected_options")
        passed, static_errors = preflight.validate_static(contract)
        self.assertFalse(passed)
        self.assertTrue(
            any("relation_worksheet_id" in error for error in static_errors)
        )

    def test_relation_write_requires_row_id_guid(self):
        contract = copy.deepcopy(load_contract())
        contract["field_references"].append(
            {
                "fieldId": "relation-field",
                "worksheet": "ws-purchase",
                "fieldName": "来源",
                "type": "Relation",
                "relation_worksheet_id": "ws-source",
            }
        )
        contract["nodes"][0]["config"]["fields"].append(
            {
                "fieldId": "relation-field",
                "value": ["6a604fdfad0dd7e1ab8df52e"],
            }
        )
        passed, errors = preflight.validate_static(contract)
        self.assertFalse(passed)
        self.assertTrue(
            any("rowId GUID" in error for error in errors)
        )

    def test_static_preflight_accepts_trigger_as_branch_source(self):
        contract = copy.deepcopy(load_contract())
        contract["nodes"][1]["config"]["paths"][0]["condition"]["left"][
            "node"
        ] = "trigger"
        passed, errors = preflight.validate_static(contract)
        self.assertTrue(passed, errors)

    def test_live_cli_uses_global_json_flag(self):
        info_result = mock.Mock(
            returncode=0,
            stdout=json.dumps({"appId": "app-001"}),
            stderr="",
        )
        fields_result = mock.Mock(
            returncode=0,
            stdout=json.dumps([]),
            stderr="",
        )
        with mock.patch.object(
            live_preflight.subprocess,
            "run",
            side_effect=[info_result, fields_result],
        ) as run:
            live_preflight._load_info(
                "ws-001",
                None,
                "hap",
                "app-001",
            )
        self.assertEqual(
            ["hap", "--json", "worksheet", "info", "ws-001",
             "--app-id", "app-001"],
            run.call_args_list[0].args[0],
        )
        self.assertEqual(
            ["hap", "--json", "worksheet", "fields", "ws-001"],
            run.call_args_list[1].args[0],
        )


class SaveActionTests(unittest.TestCase):
    def test_contract_alias_and_runtime_mapping_create_task(self):
        tasks = save_actions.collect_tasks(
            load_contract()["nodes"],
            {"mark_submitted": "node-001"},
            "pid-001",
            {},
            field_types={"field-status": 9},
        )
        self.assertEqual(1, len(tasks))
        self.assertEqual("mark_submitted", tasks[0].alias)
        self.assertEqual("node-001", tasks[0].node_id)
        self.assertEqual("pid-001", tasks[0].pid)
        self.assertEqual(9, tasks[0].data["fields"][0]["type"])

    def test_single_relation_list_normalizes_to_row_id_string(self):
        fields = save_actions._normalize_fields(
            [
                {
                    "fieldId": "relation-field",
                    "value": ["row-guid"],
                }
            ],
            {"relation-field": 29},
        )
        self.assertEqual("row-guid", fields[0]["fieldValue"])

    def test_missing_pid_is_structured_blocker(self):
        argv = [
            "save_actions.py",
            "--contract",
            str(FIXTURES / "complex-contract.json"),
        ]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(2, save_actions.main())

    def test_inner_process_uses_pid_scoped_alias_mapping(self):
        nodes = [
            {
                "alias": "sub",
                "nodeType": "sub_process",
                "config": {
                    "process": {
                        "nodes": [
                            {
                                "nodeAlias": "inner_update",
                                "nodeType": "update_record",
                                "name": "内部更新",
                                "config": {
                                    "worksheet": "ws-purchase",
                                    "target": {"node": "sub_trigger"},
                                    "fields": [
                                        {"fieldId": "field-status", "value": "x"}
                                    ],
                                },
                            }
                        ]
                    }
                },
            }
        ]
        tasks = save_actions.collect_tasks(
            nodes,
            {"sub": "outer-node"},
            "main-pid",
            {"sub": "inner-pid"},
            alias_maps={
                "main-pid": {"sub": "outer-node"},
                "inner-pid": {
                    "inner_update": "inner-node",
                    "sub_trigger": "inner-trigger",
                },
            },
        )
        self.assertEqual(1, len(tasks))
        self.assertEqual("inner-pid", tasks[0].pid)
        self.assertEqual("inner-node", tasks[0].node_id)
        self.assertEqual("inner-trigger", tasks[0].data["source_node_id"])

    def test_missing_inner_pid_never_falls_back_to_main_scope(self):
        nodes = [
            {
                "alias": "sub",
                "nodeType": "sub_process",
                "config": {
                    "process": {
                        "nodes": [
                            {
                                "nodeAlias": "write",
                                "nodeType": "update_record",
                                "config": {
                                    "worksheet": "ws-purchase",
                                    "target": {"node": "trigger"},
                                    "fields": [
                                        {"fieldId": "field-status", "value": "x"}
                                    ],
                                },
                            }
                        ]
                    }
                },
            }
        ]
        tasks = save_actions.collect_tasks(
            nodes,
            {"sub": "sub-node", "write": "outer-write-node"},
            "main-pid",
            {},
            alias_maps={
                "main-pid": {
                    "sub": "sub-node",
                    "write": "outer-write-node",
                }
            },
            field_types={"field-status": 9},
        )
        self.assertEqual("", tasks[0].pid)
        self.assertEqual("", tasks[0].node_id)

    def test_literal_create_record_does_not_bind_source_node(self):
        nodes = [
            {
                "alias": "create_log",
                "nodeType": "create_record",
                "config": {
                    "worksheet": "ws-log",
                    "target": {"node": "trigger"},
                    "fields": [
                        {"fieldId": "log-title", "value": "created"}
                    ],
                },
            }
        ]
        tasks = save_actions.collect_tasks(
            nodes,
            {"create_log": "node-create", "trigger": "node-trigger"},
            "main-pid",
            {},
            field_types={"log-title": 2},
        )
        self.assertEqual("", tasks[0].data["source_alias"])
        self.assertEqual("", tasks[0].data["source_node_id"])

    def test_dynamic_update_fields_preserve_pbp_and_rollup_sources(self):
        nodes = [
            {
                "alias": "count_targets",
                "nodeType": "rollup",
                "name": "统计关联数量",
                "config": {"data_source": {"node": "fetch_targets"}},
            },
            {
                "alias": "call_normalize",
                "nodeType": "pbp_call",
                "name": "调用标准化 PBP",
                "config": {
                    "processId": "pbp-pid",
                    "outputs": [
                        {
                            "fieldId": "pbp-output",
                            "fieldName": "normalized_value",
                            "type": 6,
                        }
                    ],
                },
            },
            {
                "alias": "update_source",
                "nodeType": "update_record",
                "name": "回写验收结果",
                "config": {
                    "worksheet": "source-ws",
                    "target": {"node": "trigger"},
                    "fields": [
                        {
                            "fieldId": "normalized-field",
                            "valueRef": {
                                "kind": "field",
                                "node": "call_normalize",
                                "fieldId": "pbp-output",
                            },
                        },
                        {
                            "fieldId": "count-field",
                            "valueRef": {
                                "kind": "field",
                                "node": "count_targets",
                                "fieldId": "number_fx_id",
                            },
                        },
                    ],
                },
            },
        ]
        tasks = save_actions.collect_tasks(
            nodes,
            {
                "trigger": "trigger-id",
                "count_targets": "count-id",
                "call_normalize": "call-id",
                "update_source": "update-id",
            },
            "main-pid",
            {},
            field_types={"normalized-field": 6, "count-field": 6},
        )
        fields = tasks[0].data["fields"]
        self.assertEqual("call-id", fields[0]["nodeId"])
        self.assertEqual("pbp-output", fields[0]["fieldValueId"])
        self.assertEqual(17, fields[0]["nodeAppType"])
        self.assertEqual("pbp-pid", fields[0]["nodeAppId"])
        self.assertEqual(20, fields[0]["nodeTypeId"])
        self.assertEqual("500", fields[0]["nodeActionId"])
        self.assertEqual("count-id", fields[1]["nodeId"])
        self.assertEqual("number_fx_id", fields[1]["fieldValueId"])
        self.assertEqual(11, fields[1]["nodeAppType"])
        self.assertEqual(9, fields[1]["nodeTypeId"])
        self.assertEqual("105", fields[1]["nodeActionId"])


class ExtendedDslTests(unittest.TestCase):
    def test_pbp_trigger_can_preserve_contract_control_id(self):
        from hap_cli.core import workflow_node_dsl as dsl

        original = dsl._pbp_control
        with hap_dsl_extensions.installed_extensions():
            control = dsl._pbp_control(
                {
                    "controlId": "input-control-id",
                    "name": "old_value",
                    "type": "number",
                    "required": True,
                }
            )
            self.assertEqual("input-control-id", control["controlId"])
        self.assertIs(original, dsl._pbp_control)

    def test_extended_context_normalizes_string_field_source_alias(self):
        from hap_cli.core import workflow_node_dsl as dsl

        original = dsl.translate_field_patches
        with hap_dsl_extensions.installed_extensions():
            fields = dsl.translate_field_patches(
                [
                    {
                        "fieldId": "target-field",
                        "valueRef": {
                            "kind": "field",
                            "node": "source_alias",
                            "fieldId": "source-field",
                        },
                    }
                ],
                {"source_alias": "source-id"},
            )

        self.assertEqual("source-id", fields[0]["nodeId"])
        self.assertEqual("source-field", fields[0]["fieldValueId"])
        self.assertIs(original, dsl.translate_field_patches)

    def test_code_bypasses_legacy_batch_normalizer_rejection(self):
        from hap_cli.core import workflow_node_dsl as dsl

        original = dsl._normalize_v3_node
        node = {
            "nodeAlias": "normalize",
            "nodeType": "code",
            "config": {"code": "output = { result: 1 };"},
        }
        with hap_dsl_extensions.installed_extensions():
            self.assertEqual(node, dsl._normalize_v3_node(node))
        self.assertIs(original, dsl._normalize_v3_node)

    def test_pbp_output_reuses_platform_owned_terminal_node(self):
        from hap_cli.core import workflow_node_dsl as dsl

        structure = {
            "flowNodeMap": {
                "trigger-id": {"id": "trigger-id", "typeId": 0},
                "output-id": {
                    "id": "output-id",
                    "typeId": 20,
                    "actionId": "502",
                },
            }
        }
        with mock.patch(
            "hap_cli.core.flow_node.get_nodes",
            return_value=structure,
        ), mock.patch("hap_cli.core.flow_node.add_node") as add_node, mock.patch(
            "hap_cli.core.flow_node.save_node",
            return_value={"ok": True},
        ):
            with hap_dsl_extensions.installed_extensions():
                result = dsl.build_workflow_nodes(
                    mock.Mock(),
                    "pbp-pid",
                    [
                        {
                            "nodeAlias": "return_value",
                            "nodeType": "pbp_output",
                            "name": "输出参数",
                            "config": {"outputs": []},
                        }
                    ],
                    trigger_node_id="trigger-id",
                    trigger_alias="pbp_trigger",
                )

        add_node.assert_not_called()
        self.assertEqual(
            "output-id",
            result["aliasToNodeId"]["return_value"],
        )
        self.assertEqual("output-id", result["created"][0]["nodeId"])

    def test_code_wire_uses_utf8_base64_and_resolves_input_node(self):
        source = "const 名称 = input.old;\noutput = { result: 名称 };"
        wire = hap_dsl_extensions.build_code_wire(
            {
                "config": {
                    "language": "javascript",
                    "code": source,
                    "inputs": [
                        {
                            "name": "old",
                            "value": {
                                "kind": "field",
                                "node": "trigger",
                                "fieldId": "old-value",
                            },
                        }
                    ],
                }
            },
            {"trigger": "trigger-id"},
        )
        import base64

        self.assertEqual(source, base64.b64decode(wire["code"]).decode())
        self.assertEqual("102", wire["actionId"])
        self.assertEqual(
            "$trigger-id-old-value$",
            wire["inputDatas"][0]["value"],
        )

    def test_code_wire_accepts_preencoded_source_without_double_encoding(self):
        import base64

        source = "output = { result: input.old ?? 0 };"
        encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
        wire = hap_dsl_extensions.build_code_wire(
            {
                "config": {
                    "language": "javascript",
                    "source": source,
                    "code": encoded,
                    "codeEncoding": "utf8_base64",
                }
            },
            {},
        )
        self.assertEqual(encoded, wire["code"])

    def test_static_preflight_rejects_mismatched_preencoded_code(self):
        import base64

        contract = copy.deepcopy(load_contract())
        contract["nodes"] = [
            {
                "alias": "code",
                "nodeType": "code",
                "config": {
                    "source": "output = { result: 1 };",
                    "code": base64.b64encode(
                        b"output = { result: 2 };"
                    ).decode("ascii"),
                    "codeEncoding": "utf8_base64",
                },
            }
        ]
        passed, errors = preflight.validate_static(contract)
        self.assertFalse(passed)
        self.assertTrue(any("Base64 解码结果不一致" in error for error in errors))

    def test_pbp_fields_keep_metadata_and_resolve_dynamic_value(self):
        fields = hap_dsl_extensions.build_pbp_fields(
            [
                {
                    "fieldId": "output-id",
                    "fieldName": "normalized_value",
                    "alias": "normalized_value",
                    "desc": "",
                    "type": 6,
                    "valueRef": {
                        "kind": "field",
                        "node": "compute",
                        "fieldId": "number_fx_id",
                    },
                }
            ],
            {"compute": "compute-id"},
            {
                "compute": {
                    "nodeAlias": "compute",
                    "nodeType": "compute",
                    "name": "计算绝对值",
                    "config": {
                        "mode": "function",
                        "output_type": "number",
                    },
                }
            },
        )
        self.assertEqual("normalized_value", fields[0]["fieldName"])
        self.assertEqual("compute-id", fields[0]["nodeId"])
        self.assertEqual("string_fx_id", fields[0]["fieldValueId"])
        self.assertEqual(11, fields[0]["nodeAppType"])
        self.assertEqual("6", fields[0]["fieldValueType"])
        self.assertEqual(9, fields[0]["nodeTypeId"])
        self.assertEqual("106", fields[0]["nodeActionId"])
        self.assertEqual(0, fields[0]["sourceType"])
        self.assertEqual("compute-id", fields[0]["sureNodeId"])
        self.assertEqual("计算绝对值", fields[0]["nodeName"])
        self.assertEqual("结果", fields[0]["fieldValueName"])
        self.assertFalse(fields[0]["isSourceApp"])
        self.assertNotIn("addType", fields[0])

    def test_non_function_compute_keeps_declared_result_id(self):
        fields = hap_dsl_extensions.build_pbp_fields(
            [
                {
                    "fieldId": "output-id",
                    "type": 6,
                    "valueRef": {
                        "kind": "field",
                        "node": "compute",
                        "fieldId": "number_fx_id",
                    },
                }
            ],
            {"compute": "compute-id"},
            {
                "compute": {
                    "nodeAlias": "compute",
                    "nodeType": "compute",
                    "name": "数值计算",
                    "config": {"mode": "number", "output_type": "number"},
                }
            },
        )
        self.assertEqual("number_fx_id", fields[0]["fieldValueId"])

    def test_interface_push_defaults_match_alert_wire(self):
        wire = hap_dsl_extensions.build_push_wire(
            {"config": {"content": "完成", "pushType": 1}},
            {},
        )
        self.assertEqual(1, wire["pushType"])
        self.assertEqual(2, wire["promptType"])
        self.assertEqual(5, wire["duration"])
        self.assertEqual("完成", wire["content"])

    def test_static_preflight_rejects_incomplete_extension_nodes(self):
        contract = copy.deepcopy(load_contract())
        contract["nodes"] = [
            {"alias": "code", "nodeType": "code", "config": {}},
            {"alias": "call", "nodeType": "pbp_call", "config": {}},
            {
                "alias": "push",
                "nodeType": "interface_push",
                "config": {"pushType": 1},
            },
        ]
        passed, errors = preflight.validate_static(contract)
        self.assertFalse(passed)
        self.assertTrue(any("config.code" in error for error in errors))
        self.assertTrue(any("processId" in error for error in errors))
        self.assertTrue(any("弹出提示内容" in error for error in errors))


class BatchRunnerTests(unittest.TestCase):
    def test_extended_nodes_route_through_in_process_builder(self):
        nodes = [
            {
                "nodeAlias": "normalize",
                "nodeType": "code",
                "name": "标准化",
                "config": {"code": "output = { result: 1 };"},
            }
        ]
        trigger_pbp = {
            "inputs": [
                {"name": "old_value", "type": "number", "required": True}
            ]
        }
        built = {
            "aliasToNodeId": {
                "pbp_trigger": "trigger-id",
                "normalize": "code-id",
            },
            "created": [
                {
                    "alias": "normalize",
                    "nodeId": "code-id",
                    "nodeType": "code",
                }
            ],
        }
        with mock.patch.object(
            run_batch_add.hap_dsl_extensions,
            "run_extended_batch_add",
            return_value=built,
        ) as extended, mock.patch.object(run_batch_add.subprocess, "run") as run:
            result, exit_code = run_batch_add.run_batch_add(
                "pid-pbp",
                nodes,
                trigger_alias="pbp_trigger",
                trigger_pbp=trigger_pbp,
            )

        self.assertEqual(0, exit_code)
        self.assertEqual("pass", result["verdict"])
        self.assertEqual("pid-pbp", result["pid"])
        extended.assert_called_once_with(
            "pid-pbp",
            nodes,
            trigger_alias="pbp_trigger",
            trigger_pbp=trigger_pbp,
        )
        run.assert_not_called()

    def test_successful_batch_output_is_bound_to_pid(self):
        completed = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {"aliasToNodeId": {"a": "node-a"}, "created": []}
            ),
            stderr="",
        )
        with mock.patch.object(run_batch_add.subprocess, "run", return_value=completed):
            result, exit_code = run_batch_add.run_batch_add(
                "pid-001",
                [{"nodeAlias": "a", "nodeType": "branch", "config": {}}],
            )
        self.assertEqual(0, exit_code)
        self.assertEqual("pid-001", result["pid"])
        self.assertEqual("pass", result["verdict"])

    def test_failed_batch_recovers_mapping_from_read_only_structure(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="500")
        structure = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "startEventId": "trigger-id",
                    "flowNodeMap": {
                        "node-a": {
                            "id": "node-a",
                            "name": "节点A",
                            "typeId": 6,
                        }
                    },
                }
            ),
            stderr="",
        )
        with mock.patch.object(
            run_batch_add.subprocess,
            "run",
            side_effect=[failed, structure],
        ):
            result, exit_code = run_batch_add.run_batch_add(
                "pid-001",
                [
                    {
                        "nodeAlias": "a",
                        "nodeType": "update_record",
                        "name": "节点A",
                        "config": {},
                    }
                ],
            )
        self.assertEqual(0, exit_code)
        self.assertTrue(result["recovered_from_structure"])
        self.assertEqual("node-a", result["aliasToNodeId"]["a"])

    def test_structure_generates_pid_scoped_alias_maps(self):
        structure = {
            "processId": "main-pid",
            "nodes": [
                {
                    "nodeAlias": "sub",
                    "nodeId": "outer-node",
                    "innerProcessId": "inner-pid",
                    "process": {
                        "processId": "inner-pid",
                        "nodes": [
                            {
                                "nodeAlias": "sub_trigger",
                                "nodeId": "inner-trigger",
                            },
                            {
                                "nodeAlias": "inner_update",
                                "nodeId": "inner-node",
                            },
                        ],
                    },
                }
            ],
        }
        mappings = structure_to_mappings.extract_scoped_mappings(structure)
        self.assertEqual("outer-node", mappings["main-pid"]["sub"])
        self.assertEqual(
            "inner-node",
            mappings["inner-pid"]["inner_update"],
        )

    def test_real_flow_node_map_shape_is_supported(self):
        structure = {
            "processId": "main-pid",
            "startEventId": "start-id",
            "flowNodeMap": {
                "start-id": {"id": "start-id", "nodeAlias": "trigger"},
                "sub-id": {
                    "id": "sub-id",
                    "nodeAlias": "sub",
                    "innerProcessId": "inner-pid",
                    "processNode": {
                        "processId": "inner-pid",
                        "startEventId": "inner-start",
                        "flowNodeMap": {
                            "inner-start": {
                                "id": "inner-start",
                                "nodeAlias": "sub_trigger",
                            },
                            "inner-action": {
                                "id": "inner-action",
                                "nodeAlias": "inner_update",
                            },
                        },
                    },
                },
            },
        }
        mappings = structure_to_mappings.extract_scoped_mappings(structure)
        self.assertEqual("sub-id", mappings["main-pid"]["sub"])
        self.assertEqual(
            "inner-action",
            mappings["inner-pid"]["inner_update"],
        )

    def test_batch_output_recovers_inner_alias_mapping(self):
        contract = {
            "nodes": [
                {
                    "alias": "approval",
                    "config": {
                        "process": {
                            "nodes": [
                                {
                                    "nodeAlias": "approval_start",
                                    "nodeType": "approval_start",
                                },
                                {
                                    "nodeAlias": "approve_step",
                                    "nodeType": "approve",
                                },
                            ]
                        }
                    },
                }
            ]
        }
        batch_output = {
            "pid": "main-pid",
            "aliasToNodeId": {"approval": "outer-node"},
            "created": [
                {
                    "alias": "approval",
                    "nodeId": "outer-node",
                    "innerProcessId": "inner-pid",
                },
                {
                    "alias": "approve_step",
                    "nodeId": "inner-approve",
                },
            ],
        }
        mappings = structure_to_mappings.extract_batch_scoped_mappings(
            contract,
            batch_output,
        )
        self.assertEqual(
            "inner-approve",
            mappings["inner-pid"]["approve_step"],
        )


class ExecutionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.contract_path = Path(self.temp_dir.name) / "contract.json"
        self.state_path = Path(self.temp_dir.name) / "state.json"
        self.contract_path.write_text(
            json.dumps(load_contract()),
            encoding="utf-8",
        )
        self.state = execution_state.new_state(
            str(self.contract_path),
            str(self.state_path),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_completed_step_cannot_repeat(self):
        execution_state.advance(self.state, "static_preflight")
        with self.assertRaisesRegex(ValueError, "禁止重复"):
            execution_state.advance(self.state, "static_preflight")

    def test_transient_failure_retries_at_most_three_times(self):
        decisions = []
        for _ in range(4):
            self.state, decision = execution_state.record_failure(
                self.state,
                "live_preflight",
                "HTTP 503 temporarily unavailable",
            )
            decisions.append(decision)
        self.assertEqual(["retry", "retry", "retry", "hard_stop"], decisions)

    def test_mutating_timeout_is_partial_write_not_retry(self):
        self.state, decision = execution_state.record_failure(
            self.state,
            "batch_add",
            "HTTP 504 timeout",
        )
        self.assertEqual("await_user", decision)
        self.assertEqual("PARTIAL_WRITE", self.state["errors"][-1]["class"])

    def test_unknown_create_error_is_partial_write(self):
        self.state, decision = execution_state.record_failure(
            self.state,
            "create_skeleton",
            "HTTP 500 EOF",
        )
        self.assertEqual("await_user", decision)
        self.assertEqual("PARTIAL_WRITE", self.state["errors"][-1]["class"])

    def test_runtime_outputs_are_required_before_advancing_write_steps(self):
        execution_state.advance(self.state, "static_preflight")
        execution_state.advance(self.state, "live_preflight")
        execution_state.begin_step(self.state, "create_skeleton")
        with self.assertRaisesRegex(ValueError, "pid, trigger_node_id"):
            execution_state.advance(self.state, "create_skeleton")

    def test_in_progress_write_requires_probe_after_resume(self):
        self.state["current_step"] = "batch_add"
        execution_state.begin_step(self.state, "batch_add")
        with self.assertRaisesRegex(ValueError, "只读探测"):
            execution_state.begin_step(self.state, "batch_add")

    def test_semantic_failure_returns_to_mode_b(self):
        _, decision = execution_state.record_failure(
            self.state,
            "static_preflight",
            "contract branch condition scope invalid",
        )
        self.assertEqual("mode_b_handoff", decision)
        self.assertEqual(
            "return_to_hhr_plan_mode_b",
            self.state["next_action"],
        )

    def test_changed_contract_invalidates_state(self):
        self.contract_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "已变化"):
            execution_state.verify_contract_unchanged(self.state)

    def test_init_refuses_to_overwrite_checkpoint_without_reset(self):
        execution_state.atomic_write(self.state_path, self.state)
        argv = [
            "execution_state.py",
            "init",
            "--contract",
            str(self.contract_path),
            "--state",
            str(self.state_path),
        ]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(2, execution_state.main())

    def test_partial_no_write_can_be_resolved_and_retried(self):
        self.state["current_step"] = "save_actions"
        execution_state.begin_step(self.state, "save_actions")
        self.state, _ = execution_state.record_failure(
            self.state,
            "save_actions",
            "mapping missing before SDK call",
            2,
        )
        execution_state.resolve_partial(
            self.state,
            "save_actions",
            "no_write",
        )
        self.assertIsNone(self.state["in_progress_step"])
        self.assertEqual("ready", self.state["status"])


if __name__ == "__main__":
    unittest.main()
