import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_module(
    "test_validate_agent_output",
    ROOT / "scripts" / "validate-agent-output.py",
)
MERGER = load_module(
    "test_verification_merge",
    ROOT / "scripts" / "verification_merge.py",
)
PREPARE = load_module(
    "test_agent_prepare",
    ROOT / "scripts" / "agent_prepare.py",
)


class AgentOutputValidationTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_all_agents_accept_positive_fixtures(self):
        for name in ("agent1-pass.json", "agent2-pass.json", "agent3-pass.json"):
            with self.subTest(name=name):
                result = VALIDATOR.validate_output(self.fixture(name))
                self.assertEqual("pass", result["format_verdict"])
                self.assertEqual("pass", result["semantic_verdict"])
                self.assertEqual([], result["format_failures"])

    def test_all_agents_reject_negative_fixtures(self):
        for name in (
            "agent1-invalid.json",
            "agent2-invalid.json",
            "agent3-invalid.json",
        ):
            with self.subTest(name=name):
                result = VALIDATOR.validate_output(self.fixture(name))
                self.assertEqual("fail", result["format_verdict"])
                self.assertEqual("not_evaluated", result["semantic_verdict"])
                self.assertTrue(result["format_failures"])

    def test_agent3_reads_payload_missed_dimensions(self):
        result = VALIDATOR.validate_output(self.fixture("agent3-fail.json"))
        self.assertEqual("pass", result["format_verdict"])
        self.assertEqual("fail", result["semantic_verdict"])
        self.assertEqual(
            "A3_AUDIT_COVERAGE_INCOMPLETE",
            result["semantic_failures"][0]["failure_code"],
        )

    def test_agent1_cannot_pass_with_uncertain_completeness(self):
        output = self.fixture("agent1-pass.json")
        output["payload"]["sections"]["completeness"] = {
            "result": "uncertain",
            "detail": "需求尚未完整追踪",
        }
        result = VALIDATOR.validate_output(output)
        self.assertEqual("fail", result["format_verdict"])
        self.assertTrue(
            any(
                failure["code"] == "FORMAT_COMPLETENESS_NOT_PASS"
                for failure in result["format_failures"]
            )
        )

    def test_agent2_cannot_pass_with_uncertain_check(self):
        output = self.fixture("agent2-pass.json")
        output["payload"]["node_checks"][0]["checks"]["sub_mode"] = {
            "result": "uncertain",
            "detail": "缺少平台证据",
        }
        output["summary"] = {
            "total_checks": 12,
            "passed": 11,
            "failed": 0,
            "uncertain": 1,
        }
        result = VALIDATOR.validate_output(output)
        self.assertEqual("fail", result["format_verdict"])
        self.assertTrue(
            any(
                failure["code"] == "FORMAT_UNRESOLVED_AGENT_CHECK"
                for failure in result["format_failures"]
            )
        )

    def test_agent1_cannot_pass_with_any_uncertain_section(self):
        output = self.fixture("agent1-pass.json")
        output["payload"]["sections"]["logic"] = {
            "result": "uncertain",
            "detail": "分支证据不足",
        }
        output["summary"] = {
            "total_checks": 6,
            "passed": 5,
            "failed": 0,
            "uncertain": 1,
        }
        result = VALIDATOR.validate_output(output)
        self.assertEqual("fail", result["format_verdict"])
        self.assertTrue(
            any(
                failure["code"] == "FORMAT_UNRESOLVED_AGENT_CHECK"
                for failure in result["format_failures"]
            )
        )

    def test_selftest_covers_pass_fail_and_invalid_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "validate-agent-output.py"),
                "--selftest",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual("pass", output["verdict"])
        self.assertEqual(9, output["cases_total"])

    def test_cli_separates_semantic_and_format_failures(self):
        semantic = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "validate-agent-output.py"),
                "--agent3",
                str(FIXTURES / "agent3-fail.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, semantic.returncode, semantic.stderr)
        semantic_output = json.loads(semantic.stdout)
        self.assertEqual("pass", semantic_output["format_verdict"])
        self.assertEqual("fail", semantic_output["semantic_verdict"])

        malformed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "validate-agent-output.py"),
                "--agent3",
                str(FIXTURES / "agent3-invalid.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, malformed.returncode, malformed.stderr)
        malformed_output = json.loads(malformed.stdout)
        self.assertEqual("fail", malformed_output["format_verdict"])
        self.assertEqual("not_evaluated", malformed_output["semantic_verdict"])

    def test_schema_is_json_and_declares_unified_envelope(self):
        schema = json.loads(
            (
                ROOT
                / "references"
                / "schemas"
                / "agent-verification-output.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(VALIDATOR.ENVELOPE_KEYS, set(schema["required"]))
        self.assertFalse(schema["additionalProperties"])


class VerificationMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target = Path(self.temp_dir.name) / "execution-lock.json"
        shutil.copyfile(FIXTURES / "execution-lock.json", self.target)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_complete_design_outputs_write_gates(self):
        result, exit_code = MERGER.run_merge(
            self.target,
            [
                (VALIDATOR.AGENT_IDS["agent1"], FIXTURES / "agent1-pass.json"),
                (VALIDATOR.AGENT_IDS["agent2"], FIXTURES / "agent2-pass.json"),
            ],
            mode="design",
        )
        self.assertEqual(0, exit_code)
        self.assertTrue(result["gates_written"])
        merged = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual("pass", merged["gates"]["agent_1_logic"]["result"])
        self.assertEqual("pass", merged["gates"]["agent_2_platform"]["result"])
        self.assertEqual(
            "pass",
            merged["verification"]["verification_agents"]["semantic_verdict"],
        )
        self.assertIn("fix_plan", merged["verification"])
        self.assertNotIn("verification_agents", merged["gates"])
        self.assertNotIn("fix_plan", merged["gates"])

    def test_format_failure_never_writes_gates(self):
        before = self.target.read_bytes()
        result, exit_code = MERGER.run_merge(
            self.target,
            [
                (VALIDATOR.AGENT_IDS["agent1"], FIXTURES / "agent1-pass.json"),
                (VALIDATOR.AGENT_IDS["agent2"], FIXTURES / "agent2-invalid.json"),
            ],
            mode="design",
        )
        self.assertEqual(2, exit_code)
        self.assertFalse(result["gates_written"])
        self.assertEqual(before, self.target.read_bytes())
        self.assertTrue(result["format_failures"])
        self.assertEqual([], result["semantic_failures"])

    def test_semantic_failure_is_written_separately(self):
        source = Path(self.temp_dir.name) / "audit-report.md"
        source.write_text("# audit\n", encoding="utf-8")
        envelope = json.loads(
            (FIXTURES / "agent3-fail.json").read_text(encoding="utf-8")
        )
        envelope["input_digest"] = PREPARE.compute_file_digest(source)
        agent_output = Path(self.temp_dir.name) / "agent3-fail.json"
        agent_output.write_text(
            json.dumps(envelope, ensure_ascii=False),
            encoding="utf-8",
        )
        result, exit_code = MERGER.run_merge(
            self.target,
            [
                (VALIDATOR.AGENT_IDS["agent3"], agent_output),
            ],
            mode="audit",
            source_path=source,
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("pass", result["format_verdict"])
        self.assertEqual("fail", result["semantic_verdict"])
        self.assertTrue(result["gates_written"])
        merged = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual("fail", merged["gates"]["agent_3_audit"]["result"])
        self.assertEqual(
            "A3_AUDIT_COVERAGE_INCOMPLETE",
            merged["gates"]["agent_3_audit"]["failure_code"],
        )
        self.assertEqual(
            PREPARE.compute_file_digest(source),
            merged["verification"]["input_digest"],
        )

    def test_old_agent_outputs_cannot_be_replayed_after_lock_change(self):
        target = json.loads(self.target.read_text(encoding="utf-8"))
        target["meta"]["project"] = "已变更项目"
        self.target.write_text(
            json.dumps(target, ensure_ascii=False),
            encoding="utf-8",
        )
        before = self.target.read_bytes()

        result, exit_code = MERGER.run_merge(
            self.target,
            [
                (VALIDATOR.AGENT_IDS["agent1"], FIXTURES / "agent1-pass.json"),
                (VALIDATOR.AGENT_IDS["agent2"], FIXTURES / "agent2-pass.json"),
            ],
            mode="design",
        )

        self.assertEqual(2, exit_code)
        self.assertEqual(before, self.target.read_bytes())
        self.assertTrue(
            any(
                failure["code"] == "FORMAT_INPUT_DIGEST_MISMATCH"
                for failure in result["format_failures"]
            )
        )


class AgentPrepareTests(unittest.TestCase):
    def test_prepare_keeps_platform_identifiers_and_contract(self):
        lock = {
            "meta": {"project": "测试", "mode": "A", "axioms_covered": [1]},
            "naming": {},
            "sheets": [
                {
                    "name": "订单",
                    "fields": [
                        {
                            "name": "状态",
                            "type": "SingleSelect",
                            "options": ["草稿", "完成"],
                        }
                    ],
                }
            ],
            "associations": [],
            "workflows": [
                {
                    "name": "更新订单",
                    "trigger_sheet": "订单",
                    "trigger_type": "button",
                    "node_chain": [
                        {
                            "index": 1,
                            "node_name": "更新",
                            "node_type": "update",
                            "type_id": 3,
                            "action_id": 1,
                        }
                    ],
                }
            ],
            "gates": {"agent_1_logic": {"result": "fail"}},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "lock.json"
            validator_path = Path(temp_dir) / "validator.json"
            path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
            validator_path.write_text(
                json.dumps(
                    {
                        "project": "测试",
                        "overall_verdict": "pass",
                        "input_digest": PREPARE.compute_lock_digest(lock),
                        "results": [
                            {
                                "gate": "Gate 4",
                                "verdict": "pass",
                                "issues": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            brief = PREPARE.prepare_brief(str(path), str(validator_path))
        node = brief["workflows"][0]["node_chain"][0]
        self.assertEqual(3, node["type_id"])
        self.assertEqual(1, node["action_id"])
        self.assertEqual(
            ["agent_1_logic", "agent_2_platform"],
            brief["verification_contract"]["agent_ids"],
        )
        self.assertEqual(PREPARE.compute_lock_digest(lock), brief["input_digest"])
        self.assertEqual(
            "pass",
            brief["deterministic_evidence"]["design_validator"][
                "overall_verdict"
            ],
        )
        self.assertNotIn("gates", brief)

    def test_prepare_rejects_stale_validator_evidence(self):
        lock = {"meta": {"project": "测试"}, "gates": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "lock.json"
            validator_path = Path(temp_dir) / "validator.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            validator_path.write_text(
                json.dumps(
                    {
                        "overall_verdict": "pass",
                        "input_digest": "0" * 64,
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "摘要不一致"):
                PREPARE.prepare_brief(
                    str(lock_path),
                    str(validator_path),
                )

    def test_prepare_only_keeps_manifest_workflows_touching_target_sheets(self):
        lock = {
            "meta": {"project": "测试"},
            "workflows": [{"trigger_sheet": "采购需求", "node_chain": []}],
            "associations": [],
            "gates": {},
        }
        digest = PREPARE.compute_lock_digest(lock)
        manifest = {
            "tables": {
                "采购需求": [
                    {
                        "pid": "pid-hit",
                        "wf": "更新采购",
                        "r": ["采购需求"],
                        "w": ["采购需求"],
                    }
                ],
                "无关表": [
                    {
                        "pid": "pid-miss",
                        "wf": "无关流程",
                        "r": ["无关表"],
                        "w": ["无关表"],
                    }
                ],
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "lock.json"
            validator_path = Path(temp_dir) / "validator.json"
            manifest_path = Path(temp_dir) / "manifest.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            validator_path.write_text(
                json.dumps(
                    {
                        "overall_verdict": "pass",
                        "input_digest": digest,
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            brief = PREPARE.prepare_brief(
                str(lock_path),
                str(validator_path),
                str(manifest_path),
            )
        scoped = brief["deterministic_evidence"]["manifest_scope"]["workflows"]
        self.assertEqual(["pid-hit"], [item["pid"] for item in scoped])

    def test_prepare_canonicalizes_legacy_node_ids(self):
        lock = {
            "meta": {"project": "测试"},
            "workflows": [
                {
                    "name": "旧格式流程",
                    "node_chain": [
                        {
                            "alias": "legacy",
                            "name": "旧节点",
                            "node_type": "update_record",
                            "typeId": "6",
                            "actionId": "2",
                        }
                    ],
                }
            ],
            "associations": [],
            "gates": {},
        }
        digest = PREPARE.compute_lock_digest(lock)
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "lock.json"
            validator_path = Path(temp_dir) / "validator.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            validator_path.write_text(
                json.dumps(
                    {
                        "overall_verdict": "pass",
                        "input_digest": digest,
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            brief = PREPARE.prepare_brief(
                str(lock_path),
                str(validator_path),
            )
        node = brief["workflows"][0]["node_chain"][0]
        self.assertEqual(6, node["type_id"])
        self.assertEqual(2, node["action_id"])


if __name__ == "__main__":
    unittest.main()
