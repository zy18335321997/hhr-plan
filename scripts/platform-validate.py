#!/usr/bin/env python3
"""平台只读校验占位入口。

当前尚无经过确认的明道云只读 workflow validate API。此脚本绝不调用发布、
保存或其他写操作；在只读 API 可用前始终明确返回 skipped。

用法:
  python3 platform-validate.py --workflow-id <process_id>
  python3 platform-validate.py --lock-file execution_lock.json

exit code: 2=跳过（没有真实只读 validate API）
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        description="只读平台校验占位入口（当前固定 skipped）"
    )
    parser.add_argument("--workflow-id", help="Workflow process_id to validate")
    parser.add_argument("--lock-file", help="execution_lock.json (extract workflow IDs)")
    args = parser.parse_args()

    workflow_ids = [args.workflow_id] if args.workflow_id else []
    if args.lock_file:
        try:
            with open(args.lock_file, encoding="utf-8") as f:
                lock = json.load(f)
            for wf in lock.get("workflows", []):
                pid = wf.get("pid", wf.get("process_id", ""))
                if pid:
                    workflow_ids.append(pid)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "error": f"Cannot read lock file: {exc}",
                    },
                    ensure_ascii=False,
                )
            )
            return 1

    output = {
        "verdict": "skipped",
        "source": "platform-validate.py",
        "method": "none",
        "detail": (
            "尚无经过确认的明道云只读 workflow validate API；"
            "为避免发布或保存等写操作，本检查未执行"
        ),
        "total_workflows": len(workflow_ids),
        "passed": 0,
        "failed": 0,
        "skipped": len(workflow_ids),
        "workflows": [
            {"workflow_id": workflow_id, "verdict": "skipped"}
            for workflow_id in workflow_ids
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
