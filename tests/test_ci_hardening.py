import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "regression"
sys.path.insert(0, str(SCRIPTS))

import regression_test  # noqa: E402
import scan_secrets  # noqa: E402


class RegressionFixtureTests(unittest.TestCase):
    def test_fixture_extracts_real_metrics_and_both_edge_shapes(self):
        metrics, errors = regression_test.extract_metrics(
            "ci-minimal",
            data_root=FIXTURE_ROOT / "data",
        )

        self.assertEqual([], errors)
        self.assertEqual(3, metrics["worksheet_count"])
        self.assertEqual(2, metrics["workflow_count"])
        self.assertEqual(3, metrics["dependency_graph"]["edge_count"])
        self.assertEqual(
            ["客户↔订单"],
            metrics["dependency_graph"]["bidirectional_edge_pairs"],
        )

    def test_fixture_cli_performs_metric_comparison(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "regression_test.py"),
                "--project",
                "ci-minimal",
                "--fixture-dir",
                str(FIXTURE_ROOT),
                "--quiet",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("pass", json.loads(completed.stdout)["verdict"])

    def test_fixture_comparison_fails_when_data_drifts(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_copy = Path(directory) / "regression"
            shutil.copytree(FIXTURE_ROOT, fixture_copy)
            context_path = (
                fixture_copy
                / "data"
                / "ci-minimal"
                / "project_context.json"
            )
            context = json.loads(context_path.read_text(encoding="utf-8"))
            context["worksheets"].pop("明细")
            context_path.write_text(
                json.dumps(context, ensure_ascii=False),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "regression_test.py"),
                    "--project",
                    "ci-minimal",
                    "--fixture-dir",
                    str(fixture_copy),
                    "--quiet",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(1, completed.returncode)
        output = json.loads(completed.stdout)
        self.assertEqual("fail", output["verdict"])
        self.assertEqual(1, output["failures"])


class HardeningStaticTests(unittest.TestCase):
    def setUp(self):
        self.preflight = (SCRIPTS / "preflight.sh").read_text(encoding="utf-8")
        self.ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

    def test_preflight_uses_current_schemas_and_deterministic_gates(self):
        self.assertIn("execution-lock-validation-schema.json", self.preflight)
        self.assertIn("agent-verification-output.schema.json", self.preflight)
        self.assertIn("python3 -m unittest discover", self.preflight)
        self.assertIn('git -C "$SKILL_DIR" diff --check', self.preflight)
        self.assertIn(
            'git -C "$SKILL_DIR" diff --cached --check',
            self.preflight,
        )
        self.assertIn("skill_discovery.py", self.preflight)
        self.assertIn("validate --strict", self.preflight)
        self.assertIn("scripts/scan_secrets.py", self.preflight)
        self.assertIn("--worktree --staged", self.preflight)

    def test_preflight_help_probe_targets_argparse_entrypoints_only(self):
        self.assertIn("ast.parse", self.preflight)
        self.assertIn("has_main_guard", self.preflight)
        self.assertIn("uses_argparse", self.preflight)
        self.assertNotIn('find "$SKILL_DIR/scripts"', self.preflight)

    def test_ci_does_not_swallow_deterministic_failures(self):
        self.assertNotIn("|| true", self.ci)
        self.assertNotIn("|| exit 0", self.ci)
        self.assertIn("validate-agent-output.py --selftest", self.ci)
        self.assertIn("tests/fixtures/valid_execution_lock.json", self.ci)
        self.assertIn("--fixture-dir tests/fixtures/regression", self.ci)
        self.assertIn("unittest discover", self.ci)
        self.assertIn("github.event.pull_request.base.sha", self.ci)
        self.assertIn("github.event.before", self.ci)
        self.assertIn('git diff --check "$range"', self.ci)

    def test_platform_guide_defaults_to_repository_reference(self):
        guide = (ROOT / "agents" / "platform-verify.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "${WORKFLOW_NODES_GUIDE_PATH:-"
            "${SKILL_DIR}/references/platform/node-capabilities.md}",
            guide,
        )
        self.assertNotIn("zy-signflow", guide)

    def test_mode_a_b_use_non_overwriting_contract_paths_and_no_publish_probe(self):
        mode_a = (ROOT / "built-in-skills" / "mode-a-greenfield.md").read_text(
            encoding="utf-8"
        )
        mode_b = (ROOT / "built-in-skills" / "mode-b-brownfield.md").read_text(
            encoding="utf-8"
        )
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("execution_contracts/<safe-workflow-name>.json", skill)
        for document in (mode_a, mode_b):
            self.assertIn(
                "execution_contracts/<safe-workflow-name>.json",
                document,
            )
            self.assertNotIn("execution_contract.json", document)
            self.assertIn("命令与顺序见 SKILL.md §7", document)
            self.assertIn("hap-flow-exec", document)
        self.assertIn("--source-design", mode_b)

    def test_node_capabilities_lists_all_verify_platform_type_ids(self):
        guide = (
            ROOT / "references" / "platform" / "node-capabilities.md"
        ).read_text(encoding="utf-8")
        names = (SCRIPTS / "type_names.py").read_text(encoding="utf-8")
        match = re.search(
            r"VALID_TYPE_IDS\s*=\s*\{(.*?)\}",
            names,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        type_ids = {
            int(value)
            for value in re.findall(r"\b\d+\b", match.group(1))
        }
        self.assertEqual(39, len(type_ids))
        for type_id in type_ids:
            self.assertIn(f"| {type_id} |", guide)
        self.assertNotIn("references/manual.md", guide)
        self.assertNotIn("workflow-nodes-complete-guide", guide)

    def test_staged_whitespace_command_rejects_staged_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(
                ["git", "-C", repo, "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", repo, "config", "user.name", "Test"],
                check=True,
            )
            path = repo / "sample.txt"
            path.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "-C", repo, "add", "sample.txt"], check=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "-qm", "baseline"],
                check=True,
            )
            path.write_text("trailing space   \n", encoding="utf-8")
            subprocess.run(["git", "-C", repo, "add", "sample.txt"], check=True)

            completed = subprocess.run(
                ["git", "-C", repo, "diff", "--cached", "--check"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("trailing whitespace", completed.stdout)


class SecretScanBehaviorTests(unittest.TestCase):
    def _plant_all_patterns(self, directory: Path) -> None:
        (directory / "leak.md").write_text(
            "\n".join(
                [
                    "openai " + "sk-" + "A" * 24,
                    "oauth " + "gho_" + "B" * 24,
                    "personal " + "ghp_" + "C" * 24,
                    "fine " + "github_pat_" + "D" * 24,
                    "jwt eyJ" + "a" * 11 + "." + "b" * 11 + "." + "c" * 11,
                    "auth Bearer " + "e" * 24,
                    "HAP-Appkey: " + "f" * 12,
                    "HAP-Sign: " + "g" * 12,
                    "home /Users/" + "someone" + "/src",
                ]
            ),
            encoding="utf-8",
        )

    def test_worktree_scan_flags_every_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._plant_all_patterns(root)
            with mock.patch.object(scan_secrets, "ROOT", root):
                hits = scan_secrets.scan_worktree()

        self.assertEqual(
            {
                "OpenAI key",
                "GitHub OAuth token",
                "GitHub personal token",
                "GitHub fine-grained token",
                "JWT",
                "Bearer token",
                "HAP Appkey/Sign pair",
                "hardcoded user path",
            },
            {label for _, label in hits},
        )

    def test_user_path_rule_is_scoped_away_from_history_mode(self):
        relative = "notes.md"
        text = "home /Users/" + "someone" + "/src"

        self.assertEqual([], scan_secrets.scan_text(relative, text))
        self.assertEqual(
            [(relative, "hardcoded user path")],
            scan_secrets.scan_text(relative, text, check_user_paths=True),
        )

    def test_staged_scan_reads_index_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", root], check=True)
            (root / "leak.txt").write_text("sk-" + "A" * 24, encoding="utf-8")
            subprocess.run(["git", "-C", root, "add", "leak.txt"], check=True)
            with mock.patch.object(scan_secrets, "ROOT", root):
                hits = scan_secrets.scan_staged()

        self.assertEqual([("leak.txt", "OpenAI key")], hits)


if __name__ == "__main__":
    unittest.main()
