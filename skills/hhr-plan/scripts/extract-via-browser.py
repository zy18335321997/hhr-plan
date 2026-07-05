#!/usr/bin/env python3
"""
无 MCP 项目提取 — 通过 AppleScript + Chrome Console JS 注入工作流数据。

需要:
  - macOS + Chrome 已登录目标明道云应用
  - Chrome 里已打开目标应用的工作流列表页
  - AppleScript 权限 (系统自带)

用法:
  python3 extract-via-browser.py <项目名> <base_url> <app_id>

示例:
  python3 extract-via-browser.py 尚策 http://schg.yikuaida.cn 0bce9d4c-210a-4751-a91e-3b2151bb4165
  python3 extract-via-browser.py 城市运营 http://cy.jkqzhyj.com:81 f5411118-92d3-4f4c-b6d9-92993f48ab33

等于 extract-project.py 的无 MCP 替代路径。
"""

import json, os, sys, subprocess, time
from collections import defaultdict
from datetime import datetime

OUTPUT_BASE = os.path.expanduser("~/Documents/workflow-output")

TYPE_NAMES = {
    0: '触发器', 1: '分支', 2: '分支条件', 3: '填写节点', 4: '审批节点',
    5: '抄送/通知', 6: '数据操作', 7: '查询节点', 8: 'API请求',
    9: '公式计算', 10: '短信', 11: '邮件', 12: '延时', 13: '获取多条',
    14: '代码块', 15: '获取链接', 16: '子流程', 17: '界面推送',
    20: '封装业务流程', 26: '发起审批流程', 27: '通知', 29: '循环',
    30: '返回', 31: 'AIGC', 33: 'Agent', 100: '系统节点', 101: '工具节点'
}
TRIGGER_IDS = {
    '1': '自定义动作', '2': '工作表事件-新增', '3': '工作表事件-编辑',
    '4': '工作表事件-仅编辑', '5': '工作表事件-删除', '6': '时间',
    '7': '审批流程', '8': '子流程', '9': '封装业务流程',
    '10': '工作表事件-新增或编辑',
}


