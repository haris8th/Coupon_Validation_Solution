"""Pure interpreters for platform endpoint responses and DNS answers."""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Iterable

from .signals import SHOPIFY, WOOCOMMERCE, Hit

SHOPIFY_ENDPOINTS = ("/meta.json", "/products.json?limit=1", "/cart.js")
WOO_ENDPOINT = "/wp-json/wc/store/v1/products?per_page=1"

SHOPIFY_V4 = ipaddress.ip_network("23.227.38.0/24")
SHOPIFY_V6 = ipaddress.ip_network("2620:127:f00f::/48")
SHOPIFY_CNAMES = ("shops.myshopify.com", ".myshopify.com")


def _json(body: str) -> Any:
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


def score_shopify_endpoint(path: str, status: int, body: str) -> list[Hit]:
    if status != 200:
        return []
    data = _json(body)
    if not isinstance(data, dict):
        return []
    if path.startswith("/meta.json") and ("myshopify_domain" in data or "money_format" in data):
        return [Hit(SHOPIFY, 0.95, "/meta.json is a Shopify shop object", "storefront",
                    str(data.get("myshopify_domain") or ""))]
    if path.startswith("/products.json") and isinstance(data.get("products"), list):
        prods = data["products"]
        shopish = not prods or any(k in prods[0] for k in ("handle", "variants", "vendor"))
        if shopish:
            return [Hit(SHOPIFY, 0.9, "/products.json returns Shopify products", "storefront")]
    if path.startswith("/cart.js") and "token" in data and "item_count" in data:
        return [Hit(SHOPIFY, 0.85, "/cart.js returns a Shopify cart", "storefront")]
    return []


def score_woo_endpoint(status: int, body: str) -> list[Hit]:
    data = _json(body)
    if status == 200 and isinstance(data, list):
        if not data or any(k in data[0] for k in ("permalink", "prices", "add_to_cart")):
            return [Hit(WOOCOMMERCE, 0.9, "Store API /wp-json/wc/store/v1/products responds")]
    if isinstance(data, dict) and str(data.get("code", "")).startswith(("woocommerce", "wc_")):
        return [Hit(WOOCOMMERCE, 0.8, "WooCommerce REST error code", detail=str(data["code"]))]
    return []


def score_dns(cnames: Iterable[str], ips: Iterable[str]) -> list[Hit]:
    hits: list[Hit] = []
    for c in cnames:
        c = c.rstrip(".").lower()
        if c == "shops.myshopify.com" or c.endswith(".myshopify.com"):
            hits.append(Hit(SHOPIFY, 0.9, "CNAME to Shopify", "storefront", c))
            break
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in SHOPIFY_V4 or addr in SHOPIFY_V6:
            hits.append(Hit(SHOPIFY, 0.85, "IP in Shopify range", "storefront", ip))
            break
    return hits
