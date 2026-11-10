# # """Open Shopify stores, add a product to the cart and save each checkout page.
from __future__ import annotations

# #     pip install -U playwright
# #     playwright install chromium
# #     python shopify_checkout.py sites.txt

# # All stores share one browser window, with one tab per worker. Any other tab that
# # opens is closed at once. Pages are only loaded as far as the next step needs, so
# # the tool moves on as soon as the product links or buttons appear. Each store gets a
# # folder in `checkouts/`, and `checkouts/results.csv` has one row per store. This
# # stops at the checkout page: it never enters details or pays. It also doesn't try
# # to get past logins, captchas or queues, and reports them instead.
# # """
# # from __future__ import annotations

# # import argparse
# # import asyncio
# # import csv
# # import json
# # import re
# # import time
# # from dataclasses import asdict, dataclass
# # from pathlib import Path
# # from urllib.parse import urljoin, urlparse

# # from playwright.async_api import (
# #     Browser,
# #     BrowserContext,
# #     Error,
# #     Frame,
# #     Page,
# #     Playwright,
# #     Request,
# #     Route,
# #     async_playwright,
# # )

# # from shopify_proposal import CheckoutParseError, build_proposal_payload

# # DEFAULT_WORKERS = 1
# # NAV_TIMEOUT_MS = 40_000  # Longer first-paint budget for slow / anti-bot stores.
# # CLICK_TIMEOUT_MS = 2_000  # Short, so an overlay covering a button costs little time.
# # SITE_TIMEOUT_S = 160  # A slow store can't hold up a tab for longer than this.
# # CHECKOUT_TIMEOUT_S = 30  # Slow stores take a while to hand over the checkout session.
# # MAX_PRODUCTS_TO_TRY = 3
# # # Shopify loads its Buy Now button late, so wait longer if its container is on the page.
# # BUY_NOW_WAIT_WITH_CONTAINER_S = 5
# # BUY_NOW_WAIT_S = 2
# # AFTER_CLICK_WAIT_S = 15  # Slow stores redirect to a separate checkout host (e.g. store.govee.com).
# # CART_UPDATE_WAIT_S = 6
# # # Hard refresh the page this many times when the domain lookup fails (DNS errors are
# # # usually temporary). Short, growing gaps give the lookup time to recover without
# # # holding the tab for long. After these, the other www/non-www form is tried.
# # DNS_RETRY_DELAYS_S = (1, 2, 3, 5, 8)
# # # Reading a page is tried again this many times if a redirect replaces it meanwhile.
# # REDIRECT_RETRIES = 5
# # REDIRECT_WAIT_MS = 5_000
# # # A home page with no product links may be about to redirect or still be adding them.
# # HOME_LINKS_WAIT_S = 3
# # RETRY_FILE_NAME = "retry_sites.txt"

# # _BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
# # _BLOCKED_HOST_RE = re.compile(
# #     r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|connect\.facebook\.net"
# #     r"|hotjar\.com|clarity\.ms|analytics\.tiktok\.com|bat\.bing\.com|static\.klaviyo\.com"
# #     r"|attn\.tv|attentivemobile\.com|cdn\.segment\.com|snapchat\.com|pinimg\.com",
# #     re.IGNORECASE,
# # )
# # # Ad and redirect pages often live on these raw hosting domains. Stores also use
# # # them for scripts and files, so only opening one as a page or iframe is blocked.
# # # Add more domains here if another one shows up.
# # _JUNK_PAGE_HOST_RE = re.compile(
# #     r"(^|\.)(cloudfront\.net|amazonaws\.com|azureedge\.net|akamaihd\.net|b-cdn\.net)$",
# #     re.IGNORECASE,
# # )
# # # Playwright turns off Chromium's popup blocker by default. Keeping it on stops
# # # popups that scripts open without a click.
# # _KEEP_POPUP_BLOCKER = ["--disable-popup-blocking"]
# # # --- Stealth: make the automated browser look like an ordinary one -----------
# # # A real, recent Chrome user agent and launch flag that hides the automation bit.
# # _USER_AGENT = (
# #     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
# #     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# # )
# # _STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
# # # Patches the handful of signals bot-detectors check first (navigator.webdriver, etc).
# # _STEALTH_SCRIPT = """
# # (() => {
# #     const hide = (obj, name, value) => {
# #         try { Object.defineProperty(obj, name, {get: () => value}); } catch (e) {}
# #     };
# #     hide(navigator, 'webdriver', undefined);
# #     hide(navigator, 'languages', ['en-US', 'en']);
# #     hide(navigator, 'plugins', [1, 2, 3, 4, 5]);
# #     try { window.chrome = window.chrome || {runtime: {}}; } catch (e) {}
# #     try {
# #         const query = navigator.permissions && navigator.permissions.query;
# #         if (query) {
# #             navigator.permissions.query = parameters =>
# #                 parameters && parameters.name === 'notifications'
# #                     ? Promise.resolve({state: Notification.permission})
# #                     : query(parameters);
# #         }
# #     } catch (e) {}
# # })();
# # """
# # # Stops every new tab before it starts, including the ones the popup blocker allows
# # # because they follow a click. Checkout that redirects on the SAME tab is unaffected.
# # # WorkerTabs closes any tab that still opens.
# # _NO_POPUPS_SCRIPT = """
# # (() => {
# #     const opensTab = (element, target) => {
# #         const base = element.ownerDocument.querySelector('base[target]');
# #         const name = target || base?.getAttribute('target') || '';
# #         const keyword = name.toLowerCase();
# #         if (['', '_self', '_parent', '_top'].includes(keyword)) return false;
# #         // A name that matches an iframe loads there. Any other name opens a new tab.
# #         return keyword === '_blank'
# #             || !element.ownerDocument.querySelector(`iframe[name="${CSS.escape(name)}"]`);
# #     };
# #     const linkOpensTab = link => opensTab(link, link.getAttribute('target'));
# #     const enclosingLink = node => node.closest?.('a[href], area[href]');

# #     window.open = () => null;  // What a popup blocker returns.

# #     // composedPath() also sees links inside shadow DOM, which event.target hides.
# #     const stopNewTabClick = event => {
# #         const link = event.composedPath().find(node => node.matches?.('a[href], area[href]'));
# #         if (!link) return;
# #         const opensSeparately = event.type === 'auxclick'
# #             || event.ctrlKey || event.metaKey || event.shiftKey;
# #         if (opensSeparately || linkOpensTab(link)) event.preventDefault();
# #     };
# #     window.addEventListener('click', stopNewTabClick, true);
# #     window.addEventListener('auxclick', stopNewTabClick, true);
# #     window.addEventListener('submit', event => {
# #         const form = event.target;
# #         const target = event.submitter?.getAttribute('formtarget') || form.getAttribute('target');
# #         if (opensTab(form, target)) event.preventDefault();
# #     }, true);

# #     // A link that isn't on the page sends its click event nowhere near window, and
# #     // form.submit() sends no event at all, so these have to be stopped at the call.
# #     const click = HTMLElement.prototype.click;
# #     HTMLElement.prototype.click = function () {
# #         const link = enclosingLink(this);
# #         if (!link || !linkOpensTab(link)) click.call(this);
# #     };
# #     const dispatchEvent = EventTarget.prototype.dispatchEvent;
# #     EventTarget.prototype.dispatchEvent = function (event) {
# #         const link = event?.type === 'click' ? enclosingLink(this) : null;
# #         return link && linkOpensTab(link) ? false : dispatchEvent.call(this, event);
# #     };
# #     const submit = HTMLFormElement.prototype.submit;
# #     HTMLFormElement.prototype.submit = function () {
# #         if (!opensTab(this, this.getAttribute('target'))) submit.call(this);
# #     };
# # })();
# # """
# # # Newsletter, discount and region popups inside the page, which can cover a button.
# # _CLOSE_OVERLAYS_SCRIPT = """() => {
# #     const selector = [
# #         '[role="dialog"] [aria-label*="close" i]',
# #         '[aria-modal="true"] [aria-label*="close" i]',
# #         '[class*="popup" i] [class*="close" i]',
# #         '[id*="popup" i] [class*="close" i]',
# #         '[class*="newsletter" i] [class*="close" i]',
# #         '.klaviyo-close-form',
# #     ].join(', ');
# #     for (const element of document.querySelectorAll(selector)) {
# #         if (element.getClientRects().length) element.click();
# #     }
# # }"""
# # # Ready once enough different matches exist, or the whole page has been read.
# # _PAGE_READY_SCRIPT = """([selector, count]) => {
# #     const found = [...document.querySelectorAll(selector)].map(e => e.pathname ?? e);
# #     return new Set(found).size >= count || document.readyState !== 'loading';
# # }"""
# # _PRODUCT_PATH_RE = re.compile(r"/products?/[^/]+/?$", re.IGNORECASE)
# # _PRODUCT_LINK_SELECTOR = 'a[href*="/products/" i], a[href*="/product/" i]'
# # _SKIPPED_PRODUCT_RE = re.compile(r"gift|e-?card|sample|warranty|protection", re.IGNORECASE)
# # _LOGIN_URL_RE = re.compile(r"/account/login|/customer_authentication|/authentication|/account\b")
# # _CHALLENGE_RE = re.compile(r"/challenge|captcha", re.IGNORECASE)
# # _BLOCKED_TEXT_RE = re.compile(
# #     r"verify you are human|are you a robot|access denied|unusual traffic", re.IGNORECASE
# # )
# # _ADD_BUTTON_TEXT_RE = re.compile(r"add to (cart|bag|basket|order)", re.IGNORECASE)
# # _BUY_NOW_TEXT_RE = re.compile(
# #     r"^\s*buy\s*$|\b(buy (it )?now|buy today|order now|purchase( now)?|check ?out now)\b",
# #     re.IGNORECASE,
# # )
# # # These open a separate payment service, not the store's own checkout.
# # _PAYMENT_SERVICE_RE = re.compile(
# #     r"pay\b|paypal|shop\s?pay|gpay|venmo|amazon|klarna|afterpay|installment", re.IGNORECASE
# # )
# # _CHECKOUT_TEXT_RE = re.compile(r"^\s*((proceed|continue|go) to |secure )?check ?out\b", re.IGNORECASE)
# # _BUY_NOW_CONTAINER = '.shopify-payment-button, [data-shopify="payment-button"], shopify-accelerated-checkout'
# # _BUTTON_SELECTORS = (
# #     'form[action*="/cart/add"] button[name="add"]',
# #     'form[action*="/cart/add"] [type="submit"]',
# #     'button[name="add"]',
# #     'button[data-testid*="add-to-cart" i]',
# #     'button[id*="add-to-cart" i]',
# #     'button[class*="add-to-cart" i]',
# # )
# # _PRODUCT_READY_SELECTOR = ", ".join((*_BUTTON_SELECTORS, _BUY_NOW_CONTAINER))


# # @dataclass
# # class SiteResult:
# #     site: str
# #     status: str = "error"
# #     product_url: str = ""
# #     checkout_url: str = ""
# #     added_by: str = ""
# #     seconds: float = 0.0
# #     detail: str = ""


# # class StopSite(Exception):
# #     """This store can't go further. The message is its status."""

# #     def __init__(self, status: str, detail: str = "") -> None:
# #         super().__init__(status)
# #         self.status = status
# #         self.detail = detail


# # def _base_host(host: str) -> str:
# #     return host.removeprefix("www.")


# # def _other_www_form(url: str) -> str:
# #     parsed = urlparse(url)
# #     host = parsed.netloc
# #     other = _base_host(host) if host.startswith("www.") else f"www.{host}"
# #     return parsed._replace(netloc=other).geturl()


# # def _site_url(site: str) -> str:
# #     return site if "://" in site else f"https://{site}"


# # async def _open_fast(page: Page, url: str, ready_selector: str, count: int = 1) -> None:
# #     """Open a URL and return once what's needed is there, not when the page finishes."""
# #     await page.goto(url, wait_until="commit")
# #     await _wait_until_ready(page, ready_selector, count)


# # async def _wait_until_ready(page: Page, ready_selector: str, count: int = 1) -> None:
# #     deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
# #     while time.monotonic() < deadline:
# #         try:
# #             if await page.evaluate(_PAGE_READY_SCRIPT, [ready_selector, count]):
# #                 return
# #         except Error:
# #             pass  # The page was navigating. Check again.
# #         await page.wait_for_timeout(100)


# # async def _hard_refresh(page: Page, url: str) -> None:
# #     """Reload a failed page the way Ctrl+Shift+R does, skipping the browser's cache.

# #     Returns when the new page commits, and raises Error if it fails, like page.goto.
# #     """
# #     # Chrome only has the store's address to reload once its error page has
# #     # appeared. Before that, opening the URL is the same request: every tab has
# #     # routes, and those also make Chrome skip its cache.
# #     if not page.url.startswith("chrome-error:"):
# #         await page.goto(url, wait_until="commit")
# #         return

# #     outcome = asyncio.get_running_loop().create_future()

# #     def on_request_failed(request: Request) -> None:
# #         if request.is_navigation_request() and request.frame == page.main_frame and not outcome.done():
# #             outcome.set_exception(Error(request.failure or "the page failed to load"))

# #     def on_frame_navigated(frame: Frame) -> None:
# #         # A failed load also navigates, to Chrome's error page.
# #         if frame == page.main_frame and not frame.url.startswith("chrome-error:") and not outcome.done():
# #             outcome.set_result(None)

# #     page.on("requestfailed", on_request_failed)
# #     page.on("framenavigated", on_frame_navigated)
# #     # A session stops working when the error page replaces the tab's contents,
# #     # so each refresh needs its own.
# #     session = await page.context.new_cdp_session(page)
# #     try:
# #         try:
# #             await session.send("Page.reload", {"ignoreCache": True})
# #         except Error as error:
# #             if "Not attached" not in str(error):
# #                 raise
# #             await page.goto(url, wait_until="commit")  # The error page was still appearing.
# #             return
# #         try:
# #             await asyncio.wait_for(outcome, NAV_TIMEOUT_MS / 1000)
# #         except asyncio.TimeoutError:
# #             raise Error(f"hard refresh timed out after {NAV_TIMEOUT_MS} ms") from None
# #     finally:
# #         page.remove_listener("requestfailed", on_request_failed)
# #         page.remove_listener("framenavigated", on_frame_navigated)
# #         if outcome.done() and not outcome.cancelled():
# #             outcome.exception()  # Mark a failure as seen if the goto above replaced it.
# #         try:
# #             await session.detach()
# #         except Error:
# #             pass  # The session already ended with the page it was attached to.


# # async def open_home_page(page: Page, url: str) -> None:
# #     """Open the store, hard refreshing when the domain lookup fails.

# #     A failed lookup is retried up to ``len(DNS_RETRY_DELAYS_S)`` times (5 by
# #     default) before the other www/non-www form is tried, because these lookups
# #     often fail only temporarily, so the store isn't assumed to be down.
# #     """
# #     steps = [
# #         (url, False, 0),
# #         *[(url, True, delay) for delay in DNS_RETRY_DELAYS_S],
# #         (_other_www_form(url), False, 0),
# #     ]
# #     for attempt, hard_refresh, delay in steps:
# #         await asyncio.sleep(delay)
# #         try:
# #             if hard_refresh:
# #                 await _hard_refresh(page, attempt)
# #             else:
# #                 await page.goto(attempt, wait_until="commit")
# #             await _wait_until_ready(page, _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
# #             return
# #         except Error as error:
# #             # Retry both temporary DNS failures and slow/anti-bot first-paint timeouts.
# #             if "ERR_NAME_NOT_RESOLVED" not in str(error) and "Timeout" not in str(error):
# #                 raise
# #     raise StopSite("dns_error", f"could not look up {urlparse(url).netloc}")


# # async def _read_page(page: Page, script: str):
# #     """Run a script that reads the page, waiting out any redirect that replaces it.

# #     Pages are used before they finish loading, so a store's region or language
# #     redirect can land in the middle of a read.
# #     """
# #     for _ in range(REDIRECT_RETRIES):
# #         try:
# #             return await page.evaluate(script)
# #         except Error as error:
# #             if "Execution context was destroyed" not in str(error):
# #                 raise
# #         try:
# #             await page.wait_for_load_state("domcontentloaded", timeout=REDIRECT_WAIT_MS)
# #         except Error:
# #             pass  # Still loading or navigating. The next read will show which.
# #     return await page.evaluate(script)


# # async def _store_root(page: Page) -> str:
# #     """The store's base path, which includes the language on some stores (/en-us/)."""
# #     return await _read_page(page, "() => window.Shopify?.routes?.root || '/'")


# # async def _fetch_json(page: Page, path: str, body: dict | None = None) -> dict | None:
# #     """Request a same-site URL from inside the page, so store cookies are used."""
# #     try:
# #         return await page.evaluate(
# #             """async ([path, body]) => {
# #                 try {
# #                     const response = await fetch(path, body ? {
# #                         method: 'POST',
# #                         headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
# #                         body: JSON.stringify(body),
# #                     } : {headers: {'Accept': 'application/json'}});
# #                     return response.ok ? await response.json() : null;
# #                 } catch (error) {
# #                     return null;
# #                 }
# #             }""",
# #             [path, body],
# #         )
# #     except Error:  # The page navigated away during the request.
# #         return None


# # async def _fetch_text(page: Page, path: str) -> str | None:
# #     """Fetch a same-site URL as text (for XML sitemaps), using the store's cookies."""
# #     try:
# #         return await page.evaluate(
# #             """async (path) => {
# #                 try {
# #                     const response = await fetch(path, {headers: {'Accept': 'text/xml, */*'}});
# #                     return response.ok ? await response.text() : null;
# #                 } catch (error) { return null; }
# #             }""",
# #             path,
# #         )
# #     except Error:
# #         return None


# # async def _check_page_state(page: Page) -> None:
# #     """Raise if the page shows something this tool shouldn't try to get past."""
# #     title = await _read_page(page, "() => document.title")  # First: it may wait out a redirect.
# #     url = page.url
# #     path = urlparse(url).path
# #     if path.rstrip("/").endswith("/password"):
# #         raise StopSite("password_protected", url)
# #     if "/throttle" in path or "/queue" in path:
# #         raise StopSite("in_queue", url)
# #     if _LOGIN_URL_RE.search(path):
# #         raise StopSite("login_required", url)
# #     if _CHALLENGE_RE.search(path):
# #         raise StopSite("blocked", url)
# #     if _BLOCKED_TEXT_RE.search(title):
# #         raise StopSite("blocked", title)


# # async def _is_shopify(page: Page) -> bool:
# #     return await _read_page(
# #         page,
# #         """() => Boolean(window.Shopify)
# #             || Boolean(document.querySelector('script[src*="cdn.shopify.com"], link[href*="cdn.shopify.com"]'))""",
# #     )


# # async def _links_on_page(page: Page) -> list[str]:
# #     hrefs = await _read_page(page, "() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
# #     host = _base_host(urlparse(page.url).hostname)  # After the read, which may wait out a redirect.
# #     links: dict[str, str] = {}
# #     for href in hrefs:
# #         parsed = urlparse(href)
# #         if parsed.scheme not in ("http", "https") or parsed.hostname is None:
# #             continue
# #         if _base_host(parsed.hostname) != host:
# #             continue
# #         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
# #             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
# #     return list(links.values())


# # async def _wait_for_home_links(page: Page) -> list[str]:
# #     """Read the home page's product links, allowing time for a redirect or late links."""
# #     deadline = time.monotonic() + HOME_LINKS_WAIT_S
# #     while True:
# #         links = await _links_on_page(page)
# #         if links or time.monotonic() >= deadline:
# #             return links
# #         await page.wait_for_timeout(250)
# #         await _check_page_state(page)  # A redirect may have landed on a password page or queue.


# # async def _links_from_sitemap(page: Page, root: str) -> list[str]:
# #     """Pull product URLs from the store's product sitemap (some themes expose nothing else)."""
# #     xml = await _fetch_text(page, urljoin(page.url, f"{root}sitemap_products_1.xml")) or ""
# #     links: dict[str, str] = {}
# #     for loc in re.findall(r"<loc>\s*([^<\s]+?/products/[^<\s]+?)\s*</loc>", xml, re.IGNORECASE):
# #         parsed = urlparse(loc)
# #         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
# #             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
# #     return list(links.values())


# # async def find_product_links(page: Page) -> list[str]:
# #     """Home page, then Shopify's product feed, then the sitemap, then collection pages."""
# #     links = await _wait_for_home_links(page)
# #     if links:
# #         return links
# #     root = await _store_root(page)
# #     feed = await _fetch_json(page, f"{root}products.json?limit=50") or {}
# #     links = [
# #         urljoin(page.url, f"{root}products/{product['handle']}")
# #         for product in feed.get("products", [])
# #         if not _SKIPPED_PRODUCT_RE.search(product.get("handle", ""))
# #     ]
# #     if links:
# #         return links
# #     links = await _links_from_sitemap(page, root)
# #     if links:
# #         return links
# #     for path in (f"{root}collections/all", f"{root}collections"):
# #         try:
# #             await _open_fast(page, urljoin(page.url, path), _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
# #             await _check_page_state(page)
# #             links = await _links_on_page(page)
# #             if links:
# #                 return links
# #         except Error:
# #             continue  # Try the next catalog path.
# #     return links


# # async def _cart_count(page: Page, root: str) -> int:
# #     return (await _fetch_json(page, f"{root}cart.js") or {}).get("item_count", 0)


# # async def _add_with_cart_api(page: Page, root: str) -> bool:
# #     """Add the first purchasable variant. This works whatever the store's theme is."""
# #     path = urlparse(page.url).path.rstrip("/")
# #     product = await _fetch_json(page, f"{path}.js")
# #     if not product or product.get("gift_card") or product.get("requires_selling_plan"):
# #         return False
# #     for variant in product.get("variants", []):
# #         if not variant.get("available") or variant.get("requires_selling_plan"):
# #             continue
# #         items = {"items": [{"id": variant["id"], "quantity": 1}]}
# #         if await _fetch_json(page, f"{root}cart/add.js", items) and await _cart_count(page, root) > 0:
# #             return True
# #     return False


