#!/usr/bin/env python3
"""Mode D 审计回归测试 — 对确定性审计指标做快照回归。

用法:
  python3 regression_test.py --project 几建
  python3 regression_test.py --project 几建 --update-golden
  python3 regression_test.py --project 几建 --quiet
  python3 regression_test.py --check-format    # CI: 只验证 snapshot 格式
  python3 regression_test.py --project ci-minimal --fixture-dir tests/fixtures/regression

设计:
  - 只比较确定性数据 (脚本提取的指标), 不比较 LLM 生成的 prose
  - 双向依赖比较用集合 (顺序无关)
  - --fixture-dir 使用仓库内 data/ + snapshots/ 做真实 CI 比较
  - --data-root 可注入项目数据根目录，避免依赖 ~/Documents
  - --update-golden 标志刷新快照
  - 公理评分标记为 comparison: "delegated" (需 LLM 判断)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
REGRESSION_DIR = SKILL_DIR / "references" / "regression"
WORKFLOW_OUTPUT = Path.home() / "Documents" / "workflow-output"

SNAPSHOT_VERSION = "1.0"


def extract_metrics(
    project_name: str,
    data_root: Path | str = WORKFLOW_OUTPUT,
) -> tuple[dict, list[str]]:
    """从项目数据文件中提取确定性指标。"""
    proj_dir = Path(data_root) / project_name
    ctx_file = proj_dir / "project_context.json"
    dg_file = proj_dir / "dependency_graph.json"
    nd_file = proj_dir / "_node_data.json"

    errors = []
    metrics = {}

    # worksheet count from project_context.json
    if ctx_file.is_file():
        with open(ctx_file, encoding="utf-8") as f:
            ctx = json.load(f)
        metrics["worksheet_count"] = len(ctx.get("worksheets", {}))
    else:
        errors.append(f"project_context.json 缺失: {ctx_file}")

    # dependency graph metrics
    if dg_file.is_file():
        with open(dg_file, encoding="utf-8") as f:
            dg = json.load(f)
        nodes = dg.get("nodes", {})
        edges = dg.get("edges", [])
        metrics["dependency_graph"] = {
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        # bidirectional edge detection
        adj = {}
        for e in edges:
            src = e.get("source") or e.get("from_sheet", "")
            tgt = e.get("target") or e.get("to_sheet", "")
            if src and tgt:
                adj.setdefault(src, set()).add(tgt)
        bidir = []
        for src in adj:
            for tgt in adj[src]:
                if tgt in adj and src in adj[tgt] and src < tgt:
                    bidir.append(f"{src}↔{tgt}")
        metrics["dependency_graph"]["bidirectional_edge_pairs"] = bidir
    else:
        errors.append(f"dependency_graph.json 缺失: {dg_file}")

    # workflow count from _node_data.json
    if nd_file.is_file():
        with open(nd_file, encoding="utf-8") as f:
            nd = json.load(f)
        metrics["workflow_count"] = len(nd) if isinstance(nd, dict) else 0
    else:
        errors.append(f"_node_data.json 缺失: {nd_file}")

    return metrics, errors


def build_snapshot(project_name: str, metrics: dict, errors: list) -> dict:
    """构建完整的 golden snapshot。"""
    return {
        "project": project_name,
        "snapshot_version": SNAPSHOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "regression_test.py",
        "metrics": metrics,
        "axiom_scores": {
            "comparison": "delegated",
            "note": "公理评分需要 LLM 判断, 不做确定性比较"
        },
        "extraction_errors": errors,
    }


def snapshot_path(
    project_name: str,
    snapshot_dir: Path | str = REGRESSION_DIR,
) -> Path:
    return Path(snapshot_dir) / f"{project_name}-snapshot.json"


def load_golden(
    project_name: str,
    snapshot_dir: Path | str = REGRESSION_DIR,
) -> dict | None:
    sp = snapshot_path(project_name, snapshot_dir)
    if not sp.exists():
        return None
    with open(sp, encoding="utf-8") as f:
        return json.load(f)


# ── 比较逻辑 ──

def compare_metrics(current: dict, golden: dict) -> list:
    """比较当前指标与 golden snapshot, 返回差异列表。"""
    diffs = []
    gm = golden.get("metrics", {})

    # worksheet_count
    if "worksheet_count" in gm:
        cw = current.get("worksheet_count")
        gw = gm["worksheet_count"]
        if cw != gw:
            diffs.append({
                "metric": "worksheet_count",
                "golden": gw,
                "current": cw,
                "verdict": "fail",
                "detail": f"worksheet_count 不匹配: golden={gw}, current={cw}"
            })
        else:
            diffs.append({
                "metric": "worksheet_count",
                "golden": gw,
                "current": cw,
                "verdict": "pass",
            })

    # workflow_count
    if "workflow_count" in gm:
        cw = current.get("workflow_count")
        gw = gm["workflow_count"]
        if cw != gw:
            diffs.append({
                "metric": "workflow_count",
                "golden": gw,
                "current": cw,
                "verdict": "fail",
                "detail": f"workflow_count 不匹配: golden={gw}, current={cw}"
            })
        else:
            diffs.append({
                "metric": "workflow_count",
                "golden": gw,
                "current": cw,
                "verdict": "pass",
            })

    # dependency_graph
    gdg = gm.get("dependency_graph", {})
    cdg = current.get("dependency_graph", {})
    if gdg and cdg:
        # node_count
        gn = gdg.get("node_count")
        cn = cdg.get("node_count")
        if gn != cn:
            diffs.append({
                "metric": "dependency_graph.node_count",
                "golden": gn,
                "current": cn,
                "verdict": "fail",
                "detail": f"node_count 不匹配: golden={gn}, current={cn}"
            })
        else:
            diffs.append({
                "metric": "dependency_graph.node_count",
                "golden": gn,
                "current": cn,
                "verdict": "pass",
            })

        # edge_count
        ge = gdg.get("edge_count")
        ce = cdg.get("edge_count")
        if ge != ce:
            diffs.append({
                "metric": "dependency_graph.edge_count",
                "golden": ge,
                "current": ce,
                "verdict": "fail",
                "detail": f"edge_count 不匹配: golden={ge}, current={ce}"
            })
        else:
            diffs.append({
                "metric": "dependency_graph.edge_count",
                "golden": ge,
                "current": ce,
                "verdict": "pass",
            })

        # bidirectional_edge_pairs (集合比较, 顺序无关)
        gb = set(gdg.get("bidirectional_edge_pairs", []))
        cb = set(cdg.get("bidirectional_edge_pairs", []))
        if gb != cb:
            only_golden = gb - cb
            only_current = cb - gb
            detail_parts = []
            if only_golden:
                detail_parts.append(f"仅在 golden 中: {sorted(only_golden)}")
            if only_current:
                detail_parts.append(f"仅在 current 中: {sorted(only_current)}")
            diffs.append({
                "metric": "dependency_graph.bidirectional_edge_pairs",
                "golden": sorted(gb),
                "current": sorted(cb),
                "verdict": "fail",
                "detail": "; ".join(detail_parts),
            })
        else:
            diffs.append({
                "metric": "dependency_graph.bidirectional_edge_pairs",
                "golden_count": len(gb),
                "current_count": len(cb),
                "verdict": "pass",
            })

    return diffs


# ── 命令实现 ──

def cmd_run(
    project_name: str,
    update_golden: bool = False,
    quiet: bool = False,
    data_root: Path | str = WORKFLOW_OUTPUT,
    snapshot_dir: Path | str = REGRESSION_DIR,
):
    """运行回归测试。"""
    # 提取当前指标
    current_metrics, errors = extract_metrics(project_name, data_root=data_root)

    if update_golden:
        snapshot = build_snapshot(project_name, current_metrics, errors)
        sp = snapshot_path(project_name, snapshot_dir)
        Path(snapshot_dir).mkdir(parents=True, exist_ok=True)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            f.write("\n")
        output = {
            "verdict": "pass",
            "action": "golden_updated",
            "snapshot_path": str(sp),
            "metrics": current_metrics,
            "errors": errors,
        }
        if not quiet:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"verdict": "pass", "action": "golden_updated"}, ensure_ascii=False))
        sys.exit(0)

    # 加载 golden
    golden = load_golden(project_name, snapshot_dir=snapshot_dir)
    if golden is None:
        print(json.dumps({
            "verdict": "fail",
            "error": (
                "Golden snapshot 不存在: "
                f"{snapshot_path(project_name, snapshot_dir)}"
            ),
            "fix": f"运行: python3 scripts/regression_test.py --project {project_name} --update-golden"
        }, ensure_ascii=False))
        sys.exit(1)

    # 比较
    diffs = compare_metrics(current_metrics, golden)
    has_extraction_errors = len(errors) > 0
    has_diff_failures = any(d["verdict"] == "fail" for d in diffs)
    verdict = "fail" if (has_diff_failures or has_extraction_errors) else "pass"

    output = {
        "verdict": verdict,
        "source": "regression_test.py",
        "project": project_name,
        "snapshot_path": str(snapshot_path(project_name, snapshot_dir)),
        "golden_generated_at": golden.get("generated_at"),
        "comparisons": diffs,
        "extraction_errors": errors,
        "axiom_scores": {"comparison": "delegated"},
    }

    if quiet:
        print(json.dumps({
            "verdict": verdict,
            "failures": sum(1 for d in diffs if d["verdict"] == "fail"),
            "errors": len(errors),
        }, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


def cmd_check_format(
    snapshot_dir: Path | str = REGRESSION_DIR,
):
    """CI 模式: 只验证 snapshot 格式和结构, 不做实际数据比较。"""
    violations = []
    regression_dir = Path(snapshot_dir)

    if not regression_dir.exists():
        print(json.dumps({
            "verdict": "fail",
            "error": f"Regression 目录不存在: {regression_dir}"
        }, ensure_ascii=False))
        sys.exit(1)

    snapshots = sorted(regression_dir.glob("*-snapshot.json"))
    if not snapshots:
        print(json.dumps({
            "verdict": "warn",
            "message": "没有找到 golden snapshot 文件"
        }, ensure_ascii=False))
        sys.exit(0)

    for sp in snapshots:
        try:
            with open(sp) as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            violations.append({
                "severity": "high",
                "snapshot": sp.name,
                "detail": f"JSON 解析失败: {e}"
            })
            continue

        # 验证必需字段
        required = ["project", "snapshot_version", "metrics", "axiom_scores"]
        for key in required:
            if key not in data:
                violations.append({
                    "severity": "high",
                    "snapshot": sp.name,
                    "detail": f"缺少必需字段: {key}"
                })

        metrics = data.get("metrics", {})
        if not isinstance(metrics, dict):
            violations.append({
                "severity": "high",
                "snapshot": sp.name,
                "detail": "metrics 不是 dict"
            })
        else:
            for mk in ["worksheet_count", "workflow_count", "dependency_graph"]:
                if mk not in metrics:
                    violations.append({
                        "severity": "medium",
                        "snapshot": sp.name,
                        "detail": f"metrics 缺少: {mk}"
                    })

            dg = metrics.get("dependency_graph", {})
            if isinstance(dg, dict):
                for dk in ["node_count", "edge_count", "bidirectional_edge_pairs"]:
                    if dk not in dg:
                        violations.append({
                            "severity": "medium",
                            "snapshot": sp.name,
                            "detail": f"metrics.dependency_graph 缺少: {dk}"
                        })

        # 验证 axiom_scores comparison 标记
        axiom = data.get("axiom_scores", {})
        if axiom.get("comparison") != "delegated":
            violations.append({
                "severity": "low",
                "snapshot": sp.name,
                "detail": "axiom_scores.comparison 应标记为 'delegated'"
            })

    verdict = "pass" if len(violations) == 0 else "fail"

    output = {
        "verdict": verdict,
        "source": "regression_test.py --check-format",
        "snapshots_checked": len(snapshots),
        "snapshot_files": [sp.name for sp in snapshots],
        "violations": violations,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Mode D 审计回归测试")
    parser.add_argument("--project", help="项目名称 (如 几建)")
    parser.add_argument("--update-golden", action="store_true", help="刷新 golden snapshot")
    parser.add_argument("--quiet", action="store_true", help="精简输出")
    parser.add_argument("--check-format", action="store_true",
                        help="CI 模式: 只验证 snapshot 格式, 不做数据比较")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--fixture-dir",
        help="自包含 fixture 根目录（含 data/ 与 snapshots/）",
    )
    source.add_argument(
        "--data-root",
        help="项目数据根目录（含 <project>/ 子目录）",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root) if args.data_root else WORKFLOW_OUTPUT
    snapshot_dir = REGRESSION_DIR
    if args.fixture_dir:
        fixture_dir = Path(args.fixture_dir)
        data_root = fixture_dir / "data"
        snapshot_dir = fixture_dir / "snapshots"

    if args.check_format:
        cmd_check_format(snapshot_dir=snapshot_dir)
    elif args.project:
        cmd_run(
            args.project,
            update_golden=args.update_golden,
            quiet=args.quiet,
            data_root=data_root,
            snapshot_dir=snapshot_dir,
        )
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
