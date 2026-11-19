"""平台路由（platform_router）离线单测。

约定: 用 importlib/sys.path 加载 scripts/ 下脚本（同 test_skill_discovery.py），
mock 网络缝 _urlopen_json 与认证缝 _load_auth_module，全程无网络、无浏览器。
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import platform_router  # noqa: E402
import wf_fetch  # noqa: E402
import batch_cli_fetch  # noqa: E402

PID24 = "6a5d92351e5bb38f1cbea440"
APP_UUID = "a8120f48-9362-43ca-b60d-3a7e206f77cd"
APP_URL = f"http://fusion.ypsti.com/app/{APP_UUID}/workflow"
WF_URL = f"http://fusion.ypsti.com/workflowedit/{PID24}"


def _fake_auth(cookie="a=b"):
    class FakeAuth:
        @staticmethod
        def get_auth_headers(domain):
            return {"Cookie": cookie, "User-Agent": "test"}
    return FakeAuth()


class UrlParseTests(unittest.TestCase):
    def test_app_form(self):
        parsed = platform_router.parse_platform_url(APP_URL)
        self.assertEqual(parsed["origin"], "http://fusion.ypsti.com")
        self.assertEqual(parsed["domain"], "fusion.ypsti.com")
        self.assertEqual(parsed["app_id"], APP_UUID)
        self.assertEqual(parsed["pid"], "")
        self.assertEqual(parsed["kind"], "app")

    def test_workflowedit_form(self):
        parsed = platform_router.parse_platform_url(WF_URL)
        self.assertEqual(parsed["pid"], PID24)
        self.assertEqual(parsed["app_id"], "")
        self.assertEqual(parsed["kind"], "workflow")

    def test_trailing_slash_and_query_stripped(self):
        parsed = platform_router.parse_platform_url(
            f"http://fusion.ypsti.com/app/{APP_UUID}/workflow/?tab=1")
        self.assertEqual(parsed["app_id"], APP_UUID)
        self.assertEqual(parsed["origin"], "http://fusion.ypsti.com")

    def test_bare_origin_unknown(self):
        parsed = platform_router.parse_platform_url("http://fusion.ypsti.com")
        self.assertEqual(parsed["kind"], "unknown")
        self.assertEqual(parsed["app_id"], "")
        self.assertEqual(parsed["pid"], "")

    def test_invalid_scheme_raises(self):
        with self.assertRaises(platform_router.PlatformError):
            platform_router.parse_platform_url("ftp://fusion.ypsti.com/app/x")

    def test_empty_raises(self):
        with self.assertRaises(platform_router.PlatformError):
            platform_router.parse_platform_url("")

    def test_http_scheme_preserved(self):
        self.assertEqual(platform_router.derive_origin(APP_URL), "http://fusion.ypsti.com")

    def test_https_and_port(self):
        self.assertEqual(platform_router.derive_origin("https://h.example.com:8443/x"), "https://h.example.com:8443")

    def test_derive_origin_invalid(self):
        self.assertIsNone(platform_router.derive_origin(""))
        self.assertIsNone(platform_router.derive_origin("not a url"))


class CookieDomainTests(unittest.TestCase):
    def test_port_stripped(self):
        self.assertEqual(platform_router.derive_cookie_domain("http://h.example.com:8080/app/1"), "h.example.com")

    def test_empty(self):
        self.assertEqual(platform_router.derive_cookie_domain(""), "")


class AuthHeaderTests(unittest.TestCase):
    def test_md_pss_id_adds_authorization(self):
        with mock.patch.object(platform_router, "_load_auth_module",
                               return_value=_fake_auth("md_pss_id=tok123; sid=1")):
            headers = platform_router.get_auth_headers("fusion.ypsti.com")
        self.assertEqual(headers["Authorization"], "md_pss_id tok123")
        self.assertIn("Cookie", headers)

    def test_no_md_pss_id_cookie_only(self):
        with mock.patch.object(platform_router, "_load_auth_module",
                               return_value=_fake_auth("sid=1")):
            headers = platform_router.get_auth_headers("fusion.ypsti.com")
        self.assertIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_auth_module_missing_returns_none(self):
        with mock.patch.object(platform_router, "_load_auth_module", return_value=None):
            self.assertIsNone(platform_router.get_auth_headers("fusion.ypsti.com"))

    def test_auth_print_not_echoed_to_stdout(self):
        class NoisyAuth:
            @staticmethod
            def get_auth_headers(domain):
                print("  [auth] noisy message")
                return {"Cookie": "a=b"}
        with mock.patch.object(platform_router, "_load_auth_module", return_value=NoisyAuth()):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                headers = platform_router.get_auth_headers("fusion.ypsti.com")
        self.assertIsNotNone(headers)
        self.assertEqual(buf.getvalue(), "")


class FetchJsonTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(platform_router, "_load_auth_module",
                                    return_value=_fake_auth())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_url_method_body_and_headers(self):
        captured = {}
        def fake_urlopen(req, timeout=15):
            captured["req"] = req
            return {"ok": 1}
        with mock.patch.object(platform_router, "_urlopen_json", side_effect=fake_urlopen) as m:
            result = platform_router.fetch_json(
                "http://h", "/api/x?y=1", domain="h", method="POST", payload={"k": "v"})
        req = captured["req"]
        self.assertEqual(req.full_url, "http://h/api/x?y=1")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), {"k": "v"})
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(req.get_header("Cookie"), "a=b")
        self.assertEqual(result, {"ok": 1})
        m.assert_called_once()

    def test_http_error_becomes_platform_error(self):
        def raise_404(req, timeout=15):
            raise urllib.error.HTTPError("http://h/x", 404, "Not Found", {}, None)
        with mock.patch.object(platform_router, "_urlopen_json", side_effect=raise_404):
            with self.assertRaises(platform_router.PlatformError) as cm:
                platform_router.fetch_json("http://h", "/x", domain="h")
        self.assertIn("HTTP 404", str(cm.exception))
        self.assertNotIn("a=b", str(cm.exception))

    def test_non_json_becomes_platform_error(self):
        def raise_json(req, timeout=15):
            raise json.JSONDecodeError("boom", "doc", 0)
        with mock.patch.object(platform_router, "_urlopen_json", side_effect=raise_json):
            with self.assertRaises(platform_router.PlatformError):
                platform_router.fetch_json("http://h", "/x", domain="h")

    def test_no_auth_raises(self):
        with mock.patch.object(platform_router, "_load_auth_module", return_value=None):
            with self.assertRaises(platform_router.PlatformError):
                platform_router.fetch_json("http://h", "/x", domain="h")


class NodeParseTests(unittest.TestCase):
    def test_flow_node_map_dict_to_list(self):
        payload = {"data": {"flowNodeMap": {"n1": {"nodeId": "n1"}, "n2": {"nodeId": "n2"}}}}
        with mock.patch.object(platform_router, "fetch_json", return_value=payload):
            nodes = platform_router.fetch_workflow_nodes("http://h", PID24)
        self.assertEqual(len(nodes), 2)

    def test_data_as_list(self):
        with mock.patch.object(platform_router, "fetch_json",
                               return_value={"data": [{"nodeId": "n1"}]}):
            nodes = platform_router.fetch_workflow_nodes("http://h", PID24)
        self.assertEqual(nodes, [{"nodeId": "n1"}])

    def test_missing_flow_node_map_raises(self):
        with mock.patch.object(platform_router, "fetch_json",
                               return_value={"data": {"foo": 1}}):
            with self.assertRaises(platform_router.PlatformError):
                platform_router.fetch_workflow_nodes("http://h", PID24)

    def test_empty_map_returns_empty(self):
        with mock.patch.object(platform_router, "fetch_json",
                               return_value={"data": {"flowNodeMap": {}}}):
            self.assertEqual(platform_router.fetch_workflow_nodes("http://h", PID24), [])


class WorkflowListTests(unittest.TestCase):
    def setUp(self):
        platform_router._PROBE_CACHE.clear()

    def test_first_probe_hits(self):
        with mock.patch.object(
                platform_router, "fetch_json",
                return_value={"data": [{"id": "p1", "name": "流1"}]}) as m:
            result = platform_router.fetch_workflow_list("http://h", "app1")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], "p1")
            self.assertEqual(m.call_count, 1)
            self.assertIn("listAll", m.call_args.args[1])

    def test_cache_reuses_probe(self):
        with mock.patch.object(
                platform_router, "fetch_json",
                return_value={"data": [{"id": "p1", "name": "流1"}]}) as m:
            platform_router.fetch_workflow_list("http://h", "app1")
            platform_router.fetch_workflow_list("http://h", "app1")
            self.assertEqual(m.call_count, 2)
            self.assertIn("listAll", m.call_args.args[1])

    def test_a_404_then_b_hits(self):
        with mock.patch.object(platform_router, "fetch_json", side_effect=[
                platform_router.PlatformError("404"),
                {"data": [{"id": "p2", "name": "流2"}]}]) as m:
            result = platform_router.fetch_workflow_list("http://h", "app1")
        self.assertEqual([w["id"] for w in result], ["p2"])
        self.assertEqual(m.call_count, 2)
        self.assertIn("getProcessList", m.call_args_list[1].args[1])

    def test_ab_fail_then_c_grouped_merge_dedupe(self):
        with mock.patch.object(platform_router, "fetch_json", side_effect=[
                platform_router.PlatformError("404"),
                platform_router.PlatformError("404"),
                {"data": {"g1": [{"id": "p1", "name": "流1"}],
                          "g2": [{"id": "p1", "name": "流1"}, {"id": "p2", "name": "流2"}]}}]):
            result = platform_router.fetch_workflow_list("http://h", "app1")
        self.assertEqual(sorted(w["id"] for w in result), ["p1", "p2"])

    def test_all_fail_raises(self):
        with mock.patch.object(platform_router, "fetch_json",
                               side_effect=platform_router.PlatformError("x")):
            with self.assertRaises(platform_router.PlatformError):
                platform_router.fetch_workflow_list("http://h", "app1")

    def test_empty_data_is_success(self):
        with mock.patch.object(platform_router, "fetch_json",
                               return_value={"data": []}) as m:
            result = platform_router.fetch_workflow_list("http://h", "app1")
        self.assertEqual(result, [])
        self.assertEqual(m.call_count, 1)

    def test_unrecognized_shape_tries_next(self):
        with mock.patch.object(platform_router, "fetch_json", side_effect=[
                {"code": 500, "msg": "boom"},
                {"data": [{"processId": "p3", "processName": "流3"}]}]) as m:
            result = platform_router.fetch_workflow_list("http://h", "app1")
        self.assertEqual(result[0]["id"], "p3")
        self.assertEqual(result[0]["name"], "流3")
        self.assertEqual(m.call_count, 2)

    def test_fusion_grouped_process_list_flattened(self):
        payload = {"status": 1, "data": [
            {"groupId": "g1", "groupName": "组1",
             "processList": [{"id": "p1", "name": "流1"}]},
            {"groupId": "g2", "groupName": "组2",
             "processList": [{"id": "p2", "name": "流2"}, {"id": "p1", "name": "流1"}]}]}
        with mock.patch.object(platform_router, "fetch_json", return_value=payload):
            result = platform_router.fetch_workflow_list("http://h", "app1")
        self.assertEqual(sorted(w["id"] for w in result), ["p1", "p2"])
        self.assertEqual(result[0]["name"], "流1")


class WorkflowCountTests(unittest.TestCase):
    def test_normal_count(self):
        with mock.patch.object(platform_router, "fetch_json",
                               return_value={"data": {"count": 356}}):
            self.assertEqual(platform_router.fetch_workflow_count("http://h", "app1"), 356)

    def test_envelope_less_count(self):
        with mock.patch.object(platform_router, "fetch_json", return_value={"total": 7}):
            self.assertEqual(platform_router.fetch_workflow_count("http://h", "app1"), 7)

    def test_error_returns_none(self):
        with mock.patch.object(platform_router, "fetch_json",
                               side_effect=platform_router.PlatformError("x")):
            self.assertIsNone(platform_router.fetch_workflow_count("http://h", "app1"))


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "proj"
        self.project.mkdir()

    def test_save_binding_keys_are_exactly_whitelist(self):
        data = platform_router.save_binding(
            self.project, origin="http://h.example.com:8080", app_id="app1", pid=PID24,
            source="extract-project")
        saved = json.loads((self.project / "platform.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved.keys()), set(platform_router._BINDING_KEYS))
        self.assertEqual(saved["domain"], "h.example.com")
        self.assertEqual(saved["origin"], "http://h.example.com:8080")
        self.assertNotIn("Cookie", saved)
        self.assertNotIn("Token", saved)

    def test_load_roundtrip(self):
        platform_router.save_binding(self.project, origin="http://h", app_id="app1")
        loaded = platform_router.load_binding(self.project)
        self.assertEqual(loaded["origin"], "http://h")
        self.assertEqual(loaded["app_id"], "app1")

    def test_corrupt_file_returns_none(self):
        (self.project / "platform.json").write_text("not json{{{", encoding="utf-8")
        self.assertIsNone(platform_router.load_binding(self.project))

    def test_missing_file_returns_none(self):
        self.assertIsNone(platform_router.load_binding(self.project / "nope"))

    def test_resolve_url_overrides_file(self):
        platform_router.save_binding(self.project, origin="http://file.example.com")
        binding = platform_router.resolve_binding(self.project, APP_URL)
        self.assertEqual(binding["origin"], "http://fusion.ypsti.com")
        self.assertEqual(binding["app_id"], APP_UUID)
        self.assertEqual(binding["source"], "user_url")

    def test_resolve_no_url_uses_file(self):
        platform_router.save_binding(self.project, origin="http://file.example.com")
        binding = platform_router.resolve_binding(self.project)
        self.assertEqual(binding["origin"], "http://file.example.com")


class CliTests(unittest.TestCase):
    def test_parse_valid_exit_0_json_stdout(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = platform_router.main(["parse", APP_URL])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["kind"], "app")
        self.assertEqual(parsed["app_id"], APP_UUID)

    def test_parse_invalid_exit_1(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(io.StringIO()):
            rc = platform_router.main(["parse", "ftp://bad.example.com/x"])
        self.assertEqual(rc, 1)

    def test_help_exits_0(self):
        with self.assertRaises(SystemExit) as cm:
            platform_router._build_parser().parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)


class WfFetchChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.old_data = wf_fetch.DATA
        wf_fetch.DATA = self.data
        self.addCleanup(self._restore_data)
        self.old_argv = sys.argv
        self.addCleanup(self._restore_argv)

    def _restore_data(self):
        wf_fetch.DATA = self.old_data

    def _restore_argv(self):
        sys.argv = self.old_argv

    def _run_main(self, argv):
        sys.argv = argv
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                wf_fetch.main()
            except SystemExit as e:
                return out.getvalue(), err.getvalue(), e.code
        return out.getvalue(), err.getvalue(), 0

    def test_binding_routes_to_platform_internal(self):
        project = self.data / "proj"
        project.mkdir()
        platform_router.save_binding(project, origin="http://fusion.ypsti.com", app_id=APP_UUID)
        nodes = [{"nodeId": "n1", "typeId": 0, "appName": "测试表"}]
        with mock.patch.object(platform_router, "fetch_workflow_nodes", return_value=nodes), \
             mock.patch.object(wf_fetch.subprocess, "run") as sub_run, \
             mock.patch.object(wf_fetch, "_mcp_call", return_value=None):
            out, _, rc = self._run_main(["wf_fetch.py", "proj", PID24])
        self.assertEqual(rc, 0)
        self.assertIn('"source": "platform_internal"', out)
        sub_run.assert_not_called()
        saved = json.loads((project / "platform.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["pid"], PID24)
        meta = json.loads((self.data / "proj" / PID24 / "workflow_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["origin"], "http://fusion.ypsti.com")
        self.assertEqual(meta["name"], "")  # fetch_name=False 跳过 MCP 取名

    def test_no_binding_uses_legacy_cli(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"status": "ok", "data": {"flowNodeMap": {
                "n1": {"nodeId": "n1", "typeId": 0, "appName": "表A"}}}}),
            stderr="")
        with mock.patch.object(wf_fetch.subprocess, "run", return_value=completed) as sub_run, \
             mock.patch.object(wf_fetch, "_mcp_call", return_value=None):
            out, _, rc = self._run_main(["wf_fetch.py", "proj2", PID24])
        self.assertEqual(rc, 0)
        self.assertIn('"source": "cli_wf-nodes"', out)
        sub_run.assert_called_once()

    def test_route_error_falls_back_to_mcp_and_binding_not_written(self):
        project = self.data / "proj"
        project.mkdir()
        platform_router.save_binding(project, origin="http://fusion.ypsti.com", app_id=APP_UUID)
        with mock.patch.object(platform_router, "fetch_workflow_nodes",
                               side_effect=platform_router.PlatformError("boom")), \
             mock.patch.object(wf_fetch.subprocess, "run") as sub_run, \
             mock.patch.object(wf_fetch, "_mcp_call",
                               return_value={"name": "测试流程"}):
            out, _, rc = self._run_main(["wf_fetch.py", "proj", PID24])
        self.assertEqual(rc, 0)
        self.assertIn('"source": "mcp_fallback"', out)
        sub_run.assert_not_called()  # 有绑定时不走写死域名的 legacy CLI
        saved = json.loads((project / "platform.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["pid"], "")  # 失败不写绑定

    def test_url_overrides_binding_file(self):
        project = self.data / "proj"
        project.mkdir()
        platform_router.save_binding(project, origin="http://file.example.com", app_id="other")
        captured = {}
        def fake_nodes(origin, pid):
            captured["origin"] = origin
            return [{"nodeId": "n1", "typeId": 0, "appName": "测试表"}]
        with mock.patch.object(platform_router, "fetch_workflow_nodes", side_effect=fake_nodes), \
             mock.patch.object(wf_fetch, "_mcp_call", return_value=None):
            out, _, rc = self._run_main(
                ["wf_fetch.py", "proj", PID24, "--url", APP_URL])
        self.assertEqual(rc, 0)
        self.assertIn('"source": "platform_internal"', out)
        self.assertEqual(captured["origin"], "http://fusion.ypsti.com")
        saved = json.loads((project / "platform.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["app_id"], APP_UUID)

    def test_invalid_url_exits_2(self):
        with mock.patch.object(wf_fetch, "_mcp_call", return_value=None):
            out, err, rc = self._run_main(
                ["wf_fetch.py", "proj", PID24, "--url", "ftp://bad.example.com/x"])
        self.assertEqual(rc, 2)
        self.assertIn("[route]", err)

    def test_non_hex_pid_with_binding_skips_route(self):
        project = self.data / "proj"
        project.mkdir()
        platform_router.save_binding(project, origin="http://fusion.ypsti.com", app_id=APP_UUID)
        with mock.patch.object(platform_router, "fetch_workflow_nodes") as fetch_nodes, \
             mock.patch.object(wf_fetch.subprocess, "run") as sub_run, \
             mock.patch.object(wf_fetch, "_mcp_call", return_value={"name": "x"}):
            out, _, rc = self._run_main(["wf_fetch.py", "proj", "某个工作流名"])
        fetch_nodes.assert_not_called()
        sub_run.assert_not_called()  # 有绑定同样不走 legacy
        self.assertIn('"source": "mcp_fallback"', out)


class BatchCliFetchTests(unittest.TestCase):
    def test_both_source_markers_accepted(self):
        self.assertTrue(batch_cli_fetch._is_success('{"source": "cli_wf-nodes"}'))
        self.assertTrue(batch_cli_fetch._is_success('{"source": "platform_internal"}'))
        self.assertFalse(batch_cli_fetch._is_success('{"source": "mcp_fallback"}'))


if __name__ == "__main__":
    unittest.main()