# # async def _usable(locator) -> bool:
# #     try:
# #         return await locator.is_visible() and await locator.is_enabled()
# #     except Error:
# #         return False


# # async def _buy_now_candidates(page: Page) -> list:
# #     candidates = [page.locator(".shopify-payment-button__button--unbranded").first]
# #     for scope in (page.locator('form[action*="/cart/add"]'), page):
# #         buttons = scope.get_by_role("button", name=_BUY_NOW_TEXT_RE)
# #         candidates += [buttons.nth(i) for i in range(min(await buttons.count(), 10))]
# #     return candidates


# # async def _find_buy_now(page: Page):
# #     """Find a Buy Now button, skipping separate payment services.

# #     Those buttons often show only a logo, so their name is in `aria-label`.
# #     """
# #     for button in await _buy_now_candidates(page):
# #         if not await _usable(button):
# #             continue
# #         label = f"{await button.inner_text()} {await button.get_attribute('aria-label') or ''}"
# #         if not _PAYMENT_SERVICE_RE.search(label):
# #             return button
# #     return None


# # async def _find_add_button(page: Page):
# #     candidates = [page.locator(selector).first for selector in _BUTTON_SELECTORS]
# #     candidates.append(page.get_by_role("button", name=_ADD_BUTTON_TEXT_RE).first)
# #     for button in candidates:
# #         if await _usable(button):
# #             return button
# #     return None


# # async def _wait_for_button(page: Page, *finders: tuple) -> tuple[str, object] | None:
# #     """Return the first button that shows, as (method, button). Earlier finders win."""
# #     started = time.monotonic()
# #     while True:
# #         try:
# #             for method, find in finders:
# #                 button = await find(page)
# #                 if button is not None:
# #                     return method, button
# #             has_container = await page.locator(_BUY_NOW_CONTAINER).count() > 0
# #         except Error:
# #             has_container = False
# #         limit = BUY_NOW_WAIT_WITH_CONTAINER_S if has_container else BUY_NOW_WAIT_S
# #         if time.monotonic() - started >= limit:
# #             return None
# #         await page.wait_for_timeout(250)


# # async def _close_overlays(page: Page) -> None:
# #     try:
# #         await page.evaluate(_CLOSE_OVERLAYS_SCRIPT)
# #     except Error:
# #         pass  # The page was navigating, so there's nothing to close.


# # async def _click(page: Page, button) -> bool:
# #     """Close any popup in the page, then click. Try again if a popup appears first."""
# #     for _ in range(2):
# #         await _close_overlays(page)
# #         try:
# #             await button.click(timeout=CLICK_TIMEOUT_MS)
# #             return True
# #         except Error:
# #             try:
# #                 await page.keyboard.press("Escape")
# #             except Error:
# #                 pass
# #     return False


# # async def _find_checkout_button(page: Page):
# #     for role in ("button", "link"):
# #         options = page.get_by_role(role, name=_CHECKOUT_TEXT_RE)
# #         for index in range(min(await options.count(), 10)):
# #             if await _usable(options.nth(index)):
# #                 return options.nth(index)
# #     return None


# # def _on_checkout(page: Page) -> bool:
# #     """True once the tab has redirected to a checkout (same tab, any host)."""
# #     return "/checkouts/" in page.url


# # async def _wait_for_checkout_url(page: Page, seconds: float) -> bool:
# #     deadline = time.monotonic() + seconds
# #     while time.monotonic() < deadline:
# #         if _on_checkout(page):
# #             return True
# #         try:
# #             await _check_page_state(page)
# #         except Error:
# #             pass  # The page was navigating. Check again.
# #         await page.wait_for_timeout(200)
# #     return False


# # async def _use_buy_now(page: Page, root: str, button) -> bool:
# #     """Click Buy Now once. Return True if checkout opened or the cart has an item.

# #     A Buy click that navigates to the checkout makes button.click() raise (the page is
# #     gone), so we DON'T treat a failed click as failure -- we check the URL regardless.
# #     """
# #     await _click(page, button)
# #     # Some stores open a cart first, so look for its checkout button early.
# #     deadline = time.monotonic() + AFTER_CLICK_WAIT_S
# #     if await _wait_for_checkout_url(page, 3):
# #         return True
# #     try:
# #         checkout = await _find_checkout_button(page)
# #         if checkout is not None:
# #             await checkout.click(timeout=5_000)
# #     except Error:
# #         pass
# #     if await _wait_for_checkout_url(page, max(deadline - time.monotonic(), 1)):
# #         return True
# #     return await _cart_count(page, root) > 0


# # async def _add_with_button(page: Page, root: str, button) -> bool:
# #     """Click the store's add-to-cart button once.

# #     Some stores (e.g. Govee) redirect straight to a checkout on another host instead
# #     of filling a cart, so reaching a checkout counts as success too.
# #     """
# #     await _click(page, button)  # may raise internally if the click navigates; that's fine
# #     deadline = time.monotonic() + CART_UPDATE_WAIT_S  # short: Buy / permalink are tried next
# #     while time.monotonic() < deadline:
# #         if _on_checkout(page) or await _cart_count(page, root) > 0:
# #             return True
# #         await page.wait_for_timeout(250)
# #     return False


# # # Picks the first available option in each variant selector, so Add to Cart is enabled
# # # on products that require a size/colour choice first.
# # _SELECT_VARIANTS_SCRIPT = """() => {
# #     const form = document.querySelector('form[action*="/cart/add"]') || document;
# #     const unavailable = /unavailable|sold out|out of stock/i;
# #     for (const select of form.querySelectorAll('select')) {
# #         const option = [...select.options].find(
# #             o => o.value && !o.disabled && !unavailable.test(o.textContent)
# #         );
# #         if (option && select.value !== option.value) {
# #             select.value = option.value;
# #             select.dispatchEvent(new Event('change', {bubbles: true}));
# #         }
# #     }
# #     const groups = {};
# #     for (const input of form.querySelectorAll('input[type=radio]')) {
# #         if (!input.disabled) (groups[input.name] = groups[input.name] || []).push(input);
# #     }
# #     for (const name in groups) {
# #         if (!groups[name].some(i => i.checked)) {
# #             const pick = groups[name][0];
# #             pick.checked = true;
# #             try { pick.click(); } catch (e) {}
# #             pick.dispatchEvent(new Event('change', {bubbles: true}));
# #         }
# #     }
# # }"""


# # async def _select_variants(page: Page) -> None:
# #     try:
# #         await page.evaluate(_SELECT_VARIANTS_SCRIPT)
# #         await page.wait_for_timeout(300)  # Let the theme re-enable the button.
# #     except Error:
# #         pass  # Best-effort; the add/cart-API paths still run.


# # async def _use_product_buttons(page: Page, root: str) -> str | None:
# #     """Try Add to Cart first, then Buy. Return the method that worked."""
# #     found = await _wait_for_button(page, ("button", _find_add_button), ("buy_now", _find_buy_now))
# #     if found is None:
# #         return None
# #     method, button = found
# #     if method == "button":
# #         if await _add_with_button(page, root, button):
# #             return method
# #         found = await _wait_for_button(page, ("buy_now", _find_buy_now))
# #         if found is None:
# #             return None
# #         method, button = found
# #     return method if await _use_buy_now(page, root, button) else None


# # async def _checkout_via_permalink(page: Page, root: str) -> str | None:
# #     """Add the first available variant via the cart permalink, which goes to checkout.

# #     `/<root>cart/<variant_id>:1` bypasses the variant-button UI entirely and, on stores
# #     like Govee, redirects straight to the checkout host -- which is all we need.
# #     """
# #     path = urlparse(page.url).path.rstrip("/")
# #     product = await _fetch_json(page, f"{path}.js")
# #     if not product or product.get("requires_selling_plan"):
# #         return None
# #     for variant in product.get("variants", []):
# #         if not variant.get("available") or variant.get("requires_selling_plan"):
# #             continue
# #         try:
# #             await page.goto(urljoin(page.url, f"{root}cart/{variant['id']}:1"), wait_until="commit")
# #         except Error:
# #             continue
# #         if await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S):
# #             return "permalink"
# #     return None


# # async def start_checkout(page: Page, links: list[str], result: SiteResult) -> str:
# #     """Add to Cart, then Buy, then the cart permalink, then the cart API. Return the base path."""
# #     for link in links[:MAX_PRODUCTS_TO_TRY]:
# #         try:
# #             await _open_fast(page, link, _PRODUCT_READY_SELECTOR)
# #         except Error:
# #             continue
# #         await _check_page_state(page)
# #         root = await _store_root(page)
# #         result.product_url = page.url
# #         await _select_variants(page)  # Enable Add to Cart on size/colour products.
# #         method = await _use_product_buttons(page, root)
# #         if method is not None:
# #             result.added_by = method
# #             return root
# #         # Variant picked by UI failed (e.g. Govee's custom buttons) -> add by permalink.
# #         method = await _checkout_via_permalink(page, root)
# #         if method is not None:
# #             result.added_by = method
# #             return root
# #         if await _add_with_cart_api(page, root):
# #             result.added_by = "cart_api"
# #             return root
# #     raise StopSite("could_not_add_to_cart", f"tried {min(len(links), MAX_PRODUCTS_TO_TRY)} products")


# # async def open_checkout(page: Page, root: str) -> bool:
# #     """Open checkout at most once. Return True if the page has its session data."""
# #     if "/checkouts/" not in page.url:
# #         await page.goto(urljoin(page.url, f"{root}checkout"), wait_until="domcontentloaded")
# #     deadline = time.monotonic() + CHECKOUT_TIMEOUT_S
# #     while time.monotonic() < deadline:
# #         try:
# #             await _check_page_state(page)
# #             if await page.locator('meta[name="serialized-sessionToken"]').count():
# #                 return True
# #         except Error:
# #             pass  # The page was navigating. Check again.
# #         await page.wait_for_timeout(250)
# #     if "/checkouts/" in page.url:
# #         return False
# #     raise StopSite("checkout_not_reached", page.url)


# # async def _reach_checkout_with_buy(page: Page, root: str, result: SiteResult) -> bool:
# #     """Click Buy or Checkout on the page /checkout led to, then on the product page.

# #     Some stores only show their checkout button after Buy is clicked on an item
# #     that's already in the cart. Return True once the page is a checkout.
# #     """
# #     for url in ("", result.product_url):
# #         try:
# #             if url:
# #                 await _open_fast(page, url, _PRODUCT_READY_SELECTOR)
# #                 await _check_page_state(page)
# #             found = await _wait_for_button(
# #                 page, ("buy_now", _find_buy_now), ("checkout", _find_checkout_button)
# #             )
# #             if found is None:
# #                 continue
# #             method, button = found
# #             await _use_buy_now(page, root, button)  # Also clicks any checkout button it reveals.
# #         except Error:
# #             continue  # The page failed or navigated away. Try the next one.
# #         if "/checkouts/" in page.url:
# #             result.added_by += f"+{method}"
# #             return True
# #     return False


# # async def _saved_html(page: Page) -> str:
# #     for _ in range(5):
# #         try:
# #             return await page.content()
# #         except Error:  # The page was navigating. Try again.
# #             await page.wait_for_timeout(1_000)
# #     return await page.content()


# # def _belongs_to_host(domain: str, host: str) -> bool:
# #     domain = domain.lstrip(".")
# #     return host == domain or host.endswith(f".{domain}")


# # async def _save_store_state(page: Page, path: Path) -> None:
# #     """Save only this store's data, because tabs for other stores share the browser.

# #     This has the format of context.storage_state(), which can't be used here: it opens
# #     a visible tab and visits every site this browser has seen, including ad hosts.
# #     """
# #     storage = await _read_page(
# #         page,
# #         """() => ({
# #             origin: location.origin,
# #             localStorage: Object.entries(localStorage).map(([name, value]) => ({name, value})),
# #         })""",
# #     )
# #     host = urlparse(storage["origin"]).hostname
# #     state = {
# #         "cookies": [c for c in await page.context.cookies() if _belongs_to_host(c["domain"], host)],
# #         "origins": [storage] if storage["localStorage"] else [],
# #     }
# #     path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# # async def _prepare_for_next_store(page: Page, url: str) -> None:
# #     """Start with an empty cart even if this store has been visited before."""
# #     host = _base_host(urlparse(url).hostname or "")
# #     await page.context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(host)}$"))
# #     # A blank page stops anything the last store was still loading, which could
# #     # otherwise interrupt the next store's first page.
# #     for _ in range(3):
# #         try:
# #             await page.goto("about:blank")
# #             return
# #         except Error:
# #             await page.wait_for_timeout(500)


# # async def process_site(page: Page, site: str, out_dir: Path) -> SiteResult:
# #     result = SiteResult(site=site)
# #     started = time.monotonic()
# #     url = _site_url(site)
# #     try:
# #         await _prepare_for_next_store(page, url)
# #         await open_home_page(page, url)
# #         await _check_page_state(page)
# #         if not await _is_shopify(page):
# #             raise StopSite("not_shopify", page.url)

# #         links = await find_product_links(page)
# #         if not links:
# #             raise StopSite("no_products_found")
# #         root = await start_checkout(page, links, result)

# #         try:
# #             has_session_data = await open_checkout(page, root)
# #         except StopSite as stop:
# #             if stop.status != "checkout_not_reached":
# #                 raise
# #             if not await _reach_checkout_with_buy(page, root, result):
# #                 raise
# #             has_session_data = await open_checkout(page, root)
# #         # Same-tab checkout redirect (e.g. us.govee.com -> store.govee.com) lands here,
# #         # so page.url is the real checkout host and the folder is named for it.
# #         result.checkout_url = page.url

# #         parsed = urlparse(page.url)
# #         store_dir = out_dir / parsed.netloc.replace(":", "_")
# #         store_dir.mkdir(parents=True, exist_ok=True)
# #         html = await _saved_html(page)
# #         (store_dir / "checkout.html").write_text(html, encoding="utf-8")
# #         # Holds this store's cookies, which a later Proposal request will need.
# #         await _save_store_state(page, store_dir / "storage_state.json")

# #         if not has_session_data:
# #             result.status = "checkout_without_session_data"
# #             return result
# #         try:
# #             payload = build_proposal_payload(html, None)
# #         except CheckoutParseError as error:
# #             result.status = "payload_failed"
# #             result.detail = str(error)
# #             return result
# #         (store_dir / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
# #         result.status = "ok"
# #     except StopSite as stop:
# #         result.status = stop.status
# #         result.detail = stop.detail
# #     except Error as error:
# #         result.status = "browser_error"
# #         result.detail = str(error).splitlines()[0][:200]
# #     finally:
# #         result.seconds = round(time.monotonic() - started, 1)
# #     return result


# # async def _block_slow_requests(route: Route) -> None:
# #     request = route.request
# #     try:
# #         if request.resource_type in _BLOCKED_RESOURCE_TYPES or _BLOCKED_HOST_RE.search(
# #             urlparse(request.url).hostname or ""
# #         ):
# #             await route.abort()
# #         else:
# #             await route.continue_()
# #     except Error:
# #         pass  # The page closed or moved on, so the request no longer matters.


# # class WorkerTabs:
# #     """Opens the worker tabs, and closes every other tab the browser opens."""

# #     def __init__(self, context: BrowserContext) -> None:
# #         self.context = context
# #         self._tabs: set[Page] = set()
# #         # The browser reports a new tab before new_page() returns it, so this makes
# #         # the closer wait until a worker's own tab has been recorded.
# #         self._opening = asyncio.Lock()
# #         context.on("page", lambda page: asyncio.ensure_future(self._close_if_extra(page)))

# #     async def open(self) -> Page:
# #         async with self._opening:
# #             page = await self.context.new_page()
# #             self._tabs.add(page)
# #         return page

# #     async def _close_if_extra(self, page: Page) -> None:
# #         async with self._opening:
# #             pass
# #         if page not in self._tabs:
# #             try:
# #                 await page.close(run_before_unload=False)
# #             except Error:
# #                 pass

# #     def _is_extra_tab(self, request: Request) -> bool:
# #         try:
# #             return request.frame.page not in self._tabs
# #         except Error:  # A page load with no frame yet is a new tab starting up.
# #             return True

# #     async def block_unwanted_pages(self, route: Route) -> None:
# #         request = route.request
# #         try:
# #             if not request.is_navigation_request():
# #                 await route.fallback()
# #             elif self._is_extra_tab(request):
# #                 # Answer with an empty page, so nothing reaches the real server. Don't
# #                 # abort here: Playwright only reports a new tab once its first page
# #                 # loads, so an aborted one would stay open and never reach the closer.
# #                 await route.fulfill(status=200, content_type="text/html", body="")
# #             elif _JUNK_PAGE_HOST_RE.search(urlparse(request.url).hostname or ""):
# #                 # "aborted" keeps the current page. Other errors replace it with an error page.
# #                 await route.abort("aborted")
# #             else:
# #                 await route.fallback()
# #         except Error:
# #             pass  # The page closed or moved on, so the request no longer matters.


# # async def launch_browser(playwright: Playwright, *, headless: bool = False) -> Browser:
# #     args = _STEALTH_ARGS
# #     try:  # Real installed Chrome is trusted more than bundled Chromium.
# #         return await playwright.chromium.launch(
# #             headless=headless, channel="chrome", args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
# #         )
# #     except Error:
# #         return await playwright.chromium.launch(
# #             headless=headless, args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
# #         )


# # async def open_context(browser: Browser, *, block_slow_requests: bool = True) -> WorkerTabs:
# #     """Open the one window that every store shares."""
# #     context = await browser.new_context(
# #         user_agent=_USER_AGENT,
# #         locale="en-US",
# #         timezone_id="America/New_York",
# #         viewport={"width": 1366, "height": 768},
# #         extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
# #     )
# #     context.set_default_timeout(NAV_TIMEOUT_MS)
# #     context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
# #     await context.add_init_script(_STEALTH_SCRIPT)
# #     await context.add_init_script(_NO_POPUPS_SCRIPT)
# #     if block_slow_requests:
# #         await context.route("**/*", _block_slow_requests)
# #     tabs = WorkerTabs(context)
# #     # The newest route runs first, then falls back to the one above.
# #     await context.route("**/*", tabs.block_unwanted_pages)
# #     return tabs


# # def read_sites(path: Path) -> list[str]:
# #     """Read the list, dropping stores that appear twice in different forms."""
# #     sites: dict[str, str] = {}
# #     for line in path.read_text(encoding="utf-8").splitlines():
# #         site = line.strip()
# #         if not site or site.startswith("#"):
# #             continue
# #         parsed = urlparse(_site_url(site))
# #         key = f"{_base_host(parsed.netloc.lower())}{parsed.path.rstrip('/')}"
# #         sites.setdefault(key, site)
# #     return list(sites.values())


# # def sites_to_retry(results: list[SiteResult]) -> list[str]:
# #     retryable = ("dns_error", "browser_error", "timed_out")
# #     return [r.site for r in results if r.status in retryable]


# # async def _worker(tabs: WorkerTabs, sites: asyncio.Queue, out_dir: Path, report) -> None:
# #     page = await tabs.open()
# #     while not sites.empty():
# #         site = sites.get_nowait()
# #         if page.is_closed():
# #             try:
# #                 page = await tabs.open()
# #             except Error:
# #                 report(SiteResult(site=site, status="browser_error", detail="the browser was closed"))
# #                 continue
# #         try:
# #             result = await asyncio.wait_for(process_site(page, site, out_dir), SITE_TIMEOUT_S)
# #         except asyncio.TimeoutError:
# #             result = SiteResult(site=site, status="timed_out", seconds=SITE_TIMEOUT_S)
# #         report(result)
# #     if not page.is_closed():
# #         await page.close(run_before_unload=False)


# # async def run(
# #     sites: list[str],
# #     out_dir: Path,
# #     *,
# #     workers: int = DEFAULT_WORKERS,
# #     block_slow_requests: bool = True,
# #     headless: bool = False,
# # ) -> list[SiteResult]:
# #     out_dir.mkdir(parents=True, exist_ok=True)
# #     results: list[SiteResult] = []
# #     with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as csv_file:
# #         writer = csv.DictWriter(csv_file, fieldnames=list(SiteResult.__dataclass_fields__))
# #         writer.writeheader()

# #         def report(result: SiteResult) -> None:
# #             results.append(result)
# #             writer.writerow(asdict(result))
# #             csv_file.flush()  # Keep finished rows if a long run is interrupted.
# #             print(f"[{len(results)}/{len(sites)}] {result.status:30} {result.seconds:6.1f}s  {result.site}  {result.detail}")

# #         queue: asyncio.Queue = asyncio.Queue()
# #         for site in sites:
# #             queue.put_nowait(site)
# #         async with async_playwright() as playwright:
# #             browser = await launch_browser(playwright, headless=headless)
# #             tabs = await open_context(browser, block_slow_requests=block_slow_requests)
# #             await asyncio.gather(
# #                 *(_worker(tabs, queue, out_dir, report) for _ in range(min(workers, len(sites)) or 1))
# #             )
# #             await browser.close()
# #     retry = sites_to_retry(results)
# #     if retry:
# #         (out_dir / RETRY_FILE_NAME).write_text("\n".join(retry) + "\n", encoding="utf-8")
# #     return results


# # def main() -> None:
# #     parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
# #     parser.add_argument("sites", type=Path, help="text file with one store per line")
# #     parser.add_argument("--out", type=Path, default=Path("checkouts"), help="output folder")
# #     parser.add_argument(
# #         "--workers", type=int, default=DEFAULT_WORKERS, help="how many stores to run at once"
# #     )
# #     parser.add_argument(
# #         "--load-everything",
# #         action="store_true",
# #         help="also load images, fonts and trackers, in case blocking them breaks a store",
# #     )
# #     args = parser.parse_args()
# #     started = time.monotonic()
# #     results = asyncio.run(
# #         run(
# #             read_sites(args.sites),
# #             args.out,
# #             workers=args.workers,
# #             block_slow_requests=not args.load_everything,
# #         )
# #     )
# #     done = sum(result.status == "ok" for result in results)
# #     minutes = (time.monotonic() - started) / 60
# #     print(f"\n{done} of {len(results)} stores reached checkout in {minutes:.1f} minutes.")
# #     print(f"See {args.out / 'results.csv'}")
# #     retry = sites_to_retry(results)
# #     if retry:
# #         print(f"{len(retry)} stores had connection errors or timeouts. See {args.out / RETRY_FILE_NAME}")


