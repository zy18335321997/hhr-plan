#!/usr/bin/env python3
"""
Customer-Facing Operations Guide Generator
Produces per-worksheet user guides from project config data.

Usage:
    python3 scripts/generate_manual.py <project_root> --customer [output_dir]
    python3 scripts/generate_manual.py <project_root>                # dev manual

Output with --customer:
    references/guides/<worksheet_name>.md — one guide per worksheet
    references/guides/INDEX.md — overview and quick reference
"""

import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_id_name_map(project_root):
    root = Path(project_root)
    ds_labels = defaultdict(Counter)
    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue
            fp = ws_dir / "fields.json"
            if not fp.exists():
                continue
            try:
                fd = load_json(fp)
                for f in fd.get("fields", []):
                    ds = f.get("dataSource", "")
                    if ds and f.get("type") in [29, 34]:
                        ds_labels[ds][f.get("controlName", "")] += 1
            except:
                pass
    return {ds_id: labels.most_common(1)[0][0] if labels else ds_id
            for ds_id, labels in ds_labels.items()}


# ── Config → Customer Language Translators ────────────────────────────────

TYPE_HINTS = {
    2: "填写文字内容",
    6: "填写数字",
    8: "填写金额",
    15: "选择日期",
    16: "选择日期和时间",
    14: "上传文件",
    26: "选择人员",
    36: "打开/关闭开关",
    33: "系统自动生成，无需填写",
    11: "从下拉选项中选择",
    29: "从已有的记录中选择关联",
    34: "在表格中逐行填写明细",
    38: "系统自动计算，无需填写",
    37: "系统自动汇总，无需填写",
    30: "自动显示关联数据，无需填写",
    25: "自动显示大写金额，无需填写",
    31: "系统自动计算，无需填写",
    32: "系统自动生成，无需填写",
}


def field_to_guide(f, id_to_name):
    """Convert a field config to a customer-facing instruction line."""
    t = f.get("type", 0)
    name = f.get("controlName", "?")
    req = f.get("required", False)
    hint = f.get("hint", "")
    opts = f.get("options", [])
    ds = f.get("dataSource", "")
    default_val = f.get("default", "")

    lines = []

    # What is this field?
    action = TYPE_HINTS.get(t, "填写")
    marker = "【必填】" if req else ""
    lines.append(f"**{name}** {marker}")

    # How to fill it
    if t in [29, 30]:
        resolved = id_to_name.get(ds, ds) if ds else ""
        if t == 29 and resolved:
            lines.append(f"> 从「{resolved}」中选择关联的记录")
        elif t == 30:
            lines.append(f"> 选择关联记录后自动显示，无需手动填写")
    elif t == 34 and ds:
        resolved = id_to_name.get(ds, ds)
        lines.append(f"> 在下方表格中逐行填写每一条明细")
    elif t == 11 and opts:
        lines.append(f"> 从以下选项中选择：")
        for o in opts:
            color = o.get("color", "")
            lines.append(f"> 　• {o.get('value', '?')}")
    elif t == 33:
        lines.append(f"> 系统自动生成编号，格式：拼音缩写 + 日期 + 序号")
    elif t in [36]:
        lines.append(f"> 点击开关：打开 = 是，关闭 = 否")
    elif t in [38, 37, 31]:
        lines.append(f"> 系统根据其他字段自动计算")
    elif hint:
        lines.append(f"> {hint}")
    else:
        lines.append(f"> {action}")

    # Default value hint
    if default_val and default_val not in ["", "000"]:
        if "user-self" in str(default_val):
            lines.append(f"> 默认填当前用户")
        elif "today" in str(default_val) or default_val == "2":
            lines.append(f"> 默认填当天日期")

    return "\n".join(lines)


