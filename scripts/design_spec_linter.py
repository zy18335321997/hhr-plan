#!/usr/bin/env python3
"""Lint a human design_spec.md against execution_lock.design_ir."""

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = {
    "结论",
    "客户需求追踪",
    "角色与权限",
    "实体与字段",
    "状态机",
    "工作流",
    "视图与按钮",
    "异常与恢复",
    "门控结果",
}


def lint_spec(markdown: str, lock: dict) -> list[dict]:
    issues = []
    headings = {
        re.sub(r"\s+", "", match.group(1))
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE)
    }
    for section in sorted(REQUIRED_SECTIONS):
        if not any(section in heading for heading in headings):
            issues.append(
                {
                    "code": "SPEC_SECTION_MISSING",
                    "section": section,
                    "detail": f"design_spec 缺少章节: {section}",
                }
            )
    requirements = lock.get("design_ir", {}).get("requirements", [])
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = requirement.get("id")
        if requirement_id and requirement_id not in markdown:
            issues.append(
                {
                    "code": "SPEC_REQUIREMENT_UNTRACED",
                    "requirement_id": requirement_id,
                    "detail": f"design_spec 未引用需求 {requirement_id}",
                }
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查 design_spec 必填章节和需求追踪"
    )
    parser.add_argument("design_spec")
    parser.add_argument("--lock-file", required=True)
    args = parser.parse_args()
    try:
        markdown = Path(args.design_spec).read_text(encoding="utf-8")
        lock = json.loads(Path(args.lock_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}, ensure_ascii=False))
        return 2
    issues = lint_spec(markdown, lock)
    print(
        json.dumps(
            {"verdict": "fail" if issues else "pass", "issues": issues},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
