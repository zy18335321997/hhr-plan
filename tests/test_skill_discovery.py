import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "skill_discovery.py"
SPEC = importlib.util.spec_from_file_location("test_skill_discovery_module", MODULE_PATH)
DISCOVERY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DISCOVERY)


class SkillDiscoveryPathTests(unittest.TestCase):
    def setUp(self):
        self.original_skill_dir = DISCOVERY.SKILL_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "skill"
        self.root.mkdir()
        DISCOVERY.SKILL_DIR = self.root

    def tearDown(self):
        DISCOVERY.SKILL_DIR = self.original_skill_dir
        self.temp_dir.cleanup()

    def check(self, value, field="requires"):
        violations = []
        DISCOVERY._check_repo_path("test-mode", field, value, violations)
        return violations

    def test_requires_with_slash_or_known_extension_are_paths(self):
        self.assertEqual("references/file", DISCOVERY._repo_path("references/file"))
        self.assertEqual("input.json", DISCOVERY._repo_path("input.json"))
        self.assertIsNone(DISCOVERY._repo_path("项目上下文输入"))

    def test_path_must_resolve_to_file_inside_skill_root(self):
        references = self.root / "references"
        references.mkdir()
        (references / "valid.md").write_text("ok", encoding="utf-8")
        (references / "directory.md").mkdir()

        self.assertEqual([], self.check("references/valid.md"))
        self.assertTrue(self.check("references/typo.md"))
        self.assertTrue(self.check("references/directory.md"))
        self.assertTrue(self.check("../outside.md"))

    def test_symlink_cannot_escape_skill_root(self):
        outside = Path(self.temp_dir.name) / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "escaped.md"
        os.symlink(outside, link)

        violations = self.check("escaped.md")

        self.assertTrue(violations)
        self.assertIn("escapes skill root", violations[0]["detail"])

    def test_instructions_and_schema_reject_directories_and_typos(self):
        (self.root / "docs.md").mkdir()
        iface = {
            "requires": [],
            "instructions": "docs.md",
            "verification": {"schema": "missing.json"},
        }
        violations = []

        DISCOVERY.validate_descriptor_paths("test-mode", iface, violations)

        self.assertEqual(2, len(violations))
        self.assertTrue(all(item["severity"] == "high" for item in violations))


if __name__ == "__main__":
    unittest.main()