def classify_approval_path(nodes):
    """Extract the approval path into a readable flow."""
    steps = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        node_name = n.get("node", "")
        cfg = n.get("config", "")

        if "发起" in node_name:
            steps.append({"type": "start", "label": "提交申请"})

        elif "分支" in node_name:
            condition = node_name.replace("分支", "").strip()
            steps.append({"type": "branch", "condition": condition, "children": []})

        elif "审批" in node_name and "发起" not in node_name:
            approver = "指定审批人"
            if "按部门层级逐级审批" in cfg:
                approver = "你的直属上级（逐级向上）"
            elif "指定人员" in cfg:
                names = re.findall(r'指定人员[^，]*', cfg)
                if names:
                    approver = names[0].replace("指定人员", "").strip()
            mode = "任意一人审批通过即可" if "或签" in cfg else "需全部审批通过"
            steps.append({"type": "approval", "label": node_name, "approver": approver, "mode": mode})

        elif "抄送" in node_name or ("抄送" in cfg and "通知" in cfg):
            steps.append({"type": "notify", "label": "审批完成后通知相关人员"})

        elif "同意" in node_name:
            steps.append({"type": "pass", "label": "审批通过"})

        elif "拒绝" in node_name:
            steps.append({"type": "reject", "label": "审批退回，修改后可重新提交"})

        elif "更新" in node_name:
            steps.append({"type": "update", "label": "系统自动更新数据"})

        elif "新增" in node_name:
            steps.append({"type": "create", "label": "系统自动创建关联记录"})

    return steps


def approval_path_to_guide(steps, indent=0):
    """Convert approval steps to readable numbered guide."""
    lines = []
    num = 1
    i = 0
    while i < len(steps):
        s = steps[i]

        if s["type"] == "start":
            lines.append(f"{num}. {s['label']}")
            num += 1

        elif s["type"] == "branch":
            # Find the branch body: collect approval nodes until next branch or end
            branch_body = []
            j = i + 1
            while j < len(steps) and steps[j]["type"] not in ["branch"]:
                branch_body.append(steps[j])
                j += 1

            lines.append(f"{num}. 如果{s['condition']}：")
            sub_num = 1
            for bs in branch_body:
                if bs["type"] == "approval":
                    lines.append(f"   {sub_num}) {bs['label']} → {bs['approver']}（{bs['mode']}）")
                    sub_num += 1
                elif bs["type"] == "pass":
                    lines.append(f"   {sub_num}) 审批通过，流程继续")
                    sub_num += 1
                elif bs["type"] == "reject":
                    lines.append(f"   {sub_num}) 审批退回，可根据审批意见修改后重新提交")
                    sub_num += 1
                elif bs["type"] == "notify":
                    lines.append(f"   {sub_num}) 你会收到通知消息")
                    sub_num += 1
            i = j
            num += 1
            continue

        elif s["type"] == "approval":
            lines.append(f"{num}. {s['label']} → {s['approver']}（{s['mode']}）")
            num += 1

        elif s["type"] == "notify":
            lines.append(f"{num}. 审批完成后你会收到通知")
            num += 1

        elif s["type"] == "pass":
            lines.append(f"{num}. ✅ 审批通过")
            num += 1

        elif s["type"] == "reject":
            lines.append(f"{num}. ❌ 审批退回，可根据审批意见修改后重新提交")
            num += 1

        i += 1

    return "\n".join(lines)


def extract_status_field(fields):
    """Find the primary status field and its possible values."""
    for f in fields:
        name = f.get("controlName", "")
        if "状态" in name and f.get("type") == 11:
            opts = f.get("options", [])
            if opts:
                status_map = {
                    "进行中": "正在审批中，请耐心等待",
                    "通过": "已审批通过",
                    "否决": "审批未通过，请查看审批意见后修改重提",
                    "已关闭": "流程已结束",
                    "已升级": "已升级至上级处理",
                    "待接单": "等待处理人接单",
                    "处理中": "处理人正在处理",
                    "待确认": "等待你确认处理结果",
                    "中止": "流程已中止",
                    "待支付": "等待付款",
                    "已支付": "已完成付款",
                    "已入库": "已入库",
                    "已出库": "已出库",
                    "撤回": "已撤回，可修改后重新提交",
                    "作废": "已作废",
                }
                values = []
                for o in opts:
                    v = o.get("value", "")
                    color = o.get("color", "")
                    # Filter garbage: "选项N" with no real meaning
                    if re.match(r'^选项\d+$', v):
                        continue
                    desc = status_map.get(v, v)
                    values.append({"value": v, "description": desc, "color": color})
                if values:
                    return {"field_name": name, "values": values}
    return None


