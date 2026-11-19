#!/usr/bin/env python3
"""平台路由 — 任意明道云私有部署的 URL 解析、认证与内部 API 访问。

不写死任何域名：用户给 URL（http://<host>/app/<app_id>/workflow 或
http://<host>/workflowedit/<pid>），本模块推导 origin/域名、读该域 Chrome
Cookie（md_pss_id → Authorization）、调该平台内部 API。

Usage:
    python3 platform_router.py parse <平台URL>
    python3 platform_router.py probe <平台URL> [--pid <PID>]

安全约定:
  - 日志/错误消息只含 origin/domain 级信息，永不打印 Cookie/Token。
  - 平台绑定文件（platform.json）只存 origin + app_id，不含凭证。
  - browser_cookie3 经 auth.py 惰性加载；CI 无此包时不崩溃。
"""

import argparse
import contextlib
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "PlatformError",
    "derive_origin",
    "derive_cookie_domain",
    "parse_platform_url",
    "get_auth_headers",
    "fetch_json",
    "fetch_workflow_nodes",
    "fetch_workflow_list",
    "fetch_workflow_count",
    "load_binding",
    "save_binding",
    "resolve_binding",
]

_SCRIPT_DIR = Path(__file__).resolve().parent


class PlatformError(Exception):
    """平台路由失败（消息只含 origin/domain 级信息，不含凭证）。"""


# ---------------------------------------------------------------------------
# URL 解析
# ---------------------------------------------------------------------------
def derive_origin(url):
    """scheme://host[:port]；无效 http(s) URL 返回 None。不改写 scheme（fusion 是 http）。"""
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
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


def derive_cookie_domain(url):
    """hostname（去端口）；Cookie 按域存储。无效 URL 返回空串。"""
    if not url:
        return ""
    return urlsplit(url).hostname or ""


def parse_platform_url(url):
    """解析平台 URL → {origin, domain, app_id, pid, kind}。

    kind: "app"（/app/<app_id>/...）、"workflow"（/workflowedit/<pid>/...）、
    "unknown"（裸 origin）。非法 scheme/无 host 抛 PlatformError。
    """
    origin = derive_origin(url)
    if not origin:
        raise PlatformError("平台 URL 必须是 http(s)://host 形式，无法解析出有效 origin")
    domain = derive_cookie_domain(url)
    app_id, pid, kind = "", "", "unknown"
    parts = [p for p in urlsplit(url).path.split("/") if p]
    for i, part in enumerate(parts):
        if part == "app" and i + 1 < len(parts):
            app_id = parts[i + 1]
            kind = "app"
        elif part == "workflowedit" and i + 1 < len(parts):
            pid = parts[i + 1]
            kind = "workflow"
    return {"origin": origin, "domain": domain, "app_id": app_id, "pid": pid, "kind": kind}


