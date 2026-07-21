import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))

import design_ir_validator  # noqa: E402
import design_spec_linter  # noqa: E402


def load_lock():
    return json.loads(
        (FIXTURES / "valid_execution_lock.json").read_text(encoding="utf-8")
    )


class DesignIrTests(unittest.TestCase):
    def test_valid_ir_passes(self):
        self.assertEqual([], design_ir_validator.validate_design_ir(load_lock()))

    def test_untraced_requirement_fails(self):
        lock = load_lock()
        lock["design_ir"]["requirements"].append(
            {
                "id": "REQ-UNTRACED",
                "statement": "未落地需求",
                "priority": "must",
                "acceptance_criteria": ["可观察"],
            }
        )
        issues = design_ir_validator.validate_design_ir(lock)
        self.assertTrue(
            any("REQ-UNTRACED" in issue["detail"] for issue in issues)
        )

    def test_nonterminal_state_requires_outgoing_transition(self):
        lock = load_lock()
        lock["design_ir"]["state_machines"][0]["states"].append(
            {"key": "blocked", "label": "阻塞", "terminal": False}
        )
        issues = design_ir_validator.validate_design_ir(lock)
        self.assertTrue(
            any("没有任何出向转换" in issue["detail"] for issue in issues)
        )

    def test_traceability_requires_existing_data_and_behavior_refs(self):
        lock = load_lock()
        lock["design_ir"]["traceability"][0]["artifacts"] = [
            {"kind": "entity", "ref": "ENT-NOT-EXIST"}
        ]
        issues = design_ir_validator.validate_design_ir(lock)
        self.assertTrue(
            any("artifact 引用不存在" in issue["detail"] for issue in issues)
        )
        self.assertTrue(
            any("缺少行为落点" in issue["detail"] for issue in issues)
        )

    def test_state_permissions_views_and_buttons_reference_real_objects(self):
        lock = load_lock()
        lock["design_ir"]["state_machines"][0]["state_field_id"] = "missing"
        lock["design_ir"]["permissions"][0]["table"] = "不存在表"
        lock["design_ir"]["views"][0]["fields"] = ["不存在字段"]
        lock["design_ir"]["buttons"][0]["workflow"] = "不存在流程"
        issues = design_ir_validator.validate_design_ir(lock)
        details = [issue["detail"] for issue in issues]
        self.assertTrue(any("状态字段" in detail for detail in details))
        self.assertTrue(any("权限引用不存在" in detail for detail in details))
        self.assertTrue(any("视图引用不存在" in detail for detail in details))
        self.assertTrue(any("按钮引用不存在" in detail for detail in details))

    def test_design_spec_requires_sections_and_requirement_ids(self):
        lock = load_lock()
        issues = design_spec_linter.lint_spec("# 结论\n", lock)
        codes = {issue["code"] for issue in issues}
        self.assertIn("SPEC_SECTION_MISSING", codes)
        self.assertIn("SPEC_REQUIREMENT_UNTRACED", codes)

    def test_complete_design_spec_passes(self):
        lock = copy.deepcopy(load_lock())
        markdown = """
# 结论
REQ-001 已覆盖。
## 客户需求追踪
## 角色与权限
## 实体与字段
## 状态机
## 工作流
## 视图与按钮
## 异常与恢复
## 门控结果
"""
        self.assertEqual([], design_spec_linter.lint_spec(markdown, lock))


if __name__ == "__main__":
    unittest.main()