def is_system_field(name, t):
    """Check if a field is a system-managed field that users don't interact with."""
    system_names = [
        "记录ID", "拥有者", "创建人", "创建时间", "最近修改时间", "最近修改人",
        "流程名称", "节点负责人", "发起人", "发起时间", "流程状态", "文本组合",
        "节点开始时间", "审批完成时间", "截止时间", "剩余时间", "数据标题",
    ]
    if name in system_names:
        return True
    if t in [33, 38, 37, 31, 25, 32]:
        return True
    return False


def find_trigger_workflows(wf_dirs, ws_path):
    """Find workflows and categorize by what they do."""
    workflows = []
    if not wf_dirs:
        return workflows

    for wf_sub in sorted(wf_dirs):
        wf_dir = ws_path / wf_sub
        if not wf_dir.is_dir():
            continue
        nc = wf_dir / "node_configs.json"
        if not nc.exists():
            continue
        try:
            nodes = load_json(nc)
        except:
            continue

        wf_name = wf_dir.name
        # Classify
        if "审批" in wf_name:
            wf_type = "审批流程"
        elif "新增" in wf_name or "创建" in wf_name:
            wf_type = "自动创建数据"
        elif "更新" in wf_name or "修改" in wf_name:
            wf_type = "自动更新数据"
        elif "子流程" in wf_name:
            wf_type = "子流程（系统内部使用）"
        elif "推送" in wf_name or "通知" in wf_name:
            wf_type = "通知推送"
        else:
            wf_type = "业务流程"

        # Extract the most useful info
        trigger_info = ""
        for key in ["工作表事件", "自定义动作", "按钮", "时间"]:
            if key in wf_name:
                if "工作表事件" in wf_name:
                    trigger_info = "当你新增或修改记录时自动触发"
                elif "自定义动作" in wf_name or "按钮" in wf_name:
                    trigger_info = "需要你手动点击按钮触发"
                elif "时间" in wf_name:
                    trigger_info = "按设定的时间自动执行"

        workflows.append({
            "name": wf_name,
            "type": wf_type,
            "trigger": trigger_info,
            "nodes": nodes,
        })

    return workflows


def generate_faq(ws_name, fields, workflows, status_field):
    """Generate FAQ from common patterns."""
    faq = []

    # Can I modify after submitting?
    has_approval = any("审批" in wf["name"] for wf in workflows)
    if has_approval:
        faq.append({
            "q": "提交后还能修改吗？",
            "a": "提交后进入审批流程，此时不能直接修改。如果审批被退回，你可以根据审批意见修改后重新提交。如果需要撤回，请联系审批人。"
        })

    # Who is my approver?
    approval_wfs = [wf for wf in workflows if "审批" in wf["name"]]
    if approval_wfs:
        approvers = set()
        for wf in approval_wfs:
            for n in wf.get("nodes", []):
                if isinstance(n, dict):
                    cfg = n.get("config", "")
                    if "审批" in n.get("node", "") and "发起" not in n.get("node", ""):
                        if "按部门层级逐级审批" in cfg:
                            approvers.add("你的直属上级（系统自动判断）")
                        names = re.findall(r'指定人员[^，]*', cfg)
                        for nm in names:
                            approvers.add(nm.replace("指定人员", "").strip())
        if approvers:
            faq.append({
                "q": "谁审批我的申请？",
                "a": "审批人：" + "、".join(sorted(approvers)[:5]) +
                     (" 等" if len(approvers) > 5 else "")
            })

    # How to check progress?
    if status_field:
        statuses = [v["value"] + "=" + v["description"] for v in status_field["values"]]
        faq.append({
            "q": "怎么看审批进度？",
            "a": f"查看「{status_field['field_name']}」字段：" + "；".join(statuses)
        })

    # What if stuck?
    if has_approval:
        faq.append({
            "q": "审批卡住了怎么办？",
            "a": "查看记录的「节点负责人」字段，确认当前审批在谁手上。如果该审批人不在岗，联系系统管理员将审批转交给在岗人员。"
        })

    # Required fields reminder
    required_fields = [f.get("controlName", "") for f in fields if f.get("required")]
    if required_fields:
        faq.append({
            "q": "哪些字段必须填写？",
            "a": "以下字段为必填：" + "、".join(required_fields[:8]) +
                 (" 等" if len(required_fields) > 8 else "") + "。未填写无法提交。"
        })

    return faq


