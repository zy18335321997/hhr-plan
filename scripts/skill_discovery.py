#!/usr/bin/env python3
"""技能注册表发现与校验 — 从 YAML 描述符 + Python 脚本扫描生成注册表。

用法:
  python3 skill_discovery.py generate              # 生成 JSON 到 stdout
  python3 skill_discovery.py generate -o path.json  # 生成 JSON 到文件
  python3 skill_discovery.py validate               # 校验已提交的注册表一致性
  python3 skill_discovery.py validate --strict      # 严格模式: 发现未注册项时报错

设计:
  - YAML 解析用行级正则 (描述符结构简单且高度规整)，不引入 pyyaml
  - 注册表从源文件自动生成，validate 检查 drift
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
DESCRIPTORS_DIR = SKILL_DIR / "agents" / "descriptors"
SCRIPTS_DIR = SKILL_DIR / "scripts"
REGISTRY_PATH = SKILL_DIR / "references" / "skill-registry.json"


# ── YAML 描述符解析 (行级正则) ──

def parse_yaml_descriptor(filepath: Path) -> dict:
    """从单个 YAML 描述符文件中解析 interface 块。

    使用行级正则 (无 pyyaml 依赖)。描述符结构规整:
      - 顶层键在 2-space indent (interface 下)
      - 列表项在 4-space indent, 以 "- " 开头
      - 嵌套 dict 键在 4-space indent, 以 "key: value" 形式
    """
    with open(filepath) as f:
        lines = f.readlines()

    result = {}
    current_key = None       # 当前正在填充的顶层键名
    current_is_dict = False  # current_key 的值是 dict (非 list)

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped == "interface:":
            continue

        # ── 顶层标量: "  key: "value"" ──
        m = re.match(r'^  (\w+):\s*"(.*)"\s*$', stripped)
        if m:
            key, val = m.group(1), m.group(2)
            current_key = key
            current_is_dict = False
            result[key] = val
            continue

        # ── 顶层标量 (无引号): "  key: value" 或 "  key:" ──
        m = re.match(r'^  (\w+):\s*(.*)$', stripped)
        if m:
            key, val = m.group(1), m.group(2).strip()
            current_key = key
            if val == "":
                # 值待定 — 可能是 list 或 dict, 由后续子行决定
                current_is_dict = False
                # 不在 result 中预设类型, 等第一个子元素
            else:
                current_is_dict = False
                result[key] = val
            continue

        # ── 嵌套 dict 键 (4-space indent, key: "value") ──
        # 必须先于 list item 检查, 否则 "key: value" 可能被误匹配
        m = re.match(r'^    (\w+):\s*"(.*)"\s*$', stripped)
        if m:
            nk, nv = m.group(1), m.group(2)
            if current_key:
                if current_key not in result or not isinstance(result[current_key], dict):
                    result[current_key] = {}
                result[current_key][nk] = nv
                current_is_dict = True
            continue

        m = re.match(r'^    (\w+):\s*(.+)$', stripped)
        if m:
            nk, nv = m.group(1), m.group(2).strip()
            if current_key:
                if current_key not in result or not isinstance(result[current_key], dict):
                    result[current_key] = {}
                result[current_key][nk] = nv
                current_is_dict = True
            continue

        # ── 列表项 (4-space indent, "- value") ──
        m = re.match(r'^    - "(.*)"\s*$', stripped)
        if m:
            val = m.group(1)
            if current_key and not current_is_dict:
                if current_key not in result or not isinstance(result[current_key], list):
                    result[current_key] = []
                result[current_key].append(val)
            continue

        m = re.match(r'^    - (.*)$', stripped)
        if m:
            val = m.group(1).strip()
            if current_key and not current_is_dict:
                if current_key not in result or not isinstance(result[current_key], list):
                    result[current_key] = []
                result[current_key].append(val)
            continue

    return result


def scan_descriptors() -> dict:
    """扫描所有 YAML 描述符，返回 {mode_id: interface_data}。"""
    modes = {}
    if not DESCRIPTORS_DIR.exists():
        return modes

    for yaml_file in sorted(DESCRIPTORS_DIR.glob("*.yaml")):
        mode_id = yaml_file.stem  # e.g. "mode-a-greenfield"
        try:
            iface = parse_yaml_descriptor(yaml_file)
            iface["_descriptor_path"] = str(yaml_file.relative_to(SKILL_DIR))
            # Derive skill_md path from references
            refs = iface.get("references", [])
            skill_md = None
            agent_md = None
            for ref in (refs if isinstance(refs, list) else []):
                if ref.startswith("built-in-skills/"):
                    skill_md = ref
                if ref.startswith("agents/") and ref.endswith(".md"):
                    agent_md = ref
            iface["skill_md"] = skill_md
            iface["agent_md"] = agent_md
            modes[mode_id] = iface
        except Exception as e:
            print(f"WARNING: Failed to parse {yaml_file}: {e}", file=sys.stderr)

    return modes


# ── Python 脚本扫描 ──

def scan_python_scripts() -> dict:
    """扫描 scripts/*.py, 提取 argparse 接口。返回 {script_name: info}。"""
    scripts = {}

    for py_file in sorted(SCRIPTS_DIR.glob("*.py")):
        # Skip the discovery script itself and __init__.py
        if py_file.name == "skill_discovery.py" or py_file.name.startswith("_"):
            continue

        info = {"description": "", "arguments": []}
        with open(py_file) as f:
            content = f.read()

        # Extract module docstring
        m = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if m:
            doc = m.group(1).strip()
            # Take first line as description
            first_line = doc.split("\n")[0].strip()
            info["description"] = first_line

        # Extract argparse arguments
        for arg_match in re.finditer(
            r'add_argument\(\s*["\'](--?[\w-]+)["\']',
            content
        ):
            info["arguments"].append(arg_match.group(1))

        scripts[py_file.name] = info

    return scripts


# ── 注册表生成与校验 ──

def generate_registry() -> dict:
    """生成完整注册表。"""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "skill_discovery.py",
        "skill_dir": str(SKILL_DIR),
        "modes": scan_descriptors(),
        "scripts": scan_python_scripts(),
    }


def cmd_generate(output_path: str = None, quiet: bool = False):
    """生成注册表 JSON。"""
    registry = generate_registry()
    json_str = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"

    if output_path:
        with open(output_path, "w") as f:
            f.write(json_str)
        if not quiet:
            print(f"Registry written to {output_path}")
    else:
        print(json_str)


def cmd_validate(strict: bool = False):
    """校验已提交的注册表与源文件一致。"""
    if not REGISTRY_PATH.exists():
        print(json.dumps({
            "verdict": "fail",
            "error": f"Registry file not found: {REGISTRY_PATH}",
            "fix": "Run: python3 scripts/skill_discovery.py generate -o references/skill-registry.json"
        }, ensure_ascii=False))
        sys.exit(1)

    # Load committed registry
    with open(REGISTRY_PATH) as f:
        committed = json.load(f)

    # Generate fresh registry from source
    fresh = generate_registry()

    violations = []

    # Compare modes
    committed_modes = committed.get("modes", {})
    fresh_modes = fresh.get("modes", {})

    # Check for missing modes
    for mode_id in sorted(fresh_modes):
        if mode_id not in committed_modes:
            violations.append({
                "severity": "high",
                "detail": f"Mode '{mode_id}' exists in descriptors but not in registry"
            })

    # Check for extra modes
    for mode_id in sorted(committed_modes):
        if mode_id not in fresh_modes:
            violations.append({
                "severity": "high",
                "detail": f"Mode '{mode_id}' exists in registry but no descriptor found"
            })

    # Compare mode interfaces (only structural fields, not generated_at etc)
    for mode_id in sorted(set(fresh_modes) & set(committed_modes)):
        fresh_iface = {k: v for k, v in fresh_modes[mode_id].items()
                       if not k.startswith("_")}
        committed_iface = {k: v for k, v in committed_modes[mode_id].items()
                           if not k.startswith("_")}

        if fresh_iface != committed_iface:
            # Find specific differences
            for key in sorted(set(fresh_iface) | set(committed_iface)):
                fv = fresh_iface.get(key)
                cv = committed_iface.get(key)
                if fv != cv:
                    violations.append({
                        "severity": "medium",
                        "detail": f"Mode '{mode_id}' field '{key}' differs: "
                                  f"descriptor has {json.dumps(fv, ensure_ascii=False)}"
                    })

    # Compare scripts
    committed_scripts = committed.get("scripts", {})
    fresh_scripts = fresh.get("scripts", {})

    for script_name in sorted(fresh_scripts):
        if script_name not in committed_scripts:
            if strict:
                violations.append({
                    "severity": "medium",
                    "detail": f"Script '{script_name}' missing from registry"
                })
            else:
                violations.append({
                    "severity": "low",
                    "detail": f"Script '{script_name}' missing from registry (run generate to add)"
                })

    for script_name in sorted(committed_scripts):
        if script_name not in fresh_scripts:
            violations.append({
                "severity": "medium",
                "detail": f"Script '{script_name}' in registry but file not found"
            })

    # Check referenced tools exist
    for mode_id, iface in fresh_modes.items():
        tools = iface.get("tools", [])
        if isinstance(tools, list):
            for tool in tools:
                # Extract just the script path: strip args and Chinese annotations
                clean_tool = tool.split(" ")[0].split("（")[0].split("(")[0]
                # Only check tools that are scripts/ paths
                if clean_tool.startswith("scripts/"):
                    tool_path = SKILL_DIR / clean_tool
                    if not tool_path.exists():
                        violations.append({
                            "severity": "high",
                            "detail": f"Mode '{mode_id}' references missing tool: {tool}"
                        })

    # Check referenced built-in skills exist
    for mode_id, iface in fresh_modes.items():
        skill_md = iface.get("skill_md")
        if skill_md:
            skill_path = SKILL_DIR / skill_md
            if not skill_path.exists():
                violations.append({
                    "severity": "high",
                    "detail": f"Mode '{mode_id}' references missing skill: {skill_md}"
                })

    # Output
    verdict = "pass" if len(violations) == 0 else "fail"

    output = {
        "verdict": verdict,
        "source": "skill_discovery.py validate",
        "registry_path": str(REGISTRY_PATH),
        "total_modes": len(fresh_modes),
        "total_scripts": len(fresh_scripts),
        "violations": violations,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict == "pass" else 1)


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="技能注册表发现与校验")
    sub = parser.add_subparsers(dest="command", help="子命令")

    gen = sub.add_parser("generate", help="从源文件生成注册表 JSON")
    gen.add_argument("-o", "--output", help="输出文件路径 (默认 stdout)")

    val = sub.add_parser("validate", help="校验注册表与源文件一致性")
    val.add_argument("--strict", action="store_true", help="严格模式: 发现未注册脚本时报错")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(output_path=args.output)
    elif args.command == "validate":
        cmd_validate(strict=args.strict)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
