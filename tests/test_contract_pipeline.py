import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import contract_compat  # noqa: E402
import design_validator  # noqa: E402
import agent_prepare  # noqa: E402
import lock_manager  # noqa: E402
import verification_merge  # noqa: E402
from lock_to_contract import ConversionError, convert_lock  # noqa: E402


HAP_PREFLIGHT_PATH = (
    ROOT.parent / "hap-flow-exec" / "scripts" / "preflight.py"
)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class ContractPipelineTests(unittest.TestCase):
    def setUp(self):
        self.lock = load_fixture("valid_execution_lock.json")
        self.context = load_fixture("project_context.json")
        self.graph = load_fixture("dependency_graph.json")

    def test_valid_lock_converts_exactly_to_expected_contract(self):
        expected = load_fixture("expected_execution_contract.json")
        contract = convert_lock(self.lock)
        self.assertEqual(expected, contract)
        self.assertEqual([], contract_compat.validate_lock(self.lock))
        self.assertEqual([], contract_compat.validate_exec(contract))

    def test_merge_then_convert_passes_with_matching_digest(self):
        lock = copy.deepcopy(self.lock)
        lock.pop("verification")
        lock["gates"].pop("agent_1_logic")
        lock["gates"].pop("agent_2_platform")
        digest = agent_prepare.compute_lock_digest(lock)
        agent1 = load_fixture("agent1-pass.json")
        agent2 = load_fixture("agent2-pass.json")
        agent1["input_digest"] = digest
        agent2["input_digest"] = digest

        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            agent1_path = Path(directory) / "agent1.json"
            agent2_path = Path(directory) / "agent2.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            agent1_path.write_text(json.dumps(agent1), encoding="utf-8")
            agent2_path.write_text(json.dumps(agent2), encoding="utf-8")
            result, exit_code = verification_merge.run_merge(
                lock_path,
                [
                    ("agent_1_logic", agent1_path),
                    ("agent_2_platform", agent2_path),
                ],
                mode="design",
            )
            merged = json.loads(lock_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code, result)
        self.assertEqual("提交采购需求", convert_lock(merged)["meta"]["workflow_name"])

    def test_merge_semantic_failure_blocks_conversion(self):
        lock = copy.deepcopy(self.lock)
        lock.pop("verification")
        lock["gates"].pop("agent_1_logic")
        lock["gates"].pop("agent_2_platform")
        digest = agent_prepare.compute_lock_digest(lock)
        agent1 = load_fixture("agent1-pass.json")
        agent2 = load_fixture("agent2-pass.json")
        for envelope in (agent1, agent2):
            envelope["input_digest"] = digest
        agent1["verdict"] = "fail"
        agent1["failure_code"] = "A1_LOGIC_FAILED"
        agent1["summary"] = {
            "total_checks": 5,
            "passed": 4,
            "failed": 1,
            "uncertain": 0,
        }
        agent1["issues"] = [
            {"severity": "high", "description": "逻辑失败", "fix": "修复逻辑"}
        ]
        agent1["payload"]["sections"]["logic"] = {
            "result": "fail",
            "detail": "逻辑失败",
        }

        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            agent1_path = Path(directory) / "agent1.json"
            agent2_path = Path(directory) / "agent2.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            agent1_path.write_text(json.dumps(agent1), encoding="utf-8")
            agent2_path.write_text(json.dumps(agent2), encoding="utf-8")
            _, exit_code = verification_merge.run_merge(
                lock_path,
                [
                    ("agent_1_logic", agent1_path),
                    ("agent_2_platform", agent2_path),
                ],
                mode="design",
            )
            merged = json.loads(lock_path.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        with self.assertRaises(ConversionError):
            convert_lock(merged)

    def test_pending_failed_or_missing_required_gate_blocks_conversion(self):
        cases = (
            ("gate_1_dependency", "pending"),
            ("gate_2_logic", "fail"),
            ("agent_1_logic", None),
        )
        for gate_name, result in cases:
            with self.subTest(gate=gate_name, result=result):
                invalid = copy.deepcopy(self.lock)
                if result is None:
                    invalid["gates"].pop(gate_name)
                else:
                    invalid["gates"][gate_name]["result"] = result
                with self.assertRaises(ConversionError):
                    convert_lock(invalid)

    def test_gate_three_may_be_not_applicable(self):
        lock = copy.deepcopy(self.lock)
        lock["gates"]["gate_3_timing"]["result"] = "n/a"
        lock["verification"]["input_digest"] = agent_prepare.compute_lock_digest(lock)
        self.assertEqual("提交采购需求", convert_lock(lock)["meta"]["workflow_name"])

    @unittest.skipUnless(
        HAP_PREFLIGHT_PATH.is_file(),
        "hap-flow-exec sibling skill 未安装；仓库内 validate-exec 仍会执行",
    )
    def test_derived_contract_passes_hap_flow_exec_preflight(self):
        spec = importlib.util.spec_from_file_location(
            "hap_flow_exec_preflight",
            HAP_PREFLIGHT_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        passed, errors = module.validate_static(convert_lock(self.lock))

        self.assertTrue(passed, errors)
        self.assertEqual([], errors)

    def test_legacy_camel_case_node_ids_are_accepted_and_normalized(self):
        legacy = copy.deepcopy(self.lock)
        node = legacy["workflows"][0]["node_chain"][0]
        node["typeId"] = str(node.pop("type_id"))
        node["actionId"] = str(node.pop("action_id"))
        legacy["verification"]["input_digest"] = (
            agent_prepare.compute_lock_digest(legacy)
        )

        contract = convert_lock(legacy)

        self.assertEqual(6, contract["nodes"][0]["type_id"])
        self.assertEqual(2, contract["nodes"][0]["action_id"])
        self.assertNotIn("typeId", contract["nodes"][0])
        self.assertNotIn("actionId", contract["nodes"][0])

    def test_conflicting_canonical_and_legacy_ids_fail(self):
        invalid = copy.deepcopy(self.lock)
        node = invalid["workflows"][0]["node_chain"][0]
        node["typeId"] = 7

        with self.assertRaises(ConversionError) as raised:
            convert_lock(invalid)

        paths = {error["path"] for error in raised.exception.errors}
        self.assertIn("$.workflows[0].node_chain[0].type_id", paths)

    def test_missing_id_and_config_fail_without_guessing(self):
        invalid = copy.deepcopy(self.lock)
        invalid["target"]["org_id"] = ""
        node = invalid["workflows"][0]["node_chain"][0]
        del node["config"]

        with self.assertRaises(ConversionError) as raised:
            convert_lock(invalid)

        paths = {error["path"] for error in raised.exception.errors}
        self.assertIn("$.target.org_id", paths)
        self.assertIn("$.workflows[0].node_chain[0].config", paths)

    def test_missing_field_id_inside_node_config_fails(self):
        invalid = copy.deepcopy(self.lock)
        del invalid["workflows"][0]["node_chain"][0]["config"]["fields"][0][
            "fieldId"
        ]

        with self.assertRaises(ConversionError) as raised:
            convert_lock(invalid)

        paths = {error["path"] for error in raised.exception.errors}
        self.assertIn(
            "$.workflows[0].node_chain[0].config.fields[0].fieldId",
            paths,
        )

    def test_multiple_workflows_require_explicit_selection(self):
        invalid = copy.deepcopy(self.lock)
        second = copy.deepcopy(invalid["workflows"][0])
        second["name"] = "第二工作流"
        invalid["workflows"].append(second)
        invalid["verification"]["input_digest"] = (
            agent_prepare.compute_lock_digest(invalid)
        )

        with self.assertRaises(ConversionError) as raised:
            convert_lock(invalid)

        self.assertTrue(
            any(
                "--workflow" in error["detail"]
                for error in raised.exception.errors
            )
        )
        selected = convert_lock(invalid, "第二工作流")
        self.assertEqual("第二工作流", selected["meta"]["workflow_name"])

    def test_contract_compat_recognizes_all_three_validation_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / "execution_contract.json"
            contract_path.write_text(
                json.dumps(convert_lock(self.lock), ensure_ascii=False),
                encoding="utf-8",
            )
            cases = [
                ("validate-lock", FIXTURES / "valid_execution_lock.json", "lock"),
                ("validate", FIXTURES / "valid_execution_lock.json", "lock"),
                ("validate-exec", contract_path, "exec"),
                ("validate", contract_path, "exec"),
            ]
            for command, path, expected_kind in cases:
                with self.subTest(command=command, path=path):
                    result = run_script(
                        "contract_compat.py",
                        command,
                        path,
                        "--quiet",
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertEqual("pass", output["verdict"])
                    self.assertEqual(expected_kind, output["document_kind"])

    def test_schema_versions_trigger_and_exec_ids_are_strict(self):
        invalid_lock = copy.deepcopy(self.lock)
        invalid_lock["meta"]["schema_version"] = "1.0"
        invalid_lock["workflows"][0]["trigger"]["type"] = "unknown"
        violations = contract_compat.validate_lock(invalid_lock)
        paths = {item["path"] for item in violations}
        self.assertIn("$.meta.schema_version", paths)
        self.assertIn("$.workflows[0].trigger.type", paths)
        self.assertIn("$.workflows[0].trigger_type", paths)

        contract = convert_lock(self.lock)
        contract["meta"]["schema_version"] = "2.0"
        contract["nodes"][0]["type_id"] = 9999
        contract["nodes"][0]["action_id"] = 9999
        paths = {
            item["path"] for item in contract_compat.validate_exec(contract)
        }
        self.assertIn("$.meta.schema_version", paths)
        self.assertIn("$.nodes[0].type_id", paths)

        contract = convert_lock(self.lock)
        contract["nodes"][0]["action_id"] = 9999
        paths = {
            item["path"] for item in contract_compat.validate_exec(contract)
        }
        self.assertIn("$.nodes[0].action_id", paths)

    def test_lock_manager_init_requires_source_design(self):
        result = run_script(
            "lock_manager.py",
            "init",
            "测试项目",
            "--context-file",
            FIXTURES / "project_context.json",
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("--source-design", result.stderr)

    def test_design_validator_uses_injected_context_and_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "design-validator.json"
            result = run_script(
                "design_validator.py",
                "测试项目",
                "--lock-file",
                FIXTURES / "valid_execution_lock.json",
                "--context-file",
                FIXTURES / "project_context.json",
                "--graph-file",
                FIXTURES / "dependency_graph.json",
                "--output",
                output_path,
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("pass", output["overall_verdict"])
        self.assertEqual(
            agent_prepare.compute_lock_digest(self.lock),
            output["input_digest"],
        )

    def test_explicit_graph_check_fails_when_graph_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_graph = Path(directory) / "missing-graph.json"
            result = run_script(
                "design_validator.py",
                "测试项目",
                "--check-graph",
                "--graph-file",
                missing_graph,
            )

        self.assertEqual(1, result.returncode)
        output = json.loads(result.stdout)
        self.assertEqual("fail", output["overall_verdict"])
        self.assertTrue(
            any(
                issue.get("type") == "dependency_graph_missing"
                for check in output["results"]
                for issue in check.get("issues", [])
            )
        )

    def test_lock_association_requires_dependency_graph(self):
        lock = copy.deepcopy(self.lock)
        lock["associations"] = [
            {
                "from_sheet": "采购需求",
                "to_sheet": "采购需求",
                "field_name": "状态",
                "field_id": "field-status",
                "type": 29,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            result = lock_manager.validate_lock(
                "测试项目",
                str(lock_path),
                context=self.context,
                graph_file=str(Path(directory) / "missing-graph.json"),
            )

        self.assertEqual("fail", result["verdict"])
        self.assertTrue(
            any(
                issue["type"] == "dependency_graph_missing"
                for issue in result["issues"]
            )
        )

    def test_lock_manager_validation_accepts_injected_fixtures(self):
        result = lock_manager.validate_lock(
            "测试项目",
            str(FIXTURES / "valid_execution_lock.json"),
            context=self.context,
            graph=self.graph,
        )

        self.assertEqual("pass", result["verdict"], result["issues"])

    def test_lock_manager_blocks_every_schema_violation_severity(self):
        lock = copy.deepcopy(self.lock)
        lock["sheets"][0]["fields"][0]["type"] = "UnknownFieldType"
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            result = lock_manager.validate_lock(
                "测试项目",
                str(lock_path),
                context=self.context,
                graph=self.graph,
            )

        self.assertEqual("fail", result["verdict"])
        self.assertTrue(
            any(
                issue["type"] == "lock_schema"
                and issue["severity"] == "error"
                for issue in result["issues"]
            )
        )

    def test_verify_platform_accepts_canonical_and_legacy_ids(self):
        canonical = run_script(
            "verify-platform.py",
            "--lock-file",
            FIXTURES / "valid_execution_lock.json",
        )
        self.assertEqual(0, canonical.returncode, canonical.stderr)
        self.assertEqual("pass", json.loads(canonical.stdout)["verdict"])

        legacy = copy.deepcopy(self.lock)
        node = legacy["workflows"][0]["node_chain"][0]
        node["typeId"] = str(node.pop("type_id"))
        node["actionId"] = str(node.pop("action_id"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(
                json.dumps(legacy, ensure_ascii=False),
                encoding="utf-8",
            )
            legacy_result = run_script(
                "verify-platform.py",
                "--lock-file",
                path,
            )
        self.assertEqual(0, legacy_result.returncode, legacy_result.stderr)
        self.assertEqual("pass", json.loads(legacy_result.stdout)["verdict"])

    def test_design_validator_function_injection_never_reads_home(self):
        checks = [("采购需求", ["状态"])]
        result = design_validator.check_field_existence(
            "不存在于主目录的项目",
            checks,
            context=self.context,
        )
        self.assertEqual("pass", result["verdict"])

    def test_lock_schema_file_was_explicitly_renamed(self):
        new_schema = (
            ROOT
            / "references"
            / "schemas"
            / "execution-lock-validation-schema.json"
        )
        old_schema = (
            ROOT
            / "references"
            / "schemas"
            / "execution-contract-schema.json"
        )
        self.assertTrue(new_schema.is_file())
        compatibility_marker = json.loads(
            old_schema.read_text(encoding="utf-8")
        )
        self.assertTrue(compatibility_marker["deprecated"])
        self.assertEqual(
            "execution-lock-validation-schema.json",
            compatibility_marker["replacement"],
        )


if __name__ == "__main__":
    unittest.main()
