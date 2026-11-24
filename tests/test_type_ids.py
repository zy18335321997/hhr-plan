"""The verified TYPE_NAMES map is the only node-type map."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import type_names  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_platform = _load("verify_platform_types_test", "verify-platform.py")
extract_project = _load("extract_project_types_test", "extract-project.py")
generate_node_data = _load("generate_node_data_types_test", "generate_node_data.py")


def _capability_names():
    names = {}
    text = (ROOT / "references" / "platform" / "node-capabilities.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0].isdigit():
            continue
        names[int(cells[0])] = cells[1]
    return names


def _compact(label: str) -> str:
    return (
        label.replace(" ", "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("，", ",")
        .replace("；", ";")
    )


class TypeMapTests(unittest.TestCase):
    def test_generate_node_data_uses_verify_platform_names(self):
        self.assertIs(verify_platform.TYPE_NAMES, type_names.TYPE_NAMES)
        self.assertEqual(generate_node_data.NODE_TYPE_NAME, verify_platform.TYPE_NAMES)

    def test_node_capabilities_matches_type_names(self):
        documented = _capability_names()
        self.assertEqual(set(documented), set(verify_platform.TYPE_NAMES))
        for type_id, code_name in verify_platform.TYPE_NAMES.items():
            doc_name = _compact(documented[type_id]).strip("()")
            code = _compact(code_name).strip("()")
            self.assertTrue(
                code in doc_name or doc_name in code,
                f"type_id {type_id}: {code_name!r} vs {documented[type_id]!r}",
            )

    def test_extract_roles_follow_the_same_names(self):
        names = verify_platform.TYPE_NAMES
        self.assertEqual(extract_project.DATA_OPERATION_TYPE, 6)
        self.assertIn("数据操作", names[extract_project.DATA_OPERATION_TYPE])
        self.assertEqual(extract_project.READ_NODE_TYPES, {7, 13})
        self.assertIn("查询", names[7])
        self.assertIn("获取多条", names[13])
        self.assertEqual(extract_project.APPROVAL_NODE_TYPES, {4, 26})
        self.assertIn("审批", names[4])
        self.assertIn("审批", names[26])
        self.assertEqual(extract_project.DETAIL_NODE_TYPES, {6})
        self.assertIn("分支条件", names[2])
        self.assertIn("填写", names[3])
        self.assertIn("运算", names[9])
        self.assertIn("延时", names[12])
        self.assertNotIn(2, extract_project.DETAIL_NODE_TYPES)
        self.assertNotIn(3, extract_project.DETAIL_NODE_TYPES)

    def test_field_detail_targets_data_operations_only(self):
        self.assertFalse(extract_project.is_field_detail_node(
            {"typeId": 2, "name": "新增记录"}))
        self.assertFalse(extract_project.is_field_detail_node(
            {"typeId": 3, "name": "更新记录"}))
        self.assertTrue(extract_project.is_field_detail_node(
            {"typeId": 6, "name": "新增记录"}))
        self.assertEqual(
            extract_project.detail_type_label({"typeId": 6, "name": "新增记录", "actionId": 1}),
            "新增记录",
        )

    def test_summarize_does_not_count_messages_as_approvals(self):
        summary = extract_project.summarize_flow_nodes({
            "a": {"typeId": 10, "name": "短信", "appName": "通知"},
            "b": {"typeId": 11, "name": "邮件", "appName": "通知"},
            "c": {"typeId": 26, "name": "发起审批"},
            "d": {"typeId": 7, "name": "查询", "appName": "订单"},
            "e": {"typeId": 13, "name": "获取多条", "appName": "明细"},
            "f": {"typeId": 6, "name": "新增记录", "sourceEntityName": "订单"},
            "_name": "metadata",
        })
        self.assertEqual(summary["approval_count"], 1)
        self.assertEqual(summary["node_count"], 6)
        self.assertIn("订单", summary["reads"])
        self.assertIn("明细", summary["reads"])
        self.assertIn("订单", summary["writes"])

    def test_generate_node_data_delay_and_api_use_verified_ids(self):
        delay = generate_node_data._summarize_node(
            {"typeId": 12, "name": "等待", "executeTime": "1h"})
        calculation = generate_node_data._summarize_node(
            {"typeId": 9, "name": "运算", "executeTime": "1h"})
        api = generate_node_data._summarize_node(
            {"typeId": 8, "name": "请求", "method": "POST", "url": "https://example.com/hook"})
        get_multiple = generate_node_data._summarize_node(
            {"typeId": 13, "name": "获取多条", "method": "POST", "url": "https://example.com/hook"})
        self.assertEqual(delay.get("delay"), "1h")
        self.assertNotIn("delay", calculation)
        self.assertIn("api", api)
        self.assertNotIn("api", get_multiple)


if __name__ == "__main__":
    unittest.main()
