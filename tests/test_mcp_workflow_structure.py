"""MCP get_workflow_structure extraction. Fixtures only; no network."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mcp_workflow_structure as structure  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "workflow-structure"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _extract_project():
    spec = importlib.util.spec_from_file_location("extract_project_mcp", ROOT / "scripts" / "extract-project.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool(argument="workflow_id", name="get_workflow_structure"):
    return {
        "name": name,
        "description": "workflow structure snapshot",
        "inputSchema": {
            "type": "object",
            "properties": {argument: {"type": "string"}},
            "required": [argument],
        },
    }


class ToolSelectionTests(unittest.TestCase):
    def test_details_tool_is_not_a_structure_tool(self):
        tools = [
            {"name": "get_workflow_details", "inputSchema": {"properties": {"process_id": {}}}},
            {"name": "get_workflow_list"},
        ]
        self.assertIsNone(structure.select_structure_tool(tools))

    def test_exact_name_beats_equivalent(self):
        tools = [
            {"name": "legacy_workflow_structure"},
            {"name": "get_workflow_structure", "inputSchema": {"properties": {"workflow_id": {}}}},
        ]
        selected = structure.select_structure_tool(tools)
        self.assertEqual(selected["name"], "get_workflow_structure")

    def test_equivalent_name_is_accepted(self):
        selected = structure.select_structure_tool([{"name": "hap_get_workflow_structure"}])
        self.assertEqual(selected["name"], "hap_get_workflow_structure")

    def test_argument_follows_required_schema_field(self):
        self.assertEqual(structure.argument_name_for_process(_tool("process_id")), "process_id")
        self.assertEqual(structure.argument_name_for_process(_tool("workflow_id")), "workflow_id")
        both = {
            "name": "get_workflow_structure",
            "inputSchema": {
                "properties": {"workflow_id": {}, "process_id": {}},
                "required": ["process_id"],
            },
        }
        self.assertEqual(structure.argument_name_for_process(both), "process_id")
        unspecified = {
            "name": "get_workflow_structure",
            "inputSchema": {"properties": {"workflow_id": {}, "process_id": {}}},
        }
        self.assertEqual(structure.argument_name_for_process(unspecified), "workflow_id")


class StructureWalkTests(unittest.TestCase):
    def test_nested_approval_and_subprocess_need_extra_calls(self):
        payloads = {
            "proc-root": _load("main.json"),
            "proc-approval-inner": _load("approval-inner.json"),
            "proc-sub-inner": _load("subprocess-inner.json"),
        }
        calls = []

        def call_tool(name, args):
            calls.append((name, dict(args)))
            pid = args["workflow_id"]
            return payloads[pid]

        snapshot = structure.extract_structures(
            ["proc-root"],
            [_tool("workflow_id")],
            call_tool,
        )
        self.assertEqual([call[1]["workflow_id"] for call in calls], [
            "proc-root", "proc-approval-inner", "proc-sub-inner",
        ])
        self.assertEqual(snapshot["argument"], "workflow_id")
        self.assertEqual(
            set(snapshot["processes"]),
            {"proc-root", "proc-approval-inner", "proc-sub-inner"},
        )
        self.assertTrue(snapshot["incomplete"])
        reasons = {(gap["process_id"], gap["reason"], gap.get("node_id")) for gap in snapshot["gaps"]}
        self.assertIn(("proc-root", "empty_config", "node-update"), reasons)
        inner = snapshot["processes"]["proc-approval-inner"]["nodes"][0]["config"]["fields"][0]
        self.assertEqual(inner["fieldId"], "f1")
        self.assertNotIn("nodes", snapshot["processes"]["proc-root"]["nodes"][0]["config"]["process"])

    def test_process_id_argument_is_what_the_schema_requires(self):
        payloads = {
            "proc-root": _load("main.json"),
            "proc-approval-inner": _load("approval-inner.json"),
            "proc-sub-inner": _load("subprocess-inner.json"),
        }
        seen = []

        def call_tool(name, args):
            seen.append(args)
            return payloads[args["process_id"]]

        snapshot = structure.extract_structures(["proc-root"], [_tool("process_id")], call_tool)
        self.assertTrue(all("process_id" in args and "workflow_id" not in args for args in seen))
        self.assertEqual(snapshot["argument"], "process_id")
        self.assertIn("proc-sub-inner", snapshot["processes"])

    def test_nested_failure_is_recorded_and_does_not_raise(self):
        def call_tool(name, args):
            if args["workflow_id"] == "proc-root":
                return _load("main.json")
            secret_url = (
                "https://secret.example/mcp?"
                + "HAP-" + "Appkey=abcdefghijklmnop&"
                + "HAP-" + "Sign=abcdefghijklmnopqrstuvwxyz0123456789"
            )
            return {"error": "boom at " + secret_url}

        snapshot = structure.extract_structures(["proc-root"], [_tool()], call_tool)
        self.assertIn("proc-root", snapshot["processes"])
        self.assertNotIn("proc-approval-inner", snapshot["processes"])
        failed = [gap for gap in snapshot["gaps"] if gap["reason"] == "nested_fetch_failed"]
        self.assertEqual({gap["process_id"] for gap in failed}, {"proc-approval-inner", "proc-sub-inner"})
        blob = json.dumps(snapshot)
        self.assertNotIn("abcdefghijklmnop", blob)
        self.assertNotIn("https://", blob)
        self.assertIn("<url>", blob)
        self.assertTrue(snapshot["incomplete"])

    def test_missing_tool_is_an_explicit_gap(self):
        snapshot = structure.extract_structures(
            ["proc-root"],
            [{"name": "get_workflow_details"}],
            lambda name, args: (_ for _ in ()).throw(AssertionError("must not call")),
        )
        self.assertEqual(snapshot["processes"], {})
        self.assertEqual(snapshot["gaps"], [{"reason": "structure_tool_unavailable"}])
        self.assertEqual(structure.incomplete_process_ids(snapshot, ["proc-root"]), {"proc-root"})

    def test_cycle_does_not_refetch(self):
        payload = _load("main.json")
        payload["data"]["nodes"] = [payload["data"]["nodes"][0]]
        payload["data"]["nodes"][0]["config"]["process"]["processId"] = "proc-root"
        calls = []

        def call_tool(name, args):
            calls.append(args["workflow_id"])
            return payload

        snapshot = structure.extract_structures(["proc-root"], [_tool()], call_tool)
        self.assertEqual(calls, ["proc-root"])
        self.assertEqual(list(snapshot["processes"]), ["proc-root"])

    def test_persist_writes_nodes_and_configs(self):
        def call_tool(name, args):
            return {
                "proc-root": _load("main.json"),
                "proc-approval-inner": _load("approval-inner.json"),
                "proc-sub-inner": _load("subprocess-inner.json"),
            }[args["workflow_id"]]

        snapshot = structure.extract_structures(["proc-root"], [_tool()], call_tool)
        with tempfile.TemporaryDirectory() as tmp:
            structure.persist(tmp, snapshot)
            nodes = json.loads((Path(tmp) / "nodes.json").read_text(encoding="utf-8"))
            configs = json.loads((Path(tmp) / "_node_configs.json").read_text(encoding="utf-8"))
            saved = json.loads((Path(tmp) / "_workflow_structures.json").read_text(encoding="utf-8"))
        self.assertEqual(nodes["proc-root"]["_source"], "mcp_get_workflow_structure")
        self.assertEqual(nodes["proc-root"]["node-approve"]["nodeType"], "approval_block")
        self.assertIn("node-trigger", nodes["proc-root"])
        inner_configs = {row["node_id"]: row for row in configs["proc-approval-inner"]}
        self.assertEqual(inner_configs["inner-pass"]["config"]["fields"][0]["value"], "ok")
        self.assertFalse(inner_configs["inner-pass"]["incomplete"])
        update = {row["node_id"]: row for row in configs["proc-root"]}["node-update"]
        self.assertTrue(update["incomplete"])
        self.assertTrue(saved["incomplete"])
        rows = structure.node_data_from_snapshot(snapshot, [{"id": "proc-root", "name": "采购审批示例", "worksheet": "采购单"}])
        self.assertEqual(rows["proc-root"]["approval_count"], 1)
        self.assertTrue(rows["proc-root"]["incomplete"])
        self.assertEqual(rows["proc-root"]["worksheet"], "采购单")
        self.assertGreater(rows["proc-approval-inner"]["node_count"], 0)


class LegacyFlowNodeTests(unittest.TestCase):
    def test_inlined_approval_and_subprocess_id_recurse(self):
        calls = []

        def fetch_flow(pid):
            calls.append(pid)
            if pid == "proc-main":
                return _load("legacy-main.json")
            if pid == "proc-sub":
                return _load("legacy-sub.json")
            raise AssertionError(pid)

        legacy = structure.extract_legacy_structures(["proc-main"], fetch_flow)
        self.assertEqual(calls, ["proc-main", "proc-sub"])
        self.assertNotIn("ws-sheet", calls)
        self.assertNotIn("ws-not-a-process", calls)
        self.assertEqual(
            set(legacy["processes"]),
            {"proc-main", "proc-approval", "proc-sub", "proc-approval-2"},
        )
        approval = legacy["processes"]["proc-approval"]
        sub_node = next(node for node in approval["nodes"] if node["nodeId"] == "a-sub")
        self.assertEqual(sub_node["config"]["process"]["processId"], "proc-sub")
        self.assertNotIn("flowNodeMap", sub_node["config"].get("processNode", {}))
        deeper = legacy["processes"]["proc-approval-2"]["flowNodeMap"]["b-update"]
        self.assertEqual(deeper["fields"][0]["fieldId"], "f9")
        self.assertEqual(legacy["gaps"], [])

    def test_approval_without_inlined_map_is_fetched_by_id(self):
        calls = []

        def fetch_flow(pid):
            calls.append(pid)
            if pid == "proc-main":
                body = _load("legacy-main.json")
                process_node = body["data"]["flowNodeMap"]["n-approve"]["processNode"]
                process_node.pop("flowNodeMap")
                return body
            if pid == "proc-approval":
                return {
                    "data": {
                        "id": "proc-approval",
                        "startEventId": "a-start",
                        "flowNodeMap": {
                            "a-start": {"id": "a-start", "typeId": 0, "name": "审批开始"},
                        },
                    }
                }
            raise AssertionError(pid)

        legacy = structure.extract_legacy_structures(["proc-main"], fetch_flow)
        self.assertIn("proc-approval", calls)
        self.assertIn("proc-approval", legacy["processes"])

    def test_v3_gap_is_filled_from_legacy_shape(self):
        v3 = {
            "source": "mcp_get_workflow_structure",
            "tool": None,
            "argument": None,
            "incomplete": True,
            "gaps": [{"reason": "structure_tool_unavailable"}],
            "processes": {},
        }
        legacy = structure.extract_legacy_structures(
            ["proc-main"],
            lambda pid: _load("legacy-main.json") if pid == "proc-main" else _load("legacy-sub.json"),
        )
        merged = structure.merge_legacy(v3, legacy, ["proc-main"])
        self.assertFalse(merged["incomplete"])
        self.assertIn("proc-sub", merged["processes"])
        self.assertEqual(merged["processes"]["proc-sub"]["source"], "legacy_flow_node_get")


class ExtractProjectWiringTests(unittest.TestCase):
    def test_empty_v3_config_uses_get_node_detail_not_a_full_refetch(self):
        extract_project = _extract_project()

        def call_tool(url, name, args):
            return {
                "proc-root": _load("main.json"),
                "proc-approval-inner": _load("approval-inner.json"),
                "proc-sub-inner": _load("subprocess-inner.json"),
            }[args["workflow_id"]]

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(extract_project, "init_and_list_tools", return_value=[_tool()]), \
             mock.patch.object(extract_project, "call_tool", side_effect=call_tool), \
             mock.patch.object(extract_project, "extract_workflow_nodes") as cookie, \
             mock.patch.object(extract_project, "extract_node_detail_configs", return_value={}) as detail, \
             mock.patch.object(extract_project.platform_router, "fetch_json") as legacy:
            extract_project.collect_workflow_nodes(
                tmp,
                [{"id": "proc-root", "name": "采购审批示例"}],
                mcp_url="https://mcp.example/mcp",
                base_url="https://app.example",
            )
            cookie.assert_not_called()
            legacy.assert_not_called()
            detail.assert_called_once()
            self.assertTrue(detail.call_args.kwargs["merge_existing"])

    def test_complete_mcp_structure_does_not_call_cookie_detail(self):
        extract_project = _extract_project()

        def call_tool(url, name, args):
            self.assertEqual(name, "get_workflow_structure")
            self.assertEqual(args, {"workflow_id": "proc-approval-inner"})
            return _load("approval-inner.json")

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(extract_project, "init_and_list_tools", return_value=[_tool()]), \
             mock.patch.object(extract_project, "call_tool", side_effect=call_tool), \
             mock.patch.object(extract_project, "extract_workflow_nodes") as cookie, \
             mock.patch.object(extract_project, "extract_node_detail_configs") as detail:
            rows = extract_project.collect_workflow_nodes(
                tmp,
                [{"id": "proc-approval-inner", "name": "审批内部示例", "worksheet": "采购单"}],
                mcp_url="https://mcp.example/mcp",
                base_url="https://app.example",
            )
            cookie.assert_not_called()
            detail.assert_not_called()
            self.assertFalse(rows["proc-approval-inner"]["incomplete"])
            self.assertTrue((Path(tmp) / "_workflow_structures.json").is_file())
            saved_nodes = json.loads((Path(tmp) / "nodes.json").read_text(encoding="utf-8"))
            self.assertIn("inner-pass", saved_nodes["proc-approval-inner"])

    def test_missing_structure_tool_uses_legacy_flow_node_get(self):
        extract_project = _extract_project()

        def fetch_json(origin, path, domain=None, method="GET", payload=None):
            self.assertIn("flowNode/get", path)
            if "proc-main" in path:
                return _load("legacy-main.json")
            if "proc-sub" in path:
                return _load("legacy-sub.json")
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(extract_project, "init_and_list_tools",
                               return_value=[{"name": "get_workflow_details"}]), \
             mock.patch.object(extract_project, "call_tool") as mcp_call, \
             mock.patch.object(extract_project, "extract_node_detail_configs") as detail, \
             mock.patch.object(extract_project.platform_router, "fetch_json", side_effect=fetch_json):
            rows = extract_project.collect_workflow_nodes(
                tmp,
                [{"id": "proc-main", "name": "采购审批示例", "worksheet": "采购单"}],
                mcp_url="https://mcp.example/mcp",
                base_url="https://app.example",
            )
            mcp_call.assert_not_called()
            detail.assert_not_called()
            self.assertIn("proc-sub", rows)
            self.assertIn("proc-approval", rows)
            self.assertFalse(rows["proc-main"]["incomplete"])
            self.assertGreater(rows["proc-sub"]["node_count"], 0)
            saved = json.loads((Path(tmp) / "_workflow_structures.json").read_text(encoding="utf-8"))
            self.assertNotIn("structure_tool_unavailable", {gap.get("reason") for gap in saved["gaps"]})
            self.assertEqual(saved["processes"]["proc-approval"]["source"], "legacy_flow_node_get")


if __name__ == "__main__":
    unittest.main()
