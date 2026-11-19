"""Auth module: read Chrome cookies for Mingdao API access.

Only the session cookie named md_pss_id is forwarded, and only when its host
matches the target host exactly (or a parent domain the caller explicitly
allows). A bare registrable domain is refused when the jar contains that
cookie for more than one host.
"""

class CookieScopeError(Exception):
    """The cookie jar is too broad for the requested host."""


def cookie_host(host_key: str) -> str:
    return (host_key or "").strip().lstrip(".").lower()


def is_bare_registrable_domain(domain: str) -> bool:
    """True for names like example.com. Subdomains and IP addresses are not bare."""
    host = cookie_host(domain)
    if not host or any(sep in host for sep in ("/", ":", " ")):
        return False
    labels = host.split(".")
    if len(labels) != 2:
        return False
    if all(label.isdigit() for label in labels):
        return False
    return all(label for label in labels)


def _cookie_parts(cookie):
    if isinstance(cookie, tuple):
        name, value, host = cookie[0], cookie[1], cookie[2] if len(cookie) > 2 else ""
    else:
        name = getattr(cookie, "name", "")
        value = getattr(cookie, "value", "")
        host = getattr(cookie, "domain", "") or getattr(cookie, "host_key", "")
    return name or "", value or "", cookie_host(host)


def cookie_matches_host(host_key: str, target: str, parent_domain: str | None = None) -> bool:
    """Exact host match, plus an explicitly allowed parent domain."""
    host = cookie_host(host_key)
    target_host = cookie_host(target)
    if not host or not target_host:
        return False
    if host == target_host:
        return True
    if parent_domain:
        parent = cookie_host(parent_domain)
        target_under_parent = target_host == parent or target_host.endswith("." + parent)
        if parent and host == parent and target_under_parent:
            return True
    return False


def select_md_pss_id(cookies, domain: str, parent_domain: str | None = None) -> str:
    """Return the single md_pss_id value allowed for domain.

    Raises CookieScopeError when a bare registrable domain would attach
    cookies from more than one host, or when more than one distinct value
    matches the target.
    """
    target = cookie_host(domain)
    if not target:
        raise CookieScopeError("缺少目标域名，拒绝附加 Cookie")

    sessions = []
    for cookie in cookies:
        name, value, host = _cookie_parts(cookie)
        if name == "md_pss_id" and value and host:
            sessions.append((value, host))

    distinct_hosts = {host for _, host in sessions}
    if is_bare_registrable_domain(target) and len(distinct_hosts) > 1:
        raise CookieScopeError(
            f"拒绝使用裸域名 {target}：md_pss_id 命中多个主机"
        )

    matched = [
        (value, host)
        for value, host in sessions
        if cookie_matches_host(host, target, parent_domain)
    ]
    if not matched:
        return ""

    exact = [value for value, host in matched if host == target]
    chosen = exact or [value for value, _host in matched]
    unique = set(chosen)
    if len(unique) != 1:
        raise CookieScopeError(f"{target} 匹配到多个不同的 md_pss_id，拒绝附加")
    return unique.pop()


def get_auth_headers(domain: str, parent_domain: str | None = None) -> dict | None:
    """Auth headers for one host. Cookie and Authorization carry only md_pss_id."""
    try:
        import browser_cookie3
    except ImportError:
        print(f"  [auth] browser_cookie3 is not installed; cannot read cookies for {domain}")
        return None

    try:
        jar = browser_cookie3.chrome(domain_name=domain)
    except Exception as e:
        print(f"  [auth] Cannot read Chrome cookies for {domain}: {e}")
        return None

    try:
        token = select_md_pss_id(jar, domain, parent_domain=parent_domain)
    except CookieScopeError as e:
        print(f"  [auth] {e}")
        raise

    if not token:
        print(f"  [auth] No md_pss_id cookie for {domain} — log into 明道云 in Chrome first")
        return None

    return {
        "Cookie": f"md_pss_id={token}",
        "Authorization": f"md_pss_id {token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
