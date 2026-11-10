#!/usr/bin/env python3
"""Validate Shopify discount codes -- one command, payload-first with capture fallback.

For each store:
  1. If a saved payload exists (checkouts/<domain>/payload.json) and it still
     answers, reuse it -- no browser.
  2. If there's no payload, or the saved one is dead (expired/403/challenge),
     run the checkout capture to get a fresh payload, then validate.

For each code it swaps variables.reduction.code, POSTs to the Proposal endpoint,
saves the JSON response, and flags:
    invalid  - response contains a REDUCTION_INVALID / NOT_FOUND marker
    valid    - it doesn't
    error    - request failed or non-JSON even after a capture retry

    pip install -U playwright requests
    playwright install chromium
    python validate_codes.py codes.csv --checkouts checkouts --out validation

Sheet needs a Homepage (or website/url/domain) column and a Code (or coupon/
voucher) column; Brand and Region optional. CSV or TSV.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

PROPOSAL_PATH = "/checkouts/internal/graphql/persisted?operationName=Proposal"
REQUEST_TIMEOUT_S = 30
RETRIES = 2
PAUSE_BETWEEN_S = 0.4

# Code is VALID when the response carries this -- the discount created a trigger.
VALID_RE = re.compile(r"DiscountCodeTrigger", re.IGNORECASE)
# Explicit "code doesn't exist / can't apply" markers (back-up signal).
INVALID_RE = re.compile(
    r"REDUCTION_[A-Z_]*(?:INVALID|NOT_FOUND|NOT_APPLICABLE|DISABLED|EXPIRED)"
    r"|INVALID_DISCOUNT_CODE|DISCOUNT_CODE_NOT_FOUND",
    re.IGNORECASE,
)
# Response says the SESSION (not the code) is the problem -> re-capture the payload.
SESSION_FAIL_RE = re.compile(
    r"throttle|/queue|captcha|verify you are human|are you a robot|access denied"
    r"|INVALID_SESSION|SESSION_TOKEN|UNAUTHENT|unauthoriz|forbidden",
    re.IGNORECASE,
)
_SESSION_FAIL_STATUS = {401, 403, 419, 429}


def base_host(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def site_url(value: str) -> str:
    return value if "://" in value else f"https://{value}"


def safe_name(code: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", code.strip())
    return cleaned.strip("_.") or "blank"


def is_valid(text: str) -> bool:
    return bool(VALID_RE.search(text))


def invalid_marker(text: str) -> str:
    match = INVALID_RE.search(text)
    return match.group(0) if match else ""


# --- sheet reading (flexible headers) ---------------------------------------

_CODE_HEADERS = ("code", "coupon", "coupon code", "discount code", "promo code", "voucher", "codes")
_HOMEPAGE_HEADERS = ("homepage", "website", "url", "store", "site", "domain", "home page")
_BRAND_HEADERS = ("brand", "brand name", "merchant", "store name")
_REGION_HEADERS = ("region", "country", "geo", "locale")


def _pick(row: dict, names: tuple[str, ...]) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def read_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    delimiter = "\t" if text.count("\t") >= text.count(",") else ","
    rows = []
    for raw in csv.DictReader(text.splitlines(), delimiter=delimiter):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        homepage, code = _pick(row, _HOMEPAGE_HEADERS), _pick(row, _CODE_HEADERS)
        if homepage and code:
            rows.append({
                "brand": _pick(row, _BRAND_HEADERS), "homepage": homepage,
                "region": _pick(row, _REGION_HEADERS), "code": code,
            })
    return rows


# --- finding / capturing a store's payload ----------------------------------

MAP_FILE = "_homepage_map.json"  # homepage base-host -> checkout URL, for cross-subdomain stores


def load_checkout_map(checkouts_dir: Path) -> dict[str, str]:
    """homepage base-host -> checkout URL, from results.csv and the validator's own map."""
    mapping: dict[str, str] = {}
    results = checkouts_dir / "results.csv"
    if results.exists():
        with results.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                site, checkout = row.get("site", ""), row.get("checkout_url", "")
                if site and checkout:
                    mapping[base_host(urlparse(site_url(site)).netloc)] = checkout
    map_path = checkouts_dir / MAP_FILE
    if map_path.exists():
        try:
            mapping.update(json.loads(map_path.read_text(encoding="utf-8")))  # fresh captures win
        except Exception:
            pass
    return mapping


