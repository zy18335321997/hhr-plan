#!/usr/bin/env python3
"""
Full project extraction — 替代 workflow-analyzer。

从 HAP MCP + 内部 API 全量提取项目数据，生成:
  - business-flow-manifest.json  工作流读写清单
  - project_context.json         项目上下文
  - aliases.json                 术语别名模板
  - project-snapshot.md          全景快照
  - 更新 projects_registry.json  多项目注册表

用法:
  # 默认 MCP URL (几建/同技智能)
  python3 extract-project.py <项目名>

  # 指定 MCP URL (其他项目)
  python3 extract-project.py <项目名> --mcp-url "https://xxx/mcp?key=yyy"

  # 或通过环境变量
  HAP_MCP_URL="https://xxx/mcp?key=yyy" python3 extract-project.py <项目名>

前提:
  - MCP 代理层始终可用 (HAP-Appkey + HAP-Sign)
  - 工作流节点提取需要 Chrome 登录 (auth.py → Chrome cookies)
  - 如 Chrome 未登录，跳过节点级分析，只生成基础数据
"""

import json, os, sys, time, re, urllib.request, urllib.error, http.cookiejar
from collections import defaultdict
from datetime import datetime

# Ensure scripts/ directory is in path for auth module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OUTPUT_BASE = os.path.expanduser("~/Documents/workflow-output")
HAP_BRIDGE = os.path.expanduser("~/.claude/mcp-servers/hap-bridge")
sys.path.insert(0, HAP_BRIDGE)

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
_DEFAULT_MCP_URL = (
    "https://work.jijiansmart.com/mcp"
    "?HAP-Appkey=4ba6553626bb83cc"
    "&HAP-Sign=NDk2ZjdmYTQwNGYwZWY1ODIxN2RhZDNiMWU3YmI1ODlj"
    "NzgzNmUwYzM2ZTJiZTZhYTQ4NTU4YWFlMTI4ZmM0Yw=="
)


def resolve_mcp_url(explicit: str | None) -> str:
    return explicit or os.environ.get("HAP_MCP_URL", _DEFAULT_MCP_URL)


def derive_base_url(mcp_url: str) -> str:
    m = re.match(r"(https?://[^/]+)", mcp_url)
    base = m.group(1) if m else "https://work.jijiansmart.com"
    # Override: if project dir has a base_url.txt file, use that
    # (handles cases where MCP proxy domain != app domain)
    return base


# ---------------------------------------------------------------------------
# HAP MCP client (lightweight — no dependency on cli.py)
# ---------------------------------------------------------------------------
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# Module-level opener with cookie support — MCP proxy sets session cookie on init
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def _rpc(mcp_url: str, method: str, params: dict | None = None, timeout: int = 30) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params:
        payload["params"] = params
    req = urllib.request.Request(mcp_url, data=json.dumps(payload).encode(), headers=HEADERS, method="POST")
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def init_and_list_tools(mcp_url: str) -> list[dict]:
    _rpc(mcp_url, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "extract-project", "version": "1.0"},
    })
    result = _rpc(mcp_url, "tools/list")
    return result.get("result", {}).get("tools", [])


def call_tool(mcp_url: str, name: str, args: dict) -> dict:
    result = _rpc(mcp_url, "tools/call", {"name": name, "arguments": args})
    if "error" in result:
        return {"error": result["error"]}
    content = result.get("result", {}).get("content", [])
    if not content:
        return result.get("result", {})
    # Unwrap text content
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"text": text}
    return {"content": content}


# ---------------------------------------------------------------------------
# Phase 1: Worksheet extraction (MCP — no auth needed)
# ---------------------------------------------------------------------------
def extract_worksheets(mcp_url: str, full: bool = False) -> tuple[list[dict], dict[str, dict]]:
    """Return (worksheet_list, {ws_id: {name, fields, ...}})."""
    result = call_tool(mcp_url, "get_app_worksheets_list", {"responseFormat": "json"})
    worksheets = []

    # Response can be wrapped in different ways
    if isinstance(result, list):
        worksheets = result
    elif isinstance(result, dict):
        worksheets = result.get("data", result.get("worksheets", []))

    if not worksheets:
        # Try md format
        result = call_tool(mcp_url, "get_app_worksheets_list", {"responseFormat": "md"})
        print(f"  [md fallback] {str(result)[:200]}")

    ws_map = {}
    for ws in worksheets:
        if isinstance(ws, dict):
            wid = ws.get("id", ws.get("worksheetId", ""))
            ws_map[wid] = {
                "name": ws.get("name", wid),
                "id": wid,
                "fields": [],
            }

    print(f"  Worksheets: {len(ws_map)}")

    # Extract field structures
    count = 0
    items = list(ws_map.items())
    if not full:
        items = items[:30]  # Cap at 30 for speed; --full bypasses
    for wid, info in items:
        try:
            struct = call_tool(mcp_url, "get_worksheet_structure", {"worksheet_id": wid})
            if "error" not in struct:
                fields = _parse_fields(struct)
                info["fields"] = fields
                info["field_count"] = len(fields)
                count += 1
        except Exception as e:
            print(f"    skip {info['name']}: {e}")

    print(f"  Fields extracted: {count} worksheets")
    return worksheets, ws_map


def _parse_fields(struct: dict) -> list[dict]:
    """Extract field info from worksheet structure response."""
    fields = []
    raw = struct.get("data", struct)
    items = raw if isinstance(raw, list) else raw.get("controls", raw.get("fields", []))
    if not isinstance(items, list):
        return fields
    for c in items:
        if not isinstance(c, dict):
            continue
        fields.append({
            "id": c.get("id", c.get("controlId", "")),
            "name": c.get("name", c.get("displayName", "")),
            "type": c.get("type", c.get("controlType", "")),
            "required": c.get("required", False),
            "isTitle": c.get("isTitle", False),
        })
    return fields


