"""Auth module: read Chrome cookies for Mingdao API access."""
import browser_cookie3

def get_auth_headers(domain: str) -> dict | None:
    """Get auth headers using Chrome cookies for the given domain."""
    try:
        cj = browser_cookie3.chrome(domain_name=domain)
    except Exception as e:
        print(f"  [auth] Cannot read Chrome cookies for {domain}: {e}")
        return None

    cookies = []
    for c in cj:
        cookies.append(f"{c.name}={c.value}")

    if not cookies:
        print(f"  [auth] No cookies found for {domain} — log into 明道云 in Chrome first")
        return None

    cookie_str = "; ".join(cookies)
    return {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
