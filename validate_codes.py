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


class Playwright:
    """One Playwright driver for the whole run, started the first time a capture needs it."""

    def __init__(self) -> None:
        self._playwright = None
        self._lock = asyncio.Lock()

    async def get(self):
        async with self._lock:
            if self._playwright is None:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
            return self._playwright

    async def stop(self) -> None:
        if self._playwright is not None:
            await self._playwright.stop()


class CaptureBrowser:
    """A worker's own browser. Each worker gets one, so captures run side by side.

    The browser opens on the worker's first capture and is reused for the rest. Every
    capture gets a fresh context (its own window and cookies), so stores never share
    a cart or session.
    """

    def __init__(self, playwright: Playwright, headless: bool) -> None:
        self.playwright = playwright
        self.headless = headless
        self.browser = None

    async def capture(self, site: str, out_dir: Path):
        import shopify_checkout as capture

        if self.browser is None or not self.browser.is_connected():
            self.browser = await capture.launch_browser(await self.playwright.get(), headless=self.headless)
        out_dir.mkdir(parents=True, exist_ok=True)
        tabs = await capture.open_context(self.browser)
        try:
            page = await tabs.open()
            return await asyncio.wait_for(capture.process_site(page, site, out_dir), capture.SITE_TIMEOUT_S)
        finally:
            try:
                await tabs.context.close()
            except Exception:
                pass

    async def close(self) -> None:
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass


async def capture_payload(
    browser: CaptureBrowser, homepage: str, checkouts_dir: Path
) -> tuple[tuple[Path, str] | None, str]:
    """Run the checkout capture for one store. Returns ((folder, checkout_url), '') or (None, reason)."""
    try:
        result = await browser.capture(site_url(homepage), checkouts_dir)
    except asyncio.TimeoutError:
        return None, "capture: timed_out"
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

DEFAULT_WORKERS = 3
FIELDNAMES = ["Brand", "Homepage", "Region", "Code", "valid", "status", "reason", "domain", "response_file"]


class Run:
    """Shared state for one run.

    Workers are asyncio tasks on one thread, so this state needs no locks. Only the
    HTTP posts run in threads, and each one touches just its own store's session.
    """

    def __init__(self, args, total: int) -> None:
        self.args = args
        self.total = total
        self.allow_capture = not args.no_capture
        self.checkout_map = load_checkout_map(args.checkouts)
        self.responses_dir = args.out / "responses"
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.seen: set[tuple[str, str]] = set()
        self.done: set[int] = set()
        self.out_rows: list[tuple[int, dict]] = []
        self.playwright = Playwright()

    async def get_store(
        self, browser: CaptureBrowser, homepage: str, target: str, force: bool = False
    ) -> tuple[Store | None, str]:
        """Load the saved payload, or capture it. force=True re-captures a dead one."""
        found = None if force else find_folder(self.args.checkouts, homepage, self.checkout_map)
        reason = ""
        captured_now = False
        if found is None and self.allow_capture:
            found, reason = await capture_payload(browser, homepage, self.args.checkouts)
            captured_now = found is not None
        elif found is None:
            reason = "no saved payload" + ("" if self.allow_capture else " (--no-capture)")
        store = None
        if found is not None:
            try:
                store = Store(*found)
            except (OSError, ValueError, KeyError) as exc:
                reason = f"bad payload: {exc}"
        if store is not None and captured_now:  # remember where this store's checkout lives
            self.checkout_map[target] = found[1]
            save_mapping(self.args.checkouts, target, found[1])
        return store, reason

    def save_response(self, domain: str, code: str, body) -> str:
        store_dir = self.responses_dir / domain.replace(":", "_")
        store_dir.mkdir(parents=True, exist_ok=True)
        name, suffix = safe_name(code), 1
        while (domain, name) in self.seen:
            suffix += 1
            name = f"{safe_name(code)}_{suffix}"
        self.seen.add((domain, name))
        path = store_dir / f"{name}.json"
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def report(self, worker: int, index: int, row: dict, status: str, reason: str,
               domain: str, response_file: str) -> None:
        valid = {"valid": "yes", "invalid": "no"}.get(status, "")
        self.done.add(index)
        self.out_rows.append((index, {
            "Brand": row["brand"], "Homepage": row["homepage"], "Region": row["region"],
            "Code": row["code"], "valid": valid, "status": status, "reason": reason,
            "domain": domain, "response_file": response_file,
        }))
        print(f"[{len(self.out_rows)}/{self.total}] w{worker} {status:10} {valid or '?':3} "
              f"{row['code']:22} {domain}  {reason}", flush=True)

    async def do_store(self, worker: int, browser: CaptureBrowser, target: str,
                       items: list[tuple[int, dict]]) -> None:
        """Every code for one store, in order, on one session.

        Different stores run in parallel. Codes for the same store stay one at a time,
        so a single store never sees several requests at once.
        """
        homepage = items[0][1]["homepage"]
        store, reason = await self.get_store(browser, homepage, target)
        recaptured = False

        for index, row in items:
            code = row["code"]
            if store is None:
                self.report(worker, index, row, "no_payload", reason, target, "")
                continue

            domain = base_host(store.netloc)
            sc, body_json, text, error = await asyncio.to_thread(store.post, code)
            # Saved payload dead? Capture once per store, then retry this code.
            if self.allow_capture and not recaptured and is_session_failure(sc, body_json, text, error):
                recaptured = True
                fresh, cap_reason = await self.get_store(browser, homepage, target, force=True)
                if fresh is not None:
                    store = fresh
                    domain = base_host(store.netloc)
                    sc, body_json, text, error = await asyncio.to_thread(store.post, code)
                else:
                    error = error or cap_reason

            status, why = classify(sc, body_json, error)
            body = body_json if body_json is not None else (text[:4000] or error)
            self.report(worker, index, row, status, why, domain, self.save_response(domain, code, body))
            await asyncio.sleep(PAUSE_BETWEEN_S)

    async def worker(self, number: int, queue: asyncio.Queue) -> None:
        browser = CaptureBrowser(self.playwright, headless=not self.args.show_browser)
        try:
            while True:
                try:
                    target, items = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await self.do_store(number, browser, target, items)
                except Exception as error:  # One broken store must not stop the worker.
                    detail = (str(error).strip().splitlines() or [type(error).__name__])[0][:200]
                    for index, row in items:
                        if index not in self.done:
                            self.report(number, index, row, "error", f"worker crashed: {detail}", target, "")
        finally:
            await browser.close()