def generate_customer_guide(ws_name, fields, workflows, status_field, id_to_name):
    """Generate a single worksheet's customer guide."""
    lines = []

    lines.append(f"# {ws_name} 操作指南\n")

    # ── Section 1: What is this? ──
    lines.append("## 这是什么\n")
    has_approval = any("审批" in wf["name"] for wf in workflows)
    has_auto = any(wf["type"] in ["自动创建数据", "自动更新数据"] for wf in workflows)
    main_wf = workflows[0] if workflows else None

    if has_approval:
        lines.append(f"「{ws_name}」用于提交申请并走审批流程。填写完成后提交，系统会自动流转给审批人。")
    elif has_auto:
        lines.append(f"「{ws_name}」用于记录数据，系统会自动同步和更新相关信息。")
    elif workflows:
        lines.append(f"「{ws_name}」用于管理业务流程数据。")
    else:
        lines.append(f"「{ws_name}」用于记录和查阅数据。")
    lines.append("")

    # ── Section 2: How to fill ──
    lines.append("## 如何填写\n")
    lines.append("### 必填字段\n")
    for f in fields:
        if f.get("required") and f.get("type") != 33:
            lines.append(field_to_guide(f, id_to_name))
            lines.append("")
    lines.append("### 选填字段\n")
    for f in fields:
        if not f.get("required") and not is_system_field(f.get("controlName", ""), f.get("type", 0)):
            lines.append(field_to_guide(f, id_to_name))
            lines.append("")

    # ── Section 3: What happens after ──
    if workflows:
        lines.append("## 提交后会发生什么\n")
        # Find the main workflow
        main_wf = None
        for wf in workflows:
            if "审批" in wf["name"]:
                main_wf = wf
                break
        if not main_wf:
            main_wf = workflows[0] if workflows else None

        if main_wf:
            trigger = main_wf.get("trigger", "")
            if trigger:
                lines.append(f"{trigger}。\n")

            lines.append("### 操作流程\n")
            # Simplified, flat flow for customer reading
            node_num = 1
            for n in main_wf["nodes"]:
                if not isinstance(n, dict):
                    continue
                node_name = n.get("node", "")
                cfg = n.get("config", "")

                if "发起" in node_name:
                    lines.append(f"{node_num}. **提交申请** — 填写完成后提交")
                    node_num += 1
                elif "分支" in node_name:
                    condition = node_name.replace("分支", "").strip()
                    lines.append(f"\n> 如果**{condition}**：\n")
                elif "审批" in node_name and "发起" not in node_name:
                    approver = "指定审批人"
                    if "按部门层级逐级审批" in cfg:
                        approver = "你的直属上级（逐级向上）"
                    elif "指定人员" in cfg:
                        names = re.findall(r'指定人员[^，]*', cfg)
                        if names:
                            approver = names[0].replace("指定人员", "").strip()
                    lines.append(f"{node_num}. **{node_name}** → {approver}")
                    node_num += 1
                elif "抄送" in node_name or ("抄送" in cfg and "通知" in node_name):
                    lines.append(f"{node_num}. **通知** — 审批完成后你会收到结果通知")
                    node_num += 1
                elif "同意" in node_name:
                    lines.append(f"   → ✅ 通过")
                elif "拒绝" in node_name:
                    lines.append(f"   → ❌ 退回（可根据审批意见修改后重新提交）")
                elif "更新" in node_name:
                    lines.append(f"   → 系统自动更新数据")
                elif "新增" in node_name:
                    lines.append(f"   → 系统自动创建关联记录")

        # Other workflows
        other_wfs = [w for w in workflows if w != main_wf and w["type"] not in ["子流程（系统内部使用）"]]
        if other_wfs:
            lines.append("### 其他相关操作\n")
            for wf in other_wfs:
                trigger = wf.get("trigger", "")
                lines.append(f"- **{wf['name']}**（{wf['type']}）")
                if trigger:
                    lines.append(f"  {trigger}")
            lines.append("")

    # ── Section 4: Progress tracking ──
    if status_field:
        lines.append("## 如何查看进度\n")
        lines.append(f"查看「**{status_field['field_name']}**」字段：\n")
        for v in status_field["values"]:
            lines.append(f"- **{v['value']}**：{v['description']}")
        lines.append("")

    # ── Section 5: FAQ ──
    faq = generate_faq(ws_name, fields, workflows, status_field)
    if faq:
        lines.append("## 常见问题\n")
        for item in faq:
            lines.append(f"**问：{item['q']}**\n")
            lines.append(f"> {item['a']}\n")

    return "\n".join(lines)