# ---------------------------------------------------------------------------
# 认证（惰性加载 auth.py，Chrome Cookie）
# ---------------------------------------------------------------------------
def _load_auth_module():
    """加载 scripts/auth.py；browser_cookie3 缺失（CI）时返回 None。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("platform_router_auth", _SCRIPT_DIR / "auth.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _extract_cookie(cookie_str, name):
    for part in cookie_str.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return ""


def get_auth_headers(domain):
    """域级认证头；无 Chrome Cookie 时返回 None。

    auth.py 的 print 走 stdout —— 重定向到 stderr，保持 CLI stdout 纯 JSON。
    Cookie 含 md_pss_id 时追加 `Authorization: md_pss_id <token>`。
    """
    auth = _load_auth_module()
    if auth is None:
        return None
    with contextlib.redirect_stdout(sys.stderr):
        try:
            headers = auth.get_auth_headers(domain)
        except Exception:
            return None
    if not headers:
        return None
    token = _extract_cookie(headers.get("Cookie", ""), "md_pss_id")
    if token:
        headers = dict(headers)
        headers["Authorization"] = f"md_pss_id {token}"
    return headers


# ---------------------------------------------------------------------------
# 网络层（唯一网络缝，测试替换 _urlopen_json）
# ---------------------------------------------------------------------------
def _urlopen_json(req, timeout=15):
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_json(origin, path, domain=None, method="GET", payload=None):
    """唯一网络入口。domain 为空 = 匿名；给出 domain 但未登录 → PlatformError。

    HTTPError / JSONDecodeError 等统一转 PlatformError，消息不含 Cookie。
    """
    headers = {}
    if domain:
        auth_headers = get_auth_headers(domain)
        if not auth_headers:
            raise PlatformError(f"未登录 Chrome（{domain}）")
        headers.update(auth_headers)
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(origin + path, data=body, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        return _urlopen_json(req)
    except PlatformError:
        raise
    except Exception as e:
        status = getattr(e, "code", None)
        detail = f"HTTP {status}" if status else type(e).__name__
        raise PlatformError(f"{method} {origin}{path} → {detail}") from None


# ---------------------------------------------------------------------------
# 内部 API 封装
# ---------------------------------------------------------------------------
def fetch_workflow_nodes(origin, pid):
    """节点接口跨平台一致：GET /api/workflow/flowNode/get → data.flowNodeMap（dict）。"""
    data = fetch_json(origin, f"/api/workflow/flowNode/get?processId={pid}&count=200",
                      domain=derive_cookie_domain(origin))
    inner = data.get("data", data) if isinstance(data, dict) else None
    if isinstance(inner, dict) and "flowNodeMap" in inner:
        fm = inner["flowNodeMap"]
        if isinstance(fm, dict):
            return list(fm.values())
        if isinstance(fm, list):
            return fm
        raise PlatformError(f"{origin}: flowNodeMap 形状不可识别")
    if isinstance(inner, list):
        return inner
    raise PlatformError(f"{origin}: 节点接口响应形状不可识别")


def _list_probes(app_id):
    """列表接口各平台版本不一，按序探测。"""
    return (
        ("v1/process/listAll", "GET",
         f"/api/workflow/v1/process/listAll?relationId={app_id}", None),
        ("process/getProcessList", "POST",
         "/api/process/getProcessList",
         {"appId": app_id, "pageIndex": 1, "pageSize": 1000}),
        ("v1/process/list", "GET",
         f"/api/workflow/v1/process/list?relationId={app_id}&pageSize=500", None),
    )


_PROBE_CACHE = {}  # (origin, app_id) -> 命中端点序号（进程内）


def _find_list(data):
    """从响应中提取工作流列表；形状不可识别返回 None。

    支持: 裸列表 / {"data": [...]} / {"data": {"list": [...]}} /
    分组形态 {"data": {"<组>": [...], ...}}（合并所有列表值）。
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    inner = data.get("data", data)
    if isinstance(inner, list):
        return inner
    if not isinstance(inner, dict):
        return None
    for key in ("list", "items", "records", "workflows"):
        if isinstance(inner.get(key), list):
            return inner[key]
    groups = [v for v in inner.values() if isinstance(v, list)]
    if groups:
        return [item for group in groups for item in group]
    return None


def _normalize_workflows(items):
    """归一化为 [{id, name, ...原字段}]，按 id/name 去重。

    fusion 平台 listAll 返回分组形态 [{groupId, groupName, processList: [...]}]，
    需拍平嵌套的 processList。
    """
    result, seen = [], set()

    def add(item):
        if not isinstance(item, dict):
            return
        entry = dict(item)
        entry.setdefault("id", str(item.get("id") or item.get("processId")
                                   or item.get("process_id") or ""))
        entry.setdefault("name", item.get("name") or item.get("processName")
                         or item.get("title") or "")
        key = entry["id"] or entry["name"]
        if key and key not in seen:
            seen.add(key)
            result.append(entry)

    for item in items:
        if isinstance(item, dict) and isinstance(item.get("processList"), list):
            for workflow in item["processList"]:
                add(workflow)
        else:
            add(item)
    return result


def fetch_workflow_list(origin, app_id):
    """按序探测三个列表端点，首个形状可识别的胜出（空列表=成功=应用没流）。

    进程内缓存命中端点；全部失败抛 PlatformError。
    """
    domain = derive_cookie_domain(origin)
    cache_key = (origin, app_id)
    probes = _list_probes(app_id)
    if cache_key in _PROBE_CACHE:
        label, method, path, payload = probes[_PROBE_CACHE[cache_key]]
        items = _find_list(fetch_json(origin, path, domain=domain, method=method, payload=payload))
        if items is None:
            raise PlatformError(f"{label}: 响应形状不可识别")
        return _normalize_workflows(items)
    errors = []
    for index, (label, method, path, payload) in enumerate(probes):
        try:
            data = fetch_json(origin, path, domain=domain, method=method, payload=payload)
        except PlatformError as e:
            errors.append(f"{label}: {e}")
            continue
        items = _find_list(data)
        if items is None:
            errors.append(f"{label}: 响应形状不可识别")
            continue
        _PROBE_CACHE[cache_key] = index
        return _normalize_workflows(items)
    raise PlatformError("工作流列表接口全部不可用: " + "; ".join(errors))