def save_mapping(checkouts_dir: Path, target: str, checkout_url: str) -> None:
    """Remember where a store's checkout lives, so later runs skip re-capturing it."""
    map_path = checkouts_dir / MAP_FILE
    data: dict[str, str] = {}
    if map_path.exists():
        try:
            data = json.loads(map_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[target] = checkout_url
    try:
        map_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def find_folder(checkouts_dir: Path, homepage: str, checkout_map: dict[str, str]) -> tuple[Path, str] | None:
    target = base_host(urlparse(site_url(homepage)).netloc)
    checkout_url = checkout_map.get(target, "")
    if checkout_url:
        folder = checkouts_dir / urlparse(checkout_url).netloc.replace(":", "_")
        if (folder / "payload.json").exists():
            return folder, checkout_url
    if checkouts_dir.exists():
        for folder in sorted(checkouts_dir.iterdir()):
            if not (folder / "payload.json").exists():
                continue
            host = base_host(folder.name.replace("_", ":").split(":")[0])
            if host == target or host.endswith(f".{target}") or target.endswith(f".{host}"):
                return folder, f"https://{folder.name.replace('_', ':')}"
    return None


async def _capture_one(site: str, out_dir: Path, headless: bool):
    """Capture one store's checkout by reusing shopify_checkout.process_site."""
    from playwright.async_api import async_playwright
    import shopify_checkout as capture

    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await capture.launch_browser(playwright, headless=headless)
        try:
            tabs = await capture.open_context(browser)
            page = await tabs.open()
            return await asyncio.wait_for(capture.process_site(page, site, out_dir), capture.SITE_TIMEOUT_S)
        finally:
            await browser.close()


def capture_payload(homepage: str, checkouts_dir: Path, headless: bool) -> tuple[tuple[Path, str] | None, str]:
    """Run the checkout capture for one store. Returns ((folder, checkout_url), '') or (None, reason)."""
    try:
        result = asyncio.run(_capture_one(site_url(homepage), checkouts_dir, headless))
    except Exception as error:
        detail = (str(error).strip().splitlines() or [type(error).__name__])[0][:200]
        return None, f"capture crashed: {detail}"
    if result.status != "ok" or not result.checkout_url:
        return None, f"capture: {result.status} {result.detail}".strip()
    folder = checkouts_dir / urlparse(result.checkout_url).netloc.replace(":", "_")
    if not (folder / "payload.json").exists():
        return None, "capture ok but no payload.json written"
    return (folder, result.checkout_url), ""


# --- one store's requests session -------------------------------------------

class Store:
    def __init__(self, folder: Path, checkout_url: str) -> None:
        parsed = urlparse(checkout_url)
        scheme = parsed.scheme or "https"
        self.netloc = parsed.netloc or folder.name.replace("_", ":")
        self.url = f"{scheme}://{self.netloc}{PROPOSAL_PATH}"
        self.payload = json.loads((folder / "payload.json").read_text(encoding="utf-8"))
        self.http = requests.Session()
        self.http.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": f"{scheme}://{self.netloc}",
            "Referer": f"{scheme}://{self.netloc}/",
        })
        state_path = folder / "storage_state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for cookie in state.get("cookies", []):
                try:
                    self.http.cookies.set(
                        cookie["name"], cookie["value"],
                        domain=cookie.get("domain", "").lstrip("."), path=cookie.get("path", "/"),
                    )
                except Exception:
                    pass

    def payload_for(self, code: str) -> dict:
        payload = copy.deepcopy(self.payload)
        payload.setdefault("variables", {})["reduction"] = {"code": code}
        return payload

    def post(self, code: str) -> tuple[int, object, str, str]:
        """Return (status_code, body_or_None, text, error)."""
        last_error = ""
        for attempt in range(RETRIES + 1):
            try:
                response = self.http.post(self.url, json=self.payload_for(code), timeout=REQUEST_TIMEOUT_S)
            except requests.RequestException as error:
                last_error = str(error)
                time.sleep(1 + attempt)
                continue
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status_code, body, response.text, ""
        return 0, None, "", last_error


def is_session_failure(status: int, body, text: str, error: str) -> bool:
    """True when the SESSION looks dead (so we should re-capture), not a code verdict."""
    if error:
        return True
    if status in _SESSION_FAIL_STATUS:
        return True
    if body is None:  # non-JSON -> usually a challenge/expired page
        return True
    blob = json.dumps(body)
    if VALID_RE.search(blob) or INVALID_RE.search(blob):
        return False  # a real code verdict; the session works fine
    return bool(SESSION_FAIL_RE.search(blob))


def classify(status: int, body, error: str) -> tuple[str, str]:
    """Final verdict once the session is known good. Returns (status_label, reason).

    Valid  = response contains DiscountCodeTrigger (discount applied).
    Invalid = a clean response without it (code didn't apply).
    """
    if error:
        return "error", error
    if body is None:
        return "error", f"non-json http {status}"
    blob = json.dumps(body)
    if is_valid(blob):
        return "valid", "DiscountCodeTrigger"
    marker = invalid_marker(blob)
    if marker:
        return "invalid", marker
    if status >= 400:
        return "error", f"http {status}"
    return "invalid", "no DiscountCodeTrigger"