def generate_index(all_guides, project_name):
    """Generate an index of all customer guides."""
    lines = []
    lines.append(f"# {project_name} 操作手册\n")
    lines.append("以下是系统中各模块的操作指南。点击查看具体操作说明。\n")

    by_module = defaultdict(list)
    for g in all_guides:
        by_module[g["module"]].append(g)

    for mod in sorted(by_module.keys()):
        lines.append(f"## {mod}\n")
        for g in sorted(by_module[mod], key=lambda x: x["name"]):
            lines.append(f"- [{g['name']}]({g['file']})")
        lines.append("")

    # Quick reference
    lines.append("## 快速参考\n")
    lines.append("### 我要...\n")
    lines.append("| 操作 | 去哪做 |")
    lines.append("|------|--------|")

    for g in all_guides:
        if g["has_approval"]:
            lines.append(f"| 提交{g['name']} | [{g['name']}]({g['file']}) |")
        elif g["workflow_count"] > 0:
            lines.append(f"| 管理{g['name']} | [{g['name']}]({g['file']}) |")

    lines.append("")
    lines.append("### 我提交的申请在哪看\n")
    approval_sheets = [g for g in all_guides if g["has_approval"]]
    if approval_sheets:
        lines.append("以下申请类操作：\n")
        for g in approval_sheets:
            lines.append(f"- {g['name']} → 查看「【审批状态】」字段确认进度")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_manual.py <project_root> [--customer] [output_dir]")
        print("  --customer  Generate customer-facing guides instead of dev manual")
        sys.exit(1)

    project_root = sys.argv[1]
    customer_mode = "--customer" in sys.argv

    output_dir = sys.argv[-1] if len(sys.argv) > 2 and not sys.argv[-1].startswith("--") else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references"
    )
    if customer_mode and output_dir == sys.argv[-1] and sys.argv[-1] == "--customer":
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")

    root = Path(project_root)
    id_to_name = build_id_name_map(project_root)
    guides_dir = os.path.join(output_dir, "guides") if customer_mode else output_dir
    os.makedirs(guides_dir, exist_ok=True)

    all_guides = []

    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue
        mod_name = mod_dir.name

        for ws_dir in sorted(mod_dir.iterdir()):
            if not ws_dir.is_dir() or ws_dir.name.startswith("."):
                continue
            fp = ws_dir / "fields.json"
            if not fp.exists():
                continue

            try:
                fd = load_json(fp)
                ws_name = fd.get("name", ws_dir.name)
                fields = fd.get("fields", [])
            except:
                continue

            wf_path = ws_dir / "工作流"
            wf_dirs = [d.name for d in wf_path.iterdir() if d.is_dir()] if wf_path.exists() else []
            workflows = find_trigger_workflows(wf_dirs, ws_dir / "工作流" if wf_path.exists() else None)
            status_field = extract_status_field(fields)

            if customer_mode:
                guide = generate_customer_guide(ws_name, fields, workflows, status_field, id_to_name)
                safe_name = ws_name.replace("/", "-").replace(" ", "-")
                fname = f"{safe_name}.md"
                fpath = os.path.join(guides_dir, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(guide)

                all_guides.append({
                    "name": ws_name,
                    "module": mod_name,
                    "file": f"guides/{fname}",
                    "has_approval": any("审批" in w["name"] for w in workflows),
                    "workflow_count": len(workflows),
                })
            else:
                # dev manual mode — use existing logic
                pass

    if customer_mode and all_guides:
        index = generate_index(all_guides, root.name)
        with open(os.path.join(output_dir, "INDEX.md"), "w", encoding="utf-8") as f:
            f.write(index)

        print(f"Generated {len(all_guides)} customer guides in {guides_dir}/")
        print(f"Index: {os.path.join(output_dir, 'INDEX.md')}")
    elif customer_mode:
        print("No worksheets with field definitions found.")
    else:
        print("Use --customer flag to generate customer-facing guides.")


if __name__ == "__main__":
    main()