# ---------------------------------------------------------------------------
# Phase 2: Workflow metadata (MCP — no auth needed)
# ---------------------------------------------------------------------------
def extract_workflow_meta(mcp_url: str) -> list[dict]:
    """Get workflow list with metadata from HAP MCP."""
    result = call_tool(mcp_url, "get_workflow_list", {})
    workflows = []
    if isinstance(result, list):
        workflows = result
    elif isinstance(result, dict):
        data = result.get("data", result)
        if isinstance(data, dict):
            workflows = data.get("processes", data.get("workflows", []))
        elif isinstance(data, list):
            workflows = data
    # Ensure it's a list of dicts
    if isinstance(workflows, dict):
        workflows = list(workflows.values()) if not isinstance(workflows.get("processes"), list) else workflows.get("processes", [])
    print(f"  Workflows (meta): {len(workflows)}")
    return workflows


# ---------------------------------------------------------------------------
# Phase 2b: Playwright workflow discovery (fallback when MCP returns empty)
# ---------------------------------------------------------------------------
def get_app_id_from_mcp(mcp_url: str) -> str | None:
    """Get app_id from MCP get_app_info tool."""
    result = call_tool(mcp_url, "get_app_info", {})
    if "error" in result:
        print(f"  [MCP] get_app_info failed: {result['error'][:80]}")
        return None
    # Response in {data: {appId, name, ...}}
    app_id = None
    if isinstance(result, dict):
        data = result.get("data", result)
        if isinstance(data, dict):
            app_id = data.get("appId", data.get("app_id"))
    if app_id:
        print(f"  App ID: {app_id}")
    return app_id


