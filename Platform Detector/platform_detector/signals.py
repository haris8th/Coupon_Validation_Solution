"""Pure, side-effect-free scoring of homepage headers, cookies and HTML.

Every rule contributes a weight in (0, 1) to one platform. Per-platform
confidence is combined with a noisy-OR: ``1 - prod(1 - w)``, so several
weak hints add up but can never exceed 1.0.

Shopify rules carry a *tag*:
  * ``storefront`` - only present when Shopify renders the storefront itself
    (Online Store themes, Shopify edge headers, theme JS globals).
  * ``backend``    - Shopify is somewhere behind the site (CDN images,
    myshopify.com references, Storefront API calls). A headless front end
    shows these without the storefront ones.
  * ``headless``   - explicit headless markers (Hydrogen / Oxygen).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

SHOPIFY = "shopify"
SHOPIFY_HEADLESS = "shopify_headless"
WOOCOMMERCE = "woocommerce"
MAGENTO = "magento"
BIGCOMMERCE = "bigcommerce"
WIX = "wix"
SQUARESPACE = "squarespace"
SFCC = "salesforce_commerce_cloud"
CUSTOM = "custom"
UNKNOWN = "unknown"

KNOWN_PLATFORMS = (SHOPIFY, WOOCOMMERCE, MAGENTO, BIGCOMMERCE, WIX, SQUARESPACE, SFCC)


@dataclass(frozen=True)
class Rule:
    platform: str
    source: str  # "header" | "cookie" | "html"
    pattern: str
    weight: float
    label: str
    tag: str = ""

    def compiled(self) -> re.Pattern[str]:
        return _compile(self.pattern, self.source)


_CACHE: dict[tuple[str, str], re.Pattern[str]] = {}


def _compile(pattern: str, source: str) -> re.Pattern[str]:
    key = (pattern, source)
    if key not in _CACHE:
        flags = re.I | (re.M if source in ("header", "cookie") else 0)
        _CACHE[key] = re.compile(pattern, flags)
    return _CACHE[key]


R = Rule
RULES: tuple[Rule, ...] = (
    # ---------------- Shopify ----------------
    R(SHOPIFY, "header", r"^x-shopid:", 0.7, "header x-shopid", "storefront"),
    R(SHOPIFY, "header", r"^x-shopify-stage:", 0.6, "header x-shopify-stage", "storefront"),
    R(SHOPIFY, "header", r"^powered-by:.*shopify", 0.7, "header powered-by: Shopify", "storefront"),
    R(SHOPIFY, "header", r"^x-sorting-hat-(shopid|podid):", 0.6, "header x-sorting-hat-*", "storefront"),
    R(SHOPIFY, "header", r"^x-storefront-renderer-", 0.6, "header x-storefront-renderer-*", "storefront"),
    R(SHOPIFY, "header", r"^x-shardid:", 0.4, "header x-shardid", "storefront"),
    R(SHOPIFY, "header", r"^link:.*cdn\.shopify\.com", 0.4, "link header to cdn.shopify.com", "storefront"),
    R(SHOPIFY, "header", r"^powered-by:.*(hydrogen|oxygen)", 0.8, "header powered-by: Hydrogen/Oxygen", "headless"),
    R(SHOPIFY, "header", r"^oxygen-", 0.7, "Oxygen hosting header", "headless"),
    R(SHOPIFY, "cookie", r"^_shopify_(y|s|sa_p|sa_t|essential|analytics|marketing)$", 0.6, "cookie _shopify_*", "storefront"),
    R(SHOPIFY, "cookie", r"^(secure_customer_sig|cart_currency|_tracking_consent|_cmp_a)$", 0.4, "Shopify storefront cookie", "storefront"),
    R(SHOPIFY, "html", r"window\.Shopify\b|Shopify\.shop\s*=", 0.6, "window.Shopify in HTML", "storefront"),
    R(SHOPIFY, "html", r"Shopify\.theme\b|Shopify\.routes\b", 0.5, "Shopify.theme / Shopify.routes JS", "storefront"),
    R(SHOPIFY, "html", r"shopify-section", 0.5, "shopify-section markup", "storefront"),
    R(SHOPIFY, "html", r"/cdn/shop/(files|t|products|collections)/", 0.5, "/cdn/shop/ asset paths", "storefront"),
    R(SHOPIFY, "html", r"shopify-checkout-api-token", 0.6, "shopify-checkout-api-token meta", "storefront"),
    R(SHOPIFY, "html", r"monorail-edge\.shopifysvc\.com", 0.3, "Shopify monorail analytics", "storefront"),
    R(SHOPIFY, "html", r"cdn\.shopify\.com", 0.4, "cdn.shopify.com reference", "backend"),
    R(SHOPIFY, "html", r"[a-z0-9][a-z0-9-]*\.myshopify\.com", 0.4, "*.myshopify.com reference", "backend"),
    R(SHOPIFY, "html", r"/api/20\d\d-\d\d/graphql\.json", 0.5, "Shopify Storefront API call", "backend"),
    R(SHOPIFY, "html", r"storefront_?access_?token|SHOPIFY_STOREFRONT", 0.4, "Storefront API token reference", "backend"),
    R(SHOPIFY, "html", r"checkout\.shopify\.com|shopify\.com/checkouts", 0.4, "Shopify checkout link", "backend"),
    R(SHOPIFY, "html", r"@shopify/hydrogen|shopify-hydrogen|hydrogen-react", 0.7, "Shopify Hydrogen bundle", "headless"),
    # ---------------- WooCommerce ----------------
    R(WOOCOMMERCE, "html", r"wp-content/plugins/woocommerce", 0.7, "wp-content/plugins/woocommerce assets"),
    R(WOOCOMMERCE, "html", r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']WooCommerce", 0.8, "generator meta WooCommerce"),
    R(WOOCOMMERCE, "html", r"<body[^>]*class=[\"'][^\"']*\bwoocommerce", 0.5, "body class woocommerce*"),
    R(WOOCOMMERCE, "html", r"wc_add_to_cart_params|woocommerce_params|wc_cart_fragments_params|wc-blocks", 0.5, "WooCommerce JS params"),
    R(WOOCOMMERCE, "html", r"/wp-json/wc/", 0.4, "/wp-json/wc/ reference"),
    R(WOOCOMMERCE, "cookie", r"^(woocommerce_items_in_cart|woocommerce_cart_hash|wp_woocommerce_session_.*)$", 0.6, "cookie woocommerce_*"),
    # ---------------- Magento / Adobe Commerce ----------------
    R(MAGENTO, "html", r"text/x-magento-init", 0.8, "text/x-magento-init script"),
    R(MAGENTO, "html", r"Magento_(Ui|Theme|Customer|Checkout|Catalog)", 0.6, "Magento_* modules"),
    R(MAGENTO, "html", r"/static/(version\d+/)?frontend/[A-Za-z0-9_]+/", 0.5, "Magento static/frontend path"),
    R(MAGENTO, "html", r"mage/cookies|Mage\.Cookies|skin/frontend/", 0.5, "Magento JS/skin"),
    R(MAGENTO, "header", r"^x-magento-", 0.8, "header x-magento-*"),
    R(MAGENTO, "cookie", r"^(mage-cache-storage|mage-cache-sessid|mage-messages|private_content_version)$", 0.5, "cookie mage-*"),
    # ---------------- BigCommerce ----------------
    R(BIGCOMMERCE, "html", r"cdn\d*\.bigcommerce\.com", 0.7, "cdn*.bigcommerce.com assets"),
    R(BIGCOMMERCE, "html", r"stencil-utils|data-stencil|BCData\b", 0.5, "BigCommerce Stencil"),
    R(BIGCOMMERCE, "header", r"^x-bc-", 0.5, "header x-bc-*"),
    R(BIGCOMMERCE, "cookie", r"^(SHOP_SESSION_TOKEN|fornax_anonymousId|SF-CSRF-TOKEN|athena_short_visit_number)$", 0.5, "BigCommerce cookie"),
    # ---------------- Wix ----------------
    R(WIX, "header", r"^x-wix-", 0.8, "header x-wix-*"),
    R(WIX, "header", r"^server:\s*pepyaka", 0.8, "server: Pepyaka (Wix)"),
    R(WIX, "html", r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']Wix\.com", 0.8, "generator meta Wix.com"),
    R(WIX, "html", r"static\.wixstatic\.com|static\.parastorage\.com", 0.6, "Wix static assets"),
    # ---------------- Squarespace ----------------
    R(SQUARESPACE, "html", r"This is Squarespace\.", 0.8, "'This is Squarespace' comment"),
    R(SQUARESPACE, "html", r"Static\.SQUARESPACE_CONTEXT", 0.7, "SQUARESPACE_CONTEXT JS"),
    R(SQUARESPACE, "html", r"static1\.squarespace\.com|assets\.squarespace\.com", 0.6, "Squarespace static assets"),
    R(SQUARESPACE, "header", r"^server:\s*squarespace", 0.8, "server: Squarespace"),
    # ---------------- Salesforce Commerce Cloud (Demandware) ----------------
    R(SFCC, "html", r"demandware\.static|/on/demandware\.store/", 0.8, "Demandware static/store paths"),
    R(SFCC, "html", r"dwanonymous_|dwac_|\bdemandware\b", 0.4, "Demandware reference"),
    R(SFCC, "html", r"pwa-kit|commercecloud\.salesforce\.com|mobify", 0.4, "SFCC PWA Kit reference"),
    R(SFCC, "header", r"^x-dw-", 0.6, "header x-dw-*"),
    R(SFCC, "cookie", r"^(dwsid|dwanonymous_.*|dwac_.*|dw_dnt|__cq_dnt|dwpersonalization_.*)$", 0.6, "cookie dwsid/dwanonymous_*"),
)

WORDPRESS_RE = re.compile(r"wp-content/|wp-includes/|<meta[^>]+generator[^>]+WordPress", re.I)
WP_API_LINK_RE = re.compile(r"^link:.*api\.w\.org", re.I | re.M)

BLOCK_MARKERS = re.compile(
    r"cf-chl-|challenge-platform|<title>\s*(Just a moment|Attention Required)|"
    r"px-captcha|_Incapsula_Resource|captcha-delivery\.com|datadome|"
    r"Access Denied</title>|Request unsuccessful\. Incapsula|"
    r"<title>\s*(Access to this page has been denied|Pardon Our Interruption)",
    re.I,
)
BLOCK_STATUSES = {401, 403, 429, 503}


@dataclass(frozen=True)
class Hit:
    platform: str
    weight: float
    label: str
    tag: str = ""
    detail: str = ""

    def evidence(self) -> str:
        extra = f" ({self.detail})" if self.detail else ""
        return f"{self.platform}: {self.label}{extra} [+{self.weight:.2f}]"


@dataclass
class Signals:
    """Normalised inputs extracted from one homepage response."""

    headers: Mapping[str, str] = field(default_factory=dict)
    cookies: Iterable[str] = field(default_factory=list)
    html: str = ""
    status: int = 0

    def header_blob(self) -> str:
        return "\n".join(f"{k.lower()}: {v}" for k, v in self.headers.items())

    def cookie_blob(self) -> str:
        return "\n".join(sorted(set(self.cookies)))


def match_rules(sig: Signals, rules: Iterable[Rule] = RULES) -> list[Hit]:
    blobs = {"header": sig.header_blob(), "cookie": sig.cookie_blob(), "html": sig.html}
    hits: list[Hit] = []
    for rule in rules:
        m = rule.compiled().search(blobs[rule.source])
        if m:
            detail = ""
            if rule.source == "html" and "myshopify" in rule.pattern:
                detail = m.group(0)
            hits.append(Hit(rule.platform, rule.weight, rule.label, rule.tag, detail))
    return hits


def noisy_or(weights: Iterable[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - max(0.0, min(w, 0.99))
    return round(1.0 - p, 3)


def is_wordpress(sig: Signals) -> bool:
    return bool(WORDPRESS_RE.search(sig.html) or WP_API_LINK_RE.search(sig.header_blob()))


def is_blocked(sig: Signals) -> bool:
    """True when the response looks like a bot wall / challenge page."""
    if BLOCK_MARKERS.search(sig.html[:20000]):
        return True
    return sig.status in BLOCK_STATUSES and len(sig.html) < 50000


@dataclass
class Verdict:
    platform: str
    confidence: float
    scores: dict[str, float]
    evidence: list[str]


def classify(hits: list[Hit]) -> Verdict:
    """Turn hits (homepage + endpoint + DNS) into a single platform verdict."""
    by_platform: dict[str, list[Hit]] = {}
    for h in hits:
        by_platform.setdefault(h.platform, []).append(h)

    scores = {p: noisy_or(h.weight for h in hs) for p, hs in by_platform.items()}

    shop_hits = by_platform.get(SHOPIFY, [])
    if shop_hits:
        storefront = noisy_or(h.weight for h in shop_hits if h.tag == "storefront")
        backend = noisy_or(h.weight for h in shop_hits if h.tag in ("backend", "headless"))
        explicit_headless = any(h.tag == "headless" for h in shop_hits)
        if explicit_headless or (storefront < 0.5 and backend >= 0.5):
            scores[SHOPIFY_HEADLESS] = backend
            del scores[SHOPIFY]

    evidence = [h.evidence() for h in sorted(hits, key=lambda h: -h.weight)]
    if not scores:
        return Verdict(CUSTOM, 0.0, {}, evidence)
    best = max(scores, key=lambda p: scores[p])
    return Verdict(best, scores[best], scores, evidence)
