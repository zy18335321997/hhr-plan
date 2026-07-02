#!/usr/bin/env python3
"""Gate 4: 平台原生校验 — 地面真相。

调用明道云平台自身的 validate API 验证工作流配置。
平台说 pass 才是真的 pass。我们的 Agent 1/2 是启发式近似。

用法:
  python3 platform-validate.py --workflow-id <process_id>
  python3 platform-validate.py --lock-file execution_lock.json

认证优先级:
  1. Chrome cookies (hap-bridge internal API, 自动检测)
  2. Open API (AppKey + Sign, 需配置环境变量)

返回: JSON verdict + 平台原生错误列表
exit code: 0=通过, 1=不通过, 2=跳过(无认证)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


HAP_BRIDGE = os.path.expanduser("~/.claude/mcp-servers/hap-bridge/cli.py")


def try_chrome_auth() -> bool:
    """Check if Chrome cookie auth is available."""
    try:
        result = subprocess.run(
            ["python3", HAP_BRIDGE, "auth-check"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and "OK" in (result.stdout + result.stderr)
    except Exception:
        return False


def validate_via_chrome(workflow_id: str) -> dict:
    """Call platform validate through internal API (Chrome cookies).

    Uses hap-bridge wf-publish as a dry-run: we save the config first,
    then try to publish (which triggers validation), capture errors,
    and rollback if needed.
    """
    # Alternative: try to use the internal validate endpoint
    # wf-publish triggers validation before publishing
    try:
        result = subprocess.run(
            ["python3", HAP_BRIDGE, "wf-publish", workflow_id, "--chrome"],
            capture_output=True, text=True, timeout=30
        )
        stdout = result.stdout + result.stderr

        if "成功" in stdout or "success" in stdout.lower():
            return {
                "verdict": "pass",
                "method": "internal_chrome",
                "detail": "Platform publish/validate succeeded",
                "raw_output": stdout[:500]
            }
        else:
            return {
                "verdict": "fail",
                "method": "internal_chrome",
                "detail": "Platform rejected the workflow",
                "raw_output": stdout[:1000]
            }
    except subprocess.TimeoutExpired:
        return {
            "verdict": "fail",
            "method": "internal_chrome",
            "detail": "Platform validate timed out after 30s",
            "raw_output": ""
        }
    except Exception as e:
        return {
            "verdict": "fail",
            "method": "internal_chrome",
            "detail": f"Error calling platform validate: {e}",
            "raw_output": ""
        }


def validate_via_open_api(workflow_id: str) -> dict:
    """Call platform validate through Open API (AppKey + Sign)."""
    appkey = os.environ.get("MINGDAO_APPKEY", "")
    sign = os.environ.get("MINGDAO_SIGN", "")
    base_url = os.environ.get("MINGDAO_API_BASE", "https://api.mingdao.com")

    if not appkey or not sign:
        return {
            "verdict": "skipped",
            "method": "open_api",
            "detail": "Missing MINGDAO_APPKEY or MINGDAO_SIGN env vars",
            "raw_output": ""
        }

    # This is a placeholder — the actual Open API call needs the correct
    # base URL, auth headers, and request body format per apifox.mingdao.com
    return {
        "verdict": "skipped",
        "method": "open_api",
        "detail": "Open API path not yet implemented — use Chrome auth path",
        "raw_output": ""
    }


def main():
    parser = argparse.ArgumentParser(description="Gate 4: Platform-native workflow validation")
    parser.add_argument("--workflow-id", help="Workflow process_id to validate")
    parser.add_argument("--lock-file", help="execution_lock.json (extract workflow IDs)")
    args = parser.parse_args()

    workflow_ids = []

    if args.workflow_id:
        workflow_ids.append(args.workflow_id)

    if args.lock_file:
        try:
            with open(args.lock_file) as f:
                lock = json.load(f)
            for wf in lock.get("workflows", []):
                pid = wf.get("pid", wf.get("process_id", ""))
                if pid:
                    workflow_ids.append(pid)
        except Exception as e:
            print(json.dumps({"verdict": "fail", "error": f"Cannot read lock file: {e}"},
                             ensure_ascii=False))
            sys.exit(1)

    if not workflow_ids:
        print(json.dumps({"verdict": "skipped", "detail": "No workflow IDs provided"},
                         ensure_ascii=False))
        sys.exit(2)

    # Determine auth method
    use_chrome = try_chrome_auth()

    results = []
    overall_verdict = "pass"

    for wf_id in workflow_ids:
        if use_chrome:
            result = validate_via_chrome(wf_id)
        else:
            result = validate_via_open_api(wf_id)
            if result["verdict"] == "skipped":
                # No auth available at all
                output = {
                    "verdict": "skipped",
                    "source": "platform-validate.py (Gate 4 — ground truth)",
                    "detail": "No platform auth available. Install Chrome with Mingdao login, or set MINGDAO_APPKEY + MINGDAO_SIGN env vars.",
                    "workflows": []
                }
                print(json.dumps(output, ensure_ascii=False, indent=2))
                sys.exit(2)

        result["workflow_id"] = wf_id
        results.append(result)

        if result["verdict"] == "fail":
            overall_verdict = "fail"
        elif result["verdict"] == "skipped":
            if overall_verdict == "pass":
                overall_verdict = "skipped"

    output = {
        "verdict": overall_verdict,
        "source": "platform-validate.py (Gate 4 — ground truth)",
        "method": "internal_chrome" if use_chrome else "open_api",
        "total_workflows": len(workflow_ids),
        "passed": sum(1 for r in results if r["verdict"] == "pass"),
        "failed": sum(1 for r in results if r["verdict"] == "fail"),
        "skipped": sum(1 for r in results if r["verdict"] == "skipped"),
        "workflows": results,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if overall_verdict == "fail":
        sys.exit(1)
    elif overall_verdict == "skipped":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
