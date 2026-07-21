import copy
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import contract_compat  # noqa: E402


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


AUTO_SYNC = load_module("test_auto_sync", SCRIPTS / "auto_sync.py")


class LoadingAndSyncTests(unittest.TestCase):
    def test_skill_bootstrap_has_no_directory_references(self):
        frontmatter = (ROOT / "SKILL.md").read_text(encoding="utf-8").split(
            "---", 2
        )[1]
        self.assertNotIn("built-in-skills/", frontmatter)
        self.assertNotIn("agents/descriptors/", frontmatter)

    def test_stale_indexes_rebuild_per_project(self):
        with mock.patch.object(AUTO_SYNC.subprocess, "run") as run:
            AUTO_SYNC.rebuild_index(["项目A", "项目B"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            [
                [sys.executable, str(SCRIPTS / "build_search_index.py"), "项目A"],
                [sys.executable, str(SCRIPTS / "build_search_index.py"), "项目B"],
            ],
            commands,
        )

    def test_stale_node_data_is_force_regenerated(self):
        with mock.patch.object(AUTO_SYNC.subprocess, "run") as run:
            AUTO_SYNC.rebuild_node_data(["项目A"])
        self.assertEqual(
            [
                sys.executable,
                str(SCRIPTS / "generate_node_data.py"),
                "项目A",
                "--force",
            ],
            run.call_args.args[0],
        )

    def test_index_freshness_is_tracked_per_project(self):
        original_base = AUTO_SYNC.BASE
        original_db = AUTO_SYNC.INDEX_DB
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, mtime in (("项目A", 50), ("项目B", 200)):
                project = base / name
                project.mkdir()
                source = project / "_node_data.json"
                source.write_text("{}", encoding="utf-8")
                os.utime(source, (mtime, mtime))
            db = base / "index.db"
            connection = sqlite3.connect(db)
            connection.execute(
                "CREATE TABLE projects(name TEXT PRIMARY KEY, source_mtime REAL)"
            )
            connection.execute(
                "CREATE TABLE search_fts(project TEXT)"
            )
            connection.executemany(
                "INSERT INTO projects(name, source_mtime) VALUES(?,?)",
                [("项目A", 100), ("项目B", 100)],
            )
            connection.executemany(
                "INSERT INTO search_fts(project) VALUES(?)",
                [("项目A",), ("项目B",)],
            )
            connection.commit()
            connection.close()
            AUTO_SYNC.BASE = str(base)
            AUTO_SYNC.INDEX_DB = str(db)
            try:
                stale = AUTO_SYNC.check_index(
                    [("项目A", str(base / "项目A")),
                     ("项目B", str(base / "项目B"))]
                )
            finally:
                AUTO_SYNC.BASE = original_base
                AUTO_SYNC.INDEX_DB = original_db
        self.assertEqual(["项目B"], stale)

    def test_freshness_uses_registry_project_path(self):
        with tempfile.TemporaryDirectory() as directory:
            custom = Path(directory) / "custom-location"
            custom.mkdir()
            raw = custom / "nodes.json"
            derived = custom / "_node_data.json"
            raw.write_text("[]", encoding="utf-8")
            derived.write_text("{}", encoding="utf-8")
            os.utime(derived, (100, 100))
            os.utime(raw, (200, 200))
            self.assertTrue(
                AUTO_SYNC.check_node_data("逻辑项目名", str(custom))
            )

    def test_lifecycle_query_does_not_rebuild_or_write_graph(self):
        with tempfile.TemporaryDirectory() as home:
            project_dir = (
                Path(home) / "Documents" / "workflow-output" / "测试项目"
            )
            project_dir.mkdir(parents=True)
            graph_path = project_dir / "dependency_graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "采购需求": {
                                "reader_count": 0,
                                "writer_count": 0,
                                "created_by": [],
                                "updated_by": [],
                                "read_by": [],
                                "written_by": [],
                            }
                        },
                        "edges": [],
                        "workflows": {},
                    }
                ),
                encoding="utf-8",
            )
            before = graph_path.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "rebuild_graph.py"),
                    "测试项目",
                    "--lifecycle",
                    "采购需求",
                ],
                env={**os.environ, "HOME": home},
                capture_output=True,
                text=True,
                check=False,
            )
            after = graph_path.read_bytes()
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(before, after)


class PerformanceBudgetTests(unittest.TestCase):
    def test_validate_exec_handles_one_hundred_nodes_under_one_second(self):
        contract = json.loads(
            (FIXTURES / "expected_execution_contract.json").read_text(
                encoding="utf-8"
            )
        )
        template = contract["nodes"][0]
        contract["nodes"] = []
        for index in range(100):
            node = copy.deepcopy(template)
            node["seq"] = f"T{index + 1}"
            node["alias"] = f"update_status_{index}"
            contract["nodes"].append(node)
        contract["meta"]["node_count"] = 100

        started = time.perf_counter()
        violations = contract_compat.validate_exec(contract)
        elapsed = time.perf_counter() - started

        self.assertEqual([], violations)
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