def fetch_workflow_count(origin, app_id):
    """GET /api/workflow/v1/process/count — best-effort，失败返回 None。"""
    try:
        data = fetch_json(
            origin, f"/api/workflow/v1/process/count?relationId={app_id}&relationType=2",
            domain=derive_cookie_domain(origin))
    except PlatformError:
        return None
    if not isinstance(data, dict):
        return None
    inner = data.get("data", data)
    if isinstance(inner, int):
        return inner
    if isinstance(inner, dict):
        for key in ("count", "total", "num"):
            if isinstance(inner.get(key), int):
                return inner[key]
    return None


# ---------------------------------------------------------------------------
# 项目 ↔ 平台绑定（<project>/platform.json）
# ---------------------------------------------------------------------------
_BINDING_KEYS = ("origin", "domain", "app_id", "pid", "source", "saved_at")


def load_binding(project_dir):
    """读绑定文件；损坏/缺失 → None。"""
    path = Path(project_dir) / "platform.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("origin"):
        return None
    return data


def save_binding(project_dir, *, origin, domain="", app_id="", pid="", source=""):
    """写绑定文件。只存 6 个白名单键，绝不含 Cookie/Token/HAP 凭证/查询串。"""
    path = Path(project_dir) / "platform.json"
    data = {
        "origin": origin,
        "domain": domain or derive_cookie_domain(origin),
        "app_id": app_id or "",
        "pid": pid or "",
        "source": source or "user_url",
        "saved_at": date.today().isoformat(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def resolve_binding(project_dir, url=None):
    """URL 参数优先于绑定文件。URL 形态不写盘（写盘在拉取成功后）。"""
    if url:
        parsed = parse_platform_url(url)
        return {
            "origin": parsed["origin"],
            "domain": parsed["domain"],
            "app_id": parsed["app_id"],
            "pid": parsed["pid"],
            "source": "user_url",
        }
    return load_binding(project_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser():
    parser = argparse.ArgumentParser(
        prog="platform_router.py",
        description="明道云私有部署平台路由：URL → origin/认证/内部 API")
    sub = parser.add_subparsers(dest="command", required=True)
    p_parse = sub.add_parser("parse", help="解析平台 URL（输出 origin/domain/app_id/pid/kind）")
    p_parse.add_argument("url")
    p_probe = sub.add_parser("probe", help="探测平台可达性（auth/列表/节点）")
    p_probe.add_argument("url")
    p_probe.add_argument("--pid", default="", help="工作流 PID，探测节点接口")
    return parser


def _cmd_probe(args):
    try:
        parsed = parse_platform_url(args.url)
    except PlatformError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    origin, domain = parsed["origin"], parsed["domain"]
    result = {"origin": origin, "domain": domain, "auth_ok": False}
    headers = get_auth_headers(domain)
    result["auth_ok"] = bool(headers)
    if not headers:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"[probe] {origin}: 无 Chrome 登录 Cookie，跳过 API 探测", file=sys.stderr)
        return 0
    if parsed.get("app_id"):
        try:
            workflows = fetch_workflow_list(origin, parsed["app_id"])
            result["list_count"] = len(workflows)
            result["list_endpoint"] = _list_probes(parsed["app_id"])[
                _PROBE_CACHE[(origin, parsed["app_id"])]][0]
        except PlatformError as e:
            result["list_error"] = str(e)
    pid = args.pid or parsed.get("pid") or ""
    if pid:
        try:
            result["node_count"] = len(fetch_workflow_nodes(origin, pid))
        except PlatformError as e:
            result["nodes_error"] = str(e)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.command == "parse":
        try:
            parsed = parse_platform_url(args.url)
        except PlatformError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        return 0
    if args.command == "probe":
        return _cmd_probe(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
