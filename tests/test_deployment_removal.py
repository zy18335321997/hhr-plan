import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import agent_prepare  # noqa: E402
import contract_compat  # noqa: E402
from lock_to_contract import convert_lock  # noqa: E402


class DeploymentRemovalTests(unittest.TestCase):
    def test_lock_without_deployment_converts_successfully(self):
        lock = json.loads(
            (FIXTURES / "valid_execution_lock.json").read_text(encoding="utf-8")
        )
        workflow = copy.deepcopy(lock["workflows"][0])
        workflow.pop("deployment", None)
        lock["workflows"][0] = workflow

        digest = agent_prepare.compute_lock_digest(lock)
        lock["verification"]["input_digest"] = digest
        lock["verification"]["verification_agents"]["agent_input_digests"] = {
            "agent_1_logic": digest,
            "agent_2_platform": digest,
        }

        contract = convert_lock(lock)

        self.assertEqual("提交采购需求", contract["meta"]["workflow_name"])
        self.assertNotIn("deployment", contract)
        self.assertEqual([], contract_compat.validate_exec(contract))


if __name__ == "__main__":
    unittest.main()