# # if __name__ == "__main__":
# #     main()
# """Open Shopify stores, add a product to the cart and save each checkout page.

#     pip install -U playwright
#     playwright install chromium
#     python shopify_checkout.py sites.txt

# All stores share one browser window, with one tab per worker. Any other tab that
# opens is closed at once. Pages are only loaded as far as the next step needs, so
# the tool moves on as soon as the product links or buttons appear. Each store gets a
# folder in `checkouts/`, and `checkouts/results.csv` has one row per store. This
# stops at the checkout page: it never enters details or pays. It also doesn't try
# to get past logins, captchas or queues, and reports them instead.
# """
# from __future__ import annotations

# import argparse
# import asyncio
# import csv
# import json
# import re
# import time
# from dataclasses import asdict, dataclass
# from pathlib import Path
# from urllib.parse import urljoin, urlparse

# from playwright.async_api import (
#     Browser,
#     BrowserContext,
#     Error,
#     Frame,
#     Page,
#     Playwright,
#     Request,
#     Route,
#     async_playwright,
# )

# from shopify_proposal import CheckoutParseError, build_proposal_payload

# DEFAULT_WORKERS = 1
# NAV_TIMEOUT_MS = 40_000  # Longer first-paint budget for slow / anti-bot stores.
# CLICK_TIMEOUT_MS = 2_000  # Short, so an overlay covering a button costs little time.
# SITE_TIMEOUT_S = 160  # A slow store can't hold up a tab for longer than this.
# CHECKOUT_TIMEOUT_S = 30  # Slow stores take a while to hand over the checkout session.
# MAX_PRODUCTS_TO_TRY = 3
# # Shopify loads its Buy Now button late, so wait longer if its container is on the page.
# BUY_NOW_WAIT_WITH_CONTAINER_S = 5
# BUY_NOW_WAIT_S = 2
# AFTER_CLICK_WAIT_S = 15  # Slow stores redirect to a separate checkout host (e.g. store.govee.com).
# CART_UPDATE_WAIT_S = 6
# # Hard refresh the page this many times when the domain lookup fails (DNS errors are
# # usually temporary). Short, growing gaps give the lookup time to recover without
# # holding the tab for long. After these, the other www/non-www form is tried.
# DNS_RETRY_DELAYS_S = (1, 2, 3, 5, 8)
# # Reading a page is tried again this many times if a redirect replaces it meanwhile.
# REDIRECT_RETRIES = 5
# REDIRECT_WAIT_MS = 5_000
# # A home page with no product links may be about to redirect or still be adding them.
# HOME_LINKS_WAIT_S = 3
# RETRY_FILE_NAME = "retry_sites.txt"

# _BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
# _BLOCKED_HOST_RE = re.compile(
#     r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|connect\.facebook\.net"
#     r"|hotjar\.com|clarity\.ms|analytics\.tiktok\.com|bat\.bing\.com|static\.klaviyo\.com"
#     r"|attn\.tv|attentivemobile\.com|cdn\.segment\.com|snapchat\.com|pinimg\.com",
#     re.IGNORECASE,
# )
# # Ad and redirect pages often live on these raw hosting domains. Stores also use
# # them for scripts and files, so only opening one as a page or iframe is blocked.
# # Add more domains here if another one shows up.
# _JUNK_PAGE_HOST_RE = re.compile(
#     r"(^|\.)(cloudfront\.net|amazonaws\.com|azureedge\.net|akamaihd\.net|b-cdn\.net)$",
#     re.IGNORECASE,
# )
# # Playwright turns off Chromium's popup blocker by default. Keeping it on stops
# # popups that scripts open without a click.
# _KEEP_POPUP_BLOCKER = ["--disable-popup-blocking"]
# # --- Stealth: make the automated browser look like an ordinary one -----------
# # A real, recent Chrome user agent and launch flag that hides the automation bit.
# _USER_AGENT = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# )
# _STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
# # Patches the handful of signals bot-detectors check first (navigator.webdriver, etc).
# _STEALTH_SCRIPT = """
# (() => {
#     const hide = (obj, name, value) => {
#         try { Object.defineProperty(obj, name, {get: () => value}); } catch (e) {}
#     };
#     hide(navigator, 'webdriver', undefined);
#     hide(navigator, 'languages', ['en-US', 'en']);
#     hide(navigator, 'plugins', [1, 2, 3, 4, 5]);
#     try { window.chrome = window.chrome || {runtime: {}}; } catch (e) {}
#     try {
#         const query = navigator.permissions && navigator.permissions.query;
#         if (query) {
#             navigator.permissions.query = parameters =>
#                 parameters && parameters.name === 'notifications'
#                     ? Promise.resolve({state: Notification.permission})
#                     : query(parameters);
#         }
#     } catch (e) {}
# })();
# """
# # Stops every new tab before it starts, including the ones the popup blocker allows
# # because they follow a click. Checkout that redirects on the SAME tab is unaffected.
# # WorkerTabs closes any tab that still opens.
# _NO_POPUPS_SCRIPT = """
# (() => {
#     const opensTab = (element, target) => {
#         const base = element.ownerDocument.querySelector('base[target]');
#         const name = target || base?.getAttribute('target') || '';
#         const keyword = name.toLowerCase();
#         if (['', '_self', '_parent', '_top'].includes(keyword)) return false;
#         // A name that matches an iframe loads there. Any other name opens a new tab.
#         return keyword === '_blank'
#             || !element.ownerDocument.querySelector(`iframe[name="${CSS.escape(name)}"]`);
#     };
#     const linkOpensTab = link => opensTab(link, link.getAttribute('target'));
#     const enclosingLink = node => node.closest?.('a[href], area[href]');

#     window.open = () => null;  // What a popup blocker returns.

#     // composedPath() also sees links inside shadow DOM, which event.target hides.
#     const stopNewTabClick = event => {
#         const link = event.composedPath().find(node => node.matches?.('a[href], area[href]'));
#         if (!link) return;
#         const opensSeparately = event.type === 'auxclick'
#             || event.ctrlKey || event.metaKey || event.shiftKey;
#         if (opensSeparately || linkOpensTab(link)) event.preventDefault();
#     };
#     window.addEventListener('click', stopNewTabClick, true);
#     window.addEventListener('auxclick', stopNewTabClick, true);
#     window.addEventListener('submit', event => {
#         const form = event.target;
#         const target = event.submitter?.getAttribute('formtarget') || form.getAttribute('target');
#         if (opensTab(form, target)) event.preventDefault();
#     }, true);

#     // A link that isn't on the page sends its click event nowhere near window, and
#     // form.submit() sends no event at all, so these have to be stopped at the call.
#     const click = HTMLElement.prototype.click;
#     HTMLElement.prototype.click = function () {
#         const link = enclosingLink(this);
#         if (!link || !linkOpensTab(link)) click.call(this);
#     };
#     const dispatchEvent = EventTarget.prototype.dispatchEvent;
#     EventTarget.prototype.dispatchEvent = function (event) {
#         const link = event?.type === 'click' ? enclosingLink(this) : null;
#         return link && linkOpensTab(link) ? false : dispatchEvent.call(this, event);
#     };
#     const submit = HTMLFormElement.prototype.submit;
#     HTMLFormElement.prototype.submit = function () {
#         if (!opensTab(this, this.getAttribute('target'))) submit.call(this);
#     };
# })();
# """
# # Newsletter, discount and region popups inside the page, which can cover a button.
# _CLOSE_OVERLAYS_SCRIPT = """() => {
#     const selector = [
#         '[role="dialog"] [aria-label*="close" i]',
#         '[aria-modal="true"] [aria-label*="close" i]',
#         '[class*="popup" i] [class*="close" i]',
#         '[id*="popup" i] [class*="close" i]',
#         '[class*="newsletter" i] [class*="close" i]',
#         '.klaviyo-close-form',
#     ].join(', ');
#     for (const element of document.querySelectorAll(selector)) {
#         if (element.getClientRects().length) element.click();
#     }
# }"""
# # Ready once enough different matches exist, or the whole page has been read.
# _PAGE_READY_SCRIPT = """([selector, count]) => {
#     const found = [...document.querySelectorAll(selector)].map(e => e.pathname ?? e);
#     return new Set(found).size >= count || document.readyState !== 'loading';
# }"""
# _PRODUCT_PATH_RE = re.compile(r"/products?/[^/]+/?$", re.IGNORECASE)
# _PRODUCT_LINK_SELECTOR = 'a[href*="/products/" i], a[href*="/product/" i]'
# _SKIPPED_PRODUCT_RE = re.compile(r"gift|e-?card|sample|warranty|protection", re.IGNORECASE)
# _LOGIN_URL_RE = re.compile(r"/account/login|/customer_authentication|/authentication|/account\b")
# _CHALLENGE_RE = re.compile(r"/challenge|captcha", re.IGNORECASE)
# _BLOCKED_TEXT_RE = re.compile(
#     r"verify you are human|are you a robot|access denied|unusual traffic", re.IGNORECASE
# )
# _ADD_BUTTON_TEXT_RE = re.compile(r"add to (cart|bag|basket|order)", re.IGNORECASE)
# _BUY_NOW_TEXT_RE = re.compile(
#     r"^\s*buy\s*$|\b(buy (it )?now|buy today|order now|purchase( now)?|check ?out now)\b",
#     re.IGNORECASE,
# )
# # These open a separate payment service, not the store's own checkout.
# _PAYMENT_SERVICE_RE = re.compile(
#     r"pay\b|paypal|shop\s?pay|gpay|venmo|amazon|klarna|afterpay|installment", re.IGNORECASE
# )
# _CHECKOUT_TEXT_RE = re.compile(r"^\s*((proceed|continue|go) to |secure )?check ?out\b", re.IGNORECASE)
# _BUY_NOW_CONTAINER = '.shopify-payment-button, [data-shopify="payment-button"], shopify-accelerated-checkout'
# _BUTTON_SELECTORS = (
#     'form[action*="/cart/add"] button[name="add"]',
#     'form[action*="/cart/add"] [type="submit"]',
#     'button[name="add"]',
#     'button[data-testid*="add-to-cart" i]',
#     'button[id*="add-to-cart" i]',
#     'button[class*="add-to-cart" i]',
# )
# _PRODUCT_READY_SELECTOR = ", ".join((*_BUTTON_SELECTORS, _BUY_NOW_CONTAINER))


# @dataclass
# class SiteResult:
#     site: str
#     status: str = "error"
#     product_url: str = ""
#     checkout_url: str = ""
#     added_by: str = ""
#     seconds: float = 0.0
#     detail: str = ""


# class StopSite(Exception):
#     """This store can't go further. The message is its status."""

#     def __init__(self, status: str, detail: str = "") -> None:
#         super().__init__(status)
#         self.status = status
#         self.detail = detail


# def _base_host(host: str) -> str:
#     return host.removeprefix("www.")


# def _other_www_form(url: str) -> str:
#     parsed = urlparse(url)
#     host = parsed.netloc
#     other = _base_host(host) if host.startswith("www.") else f"www.{host}"
#     return parsed._replace(netloc=other).geturl()


# def _site_url(site: str) -> str:
#     return site if "://" in site else f"https://{site}"


# async def _open_fast(page: Page, url: str, ready_selector: str, count: int = 1) -> None:
#     """Open a URL and return once what's needed is there, not when the page finishes."""
#     await page.goto(url, wait_until="commit")
#     await _wait_until_ready(page, ready_selector, count)


# async def _wait_until_ready(page: Page, ready_selector: str, count: int = 1) -> None:
#     deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
#     while time.monotonic() < deadline:
#         try:
#             if await page.evaluate(_PAGE_READY_SCRIPT, [ready_selector, count]):
#                 return
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(100)


# async def _hard_refresh(page: Page, url: str) -> None:
#     """Reload a failed page the way Ctrl+Shift+R does, skipping the browser's cache.

#     Returns when the new page commits, and raises Error if it fails, like page.goto.
#     """
#     # Chrome only has the store's address to reload once its error page has
#     # appeared. Before that, opening the URL is the same request: every tab has
#     # routes, and those also make Chrome skip its cache.
#     if not page.url.startswith("chrome-error:"):
#         await page.goto(url, wait_until="commit")
#         return

#     outcome = asyncio.get_running_loop().create_future()

#     def on_request_failed(request: Request) -> None:
#         if request.is_navigation_request() and request.frame == page.main_frame and not outcome.done():
#             outcome.set_exception(Error(request.failure or "the page failed to load"))

#     def on_frame_navigated(frame: Frame) -> None:
#         # A failed load also navigates, to Chrome's error page.
#         if frame == page.main_frame and not frame.url.startswith("chrome-error:") and not outcome.done():
#             outcome.set_result(None)

#     page.on("requestfailed", on_request_failed)
#     page.on("framenavigated", on_frame_navigated)
#     # A session stops working when the error page replaces the tab's contents,
#     # so each refresh needs its own.
#     session = await page.context.new_cdp_session(page)
#     try:
#         try:
#             await session.send("Page.reload", {"ignoreCache": True})
#         except Error as error:
#             if "Not attached" not in str(error):
#                 raise
#             await page.goto(url, wait_until="commit")  # The error page was still appearing.
#             return
#         try:
#             await asyncio.wait_for(outcome, NAV_TIMEOUT_MS / 1000)
#         except asyncio.TimeoutError:
#             raise Error(f"hard refresh timed out after {NAV_TIMEOUT_MS} ms") from None
#     finally:
#         page.remove_listener("requestfailed", on_request_failed)
#         page.remove_listener("framenavigated", on_frame_navigated)
#         if outcome.done() and not outcome.cancelled():
#             outcome.exception()  # Mark a failure as seen if the goto above replaced it.
#         try:
#             await session.detach()
#         except Error:
#             pass  # The session already ended with the page it was attached to.


# async def open_home_page(page: Page, url: str) -> None:
#     """Open the store, hard refreshing when the domain lookup fails.

#     A failed lookup is retried up to ``len(DNS_RETRY_DELAYS_S)`` times (5 by
#     default) before the other www/non-www form is tried, because these lookups
#     often fail only temporarily, so the store isn't assumed to be down.
#     """
#     steps = [
#         (url, False, 0),
#         *[(url, True, delay) for delay in DNS_RETRY_DELAYS_S],
#         (_other_www_form(url), False, 0),
#     ]
#     for attempt, hard_refresh, delay in steps:
#         await asyncio.sleep(delay)
#         try:
#             if hard_refresh:
#                 await _hard_refresh(page, attempt)
#             else:
#                 await page.goto(attempt, wait_until="commit")
#             await _wait_until_ready(page, _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
#             return
#         except Error as error:
#             # Retry both temporary DNS failures and slow/anti-bot first-paint timeouts.
#             if "ERR_NAME_NOT_RESOLVED" not in str(error) and "Timeout" not in str(error):
#                 raise
#     raise StopSite("dns_error", f"could not look up {urlparse(url).netloc}")


# async def _read_page(page: Page, script: str):
#     """Run a script that reads the page, waiting out any redirect that replaces it.

#     Pages are used before they finish loading, so a store's region or language
#     redirect can land in the middle of a read.
#     """
#     for _ in range(REDIRECT_RETRIES):
#         try:
#             return await page.evaluate(script)
#         except Error as error:
#             if "Execution context was destroyed" not in str(error):
#                 raise
#         try:
#             await page.wait_for_load_state("domcontentloaded", timeout=REDIRECT_WAIT_MS)
#         except Error:
#             pass  # Still loading or navigating. The next read will show which.
#     return await page.evaluate(script)


# async def _store_root(page: Page) -> str:
#     """The store's base path, which includes the language on some stores (/en-us/)."""
#     return await _read_page(page, "() => window.Shopify?.routes?.root || '/'")


# async def _fetch_json(page: Page, path: str, body: dict | None = None) -> dict | None:
#     """Request a same-site URL from inside the page, so store cookies are used."""
#     try:
#         return await page.evaluate(
#             """async ([path, body]) => {
#                 try {
#                     const response = await fetch(path, body ? {
#                         method: 'POST',
#                         headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
#                         body: JSON.stringify(body),
#                     } : {headers: {'Accept': 'application/json'}});
#                     return response.ok ? await response.json() : null;
#                 } catch (error) {
#                     return null;
#                 }
#             }""",
#             [path, body],
#         )
#     except Error:  # The page navigated away during the request.
#         return None


# async def _fetch_text(page: Page, path: str) -> str | None:
#     """Fetch a same-site URL as text (for XML sitemaps), using the store's cookies."""
#     try:
#         return await page.evaluate(
#             """async (path) => {
#                 try {
#                     const response = await fetch(path, {headers: {'Accept': 'text/xml, */*'}});
#                     return response.ok ? await response.text() : null;
#                 } catch (error) { return null; }
#             }""",
#             path,
#         )
#     except Error:
#         return None


# async def _check_page_state(page: Page) -> None:
#     """Raise if the page shows something this tool shouldn't try to get past."""
#     title = await _read_page(page, "() => document.title")  # First: it may wait out a redirect.
#     url = page.url
#     path = urlparse(url).path
#     if path.rstrip("/").endswith("/password"):
#         raise StopSite("password_protected", url)
#     if "/throttle" in path or "/queue" in path:
#         raise StopSite("in_queue", url)
#     if _LOGIN_URL_RE.search(path):
#         raise StopSite("login_required", url)
#     if _CHALLENGE_RE.search(path):
#         raise StopSite("blocked", url)
#     if _BLOCKED_TEXT_RE.search(title):
#         raise StopSite("blocked", title)


# async def _is_shopify(page: Page) -> bool:
#     dom = await _read_page(
#         page,
#         """() => Boolean(window.Shopify)
#             || Boolean(document.querySelector('script[src*="cdn.shopify.com"], link[href*="cdn.shopify.com"]'))""",
#     )
#     if dom:
#         return True
#     # The DOM check misses stores whose Shopify global loads late or sit behind a
#     # splash/redirect. Confirm against the storefront API, which only Shopify answers.
#     for path, keys in (("/products.json?limit=1", ("products",)), ("/cart.js", ("token", "item_count"))):
#         data = await _fetch_json(page, path)
#         if isinstance(data, dict) and any(key in data for key in keys):
#             return True
#     return False


# async def _links_on_page(page: Page) -> list[str]:
#     hrefs = await _read_page(page, "() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
#     host = _base_host(urlparse(page.url).hostname)  # After the read, which may wait out a redirect.
#     links: dict[str, str] = {}
#     for href in hrefs:
#         parsed = urlparse(href)
#         if parsed.scheme not in ("http", "https") or parsed.hostname is None:
#             continue
#         if _base_host(parsed.hostname) != host:
#             continue
#         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
#             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
#     return list(links.values())


# async def _wait_for_home_links(page: Page) -> list[str]:
#     """Read the home page's product links, allowing time for a redirect or late links."""
#     deadline = time.monotonic() + HOME_LINKS_WAIT_S
#     while True:
#         links = await _links_on_page(page)
#         if links or time.monotonic() >= deadline:
#             return links
#         await page.wait_for_timeout(250)
#         await _check_page_state(page)  # A redirect may have landed on a password page or queue.


# async def _links_from_sitemap(page: Page, root: str) -> list[str]:
#     """Pull product URLs from the store's product sitemap (some themes expose nothing else)."""
#     xml = await _fetch_text(page, urljoin(page.url, f"{root}sitemap_products_1.xml")) or ""
#     links: dict[str, str] = {}
#     for loc in re.findall(r"<loc>\s*([^<\s]+?/products/[^<\s]+?)\s*</loc>", xml, re.IGNORECASE):
#         parsed = urlparse(loc)
#         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
#             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
#     return list(links.values())


# async def find_product_links(page: Page) -> list[str]:
#     """Home page, then Shopify's product feed, then the sitemap, then collection pages."""
#     links = await _wait_for_home_links(page)
#     if links:
#         return links
#     root = await _store_root(page)
#     feed = await _fetch_json(page, f"{root}products.json?limit=50") or {}
#     links = [
#         urljoin(page.url, f"{root}products/{product['handle']}")
#         for product in feed.get("products", [])
#         if not _SKIPPED_PRODUCT_RE.search(product.get("handle", ""))
#     ]
#     if links:
#         return links
#     links = await _links_from_sitemap(page, root)
#     if links:
#         return links
#     for path in (f"{root}collections/all", f"{root}collections"):
#         try:
#             await _open_fast(page, urljoin(page.url, path), _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
#             await _check_page_state(page)
#             links = await _links_on_page(page)
#             if links:
#                 return links
#         except Error:
#             continue  # Try the next catalog path.
#     return links


# async def _products_from_origin(page: Page, url: str) -> list[str]:
#     """Recover product links from the original host's products.json.

#     Some stores redirect their homepage to a non-Shopify splash (e.g.
#     store.faithgateway.com -> www.store...), while the Shopify store still answers on
#     the original host. Reading products.json there finds products the homepage hid.
#     """
#     base = urlparse(url)
#     origin = f"{base.scheme}://{base.netloc}"
#     try:
#         await page.goto(f"{origin}/products.json?limit=50", wait_until="domcontentloaded")
#         text = await _read_page(page, "() => document.body ? document.body.innerText : ''")
#         data = json.loads(text)
#     except (Error, ValueError):
#         return []
#     if not isinstance(data, dict):
#         return []
#     return [
#         f"{origin}/products/{product['handle']}"
#         for product in data.get("products", [])
#         if product.get("handle") and not _SKIPPED_PRODUCT_RE.search(product["handle"])
#     ]


# async def _cart_count(page: Page, root: str) -> int:
#     return (await _fetch_json(page, f"{root}cart.js") or {}).get("item_count", 0)


