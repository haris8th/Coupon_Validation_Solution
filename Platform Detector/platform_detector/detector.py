"""Async detection pipeline: homepage -> platform endpoints -> DNS -> (browser)."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from . import probes
from .signals import (
    CUSTOM,
    SHOPIFY,
    SHOPIFY_HEADLESS,
    UNKNOWN,
    WOOCOMMERCE,
    Hit,
    Signals,
    classify,
    is_blocked,
    is_wordpress,
    match_rules,
)

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; PlatformDetector/1.0; +platform detection, "
    "homepage + public store endpoints only)"
)
MAX_HTML_BYTES = 1_500_000


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    user_agent: str = os.environ.get("PD_USER_AGENT", DEFAULT_UA)
    timeout: float = _env_float("PD_TIMEOUT", 10.0)  # per HTTP request
    site_budget: float = _env_float("PD_SITE_BUDGET", 30.0)  # whole pipeline per site
    concurrency: int = int(_env_float("PD_CONCURRENCY", 20))
    cache_ttl: float = _env_float("PD_CACHE_TTL", 6 * 3600)
    confident: float = _env_float("PD_CONFIDENT", 0.9)  # stop early at/above this
    min_confidence: float = _env_float("PD_MIN_CONFIDENCE", 0.5)  # below -> custom
    use_browser: bool = os.environ.get("PD_USE_BROWSER", "0") == "1"
    headless: bool = os.environ.get("PD_HEADLESS", "0") == "1"  # default: visible browser window
    dns: bool = os.environ.get("PD_DNS", "1") == "1"


@dataclass
class DetectionResult:
    url: str
    platform: str
    confidence: float
    evidence: list[str]
    checked_at: str
    domain: str = ""
    final_url: str = ""
    reason: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    stages: list[str] = field(default_factory=list)
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(url: str) -> tuple[str, str]:
    """Return (base_url, domain) for any 'example.com' / 'https://www.x.com/path' input."""
    url = url.strip()
    if not url:
        raise ValueError("empty url")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        raise ValueError(f"invalid url: {url!r}")
    scheme = parts.scheme if parts.scheme in ("http", "https") else "https"
    netloc = host if not parts.port else f"{host}:{parts.port}"
    domain = host[4:] if host.startswith("www.") else host
    return f"{scheme}://{netloc}", domain


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TTLCache:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self._data: dict[str, tuple[float, DetectionResult]] = {}

    def get(self, key: str) -> Optional[DetectionResult]:
        item = self._data.get(key)
        if not item:
            return None
        ts, val = item
        if time.monotonic() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, val: DetectionResult) -> None:
        self._data[key] = (time.monotonic(), val)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class Detector:
    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.AsyncBaseTransport] = None,
                 resolver: Any = None):
        self.s = settings or Settings()
        self.cache = TTLCache(self.s.cache_ttl)
        self.sem = asyncio.Semaphore(self.s.concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._transport = transport
        self._resolver = resolver  # injectable for tests: async fn(domain) -> (cnames, ips)
        self._client: Optional[httpx.AsyncClient] = None
        self._insecure_client: Optional[httpx.AsyncClient] = None
        self._browser = None

    # ------------------------------------------------------------------ clients
    def _make_client(self, verify: bool = True) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "User-Agent": self.s.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.8",
            },
            timeout=httpx.Timeout(self.s.timeout, connect=min(5.0, self.s.timeout)),
            follow_redirects=True,
            max_redirects=8,
            limits=httpx.Limits(max_connections=self.s.concurrency * 4, max_keepalive_connections=self.s.concurrency),
            verify=verify,
            transport=self._transport,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._make_client()
        return self._client

    async def aclose(self) -> None:
        for c in (self._client, self._insecure_client):
            if c is not None:
                await c.aclose()
        self._client = self._insecure_client = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None

    async def __aenter__(self) -> "Detector":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ public
    async def detect(self, url: str, refresh: bool = False, use_browser: Optional[bool] = None) -> DetectionResult:
        try:
            base, domain = normalize(url)
        except ValueError as e:
            return DetectionResult(url, UNKNOWN, 0.0, [], _now(), reason=f"invalid_url: {e}")

        if not refresh:
            hit = self.cache.get(domain)
            if hit:
                return _copy(hit, url=url, cached=True)

        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:  # concurrent requests for one domain share a single run
            if not refresh:
                hit = self.cache.get(domain)
                if hit:
                    return _copy(hit, url=url, cached=True)
            async with self.sem:
                browser = self.s.use_browser if use_browser is None else use_browser
                try:
                    res = await asyncio.wait_for(self._run(url, base, domain, browser), self.s.site_budget)
                except asyncio.TimeoutError:
                    res = DetectionResult(url, UNKNOWN, 0.0, [], _now(), domain=domain, reason="timeout")
            if res.reason not in ("timeout",):
                self.cache.set(domain, res)
            return res

    async def detect_many(self, urls: list[str], **kw: Any) -> list[DetectionResult]:
        return list(await asyncio.gather(*(self.detect(u, **kw) for u in urls)))

    # ------------------------------------------------------------------ pipeline
    async def _run(self, url: str, base: str, domain: str, use_browser: bool) -> DetectionResult:
        stages: list[str] = []
        hits: list[Hit] = []
        extra_evidence: list[str] = []

        # 1. homepage
        stages.append("homepage")
        sig, final_url, err = await self._fetch_homepage(base)
        blocked = False
        wordpress = False
        if sig is not None:
            hits += match_rules(sig)
            blocked = is_blocked(sig)
            wordpress = is_wordpress(sig)
            if blocked:
                extra_evidence.append(f"homepage looks bot-walled (HTTP {sig.status})")
            if wordpress:
                extra_evidence.append("WordPress detected")
        else:
            extra_evidence.append(f"homepage fetch failed: {err}")

        verdict = classify(hits)
        if self._confident(verdict) and not blocked:
            return self._result(url, domain, final_url, verdict, stages, extra_evidence)

        # 2. platform endpoints (use the final host after redirects)
        origin = _origin(final_url) if final_url else base
        scores = verdict.scores
        want_shopify = sig is None or blocked or not scores or SHOPIFY in scores or SHOPIFY_HEADLESS in scores
        want_woo = sig is None or blocked or not scores or wordpress or WOOCOMMERCE in scores
        if want_shopify or want_woo:
            stages.append("endpoints")
            hits += await self._probe_endpoints(origin, want_shopify, want_woo)
            verdict = classify(hits)
            if self._confident(verdict):
                return self._result(url, domain, final_url, verdict, stages, extra_evidence)

        # 3. DNS
        if self.s.dns and (want_shopify or sig is None):
            stages.append("dns")
            cnames, ips = await self._resolve(domain)
            dns_hits = probes.score_dns(cnames, ips)
            hits += dns_hits
            verdict = classify(hits)
            if self._confident(verdict):
                return self._result(url, domain, final_url, verdict, stages, extra_evidence)

        # 4. browser fallback - only for bot-walled / unreachable-by-httpx pages
        if (blocked or sig is None) and verdict.confidence < self.s.min_confidence:
            if use_browser:
                stages.append("browser")
                bsig, burl, berr = await self._browser_fetch(base)
                if bsig is not None:
                    hits += match_rules(bsig)
                    final_url = burl or final_url
                    verdict = classify(hits)
                    if is_blocked(bsig) and verdict.confidence < self.s.min_confidence:
                        return self._unknown(url, domain, final_url, verdict, stages, extra_evidence, "blocked")
                    blocked, sig = False, bsig
                else:
                    extra_evidence.append(f"browser fetch failed: {berr}")
                    return self._unknown(url, domain, final_url, verdict, stages, extra_evidence, "blocked")
            else:
                reason = "blocked" if blocked else "unreachable"
                return self._unknown(url, domain, final_url, verdict, stages, extra_evidence, reason)

        return self._result(url, domain, final_url, verdict, stages, extra_evidence)

    def _confident(self, verdict: Any) -> bool:
        return verdict.confidence >= self.s.confident

    def _result(self, url, domain, final_url, verdict, stages, extra) -> DetectionResult:
        if verdict.confidence < self.s.min_confidence:
            # absence of evidence is never certainty, so custom tops out at 0.95
            platform, conf, reason = CUSTOM, round(min(0.95, 1.0 - verdict.confidence), 3), "no known platform signals"
            if verdict.scores:
                reason = f"weak signals only (best: {verdict.platform} {verdict.confidence})"
        else:
            platform, conf, reason = verdict.platform, verdict.confidence, ""
        return DetectionResult(url, platform, conf, verdict.evidence + extra, _now(), domain=domain,
                               final_url=final_url or "", reason=reason, scores=verdict.scores, stages=stages)

    def _unknown(self, url, domain, final_url, verdict, stages, extra, reason) -> DetectionResult:
        return DetectionResult(url, UNKNOWN, 0.0, verdict.evidence + extra, _now(), domain=domain,
                               final_url=final_url or "", reason=reason, scores=verdict.scores, stages=stages)

    # ------------------------------------------------------------------ io
    async def _get(self, url: str, accept_json: bool = False) -> httpx.Response:
        headers = {"Accept": "application/json"} if accept_json else None
        try:
            return await self.client.get(url, headers=headers)
        except httpx.ConnectError as e:
            if "CERTIFICATE" not in str(e).upper():
                raise
            if self._insecure_client is None:
                self._insecure_client = self._make_client(verify=False)
            return await self._insecure_client.get(url, headers=headers)

    async def _stream_homepage(self, client: httpx.AsyncClient, url: str) -> tuple[Signals, str]:
        async with client.stream("GET", url) as r:
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) >= MAX_HTML_BYTES:
                    break
            html = body.decode(r.encoding or "utf-8", errors="replace")
            return Signals(_merged_headers(r), _cookie_names(r), html, r.status_code), str(r.url)

    @staticmethod
    async def _with_dns_retry(fn, *args, attempts: int = 3):
        """Retry transient resolver failures (EAI_AGAIN / Windows WSATRY_AGAIN 11002).

        Under high concurrency the OS resolver sporadically returns "try again"
        for perfectly valid hosts; a short back-off makes these succeed.
        """
        for i in range(attempts):
            try:
                return await fn(*args)
            except httpx.ConnectError as e:
                msg = str(e)
                transient = "11002" in msg or "Temporary failure in name resolution" in msg or "EAI_AGAIN" in msg
                if not transient or i == attempts - 1:
                    raise
                await asyncio.sleep(0.5 * (i + 1))

    async def _fetch_homepage(self, base: str) -> tuple[Optional[Signals], str, str]:
        scheme, rest = base.split("://", 1)
        candidates = [base]
        if not rest.startswith("www."):
            candidates.append(f"{scheme}://www.{rest}")  # many stores only resolve on www.
        if scheme == "https":
            candidates.append("http://" + rest)
        last_err = "fetch failed"
        for cand in candidates:
            try:
                try:
                    sig, final = await self._with_dns_retry(self._stream_homepage, self.client, cand)
                except httpx.ConnectError as e:
                    if "CERTIFICATE" not in str(e).upper():
                        raise
                    if self._insecure_client is None:
                        self._insecure_client = self._make_client(verify=False)
                    sig, final = await self._stream_homepage(self._insecure_client, cand)
                return sig, final, ""
            except httpx.HTTPError as e:
                last_err = f"{type(e).__name__}: {e}"[:200]
        return None, "", last_err

    async def _probe_endpoints(self, origin: str, shopify: bool, woo: bool) -> list[Hit]:
        async def one(path: str, scorer) -> list[Hit]:
            try:
                r = await self._with_dns_retry(self._get, origin + path, True)
                return scorer(r.status_code, r.text[:200_000])
            except httpx.HTTPError:
                return []

        tasks = []
        if shopify:
            for p in probes.SHOPIFY_ENDPOINTS:
                tasks.append(one(p, lambda st, body, p=p: probes.score_shopify_endpoint(p, st, body)))
        if woo:
            tasks.append(one(probes.WOO_ENDPOINT, probes.score_woo_endpoint))
        out: list[Hit] = []
        for res in await asyncio.gather(*tasks):
            out += res
        return out

    async def _resolve(self, domain: str) -> tuple[list[str], list[str]]:
        if self._resolver is not None:
            return await self._resolver(domain)
        try:
            import dns.asyncresolver  # type: ignore
            import dns.exception  # type: ignore
        except ImportError:
            return [], []
        res = dns.asyncresolver.Resolver()
        res.lifetime = min(5.0, self.s.timeout)
        cnames: list[str] = []
        ips: list[str] = []
        for host in (domain, "www." + domain):
            for rtype, sink in (("CNAME", cnames), ("A", ips), ("AAAA", ips)):
                try:
                    ans = await res.resolve(host, rtype)
                    sink.extend(r.to_text() for r in ans)
                    canonical = str(ans.canonical_name).rstrip(".")
                    if rtype == "A" and canonical != host:
                        cnames.append(canonical)  # CNAME chain seen while resolving A
                except Exception:
                    continue
        return cnames, ips

    async def _browser_fetch(self, base: str) -> tuple[Optional[Signals], str, str]:
        try:
            from .browser import fetch_with_browser
        except ImportError as e:  # playwright missing
            return None, "", f"playwright unavailable: {e}"
        try:
            return await fetch_with_browser(self, base)
        except Exception as e:  # noqa: BLE001 - browser failures must never crash detection
            return None, "", f"{type(e).__name__}: {e}"[:200]


def _copy(res: DetectionResult, **changes: Any) -> DetectionResult:
    d = res.to_dict()
    d.update(changes)
    return DetectionResult(**d)


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _cookie_names(r: httpx.Response) -> list[str]:
    names: list[str] = []
    for resp in [*r.history, r]:
        for raw in resp.headers.get_list("set-cookie"):
            name = raw.split("=", 1)[0].strip()
            if name:
                names.append(name)
    return names


def _merged_headers(r: httpx.Response) -> dict[str, str]:
    """Headers from the final response plus any Shopify/platform headers seen on redirects."""
    merged: dict[str, str] = {}
    for resp in [*r.history, r]:
        for k, v in resp.headers.multi_items():
            k = k.lower()
            if k == "set-cookie":
                continue
            merged[k] = v  # later responses (final page) win
    return merged