# --- main -------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sheet", type=Path, help="CSV/TSV with a Homepage and a Code column")
    parser.add_argument("--checkouts", type=Path, default=Path("checkouts"),
                        help="folder for payloads (default: checkouts)")
    parser.add_argument("--out", type=Path, default=Path("validation"), help="output folder")
    parser.add_argument("--no-capture", action="store_true",
                        help="only use saved payloads; never open a browser")
    parser.add_argument("--show-browser", action="store_true",
                        help="capture with a visible browser (default headless)")
    args = parser.parse_args()

    rows = read_rows(args.sheet)
    if not rows:
        sys.exit("No usable rows (need a Homepage/website column and a Code column).")

    allow_capture = not args.no_capture
    headless = not args.show_browser
    checkout_map = load_checkout_map(args.checkouts)
    responses_dir = args.out / "responses"
    responses_dir.mkdir(parents=True, exist_ok=True)

    store_cache: dict[str, tuple[Store | None, str]] = {}
    captured: set[str] = set()   # stores we've already (re)captured this run
    seen: set[tuple[str, str]] = set()
    out_rows: list[dict] = []

    def get_store(homepage: str, target: str, force: bool = False) -> tuple[Store | None, str]:
        """Load the saved payload, or capture it. force=True re-captures a dead one."""
        if not force and target in store_cache:
            return store_cache[target]
        found = None if force else find_folder(args.checkouts, homepage, checkout_map)
        reason = ""
        captured_now = False
        if found is None and allow_capture and target not in captured:
            captured.add(target)
            found, reason = capture_payload(homepage, args.checkouts, headless)
            captured_now = found is not None
        elif found is None:
            reason = "no saved payload" + ("" if allow_capture else " (--no-capture)")
        store = None
        if found is not None:
            try:
                store = Store(*found)
            except (OSError, ValueError, KeyError) as exc:
                reason = f"bad payload: {exc}"
        if store is not None and captured_now:  # remember where this store's checkout lives
            checkout_map[target] = found[1]
            save_mapping(args.checkouts, target, found[1])
        store_cache[target] = (store, reason)
        return store, reason

    for index, row in enumerate(rows, 1):
        homepage, code = row["homepage"], row["code"]
        target = base_host(urlparse(site_url(homepage)).netloc)
        store, reason = get_store(homepage, target)

        status, body, text, error, domain = "no_payload", "", "", reason, target
        if store is not None:
            domain = base_host(store.netloc)
            sc, body_json, text, error = store.post(code)
            # Saved payload dead? Capture once, then retry this code.
            if allow_capture and target not in captured and is_session_failure(sc, body_json, text, error):
                store, cap_reason = get_store(homepage, target, force=True)
                if store is not None:
                    domain = base_host(store.netloc)
                    sc, body_json, text, error = store.post(code)
                else:
                    error = error or cap_reason
            status, why = classify(sc, body_json, error)
            reason = why
            body = body_json if body_json is not None else (text[:4000] or error)

            store_dir = responses_dir / domain.replace(":", "_")
            store_dir.mkdir(parents=True, exist_ok=True)
            name, suffix = safe_name(code), 1
            while (domain, name) in seen:
                suffix += 1
                name = f"{safe_name(code)}_{suffix}"
            seen.add((domain, name))
            path = store_dir / f"{name}.json"
            path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
            response_file = str(path)
            time.sleep(PAUSE_BETWEEN_S)
        else:
            response_file = ""

        valid = {"valid": "yes", "invalid": "no"}.get(status, "")
        out_rows.append({
            "Brand": row["brand"], "Homepage": homepage, "Region": row["region"], "Code": code,
            "valid": valid, "status": status, "reason": reason,
            "domain": domain, "response_file": response_file,
        })
        print(f"[{index}/{len(rows)}] {status:10} {valid or '?':3} {code:22} {domain}  {reason}")

    out_csv = args.out / "validated.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Brand", "Homepage", "Region", "Code", "valid", "status", "reason", "domain", "response_file"],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    valid = sum(r["valid"] == "yes" for r in out_rows)
    invalid = sum(r["valid"] == "no" for r in out_rows)
    other = len(out_rows) - valid - invalid
    print(f"\n{valid} valid, {invalid} invalid, {other} error/no-payload of {len(out_rows)}.")
    print(f"Responses: {responses_dir}/<domain>/<code>.json")
    print(f"Summary: {out_csv}")


if __name__ == "__main__":
    main()
