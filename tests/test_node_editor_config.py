"""Readable editor config for query, branch, trigger, and the other real nodes.

Fixtures are synthetic. No network, hosts, cookies, or live tenant ids.
"""

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
import node_editor_config  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "workflow-structure"
QUERY_LINES = [
    "获取方式：查询工作表",
    "选择工作表：EmpBasicInfo_员工基本信息",
    "筛选条件：[数值] 员工ID 等于 工作表事件触发 / 员工ID；条件异常时忽略：否；值为空时忽略：否",
    "排序规则：无",
    "忽略排序规则，随机获取：否",
    "未获取到数据时：继续执行",
]


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _extract_project():
    spec = importlib.util.spec_from_file_location(
        "extract_project_editor_config", ROOT / "scripts" / "extract-project.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryEditorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _load("editor-config.json")

    def test_query_detail_matches_the_editor(self):
        editor = node_editor_config.resolve_editor_config(
            self.fixture["query_node"], self.fixture["query_detail"],
        )
        self.assertEqual(editor["lines"], QUERY_LINES)
        self.assertEqual(editor["raw"]["actionId"], 406)
        self.assertEqual(editor["raw"]["executeType"], 2)
        self.assertEqual(editor["raw"]["findFields"], [])
        self.assertEqual(editor["raw"]["random"], False)
        condition = editor["raw"]["conditions"][0][0]
        self.assertEqual(condition["filedId"], "ctrlEmpId")
        self.assertEqual(condition["conditionValues"][0]["controlId"], "ctrlTriggerEmp")
        self.assertEqual(condition["conditionValues"][0]["nodeId"], "nodeTrigger")
        self.assertNotIn("unresolved", editor)
        self.assertEqual(editor["gaps"], [])

    def test_empty_operate_condition_asks_for_detail_then_stops(self):
        node = self.fixture["query_node"]
        self.assertTrue(node_editor_config.needs_editor_detail(node))
        pending = node_editor_config.resolve_editor_config(node)
        self.assertIn("结构数据未包含筛选条件", pending["lines"][2])
        merged = dict(node)
        node_editor_config.merge_detail_into(merged, {"data": self.fixture["query_detail"]})
        self.assertFalse(node_editor_config.needs_editor_detail(merged))
        self.assertEqual(
            node_editor_config.resolve_editor_config(merged)["lines"],
            QUERY_LINES,
        )

    def test_formula_token_in_the_filter_uses_formula_map(self):
        detail = json.loads(json.dumps(self.fixture["query_detail"]))
        detail["conditions"][0][0]["conditionValues"] = [{"value": "$nodeTrigger-ctrlTriggerEmp$"}]
        editor = node_editor_config.resolve_editor_config(self.fixture["query_node"], detail)
        self.assertIn("工作表事件触发 / 员工ID", editor["lines"][2])
        self.assertEqual(editor["raw"]["tokens"], ["$nodeTrigger-ctrlTriggerEmp$"])

    def test_or_groups_and_checked_ignore_flags(self):
        node = dict(self.fixture["query_node"])
        node["filters"] = self.fixture["query_or_filters"]
        node["operateCondition"] = []
        editor = node_editor_config.resolve_editor_config(node, detail_seen=True)
        text = editor["lines"][2]
        self.assertIn("） 或 （", text)
        self.assertIn("[数值] 员工ID 等于 工作表事件触发 / 员工ID；条件异常时忽略：是；值为空时忽略：是", text)
        self.assertIn("[文本] 姓名 包含 张", text)
        self.assertFalse(node_editor_config.needs_editor_detail(node))

    def test_and_group_joins_with_且(self):
        node = dict(self.fixture["query_node"])
        node["conditions"] = [[
            self.fixture["query_detail"]["conditions"][0][0],
            {
                "filedId": "ctrlName",
                "filedTypeId": 2,
                "filedValue": "姓名",
                "conditionId": "3",
                "conditionValues": [{"value": "张"}],
            },
        ]]
        editor = node_editor_config.resolve_editor_config(node, detail_seen=True)
        self.assertIn(" 且 ", editor["lines"][2])

    def test_detail_with_no_filter_is_explicitly_none(self):
        editor = node_editor_config.resolve_editor_config(
            self.fixture["query_node"],
            {"executeType": 2, "random": False, "sorts": [], "conditions": [], "findFields": []},
        )
        self.assertIn("筛选条件：无", editor["lines"])
        self.assertEqual(editor["gaps"], [])


class BranchAndTriggerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _load("editor-config.json")

    def test_branch_arm_renders_the_condition(self):
        editor = node_editor_config.resolve_editor_config(self.fixture["branch_arm"])
        self.assertEqual(
            editor["lines"],
            ["分支条件：[数值] 员工ID 等于 工作表事件触发 / 员工ID；条件异常时忽略：否；值为空时忽略：是"],
        )
        self.assertFalse(node_editor_config.needs_editor_detail(self.fixture["branch_arm"]))
        self.assertEqual(editor["raw"]["conditions"][0][0]["filedId"], "ctrlEmpId")

    def test_empty_arm_that_ends_is_the_default_path(self):
        arm = self.fixture["branch_else"]
        self.assertFalse(node_editor_config.needs_editor_detail(arm))
        editor = node_editor_config.resolve_editor_config(arm)
        self.assertTrue(editor["default_branch"])
        self.assertEqual(editor["lines"], ["默认分支（其他）：条件为空，此分支在此结束"])
        self.assertEqual(editor["gaps"], [])
        self.assertEqual(editor["raw"]["operateCondition"], [])

    def test_empty_arm_that_continues_is_fetched_once(self):
        arm = self.fixture["branch_open"]
        flow = {"nodeNext": {"nodeId": "nodeNext"}}
        self.assertTrue(node_editor_config.needs_editor_detail(arm, flow))
        merged = dict(arm)
        node_editor_config.merge_detail_into(merged, {"data": {"conditions": [], "operateCondition": []}})
        self.assertFalse(node_editor_config.needs_editor_detail(merged, flow))
        editor = node_editor_config.resolve_editor_config(merged, flow_nodes=flow, detail_seen=True)
        self.assertEqual(editor["lines"], ["默认分支（其他）：条件为空"])
        self.assertTrue(editor["default_branch"])

    def test_gateway_names_the_mode(self):
        editor = node_editor_config.resolve_editor_config({
            "typeId": 1,
            "name": "分支",
            "gatewayType": 2,
            "flowIds": ["armMatch", "armElse"],
        })
        self.assertEqual(editor["lines"][0], "分支方式：唯一分支（只走第一条满足的路径）")
        self.assertEqual(editor["lines"][1], "分支数：2")

    def test_trigger_renders_worksheet_event_fields_and_entry_condition(self):
        editor = node_editor_config.resolve_editor_config(self.fixture["trigger_node"])
        self.assertEqual(editor["lines"], [
            "触发工作表：EmpAwards_员工奖项",
            "触发事件：仅更新记录时",
            "触发字段：状态",
            "进入条件：[单选] 状态 等于 已出库",
        ])
        self.assertEqual(editor["raw"]["triggerId"], "4")
        self.assertEqual(editor["raw"]["assignFieldIds"], ["ctrlStatus"])
        self.assertFalse(node_editor_config.needs_editor_detail(self.fixture["trigger_node"]))

    def test_legacy_start_without_trigger_id_asks_for_detail(self):
        node = {"typeId": 0, "name": "开始", "appName": "采购单", "nodeType": "type_0"}
        self.assertTrue(node_editor_config.needs_editor_detail(node))
        merged = dict(node)
        node_editor_config.merge_detail_into(merged, {"data": {
            "triggerId": "1",
            "appName": "采购单",
            "assignFieldIds": [],
            "operateCondition": [],
        }})
        self.assertFalse(node_editor_config.needs_editor_detail(merged))
        lines = node_editor_config.resolve_editor_config(merged)["lines"]
        self.assertIn("触发工作表：采购单", lines)
        self.assertIn("触发事件：仅新增记录时", lines)
        self.assertIn("触发字段：不限", lines)
        self.assertIn("进入条件：无（全部记录进入）", lines)


class OtherNodeTests(unittest.TestCase):
    def test_update_record_lines_stay_on_field_mappings_and_editor_config(self):
        fixture = _load("update-record-detail.json")
        mapping = field_mappings.resolve_field_mappings(fixture["flow_node"], fixture["node_detail"])
        editor = node_editor_config.resolve_editor_config(fixture["flow_node"], fixture["node_detail"])
        self.assertEqual(mapping["lines"], [
            "更新对象：当前流程中的节点对象 工作表事件触发 / 工作表 EmpAwards_员工奖项",
            "将字段 [关联表] EmpBasicInfo_员工基本信息 设为 查询工作表 / 工作表 EmpBasicInfo_员工基本信息",
            "将字段 [文本] MainID 设为 查询工作表 / 员工工号",
        ])
        for line in mapping["lines"]:
            self.assertIn(line, editor["lines"])
        self.assertEqual(editor["raw"]["fields"][1]["fieldValue"], "$nodeQuery-ctrlEmpNo$")

    def test_literal_update_does_not_need_another_detail(self):
        node = {
            "typeId": 6,
            "actionId": 2,
            "name": "更新记录",
            "sourceEntityName": "订单",
            "fields": [{"fieldId": "f9", "fieldName": "状态", "fieldValue": "done"}],
        }
        self.assertFalse(node_editor_config.needs_editor_detail(node))
        self.assertFalse(field_mappings.needs_node_detail(node))

    def test_helpers_are_marked_and_not_fetched(self):
        system = {"typeId": 100, "name": "系统"}
        audit = {"typeId": 13, "actionId": 405, "name": "人工获取"}
        for node in (system, audit):
            self.assertTrue(node_editor_config.is_helper_node(node))
            self.assertFalse(node_editor_config.needs_editor_detail(node))
            editor = node_editor_config.resolve_editor_config(node)
            self.assertTrue(editor["helper"])
            self.assertTrue(editor["lines"][0].startswith("非业务节点："))
        self.assertIn("405", node_editor_config.resolve_editor_config(audit)["lines"][0])

    def test_delay_and_code_record_a_gap_when_the_api_returns_nothing(self):
        delay = node_editor_config.resolve_editor_config(
            {"typeId": 12, "name": "等待"}, detail_seen=True,
        )
        code = node_editor_config.resolve_editor_config(
            {"typeId": 14, "name": "代码块", "actionId": 102}, detail_seen=True,
        )
        self.assertEqual(delay["gaps"][0]["field"], "executeTime")
        self.assertIn("延时时长", delay["lines"][-1])
        self.assertEqual(code["gaps"][0]["field"], "code")
        self.assertIn("代码块正文", code["lines"][-1])
        self.assertFalse(node_editor_config.needs_editor_detail({"typeId": 12, "_editorDetailRead": True}))

    def test_webhook_renders_the_request_it_already_has(self):
        editor = node_editor_config.resolve_editor_config({
            "typeId": 8,
            "name": "回调",
            "method": "POST",
            "url": "https://example.com/hook",
        })
        self.assertIn("请求方法：POST", editor["lines"])
        self.assertIn("请求地址：https://example.com/hook", editor["lines"])
        self.assertEqual(editor["gaps"], [])
        self.assertFalse(node_editor_config.needs_editor_detail({
            "typeId": 8, "method": "POST", "url": "https://example.com/hook",
        }))


class PersistEditorTests(unittest.TestCase):
    def test_get_node_detail_stores_query_lines_and_skips_helpers(self):
        extract_project = _extract_project()
        fixture = _load("editor-config.json")
        seen = []

        def fetch_json(origin, path, domain=None, method="GET", payload=None):
            seen.append(path)
            self.assertIn("getNodeDetail", path)
            self.assertIn("nodeId=nodeQuery", path)
            self.assertIn("flowNodeType=7", path)
            return {"data": fixture["query_detail"]}

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("auth.get_auth_headers", return_value={"Authorization": "synthetic"}), \
             mock.patch.object(extract_project.platform_router, "fetch_json", side_effect=fetch_json):
            nodes_path = Path(tmp) / "nodes.json"
            nodes_path.write_text(json.dumps({
                "proc-query": {
                    "_name": "查询示例",
                    "nodeQuery": fixture["query_node"],
                    "armElse": fixture["branch_else"],
                    "audit": {"typeId": 13, "actionId": 405, "name": "人工获取"},
                },
            }, ensure_ascii=False), encoding="utf-8")
            extract_project.extract_node_detail_configs("https://app.example", {}, tmp)
            saved = json.loads((Path(tmp) / "_node_configs.json").read_text(encoding="utf-8"))
        self.assertEqual(seen, [seen[0]])
        rows = {row["node_id"]: row for row in saved["proc-query"]}
        self.assertEqual(rows["nodeQuery"]["editor_config"]["lines"], QUERY_LINES)
        self.assertEqual(rows["nodeQuery"]["editor_config"]["raw"]["findFields"], [])
        self.assertNotIn("armElse", rows)
        self.assertNotIn("audit", rows)

    def test_structure_fetch_fills_a_query_and_leaves_the_else_arm(self):
        extract_project = _extract_project()
        fixture = _load("editor-config.json")
        process = {
            "success": True,
            "data": {
                "processId": "proc-editor",
                "name": "查询示例",
                "trigger": {
                    "nodeId": "node-trigger",
                    "triggerType": "worksheet_event",
                    "name": "工作表事件触发",
                    "config": {
                        "worksheetId": "ws-awards",
                        "appName": "EmpAwards_员工奖项",
                        "triggerId": "1",
                    },
                },
                "nodes": [
                    {
                        "nodeId": "node-query",
                        "nodeType": "get_single",
                        "name": "查询工作表",
                        "config": {
                            "typeId": 7,
                            "actionId": 406,
                            "appName": "EmpBasicInfo_员工基本信息",
                            "executeType": 2,
                            "random": False,
                            "findFields": [],
                            "sorts": [],
                            "operateCondition": [],
                        },
                    },
                    {
                        "nodeId": "node-else",
                        "nodeType": "branch_item",
                        "name": "其他",
                        "config": {"typeId": 2, "operateCondition": [], "nextId": ""},
                    },
                    {
                        "nodeId": "node-update",
                        "nodeType": "update_record",
                        "name": "更新记录",
                        "config": {
                            "typeId": 6,
                            "actionId": 2,
                            "sourceEntityName": "订单",
                            "fields": [{"fieldId": "f9", "fieldName": "状态", "fieldValue": "done"}],
                        },
                    },
                ],
            },
        }

        def fetch_json(origin, path, domain=None, method="GET", payload=None):
            self.assertIn("getNodeDetail", path)
            self.assertIn("nodeId=node-query", path)
            self.assertIn("flowNodeType=7", path)
            self.assertNotIn("node-else", path)
            self.assertNotIn("node-update", path)
            return {"data": fixture["query_detail"]}

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(extract_project, "init_and_list_tools", return_value=[{
                 "name": "get_workflow_structure",
                 "inputSchema": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]},
             }]), \
             mock.patch.object(extract_project, "call_tool", return_value=process), \
             mock.patch.object(extract_project, "extract_node_detail_configs") as empty_pass, \
             mock.patch.object(extract_project.platform_router, "fetch_json", side_effect=fetch_json):
            extract_project.collect_workflow_nodes(
                tmp,
                [{"id": "proc-editor", "name": "查询示例"}],
                mcp_url="https://mcp.example/mcp",
                base_url="https://app.example",
            )
            empty_pass.assert_not_called()
            saved = json.loads((Path(tmp) / "_node_configs.json").read_text(encoding="utf-8"))
        rows = {row["node_id"]: row for row in saved["proc-editor"]}
        self.assertEqual(rows["node-query"]["editor_config"]["lines"], QUERY_LINES)
        self.assertTrue(rows["node-else"]["editor_config"]["default_branch"])
        self.assertIn("将字段 状态 设为 done", rows["node-update"]["field_mappings"]["lines"][0])
        self.assertIn("将字段 状态 设为 done", rows["node-update"]["editor_config"]["lines"])


if __name__ == "__main__":
    unittest.main()