# async def _add_with_cart_api(page: Page, root: str) -> bool:
#     """Add the first purchasable variant. This works whatever the store's theme is."""
#     path = urlparse(page.url).path.rstrip("/")
#     product = await _fetch_json(page, f"{path}.js")
#     if not product or product.get("gift_card") or product.get("requires_selling_plan"):
#         return False
#     for variant in product.get("variants", []):
#         if not variant.get("available") or variant.get("requires_selling_plan"):
#             continue
#         items = {"items": [{"id": variant["id"], "quantity": 1}]}
#         if await _fetch_json(page, f"{root}cart/add.js", items) and await _cart_count(page, root) > 0:
#             return True
#     return False


# async def _usable(locator) -> bool:
#     try:
#         return await locator.is_visible() and await locator.is_enabled()
#     except Error:
#         return False


# async def _buy_now_candidates(page: Page) -> list:
#     candidates = [page.locator(".shopify-payment-button__button--unbranded").first]
#     for scope in (page.locator('form[action*="/cart/add"]'), page):
#         buttons = scope.get_by_role("button", name=_BUY_NOW_TEXT_RE)
#         candidates += [buttons.nth(i) for i in range(min(await buttons.count(), 10))]
#     return candidates


# async def _find_buy_now(page: Page):
#     """Find a Buy Now button, skipping separate payment services.

#     Those buttons often show only a logo, so their name is in `aria-label`.
#     """
#     for button in await _buy_now_candidates(page):
#         if not await _usable(button):
#             continue
#         label = f"{await button.inner_text()} {await button.get_attribute('aria-label') or ''}"
#         if not _PAYMENT_SERVICE_RE.search(label):
#             return button
#     return None


# async def _find_add_button(page: Page):
#     candidates = [page.locator(selector).first for selector in _BUTTON_SELECTORS]
#     candidates.append(page.get_by_role("button", name=_ADD_BUTTON_TEXT_RE).first)
#     for button in candidates:
#         if await _usable(button):
#             return button
#     return None


# async def _wait_for_button(page: Page, *finders: tuple) -> tuple[str, object] | None:
#     """Return the first button that shows, as (method, button). Earlier finders win."""
#     started = time.monotonic()
#     while True:
#         try:
#             for method, find in finders:
#                 button = await find(page)
#                 if button is not None:
#                     return method, button
#             has_container = await page.locator(_BUY_NOW_CONTAINER).count() > 0
#         except Error:
#             has_container = False
#         limit = BUY_NOW_WAIT_WITH_CONTAINER_S if has_container else BUY_NOW_WAIT_S
#         if time.monotonic() - started >= limit:
#             return None
#         await page.wait_for_timeout(250)


# async def _close_overlays(page: Page) -> None:
#     try:
#         await page.evaluate(_CLOSE_OVERLAYS_SCRIPT)
#     except Error:
#         pass  # The page was navigating, so there's nothing to close.


# async def _click(page: Page, button) -> bool:
#     """Close any popup in the page, then click. Try again if a popup appears first."""
#     for _ in range(2):
#         await _close_overlays(page)
#         try:
#             await button.click(timeout=CLICK_TIMEOUT_MS)
#             return True
#         except Error:
#             try:
#                 await page.keyboard.press("Escape")
#             except Error:
#                 pass
#     return False


# async def _find_checkout_button(page: Page):
#     for role in ("button", "link"):
#         options = page.get_by_role(role, name=_CHECKOUT_TEXT_RE)
#         for index in range(min(await options.count(), 10)):
#             if await _usable(options.nth(index)):
#                 return options.nth(index)
#     return None


# def _on_checkout(page: Page) -> bool:
#     """True once the tab has redirected to a checkout (same tab, any host)."""
#     return "/checkouts/" in page.url


# async def _wait_for_checkout_url(page: Page, seconds: float) -> bool:
#     deadline = time.monotonic() + seconds
#     while time.monotonic() < deadline:
#         if _on_checkout(page):
#             return True
#         try:
#             await _check_page_state(page)
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(200)
#     return False


# async def _use_buy_now(page: Page, root: str, button) -> bool:
#     """Click Buy Now once. Return True if checkout opened or the cart has an item.

#     A Buy click that navigates to the checkout makes button.click() raise (the page is
#     gone), so we DON'T treat a failed click as failure -- we check the URL regardless.
#     """
#     await _click(page, button)
#     # Some stores open a cart first, so look for its checkout button early.
#     deadline = time.monotonic() + AFTER_CLICK_WAIT_S
#     if await _wait_for_checkout_url(page, 3):
#         return True
#     try:
#         checkout = await _find_checkout_button(page)
#         if checkout is not None:
#             await checkout.click(timeout=5_000)
#     except Error:
#         pass
#     if await _wait_for_checkout_url(page, max(deadline - time.monotonic(), 1)):
#         return True
#     return await _cart_count(page, root) > 0


# async def _add_with_button(page: Page, root: str, button) -> bool:
#     """Click the store's add-to-cart button once.

#     Some stores (e.g. Govee) redirect straight to a checkout on another host instead
#     of filling a cart, so reaching a checkout counts as success too.
#     """
#     await _click(page, button)  # may raise internally if the click navigates; that's fine
#     deadline = time.monotonic() + CART_UPDATE_WAIT_S  # short: Buy / permalink are tried next
#     while time.monotonic() < deadline:
#         if _on_checkout(page) or await _cart_count(page, root) > 0:
#             return True
#         await page.wait_for_timeout(250)
#     return False


# # Picks the first available option in each variant selector, so Add to Cart is enabled
# # on products that require a size/colour choice first.
# _SELECT_VARIANTS_SCRIPT = """() => {
#     const form = document.querySelector('form[action*="/cart/add"]') || document;
#     const unavailable = /unavailable|sold out|out of stock/i;
#     for (const select of form.querySelectorAll('select')) {
#         const option = [...select.options].find(
#             o => o.value && !o.disabled && !unavailable.test(o.textContent)
#         );
#         if (option && select.value !== option.value) {
#             select.value = option.value;
#             select.dispatchEvent(new Event('change', {bubbles: true}));
#         }
#     }
#     const groups = {};
#     for (const input of form.querySelectorAll('input[type=radio]')) {
#         if (!input.disabled) (groups[input.name] = groups[input.name] || []).push(input);
#     }
#     for (const name in groups) {
#         if (!groups[name].some(i => i.checked)) {
#             const pick = groups[name][0];
#             pick.checked = true;
#             try { pick.click(); } catch (e) {}
#             pick.dispatchEvent(new Event('change', {bubbles: true}));
#         }
#     }
# }"""


# async def _select_variants(page: Page) -> None:
#     try:
#         await page.evaluate(_SELECT_VARIANTS_SCRIPT)
#         await page.wait_for_timeout(300)  # Let the theme re-enable the button.
#     except Error:
#         pass  # Best-effort; the add/cart-API paths still run.


# async def _use_product_buttons(page: Page, root: str) -> str | None:
#     """Try Add to Cart first, then Buy. Return the method that worked."""
#     found = await _wait_for_button(page, ("button", _find_add_button), ("buy_now", _find_buy_now))
#     if found is None:
#         return None
#     method, button = found
#     if method == "button":
#         if await _add_with_button(page, root, button):
#             return method
#         found = await _wait_for_button(page, ("buy_now", _find_buy_now))
#         if found is None:
#             return None
#         method, button = found
#     return method if await _use_buy_now(page, root, button) else None


# async def _checkout_via_permalink(page: Page, root: str) -> str | None:
#     """Add the first available variant via the cart permalink, which goes to checkout.

#     `/<root>cart/<variant_id>:1` bypasses the variant-button UI entirely and, on stores
#     like Govee, redirects straight to the checkout host -- which is all we need.
#     """
#     path = urlparse(page.url).path.rstrip("/")
#     product = await _fetch_json(page, f"{path}.js")
#     if not product or product.get("requires_selling_plan"):
#         return None
#     for variant in product.get("variants", []):
#         if not variant.get("available") or variant.get("requires_selling_plan"):
#             continue
#         try:
#             await page.goto(urljoin(page.url, f"{root}cart/{variant['id']}:1"), wait_until="commit")
#         except Error:
#             continue
#         if await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S):
#             return "permalink"
#     return None


# async def start_checkout(page: Page, links: list[str], result: SiteResult) -> str:
#     """Add to Cart, then Buy, then the cart permalink, then the cart API. Return the base path."""
#     for link in links[:MAX_PRODUCTS_TO_TRY]:
#         try:
#             await _open_fast(page, link, _PRODUCT_READY_SELECTOR)
#         except Error:
#             continue
#         await _check_page_state(page)
#         root = await _store_root(page)
#         result.product_url = page.url
#         await _select_variants(page)  # Enable Add to Cart on size/colour products.
#         method = await _use_product_buttons(page, root)
#         if method is not None:
#             result.added_by = method
#             return root
#         # Variant picked by UI failed (e.g. Govee's custom buttons) -> add by permalink.
#         method = await _checkout_via_permalink(page, root)
#         if method is not None:
#             result.added_by = method
#             return root
#         if await _add_with_cart_api(page, root):
#             result.added_by = "cart_api"
#             return root
#     raise StopSite("could_not_add_to_cart", f"tried {min(len(links), MAX_PRODUCTS_TO_TRY)} products")


# async def open_checkout(page: Page, root: str) -> bool:
#     """Reach checkout, then return True if the page has its session data.

#     Many themes open a side cart whose "Check Out" button is what reaches the real
#     checkout, so that's tried first; otherwise fall back to navigating to /checkout.
#     """
#     if "/checkouts/" not in page.url:
#         button = await _find_checkout_button(page)
#         if button is not None:
#             await _click(page, button)
#             await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S)
#         if "/checkouts/" not in page.url:
#             try:
#                 await page.goto(urljoin(page.url, f"{root}checkout"), wait_until="domcontentloaded")
#             except Error:
#                 pass
#     deadline = time.monotonic() + CHECKOUT_TIMEOUT_S
#     while time.monotonic() < deadline:
#         try:
#             await _check_page_state(page)
#             if await page.locator('meta[name="serialized-sessionToken"]').count():
#                 return True
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(250)
#     if "/checkouts/" in page.url:
#         return False
#     raise StopSite("checkout_not_reached", page.url)


# async def _reach_checkout_with_buy(page: Page, root: str, result: SiteResult) -> bool:
#     """Click Buy or Checkout on the page /checkout led to, then on the product page.

#     Some stores only show their checkout button after Buy is clicked on an item
#     that's already in the cart. Return True once the page is a checkout.
#     """
#     for url in ("", result.product_url):
#         try:
#             if url:
#                 await _open_fast(page, url, _PRODUCT_READY_SELECTOR)
#                 await _check_page_state(page)
#             found = await _wait_for_button(
#                 page, ("buy_now", _find_buy_now), ("checkout", _find_checkout_button)
#             )
#             if found is None:
#                 continue
#             method, button = found
#             await _use_buy_now(page, root, button)  # Also clicks any checkout button it reveals.
#         except Error:
#             continue  # The page failed or navigated away. Try the next one.
#         if "/checkouts/" in page.url:
#             result.added_by += f"+{method}"
#             return True
#     return False


# async def _open_checkout_any_way(page: Page, root: str, result: SiteResult) -> bool:
#     """Reach a real Shopify /checkouts/ session by whatever path works.

#     1. Normal /checkout (or a side-cart Check Out button, handled in open_checkout).
#     2. Buy / Checkout buttons on the product or cart.
#     3. The native cart permalink /cart/<variant>:1 -- a Shopify server route that works
#        even for custom/headless storefronts (e.g. typhur) whose buttons go elsewhere.
#     Returns True if the checkout exposes its session data.
#     """
#     try:
#         return await open_checkout(page, root)
#     except StopSite as stop:
#         if stop.status != "checkout_not_reached":
#             raise

#     if await _reach_checkout_with_buy(page, root, result):
#         try:
#             return await open_checkout(page, root)
#         except StopSite:
#             pass

#     if "/checkouts/" not in page.url and result.product_url:
#         try:
#             await _open_fast(page, result.product_url, _PRODUCT_READY_SELECTOR)
#             if await _checkout_via_permalink(page, root):
#                 result.added_by = (result.added_by + "+permalink").lstrip("+")
#                 return await open_checkout(page, root)
#         except (Error, StopSite):
#             pass

#     if "/checkouts/" in page.url:
#         return False
#     raise StopSite("checkout_not_reached", page.url)


# async def _saved_html(page: Page) -> str:
#     for _ in range(5):
#         try:
#             return await page.content()
#         except Error:  # The page was navigating. Try again.
#             await page.wait_for_timeout(1_000)
#     return await page.content()


# def _belongs_to_host(domain: str, host: str) -> bool:
#     domain = domain.lstrip(".")
#     return host == domain or host.endswith(f".{domain}")


# async def _save_store_state(page: Page, path: Path) -> None:
#     """Save only this store's data, because tabs for other stores share the browser.

#     This has the format of context.storage_state(), which can't be used here: it opens
#     a visible tab and visits every site this browser has seen, including ad hosts.
#     """
#     storage = await _read_page(
#         page,
#         """() => ({
#             origin: location.origin,
#             localStorage: Object.entries(localStorage).map(([name, value]) => ({name, value})),
#         })""",
#     )
#     host = urlparse(storage["origin"]).hostname
#     state = {
#         "cookies": [c for c in await page.context.cookies() if _belongs_to_host(c["domain"], host)],
#         "origins": [storage] if storage["localStorage"] else [],
#     }
#     path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# async def _prepare_for_next_store(page: Page, url: str) -> None:
#     """Start with an empty cart even if this store has been visited before."""
#     host = _base_host(urlparse(url).hostname or "")
#     await page.context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(host)}$"))
#     # A blank page stops anything the last store was still loading, which could
#     # otherwise interrupt the next store's first page.
#     for _ in range(3):
#         try:
#             await page.goto("about:blank")
#             return
#         except Error:
#             await page.wait_for_timeout(500)


# async def process_site(page: Page, site: str, out_dir: Path) -> SiteResult:
#     result = SiteResult(site=site)
#     started = time.monotonic()
#     url = _site_url(site)
#     try:
#         await _prepare_for_next_store(page, url)
#         await open_home_page(page, url)
#         await _check_page_state(page)
#         if await _is_shopify(page):
#             links = await find_product_links(page)
#         else:
#             # Homepage redirected off to a non-Shopify splash; recover from the
#             # original host's products.json, which a real Shopify store still answers.
#             links = await _products_from_origin(page, url)
#             if not links:
#                 raise StopSite("not_shopify", page.url)
#         if not links:
#             raise StopSite("no_products_found")
#         root = await start_checkout(page, links, result)

#         has_session_data = await _open_checkout_any_way(page, root, result)
#         # Same-tab checkout redirect (e.g. us.govee.com -> store.govee.com) lands here,
#         # so page.url is the real checkout host and the folder is named for it.
#         result.checkout_url = page.url

#         parsed = urlparse(page.url)
#         store_dir = out_dir / parsed.netloc.replace(":", "_")
#         store_dir.mkdir(parents=True, exist_ok=True)
#         html = await _saved_html(page)
#         (store_dir / "checkout.html").write_text(html, encoding="utf-8")
#         # Holds this store's cookies, which a later Proposal request will need.
#         await _save_store_state(page, store_dir / "storage_state.json")

#         if not has_session_data:
#             result.status = "checkout_without_session_data"
#             return result
#         try:
#             payload = build_proposal_payload(html, None)
#         except CheckoutParseError as error:
#             result.status = "payload_failed"
#             result.detail = str(error)
#             return result
#         (store_dir / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
#         result.status = "ok"
#     except StopSite as stop:
#         result.status = stop.status
#         result.detail = stop.detail
#     except Error as error:
#         result.status = "browser_error"
#         result.detail = str(error).splitlines()[0][:200]
#     finally:
#         result.seconds = round(time.monotonic() - started, 1)
#     return result


# async def _block_slow_requests(route: Route) -> None:
#     request = route.request
#     try:
#         if request.resource_type in _BLOCKED_RESOURCE_TYPES or _BLOCKED_HOST_RE.search(
#             urlparse(request.url).hostname or ""
#         ):
#             await route.abort()
#         else:
#             await route.continue_()
#     except Error:
#         pass  # The page closed or moved on, so the request no longer matters.


# class WorkerTabs:
#     """Opens the worker tabs, and closes every other tab the browser opens."""

#     def __init__(self, context: BrowserContext) -> None:
#         self.context = context
#         self._tabs: set[Page] = set()
#         # The browser reports a new tab before new_page() returns it, so this makes
#         # the closer wait until a worker's own tab has been recorded.
#         self._opening = asyncio.Lock()
#         context.on("page", lambda page: asyncio.ensure_future(self._close_if_extra(page)))

#     async def open(self) -> Page:
#         async with self._opening:
#             page = await self.context.new_page()
#             self._tabs.add(page)
#         return page

#     async def _close_if_extra(self, page: Page) -> None:
#         async with self._opening:
#             pass
#         if page not in self._tabs:
#             try:
#                 await page.close(run_before_unload=False)
#             except Error:
#                 pass

#     def _is_extra_tab(self, request: Request) -> bool:
#         try:
#             return request.frame.page not in self._tabs
#         except Error:  # A page load with no frame yet is a new tab starting up.
#             return True

#     async def block_unwanted_pages(self, route: Route) -> None:
#         request = route.request
#         try:
#             if not request.is_navigation_request():
#                 await route.fallback()
#             elif self._is_extra_tab(request):
#                 # Answer with an empty page, so nothing reaches the real server. Don't
#                 # abort here: Playwright only reports a new tab once its first page
#                 # loads, so an aborted one would stay open and never reach the closer.
#                 await route.fulfill(status=200, content_type="text/html", body="")
#             elif _JUNK_PAGE_HOST_RE.search(urlparse(request.url).hostname or ""):
#                 # "aborted" keeps the current page. Other errors replace it with an error page.
#                 await route.abort("aborted")
#             else:
#                 await route.fallback()
#         except Error:
#             pass  # The page closed or moved on, so the request no longer matters.


# async def launch_browser(playwright: Playwright, *, headless: bool = False) -> Browser:
#     args = _STEALTH_ARGS
#     try:  # Real installed Chrome is trusted more than bundled Chromium.
#         return await playwright.chromium.launch(
#             headless=headless, channel="chrome", args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
#         )
#     except Error:
#         return await playwright.chromium.launch(
#             headless=headless, args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
#         )


# async def open_context(browser: Browser, *, block_slow_requests: bool = True) -> WorkerTabs:
#     """Open the one window that every store shares."""
#     context = await browser.new_context(
#         user_agent=_USER_AGENT,
#         locale="en-US",
#         timezone_id="America/New_York",
#         viewport={"width": 1366, "height": 768},
#         extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
#     )
#     context.set_default_timeout(NAV_TIMEOUT_MS)
#     context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
#     await context.add_init_script(_STEALTH_SCRIPT)
#     await context.add_init_script(_NO_POPUPS_SCRIPT)
#     if block_slow_requests:
#         await context.route("**/*", _block_slow_requests)
#     tabs = WorkerTabs(context)
#     # The newest route runs first, then falls back to the one above.
#     await context.route("**/*", tabs.block_unwanted_pages)
#     return tabs


# def read_sites(path: Path) -> list[str]:
#     """Read the list, dropping stores that appear twice in different forms."""
#     sites: dict[str, str] = {}
#     for line in path.read_text(encoding="utf-8").splitlines():
#         site = line.strip()
#         if not site or site.startswith("#"):
#             continue
#         parsed = urlparse(_site_url(site))
#         key = f"{_base_host(parsed.netloc.lower())}{parsed.path.rstrip('/')}"
#         sites.setdefault(key, site)
#     return list(sites.values())


# def sites_to_retry(results: list[SiteResult]) -> list[str]:
#     retryable = ("dns_error", "browser_error", "timed_out")
#     return [r.site for r in results if r.status in retryable]


# async def _worker(tabs: WorkerTabs, sites: asyncio.Queue, out_dir: Path, report) -> None:
#     page = await tabs.open()
#     while not sites.empty():
#         site = sites.get_nowait()
#         if page.is_closed():
#             try:
#                 page = await tabs.open()
#             except Error:
#                 report(SiteResult(site=site, status="browser_error", detail="the browser was closed"))
#                 continue
#         try:
#             result = await asyncio.wait_for(process_site(page, site, out_dir), SITE_TIMEOUT_S)
#         except asyncio.TimeoutError:
#             result = SiteResult(site=site, status="timed_out", seconds=SITE_TIMEOUT_S)
#         report(result)
#     if not page.is_closed():
#         await page.close(run_before_unload=False)


# async def run(
#     sites: list[str],
#     out_dir: Path,
#     *,
#     workers: int = DEFAULT_WORKERS,
#     block_slow_requests: bool = True,
#     headless: bool = False,
# ) -> list[SiteResult]:
#     out_dir.mkdir(parents=True, exist_ok=True)
#     results: list[SiteResult] = []
#     with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as csv_file:
#         writer = csv.DictWriter(csv_file, fieldnames=list(SiteResult.__dataclass_fields__))
#         writer.writeheader()

#         def report(result: SiteResult) -> None:
#             results.append(result)
#             writer.writerow(asdict(result))
#             csv_file.flush()  # Keep finished rows if a long run is interrupted.
#             print(f"[{len(results)}/{len(sites)}] {result.status:30} {result.seconds:6.1f}s  {result.site}  {result.detail}")

#         queue: asyncio.Queue = asyncio.Queue()
#         for site in sites:
#             queue.put_nowait(site)
#         async with async_playwright() as playwright:
#             browser = await launch_browser(playwright, headless=headless)
#             tabs = await open_context(browser, block_slow_requests=block_slow_requests)
#             await asyncio.gather(
#                 *(_worker(tabs, queue, out_dir, report) for _ in range(min(workers, len(sites)) or 1))
#             )
#             await browser.close()
#     retry = sites_to_retry(results)
#     if retry:
#         (out_dir / RETRY_FILE_NAME).write_text("\n".join(retry) + "\n", encoding="utf-8")
#     return results


