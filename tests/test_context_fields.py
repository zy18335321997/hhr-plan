"""project_context 字段计算的契约测试。

钉住共享模块 scripts/context_fields.py 以及 extract-project.build_context
对现代提取格式（无 _extracted 布局）的计算与回退。
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# 订单明细的 worksheetId（24 位小写 hex，供 dataSource 解析测试）
ORDER_ITEM_ID = "65e80a207059c43ba97f728f"


def _load_extract_project():
    spec = importlib.util.spec_from_file_location(
        "extract_project_context_fields", ROOT / "scripts" / "extract-project.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SharedModuleModernFields(unittest.TestCase):
    """scripts/context_fields.py accepts MCP-style fields (English type names)."""

    def setUp(self):
        import context_fields
        self.cf = context_fields

    def test_relation_data_source_hex_resolves_to_worksheet_name(self):
        worksheets = [
            {"name": "订单", "fields": [
                {"name": "明细", "type": "Relation", "dataSource": ORDER_ITEM_ID},
            ]},
            {"name": "订单明细", "worksheet_id": ORDER_ITEM_ID, "fields": []},
        ]
        graph, reverse = self.cf.compute_relation_graph(worksheets)
        self.assertEqual(graph, {"订单": {"订单明细"}})
        self.assertEqual(reverse, {"订单明细": {"订单"}})

    def test_auto_number_prefixes_come_from_field_names(self):
        worksheets = [
            {"name": "订单", "fields": [
                {"name": "订单编号", "type": "AutoNumber"},
            ]},
            {"name": "客户", "fields": [
                {"name": "客户编号", "type": "AutoNumber"},
                {"name": "自动编号", "type": "AutoNumber"},  # platform default, ignored
            ]},
        ]
        self.assertEqual(
            self.cf.auto_number_prefixes_from_field_names(worksheets),
            ["订单", "客户"],
        )
        # MCP output has no advancedSetting.increase -> legacy naming is empty.
        self.assertEqual(
            self.cf.compute_naming(worksheets)["auto_number_prefixes"], [],
        )

    def test_workflow_edges_prefer_trigger_sheet_over_placeholder_worksheet(self):
        # Real nodes.json files often carry a placeholder _sheet ("未分类");
        # the trigger sheet is the trustworthy source-side sheet name.
        node_data = {
            "p1": {"worksheet": "订单", "reads": [], "writes": ["客户"]},
            "p2": {"worksheet": "", "trigger_sheet": "收款登记",
                   "reads": ["客户"], "writes": []},
            "p3": {"worksheet": "订单", "reads": ["订单"], "writes": [""]},
            "p4": {"worksheet": "未分类", "trigger_sheet": "合同",
                   "reads": ["客户"], "writes": []},
            # No resolvable trigger sheet -> placeholder sources are dropped.
            "p5": {"worksheet": "未分类", "trigger_sheet": "",
                   "reads": ["成员"], "writes": []},
        }
        graph, reverse = self.cf.compute_workflow_edges(node_data)
        # Self edges and empty targets are skipped; the placeholder never wins.
        self.assertEqual(graph, {"订单": {"客户"}, "收款登记": {"客户"}, "合同": {"客户"}})
        self.assertEqual(reverse, {"客户": {"订单", "收款登记", "合同"}})
        self.assertNotIn("未分类", graph)
        self.assertNotIn("成员", reverse)


class ExtractProjectBuildContext(unittest.TestCase):
    """extract-project.build_context computes derived fields, not empty literals."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_extract_project()

    def _modern_ws_map(self):
        return {
            "id-order": {"name": "订单", "fields": [
                {"id": "f1", "name": "客户", "type": "Relation",
                 "required": True, "isTitle": False},
                {"id": "f2", "name": "订单编号", "type": "AutoNumber",
                 "required": False, "isTitle": False},
            ]},
            "id-customer": {"name": "客户", "fields": [
                {"id": "f3", "name": "客户编号", "type": "AutoNumber",
                 "required": False, "isTitle": True},
            ]},
            "id-payment": {"name": "收款登记", "fields": [
                {"id": "f4", "name": "金额", "type": "Number",
                 "required": False, "isTitle": False},
            ]},
            "id-plan": {"name": "佣金方案", "fields": [
                {"id": "f5", "name": "方案名称", "type": "Text",
                 "required": False, "isTitle": True},
            ]},
        }

    def test_derived_fields_computed_from_workflow_edges_and_field_names(self):
        node_data = {
            "p1": {"worksheet": "未分类", "trigger_sheet": "订单",
                   "trigger": "工作表事件", "reads": [], "writes": ["客户"]},
            "p2": {"worksheet": "未分类", "trigger_sheet": "收款登记",
                   "trigger": "工作表事件", "reads": ["客户"], "writes": []},
            "p3": {"worksheet": "未分类", "trigger_sheet": "佣金方案",
                   "trigger": "工作表事件", "reads": [], "writes": ["客户"]},
        }
        ctx = self.mod.build_context(
            "proj", self._modern_ws_map(), [{"trigger": "工作表事件"}], node_data,
        )

        self.assertEqual(set(ctx), {"project", "worksheets", "relation_graph",
                                    "hub_tables", "naming", "workflows", "patterns"})
        self.assertEqual(
            {src: set(targets) for src, targets in ctx["relation_graph"].items()},
            {"订单": {"客户"}, "收款登记": {"客户"}, "佣金方案": {"客户"}},
        )
        self.assertEqual([hub["name"] for hub in ctx["hub_tables"]], ["客户"])
        self.assertEqual(ctx["hub_tables"][0]["ref_count"], 3)
        self.assertEqual(
            set(ctx["hub_tables"][0]["referenced_by"]),
            {"订单", "收款登记", "佣金方案"},
        )
        self.assertEqual(ctx["naming"]["auto_number_prefixes"], ["订单", "客户"])
        self.assertEqual(ctx["naming"]["param_name_sample"], [])
        self.assertEqual(ctx["patterns"], {})

    def test_field_edges_take_priority_over_workflow_edges(self):
        # Only 24-hex dataSource ids resolve to worksheet names (legacy rule).
        a, b, c = ("65e80a207059c43ba97f72a0",
                   "65e80a207059c43ba97f72a1",
                   "65e80a207059c43ba97f72a2")
        ws_map = {
            a: {"name": "A", "fields": [
                {"name": "B", "type": "Relation", "dataSource": b},
            ]},
            b: {"name": "B", "fields": []},
            c: {"name": "C", "fields": []},
        }
        node_data = {"p1": {"worksheet": "C", "reads": [], "writes": ["B"]}}
        ctx = self.mod.build_context("proj", ws_map, [], node_data)
        # Field-based edges exist -> workflow edges must not be mixed in.
        self.assertEqual(ctx["relation_graph"], {"A": ["B"]})
        self.assertEqual(ctx["hub_tables"], [])

    def test_empty_input_returns_empty_defaults_with_stable_shape(self):
        ctx = self.mod.build_context("proj", {}, [])
        self.assertEqual(ctx["relation_graph"], {})
        self.assertEqual(ctx["hub_tables"], [])
        self.assertEqual(ctx["naming"], {
            "auto_number_prefixes": [],
            "param_name_sample": [],
        })
        self.assertEqual(ctx["patterns"], {})


if __name__ == "__main__":
    unittest.main()