def run_js(js_code, domain_hint, timeout=15):
    """Inject JS into a Chrome tab matching domain_hint and return result."""
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"')
    applescript = (
        'tell application "Google Chrome"\n'
        '  repeat with w in windows\n'
        '    repeat with t in tabs of w\n'
        '      if URL of t contains "' + domain_hint + '" then\n'
        '        execute t javascript "' + escaped + '"\n'
        '        return result\n'
        '      end if\n'
        '    end repeat\n'
        '  end repeat\n'
        '  return "NOT_FOUND"\n'
        'end tell\n'
    )
    r = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def extract(project_name: str, base_url: str, app_id: str) -> bool:
    """Full project extraction via browser injection."""
    output_dir = os.path.join(OUTPUT_BASE, project_name)
    os.makedirs(output_dir, exist_ok=True)

    domain = base_url.replace("http://", "").replace("https://", "").split(":")[0].split("/")[0]
    print(f"🌐 {project_name}: {base_url} (app={app_id})")

    # ---- Phase 1: Verify Chrome tab ----
    check = run_js(
        "(function(){ return 'cookies='+document.cookie.length+' has_pss='+(document.cookie.indexOf('md_pss_id')>-1?'yes':'no'); })()",
        domain
    )
    if "NOT_FOUND" in check or "has_pss=no" in check:
        print(f"❌ Chrome 未登录 {domain} 或页面未打开")
        print(f"   请先打开 {base_url}/app/{app_id}/workflow 并登录")
        return False
    print(f"✅ Chrome 登录态: {check}")

    # ---- Phase 2: Collect all workflow PIDs ----
    print("\n📋 Phase 2: 收集工作流 PID...")
    all_pids = set()
    for lt in range(15):
        lt_s = str(lt)
        js = (
            "(function(){"
            "var a=document.cookie.match(/md_pss_id=([^;]+)/);"
            "var h=a?('md_pss_id '+a[1]):'';"
            "var x=new XMLHttpRequest();"
            "x.open('GET','/api/workflow/v1/process/list?relationId=" + app_id + "&pageSize=500&processListType=" + lt_s + "',false);"
            "if(h)x.setRequestHeader('Authorization',h);"
            "x.withCredentials=true;"
            "try{x.send();"
            "var r=JSON.parse(x.responseText);"
            "if(r.data&&Array.isArray(r.data)){"
            "var p=[];"
            "r.data.forEach(function(g){(g.processList||[]).forEach(function(w){if(w.id)p.push(w.id)})});"
            "return 'XXX'+p.length+'YYY'+JSON.stringify(p);"
            "}"
            "return 'EMPTY';"
            "}catch(e){return 'ERR:'+e.message;}"
            "})()"
        )
        output = run_js(js, domain)
        xxx = output.find("XXX")
        yyy = output.find("YYY")
        if xxx >= 0 and yyy > xxx:
            count = int(output[xxx+3:yyy])
            if count > 0:
                pids = json.loads(output[yyy+3:])
                all_pids.update(pids)
        if isinstance(all_pids, set) and len(all_pids) > 0:
            print(f"  total unique so far: {len(all_pids)}", end="\r")
    print(f"\n  ✅ 共 {len(all_pids)} 个 PID")

    if not all_pids:
        print("❌ 未找到任何工作流 PID，请检查登录状态")
        return False

    pids_list = sorted(all_pids)
    with open(os.path.join(output_dir, "pids.json"), "w") as f:
        json.dump(pids_list, f)

    # ---- Phase 3: Extract node configs ----
    total = len(pids_list)
    batch_size = min(30, max(10, total // 10))
    batches = [pids_list[i:i+batch_size] for i in range(0, total, batch_size)]
    print(f"\n📋 Phase 3: 提取节点配置 ({total} 个工作流, {len(batches)} 批)...")

    data = {}
    for bi, batch in enumerate(batches):
        batch_num = bi + 1
        pids_json = json.dumps(batch)

        # Fetch batch
        fetch_js = (
            "(function(){"
            "var pids=" + pids_json + ";"
            "var a=document.cookie.match(/md_pss_id=([^;]+)/);"
            "var h=a?('md_pss_id '+a[1]):'';"
            "window._BS=false;window._BCS=0;"
            "function n(i){"
            "if(i>=pids.length){window._BS=true;return;}"
            "var pid=pids[i];"
            "var x=new XMLHttpRequest();"
            "x.open('GET','/api/workflow/flowNode/get?processId='+pid+'&count=200',true);"
            "if(h)x.setRequestHeader('Authorization',h);"
            "x.withCredentials=true;"
            "x.onreadystatechange=function(){"
            "if(x.readyState===4){"
            "try{var r=JSON.parse(x.responseText);"
            "var d=r.data||{};"
            "var out=d.flowNodeMap||{};"
            "out._name=d.name||'';"
            "out._sheet=d.worksheetName||'';"
            "out._trigger=d.triggerType;"
            "localStorage.setItem('ex_'+pid,JSON.stringify(out));"
            "}catch(e){localStorage.setItem('ex_'+pid,'ERR');}"
            "window._BCS=i+1;n(i+1);"
            "}"
            "};"
            "x.send();"
            "}"
            "n(0);"
            "return 'started';"
            "})()"
        )
        run_js(fetch_js, domain)

        # Poll
        for poll_i in range(120):
            time.sleep(1.5)
            poll_out = run_js(
                "(function(){return (window._BS?'T':'F')+'|'+window._BCS;})()",
                domain, timeout=10
            )
            if poll_out.startswith("T"):
                break

        # Read back
        for pid in batch:
            raw = run_js("localStorage.getItem('ex_" + pid + "')", domain)
            if raw and raw != "ERR" and raw != "NOT_FOUND":
                try:
                    node_map = json.loads(raw)
                    if node_map:
                        data[pid] = node_map
                except json.JSONDecodeError:
                    pass

        print(f"  批次 {batch_num}/{len(batches)}: {len(data)}/{total} 已收集")

    # Save nodes.json
    with open(os.path.join(output_dir, "nodes.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False)

    nodes_count = sum(len(v) for v in data.values() if isinstance(v, dict))
    print(f"\n✅ nodes.json: {len(data)} 工作流, {nodes_count} 节点")

    # ---- Phase 4: Generate manifest + snapshot ----
    print("\n📋 Phase 4: 生成 manifest + snapshot...")
    _build_outputs(project_name, output_dir, data, base_url, app_id)

    # ---- Update registry ----
    registry_path = os.path.join(OUTPUT_BASE, "projects_registry.json")
    registry = {}
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            registry = json.load(f)
    registry[project_name] = {
        "base_url": base_url,
        "app_id": app_id,
        "total_workflows": len(data),
        "total_nodes": nodes_count,
        "last_extraction": datetime.now().strftime("%Y-%m-%d"),
        "extraction_method": "extract-via-browser (AppleScript + Chrome JS)",
        "has_nodes": True, "has_manifest": True, "has_snapshot": True,
    }
    with open(registry_path, "w") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 {project_name} 提取完成！")
    return True


def _build_outputs(project_name: str, output_dir: str, data: dict,
                   base_url: str, app_id: str):
    """Generate business-flow-manifest.json and project-snapshot.md."""
    trigger_dist = defaultdict(int)
    tables = defaultdict(list)
    read_index = defaultdict(list)
    write_index = defaultdict(list)
    node_type_dist = defaultdict(int)
    empty_writes = []

    for pid, node_map in data.items():
        if not isinstance(node_map, dict) or '_err' in node_map:
            continue

        sheets_read = set()
        sheets_write = set()
        wf_name = node_map.get('_name', '') or f"WF_{pid[:12]}"
        # Extract trigger type directly from flowNodeMap trigger node
        trigger_type = 'Unknown'
        for nid, node in node_map.items():
            if nid.startswith('_') or not isinstance(node, dict):
                continue
            if node.get('typeId') == 0:
                tid = str(node.get('triggerId', ''))
                trigger_type = TRIGGER_IDS.get(tid, f"type={tid}")
                break
        node_count = len([k for k in node_map if not k.startswith('_')])

        for nid, node in node_map.items():
            if nid.startswith('_'):
                continue
            if not isinstance(node, dict):
                continue
            tid = node.get('typeId', -1)
            node_type_dist[tid] += 1
            sn = node.get('appName', '') or node.get('sourceEntityName', '')
            aid = str(node.get('actionId', ''))

            if tid == 6:
                if aid in ('1', '2'):
                    if sn:
                        sheets_write.add(sn)
                elif aid == '20':
                    if sn:
                        sheets_read.add(sn)
            elif tid in (7, 13):
                if sn:
                    sheets_read.add(sn)
            elif tid in (16, 26):
                subn = node.get('subProcessName', '')
                if subn:
                    sheets_write.add(f"[子流程:{subn[:20]}]")

        trigger_dist[trigger_type] += 1

        for s in sheets_read | sheets_write:
            if s.startswith('['):
                continue
            tables[s].append({
                "wf": wf_name, "pid": pid,
                "r": sorted(sheets_read - {s}),
                "w": sorted(sheets_write),
                "trigger": trigger_type,
                "node_count": node_count
            })

        for s in sheets_read:
            if not s.startswith('['):
                read_index[s].append(pid)
        for s in sheets_write:
            if not s.startswith('['):
                write_index[s].append(pid)
        if not sheets_write:
            empty_writes.append(pid)

    tables_sorted = dict(sorted(tables.items(), key=lambda x: -len(x[1])))
    valid_count = sum(1 for v in data.values() if isinstance(v, dict) and '_err' not in v)
    total_nodes = sum(len(v) for v in data.values() if isinstance(v, dict) and '_err' not in v)

    # Manifest
    manifest = {
        "_description": "工作流读写清单 — extract-via-browser (AppleScript + Chrome JS)",
        "project": project_name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_worksheets": len(tables_sorted),
        "total_workflows_analyzed": valid_count,
        "tables": tables_sorted,
        "read_index": dict(read_index),
        "write_index": dict(write_index),
        "empty_write_workflows": empty_writes,
        "trigger_distribution": dict(trigger_dist),
    }
    with open(os.path.join(output_dir, "business-flow-manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Snapshot
    top_tables = sorted(tables_sorted.items(), key=lambda x: -len(x[1]))[:20]
    top_written = sorted(write_index.items(), key=lambda x: -len(x[1]))[:10]
    top_read = sorted(read_index.items(), key=lambda x: -len(x[1]))[:10]

    lines = [
        f"# {project_name} 项目全景快照",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**数据来源**: extract-via-browser (AppleScript + Chrome Console JS, {valid_count}/{len(data)} 完成)",
        "",
        "## 规模",
        f"- 工作表: {len(tables_sorted)}+",
        f"- 工作流: {len(data)} (节点提取完成: {valid_count})",
        f"- 节点总数: {total_nodes}",
        f"- 有工作流的工作表: {len(tables_sorted)} 张",
        "",
        "## 触发类型分布",
    ]
    for t, c in sorted(trigger_dist.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {c}")

    lines += ["", "## 节点类型分布"]
    for tid, count in sorted(node_type_dist.items(), key=lambda x: -x[1])[:12]:
        name = TYPE_NAMES.get(tid, f'typeId={tid}')
        pct = count / total_nodes * 100 if total_nodes else 0
        lines.append(f"- {name}: {count} ({pct:.1f}%)")

    lines += ["", "## 数据链路",
              f"- 被读工作表: {len(read_index)} 张",
              f"- 被写工作表: {len(write_index)} 张",
              f"- 空写工作流: {len(empty_writes)} 个",
              "", "## Top 20 工作表（按工作流数量）"]
    for sn, wfl in top_tables:
        r_ct = len(set(s for wf in wfl for s in wf.get('r', [])))
        w_ct = len(set(s for wf in wfl for s in wf.get('w', [])))
        lines.append(f"- **{sn}**: {len(wfl)} WFs, {r_ct} 读边, {w_ct} 写边")

    lines += ["", "## Top 10 被写入最多的表"]
    for sn, pl in top_written:
        lines.append(f"- **{sn}**: 被 {len(pl)} 个工作流写入")

    lines += ["", "## Top 10 被读取最多的表"]
    for sn, pl in top_read:
        lines.append(f"- **{sn}**: 被 {len(pl)} 个工作流读取")

    lines += ["", "## 文件索引",
              f"- `business-flow-manifest.json` — 工作流读写清单（{valid_count} WFs）",
              f"- `nodes.json` — 完整节点数据（{valid_count} WFs, {total_nodes} nodes）",
              f"- `pids.json` — PID 列表（{len(data)} 个）",
              "", "## 连接信息",
              f"- Base URL: {base_url}",
              f"- App ID: {app_id}",
              "", "## 使用提示",
              "- Mode C 诊断: 查 `business-flow-manifest.json` 定位涉事工作流 → 看 r/w 链路",
              "- Mode D 审计: 遍历 manifest → 检查空写工作流 → 抽查节点配置",
              "- Mode B 改造: 查 manifest 了解目标表上下游"]

    with open(os.path.join(output_dir, "project-snapshot.md"), "w") as f:
        f.write("\n".join(lines))

    mf_size = os.path.getsize(os.path.join(output_dir, "business-flow-manifest.json")) / 1024
    ss_size = os.path.getsize(os.path.join(output_dir, "project-snapshot.md")) / 1024
    print(f"  ✅ business-flow-manifest.json ({mf_size:.0f}KB)")
    print(f"  ✅ project-snapshot.md ({ss_size:.0f}KB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python3 extract-via-browser.py <项目名> <base_url> <app_id>")
        print("示例: python3 extract-via-browser.py 尚策 http://schg.yikuaida.cn 0bce9d4c-210a-4751-a91e-3b2151bb4165")
        sys.exit(1)

    project = sys.argv[1]
    url = sys.argv[2].rstrip("/")
    app = sys.argv[3]
    success = extract(project, url, app)
    sys.exit(0 if success else 1)