# def main() -> None:
#     parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
#     parser.add_argument("sites", type=Path, help="text file with one store per line")
#     parser.add_argument("--out", type=Path, default=Path("checkouts"), help="output folder")
#     parser.add_argument(
#         "--workers", type=int, default=DEFAULT_WORKERS, help="how many stores to run at once"
#     )
#     parser.add_argument(
#         "--load-everything",
#         action="store_true",
#         help="also load images, fonts and trackers, in case blocking them breaks a store",
#     )
#     args = parser.parse_args()
#     started = time.monotonic()
#     results = asyncio.run(
#         run(
#             read_sites(args.sites),
#             args.out,
#             workers=args.workers,
#             block_slow_requests=not args.load_everything,
#         )
#     )
#     done = sum(result.status == "ok" for result in results)
#     minutes = (time.monotonic() - started) / 60
#     print(f"\n{done} of {len(results)} stores reached checkout in {minutes:.1f} minutes.")
#     print(f"See {args.out / 'results.csv'}")
#     retry = sites_to_retry(results)
#     if retry:
#         print(f"{len(retry)} stores had connection errors or timeouts. See {args.out / RETRY_FILE_NAME}")


# if __name__ == "__main__":
#     main()


"""Open Shopify stores, add a product to the cart and save each checkout page.

    pip install -U playwright
    playwright install chromium
    python shopify_checkout.py sites.txt

All stores share one browser window, with one tab per worker. Any other tab that
opens is closed at once. Pages are only loaded as far as the next step needs, so
the tool moves on as soon as the product links or buttons appear. Each store gets a
folder in `checkouts/`, and `checkouts/results.csv` has one row per store. This
stops at the checkout page: it never enters details or pays. It also doesn't try
to get past logins, captchas or queues, and reports them instead.
"""
# from __future__ import annotations

# import argparse
# import asyncio
# import csv
# import json
# import re
# import time
# from dataclasses import asdict, dataclass
# from pathlib import Path
# from urllib.parse import urljoin, urlparse

# from playwright.async_api import (
#     Browser,
#     BrowserContext,
#     Error,
#     Frame,
#     Page,
#     Playwright,
#     Request,
#     Route,
#     async_playwright,
# )

# from shopify_proposal import CheckoutParseError, build_proposal_payload

# DEFAULT_WORKERS = 1
# NAV_TIMEOUT_MS = 40_000  # Longer first-paint budget for slow / anti-bot stores.
# CLICK_TIMEOUT_MS = 2_000  # Short, so an overlay covering a button costs little time.
# SITE_TIMEOUT_S = 160  # A slow store can't hold up a tab for longer than this.
# CHECKOUT_TIMEOUT_S = 30  # Slow stores take a while to hand over the checkout session.
# MAX_PRODUCTS_TO_TRY = 3
# # Shopify loads its Buy Now button late, so wait longer if its container is on the page.
# BUY_NOW_WAIT_WITH_CONTAINER_S = 5
# BUY_NOW_WAIT_S = 2
# AFTER_CLICK_WAIT_S = 15  # Slow stores redirect to a separate checkout host (e.g. store.govee.com).
# CART_UPDATE_WAIT_S = 6
# # Hard refresh the page this many times when the domain lookup fails (DNS errors are
# # usually temporary). Short, growing gaps give the lookup time to recover without
# # holding the tab for long. After these, the other www/non-www form is tried.
# DNS_RETRY_DELAYS_S = (1, 2, 3, 5, 8)
# # Reading a page is tried again this many times if a redirect replaces it meanwhile.
# REDIRECT_RETRIES = 5
# REDIRECT_WAIT_MS = 5_000
# # A home page with no product links may be about to redirect or still be adding them.
# HOME_LINKS_WAIT_S = 3
# RETRY_FILE_NAME = "retry_sites.txt"

# _BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
# _BLOCKED_HOST_RE = re.compile(
#     r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|connect\.facebook\.net"
#     r"|hotjar\.com|clarity\.ms|analytics\.tiktok\.com|bat\.bing\.com|static\.klaviyo\.com"
#     r"|attn\.tv|attentivemobile\.com|cdn\.segment\.com|snapchat\.com|pinimg\.com",
#     re.IGNORECASE,
# )
# # Ad and redirect pages often live on these raw hosting domains. Stores also use
# # them for scripts and files, so only opening one as a page or iframe is blocked.
# # Add more domains here if another one shows up.
# _JUNK_PAGE_HOST_RE = re.compile(
#     r"(^|\.)(cloudfront\.net|amazonaws\.com|azureedge\.net|akamaihd\.net|b-cdn\.net)$",
#     re.IGNORECASE,
# )
# # Playwright turns off Chromium's popup blocker by default. Keeping it on stops
# # popups that scripts open without a click.
# _KEEP_POPUP_BLOCKER = ["--disable-popup-blocking"]
# # --- Stealth: make the automated browser look like an ordinary one -----------
# # A real, recent Chrome user agent and launch flag that hides the automation bit.
# _USER_AGENT = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# )
# _STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
# # Patches the handful of signals bot-detectors check first (navigator.webdriver, etc).
# _STEALTH_SCRIPT = """
# (() => {
#     const hide = (obj, name, value) => {
#         try { Object.defineProperty(obj, name, {get: () => value}); } catch (e) {}
#     };
#     hide(navigator, 'webdriver', undefined);
#     hide(navigator, 'languages', ['en-US', 'en']);
#     hide(navigator, 'plugins', [1, 2, 3, 4, 5]);
#     try { window.chrome = window.chrome || {runtime: {}}; } catch (e) {}
#     try {
#         const query = navigator.permissions && navigator.permissions.query;
#         if (query) {
#             navigator.permissions.query = parameters =>
#                 parameters && parameters.name === 'notifications'
#                     ? Promise.resolve({state: Notification.permission})
#                     : query(parameters);
#         }
#     } catch (e) {}
# })();
# """
# # Stops every new tab before it starts, including the ones the popup blocker allows
# # because they follow a click. Checkout that redirects on the SAME tab is unaffected.
# # WorkerTabs closes any tab that still opens.
# _NO_POPUPS_SCRIPT = """
# (() => {
#     const opensTab = (element, target) => {
#         const base = element.ownerDocument.querySelector('base[target]');
#         const name = target || base?.getAttribute('target') || '';
#         const keyword = name.toLowerCase();
#         if (['', '_self', '_parent', '_top'].includes(keyword)) return false;
#         // A name that matches an iframe loads there. Any other name opens a new tab.
#         return keyword === '_blank'
#             || !element.ownerDocument.querySelector(`iframe[name="${CSS.escape(name)}"]`);
#     };
#     const linkOpensTab = link => opensTab(link, link.getAttribute('target'));
#     const enclosingLink = node => node.closest?.('a[href], area[href]');

#     window.open = () => null;  // What a popup blocker returns.

#     // composedPath() also sees links inside shadow DOM, which event.target hides.
#     const stopNewTabClick = event => {
#         const link = event.composedPath().find(node => node.matches?.('a[href], area[href]'));
#         if (!link) return;
#         const opensSeparately = event.type === 'auxclick'
#             || event.ctrlKey || event.metaKey || event.shiftKey;
#         if (opensSeparately || linkOpensTab(link)) event.preventDefault();
#     };
#     window.addEventListener('click', stopNewTabClick, true);
#     window.addEventListener('auxclick', stopNewTabClick, true);
#     window.addEventListener('submit', event => {
#         const form = event.target;
#         const target = event.submitter?.getAttribute('formtarget') || form.getAttribute('target');
#         if (opensTab(form, target)) event.preventDefault();
#     }, true);

#     // A link that isn't on the page sends its click event nowhere near window, and
#     // form.submit() sends no event at all, so these have to be stopped at the call.
#     const click = HTMLElement.prototype.click;
#     HTMLElement.prototype.click = function () {
#         const link = enclosingLink(this);
#         if (!link || !linkOpensTab(link)) click.call(this);
#     };
#     const dispatchEvent = EventTarget.prototype.dispatchEvent;
#     EventTarget.prototype.dispatchEvent = function (event) {
#         const link = event?.type === 'click' ? enclosingLink(this) : null;
#         return link && linkOpensTab(link) ? false : dispatchEvent.call(this, event);
#     };
#     const submit = HTMLFormElement.prototype.submit;
#     HTMLFormElement.prototype.submit = function () {
#         if (!opensTab(this, this.getAttribute('target'))) submit.call(this);
#     };
# })();
# """
# # Newsletter, discount and region popups inside the page, which can cover a button.
# _CLOSE_OVERLAYS_SCRIPT = """() => {
#     const selector = [
#         '[role="dialog"] [aria-label*="close" i]',
#         '[aria-modal="true"] [aria-label*="close" i]',
#         '[class*="popup" i] [class*="close" i]',
#         '[id*="popup" i] [class*="close" i]',
#         '[class*="newsletter" i] [class*="close" i]',
#         '.klaviyo-close-form',
#     ].join(', ');
#     for (const element of document.querySelectorAll(selector)) {
#         if (element.getClientRects().length) element.click();
#     }
# }"""
# # Ready once enough different matches exist, or the whole page has been read.
# _PAGE_READY_SCRIPT = """([selector, count]) => {
#     const found = [...document.querySelectorAll(selector)].map(e => e.pathname ?? e);
#     return new Set(found).size >= count || document.readyState !== 'loading';
# }"""
# _PRODUCT_PATH_RE = re.compile(r"/products?/[^/]+/?$", re.IGNORECASE)
# _PRODUCT_LINK_SELECTOR = 'a[href*="/products/" i], a[href*="/product/" i]'
# _SKIPPED_PRODUCT_RE = re.compile(r"gift|e-?card|sample|warranty|protection", re.IGNORECASE)
# _LOGIN_URL_RE = re.compile(r"/account/login|/customer_authentication|/authentication|/account\b")
# _CHALLENGE_RE = re.compile(r"/challenge|captcha", re.IGNORECASE)
# _BLOCKED_TEXT_RE = re.compile(
#     r"verify you are human|are you a robot|access denied|unusual traffic", re.IGNORECASE
# )
# _ADD_BUTTON_TEXT_RE = re.compile(r"add to (cart|bag|basket|order)", re.IGNORECASE)
# _BUY_NOW_TEXT_RE = re.compile(
#     r"^\s*buy\s*$|\b(buy (it )?now|buy today|order now|purchase( now)?|check ?out now)\b",
#     re.IGNORECASE,
# )
# # These open a separate payment service, not the store's own checkout.
# _PAYMENT_SERVICE_RE = re.compile(
#     r"pay\b|paypal|shop\s?pay|gpay|venmo|amazon|klarna|afterpay|installment", re.IGNORECASE
# )
# _CHECKOUT_TEXT_RE = re.compile(r"^\s*((proceed|continue|go) to |secure )?check ?out\b", re.IGNORECASE)
# _BUY_NOW_CONTAINER = '.shopify-payment-button, [data-shopify="payment-button"], shopify-accelerated-checkout'
# _BUTTON_SELECTORS = (
#     'form[action*="/cart/add"] button[name="add"]',
#     'form[action*="/cart/add"] [type="submit"]',
#     'button[name="add"]',
#     'button[data-testid*="add-to-cart" i]',
#     'button[id*="add-to-cart" i]',
#     'button[class*="add-to-cart" i]',
# )
# _PRODUCT_READY_SELECTOR = ", ".join((*_BUTTON_SELECTORS, _BUY_NOW_CONTAINER))


# @dataclass
# class SiteResult:
#     site: str
#     status: str = "error"
#     product_url: str = ""
#     checkout_url: str = ""
#     added_by: str = ""
#     seconds: float = 0.0
#     detail: str = ""


# class StopSite(Exception):
#     """This store can't go further. The message is its status."""

#     def __init__(self, status: str, detail: str = "") -> None:
#         super().__init__(status)
#         self.status = status
#         self.detail = detail


# def _base_host(host: str) -> str:
#     return host.removeprefix("www.")


# def _other_www_form(url: str) -> str:
#     parsed = urlparse(url)
#     host = parsed.netloc
#     other = _base_host(host) if host.startswith("www.") else f"www.{host}"
#     return parsed._replace(netloc=other).geturl()


# def _site_url(site: str) -> str:
#     return site if "://" in site else f"https://{site}"


# async def _open_fast(page: Page, url: str, ready_selector: str, count: int = 1) -> None:
#     """Open a URL and return once what's needed is there, not when the page finishes."""
#     await page.goto(url, wait_until="commit")
#     await _wait_until_ready(page, ready_selector, count)


# async def _wait_until_ready(page: Page, ready_selector: str, count: int = 1) -> None:
#     deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
#     while time.monotonic() < deadline:
#         try:
#             if await page.evaluate(_PAGE_READY_SCRIPT, [ready_selector, count]):
#                 return
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(100)


# async def _hard_refresh(page: Page, url: str) -> None:
#     """Reload a failed page the way Ctrl+Shift+R does, skipping the browser's cache.

#     Returns when the new page commits, and raises Error if it fails, like page.goto.
#     """
#     # Chrome only has the store's address to reload once its error page has
#     # appeared. Before that, opening the URL is the same request: every tab has
#     # routes, and those also make Chrome skip its cache.
#     if not page.url.startswith("chrome-error:"):
#         await page.goto(url, wait_until="commit")
#         return

#     outcome = asyncio.get_running_loop().create_future()

#     def on_request_failed(request: Request) -> None:
#         if request.is_navigation_request() and request.frame == page.main_frame and not outcome.done():
#             outcome.set_exception(Error(request.failure or "the page failed to load"))

#     def on_frame_navigated(frame: Frame) -> None:
#         # A failed load also navigates, to Chrome's error page.
#         if frame == page.main_frame and not frame.url.startswith("chrome-error:") and not outcome.done():
#             outcome.set_result(None)

#     page.on("requestfailed", on_request_failed)
#     page.on("framenavigated", on_frame_navigated)
#     # A session stops working when the error page replaces the tab's contents,
#     # so each refresh needs its own.
#     session = await page.context.new_cdp_session(page)
#     try:
#         try:
#             await session.send("Page.reload", {"ignoreCache": True})
#         except Error as error:
#             if "Not attached" not in str(error):
#                 raise
#             await page.goto(url, wait_until="commit")  # The error page was still appearing.
#             return
#         try:
#             await asyncio.wait_for(outcome, NAV_TIMEOUT_MS / 1000)
#         except asyncio.TimeoutError:
#             raise Error(f"hard refresh timed out after {NAV_TIMEOUT_MS} ms") from None
#     finally:
#         page.remove_listener("requestfailed", on_request_failed)
#         page.remove_listener("framenavigated", on_frame_navigated)
#         if outcome.done() and not outcome.cancelled():
#             outcome.exception()  # Mark a failure as seen if the goto above replaced it.
#         try:
#             await session.detach()
#         except Error:
#             pass  # The session already ended with the page it was attached to.


# async def open_home_page(page: Page, url: str) -> None:
#     """Open the store, hard refreshing when the domain lookup fails.

#     A failed lookup is retried up to ``len(DNS_RETRY_DELAYS_S)`` times (5 by
#     default) before the other www/non-www form is tried, because these lookups
#     often fail only temporarily, so the store isn't assumed to be down.
#     """
#     steps = [
#         (url, False, 0),
#         *[(url, True, delay) for delay in DNS_RETRY_DELAYS_S],
#         (_other_www_form(url), False, 0),
#     ]
#     for attempt, hard_refresh, delay in steps:
#         await asyncio.sleep(delay)
#         try:
#             if hard_refresh:
#                 await _hard_refresh(page, attempt)
#             else:
#                 await page.goto(attempt, wait_until="commit")
#             await _wait_until_ready(page, _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
#             return
#         except Error as error:
#             # Retry both temporary DNS failures and slow/anti-bot first-paint timeouts.
#             if "ERR_NAME_NOT_RESOLVED" not in str(error) and "Timeout" not in str(error):
#                 raise
#     raise StopSite("dns_error", f"could not look up {urlparse(url).netloc}")


# async def _read_page(page: Page, script: str):
#     """Run a script that reads the page, waiting out any redirect that replaces it.

#     Pages are used before they finish loading, so a store's region or language
#     redirect can land in the middle of a read.
#     """
#     for _ in range(REDIRECT_RETRIES):
#         try:
#             return await page.evaluate(script)
#         except Error as error:
#             if "Execution context was destroyed" not in str(error):
#                 raise
#         try:
#             await page.wait_for_load_state("domcontentloaded", timeout=REDIRECT_WAIT_MS)
#         except Error:
#             pass  # Still loading or navigating. The next read will show which.
#     return await page.evaluate(script)


# async def _store_root(page: Page) -> str:
#     """The store's base path, which includes the language on some stores (/en-us/)."""
#     return await _read_page(page, "() => window.Shopify?.routes?.root || '/'")


# async def _fetch_json(page: Page, path: str, body: dict | None = None) -> dict | None:
#     """Request a same-site URL from inside the page, so store cookies are used."""
#     try:
#         return await page.evaluate(
#             """async ([path, body]) => {
#                 try {
#                     const response = await fetch(path, body ? {
#                         method: 'POST',
#                         headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
#                         body: JSON.stringify(body),
#                     } : {headers: {'Accept': 'application/json'}});
#                     return response.ok ? await response.json() : null;
#                 } catch (error) {
#                     return null;
#                 }
#             }""",
#             [path, body],
#         )
#     except Error:  # The page navigated away during the request.
#         return None


# async def _fetch_text(page: Page, path: str) -> str | None:
#     """Fetch a same-site URL as text (for XML sitemaps), using the store's cookies."""
#     try:
#         return await page.evaluate(
#             """async (path) => {
#                 try {
#                     const response = await fetch(path, {headers: {'Accept': 'text/xml, */*'}});
#                     return response.ok ? await response.text() : null;
#                 } catch (error) { return null; }
#             }""",
#             path,
#         )
#     except Error:
#         return None


# async def _check_page_state(page: Page) -> None:
#     """Raise if the page shows something this tool shouldn't try to get past."""
#     title = await _read_page(page, "() => document.title")  # First: it may wait out a redirect.
#     url = page.url
#     path = urlparse(url).path
#     if path.rstrip("/").endswith("/password"):
#         raise StopSite("password_protected", url)
#     if "/throttle" in path or "/queue" in path:
#         raise StopSite("in_queue", url)
#     if _LOGIN_URL_RE.search(path):
#         raise StopSite("login_required", url)
#     if _CHALLENGE_RE.search(path):
#         raise StopSite("blocked", url)
#     if _BLOCKED_TEXT_RE.search(title):
#         raise StopSite("blocked", title)


# async def _is_shopify(page: Page) -> bool:
#     dom = await _read_page(
#         page,
#         """() => Boolean(window.Shopify)
#             || Boolean(document.querySelector('script[src*="cdn.shopify.com"], link[href*="cdn.shopify.com"]'))""",
#     )
#     if dom:
#         return True
#     # The DOM check misses stores whose Shopify global loads late or sit behind a
#     # splash/redirect. Confirm against the storefront API, which only Shopify answers.
#     for path, keys in (("/products.json?limit=1", ("products",)), ("/cart.js", ("token", "item_count"))):
#         data = await _fetch_json(page, path)
#         if isinstance(data, dict) and any(key in data for key in keys):
#             return True
#     return False


# async def _links_on_page(page: Page) -> list[str]:
#     hrefs = await _read_page(page, "() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
#     host = _base_host(urlparse(page.url).hostname)  # After the read, which may wait out a redirect.
#     links: dict[str, str] = {}
#     for href in hrefs:
#         parsed = urlparse(href)
#         if parsed.scheme not in ("http", "https") or parsed.hostname is None:
#             continue
#         if _base_host(parsed.hostname) != host:
#             continue
#         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
#             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
#     return list(links.values())


# async def _wait_for_home_links(page: Page) -> list[str]:
#     """Read the home page's product links, allowing time for a redirect or late links."""
#     deadline = time.monotonic() + HOME_LINKS_WAIT_S
#     while True:
#         links = await _links_on_page(page)
#         if links or time.monotonic() >= deadline:
#             return links
#         await page.wait_for_timeout(250)
#         await _check_page_state(page)  # A redirect may have landed on a password page or queue.


# async def _links_from_sitemap(page: Page, root: str) -> list[str]:
#     """Pull product URLs from the store's product sitemap (some themes expose nothing else)."""
#     xml = await _fetch_text(page, urljoin(page.url, f"{root}sitemap_products_1.xml")) or ""
#     links: dict[str, str] = {}
#     for loc in re.findall(r"<loc>\s*([^<\s]+?/products/[^<\s]+?)\s*</loc>", xml, re.IGNORECASE):
#         parsed = urlparse(loc)
#         if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
#             links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
#     return list(links.values())


# async def find_product_links(page: Page) -> list[str]:
#     """Home page, then Shopify's product feed, then the sitemap, then collection pages."""
#     links = await _wait_for_home_links(page)
#     if links:
#         return links
#     root = await _store_root(page)
#     feed = await _fetch_json(page, f"{root}products.json?limit=50") or {}
#     links = [
#         urljoin(page.url, f"{root}products/{product['handle']}")
#         for product in feed.get("products", [])
#         if not _SKIPPED_PRODUCT_RE.search(product.get("handle", ""))
#     ]
#     if links:
#         return links
#     links = await _links_from_sitemap(page, root)
#     if links:
#         return links
#     for path in (f"{root}collections/all", f"{root}collections"):
#         try:
#             await _open_fast(page, urljoin(page.url, path), _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
#             await _check_page_state(page)
#             links = await _links_on_page(page)
#             if links:
#                 return links
#         except Error:
#             continue  # Try the next catalog path.
#     return links


# async def _products_from_origin(page: Page, url: str) -> list[str]:
#     """Recover product links from the store's products.json over HTTPS.

