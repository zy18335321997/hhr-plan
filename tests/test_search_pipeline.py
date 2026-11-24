import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

PROJECT = "pipeline-fixture"
ORDER_PID = "wf-order-0001"
CUSTOMER_PID = "wf-customer-0001"


class SearchPipelineTests(unittest.TestCase):
    """End-to-end: build index from project data, then query it via the CLIs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self._tmp.name)
        self.project_dir = self.data_root / PROJECT
        self.project_dir.mkdir()
        self.env = {**os.environ, "HHR_DATA_ROOT": str(self.data_root)}
        self._write_fixture()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_fixture(self):
        registry = {
            "projects": {
                PROJECT: {
                    "context_ready": True,
                    "path": str(self.project_dir),
                }
            }
        }
        (self.data_root / "projects_registry.json").write_text(
            json.dumps(registry, ensure_ascii=False), encoding="utf-8"
        )

        context = {
            "worksheets": {
                "订单": {
                    "id": "ws-orders",
                    "fields": [
                        {
                            "id": "f-contract",
                            "name": "合同编号",
                            "type": "Text",
                            "isTitle": True,
                        },
                        {"id": "f-amount", "name": "采购金额", "type": "Number"},
                    ],
                },
                "客户": {
                    "id": "ws-customers",
                    "fields": [
                        {
                            "id": "f-customer",
                            "name": "客户名称",
                            "type": "Text",
                            "isTitle": True,
                        }
                    ],
                },
            }
        }
        (self.project_dir / "project_context.json").write_text(
            json.dumps(context, ensure_ascii=False), encoding="utf-8"
        )

        node_data = {
            ORDER_PID: {
                "name": "新增采购单",
                "worksheet": "订单",
                "trigger": "工作表事件",
                "node_count": 2,
                "reads": ["客户"],
                "writes": ["订单"],
            },
            CUSTOMER_PID: {
                "name": "同步客户",
                "worksheet": "客户",
                "trigger": "定时触发",
                "node_count": 1,
                "reads": [],
                "writes": ["客户"],
            },
        }
        (self.project_dir / "_node_data.json").write_text(
            json.dumps(node_data, ensure_ascii=False), encoding="utf-8"
        )
        (self.project_dir / "name_index.json").write_text(
            json.dumps(
                {"新增采购单": ORDER_PID, "同步客户": CUSTOMER_PID},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        for dir_name, wf_name, sheet in (
            ("wf-order", "新增采购单", "订单"),
            ("wf-customer", "同步客户", "客户"),
        ):
            cache_dir = self.project_dir / "workflows" / dir_name
            cache_dir.mkdir(parents=True)
            (cache_dir / "node_configs.json").write_text(
                json.dumps(
                    [
                        {
                            "typeId": 0,
                            "appName": sheet,
                            "appType": 2,
                            "id": f"node-{dir_name}",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (cache_dir / "workflow_meta.json").write_text(
                json.dumps({"name": wf_name}, ensure_ascii=False),
                encoding="utf-8",
            )

    def _run(self, script, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_build_index_then_search_and_sheet_mapping(self):
        built = self._run("build_search_index.py", PROJECT)
        self.assertEqual(0, built.returncode, built.stderr)

        found = self._run(
            "search.py", "采购", "--type", "workflow", "-p", PROJECT, "-f", "json"
        )
        self.assertEqual(0, found.returncode, found.stderr)
        payload = json.loads(found.stdout)
        self.assertEqual(1, payload["count"])
        self.assertEqual("新增采购单", payload["results"][0]["entity_name"])
        self.assertEqual("订单", payload["results"][0]["parent_context"])

        field_hit = self._run(
            "search.py", "合同编号", "--field-search", "-p", PROJECT, "-f", "json"
        )
        self.assertEqual(0, field_hit.returncode, field_hit.stderr)
        field_payload = json.loads(field_hit.stdout)
        self.assertEqual(1, field_payload["count"])
        self.assertEqual("订单", field_payload["results"][0]["sheet_name"])

        rebuilt = self._run("sheet_workflows.py", PROJECT, "--rebuild")
        self.assertEqual(0, rebuilt.returncode, rebuilt.stderr)

        listed = self._run("sheet_workflows.py", PROJECT, "--list")
        self.assertEqual(0, listed.returncode, listed.stderr)
        self.assertIn("订单: 1 workflows", listed.stdout)
        self.assertIn("客户: 1 workflows", listed.stdout)


if __name__ == "__main__":
    unittest.main()
