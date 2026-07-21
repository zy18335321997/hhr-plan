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


class BatchRunnerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
