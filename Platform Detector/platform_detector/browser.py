"""Stealth fetch: TLS impersonation + Smartproxy residential IPs. No browser needed."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse

from .signals import Signals

log = logging.getLogger(__name__)

# ── Proxy config (override via env vars for security) ──
PROXY_USER = os.getenv("PROXY_USER", "smart-tti0q16uqyca")
PROXY_PASS = os.getenv("PROXY_PASS", "Zq6tUW02FqlRx84Q")
PROXY_HOST = os.getenv("PROXY_HOST", "proxy.smartproxy.net")
PROXY_PORT = os.getenv("PROXY_PORT", "3120")

PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"


class _BrowserHandle:
    """Stub so Detector.aclose() doesn't break."""
    async def close(self) -> None:
        pass


def _fetch_sync(url: str, domain: str, timeout: int = 30) -> tuple[Signals, str, str]:
    """Stealth HTTP request: real Chrome TLS fingerprint + residential proxy IP."""
    from curl_cffi import requests as cffi_requests

    # ── Try to grab real Chrome cookies (optional, may not match proxy IP) ──
    cookies: dict[str, str] = {}
    try:
        import rookiepy
        raw = rookiepy.chrome([domain])
        cookies = {c["name"]: c["value"] for c in raw}
        log.debug("Loaded %d cookies for %s", len(cookies), domain)
    except Exception:
        pass  # No cookies is fine — residential IP + TLS impersonation is enough

    session = cffi_requests.Session(impersonate="chrome")

    resp = session.get(
        url,
        proxies={"http": PROXY_URL, "https": PROXY_URL},
        cookies=cookies if cookies else None,
        timeout=timeout,
        allow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        },
    )

    headers = dict(resp.headers)
    cookie_names = list(resp.cookies.keys())
    html = resp.text
    status = resp.status_code
    final_url = str(resp.url)

    log.info("Fetch via proxy: %s → %d (%d bytes)", final_url, status, len(html))

    return (
        Signals(headers=headers, cookies=cookie_names, html=html, status=status),
        final_url,
        "",
    )


async def fetch_with_browser(
    det: Any, url: str
) -> tuple[Optional[Signals], str, str]:
    """Fetch via Smartproxy residential IP + Chrome TLS impersonation."""
    try:
        if getattr(det, "_browser", None) is None:
            det._browser = _BrowserHandle()

        parsed = urlparse(url if "://" in url else f"https://{url}")
        domain = parsed.hostname or url

        return await asyncio.to_thread(_fetch_sync, url, domain, det.s.timeout)

    except Exception as e:
        log.error("Stealth fetch failed: %s", e, exc_info=True)
        return None, url, str(e)