#     Some stores redirect their homepage (and even a browser navigation to
#     products.json) to a non-Shopify splash on another host/scheme, while the Shopify
#     store still answers products.json over HTTPS. Fetching it with the HTTP client
#     (not a browser navigation) over both host variants avoids that redirect.
#     """
#     host = _base_host(urlparse(url).netloc)
#     for netloc in (host, f"www.{host}"):
#         endpoint = f"https://{netloc}/products.json?limit=50"
#         try:
#             response = await page.context.request.get(endpoint, timeout=NAV_TIMEOUT_MS)
#             if not response.ok:
#                 continue
#             data = await response.json()
#         except Exception:
#             continue
#         products = data.get("products") if isinstance(data, dict) else None
#         if products:
#             origin = f"https://{netloc}"
#             return [
#                 f"{origin}/products/{product['handle']}"
#                 for product in products
#                 if product.get("handle") and not _SKIPPED_PRODUCT_RE.search(product["handle"])
#             ]
#     return []


# async def _cart_count(page: Page, root: str) -> int:
#     return (await _fetch_json(page, f"{root}cart.js") or {}).get("item_count", 0)


# async def _add_with_cart_api(page: Page, root: str) -> bool:
#     """Add the first purchasable variant. This works whatever the store's theme is."""
#     path = urlparse(page.url).path.rstrip("/")
#     product = await _fetch_json(page, f"{path}.js")
#     if not product or product.get("gift_card") or product.get("requires_selling_plan"):
#         return False
#     for variant in product.get("variants", []):
#         if not variant.get("available") or variant.get("requires_selling_plan"):
#             continue
#         items = {"items": [{"id": variant["id"], "quantity": 1}]}
#         if await _fetch_json(page, f"{root}cart/add.js", items) and await _cart_count(page, root) > 0:
#             return True
#     return False


# async def _usable(locator) -> bool:
#     try:
#         return await locator.is_visible() and await locator.is_enabled()
#     except Error:
#         return False


# async def _buy_now_candidates(page: Page) -> list:
#     candidates = [page.locator(".shopify-payment-button__button--unbranded").first]
#     for scope in (page.locator('form[action*="/cart/add"]'), page):
#         buttons = scope.get_by_role("button", name=_BUY_NOW_TEXT_RE)
#         candidates += [buttons.nth(i) for i in range(min(await buttons.count(), 10))]
#     return candidates


# async def _find_buy_now(page: Page):
#     """Find a Buy Now button, skipping separate payment services.

#     Those buttons often show only a logo, so their name is in `aria-label`.
#     """
#     for button in await _buy_now_candidates(page):
#         if not await _usable(button):
#             continue
#         label = f"{await button.inner_text()} {await button.get_attribute('aria-label') or ''}"
#         if not _PAYMENT_SERVICE_RE.search(label):
#             return button
#     return None


# async def _find_add_button(page: Page):
#     candidates = [page.locator(selector).first for selector in _BUTTON_SELECTORS]
#     candidates.append(page.get_by_role("button", name=_ADD_BUTTON_TEXT_RE).first)
#     for button in candidates:
#         if await _usable(button):
#             return button
#     return None


# async def _wait_for_button(page: Page, *finders: tuple) -> tuple[str, object] | None:
#     """Return the first button that shows, as (method, button). Earlier finders win."""
#     started = time.monotonic()
#     while True:
#         try:
#             for method, find in finders:
#                 button = await find(page)
#                 if button is not None:
#                     return method, button
#             has_container = await page.locator(_BUY_NOW_CONTAINER).count() > 0
#         except Error:
#             has_container = False
#         limit = BUY_NOW_WAIT_WITH_CONTAINER_S if has_container else BUY_NOW_WAIT_S
#         if time.monotonic() - started >= limit:
#             return None
#         await page.wait_for_timeout(250)


# async def _close_overlays(page: Page) -> None:
#     try:
#         await page.evaluate(_CLOSE_OVERLAYS_SCRIPT)
#     except Error:
#         pass  # The page was navigating, so there's nothing to close.


# async def _click(page: Page, button) -> bool:
#     """Close any popup in the page, then click. Try again if a popup appears first."""
#     for _ in range(2):
#         await _close_overlays(page)
#         try:
#             await button.click(timeout=CLICK_TIMEOUT_MS)
#             return True
#         except Error:
#             try:
#                 await page.keyboard.press("Escape")
#             except Error:
#                 pass
#     return False


# async def _find_checkout_button(page: Page):
#     for role in ("button", "link"):
#         options = page.get_by_role(role, name=_CHECKOUT_TEXT_RE)
#         for index in range(min(await options.count(), 10)):
#             if await _usable(options.nth(index)):
#                 return options.nth(index)
#     return None


# def _on_checkout(page: Page) -> bool:
#     """True once the tab has redirected to a checkout (same tab, any host)."""
#     return "/checkouts/" in page.url


# async def _wait_for_checkout_url(page: Page, seconds: float) -> bool:
#     deadline = time.monotonic() + seconds
#     while time.monotonic() < deadline:
#         if _on_checkout(page):
#             return True
#         try:
#             await _check_page_state(page)
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(200)
#     return False


# async def _use_buy_now(page: Page, root: str, button) -> bool:
#     """Click Buy Now once. Return True if checkout opened or the cart has an item.

#     A Buy click that navigates to the checkout makes button.click() raise (the page is
#     gone), so we DON'T treat a failed click as failure -- we check the URL regardless.
#     """
#     await _click(page, button)
#     # Some stores open a cart first, so look for its checkout button early.
#     deadline = time.monotonic() + AFTER_CLICK_WAIT_S
#     if await _wait_for_checkout_url(page, 3):
#         return True
#     try:
#         checkout = await _find_checkout_button(page)
#         if checkout is not None:
#             await checkout.click(timeout=5_000)
#     except Error:
#         pass
#     if await _wait_for_checkout_url(page, max(deadline - time.monotonic(), 1)):
#         return True
#     return await _cart_count(page, root) > 0


# async def _add_with_button(page: Page, root: str, button) -> bool:
#     """Click the store's add-to-cart button once.

#     Some stores (e.g. Govee) redirect straight to a checkout on another host instead
#     of filling a cart, so reaching a checkout counts as success too.
#     """
#     await _click(page, button)  # may raise internally if the click navigates; that's fine
#     deadline = time.monotonic() + CART_UPDATE_WAIT_S  # short: Buy / permalink are tried next
#     while time.monotonic() < deadline:
#         if _on_checkout(page) or await _cart_count(page, root) > 0:
#             return True
#         # A cart drawer with a "Check Out" button means the add worked even when the
#         # native /cart.js stays empty (custom/headless carts like typhur). open_checkout
#         # then clicks that button.
#         if await _find_checkout_button(page) is not None:
#             return True
#         await page.wait_for_timeout(250)
#     return False


# # Picks the first available option in each variant selector, so Add to Cart is enabled
# # on products that require a size/colour choice first.
# _SELECT_VARIANTS_SCRIPT = """() => {
#     const form = document.querySelector('form[action*="/cart/add"]') || document;
#     const unavailable = /unavailable|sold out|out of stock/i;
#     for (const select of form.querySelectorAll('select')) {
#         const option = [...select.options].find(
#             o => o.value && !o.disabled && !unavailable.test(o.textContent)
#         );
#         if (option && select.value !== option.value) {
#             select.value = option.value;
#             select.dispatchEvent(new Event('change', {bubbles: true}));
#         }
#     }
#     const groups = {};
#     for (const input of form.querySelectorAll('input[type=radio]')) {
#         if (!input.disabled) (groups[input.name] = groups[input.name] || []).push(input);
#     }
#     for (const name in groups) {
#         if (!groups[name].some(i => i.checked)) {
#             const pick = groups[name][0];
#             pick.checked = true;
#             try { pick.click(); } catch (e) {}
#             pick.dispatchEvent(new Event('change', {bubbles: true}));
#         }
#     }
# }"""


# async def _select_variants(page: Page) -> None:
#     try:
#         await page.evaluate(_SELECT_VARIANTS_SCRIPT)
#         await page.wait_for_timeout(300)  # Let the theme re-enable the button.
#     except Error:
#         pass  # Best-effort; the add/cart-API paths still run.


# async def _use_product_buttons(page: Page, root: str) -> str | None:
#     """Try Add to Cart first, then Buy. Return the method that worked."""
#     found = await _wait_for_button(page, ("button", _find_add_button), ("buy_now", _find_buy_now))
#     if found is None:
#         return None
#     method, button = found
#     if method == "button":
#         if await _add_with_button(page, root, button):
#             return method
#         found = await _wait_for_button(page, ("buy_now", _find_buy_now))
#         if found is None:
#             return None
#         method, button = found
#     return method if await _use_buy_now(page, root, button) else None


# async def _checkout_via_permalink(page: Page, root: str) -> str | None:
#     """Add the first available variant via the cart permalink, which goes to checkout.

#     `/<root>cart/<variant_id>:1` bypasses the variant-button UI entirely and, on stores
#     like Govee, redirects straight to the checkout host -- which is all we need.
#     """
#     path = urlparse(page.url).path.rstrip("/")
#     product = await _fetch_json(page, f"{path}.js")
#     if not product or product.get("requires_selling_plan"):
#         return None
#     for variant in product.get("variants", []):
#         if not variant.get("available") or variant.get("requires_selling_plan"):
#             continue
#         try:
#             await page.goto(urljoin(page.url, f"{root}cart/{variant['id']}:1"), wait_until="commit")
#         except Error:
#             continue
#         if await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S):
#             return "permalink"
#     return None


# async def start_checkout(page: Page, links: list[str], result: SiteResult) -> str:
#     """Add to Cart, then Buy, then the cart permalink, then the cart API. Return the base path."""
#     for link in links[:MAX_PRODUCTS_TO_TRY]:
#         try:
#             await _open_fast(page, link, _PRODUCT_READY_SELECTOR)
#         except Error:
#             continue
#         await _check_page_state(page)
#         root = await _store_root(page)
#         result.product_url = page.url
#         await _select_variants(page)  # Enable Add to Cart on size/colour products.
#         method = await _use_product_buttons(page, root)
#         if method is not None:
#             result.added_by = method
#             return root
#         # Variant picked by UI failed (e.g. Govee's custom buttons) -> add by permalink.
#         method = await _checkout_via_permalink(page, root)
#         if method is not None:
#             result.added_by = method
#             return root
#         if await _add_with_cart_api(page, root):
#             result.added_by = "cart_api"
#             return root
#     raise StopSite("could_not_add_to_cart", f"tried {min(len(links), MAX_PRODUCTS_TO_TRY)} products")


# async def open_checkout(page: Page, root: str) -> bool:
#     """Reach checkout, then return True if the page has its session data.

#     Many themes open a side cart whose "Check Out" button is what reaches the real
#     checkout, so that's tried first; otherwise fall back to navigating to /checkout.
#     """
#     if "/checkouts/" not in page.url:
#         button = await _find_checkout_button(page)
#         if button is not None:
#             await _click(page, button)
#             await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S)
#         if "/checkouts/" not in page.url:
#             try:
#                 await page.goto(urljoin(page.url, f"{root}checkout"), wait_until="domcontentloaded")
#             except Error:
#                 pass
#     deadline = time.monotonic() + CHECKOUT_TIMEOUT_S
#     while time.monotonic() < deadline:
#         try:
#             await _check_page_state(page)
#             if await page.locator('meta[name="serialized-sessionToken"]').count():
#                 return True
#         except Error:
#             pass  # The page was navigating. Check again.
#         await page.wait_for_timeout(250)
#     if "/checkouts/" in page.url:
#         return False
#     raise StopSite("checkout_not_reached", page.url)


# async def _reach_checkout_with_buy(page: Page, root: str, result: SiteResult) -> bool:
#     """Click Buy or Checkout on the page /checkout led to, then on the product page.

#     Some stores only show their checkout button after Buy is clicked on an item
#     that's already in the cart. Return True once the page is a checkout.
#     """
#     for url in ("", result.product_url):
#         try:
#             if url:
#                 await _open_fast(page, url, _PRODUCT_READY_SELECTOR)
#                 await _check_page_state(page)
#             found = await _wait_for_button(
#                 page, ("buy_now", _find_buy_now), ("checkout", _find_checkout_button)
#             )
#             if found is None:
#                 continue
#             method, button = found
#             await _use_buy_now(page, root, button)  # Also clicks any checkout button it reveals.
#         except Error:
#             continue  # The page failed or navigated away. Try the next one.
#         if "/checkouts/" in page.url:
#             result.added_by += f"+{method}"
#             return True
#     return False


# async def _open_checkout_any_way(page: Page, root: str, result: SiteResult) -> bool:
#     """Reach a real Shopify /checkouts/ session by whatever path works.

#     1. Normal /checkout (or a side-cart Check Out button, handled in open_checkout).
#     2. Buy / Checkout buttons on the product or cart.
#     3. The native cart permalink /cart/<variant>:1 -- a Shopify server route that works
#        even for custom/headless storefronts (e.g. typhur) whose buttons go elsewhere.
#     Returns True if the checkout exposes its session data.
#     """
#     try:
#         return await open_checkout(page, root)
#     except StopSite as stop:
#         if stop.status != "checkout_not_reached":
#             raise

#     if await _reach_checkout_with_buy(page, root, result):
#         try:
#             return await open_checkout(page, root)
#         except StopSite:
#             pass

#     if "/checkouts/" not in page.url and result.product_url:
#         try:
#             await _open_fast(page, result.product_url, _PRODUCT_READY_SELECTOR)
#             if await _checkout_via_permalink(page, root):
#                 result.added_by = (result.added_by + "+permalink").lstrip("+")
#                 return await open_checkout(page, root)
#         except (Error, StopSite):
#             pass

#     if "/checkouts/" in page.url:
#         return False
#     raise StopSite("checkout_not_reached", page.url)


# async def _saved_html(page: Page) -> str:
#     for _ in range(5):
#         try:
#             return await page.content()
#         except Error:  # The page was navigating. Try again.
#             await page.wait_for_timeout(1_000)
#     return await page.content()


# def _belongs_to_host(domain: str, host: str) -> bool:
#     domain = domain.lstrip(".")
#     return host == domain or host.endswith(f".{domain}")


# async def _save_store_state(page: Page, path: Path) -> None:
#     """Save only this store's data, because tabs for other stores share the browser.

#     This has the format of context.storage_state(), which can't be used here: it opens
#     a visible tab and visits every site this browser has seen, including ad hosts.
#     """
#     storage = await _read_page(
#         page,
#         """() => ({
#             origin: location.origin,
#             localStorage: Object.entries(localStorage).map(([name, value]) => ({name, value})),
#         })""",
#     )
#     host = urlparse(storage["origin"]).hostname
#     state = {
#         "cookies": [c for c in await page.context.cookies() if _belongs_to_host(c["domain"], host)],
#         "origins": [storage] if storage["localStorage"] else [],
#     }
#     path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# async def _prepare_for_next_store(page: Page, url: str) -> None:
#     """Start with an empty cart even if this store has been visited before."""
#     host = _base_host(urlparse(url).hostname or "")
#     await page.context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(host)}$"))
#     # A blank page stops anything the last store was still loading, which could
#     # otherwise interrupt the next store's first page.
#     for _ in range(3):
#         try:
#             await page.goto("about:blank")
#             return
#         except Error:
#             await page.wait_for_timeout(500)


# async def process_site(page: Page, site: str, out_dir: Path) -> SiteResult:
#     result = SiteResult(site=site)
#     started = time.monotonic()
#     url = _site_url(site)
#     try:
#         await _prepare_for_next_store(page, url)
#         await open_home_page(page, url)
#         await _check_page_state(page)
#         if await _is_shopify(page):
#             links = await find_product_links(page)
#         else:
#             # Homepage redirected off to a non-Shopify splash; recover from the
#             # original host's products.json, which a real Shopify store still answers.
#             links = await _products_from_origin(page, url)
#             if not links:
#                 raise StopSite("not_shopify", page.url)
#         if not links:
#             raise StopSite("no_products_found")
#         root = await start_checkout(page, links, result)

#         has_session_data = await _open_checkout_any_way(page, root, result)
#         # Same-tab checkout redirect (e.g. us.govee.com -> store.govee.com) lands here,
#         # so page.url is the real checkout host and the folder is named for it.
#         result.checkout_url = page.url

#         parsed = urlparse(page.url)
#         store_dir = out_dir / parsed.netloc.replace(":", "_")
#         store_dir.mkdir(parents=True, exist_ok=True)
#         html = await _saved_html(page)
#         (store_dir / "checkout.html").write_text(html, encoding="utf-8")
#         # Holds this store's cookies, which a later Proposal request will need.
#         await _save_store_state(page, store_dir / "storage_state.json")

#         if not has_session_data:
#             result.status = "checkout_without_session_data"
#             return result
#         try:
#             payload = build_proposal_payload(html, None)
#         except CheckoutParseError as error:
#             result.status = "payload_failed"
#             result.detail = str(error)
#             return result
#         (store_dir / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
#         result.status = "ok"
#     except StopSite as stop:
#         result.status = stop.status
#         result.detail = stop.detail
#     except Error as error:
#         result.status = "browser_error"
#         result.detail = str(error).splitlines()[0][:200]
#     finally:
#         result.seconds = round(time.monotonic() - started, 1)
#     return result


# async def _block_slow_requests(route: Route) -> None:
#     request = route.request
#     try:
#         if request.resource_type in _BLOCKED_RESOURCE_TYPES or _BLOCKED_HOST_RE.search(
#             urlparse(request.url).hostname or ""
#         ):
#             await route.abort()
#         else:
#             await route.continue_()
#     except Error:
#         pass  # The page closed or moved on, so the request no longer matters.


# class WorkerTabs:
#     """Opens the worker tabs, and closes every other tab the browser opens."""

#     def __init__(self, context: BrowserContext) -> None:
#         self.context = context
#         self._tabs: set[Page] = set()
#         # The browser reports a new tab before new_page() returns it, so this makes
#         # the closer wait until a worker's own tab has been recorded.
#         self._opening = asyncio.Lock()
#         context.on("page", lambda page: asyncio.ensure_future(self._close_if_extra(page)))

#     async def open(self) -> Page:
#         async with self._opening:
#             page = await self.context.new_page()
#             self._tabs.add(page)
#         return page

#     async def _close_if_extra(self, page: Page) -> None:
#         async with self._opening:
#             pass
#         if page not in self._tabs:
#             try:
#                 await page.close(run_before_unload=False)
#             except Error:
#                 pass

#     def _is_extra_tab(self, request: Request) -> bool:
#         try:
#             return request.frame.page not in self._tabs
#         except Error:  # A page load with no frame yet is a new tab starting up.
#             return True

#     async def block_unwanted_pages(self, route: Route) -> None:
#         request = route.request
#         try:
#             if not request.is_navigation_request():
#                 await route.fallback()
#             elif self._is_extra_tab(request):
#                 # Answer with an empty page, so nothing reaches the real server. Don't
#                 # abort here: Playwright only reports a new tab once its first page
#                 # loads, so an aborted one would stay open and never reach the closer.
#                 await route.fulfill(status=200, content_type="text/html", body="")
#             elif _JUNK_PAGE_HOST_RE.search(urlparse(request.url).hostname or ""):
#                 # "aborted" keeps the current page. Other errors replace it with an error page.
#                 await route.abort("aborted")
#             else:
#                 await route.fallback()
#         except Error:
#             pass  # The page closed or moved on, so the request no longer matters.


# async def launch_browser(playwright: Playwright, *, headless: bool = False) -> Browser:
#     args = _STEALTH_ARGS
#     try:  # Real installed Chrome is trusted more than bundled Chromium.
#         return await playwright.chromium.launch(
#             headless=headless, channel="chrome", args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
#         )
#     except Error:
#         return await playwright.chromium.launch(
#             headless=headless, args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
#         )


# async def open_context(browser: Browser, *, block_slow_requests: bool = True) -> WorkerTabs:
#     """Open the one window that every store shares."""
#     context = await browser.new_context(
#         user_agent=_USER_AGENT,
#         locale="en-US",
#         timezone_id="America/New_York",
#         viewport={"width": 1366, "height": 768},
#         extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
#     )
#     context.set_default_timeout(NAV_TIMEOUT_MS)
#     context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
#     await context.add_init_script(_STEALTH_SCRIPT)
#     await context.add_init_script(_NO_POPUPS_SCRIPT)
#     if block_slow_requests:
#         await context.route("**/*", _block_slow_requests)
#     tabs = WorkerTabs(context)
#     # The newest route runs first, then falls back to the one above.
#     await context.route("**/*", tabs.block_unwanted_pages)
#     return tabs


# def read_sites(path: Path) -> list[str]:
#     """Read the list, dropping stores that appear twice in different forms."""
#     sites: dict[str, str] = {}
#     for line in path.read_text(encoding="utf-8").splitlines():
#         site = line.strip()
#         if not site or site.startswith("#"):
#             continue
#         parsed = urlparse(_site_url(site))
#         key = f"{_base_host(parsed.netloc.lower())}{parsed.path.rstrip('/')}"
#         sites.setdefault(key, site)
#     return list(sites.values())


# def sites_to_retry(results: list[SiteResult]) -> list[str]:
#     retryable = ("dns_error", "browser_error", "timed_out")
#     return [r.site for r in results if r.status in retryable]


# async def _worker(tabs: WorkerTabs, sites: asyncio.Queue, out_dir: Path, report) -> None:
#     page = await tabs.open()
#     while not sites.empty():
#         site = sites.get_nowait()
#         if page.is_closed():
#             try:
#                 page = await tabs.open()
#             except Error:
#                 report(SiteResult(site=site, status="browser_error", detail="the browser was closed"))
#                 continue
#         try:
#             result = await asyncio.wait_for(process_site(page, site, out_dir), SITE_TIMEOUT_S)
#         except asyncio.TimeoutError:
#             result = SiteResult(site=site, status="timed_out", seconds=SITE_TIMEOUT_S)
#         report(result)
#     if not page.is_closed():
#         await page.close(run_before_unload=False)


# async def run(
#     sites: list[str],
#     out_dir: Path,
#     *,
#     workers: int = DEFAULT_WORKERS,
#     block_slow_requests: bool = True,
#     headless: bool = False,
# ) -> list[SiteResult]:
#     out_dir.mkdir(parents=True, exist_ok=True)
#     results: list[SiteResult] = []
#     with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as csv_file:
#         writer = csv.DictWriter(csv_file, fieldnames=list(SiteResult.__dataclass_fields__))
#         writer.writeheader()