async def run(args, rows: list[dict]) -> list[dict]:
    # Group codes by store, so each store is handled by one worker from start to finish.
    groups: dict[str, list[tuple[int, dict]]] = {}
    for index, row in enumerate(rows, 1):
        target = base_host(urlparse(site_url(row["homepage"])).netloc)
        groups.setdefault(target, []).append((index, row))

    state = Run(args, len(rows))
    queue: asyncio.Queue = asyncio.Queue()
    for target, items in groups.items():
        queue.put_nowait((target, items))

    workers = max(1, min(args.workers, len(groups)))
    print(f"{len(rows)} codes across {len(groups)} stores, {workers} workers.", flush=True)
    try:
        await asyncio.gather(*(state.worker(n, queue) for n in range(1, workers + 1)))
    finally:
        await state.playwright.stop()
    return [row for _, row in sorted(state.out_rows, key=lambda item: item[0])]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sheet", type=Path, help="CSV/TSV with a Homepage and a Code column")
    parser.add_argument("--checkouts", type=Path, default=Path("checkouts"),
                        help="folder for payloads (default: checkouts)")
    parser.add_argument("--out", type=Path, default=Path("validation"), help="output folder")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"stores to process at once, each with its own browser (default {DEFAULT_WORKERS})")
    parser.add_argument("--no-capture", action="store_true",
                        help="only use saved payloads; never open a browser")
    parser.add_argument("--show-browser", action="store_true",
                        help="capture with a visible browser (default headless)")
    parser.add_argument("--log", type=Path, default=None,
                        help="log file (default: <out>/validation_log.txt); each run is appended")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.log or args.out / "validation_log.txt"
    start_log(log_path)
    try:
        _main(args)
    except BaseException as error:
        if not isinstance(error, SystemExit):
            import traceback
            traceback.print_exc()
        raise
    finally:
        print(f"Log: {log_path}")
        stop_log()


class _Tee:
    """Writes everything to the console and, with a timestamp per line, to the log file."""

    def __init__(self, console, log_file) -> None:
        self.console = console
        self.log_file = log_file
        self.at_line_start = True

    def write(self, text: str) -> int:
        self.console.write(text)
        stamped = []
        for piece in text.splitlines(keepends=True):
            if self.at_line_start and piece.strip():
                stamped.append(time.strftime("%Y-%m-%d %H:%M:%S  "))
            stamped.append(piece)
            self.at_line_start = piece.endswith("\n")
        self.log_file.write("".join(stamped))
        self.log_file.flush()  # Keep the log if a long run is interrupted.
        return len(text)

    def flush(self) -> None:
        self.console.flush()
        self.log_file.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


_LOG_STATE: dict = {}


def start_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log_file = path.open("a", encoding="utf-8")
    log_file.write(f"\n{'=' * 70}\n{time.strftime('%Y-%m-%d %H:%M:%S')}  RUN: "
                   f"{' '.join(sys.argv)}\n{'=' * 70}\n")
    _LOG_STATE.update(file=log_file, stdout=sys.stdout, stderr=sys.stderr)
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)


def stop_log() -> None:
    if _LOG_STATE:
        sys.stdout, sys.stderr = _LOG_STATE["stdout"], _LOG_STATE["stderr"]
        _LOG_STATE["file"].close()
        _LOG_STATE.clear()


def _main(args) -> None:
    rows = read_rows(args.sheet)
    if not rows:
        sys.exit("No usable rows (need a Homepage/website column and a Code column).")

    out_rows = asyncio.run(run(args, rows))

    out_csv = args.out / "validated.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(out_rows)

    valid = sum(r["valid"] == "yes" for r in out_rows)
    invalid = sum(r["valid"] == "no" for r in out_rows)
    other = len(out_rows) - valid - invalid
    print(f"\n{valid} valid, {invalid} invalid, {other} error/no-payload of {len(out_rows)}.")
    print(f"Responses: {args.out / 'responses'}/<domain>/<code>.json")
    print(f"Summary: {out_csv}")


if __name__ == "__main__":
    main()
