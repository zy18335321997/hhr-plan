"""Shared filesystem roots for hhr-plan scripts.

HHR_DATA_ROOT overrides the project data root. The default stays
the workflow-output directory under $HOME. The leading underscore
keeps skill_discovery.py from registering this module as a CLI script.
"""

import os
from pathlib import Path


DATA_ROOT = Path(
    os.environ.get("HHR_DATA_ROOT", Path.home() / "Documents" / "workflow-output")
)
HAP_BRIDGE_CLI = Path.home() / ".claude" / "mcp-servers" / "hap-bridge" / "cli.py"