#         def report(result: SiteResult) -> None:
#             results.append(result)
#             writer.writerow(asdict(result))
#             csv_file.flush()  # Keep finished rows if a long run is interrupted.
#             print(f"[{len(results)}/{len(sites)}] {result.status:30} {result.seconds:6.1f}s  {result.site}  {result.detail}")

#         queue: asyncio.Queue = asyncio.Queue()
#         for site in sites:
#             queue.put_nowait(site)
#         async with async_playwright() as playwright:
#             browser = await launch_browser(playwright, headless=headless)
#             tabs = await open_context(browser, block_slow_requests=block_slow_requests)
#             await asyncio.gather(
#                 *(_worker(tabs, queue, out_dir, report) for _ in range(min(workers, len(sites)) or 1))
#             )
#             await browser.close()
#     retry = sites_to_retry(results)
#     if retry:
#         (out_dir / RETRY_FILE_NAME).write_text("\n".join(retry) + "\n", encoding="utf-8")
#     return results


# def main() -> None:
#     parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
#     parser.add_argument("sites", type=Path, help="text file with one store per line")
#     parser.add_argument("--out", type=Path, default=Path("checkouts"), help="output folder")
#     parser.add_argument(
#         "--workers", type=int, default=DEFAULT_WORKERS, help="how many stores to run at once"
#     )
#     parser.add_argument(
#         "--load-everything",
#         action="store_true",
#         help="also load images, fonts and trackers, in case blocking them breaks a store",
#     )
#     args = parser.parse_args()
#     started = time.monotonic()
#     results = asyncio.run(
#         run(
#             read_sites(args.sites),
#             args.out,
#             workers=args.workers,
#             block_slow_requests=not args.load_everything,
#         )
#     )
#     done = sum(result.status == "ok" for result in results)
#     minutes = (time.monotonic() - started) / 60
#     print(f"\n{done} of {len(results)} stores reached checkout in {minutes:.1f} minutes.")
#     print(f"See {args.out / 'results.csv'}")
#     retry = sites_to_retry(results)
#     if retry:
#         print(f"{len(retry)} stores had connection errors or timeouts. See {args.out / RETRY_FILE_NAME}")


# if __name__ == "__main__":
#     main()

"""Open Shopify stores, add a product to the cart and save each checkout page.

    pip install -U playwright
    playwright install chromium
    python shopify_checkout.py sites.txt

All stores share one browser window, with one tab per worker. Any other tab that
opens is closed at once. Pages are only loaded as far as the next step needs, so
the tool moves on as soon as the product links or buttons appear. Each store gets a
folder in `checkouts/`, and `checkouts/results.csv` has one row per store. This
stops at the checkout page: it never enters details or pays. It also doesn't try
to get past logins, captchas or queues, and reports them instead.
"""

import argparse
import asyncio
import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error,
    Frame,
    Page,
    Playwright,
    Request,
    Route,
    async_playwright,
)

from shopify_proposal import CheckoutParseError, build_proposal_payload

DEFAULT_WORKERS = 3
NAV_TIMEOUT_MS = 40_000  # Longer first-paint budget for slow / anti-bot stores.
CLICK_TIMEOUT_MS = 2_000  # Short, so an overlay covering a button costs little time.
SITE_TIMEOUT_S = 160  # A slow store can't hold up a tab for longer than this.
CHECKOUT_TIMEOUT_S = 30  # Slow stores take a while to hand over the checkout session.
MAX_PRODUCTS_TO_TRY = 3
# Shopify loads its Buy Now button late, so wait longer if its container is on the page.
BUY_NOW_WAIT_WITH_CONTAINER_S = 5
BUY_NOW_WAIT_S = 2
AFTER_CLICK_WAIT_S = 15  # Slow stores redirect to a separate checkout host (e.g. store.govee.com).
CART_UPDATE_WAIT_S = 6
# Hard refresh the page this many times when the domain lookup fails (DNS errors are
# usually temporary). Short, growing gaps give the lookup time to recover without
# holding the tab for long. After these, the other www/non-www form is tried.
DNS_RETRY_DELAYS_S = (1, 2, 3, 5, 8)
# Reading a page is tried again this many times if a redirect replaces it meanwhile.
REDIRECT_RETRIES = 5
REDIRECT_WAIT_MS = 5_000
# A home page with no product links may be about to redirect or still be adding them.
HOME_LINKS_WAIT_S = 3
RETRY_FILE_NAME = "retry_sites.txt"

_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_BLOCKED_HOST_RE = re.compile(
    r"google-analytics\.com|googletagmanager\.com|doubleclick\.net|connect\.facebook\.net"
    r"|hotjar\.com|clarity\.ms|analytics\.tiktok\.com|bat\.bing\.com|static\.klaviyo\.com"
    r"|attn\.tv|attentivemobile\.com|cdn\.segment\.com|snapchat\.com|pinimg\.com",
    re.IGNORECASE,
)
# Ad and redirect pages often live on these raw hosting domains. Stores also use
# them for scripts and files, so only opening one as a page or iframe is blocked.
# Add more domains here if another one shows up.
_JUNK_PAGE_HOST_RE = re.compile(
    r"(^|\.)(cloudfront\.net|amazonaws\.com|azureedge\.net|akamaihd\.net|b-cdn\.net)$",
    re.IGNORECASE,
)
# Playwright turns off Chromium's popup blocker by default. Keeping it on stops
# popups that scripts open without a click.
_KEEP_POPUP_BLOCKER = ["--disable-popup-blocking"]
# --- Stealth: make the automated browser look like an ordinary one -----------
# A real, recent Chrome user agent and launch flag that hides the automation bit.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
# Patches the handful of signals bot-detectors check first (navigator.webdriver, etc).
_STEALTH_SCRIPT = """
(() => {
    const hide = (obj, name, value) => {
        try { Object.defineProperty(obj, name, {get: () => value}); } catch (e) {}
    };
    hide(navigator, 'webdriver', undefined);
    hide(navigator, 'languages', ['en-US', 'en']);
    hide(navigator, 'plugins', [1, 2, 3, 4, 5]);
    try { window.chrome = window.chrome || {runtime: {}}; } catch (e) {}
    try {
        const query = navigator.permissions && navigator.permissions.query;
        if (query) {
            navigator.permissions.query = parameters =>
                parameters && parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : query(parameters);
        }
    } catch (e) {}
})();
"""
# Stops every new tab before it starts, including the ones the popup blocker allows
# because they follow a click. Checkout that redirects on the SAME tab is unaffected.
# WorkerTabs closes any tab that still opens.
_NO_POPUPS_SCRIPT = """
(() => {
    const opensTab = (element, target) => {
        const base = element.ownerDocument.querySelector('base[target]');
        const name = target || base?.getAttribute('target') || '';
        const keyword = name.toLowerCase();
        if (['', '_self', '_parent', '_top'].includes(keyword)) return false;
        // A name that matches an iframe loads there. Any other name opens a new tab.
        return keyword === '_blank'
            || !element.ownerDocument.querySelector(`iframe[name="${CSS.escape(name)}"]`);
    };
    const linkOpensTab = link => opensTab(link, link.getAttribute('target'));
    const enclosingLink = node => node.closest?.('a[href], area[href]');

    window.open = () => null;  // What a popup blocker returns.

    // composedPath() also sees links inside shadow DOM, which event.target hides.
    const stopNewTabClick = event => {
        const link = event.composedPath().find(node => node.matches?.('a[href], area[href]'));
        if (!link) return;
        const opensSeparately = event.type === 'auxclick'
            || event.ctrlKey || event.metaKey || event.shiftKey;
        if (opensSeparately || linkOpensTab(link)) event.preventDefault();
    };
    window.addEventListener('click', stopNewTabClick, true);
    window.addEventListener('auxclick', stopNewTabClick, true);
    window.addEventListener('submit', event => {
        const form = event.target;
        const target = event.submitter?.getAttribute('formtarget') || form.getAttribute('target');
        if (opensTab(form, target)) event.preventDefault();
    }, true);

    // A link that isn't on the page sends its click event nowhere near window, and
    // form.submit() sends no event at all, so these have to be stopped at the call.
    const click = HTMLElement.prototype.click;
    HTMLElement.prototype.click = function () {
        const link = enclosingLink(this);
        if (!link || !linkOpensTab(link)) click.call(this);
    };
    const dispatchEvent = EventTarget.prototype.dispatchEvent;
    EventTarget.prototype.dispatchEvent = function (event) {
        const link = event?.type === 'click' ? enclosingLink(this) : null;
        return link && linkOpensTab(link) ? false : dispatchEvent.call(this, event);
    };
    const submit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (!opensTab(this, this.getAttribute('target'))) submit.call(this);
    };
})();
"""
# Newsletter, discount and region popups inside the page, which can cover a button.
_CLOSE_OVERLAYS_SCRIPT = """() => {
    const selector = [
        '[role="dialog"] [aria-label*="close" i]',
        '[aria-modal="true"] [aria-label*="close" i]',
        '[class*="popup" i] [class*="close" i]',
        '[id*="popup" i] [class*="close" i]',
        '[class*="newsletter" i] [class*="close" i]',
        '.klaviyo-close-form',
    ].join(', ');
    for (const element of document.querySelectorAll(selector)) {
        if (element.getClientRects().length) element.click();
    }
}"""
# Ready once enough different matches exist, or the whole page has been read.
_PAGE_READY_SCRIPT = """([selector, count]) => {
    const found = [...document.querySelectorAll(selector)].map(e => e.pathname ?? e);
    return new Set(found).size >= count || document.readyState !== 'loading';
}"""
_PRODUCT_PATH_RE = re.compile(r"/products?/[^/]+/?$", re.IGNORECASE)
_PRODUCT_LINK_SELECTOR = 'a[href*="/products/" i], a[href*="/product/" i]'
_SKIPPED_PRODUCT_RE = re.compile(r"gift|e-?card|sample|warranty|protection", re.IGNORECASE)
_LOGIN_URL_RE = re.compile(r"/account/login|/customer_authentication|/authentication|/account\b")
_CHALLENGE_RE = re.compile(r"/challenge|captcha", re.IGNORECASE)
_BLOCKED_TEXT_RE = re.compile(
    r"verify you are human|are you a robot|access denied|unusual traffic", re.IGNORECASE
)
_ADD_BUTTON_TEXT_RE = re.compile(r"add to (cart|bag|basket|order)", re.IGNORECASE)
_BUY_NOW_TEXT_RE = re.compile(
    r"^\s*buy\s*$|\b(buy (it )?now|buy today|order now|purchase( now)?|check ?out now)\b",
    re.IGNORECASE,
)
# These open a separate payment service, not the store's own checkout.
_PAYMENT_SERVICE_RE = re.compile(
    r"pay\b|paypal|shop\s?pay|gpay|venmo|amazon|klarna|afterpay|installment", re.IGNORECASE
)
_CHECKOUT_TEXT_RE = re.compile(r"^\s*((proceed|continue|go) to |secure )?check ?out\b", re.IGNORECASE)
_BUY_NOW_CONTAINER = '.shopify-payment-button, [data-shopify="payment-button"], shopify-accelerated-checkout'
_BUTTON_SELECTORS = (
    'form[action*="/cart/add"] button[name="add"]',
    'form[action*="/cart/add"] [type="submit"]',
    'button[name="add"]',
    'button[data-testid*="add-to-cart" i]',
    'button[id*="add-to-cart" i]',
    'button[class*="add-to-cart" i]',
)
_PRODUCT_READY_SELECTOR = ", ".join((*_BUTTON_SELECTORS, _BUY_NOW_CONTAINER))


@dataclass
class SiteResult:
    site: str
    status: str = "error"
    product_url: str = ""
    checkout_url: str = ""
    added_by: str = ""
    seconds: float = 0.0
    detail: str = ""


class StopSite(Exception):
    """This store can't go further. The message is its status."""

    def __init__(self, status: str, detail: str = "") -> None:
        super().__init__(status)
        self.status = status
        self.detail = detail


def _base_host(host: str) -> str:
    return host.removeprefix("www.")


