"""Readable create/update field mappings. Fixtures only; no network and no secrets."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import field_mappings  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "workflow-structure"
SCREENSHOT_LINES = [
    "更新对象：当前流程中的节点对象 工作表事件触发 / 工作表 EmpAwards_员工奖项",
    "将字段 [关联表] EmpBasicInfo_员工基本信息 设为 查询工作表 / 工作表 EmpBasicInfo_员工基本信息",
    "将字段 [文本] MainID 设为 查询工作表 / 员工工号",
]


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _extract_project():
    spec = importlib.util.spec_from_file_location(
        "extract_project_field_mappings", ROOT / "scripts" / "extract-project.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool(argument="workflow_id"):
    return {
        "name": "get_workflow_structure",
        "inputSchema": {
            "type": "object",
            "properties": {argument: {"type": "string"}},
            "required": [argument],
        },
    }


class ReadableMappingTests(unittest.TestCase):
    def setUp(self):
        fixture = _load("update-record-detail.json")
        self.flow_node = fixture["flow_node"]
        self.detail = fixture["node_detail"]

    def test_token_and_relation_match_the_editor_lines(self):
        mapping = field_mappings.resolve_field_mappings(self.flow_node, self.detail)
        self.assertEqual(mapping["lines"], SCREENSHOT_LINES)
        relation, text = mapping["assignments"]
        self.assertEqual(relation["field_name"], "EmpBasicInfo_员工基本信息")
        self.assertEqual(relation["field_type"], 29)
        self.assertEqual(relation["field_type_label"], "关联表")
        self.assertEqual(relation["set_to"]["kind"], "node")
        self.assertEqual(relation["set_to"]["node_name"], "查询工作表")
        self.assertEqual(relation["set_to"]["worksheet"], "EmpBasicInfo_员工基本信息")
        self.assertEqual(relation["raw"]["fieldId"], "relBasic")
        self.assertEqual(relation["raw"]["nodeId"], "nodeQuery")
        self.assertEqual(text["set_to_display"], "查询工作表 / 员工工号")
        self.assertEqual(text["set_to"]["node_name"], "查询工作表")
        self.assertEqual(text["set_to"]["field_name"], "员工工号")
        self.assertEqual(text["set_to"]["node_id"], "nodeQuery")
        self.assertEqual(text["set_to"]["control_id"], "ctrlEmpNo")
        self.assertEqual(text["raw"]["fieldValue"], "$nodeQuery-ctrlEmpNo$")
        self.assertEqual(text["field_name"], "MainID")
        self.assertEqual(text["field_type_label"], "文本")
        self.assertNotIn("unresolved", text)
        self.assertNotIn("unresolved", relation)
        self.assertEqual(mapping["update_object"]["scope"], "当前流程中的节点对象")
        self.assertEqual(mapping["update_object"]["node_name"], "工作表事件触发")
        self.assertEqual(mapping["update_object"]["worksheet"], "EmpAwards_员工奖项")

    def test_flow_node_alone_keeps_the_token_and_asks_for_detail(self):
        mapping = field_mappings.resolve_field_mappings(self.flow_node)
        text = mapping["assignments"][1]
        self.assertEqual(text["set_to_display"], "$nodeQuery-ctrlEmpNo$")
        self.assertTrue(text["unresolved"])
        relation = mapping["assignments"][0]
        self.assertEqual(relation["field_name"], "relBasic")
        self.assertTrue(relation["unresolved"])
        self.assertTrue(field_mappings.needs_node_detail(self.flow_node))
        merged = dict(self.flow_node)
        field_mappings.merge_detail_into(merged, {"data": self.detail})
        self.assertFalse(field_mappings.needs_node_detail(merged))

    def test_formula_map_name_plus_flow_node_list_still_resolves(self):
        detail = {
            "formulaMap": {"nodeQuery-ctrlEmpNo": {"name": "员工工号", "type": 2}},
            "controls": self.detail["controls"],
            "flowNodeList": self.detail["flowNodeList"],
            "selectNodeObj": self.detail["selectNodeObj"],
        }
        mapping = field_mappings.resolve_field_mappings(self.flow_node, detail)
        self.assertEqual(mapping["assignments"][1]["set_to_display"], "查询工作表 / 员工工号")

    def test_dollar_wrapped_formula_key_resolves(self):
        detail = json.loads(json.dumps(self.detail))
        detail["formulaMap"] = {
            "$nodeQuery-ctrlEmpNo$": detail["formulaMap"]["nodeQuery-ctrlEmpNo"],
        }
        mapping = field_mappings.resolve_field_mappings(self.flow_node, detail)
        self.assertEqual(mapping["assignments"][1]["set_to_display"], "查询工作表 / 员工工号")

    def test_literal_value_does_not_need_node_detail(self):
        node = {
            "typeId": 6,
            "name": "更新记录",
            "sourceEntityName": "订单",
            "fields": [{"fieldId": "f9", "fieldValue": "done"}],
        }
        self.assertFalse(field_mappings.needs_node_detail(node))
        mapping = field_mappings.resolve_field_mappings(node)
        self.assertEqual(mapping["assignments"][0]["set_to_display"], "done")
        self.assertEqual(mapping["assignments"][0]["raw"]["fieldId"], "f9")

    def test_other_node_types_with_the_same_field_rows_are_included(self):
        node = {
            "typeId": 32,
            "name": "插件回写",
            "fields": [{"fieldId": "status", "fieldName": "状态", "fieldValue": "ok"}],
        }
        mapping = field_mappings.resolve_field_mappings(node)
        self.assertEqual(mapping["lines"], ["将字段 状态 设为 ok"])
        self.assertFalse(field_mappings.needs_node_detail(node))


class PersistMappingTests(unittest.TestCase):
    def test_get_node_detail_response_is_stored_as_editor_lines(self):
        extract_project = _extract_project()
        fixture = _load("update-record-detail.json")
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("auth.get_auth_headers", return_value={"Authorization": "synthetic"}), \
             mock.patch.object(
                 extract_project.platform_router,
                 "fetch_json",
                 return_value={"data": fixture["node_detail"]},
             ) as fetch:
            nodes_path = Path(tmp) / "nodes.json"
            nodes_path.write_text(json.dumps({
                "proc-awards": {
                    "_name": "员工奖项",
                    "nodeUpdate": fixture["flow_node"],
                },
            }, ensure_ascii=False), encoding="utf-8")
            extract_project.extract_node_detail_configs(
                "https://app.example", {}, tmp,
            )
            saved = json.loads((Path(tmp) / "_node_configs.json").read_text(encoding="utf-8"))
        self.assertIn("getNodeDetail", fetch.call_args.args[1])
        row = saved["proc-awards"][0]
        self.assertEqual(row["field_mappings"]["lines"], SCREENSHOT_LINES)
        self.assertEqual(row["fields"][1]["fieldValue"], "$nodeQuery-ctrlEmpNo$")
        self.assertEqual(row["formulaMap"]["nodeQuery-ctrlEmpNo"]["name"], "员工工号")
        self.assertEqual(row["controls"][1]["controlName"], "MainID")

    def test_structure_fetch_still_walks_nested_flows_and_resolves_fields(self):
        extract_project = _extract_project()
        fixture = _load("update-record-detail.json")
        root = _load("main.json")
        update = next(node for node in root["data"]["nodes"] if node["nodeId"] == "node-update")
        update["name"] = "更新记录"
        update["config"] = {
            "selectNodeId": "nodeTrigger",
            "selectNodeName": "工作表事件触发",
            "appName": "EmpAwards_员工奖项",
            "appTypeName": "工作表",
            "fields": fixture["flow_node"]["fields"],
        }
        payloads = {
            "proc-root": root,
            "proc-approval-inner": _load("approval-inner.json"),
            "proc-sub-inner": _load("subprocess-inner.json"),
        }
        seen = []

        def call_tool(url, name, args):
            seen.append(args["workflow_id"])
            return payloads[args["workflow_id"]]

        def fetch_json(origin, path, domain=None, method="GET", payload=None):
            self.assertIn("getNodeDetail", path)
            self.assertNotIn("/flowNode/get?", path)
            self.assertIn("processId=proc-root", path)
            self.assertIn("nodeId=node-update", path)
            self.assertIn("flowNodeType=6", path)
            return {"data": fixture["node_detail"]}

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(extract_project, "init_and_list_tools", return_value=[_tool()]), \
             mock.patch.object(extract_project, "call_tool", side_effect=call_tool), \
             mock.patch.object(extract_project, "extract_node_detail_configs") as detail, \
             mock.patch.object(extract_project.platform_router, "fetch_json", side_effect=fetch_json):
            rows = extract_project.collect_workflow_nodes(
                tmp,
                [{"id": "proc-root", "name": "员工奖项"}],
                mcp_url="https://mcp.example/mcp",
                base_url="https://app.example",
            )
            detail.assert_not_called()
            saved = json.loads((Path(tmp) / "_node_configs.json").read_text(encoding="utf-8"))
        self.assertEqual(seen, ["proc-root", "proc-approval-inner", "proc-sub-inner"])
        self.assertIn("proc-approval-inner", rows)
        self.assertIn("proc-sub-inner", rows)
        configs = {row["node_id"]: row for row in saved["proc-root"]}
        self.assertEqual(configs["node-update"]["field_mappings"]["lines"], SCREENSHOT_LINES)
        self.assertEqual(
            configs["node-update"]["field_detail"]["formulaMap"]["nodeQuery-ctrlEmpNo"]["nodeName"],
            "查询工作表",
        )
        readable = rows["proc-root"]["crud_field_mappings"][0]["readable"]
        self.assertIn("查询工作表 / 员工工号", readable[-1])
        self.assertEqual(
            rows["proc-root"]["crud_field_mappings"][0]["raw"][1],
            "textMain:$nodeQuery-ctrlEmpNo$",
        )


if __name__ == "__main__":
    unittest.main()
