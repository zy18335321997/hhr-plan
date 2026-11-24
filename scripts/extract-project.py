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
  # 显式指定 MCP URL。get_workflow_structure 会拉取节点 config；
  # get_workflow_details 只有触发流程元数据，不够用。
  python3 extract-project.py <项目名> --mcp-url "https://xxx/mcp?key=yyy"

  # 只拉一个流程（也接受 /workflowedit/<processId> 形式的 --base-url）
  python3 extract-project.py <项目名> --mcp-url "https://xxx/mcp?key=yyy" \
    --process-id "<processId>"

  # 或通过环境变量
  HAP_MCP_URL="https://xxx/mcp?key=yyy" python3 extract-project.py <项目名>

  # 完全使用本地提取物，不需要 MCP URL
  python3 extract-project.py <项目名> --skip-mcp \
    --pids-file /path/to/pids.json \
    --nodes-file /path/to/nodes.json \
    --base-url "https://your-hap-host"

前提:
  - 非 --skip-mcp 模式必须通过 --mcp-url 或 HAP_MCP_URL 提供地址
  - 工作流节点提取需要 Chrome 登录 (auth.py → Chrome cookies)
  - 如 Chrome 未登录，跳过节点级分析，只生成基础数据
"""

import json, os, sys, time, re, urllib.request, urllib.error, urllib.parse, http.cookiejar
from collections import defaultdict
from datetime import datetime

# Ensure scripts/ directory is in path for auth module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import context_fields
import field_mappings
import mcp_workflow_structure
import node_editor_config
import platform_router

# Node roles come from scripts/verify-platform.py TYPE_NAMES.
# 6 is the data operation, 7 is query, 13 is get-multiple, 4 and 26 are approvals.
# 2 and 3 are a branch arm and a fill step, not create/update.
DATA_OPERATION_TYPE = 6
READ_NODE_TYPES = {7, 13}
APPROVAL_NODE_TYPES = {4, 26}
DETAIL_NODE_TYPES = {DATA_OPERATION_TYPE}
CREATE_ACTION_IDS = {1, 21}
UPDATE_ACTION_IDS = {2, 412}
_READ_NAME_KEYWORDS = ("获取", "查询")
_WRITE_NAME_KEYWORDS = ("新增", "更新", "删除")
_IGNORED_TARGETS = {"按钮触发", "获取关联记录", "工作表事件触发"}


def _load_type_names() -> dict:
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify-platform.py")
    spec = importlib.util.spec_from_file_location("verify_platform_types", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TYPE_NAMES


TYPE_NAMES = _load_type_names()


def iter_flow_nodes(flow_node_map):
    """Yield real nodes. Metadata keys saved beside the map start with '_'."""
    if not isinstance(flow_node_map, dict):
        return
    for node_id, node in flow_node_map.items():
        if isinstance(node_id, str) and node_id.startswith("_"):
            continue
        if isinstance(node, dict):
            yield node_id, node


def _action_id(node) -> int | None:
    try:
        return int(node.get("actionId"))
    except (TypeError, ValueError):
        return None


def is_field_detail_node(node: dict) -> bool:
    """Field-level create/update lives on type 6, not on branch/fill nodes."""
    if node.get("typeId") not in DETAIL_NODE_TYPES:
        return False
    name = node.get("name") or ""
    aid = _action_id(node)
    if aid in CREATE_ACTION_IDS or aid in UPDATE_ACTION_IDS:
        return True
    return any(keyword in name for keyword in ("新增", "更新"))


def detail_type_label(node: dict) -> str:
    name = node.get("name") or ""
    aid = _action_id(node)
    if aid in CREATE_ACTION_IDS or "新增" in name:
        return "新增记录"
    return "更新记录"


def summarize_flow_nodes(flow_node_map) -> dict:
    """Classify one workflow using the verified type-id map."""
    reads, writes = set(), set()
    crud_mappings = []
    query_empty_actions = []
    approval_count = 0
    trigger_sheet = ""
    node_count = 0
    incomplete = False
    for _node_id, node in iter_flow_nodes(flow_node_map):
        node_count += 1
        tid = node.get("typeId", -1)
        name = node.get("name") or ""
        app_name = node.get("appName") or ""
        src_entity = node.get("sourceEntityName") or ""
        if tid == DATA_OPERATION_TYPE:
            target = src_entity or app_name
            if target and target not in _IGNORED_TARGETS:
                if any(keyword in name for keyword in _READ_NAME_KEYWORDS):
                    reads.add(target)
                elif any(keyword in name for keyword in _WRITE_NAME_KEYWORDS):
                    writes.add(target)
                mapping = field_mappings.resolve_field_mappings(node)
                if mapping and mapping.get("assignments"):
                    crud_mappings.append({
                        "node_name": name,
                        "target": target,
                        "update_object": mapping.get("update_object"),
                        "readable": mapping.get("lines") or [],
                        "raw": field_mappings.raw_assignment_summary(mapping),
                    })
            continue
        if tid in READ_NODE_TYPES:
            target = app_name or src_entity
            if target:
                reads.add(target)
                query_empty_actions.append((
                    name,
                    target,
                    node.get("executeType", -1),
                    node.get("isException", False),
                ))
            continue
        if tid == 0 and app_name and not trigger_sheet:
            trigger_sheet = app_name
            continue
        if tid in APPROVAL_NODE_TYPES:
            approval_count += 1
    if node_count >= 200:
        incomplete = True
    return {
        "reads": reads,
        "writes": writes,
        "crud_field_mappings": crud_mappings,
        "query_empty_actions": query_empty_actions,
        "approval_count": approval_count,
        "trigger_sheet": trigger_sheet,
        "node_count": node_count,
        "incomplete": incomplete,
    }


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OUTPUT_BASE = os.path.expanduser("~/Documents/workflow-output")
HAP_BRIDGE = os.path.expanduser("~/.claude/mcp-servers/hap-bridge")
sys.path.insert(0, HAP_BRIDGE)

# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------
def resolve_mcp_url(explicit: str | None) -> str | None:
    """只接受调用参数或环境变量，不提供仓库内默认值。"""
    return explicit or os.environ.get("HAP_MCP_URL")


def derive_base_url(mcp_url: str | None) -> str | None:
    if not mcp_url:
        return None
    parsed = urllib.parse.urlsplit(mcp_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    if port:
        host = f"{host}:{port}"
    return f"{parsed.scheme}://{host}"


def display_mcp_origin(mcp_url: str | None) -> str:
    """日志只显示 origin，避免泄漏查询参数中的凭证。"""
    return derive_base_url(mcp_url) or "(not configured)"


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
    domain = platform_router.derive_cookie_domain(base_url)
    if not domain:
        print("  [skip] Cannot derive cookie domain from base_url")
        return []
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
        
        if flow_node_map:
            summary = summarize_flow_nodes(flow_node_map)
        else:
            errors += 1
            summary = summarize_flow_nodes({})
        
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
            "trigger_sheet": summary["trigger_sheet"],
            "trigger": trig_label,
            "trigger_type_id": trig_id,
            "node_count": summary["node_count"],
            "reads": sorted(summary["reads"]),
            "writes": sorted(summary["writes"]),
            "crud_field_mappings": summary["crud_field_mappings"],
            "query_empty_actions": summary["query_empty_actions"],
            "approval_count": summary["approval_count"],
            "incomplete": summary["incomplete"],
        }

        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{total}...")
    
    print(f"  Nodes extracted: {len(node_data)}/{total} ({errors} errors)")
    return node_data



def extract_workflow_nodes(base_url: str, wf_list: list[dict], project_dir: str = "",
                           merge_existing: bool = False) -> dict[str, dict]:
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
    domain = platform_router.derive_cookie_domain(base_url)
    if not domain:
        print("  [skip] Cannot derive cookie domain from base_url")
        return {}
    try:
        headers = auth.get_auth_headers(domain)
    except auth.CookieScopeError as e:
        print(f"  [skip] {e}")
        return {}
    if not headers:
        print(f"  [skip] No auth for domain: {domain} — log into 明道云 in Chrome first")
        return {}

    # Trigger type mapping (明道云 triggerType values). This is not the node type_id map.
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
    raw_nodes = {}  # Store raw flowNodeMap for detail extraction and nodes.json
    total = len(wf_list)
    errors = 0

    for i, wf in enumerate(wf_list):
        pid = wf.get("id", wf.get("processId", wf.get("process_id", "")))
        if not pid:
            continue

        try:
            query = urllib.parse.urlencode({
                "processId": pid,
                "count": platform_router.NODE_FETCH_LIMIT,
            })
            resp_data = platform_router.fetch_json(
                base_url,
                f"/api/workflow/flowNode/get?{query}",
                domain=domain,
            )

            flow_node_map = resp_data.get("data", {}).get("flowNodeMap", {})

            # Store raw nodes (with metadata) for Phase 3b detail extraction
            raw_entry = dict(flow_node_map)
            raw_entry["_name"] = wf.get("name", "")
            raw_entry["_sheet"] = wf.get("worksheet", wf.get("appName", ""))
            raw_entry["_trigger"] = wf.get("trigger", "")
            raw_nodes[pid] = raw_entry

            summary = summarize_flow_nodes(flow_node_map)
            if summary["trigger_sheet"] and not wf.get("worksheet"):
                wf["worksheet"] = summary["trigger_sheet"]
            stated_total = resp_data.get("data", {}).get("total")
            if isinstance(stated_total, int) and stated_total > summary["node_count"]:
                summary["incomplete"] = True

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
                "trigger_sheet": summary["trigger_sheet"],
                "trigger": trig_label,
                "trigger_type_id": trig_id,
                "node_count": summary["node_count"],
                "reads": sorted(summary["reads"]),
                "writes": sorted(summary["writes"]),
                "crud_field_mappings": summary["crud_field_mappings"],
                "query_empty_actions": summary["query_empty_actions"],
                "approval_count": summary["approval_count"],
                "incomplete": summary["incomplete"],
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
                "trigger_sheet": "",
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

    # Save raw nodes.json for Phase 3b detail extraction.
    # merge_existing keeps MCP structure rows for processes this cookie pass did not fetch.
    nodes_file = os.path.join(project_dir, "nodes.json")
    if merge_existing and os.path.exists(nodes_file):
        try:
            with open(nodes_file, encoding="utf-8") as existing:
                previous = json.load(existing)
            if isinstance(previous, dict):
                previous.update(raw_nodes)
                raw_nodes = previous
        except (OSError, json.JSONDecodeError):
            pass
    with open(nodes_file, "w") as f:
        json.dump(raw_nodes, f, ensure_ascii=False, indent=2)

    return node_data


def _node_wants_detail(node, siblings=None) -> bool:
    """Create/update field rows, empty shells, and editor settings the structure hid."""
    if not isinstance(node, dict) or node_editor_config.is_helper_node(node):
        return False
    if node_editor_config.config_is_empty(node):
        return True
    if is_field_detail_node(node) or field_mappings.needs_node_detail(node):
        return True
    return node_editor_config.needs_editor_detail(node, siblings)


def _remember_detail(snapshot, pid, node_id, payload) -> None:
    """Copy one getNodeDetail body onto the in-memory structure node."""
    if not isinstance(snapshot, dict):
        return
    structure = (snapshot.get("processes") or {}).get(pid)
    if not isinstance(structure, dict):
        return
    for node in mcp_workflow_structure.iter_structure_nodes(structure):
        current = str(node.get("nodeId") or node.get("id") or "")
        if current != node_id:
            continue
        node_editor_config.merge_detail_into(node, payload)
        raw_map = structure.get("flowNodeMap")
        if isinstance(raw_map, dict) and isinstance(raw_map.get(node_id), dict):
            node_editor_config.merge_detail_into(raw_map[node_id], payload)
        return


def extract_node_detail_configs(base_url: str, node_data: dict, project_dir: str,
                                merge_existing: bool = False, snapshot=None) -> dict:
    """Call getNodeDetail and save readable editor config.

    Reads nodes.json. Empty shells, create/update rows, and nodes whose
    editor fields are still unresolved each get one getNodeDetail call.
    field_mappings stays the 「将字段 / 设为」 block. editor_config is the
    same kind of readable line for every real node. Raw ids and tokens stay
    beside those lines.

    Returns {pid: [{node_id, node_name, type_id, target_sheet, controls, field_mappings}]}
    """
    import auth

    domain = platform_router.derive_cookie_domain(base_url)
    if not domain:
        print("  [skip] Node detail extraction: cannot derive cookie domain")
        return {}
    try:
        headers = auth.get_auth_headers(domain)
    except auth.CookieScopeError as e:
        print(f"  [skip] {e}")
        return {}
    if not headers:
        print("  [skip] Node detail extraction: no auth")
        return {}

    # Read the raw nodes.json saved by extract_workflow_nodes
    nodes_file = os.path.join(project_dir, "nodes.json")
    if not os.path.exists(nodes_file):
        print("  [skip] nodes.json not found")
        return {}

    with open(nodes_file) as f:
        raw_nodes = json.load(f)

    # Create/update rows, empty shells, and nodes whose editor text is still hidden.
    detail_jobs = []  # (pid, wf_name, node_id, type_id, node_name, type_label, node, siblings)
    for pid, wf_data in raw_nodes.items():
        if not isinstance(wf_data, dict):
            continue
        wf_name = wf_data.get("_name", pid[:16])
        siblings = {
            key: value for key, value in wf_data.items()
            if isinstance(key, str) and not key.startswith("_") and isinstance(value, dict)
        }
        for nkey, node in wf_data.items():
            if not isinstance(nkey, str) or nkey.startswith("_") or not isinstance(node, dict):
                continue
            if _node_wants_detail(node, siblings):
                detail_jobs.append((
                    pid,
                    wf_name,
                    node.get("nodeId") or node.get("id") or nkey,
                    _detail_type_id(node),
                    node.get("name", ""),
                    detail_type_label(node) if is_field_detail_node(node) else (node.get("name") or ""),
                    node,
                    siblings,
                ))

    if not detail_jobs:
        print("  No nodes need getNodeDetail")
        return {}

    print(f"  Extracting editor configs for {len(detail_jobs)} nodes...")
    node_configs = {}
    errors = 0

    for i, (pid, wf_name, node_id, type_id, node_name, type_label, node, siblings) in enumerate(detail_jobs):
        try:
            query = urllib.parse.urlencode({
                "processId": pid,
                "nodeId": node_id,
                "flowNodeType": type_id,
            })
            detail = platform_router.fetch_json(
                base_url,
                f"/api/workflow/flowNode/getNodeDetail?{query}",
                domain=domain,
            )

            ddata = detail.get("data", detail)
            if not isinstance(ddata, dict):
                errors += 1
                continue

            # Extract target sheet info from flowNodeAppDtos
            app_dtos = ddata.get("flowNodeAppDtos", [])
            target_sheet = ""
            controls = []

            if isinstance(app_dtos, list) and app_dtos and isinstance(app_dtos[0], dict):
                app0 = app_dtos[0]
                target_sheet = app0.get("appName", "")
                if isinstance(app0.get("controls"), list):
                    controls = app0.get("controls")
            if not controls and isinstance(ddata.get("controls"), list):
                controls = ddata.get("controls")

            # Also check flowNodeList for field mapping
            flow_node_list = ddata.get("flowNodeList", [])
            conditions = ddata.get("conditions", [])

            # Build compact config
            config = {
                "pid": pid,
                "wf_name": wf_name,
                "node_id": node_id,
                "node_name": node_name,
                "type_id": type_id,
                "type_label": type_label,
                "target_sheet": target_sheet,
                "conditions": conditions if conditions else [],
                "controls": [],
            }

            for ctrl in controls:
                if not isinstance(ctrl, dict):
                    continue
                config["controls"].append({
                    "controlId": ctrl.get("controlId", ""),
                    "controlName": ctrl.get("controlName", ""),
                    "type": ctrl.get("type", ""),
                    "required": ctrl.get("required", False),
                    "dataSource": ctrl.get("dataSource", ""),
                    "sourceEntityName": ctrl.get("sourceEntityName", ""),
                    "options": ctrl.get("options", [])[:20],  # limit option list
                    "desc": ctrl.get("desc", ""),
                })

            detail_view = field_mappings.prepare_detail(ddata)
            if not detail_view.get("controls") and controls:
                detail_view["controls"] = controls
            node_editor_config.merge_detail_into(node, detail_view)
            _remember_detail(snapshot, pid, node_id, detail_view)
            mapping = field_mappings.resolve_field_mappings(node, detail_view)
            if mapping:
                config["field_mappings"] = mapping
            editor = node_editor_config.resolve_editor_config(
                node, detail_view, flow_nodes=siblings, detail_seen=True,
            )
            if editor:
                config["editor_config"] = editor
            if detail_view.get("fields"):
                config["fields"] = detail_view.get("fields")
            elif node.get("fields"):
                config["fields"] = node.get("fields")
            if detail_view.get("formulaMap"):
                config["formulaMap"] = detail_view.get("formulaMap")
            if detail_view.get("selectNodeObj"):
                config["selectNodeObj"] = detail_view.get("selectNodeObj")

            if pid not in node_configs:
                node_configs[pid] = []
            node_configs[pid].append(config)

            if (i + 1) % 20 == 0:
                print(f"    {i + 1}/{len(detail_jobs)}...")
            time.sleep(0.15)  # Rate limit

        except Exception as e:
            errors += 1

    # Save. Cookie rows replace the same node_id; MCP rows for other nodes stay.
    configs_file = os.path.join(project_dir, "_node_configs.json")
    if merge_existing and os.path.exists(configs_file):
        try:
            with open(configs_file, encoding="utf-8") as existing:
                previous = json.load(existing)
        except (OSError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict):
            for pid, items in node_configs.items():
                prior = previous.get(pid) if isinstance(previous.get(pid), list) else []
                by_id = {item.get("node_id"): item for item in prior if isinstance(item, dict)}
                for item in items:
                    by_id[item.get("node_id")] = item
                previous[pid] = list(by_id.values())
            node_configs = previous
    with open(configs_file, "w") as f:
        json.dump(node_configs, f, ensure_ascii=False, indent=2)
    with open(nodes_file, "w", encoding="utf-8") as handle:
        json.dump(raw_nodes, handle, ensure_ascii=False, indent=2)

    total_nodes = sum(len(v) for v in node_configs.values())
    wf_count = len(node_configs)
    print(f"  Node configs extracted: {total_nodes} nodes across {wf_count} workflows ({errors} errors)")
    print(f"  Saved to _node_configs.json")
    return node_configs


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
            **({"incomplete": True} if info.get("incomplete") else {}),
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

    # Derived sections shared with build_context.py (legacy _extracted layout).
    # Modern extraction keeps only id/name/type/required/isTitle per field, so
    # association targets and auto-number formats are often absent. Fall back
    # to workflow read/write edges and auto-number field names when needed.
    worksheet_records = [
        {"name": name, "worksheet_id": info.get("id", ""), "fields": info.get("fields", [])}
        for name, info in worksheets.items()
    ]
    derived = context_fields.compute_context_fields(worksheet_records)
    if not derived["relation_graph"] and node_data:
        edges, reverse_edges = context_fields.compute_workflow_edges(node_data)
        derived["relation_graph"] = {k: list(v) for k, v in edges.items()}
        derived["reverse_refs"] = {k: list(v) for k, v in reverse_edges.items()}
        derived["hub_tables"] = context_fields.compute_hub_tables(reverse_edges)
    if not derived["naming"]["auto_number_prefixes"]:
        derived["naming"]["auto_number_prefixes"] = \
            context_fields.auto_number_prefixes_from_field_names(worksheet_records)

    return {
        "project": {
            "name": project_name,
            "total_worksheets": len(worksheets),
            "total_workflows": len(wf_list),
            "total_modules": 1,
        },
        "worksheets": worksheets,
        "relation_graph": derived["relation_graph"],
        "hub_tables": derived["hub_tables"],
        "naming": derived["naming"],
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
                   mcp_configured: bool, base_url: str) -> str:
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
        f"- MCP: {'已通过运行时参数配置（地址未落盘）' if mcp_configured else '未使用'}",
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
def update_registry(project_name: str, ws_count: int, wf_count: int,
                    mcp_configured: bool = False):
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
        "mcp_configured": mcp_configured,
    }

    # 旧版本曾把完整凭证化 URL 写入 registry；写回时统一清除。
    for project in reg.get("projects", {}).values():
        if isinstance(project, dict):
            project.pop("mcp_url", None)

    with open(registry_path, "w") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    print(f"  Registry updated: {registry_path}")


def _workflow_pid(workflow: dict) -> str:
    if not isinstance(workflow, dict):
        return ""
    return str(workflow.get("id") or workflow.get("processId") or "").strip()


def _fetch_legacy_flow(base_url, process_id):
    """GET flowNode/get the way hap-cli ``workflow structure`` does. No count cap."""
    query = urllib.parse.urlencode({"processId": process_id})
    return platform_router.fetch_json(
        base_url,
        f"/api/workflow/flowNode/get?{query}",
        domain=platform_router.derive_cookie_domain(base_url),
    )


def _detail_type_id(node) -> int:
    """flowNodeType for getNodeDetail. Keeps the old data-op default."""
    if not isinstance(node, dict):
        return DATA_OPERATION_TYPE
    return node_editor_config.flow_node_type(node)


def _apply_flow_summaries(snapshot, node_data) -> None:
    """Fill reads/writes from a legacy flowNodeMap, and readable CRUD lines either way."""
    for pid, structure in (snapshot.get("processes") or {}).items():
        if pid not in node_data or not isinstance(structure, dict):
            continue
        flow_map = structure.get("flowNodeMap")
        if isinstance(flow_map, dict) and flow_map:
            summary = summarize_flow_nodes(flow_map)
            node_data[pid].update({
                "node_count": summary["node_count"],
                "reads": sorted(summary["reads"]),
                "writes": sorted(summary["writes"]),
                "crud_field_mappings": summary["crud_field_mappings"],
                "query_empty_actions": summary["query_empty_actions"],
                "approval_count": summary["approval_count"],
                "trigger_sheet": summary.get("trigger_sheet") or node_data[pid].get("worksheet") or "",
            })
            continue
        mappings = []
        for node in mcp_workflow_structure.iter_structure_nodes(structure):
            mapping = field_mappings.resolve_field_mappings(node)
            if not mapping or not mapping.get("assignments"):
                continue
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            target = (
                config.get("appName")
                or config.get("sourceEntityName")
                or node.get("appName")
                or (mapping.get("update_object") or {}).get("worksheet")
                or ""
            )
            mappings.append({
                "node_name": node.get("name") or "",
                "target": target,
                "update_object": mapping.get("update_object"),
                "readable": mapping.get("lines") or [],
                "raw": field_mappings.raw_assignment_summary(mapping),
            })
        if mappings:
            node_data[pid]["crud_field_mappings"] = mappings


def _load_node_configs(project_dir) -> dict:
    path = os.path.join(project_dir, "_node_configs.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _mapping_resolved(row) -> bool:
    mapping = row.get("field_mappings") if isinstance(row, dict) else None
    if not isinstance(mapping, dict):
        return False
    assignments = mapping.get("assignments") or []
    if not assignments:
        return False
    return not any(isinstance(item, dict) and item.get("unresolved") for item in assignments)


def _field_detail(flat, node) -> dict:
    fields = flat.get("fields") if isinstance(flat.get("fields"), list) and flat.get("fields") else None
    if fields is None:
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if isinstance(config.get("fields"), list):
            fields = config.get("fields")
        elif isinstance(node.get("fields"), list):
            fields = node.get("fields")
    controls = []
    raw_controls = flat.get("controls") if isinstance(flat.get("controls"), list) else []
    for control in raw_controls:
        if not isinstance(control, dict):
            continue
        controls.append({
            "controlId": control.get("controlId") or control.get("id") or "",
            "controlName": control.get("controlName") or control.get("name") or "",
            "type": control.get("type", ""),
            "sourceEntityName": control.get("sourceEntityName") or "",
        })
    return {
        "fields": fields or [],
        "formulaMap": flat.get("formulaMap") if isinstance(flat.get("formulaMap"), dict) else {},
        "selectNodeObj": flat.get("selectNodeObj") if isinstance(flat.get("selectNodeObj"), dict) else {},
        "controls": controls,
    }


def _flow_index(structure) -> dict:
    index = {}
    for node in mcp_workflow_structure.iter_structure_nodes(structure):
        node_id = str(node.get("nodeId") or node.get("id") or "")
        if node_id:
            index[node_id] = node
    return index


def _editor_saved(row) -> bool:
    editor = row.get("editor_config") if isinstance(row, dict) else None
    if not isinstance(editor, dict):
        return False
    if editor.get("helper"):
        return True
    if editor.get("unresolved"):
        return False
    gaps = editor.get("gaps") or []
    return not any(
        isinstance(gap, dict) and gap.get("reason") in {"not_in_structure", "not_in_detail"}
        for gap in gaps
    )


def _enrich_readable_field_mappings(base_url, project_dir, snapshot) -> bool:
    """One getNodeDetail call when editor text would otherwise stay empty.

    Structure fetch is unchanged. Create/update rows still resolve
    「将字段 / 设为」. Query filters, branch conditions, trigger events, and
    the same class of editor settings are filled from the same response
    when the structure left them unresolved or as an empty placeholder.
    A default/else arm that already ends with an empty condition is not
    fetched again.
    """
    configs = _load_node_configs(project_dir)
    jobs = []
    for pid, structure in (snapshot.get("processes") or {}).items():
        flow_nodes = _flow_index(structure)
        for node in mcp_workflow_structure.iter_structure_nodes(structure):
            needs_fields = field_mappings.needs_node_detail(node)
            needs_editor = node_editor_config.needs_editor_detail(node, flow_nodes)
            if not needs_fields and not needs_editor:
                continue
            node_id = str(node.get("nodeId") or node.get("id") or "")
            rows = configs.get(pid) if isinstance(configs.get(pid), list) else []
            saved = next(
                (row for row in rows if isinstance(row, dict) and row.get("node_id") == node_id),
                None,
            )
            if (
                saved
                and (not needs_fields or _mapping_resolved(saved))
                and (not needs_editor or _editor_saved(saved))
            ):
                continue
            if node_id:
                jobs.append((str(pid), node_id, node, structure, flow_nodes))
    if not jobs:
        return False

    print(f"--- Phase 3d: getNodeDetail（编辑器配置，{len(jobs)} 个节点） ---")
    changed = False
    stop = False
    for pid, node_id, node, structure, flow_nodes in jobs:
        if stop:
            break
        try:
            query = urllib.parse.urlencode({
                "processId": pid,
                "nodeId": node_id,
                "flowNodeType": _detail_type_id(node),
            })
            payload = platform_router.fetch_json(
                base_url,
                f"/api/workflow/flowNode/getNodeDetail?{query}",
                domain=platform_router.derive_cookie_domain(base_url),
            )
        except Exception as exc:
            print(f"  [skip] 节点配置 {node_id}: {mcp_workflow_structure.public_error(exc)}")
            if "未登录" in str(exc):
                stop = True
            continue
        flat = field_mappings.prepare_detail(payload)
        node_editor_config.merge_detail_into(node, flat)
        raw_map = structure.get("flowNodeMap") if isinstance(structure, dict) else None
        if isinstance(raw_map, dict) and isinstance(raw_map.get(node_id), dict):
            node_editor_config.merge_detail_into(raw_map[node_id], flat)
        mapping = field_mappings.resolve_field_mappings(node)
        editor = node_editor_config.resolve_editor_config(
            node, flow_nodes=flow_nodes, detail_seen=True,
        )
        rows = configs.get(pid)
        if not isinstance(rows, list):
            rows = []
            configs[pid] = rows
        detail_view = _field_detail(flat, node)
        updated = False
        for row in rows:
            if isinstance(row, dict) and row.get("node_id") == node_id:
                if mapping:
                    row["field_mappings"] = mapping
                    row["field_detail"] = detail_view
                if editor:
                    row["editor_config"] = editor
                updated = True
        if not updated:
            extra = {
                "pid": pid,
                "node_id": node_id,
                "node_name": node.get("name") or "",
            }
            if mapping:
                extra["field_mappings"] = mapping
                extra["field_detail"] = detail_view
            if editor:
                extra["editor_config"] = editor
            rows.append(extra)
        changed = True
        time.sleep(0.15)

    if changed:
        with open(os.path.join(project_dir, "_node_configs.json"), "w", encoding="utf-8") as handle:
            json.dump(configs, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(project_dir, mcp_workflow_structure.SNAPSHOT_NAME), "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(project_dir, "nodes.json"), "w", encoding="utf-8") as handle:
            json.dump(mcp_workflow_structure.nodes_document(snapshot), handle, ensure_ascii=False, indent=2)
        print("  可读节点配置已写入 _node_configs.json")
    return changed


def collect_workflow_nodes(project_dir, wf_list, *, mcp_url, base_url, nodes_file=None,
                           process_id="", skip_mcp=False) -> dict:
    """Node config via MCP V3 structure, then legacy flowNode/get for nested flows.

    get_workflow_details is not used here. It has no node structure. Chrome
    getNodeDetail fills nodes whose config is empty, and nodes whose editor
    text would otherwise stay empty or unresolved: query filters, branch
    conditions, trigger events, and create/update 「将字段 / 设为」 lines.
    A branch arm that already ends with an empty condition is the default
    path and is not fetched again.
    """
    if nodes_file:
        return extract_workflow_nodes_from_file(nodes_file, wf_list)

    roots = [process_id] if process_id else []
    if not roots:
        for workflow in wf_list or []:
            pid = _workflow_pid(workflow)
            if pid and pid not in roots:
                roots.append(pid)

    node_data = {}
    if mcp_url and not skip_mcp and roots:
        print("--- Phase 3a: MCP get_workflow_structure ---")
        tools = init_and_list_tools(mcp_url)
        snapshot = mcp_workflow_structure.extract_structures(
            roots,
            tools,
            lambda name, args: call_tool(mcp_url, name, args),
        )
        if snapshot.get("tool"):
            print(
                f"  MCP structures: {len(snapshot.get('processes') or {})} processes, "
                f"incomplete={snapshot.get('incomplete')}"
            )
        else:
            print("  [mcp] get_workflow_structure 不可用，嵌套流程改走 flowNode/get")
    else:
        snapshot = {
            "source": "mcp_get_workflow_structure",
            "tool": None,
            "argument": None,
            "incomplete": bool(roots),
            "gaps": [{"reason": "structure_tool_unavailable"}] if roots else [],
            "processes": {},
        }

    targets = mcp_workflow_structure.legacy_targets(snapshot, roots) if base_url else []
    if targets:
        print("--- Phase 3b: legacy flowNode/get（审批块与子流程） ---")
        legacy = mcp_workflow_structure.extract_legacy_structures(
            targets, lambda pid: _fetch_legacy_flow(base_url, pid),
        )
        snapshot = mcp_workflow_structure.merge_legacy(snapshot, legacy, roots)
        print(
            f"  legacy processes: {len(legacy.get('processes') or {})}, "
            f"incomplete={snapshot.get('incomplete')}"
        )

    if snapshot.get("processes") or snapshot.get("gaps"):
        mcp_workflow_structure.persist(project_dir, snapshot)
        node_data = mcp_workflow_structure.node_data_from_snapshot(snapshot, wf_list)
        _apply_flow_summaries(snapshot, node_data)

    empty_config = [
        gap for gap in snapshot.get("gaps") or []
        if gap.get("reason") == "empty_config" and gap.get("process_id")
    ]
    if empty_config and base_url:
        print("--- Phase 3c: Chrome getNodeDetail（仅补空 config） ---")
        extract_node_detail_configs(
            base_url, node_data, project_dir,
            merge_existing=bool(snapshot.get("processes")),
            snapshot=snapshot,
        )
    elif not node_data and not nodes_file:
        print("  [skip] 无 MCP 结构，也没有可用的 Base URL / 节点文件")
    if base_url and snapshot.get("processes") and _enrich_readable_field_mappings(base_url, project_dir, snapshot):
        _apply_flow_summaries(snapshot, node_data)
    return node_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    project_name = sys.argv[1]

    # Parse --mcp-url and --pids-file
    explicit_mcp_url = None
    full_extract = False
    pids_file = None
    skip_mcp = False
    base_url_override = None
    nodes_file = None
    process_id_arg = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--mcp-url" and i + 1 < len(sys.argv):
            explicit_mcp_url = sys.argv[i + 1]
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
        if arg == "--process-id" and i + 1 < len(sys.argv):
            process_id_arg = sys.argv[i + 1].strip()
    mcp_url = resolve_mcp_url(explicit_mcp_url)
    if not skip_mcp and not mcp_url:
        print(
            "ERROR: 必须通过 --mcp-url 或 HAP_MCP_URL 提供 MCP 地址；"
            "仓库不包含默认凭证。",
            file=sys.stderr,
        )
        sys.exit(2)
    derived_base_url = derive_base_url(mcp_url)
    if mcp_url and not derived_base_url:
        print("ERROR: MCP URL 必须是有效的 http(s) URL。", file=sys.stderr)
        sys.exit(2)
    normalized_override = derive_base_url(base_url_override)
    if base_url_override and not normalized_override:
        print("ERROR: --base-url 必须是有效的 http(s) URL。", file=sys.stderr)
        sys.exit(2)
    base_url = normalized_override or derived_base_url
    if pids_file and not nodes_file and not base_url:
        print(
            "ERROR: 使用 --pids-file 拉取节点时必须提供 --base-url，"
            "或配置可推导 origin 的 MCP URL。",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"=== 项目提取: {project_name} ===")
    print(f"MCP origin: {display_mcp_origin(mcp_url)}")
    print(f"Base URL: {base_url or '(not configured)'}")
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
    app_id = None
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

    # A /workflowedit/<processId> URL selects that process when --process-id is absent.
    if not process_id_arg and base_url_override:
        try:
            parsed_platform = platform_router.parse_platform_url(base_url_override)
        except platform_router.PlatformError:
            parsed_platform = {}
        if parsed_platform.get("kind") == "workflow" and parsed_platform.get("pid"):
            process_id_arg = parsed_platform["pid"]

    if process_id_arg and not any(
        (wf.get("id") or wf.get("processId")) == process_id_arg for wf in wf_list if isinstance(wf, dict)
    ):
        wf_list.append({
            "id": process_id_arg,
            "processId": process_id_arg,
            "name": process_id_arg,
            "trigger": "",
            "worksheet": "",
        })

    # Phase 3: MCP structure first. getNodeDetail fills empty config and unresolved editor text.
    print("--- Phase 3: 工作流节点 ---")
    node_data = collect_workflow_nodes(
        project_dir,
        wf_list,
        mcp_url=mcp_url,
        base_url=base_url,
        nodes_file=nodes_file,
        process_id=process_id_arg,
        skip_mcp=skip_mcp,
    )

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
    snapshot = build_snapshot(
        project_name,
        ws_map,
        wf_list,
        manifest,
        bool(mcp_url),
        base_url or "未配置",
    )
    with open(os.path.join(project_dir, "project-snapshot.md"), "w") as f:
        f.write(snapshot)
    print("  project-snapshot.md")

    # 4b. 平台绑定只使用 URL 里的 app id。MCP app id 不一致时不写 platform.json。
    if base_url:
        try:
            url_app_id = ""
            if base_url_override:
                url_app_id = platform_router.parse_platform_url(base_url_override).get("app_id") or ""
            mcp_app_id = ""
            if mcp_url and not skip_mcp:
                mcp_app_id = get_app_id_from_mcp(mcp_url) or ""
            binding_app_id = platform_router.resolve_binding_app_id(url_app_id, mcp_app_id)
            platform_router.save_binding(
                project_dir,
                origin=base_url,
                domain=platform_router.derive_cookie_domain(base_url),
                app_id=binding_app_id,
                source="extract-project",
            )
            print("  platform.json")
        except Exception as e:
            print(f"  [skip] platform.json 未写入: {e}")

    # 5. Registry
    update_registry(project_name, len(ws_map), len(wf_list), bool(mcp_url))

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
        print("节点级数据: 不可用 (MCP 未提供 get_workflow_structure，且没有 Chrome 节点接口)")
    print()
    print("下一步:")
    print(f"  1. 编辑 aliases.json 填充客户术语映射")
    print(f"  2. /hhr-plan → Mode D 健康审计")
    print(f"  3. 后续刷新: python3 {__file__} {project_name}")


if __name__ == "__main__":
    main()
