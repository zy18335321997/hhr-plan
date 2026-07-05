#!/usr/bin/env python3
"""验证覆盖台账格式完整性和一致性。

用法:
  python3 verify-ledger.py [--strict]

--strict: 同时检查所有约束是否在 system-prompt.md 中有对应（需要读取源文件）
"""

import csv
import sys
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "references" / "axioms" / "coverage-ledger.tsv"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "system-prompt.md"

REQUIRED_COLUMNS = [
    "axiom_id", "constraint_id", "constraint_type", "description",
    "evidence_source", "positive_cases", "known_failures",
    "validated_projects", "last_validated", "status"
]
VALID_CONSTRAINT_TYPES = {"MUST", "MUST_NOT"}
VALID_STATUSES = {"observed", "validating", "validated", "locked"}
VALID_AXIOM_IDS = {"1", "2", "3", "4", "5"}
VALID_SEVERITIES = {"high", "medium", "low"}


def main():
    violations = []

    # ── Check file exists ──
    if not LEDGER_PATH.exists():
        print(f"FAIL: {LEDGER_PATH} not found")
        sys.exit(1)

    # ── Parse TSV ──
    with open(LEDGER_PATH) as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    if len(rows) == 0:
        violations.append({"severity": "high", "detail": "Ledger is empty"})

    # ── Check header ──
    with open(LEDGER_PATH) as f:
        header = f.readline().strip().split("\t")
    missing_cols = set(REQUIRED_COLUMNS) - set(header)
    if missing_cols:
        violations.append({"severity": "high",
                           "detail": f"Missing columns: {missing_cols}"})
    extra_cols = set(header) - set(REQUIRED_COLUMNS)
    if extra_cols:
        violations.append({"severity": "low",
                           "detail": f"Extra columns (will be ignored): {extra_cols}"})

    # ── Per-row validation ──
    seen_ids = set()
    axiom_coverage = {a: {"MUST": 0, "MUST_NOT": 0} for a in VALID_AXIOM_IDS}
    total_must = 0
    total_must_not = 0

    for i, row in enumerate(rows, start=2):  # line 2 (1-indexed in file)
        cid = row.get("constraint_id", "").strip()
        aid = row.get("axiom_id", "").strip()
        ctype = row.get("constraint_type", "").strip()
        status = row.get("status", "").strip()
        desc = row.get("description", "").strip()
        evidence = row.get("evidence_source", "").strip()

        # constraint_id
        if not cid:
            violations.append({"severity": "high",
                               "detail": f"Line {i}: empty constraint_id"})
        elif cid in seen_ids:
            violations.append({"severity": "high",
                               "detail": f"Line {i}: duplicate constraint_id: {cid}"})
        else:
            seen_ids.add(cid)
            # Check format: "N.M"
            parts = cid.split(".")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                violations.append({"severity": "medium",
                                   "detail": f"Line {i}: constraint_id '{cid}' should be 'N.M' format"})

        # axiom_id
        if aid not in VALID_AXIOM_IDS:
            violations.append({"severity": "high",
                               "detail": f"Line {i}: invalid axiom_id: {aid}"})

        # constraint_type
        if ctype not in VALID_CONSTRAINT_TYPES:
            violations.append({"severity": "medium",
                               "detail": f"Line {i}: invalid constraint_type: {ctype}"})
        else:
            if aid in VALID_AXIOM_IDS:
                axiom_coverage[aid][ctype] += 1
            if ctype == "MUST":
                total_must += 1
            else:
                total_must_not += 1

        # status
        if status not in VALID_STATUSES:
            violations.append({"severity": "medium",
                               "detail": f"Line {i}: invalid status: {status}"})

        # description
        if not desc:
            violations.append({"severity": "medium",
                               "detail": f"Line {i}: empty description"})

        # evidence_source
        if not evidence:
            violations.append({"severity": "low",
                               "detail": f"Line {i}: empty evidence_source"})

    # ── Axiom coverage check ──
    for aid in sorted(VALID_AXIOM_IDS):
        cov = axiom_coverage[aid]
        if cov["MUST"] == 0 and cov["MUST_NOT"] == 0:
            violations.append({"severity": "high",
                               "detail": f"Axiom {aid}: no constraints tracked at all"})
        elif cov["MUST"] == 0:
            violations.append({"severity": "medium",
                               "detail": f"Axiom {aid}: no MUST constraints tracked"})
        elif cov["MUST_NOT"] == 0:
            violations.append({"severity": "medium",
                               "detail": f"Axiom {aid}: no MUST_NOT constraints tracked"})

    # ── Summary ──
    verdict = "pass" if len(violations) == 0 else "fail"
    summary = {
        "verdict": verdict,
        "total_constraints": len(rows),
        "unique_constraint_ids": len(seen_ids),
        "total_must": total_must,
        "total_must_not": total_must_not,
        "axiom_coverage": {
            aid: {"MUST": cov["MUST"], "MUST_NOT": cov["MUST_NOT"]}
            for aid, cov in sorted(axiom_coverage.items())
        },
        "violations": [
            {"severity": v["severity"], "detail": v["detail"]}
            for v in violations
        ],
    }

    # ── Strict mode: cross-check with system-prompt.md ──
    if "--strict" in sys.argv and SYSTEM_PROMPT_PATH.exists():
        with open(SYSTEM_PROMPT_PATH) as f:
            sp_content = f.read()

        missing_from_ledger = []

        # Check that all MUST/MUST_NOT from system-prompt are in the ledger
        for aid in VALID_AXIOM_IDS:
            # Count MUST/MUST_NOT rows in the constraint tables
            # Simple heuristic: count table rows starting with |
            in_axiom_section = False
            table_rows = 0
            for line in sp_content.split("\n"):
                if f"公理 {aid}:" in line or f"公理{aid}:" in line:
                    in_axiom_section = True
                    continue
                if in_axiom_section and line.startswith("### "):
                    break  # Next axiom section
                if in_axiom_section and line.startswith("|") and "MUST" in line:
                    table_rows += 1

            # This is approximate; the real check would parse the markdown tables
            # For now, just note if coverage seems low
            ledger_count = sum(1 for r in rows if r["axiom_id"] == aid)
            if table_rows > 0 and ledger_count < table_rows - 1:  # -1 for header
                missing_from_ledger.append(
                    f"Axiom {aid}: ~{table_rows - 1} table rows in system-prompt, "
                    f"but only {ledger_count} in ledger (may have constraints not tracked)"
                )

        if missing_from_ledger:
            summary["strict_check"] = {
                "result": "warn",
                "details": missing_from_ledger
            }

    # ── Output ──
    import json
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


if __name__ == "__main__":
    main()