def _other_www_form(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc
    other = _base_host(host) if host.startswith("www.") else f"www.{host}"
    return parsed._replace(netloc=other).geturl()


def _site_url(site: str) -> str:
    return site if "://" in site else f"https://{site}"


async def _open_fast(page: Page, url: str, ready_selector: str, count: int = 1) -> None:
    """Open a URL and return once what's needed is there, not when the page finishes."""
    await page.goto(url, wait_until="commit")
    await _wait_until_ready(page, ready_selector, count)


async def _wait_until_ready(page: Page, ready_selector: str, count: int = 1) -> None:
    deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        try:
            if await page.evaluate(_PAGE_READY_SCRIPT, [ready_selector, count]):
                return
        except Error:
            pass  # The page was navigating. Check again.
        await page.wait_for_timeout(100)


async def _hard_refresh(page: Page, url: str) -> None:
    """Reload a failed page the way Ctrl+Shift+R does, skipping the browser's cache.

    Returns when the new page commits, and raises Error if it fails, like page.goto.
    """
    # Chrome only has the store's address to reload once its error page has
    # appeared. Before that, opening the URL is the same request: every tab has
    # routes, and those also make Chrome skip its cache.
    if not page.url.startswith("chrome-error:"):
        await page.goto(url, wait_until="commit")
        return

    outcome = asyncio.get_running_loop().create_future()

    def on_request_failed(request: Request) -> None:
        if request.is_navigation_request() and request.frame == page.main_frame and not outcome.done():
            outcome.set_exception(Error(request.failure or "the page failed to load"))

    def on_frame_navigated(frame: Frame) -> None:
        # A failed load also navigates, to Chrome's error page.
        if frame == page.main_frame and not frame.url.startswith("chrome-error:") and not outcome.done():
            outcome.set_result(None)

    page.on("requestfailed", on_request_failed)
    page.on("framenavigated", on_frame_navigated)
    # A session stops working when the error page replaces the tab's contents,
    # so each refresh needs its own.
    session = await page.context.new_cdp_session(page)
    try:
        try:
            await session.send("Page.reload", {"ignoreCache": True})
        except Error as error:
            if "Not attached" not in str(error):
                raise
            await page.goto(url, wait_until="commit")  # The error page was still appearing.
            return
        try:
            await asyncio.wait_for(outcome, NAV_TIMEOUT_MS / 1000)
        except asyncio.TimeoutError:
            raise Error(f"hard refresh timed out after {NAV_TIMEOUT_MS} ms") from None
    finally:
        page.remove_listener("requestfailed", on_request_failed)
        page.remove_listener("framenavigated", on_frame_navigated)
        if outcome.done() and not outcome.cancelled():
            outcome.exception()  # Mark a failure as seen if the goto above replaced it.
        try:
            await session.detach()
        except Error:
            pass  # The session already ended with the page it was attached to.


async def open_home_page(page: Page, url: str) -> None:
    """Open the store, hard refreshing when the domain lookup fails.

    A failed lookup is retried up to ``len(DNS_RETRY_DELAYS_S)`` times (5 by
    default) before the other www/non-www form is tried, because these lookups
    often fail only temporarily, so the store isn't assumed to be down.
    """
    steps = [
        (url, False, 0),
        *[(url, True, delay) for delay in DNS_RETRY_DELAYS_S],
        (_other_www_form(url), False, 0),
    ]
    for attempt, hard_refresh, delay in steps:
        await asyncio.sleep(delay)
        try:
            if hard_refresh:
                await _hard_refresh(page, attempt)
            else:
                await page.goto(attempt, wait_until="commit")
            await _wait_until_ready(page, _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
            return
        except Error as error:
            # Retry both temporary DNS failures and slow/anti-bot first-paint timeouts.
            if "ERR_NAME_NOT_RESOLVED" not in str(error) and "Timeout" not in str(error):
                raise
    raise StopSite("dns_error", f"could not look up {urlparse(url).netloc}")


async def _read_page(page: Page, script: str):
    """Run a script that reads the page, waiting out any redirect that replaces it.

    Pages are used before they finish loading, so a store's region or language
    redirect can land in the middle of a read.
    """
    for _ in range(REDIRECT_RETRIES):
        try:
            return await page.evaluate(script)
        except Error as error:
            if "Execution context was destroyed" not in str(error):
                raise
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=REDIRECT_WAIT_MS)
        except Error:
            pass  # Still loading or navigating. The next read will show which.
    return await page.evaluate(script)


async def _store_root(page: Page) -> str:
    """The store's base path, which includes the language on some stores (/en-us/)."""
    return await _read_page(page, "() => window.Shopify?.routes?.root || '/'")


async def _fetch_json(page: Page, path: str, body: dict | None = None) -> dict | None:
    """Request a same-site URL from inside the page, so store cookies are used."""
    try:
        return await page.evaluate(
            """async ([path, body]) => {
                try {
                    const response = await fetch(path, body ? {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                        body: JSON.stringify(body),
                    } : {headers: {'Accept': 'application/json'}});
                    return response.ok ? await response.json() : null;
                } catch (error) {
                    return null;
                }
            }""",
            [path, body],
        )
    except Error:  # The page navigated away during the request.
        return None


async def _fetch_text(page: Page, path: str) -> str | None:
    """Fetch a same-site URL as text (for XML sitemaps), using the store's cookies."""
    try:
        return await page.evaluate(
            """async (path) => {
                try {
                    const response = await fetch(path, {headers: {'Accept': 'text/xml, */*'}});
                    return response.ok ? await response.text() : null;
                } catch (error) { return null; }
            }""",
            path,
        )
    except Error:
        return None


async def _check_page_state(page: Page) -> None:
    """Raise if the page shows something this tool shouldn't try to get past."""
    title = await _read_page(page, "() => document.title")  # First: it may wait out a redirect.
    url = page.url
    path = urlparse(url).path
    if path.rstrip("/").endswith("/password"):
        raise StopSite("password_protected", url)
    if "/throttle" in path or "/queue" in path:
        raise StopSite("in_queue", url)
    if _LOGIN_URL_RE.search(path):
        raise StopSite("login_required", url)
    if _CHALLENGE_RE.search(path):
        raise StopSite("blocked", url)
    if _BLOCKED_TEXT_RE.search(title):
        raise StopSite("blocked", title)


async def _is_shopify(page: Page) -> bool:
    dom = await _read_page(
        page,
        """() => Boolean(window.Shopify)
            || Boolean(document.querySelector('script[src*="cdn.shopify.com"], link[href*="cdn.shopify.com"]'))""",
    )
    if dom:
        return True
    # The DOM check misses stores whose Shopify global loads late or sit behind a
    # splash/redirect. Confirm against the storefront API, which only Shopify answers.
    for path, keys in (("/products.json?limit=1", ("products",)), ("/cart.js", ("token", "item_count"))):
        data = await _fetch_json(page, path)
        if isinstance(data, dict) and any(key in data for key in keys):
            return True
    return False


async def _links_on_page(page: Page) -> list[str]:
    hrefs = await _read_page(page, "() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
    host = _base_host(urlparse(page.url).hostname)  # After the read, which may wait out a redirect.
    links: dict[str, str] = {}
    for href in hrefs:
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or parsed.hostname is None:
            continue
        if _base_host(parsed.hostname) != host:
            continue
        if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
            links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
    return list(links.values())


async def _wait_for_home_links(page: Page) -> list[str]:
    """Read the home page's product links, allowing time for a redirect or late links."""
    deadline = time.monotonic() + HOME_LINKS_WAIT_S
    while True:
        links = await _links_on_page(page)
        if links or time.monotonic() >= deadline:
            return links
        await page.wait_for_timeout(250)
        await _check_page_state(page)  # A redirect may have landed on a password page or queue.


async def _links_from_sitemap(page: Page, root: str) -> list[str]:
    """Pull product URLs from the store's product sitemap (some themes expose nothing else)."""
    xml = await _fetch_text(page, urljoin(page.url, f"{root}sitemap_products_1.xml")) or ""
    links: dict[str, str] = {}
    for loc in re.findall(r"<loc>\s*([^<\s]+?/products/[^<\s]+?)\s*</loc>", xml, re.IGNORECASE):
        parsed = urlparse(loc)
        if _PRODUCT_PATH_RE.search(parsed.path) and not _SKIPPED_PRODUCT_RE.search(parsed.path):
            links.setdefault(parsed.path.rstrip("/"), f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
    return list(links.values())


async def find_product_links(page: Page) -> list[str]:
    """Home page, then Shopify's product feed, then the sitemap, then collection pages."""
    links = await _wait_for_home_links(page)
    if links:
        return links
    root = await _store_root(page)
    feed = await _fetch_json(page, f"{root}products.json?limit=50") or {}
    links = [
        urljoin(page.url, f"{root}products/{product['handle']}")
        for product in feed.get("products", [])
        if not _SKIPPED_PRODUCT_RE.search(product.get("handle", ""))
    ]
    if links:
        return links
    links = await _links_from_sitemap(page, root)
    if links:
        return links
    for path in (f"{root}collections/all", f"{root}collections"):
        try:
            await _open_fast(page, urljoin(page.url, path), _PRODUCT_LINK_SELECTOR, MAX_PRODUCTS_TO_TRY)
            await _check_page_state(page)
            links = await _links_on_page(page)
            if links:
                return links
        except Error:
            continue  # Try the next catalog path.
    return links


async def _products_from_origin(page: Page, url: str) -> list[str]:
    """Recover product links from the store's products.json over HTTPS.

    Some stores redirect their homepage (and even a browser navigation to
    products.json) to a non-Shopify splash on another host/scheme, while the Shopify
    store still answers products.json over HTTPS. Fetching it with the HTTP client
    (not a browser navigation) over both host variants avoids that redirect.
    """
    host = _base_host(urlparse(url).netloc)
    for netloc in (host, f"www.{host}"):
        endpoint = f"https://{netloc}/products.json?limit=50"
        try:
            response = await page.context.request.get(endpoint, timeout=NAV_TIMEOUT_MS)
            if not response.ok:
                continue
            data = await response.json()
        except Exception:
            continue
        products = data.get("products") if isinstance(data, dict) else None
        if products:
            origin = f"https://{netloc}"
            return [
                f"{origin}/products/{product['handle']}"
                for product in products
                if product.get("handle") and not _SKIPPED_PRODUCT_RE.search(product["handle"])
            ]
    return []


async def _cart_count(page: Page, root: str) -> int:
    return (await _fetch_json(page, f"{root}cart.js") or {}).get("item_count", 0)


async def _add_with_cart_api(page: Page, root: str) -> bool:
    """Add the first purchasable variant. This works whatever the store's theme is."""
    path = urlparse(page.url).path.rstrip("/")
    product = await _fetch_json(page, f"{path}.js")
    if not product or product.get("gift_card") or product.get("requires_selling_plan"):
        return False
    for variant in product.get("variants", []):
        if not variant.get("available") or variant.get("requires_selling_plan"):
            continue
        items = {"items": [{"id": variant["id"], "quantity": 1}]}
        if await _fetch_json(page, f"{root}cart/add.js", items) and await _cart_count(page, root) > 0:
            return True
    return False


async def _usable(locator) -> bool:
    try:
        return await locator.is_visible() and await locator.is_enabled()
    except Error:
        return False


async def _buy_now_candidates(page: Page) -> list:
    candidates = [page.locator(".shopify-payment-button__button--unbranded").first]
    for scope in (page.locator('form[action*="/cart/add"]'), page):
        buttons = scope.get_by_role("button", name=_BUY_NOW_TEXT_RE)
        candidates += [buttons.nth(i) for i in range(min(await buttons.count(), 10))]
    return candidates


async def _find_buy_now(page: Page):
    """Find a Buy Now button, skipping separate payment services.

    Those buttons often show only a logo, so their name is in `aria-label`.
    """
    for button in await _buy_now_candidates(page):
        if not await _usable(button):
            continue
        label = f"{await button.inner_text()} {await button.get_attribute('aria-label') or ''}"
        if not _PAYMENT_SERVICE_RE.search(label):
            return button
    return None


async def _find_add_button(page: Page):
    candidates = [page.locator(selector).first for selector in _BUTTON_SELECTORS]
    candidates.append(page.get_by_role("button", name=_ADD_BUTTON_TEXT_RE).first)
    for button in candidates:
        if await _usable(button):
            return button
    return None


async def _wait_for_button(page: Page, *finders: tuple) -> tuple[str, object] | None:
    """Return the first button that shows, as (method, button). Earlier finders win."""
    started = time.monotonic()
    while True:
        try:
            for method, find in finders:
                button = await find(page)
                if button is not None:
                    return method, button
            has_container = await page.locator(_BUY_NOW_CONTAINER).count() > 0
        except Error:
            has_container = False
        limit = BUY_NOW_WAIT_WITH_CONTAINER_S if has_container else BUY_NOW_WAIT_S
        if time.monotonic() - started >= limit:
            return None
        await page.wait_for_timeout(250)


async def _close_overlays(page: Page) -> None:
    try:
        await page.evaluate(_CLOSE_OVERLAYS_SCRIPT)
    except Error:
        pass  # The page was navigating, so there's nothing to close.


async def _click(page: Page, button) -> bool:
    """Close any popup in the page, then click. Try again if a popup appears first."""
    for _ in range(2):
        await _close_overlays(page)
        try:
            await button.click(timeout=CLICK_TIMEOUT_MS)
            return True
        except Error:
            try:
                await page.keyboard.press("Escape")
            except Error:
                pass
    return False


async def _find_checkout_button(page: Page):
    for role in ("button", "link"):
        options = page.get_by_role(role, name=_CHECKOUT_TEXT_RE)
        for index in range(min(await options.count(), 10)):
            if await _usable(options.nth(index)):
                return options.nth(index)
    return None


def _on_checkout(page: Page) -> bool:
    """True once the tab has redirected to a checkout (same tab, any host)."""
    return "/checkouts/" in page.url


async def _wait_for_checkout_url(page: Page, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _on_checkout(page):
            return True
        try:
            await _check_page_state(page)
        except Error:
            pass  # The page was navigating. Check again.
        await page.wait_for_timeout(200)
    return False


async def _use_buy_now(page: Page, root: str, button) -> bool:
    """Click Buy Now once. Return True if checkout opened or the cart has an item.

    A Buy click that navigates to the checkout makes button.click() raise (the page is
    gone), so we DON'T treat a failed click as failure -- we check the URL regardless.
    """
    await _click(page, button)
    # Some stores open a cart first, so look for its checkout button early.
    deadline = time.monotonic() + AFTER_CLICK_WAIT_S
    if await _wait_for_checkout_url(page, 3):
        return True
    try:
        checkout = await _find_checkout_button(page)
        if checkout is not None:
            await checkout.click(timeout=5_000)
    except Error:
        pass
    if await _wait_for_checkout_url(page, max(deadline - time.monotonic(), 1)):
        return True
    return await _cart_count(page, root) > 0


async def _add_with_button(page: Page, root: str, button) -> bool:
    """Click the store's add-to-cart button once.

    Some stores (e.g. Govee) redirect straight to a checkout on another host instead
    of filling a cart, so reaching a checkout counts as success too.
    """
    await _click(page, button)  # may raise internally if the click navigates; that's fine
    deadline = time.monotonic() + CART_UPDATE_WAIT_S  # short: Buy / permalink are tried next
    while time.monotonic() < deadline:
        if _on_checkout(page) or await _cart_count(page, root) > 0:
            return True
        # A cart drawer with a "Check Out" button means the add worked even when the
        # native /cart.js stays empty (custom/headless carts like typhur). open_checkout
        # then clicks that button.
        if await _find_checkout_button(page) is not None:
            return True
        await page.wait_for_timeout(250)
    return False


# Picks the first available option in each variant selector, so Add to Cart is enabled
# on products that require a size/colour choice first.
_SELECT_VARIANTS_SCRIPT = """() => {
    const form = document.querySelector('form[action*="/cart/add"]') || document;
    const unavailable = /unavailable|sold out|out of stock/i;
    for (const select of form.querySelectorAll('select')) {
        const option = [...select.options].find(
            o => o.value && !o.disabled && !unavailable.test(o.textContent)
        );
        if (option && select.value !== option.value) {
            select.value = option.value;
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
    const groups = {};
    for (const input of form.querySelectorAll('input[type=radio]')) {
        if (!input.disabled) (groups[input.name] = groups[input.name] || []).push(input);
    }
    for (const name in groups) {
        if (!groups[name].some(i => i.checked)) {
            const pick = groups[name][0];
            pick.checked = true;
            try { pick.click(); } catch (e) {}
            pick.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
}"""


async def _select_variants(page: Page) -> None:
    try:
        await page.evaluate(_SELECT_VARIANTS_SCRIPT)
        await page.wait_for_timeout(300)  # Let the theme re-enable the button.
    except Error:
        pass  # Best-effort; the add/cart-API paths still run.


async def _use_product_buttons(page: Page, root: str) -> str | None:
    """Try Add to Cart first, then Buy. Return the method that worked."""
    found = await _wait_for_button(page, ("button", _find_add_button), ("buy_now", _find_buy_now))
    if found is None:
        return None
    method, button = found
    if method == "button":
        if await _add_with_button(page, root, button):
            return method
        found = await _wait_for_button(page, ("buy_now", _find_buy_now))
        if found is None:
            return None
        method, button = found
    return method if await _use_buy_now(page, root, button) else None


async def _checkout_via_permalink(page: Page, root: str) -> str | None:
    """Add the first available variant via the cart permalink, which goes to checkout.

    `/<root>cart/<variant_id>:1` bypasses the variant-button UI entirely and, on stores
    like Govee, redirects straight to the checkout host -- which is all we need.
    """
    path = urlparse(page.url).path.rstrip("/")
    product = await _fetch_json(page, f"{path}.js")
    if not product or product.get("requires_selling_plan"):
        return None
    for variant in product.get("variants", []):
        if not variant.get("available") or variant.get("requires_selling_plan"):
            continue
        try:
            await page.goto(urljoin(page.url, f"{root}cart/{variant['id']}:1"), wait_until="commit")
        except Error:
            continue
        if await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S):
            return "permalink"
    return None


async def start_checkout(page: Page, links: list[str], result: SiteResult) -> str:
    """Add to Cart, then Buy, then the cart permalink, then the cart API. Return the base path."""
    for link in links[:MAX_PRODUCTS_TO_TRY]:
        try:
            await _open_fast(page, link, _PRODUCT_READY_SELECTOR)
        except Error:
            continue
        await _check_page_state(page)
        root = await _store_root(page)
        result.product_url = page.url
        await _select_variants(page)  # Enable Add to Cart on size/colour products.
        method = await _use_product_buttons(page, root)
        if method is not None:
            result.added_by = method
            return root
        # Variant picked by UI failed (e.g. Govee's custom buttons) -> add by permalink.
        method = await _checkout_via_permalink(page, root)
        if method is not None:
            result.added_by = method
            return root
        if await _add_with_cart_api(page, root):
            result.added_by = "cart_api"
            return root
    raise StopSite("could_not_add_to_cart", f"tried {min(len(links), MAX_PRODUCTS_TO_TRY)} products")


async def open_checkout(page: Page, root: str) -> bool:
    """Reach checkout, then return True if the page has its session data.

    Many themes open a side cart whose "Check Out" button is what reaches the real
    checkout, so that's tried first; otherwise fall back to navigating to /checkout.
    """
    if "/checkouts/" not in page.url:
        button = await _find_checkout_button(page)
        if button is not None:
            await _click(page, button)
            await _wait_for_checkout_url(page, AFTER_CLICK_WAIT_S)
        if "/checkouts/" not in page.url:
            try:
                await page.goto(urljoin(page.url, f"{root}checkout"), wait_until="domcontentloaded")
            except Error:
                pass
    deadline = time.monotonic() + CHECKOUT_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            await _check_page_state(page)
            if await page.locator('meta[name="serialized-sessionToken"]').count():
                return True
        except Error:
            pass  # The page was navigating. Check again.
        await page.wait_for_timeout(250)
    if "/checkouts/" in page.url:
        return False
    raise StopSite("checkout_not_reached", page.url)


async def _reach_checkout_with_buy(page: Page, root: str, result: SiteResult) -> bool:
    """Click Buy or Checkout on the page /checkout led to, then on the product page.

    Some stores only show their checkout button after Buy is clicked on an item
    that's already in the cart. Return True once the page is a checkout.
    """
    for url in ("", result.product_url):
        try:
            if url:
                await _open_fast(page, url, _PRODUCT_READY_SELECTOR)
                await _check_page_state(page)
            found = await _wait_for_button(
                page, ("buy_now", _find_buy_now), ("checkout", _find_checkout_button)
            )
            if found is None:
                continue
            method, button = found
            await _use_buy_now(page, root, button)  # Also clicks any checkout button it reveals.
        except Error:
            continue  # The page failed or navigated away. Try the next one.
        if "/checkouts/" in page.url:
            result.added_by += f"+{method}"
            return True
    return False


async def _open_checkout_any_way(page: Page, root: str, result: SiteResult) -> bool:
    """Reach a real Shopify /checkouts/ session by whatever path works.

    1. Normal /checkout (or a side-cart Check Out button, handled in open_checkout).
    2. Buy / Checkout buttons on the product or cart.
    3. The native cart permalink /cart/<variant>:1 -- a Shopify server route that works
       even for custom/headless storefronts (e.g. typhur) whose buttons go elsewhere.
    Returns True if the checkout exposes its session data.
    """
    try:
        return await open_checkout(page, root)
    except StopSite as stop:
        if stop.status != "checkout_not_reached":
            raise

    if await _reach_checkout_with_buy(page, root, result):
        try:
            return await open_checkout(page, root)
        except StopSite:
            pass

    if "/checkouts/" not in page.url and result.product_url:
        try:
            await _open_fast(page, result.product_url, _PRODUCT_READY_SELECTOR)
            if await _checkout_via_permalink(page, root):
                result.added_by = (result.added_by + "+permalink").lstrip("+")
                return await open_checkout(page, root)
        except (Error, StopSite):
            pass

    if "/checkouts/" in page.url:
        return False
    raise StopSite("checkout_not_reached", page.url)


async def _saved_html(page: Page) -> str:
    for _ in range(5):
        try:
            return await page.content()
        except Error:  # The page was navigating. Try again.
            await page.wait_for_timeout(1_000)
    return await page.content()


def _belongs_to_host(domain: str, host: str) -> bool:
    domain = domain.lstrip(".")
    return host == domain or host.endswith(f".{domain}")


async def _save_store_state(page: Page, path: Path) -> None:
    """Save only this store's data, because tabs for other stores share the browser.

    This has the format of context.storage_state(), which can't be used here: it opens
    a visible tab and visits every site this browser has seen, including ad hosts.
    """
    storage = await _read_page(
        page,
        """() => ({
            origin: location.origin,
            localStorage: Object.entries(localStorage).map(([name, value]) => ({name, value})),
        })""",
    )
    host = urlparse(storage["origin"]).hostname
    state = {
        "cookies": [c for c in await page.context.cookies() if _belongs_to_host(c["domain"], host)],
        "origins": [storage] if storage["localStorage"] else [],
    }
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


async def _prepare_for_next_store(page: Page, url: str) -> None:
    """Start with an empty cart even if this store has been visited before."""
    host = _base_host(urlparse(url).hostname or "")
    await page.context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(host)}$"))
    # A blank page stops anything the last store was still loading, which could
    # otherwise interrupt the next store's first page.
    for _ in range(3):
        try:
            await page.goto("about:blank")
            return
        except Error:
            await page.wait_for_timeout(500)


async def process_site(page: Page, site: str, out_dir: Path) -> SiteResult:
    result = SiteResult(site=site)
    started = time.monotonic()
    url = _site_url(site)
    try:
        await _prepare_for_next_store(page, url)
        await open_home_page(page, url)
        await _check_page_state(page)
        if await _is_shopify(page):
            links = await find_product_links(page)
        else:
            # Homepage redirected off to a non-Shopify splash; recover from the
            # original host's products.json, which a real Shopify store still answers.
            links = await _products_from_origin(page, url)
            if not links:
                raise StopSite("not_shopify", page.url)
        if not links:
            raise StopSite("no_products_found")
        root = await start_checkout(page, links, result)

        has_session_data = await _open_checkout_any_way(page, root, result)
        # Same-tab checkout redirect (e.g. us.govee.com -> store.govee.com) lands here,
        # so page.url is the real checkout host and the folder is named for it.
        result.checkout_url = page.url

        parsed = urlparse(page.url)
        store_dir = out_dir / parsed.netloc.replace(":", "_")
        store_dir.mkdir(parents=True, exist_ok=True)
        html = await _saved_html(page)
        (store_dir / "checkout.html").write_text(html, encoding="utf-8")
        # Holds this store's cookies, which a later Proposal request will need.
        await _save_store_state(page, store_dir / "storage_state.json")

        if not has_session_data:
            result.status = "checkout_without_session_data"
            return result
        try:
            payload = build_proposal_payload(html, None)
        except CheckoutParseError as error:
            result.status = "payload_failed"
            result.detail = str(error)
            return result
        (store_dir / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result.status = "ok"
    except StopSite as stop:
        result.status = stop.status
        result.detail = stop.detail
    except Error as error:
        result.status = "browser_error"
        result.detail = str(error).splitlines()[0][:200]
    finally:
        result.seconds = round(time.monotonic() - started, 1)
    return result


async def _block_slow_requests(route: Route) -> None:
    request = route.request
    try:
        if request.resource_type in _BLOCKED_RESOURCE_TYPES or _BLOCKED_HOST_RE.search(
            urlparse(request.url).hostname or ""
        ):
            await route.abort()
        else:
            await route.continue_()
    except Error:
        pass  # The page closed or moved on, so the request no longer matters.


class WorkerTabs:
    """Opens the worker tabs, and closes every other tab the browser opens."""

    def __init__(self, context: BrowserContext) -> None:
        self.context = context
        self._tabs: set[Page] = set()
        # The browser reports a new tab before new_page() returns it, so this makes
        # the closer wait until a worker's own tab has been recorded.
        self._opening = asyncio.Lock()
        context.on("page", lambda page: asyncio.ensure_future(self._close_if_extra(page)))

    async def open(self) -> Page:
        async with self._opening:
            page = await self.context.new_page()
            self._tabs.add(page)
        return page

    async def _close_if_extra(self, page: Page) -> None:
        async with self._opening:
            pass
        if page not in self._tabs:
            try:
                await page.close(run_before_unload=False)
            except Error:
                pass

    def _is_extra_tab(self, request: Request) -> bool:
        try:
            return request.frame.page not in self._tabs
        except Error:  # A page load with no frame yet is a new tab starting up.
            return True

    async def block_unwanted_pages(self, route: Route) -> None:
        request = route.request
        try:
            if not request.is_navigation_request():
                await route.fallback()
            elif self._is_extra_tab(request):
                # Answer with an empty page, so nothing reaches the real server. Don't
                # abort here: Playwright only reports a new tab once its first page
                # loads, so an aborted one would stay open and never reach the closer.
                await route.fulfill(status=200, content_type="text/html", body="")
            elif _JUNK_PAGE_HOST_RE.search(urlparse(request.url).hostname or ""):
                # "aborted" keeps the current page. Other errors replace it with an error page.
                await route.abort("aborted")
            else:
                await route.fallback()
        except Error:
            pass  # The page closed or moved on, so the request no longer matters.


async def launch_browser(playwright: Playwright, *, headless: bool = False) -> Browser:
    args = _STEALTH_ARGS
    try:  # Real installed Chrome is trusted more than bundled Chromium.
        return await playwright.chromium.launch(
            headless=headless, channel="chrome", args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
        )
    except Error:
        return await playwright.chromium.launch(
            headless=headless, args=args, ignore_default_args=_KEEP_POPUP_BLOCKER
        )


async def open_context(browser: Browser, *, block_slow_requests: bool = True) -> WorkerTabs:
    """Open the one window that every store shares."""
    context = await browser.new_context(
        user_agent=_USER_AGENT,
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1366, "height": 768},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    context.set_default_timeout(NAV_TIMEOUT_MS)
    context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    await context.add_init_script(_STEALTH_SCRIPT)
    await context.add_init_script(_NO_POPUPS_SCRIPT)
    if block_slow_requests:
        await context.route("**/*", _block_slow_requests)
    tabs = WorkerTabs(context)
    # The newest route runs first, then falls back to the one above.
    await context.route("**/*", tabs.block_unwanted_pages)
    return tabs


def read_sites(path: Path) -> list[str]:
    """Read the list, dropping stores that appear twice in different forms."""
    sites: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        site = line.strip()
        if not site or site.startswith("#"):
            continue
        parsed = urlparse(_site_url(site))
        key = f"{_base_host(parsed.netloc.lower())}{parsed.path.rstrip('/')}"
        sites.setdefault(key, site)
    return list(sites.values())


def sites_to_retry(results: list[SiteResult]) -> list[str]:
    retryable = ("dns_error", "browser_error", "timed_out")
    return [r.site for r in results if r.status in retryable]


async def _worker(tabs: WorkerTabs, sites: asyncio.Queue, out_dir: Path, report) -> None:
    page = await tabs.open()
    while not sites.empty():
        site = sites.get_nowait()
        if page.is_closed():
            try:
                page = await tabs.open()
            except Error:
                report(SiteResult(site=site, status="browser_error", detail="the browser was closed"))
                continue
        try:
            result = await asyncio.wait_for(process_site(page, site, out_dir), SITE_TIMEOUT_S)
        except asyncio.TimeoutError:
            result = SiteResult(site=site, status="timed_out", seconds=SITE_TIMEOUT_S)
        report(result)
    if not page.is_closed():
        await page.close(run_before_unload=False)


async def run(
    sites: list[str],
    out_dir: Path,
    *,
    workers: int = DEFAULT_WORKERS,
    block_slow_requests: bool = True,
    headless: bool = False,
) -> list[SiteResult]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[SiteResult] = []
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(SiteResult.__dataclass_fields__))
        writer.writeheader()

        def report(result: SiteResult) -> None:
            results.append(result)
            writer.writerow(asdict(result))
            csv_file.flush()  # Keep finished rows if a long run is interrupted.
            print(f"[{len(results)}/{len(sites)}] {result.status:30} {result.seconds:6.1f}s  {result.site}  {result.detail}")

        queue: asyncio.Queue = asyncio.Queue()
        for site in sites:
            queue.put_nowait(site)
        async with async_playwright() as playwright:
            browser = await launch_browser(playwright, headless=headless)
            tabs = await open_context(browser, block_slow_requests=block_slow_requests)
            await asyncio.gather(
                *(_worker(tabs, queue, out_dir, report) for _ in range(min(workers, len(sites)) or 1))
            )
            await browser.close()
    retry = sites_to_retry(results)
    if retry:
        (out_dir / RETRY_FILE_NAME).write_text("\n".join(retry) + "\n", encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sites", type=Path, help="text file with one store per line")
    parser.add_argument("--out", type=Path, default=Path("checkouts"), help="output folder")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="how many stores to run at once"
    )
    parser.add_argument(
        "--load-everything",
        action="store_true",
        help="also load images, fonts and trackers, in case blocking them breaks a store",
    )
    args = parser.parse_args()
    started = time.monotonic()
    results = asyncio.run(
        run(
            read_sites(args.sites),
            args.out,
            workers=args.workers,
            block_slow_requests=not args.load_everything,
        )
    )
    done = sum(result.status == "ok" for result in results)
    minutes = (time.monotonic() - started) / 60
    print(f"\n{done} of {len(results)} stores reached checkout in {minutes:.1f} minutes.")
    print(f"See {args.out / 'results.csv'}")
    retry = sites_to_retry(results)
    if retry:
        print(f"{len(retry)} stores had connection errors or timeouts. See {args.out / RETRY_FILE_NAME}")


if __name__ == "__main__":
    main()