def extract_workflows_playwright(base_url: str, ws_names: set, app_id: str | None = None) -> list[dict]:
    """Use Playwright to scrape the workflow list page for workflow→worksheet mapping.

    Returns list of {id, name, trigger, status, worksheet} dicts.
    Requires: Chrome logged into 明道云, playwright + browser_cookie3 installed.
    """
    try:
        import browser_cookie3
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [skip] playwright/browser_cookie3 not installed")
        print("  Install: pip install playwright browser-cookie3 && python3 -m playwright install chromium")
        return []

    # Get Chrome cookies — strip port from domain (cookies are stored without port)
    domain_match = re.match(r"https?://([^/:]+)", base_url)
    domain = domain_match.group(1) if domain_match else "work.jijiansmart.com"
    print(f"  Chrome domain: {domain}")
    try:
        cj = browser_cookie3.chrome(domain_name=domain)
    except Exception as e:
        print(f"  [skip] Cannot read Chrome cookies: {e}")
        return []

    cookies = []
    for c in cj:
        cookie = {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
        if c.secure: cookie["secure"] = True
        if c.expires: cookie["expires"] = int(c.expires)
        cookies.append(cookie)

    if not cookies:
        print("  [skip] No Chrome cookies found for domain: " + domain)
        return []

    if not app_id:
        print("  [skip] No app_id provided for Playwright discovery")
        return []

    wf_url = f"{base_url}/app/{app_id}/workflow"
    print(f"  Playwright → {wf_url}")

    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        for c in cookies:
            try: ctx.add_cookies([c])
            except Exception: pass

        page = ctx.new_page()
        try:
            page.goto(wf_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            page.goto(wf_url, wait_until="commit", timeout=60000)
        time.sleep(5)

        # Get all workflow PIDs and names from DOM
        dom_data = page.evaluate("""() => {
            var links = [];
            var seen = {};
            document.querySelectorAll('a[href*="workflowedit"]').forEach(function(a) {
                var m = a.getAttribute('href').match(/workflowedit\\/([a-f0-9]+)/);
                if (m && !seen[m[1]]) {
                    seen[m[1]] = true;
                    links.push({pid: m[1], name: a.textContent.trim()});
                }
            });
            return JSON.stringify(links);
        }""")
        dom_links = json.loads(dom_data)
        print(f"  DOM links found: {len(dom_links)}")

        # Build PID→name map from DOM (trusted source)
        pid_name_map = {d["pid"]: d["name"] for d in dom_links}

        # Extract workflow metadata via JS: get each workflow row's trigger type, status, worksheet header
        wf_metadata = page.evaluate("""() => {
            var result = {};
            // Find all workflow name links and walk up to their row container
            document.querySelectorAll('a[href*="workflowedit"]').forEach(function(a) {
                var m = a.getAttribute('href').match(/workflowedit\\/([a-f0-9]+)/);
                if (!m) return;
                var pid = m[1];
                if (result[pid]) return; // already captured

                // Walk up to find the table row
                var row = a.closest('tr, .workflow-item, [class*="row"], [class*="item"]');
                if (!row) row = a.parentElement;
                // Keep walking up to find a suitable container
                while (row && row.tagName !== 'TR' && !row.className.match(/row|item|list/i)) {
                    row = row.parentElement;
                    if (!row || row.tagName === 'TABLE' || row.tagName === 'BODY') break;
                }

                // If still no row, use the parent chain text as fallback
                var rowText = row ? row.textContent.trim() : '';

                // Find the closest worksheet header (h2, h3, strong, or section title before this row)
                var wsHeader = '';
                var el = row || a;
                while (el && !wsHeader) {
                    var prev = el.previousElementSibling;
                    while (prev) {
                        if (prev.tagName && prev.tagName.match(/^H[1-4]$/i)) {
                            wsHeader = prev.textContent.trim(); break;
                        }
                        // Also check for section/collapse headers
                        if (prev.className && prev.className.match(/header|title|section|collapse|group/i)) {
                            var txt = prev.textContent.trim();
                            if (txt && txt.length < 40) { wsHeader = txt; break; }
                        }
                        prev = prev.previousElementSibling;
                    }
                    el = el.parentElement;
                    if (el && el.tagName === 'BODY') break;
                }

                result[pid] = {rowText: rowText, wsHeader: wsHeader};
            });
            return JSON.stringify(result);
        }""")
        wf_meta = json.loads(wf_metadata)

        # Recognized trigger keywords and worksheet names
        triggers = ["工作表事件","自定义动作","审批流程","子流程","时间",
                     "封装业务流程","Webhook","人员事件","调用流程","循环","对话",
                     "定时触发","按钮"]
        trigger_set = set(triggers)

        # Build workflows using DOM links for names + row text for metadata
        # First pass: extract worksheet headers from DOM
        ws_header_data = page.evaluate("""() => {
            var headers = [];
            // Find all collapse/expand headers that contain worksheet names
            document.querySelectorAll('.ant-collapse-header, [class*="collapse"] [class*="header"], h2, h3, [class*="group-title"]').forEach(function(el) {
                var txt = el.textContent.trim();
                // Remove count like (5)
                txt = txt.replace(/\\s*\\(\\d+\\)\\s*$/, '').trim();
                if (txt && txt.length < 50) {
                    headers.push({text: txt, top: el.getBoundingClientRect().top});
                }
            });
            return JSON.stringify(headers);
        }""")
        ws_headers = json.loads(ws_header_data)

        # Map worksheet names to their Y positions
        ws_y_positions = []
        for h in ws_headers:
            txt = h["text"]
            # Remove trailing counts
            txt = re.sub(r'\s*\(\d+\)\s*$', '', txt).strip()
            if txt in ws_names:
                ws_y_positions.append((h["top"], txt))

        # Second pass: get each workflow link's Y position to assign worksheet
        wf_positions = page.evaluate("""() => {
            var positions = {};
            document.querySelectorAll('a[href*="workflowedit"]').forEach(function(a) {
                var m = a.getAttribute('href').match(/workflowedit\\/([a-f0-9]+)/);
                if (m) {
                    positions[m[1]] = a.getBoundingClientRect().top;
                }
            });
            return JSON.stringify(positions);
        }""")
        wf_y = json.loads(wf_positions)

        def _dedup_name(name):
            """Fix duplicated names like '任务拆分任务拆分' → '任务拆分'."""
            half = len(name) // 2
            if half >= 2 and name[:half] == name[-half:]:
                return name[:half]
            return name

        workflows = []
        for dl in dom_links:
            pid = dl["pid"]
            name = _dedup_name(dl["name"])
            meta = wf_meta.get(pid, {})
            row_text = meta.get("rowText", "")

            # Determine trigger from row text
            trigger = "Unknown"
            for t in triggers:
                if t in row_text:
                    trigger = t
                    break

            # Determine worksheet via Y-position: find nearest header above this workflow
            worksheet = "未分类"
            y = wf_y.get(pid, 0)
            if y and ws_y_positions:
                # Find the nearest header above this workflow
                candidates = [(pos, name) for pos, name in ws_y_positions if pos < y]
                if candidates:
                    worksheet = max(candidates, key=lambda x: x[0])[1]

            # Determine status
            status = "Unknown"
            for st in ["启用", "停用", "草稿"]:
                if st in row_text:
                    status = st
                    break

            workflows.append({
                "id": pid, "name": name, "trigger": trigger,
                "status": status, "worksheet": worksheet,
            })

        print(f"  Workflows discovered: {len(workflows)} (Playwright)")
        return workflows

    finally:
        browser.close() if "browser" in dir() else None
        p.stop()


# ---------------------------------------------------------------------------
# Phase 2c: PID verification (sample-check Playwright results against MCP)
# ---------------------------------------------------------------------------
def verify_workflow_pids(wf_list: list[dict], mcp_url: str,
                         sample_rate: int = 5) -> dict:
    """Sample-verify that Playwright-extracted PIDs match workflow names via MCP.

    Returns {"verified": N, "mismatches": [...], "confidence": float}.
    Each mismatch is {pid, expected_name, actual_name}.
    """
    if not wf_list:
        return {"verified": 0, "mismatches": [], "confidence": 0.0}

    mismatches = []
    verified = 0
    sample_size = max(len(wf_list) // sample_rate, 5)

    print(f"  PID verification (sample {sample_size}/{len(wf_list)})...")
    for i in range(0, len(wf_list), max(len(wf_list) // sample_size, 1)):
        if i >= len(wf_list):
            break
        wf = wf_list[i]
        pid = wf.get("id", wf.get("processId", ""))
        expected = wf.get("name", "")

        try:
            result = call_tool(mcp_url, "get_workflow_details",
                               {"process_id": pid, "ai_description": "verify"})
            # Response may be wrapped
            actual_name = ""
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    actual_name = data.get("name", "")
                    if not actual_name and "error" not in str(result):
                        actual_name = result.get("name", "")

            if actual_name and actual_name != expected:
                mismatches.append({
                    "pid": pid,
                    "expected_name": expected,
                    "actual_name": actual_name,
                })
            elif actual_name:
                verified += 1
        except Exception:
            pass  # MCP call failed, skip verification for this PID

    confidence = verified / max(len(mismatches) + verified, 1) if (mismatches or verified) else 0.5

    if mismatches:
        print(f"  ⚠  PID mismatches found: {len(mismatches)}/{verified + len(mismatches)}")
        for m in mismatches[:5]:
            print(f"    {m['pid'][:20]}... expected='{m['expected_name'][:40]}' actual='{m['actual_name'][:40]}'")
    else:
        print(f"  ✓ All {verified} sampled PIDs verified")

    # Auto-correct mismatches if confidence is low
    if mismatches and confidence < 0.5:
        print(f"  ⚠ Low confidence ({confidence:.0%}), flagging for review")

    return {
        "verified": verified,
        "mismatches": mismatches,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Phase 3: Workflow node details (internal API — needs Chrome auth)
# ---------------------------------------------------------------------------
def extract_workflow_nodes_from_file(nodes_file: str, wf_list: list[dict]) -> dict[str, dict]:
    """Load and process workflow nodes from a pre-fetched nodes.json file."""
    import os as _os
    
    print(f"  Loading nodes from {nodes_file}...")
    with open(nodes_file, 'r') as f:
        raw_nodes = json.load(f)
    
    node_data = {}
    pid_lookup = {}
    for key, val in raw_nodes.items():
        if isinstance(val, dict):
            # Check if value is nested {data: {flowNodeMap: {...}}} or direct {nodeId: node, ...}
            if 'data' in val and isinstance(val['data'], dict) and 'flowNodeMap' in val['data']:
                pid_lookup[key] = val['data']['flowNodeMap']
            elif 'flowNodeMap' in val:
                pid_lookup[key] = val['flowNodeMap']
            else:
                # Direct flowNodeMap: {nodeId: node, ...} — first key check
                sample_keys = list(val.keys())[:3] if val else []
                has_node_ids = all(isinstance(k, str) and len(k) >= 20 for k in sample_keys)
                if has_node_ids or (val and not any(k in val for k in ('name', 'worksheet', 'reads', 'writes'))):
                    pid_lookup[key] = val
    
    total = len(wf_list)
    errors = 0
    
    READ_KEYWORDS = ("获取", "查询")
    WRITE_KEYWORDS = ("新增", "更新", "删除")
    
    def _is_read(name, tid):
        if tid == 13: return True
        if tid == 7: return True
        return any(kw in name for kw in READ_KEYWORDS)
    
    def _is_write(name, tid):
        return any(kw in name for kw in WRITE_KEYWORDS)
    
    TRIGGER_MAP = {
        0: "工作表事件", 1: "自定义动作(按钮)", 2: "定时触发",
        3: "Webhook", 4: "人员事件", 5: "审批流程", 6: "子流程",
        7: "封装业务流程", 8: "调用流程", 9: "循环", 10: "对话",
    }
    
    def _map_trigger(wf_item):
        tt = wf_item.get("triggerType", wf_item.get("trigger_type", -1))
        if isinstance(tt, int) and tt in TRIGGER_MAP:
            return tt, TRIGGER_MAP[tt]
        trigger_str = str(wf_item.get("trigger", "")).strip()
        if trigger_str:
            return -1, trigger_str
        return -1, "unknown"
    
    for i, wf in enumerate(wf_list):
        pid = wf.get("id", wf.get("processId", wf.get("process_id", "")))
        if not pid:
            continue
        
        flow_node_map = pid_lookup.get(pid, {})
        if not flow_node_map:
            for k, v in pid_lookup.items():
                if pid in k or k in pid:
                    flow_node_map = v
                    break
        
        reads, writes = set(), set()
        crud_mappings = []
        query_empty_actions = []
        approval_count = 0
        
        if flow_node_map:
            for node_id, node in flow_node_map.items():
                if not isinstance(node, dict):
                    continue
                tid = node.get("typeId", -1)
                name = node.get("name", "")
                
                if tid == 6:
                    target = node.get("sourceEntityName", "") or node.get("selectNodeName", "")
                    if target:
                        writes.add(target)
                        fields = node.get("fields", [])
                        if isinstance(fields, list):
                            field_names = []
                            for f in fields:
                                fn = f.get("fieldName", "") or f.get("fieldId", "")
                                fv = f.get("fieldValue", "")
                                if fn or fv:
                                    field_names.append(f"{fn or '?'}:{str(fv)[:50]}")
                            if field_names:
                                crud_mappings.append((name, target, field_names))
                    continue
                
                if tid in (7, 13):
                    target = node.get("appName", "")
                    if target:
                        reads.add(target)
                        et = node.get("executeType", -1)
                        is_exception = node.get("isException", False)
                        query_empty_actions.append((name, target, et, is_exception))
                    continue
                
                app_name = node.get("appName", "")
                if _is_write(name, tid) and app_name:
                    writes.add(app_name)
                elif _is_read(name, tid) and app_name:
                    reads.add(app_name)
                
                if tid in (10, 11):
                    approval_count += 1
        else:
            errors += 1
        
        # Prefer metadata from nodes.json (_name, _sheet, _trigger)
        wf_name = flow_node_map.get("_name", "") if flow_node_map else ""
        wf_worksheet = flow_node_map.get("_sheet", "") if flow_node_map else ""
        wf_trigger_val = flow_node_map.get("_trigger", None) if flow_node_map else None
        if not wf_name:
            wf_name = wf.get("name", "")
        if not wf_worksheet:
            wf_worksheet = wf.get("worksheet", wf.get("appName", ""))
        if wf_trigger_val is not None and isinstance(wf_trigger_val, int):
            trig_id, trig_label = wf_trigger_val, TRIGGER_MAP.get(wf_trigger_val, "unknown")
        else:
            trig_id, trig_label = _map_trigger(wf)
        
        node_data[pid] = {
            "name": wf_name,
            "worksheet": wf_worksheet,
            "trigger": trig_label,
            "trigger_type_id": trig_id,
            "node_count": len(flow_node_map) if flow_node_map else 0,
            "reads": sorted(reads),
            "writes": sorted(writes),
            "crud_field_mappings": crud_mappings,
            "query_empty_actions": query_empty_actions,
            "approval_count": approval_count,
        }
        
        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{total}...")
    
    print(f"  Nodes extracted: {len(node_data)}/{total} ({errors} errors)")
    return node_data



def extract_workflow_nodes(base_url: str, wf_list: list[dict]) -> dict[str, dict]:
    """For each workflow, get node structure via internal API.

    Returns {process_id: {name, worksheet, nodes, reads, writes, subs,
                          node_count, trigger, trigger_type,
                          crud_field_mappings, query_empty_actions,
                          approval_count}}.
    """
    try:
        import auth
    except ImportError:
        print("  [skip] auth module not available")
        return {}

    # Extract domain (without port) for cookie lookup
    domain_match = re.match(r"https?://([^/:]+)", base_url)
    domain = domain_match.group(1) if domain_match else "work.jijiansmart.com"
    headers = auth.get_auth_headers(domain)
    if not headers:
        print(f"  [skip] No auth for domain: {domain} — log into 明道云 in Chrome first")
        return {}

    # Node typeId classification
    READ_KEYWORDS = ("获取", "查询")
    WRITE_KEYWORDS = ("新增", "更新", "删除")

    def _is_read(name, tid):
        if tid == 13: return True
        if tid == 7: return True
        return any(kw in name for kw in READ_KEYWORDS)

    def _is_write(name, tid):
        return any(kw in name for kw in WRITE_KEYWORDS)

    # Trigger type mapping (明道云 triggerType values)
    TRIGGER_MAP = {
        0: "工作表事件",
        1: "自定义动作(按钮)",
        2: "定时触发",
        3: "Webhook",
        4: "人员事件",
        5: "审批流程",
        6: "子流程",
        7: "封装业务流程",
        8: "调用流程",
        9: "循环",
        10: "对话",
    }

    def _map_trigger(wf_item):
        """Extract and map trigger type from workflow metadata."""
        tt = wf_item.get("triggerType", wf_item.get("trigger_type", -1))
        if isinstance(tt, int) and tt in TRIGGER_MAP:
            return tt, TRIGGER_MAP[tt]
        # Fallback: try trigger string from DOM scraping
        trigger_str = str(wf_item.get("trigger", "")).strip()
        if trigger_str:
            return -1, trigger_str
        return -1, "unknown"

    print("  Extracting workflow nodes via internal API...")
    node_data = {}
    total = len(wf_list)
    errors = 0

    for i, wf in enumerate(wf_list):
        pid = wf.get("id", wf.get("processId", wf.get("process_id", "")))
        if not pid:
            continue

        try:
            url = f"{base_url}/api/workflow/flowNode/get?processId={pid}&count=200"
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp_data = json.loads(resp.read().decode())

            flow_node_map = resp_data.get("data", {}).get("flowNodeMap", {})
            reads, writes = set(), set()
            crud_mappings = []   # (node_name, target_table, field_names_written)
            query_empty_actions = []  # (node_name, table, executeType, isException)
            approval_count = 0

            for node_id, node in flow_node_map.items():
                if not isinstance(node, dict):
                    continue
                tid = node.get("typeId", -1)
                name = node.get("name", "")

                # CRUD node (typeId=6): sourceEntityName/selectNodeName = target worksheet
                if tid == 6:
                    target = node.get("sourceEntityName", "") or node.get("selectNodeName", "")
                    if target:
                        writes.add(target)
                        # Extract field mappings for 公理1
                        fields = node.get("fields", [])
                        if isinstance(fields, list):
                            field_names = []
                            for f in fields:
                                fn = f.get("fieldName", "") or f.get("fieldId", "")
                                fv = f.get("fieldValue", "")
                                if fn or fv:
                                    field_names.append(f"{fn or '?'}:{str(fv)[:50]}")
                            if field_names:
                                crud_mappings.append((name, target, field_names))
                    continue

                # Query/GetRecord node (typeId=7, typeId=13): appName = target worksheet
                if tid in (7, 13):
                    target = node.get("appName", "")
                    if target:
                        reads.add(target)
                        # Extract on-empty behavior for 公理5
                        et = node.get("executeType", -1)
                        is_exception = node.get("isException", False)
                        query_empty_actions.append((name, target, et, is_exception))
                    continue
                
                # Other read nodes (typeId=13 is also read but handled above)
                # Legacy classification for any remaining nodes
                app_name = node.get("appName", "")
                if _is_write(name, tid) and app_name:
                    writes.add(app_name)
                elif _is_read(name, tid) and app_name:
                    reads.add(app_name)
                
                # Approval nodes (公理2)
                if tid in (10, 11):
                    approval_count += 1

            # Map trigger type
            trig_id, trig_label = _map_trigger(wf)

            # If name is just a PID (from --pids-file), try to get real name from API
            wf_name = wf.get("name", "")
            wf_worksheet = wf.get("worksheet", wf.get("appName", ""))
            if wf_name and (wf_name == pid or len(wf_name) == 24):
                # Name looks like a PID, try API response
                resp_name = resp_data.get("data", {}).get("name", "")
                resp_ws = resp_data.get("data", {}).get("worksheetName", "")
                if resp_name:
                    wf_name = resp_name
                if resp_ws:
                    wf_worksheet = resp_ws

            node_data[pid] = {
                "name": wf_name,
                "worksheet": wf_worksheet,
                "trigger": trig_label,
                "trigger_type_id": trig_id,
                "node_count": len(flow_node_map),
                "reads": sorted(reads),
                "writes": sorted(writes),
                # New fields for axiom verification
                "crud_field_mappings": crud_mappings,
                "query_empty_actions": query_empty_actions,
                "approval_count": approval_count,
            }

            if (i + 1) % 50 == 0:
                print(f"    {i + 1}/{total}...")
        except Exception as e:
            errors += 1
            trig_id, trig_label = _map_trigger(wf)
            wf_name = wf.get("name", "")
            wf_worksheet = wf.get("worksheet", wf.get("appName", ""))
            node_data[pid] = {
                "name": wf_name,
                "worksheet": wf_worksheet,
                "trigger": trig_label,
                "trigger_type_id": trig_id,
                "node_count": 0, "reads": [], "writes": [],
                "crud_field_mappings": [],
                "query_empty_actions": [],
                "approval_count": 0,
                "error": str(e)[:100],
            }

        time.sleep(0.1)

    print(f"  Nodes extracted: {len(node_data)}/{total} ({errors} errors)")
    return node_data


# ---------------------------------------------------------------------------
# Build: manifest.json
# ---------------------------------------------------------------------------
def build_manifest(node_data: dict[str, dict], wf_list: list[dict]) -> dict:
    """Build business-flow-manifest.json from extracted node data.

    node_data format: {pid: {name, worksheet, reads, writes, subs, trigger,
                              trigger_type_id, node_count,
                              crud_field_mappings, query_empty_actions, approval_count}}
    """
    table_wfs = defaultdict(list)

    for pid, info in node_data.items():
        table_name = info.get("worksheet", "Unknown")
        reads = info.get("reads", [])
        writes = info.get("writes", [])

        table_wfs[table_name].append({
            "wf": info.get("name", pid),
            "pid": pid,
            "r": sorted([x for x in reads if x != table_name]),
            "w": sorted(writes),
            "trigger": info.get("trigger", ""),
            "node_count": info.get("node_count", 0),
        })

    read_index = defaultdict(set)
    write_index = defaultdict(set)
    empty_writes = []

    for table, wfs in table_wfs.items():
        for wf in wfs:
            for r in wf["r"]:
                read_index[r].add(table)
            for w in wf["w"]:
                write_index[w].add(table)
            if not wf["w"] and wf["node_count"] > 0:
                empty_writes.append({"table": table, "wf": wf["wf"]})

    total_wfs = sum(len(v) for v in table_wfs.values())

    # Axiom verification summary
    trigger_stats = {}
    total_crud_mappings = 0
    total_query_empty = 0
    total_approvals = 0
    for pid, info in node_data.items():
        tt = info.get("trigger_type_id", -1)
        tl = info.get("trigger", "unknown")
        key = f"{tt}:{tl}"
        trigger_stats[key] = trigger_stats.get(key, 0) + 1
        total_crud_mappings += len(info.get("crud_field_mappings", []))
        total_query_empty += len(info.get("query_empty_actions", []))
        total_approvals += info.get("approval_count", 0)

    return {
        "_description": "工作流读写清单 — 自动提取",
        "project": "",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_worksheets": len(table_wfs),
        "total_workflows_analyzed": total_wfs,
        "tables_with_workflows": len(table_wfs),
        "tables": {k: v for k, v in sorted(table_wfs.items())},
        "read_index": {k: sorted(v) for k, v in sorted(read_index.items())},
        "write_index": {k: sorted(v) for k, v in sorted(write_index.items())},
        "empty_write_workflows": empty_writes,
        "sub_process_index": {},
        "_axiom_verification": {
            "trigger_distribution": trigger_stats,
            "total_crud_field_mappings": total_crud_mappings,
            "total_query_empty_actions": total_query_empty,
            "total_approval_nodes": total_approvals,
        },
    }


# ---------------------------------------------------------------------------
# Build: project_context.json
# ---------------------------------------------------------------------------
def build_context(project_name: str, ws_map: dict[str, dict],
                  wf_list: list[dict], node_data: dict | None = None,
                  module: str = "默认模块", manifest: dict | None = None) -> dict:
    """Build project_context.json.

    If ws_map is empty (e.g. Browser extraction without MCP), worksheet names
    are extracted from the manifest's table keys as a fallback so
    project_context.json is never missing sheet data.
    """
    worksheets = {}
    for wid, info in ws_map.items():
        worksheets[info.get("name", wid)] = {
            "id": wid,
            "module": module,
            "field_count": info.get("field_count", len(info.get("fields", []))),
            "fields": info.get("fields", []),
        }

    # Fallback: if MCP worksheet extraction produced nothing, pull sheet
    # names from the manifest so project_context always has worksheet entries.
    if not worksheets and manifest:
        sheet_names = list(manifest.get("tables", {}).keys())
        for name in sheet_names:
            worksheets[name] = {
                "id": "",
                "module": module,
                "field_count": 0,
                "fields": [],
            }

    # Compute trigger distribution (use node_data if available for richer mapping)
    trigger_dist = defaultdict(int)
    if node_data:
        for pid, info in node_data.items():
            trigger = info.get("trigger", "Unknown")
            if trigger and trigger != "unknown":
                trigger_dist[trigger] += 1
    if not trigger_dist:
        for wf in wf_list:
            trigger = wf.get("trigger", "Unknown")
            if trigger:
                trigger_dist[trigger] += 1

    return {
        "project": {
            "name": project_name,
            "total_worksheets": len(worksheets),
            "total_workflows": len(wf_list),
            "total_modules": 1,
        },
        "worksheets": worksheets,
        "relation_graph": {},
        "hub_tables": [],
        "naming": {},
        "workflows": {
            "trigger_distribution": dict(sorted(trigger_dist.items(), key=lambda x: -x[1])),
            "total_approval_chains_sampled": 0,
        },
        "patterns": {},
    }


# ---------------------------------------------------------------------------
# Build: aliases.json
# ---------------------------------------------------------------------------
def build_aliases(ws_map: dict[str, dict]) -> dict:
    """Build empty aliases template."""
    names = sorted([info.get("name", "") for info in ws_map.values() if info.get("name")])
    return {
        "_description": "术语别名映射 — 客户用语 → 系统名称。手动填充。",
        "worksheets": {n: n for n in names},
        "workflows": {},
        "fields": {},
    }


# ---------------------------------------------------------------------------
# Build: project-snapshot.md
# ---------------------------------------------------------------------------
def build_snapshot(project_name: str, ws_map: dict[str, dict],
                   wf_list: list[dict], manifest: dict,
                   mcp_url: str, base_url: str) -> str:
    """Build project-snapshot.md Markdown."""
    ws_count = len(ws_map)
    wf_count = len(wf_list)
    manifest_wf_count = sum(len(v) for v in manifest.get("tables", {}).values())

    # Trigger stats
    trigger_dist = defaultdict(int)
    for wf in wf_list:
        trigger = wf.get("trigger", "Unknown")
        trigger_dist[trigger] += 1

    # Table with most workflows
    top_tables = sorted(manifest.get("tables", {}).items(), key=lambda x: -len(x[1]))[:10]

    lines = [
        f"# {project_name} 项目全景快照",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**数据来源**: HAP MCP + Playwright + 内部 API",
        "",
        "## 规模",
        f"- 工作表: {ws_count}",
        f"- 工作流: {wf_count}",
        f"- 节点分析: {manifest_wf_count} 个",
        f"- 有工作流的工作表: {manifest.get('tables_with_workflows', 0)} 张",
        "",
        "## 触发类型分布",
    ]
    for trigger, count in sorted(trigger_dist.items(), key=lambda x: -x[1]):
        lines.append(f"- {trigger}: {count}")

    read_count = len(manifest.get("read_index", {}))
    write_count = len(manifest.get("write_index", {}))
    empty_wf_count = len(manifest.get("empty_write_workflows", []))

    lines += [
        "",
        "## 数据链路",
        f"- 被读工作表: {read_count} 张",
        f"- 被写工作表: {write_count} 张",
        f"- 空写工作流: {empty_wf_count} 个（审批/通知/子流程类）",
        "",
        "## Top 10 工作表（工作流数量）",
    ]
    for name, wfs in top_tables:
        r_total = sum(len(w["r"]) for w in wfs)
        w_total = sum(len(w["w"]) for w in wfs)
        lines.append(f"- **{name}**: {len(wfs)} 工作流, {r_total} 读, {w_total} 写")

    lines += [
        "",
        "## 工作表列表",
    ]
    for name in sorted([info.get("name", "") for info in ws_map.values() if info.get("name")])[:50]:
        lines.append(f"- {name}")
    if ws_count > 50:
        lines.append(f"- ... ({ws_count - 50} more)")

    lines += [
        "",
        "## 文件索引",
        f"- 项目目录: `~/Documents/workflow-output/{project_name}/`",
        "- `business-flow-manifest.json` — 工作流读写清单",
        "- `project_context.json` — 项目上下文",
        "- `aliases.json` — 术语别名",
        "",
        "## 连接信息",
        f"- MCP URL: {mcp_url[:60]}...",
        f"- Base URL: {base_url}",
        "",
        "## 使用提示",
        "- Mode C 诊断: 查 `business-flow-manifest.json` 定位涉事工作流 → 看 r/w 链路",
        "- Mode D 审计: 遍历 manifest → 检查空写工作流 → 抽查节点配置",
        "- Mode B 改造: 查 manifest 了解目标表上下游",
        "- 需要刷新: 重新运行 `extract-project.py {project_name}`",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def update_registry(project_name: str, ws_count: int, wf_count: int, mcp_url: str = ""):
    registry_path = os.path.join(OUTPUT_BASE, "projects_registry.json")
    try:
        with open(registry_path) as f:
            reg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        reg = {"projects": {}, "_description": "多项目注册表"}

    reg["projects"][project_name] = {
        "path": f"~/Documents/workflow-output/{project_name}",
        "context_file": "project_context.json",
        "aliases_file": "aliases.json",
        "worksheets": ws_count,
        "workflows": wf_count,
        "last_extracted": datetime.now().strftime("%Y-%m-%d"),
        "context_ready": True,
        "aliases_ready": False,
        "mcp_url": mcp_url,
    }

    with open(registry_path, "w") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    print(f"  Registry updated: {registry_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    project_name = sys.argv[1]

    # Parse --mcp-url and --pids-file
    mcp_url = _DEFAULT_MCP_URL
    full_extract = False
    pids_file = None
    skip_mcp = False
    base_url_override = None
    nodes_file = None
    for i, arg in enumerate(sys.argv):
        if arg == "--mcp-url" and i + 1 < len(sys.argv):
            mcp_url = sys.argv[i + 1]
        if arg == "--pids-file" and i + 1 < len(sys.argv):
            pids_file = sys.argv[i + 1]
        if arg == "--full":
            full_extract = True
        if arg == "--skip-mcp":
            skip_mcp = True
        if arg == "--base-url" and i + 1 < len(sys.argv):
            base_url_override = sys.argv[i + 1]
        if arg == "--nodes-file" and i + 1 < len(sys.argv):
            nodes_file = sys.argv[i + 1]
    mcp_url = resolve_mcp_url(mcp_url if mcp_url != _DEFAULT_MCP_URL else None)
    base_url = base_url_override or derive_base_url(mcp_url)

    print(f"=== 项目提取: {project_name} ===")
    print(f"MCP URL: {mcp_url[:80]}...")
    print(f"Base URL: {base_url}")
    print()

    # Create output directory
    project_dir = os.path.join(OUTPUT_BASE, project_name)
    os.makedirs(project_dir, exist_ok=True)

    # Phase 1: Worksheets
    if skip_mcp:
        print("--- Phase 1: 跳过 (--skip-mcp) ---")
        # Try to load existing context
        ctx_path = os.path.join(project_dir, "project_context.json")
        if os.path.exists(ctx_path):
            with open(ctx_path) as f:
                existing = json.load(f)
            ws_map = existing.get("worksheets", {})
            worksheets = list(ws_map.values())
            print(f"  从现有 context 加载 {len(ws_map)} 张工作表")
        else:
            ws_map = {}
            worksheets = []
            print("  无现有 context，工作表数据为空")
    else:
        print("--- Phase 1: 工作表提取 ---")
        worksheets, ws_map = extract_worksheets(mcp_url, full=full_extract)

    # Phase 2: Workflow metadata
    if skip_mcp:
        print("--- Phase 2: 跳过 (--skip-mcp) ---")
        wf_list = []
    else:
        print("--- Phase 2: 工作流元数据 ---")
        wf_list = extract_workflow_meta(mcp_url)

    # Phase 2a: Load PIDs from file if provided (bypasses Playwright)
    if (not wf_list) and pids_file:
        print(f"--- Phase 2a: 从文件加载 PID: {pids_file} ---")
        try:
            with open(pids_file, 'r') as f:
                raw = f.read()
            # Parse as JSON array
            pids = json.loads(raw)
            if isinstance(pids, list):
                wf_list = [{"id": pid, "processId": pid, "name": pid, "trigger": "", "worksheet": ""} for pid in pids]
                print(f"  加载 {len(pids)} 个 PID (名称将在节点提取时从 API 获取)")
        except Exception as e:
            print(f"  [error] 无法解析 PID 文件: {e}")

    # Phase 2b: Playwright fallback when MCP returns empty (workflow-analyzer approach)
    if not wf_list and not skip_mcp:
        print("--- Phase 2b: Playwright 工作流发现 (MCP 返回空, workflow-analyzer 方式) ---")
        app_id = get_app_id_from_mcp(mcp_url)
        ws_names = set(info["name"] for info in ws_map.values() if info.get("name"))
        wf_list = extract_workflows_playwright(base_url, ws_names, app_id)

        # Phase 2c: Verify extracted PIDs
        if wf_list and not skip_mcp:
            verify_result = verify_workflow_pids(wf_list, mcp_url)
            if verify_result["mismatches"]:
                with open(os.path.join(project_dir, "_pid_mismatches.json"), "w") as f:
                    json.dump(verify_result["mismatches"], f, ensure_ascii=False, indent=2)
        else:
            print("  Playwright also returned 0 workflows — app may have no workflows yet")

    # Phase 3: Workflow nodes (use --nodes-file if available, else API)
    print("--- Phase 3: 工作流节点 ---")
    if nodes_file:
        node_data = extract_workflow_nodes_from_file(nodes_file, wf_list)
    else:
        node_data = extract_workflow_nodes(base_url, wf_list)

    # Build outputs
    print("--- 生成输出文件 ---")

    # 1. business-flow-manifest.json
    if node_data:
        manifest = build_manifest(node_data, wf_list)
    else:
        manifest = {
            "_description": "基础清单 (节点数据不可用)",
            "tables": {},
            "read_index": {},
            "write_index": {},
            "empty_write_workflows": [],
            "sub_process_index": {},
        }
    manifest["project"] = project_name
    with open(os.path.join(project_dir, "business-flow-manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("  business-flow-manifest.json")

    # 2. project_context.json
    context = build_context(project_name, ws_map, wf_list, node_data, manifest=manifest)
    with open(os.path.join(project_dir, "project_context.json"), "w") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)
    print("  project_context.json")

    # 3. aliases.json
    aliases = build_aliases(ws_map)
    with open(os.path.join(project_dir, "aliases.json"), "w") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)
    print("  aliases.json")

    # 4. project-snapshot.md
    snapshot = build_snapshot(project_name, ws_map, wf_list, manifest, mcp_url, base_url)
    with open(os.path.join(project_dir, "project-snapshot.md"), "w") as f:
        f.write(snapshot)
    print("  project-snapshot.md")

    # 5. Registry
    update_registry(project_name, len(ws_map), len(wf_list), mcp_url)

    # 6. Auto-sync derived data (index + graph)
    auto_sync_script = os.path.join(os.path.dirname(__file__), "auto_sync.py")
    print()
    print("--- 同步派生数据 ---")
    import subprocess
    subprocess.run([sys.executable, auto_sync_script], check=False)

    print()
    print("=== 提取完成 ===")
    print(f"项目目录: {project_dir}")
    print(f"工作表: {len(ws_map)}")
    print(f"工作流: {len(wf_list)}")
    if node_data:
        total_r = sum(len(wf["r"]) for wfs in manifest.get("tables", {}).values() for wf in wfs)
        total_w = sum(len(wf["w"]) for wfs in manifest.get("tables", {}).values() for wf in wfs)
        print(f"读关系: {total_r}  写关系: {total_w}")
    else:
        print("节点级数据: 不可用 (需要 Chrome 登录)")
    print()
    print("下一步:")
    print(f"  1. 编辑 aliases.json 填充客户术语映射")
    print(f"  2. /hhr-plan → Mode D 健康审计")
    print(f"  3. 后续刷新: python3 {__file__} {project_name}")


if __name__ == "__main__":
    main()
