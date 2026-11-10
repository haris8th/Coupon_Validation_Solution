"""Build a Shopify checkout `Proposal` payload by matching a template to the page.

The template is a captured payload. It decides which fields get sent, and the
page decides their values. Each field is looked up by name in the JSON held in
the page's `<meta>` tags, so these changes need no code:

- a new field in the payload, if the page has a field of the same name
- a field moving deeper inside the same parent object
- different query hashes, currencies, countries, line counts or shipping handles

A field that can't be found keeps its template value and is listed in the report
from `build_proposal_payload_with_report`, so a guess is never silent.

Standard library only.
"""
from __future__ import annotations

import copy
import json
import re
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any, Iterable, Iterator

_MISSING = object()
_HANDLE = r"[0-9a-f]{32}-[0-9a-f]{32}"
_HANDLE_RE = re.compile(_HANDLE)
_PROPOSAL_KEY_RE = re.compile(r"proposal(?:_?v?\d+)?$", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_PRICE_RE = re.compile(r"\d[\d.,]*")
_FREE_RE = re.compile(r"\bfree\b", re.IGNORECASE)

# Payload fields whose name differs from the page's. Keys are "field" or
# "parent/field". A dot walks into an object, and "^" searches from the top of the
# proposal. If Shopify renames a field, this table is the place to add it.
ALIASES: dict[str, tuple[str, ...]] = {
    "discounts": ("merchandiseDiscount",),
    "taxes": ("tax",),
    "proposedTotalAmount": ("totalTaxAmount",),
    "expectedTotalPrice": ("totalAmount",),
    "targetMerchandiseLines": ("^merchandise",),
    "targetMerchandiseLines/lines": ("merchandiseLines",),
    "sellingPlanId": ("sellingPlan.id",),
    "sellingPlanDigest": ("sellingPlan.digest",),
}

# Names too common to search for at depth, because a match could be the wrong data.
_NOT_SEARCHED_DEEP = {"value", "amount", "items", "lines", "fields", "id"}

# Values that describe the buyer as a whole, wherever they appear in the payload.
_CUSTOMER_FIELDS = {
    "countryCode": "countryCode",
    "phoneCountryCode": "countryCode",
    "currencyCode": "presentmentCurrency",
}

# Used when no captured payload is given. This is the shortest field set that gave
# the expected response when tested on store.govee.com. Blank values come from the page.
DEFAULT_TEMPLATE: dict[str, Any] = {
    "variables": {
        "sessionInput": {"sessionToken": ""},
        "queueToken": "",
        "merchandise": {
            "merchandiseLines": [
                {
                    "stableId": "",
                    "merchandise": {
                        "productVariantReference": {
                            "id": "",
                            "variantId": "",
                            "properties": [],
                            "sellingPlanId": None,
                            "sellingPlanDigest": None,
                        }
                    },
                    "quantity": {"items": {"value": 1}},
                    "expectedTotalPrice": {
                        "value": {"amount": "", "currencyCode": ""}
                    },
                    "lineComponentsSource": None,
                    "lineComponents": [],
                }
            ]
        },
        "reduction": {"code": ""},
    },
    "operationName": "Proposal",
    # Hash of the query in Shopify's JS bundle. It isn't in the page's HTML and can
    # change when Shopify deploys, so override it with `operation_id` when it does.
    "id": "bc8a42c54dc744e251af71d9e095a9bcf5c87218256e2bbf07059b0a586bdef0",
}


class CheckoutParseError(ValueError):
    """The HTML is missing data needed to build the payload."""


@dataclass(frozen=True)
class DeliveryOption:
    handle: str
    amount: str


@dataclass(frozen=True)
class CheckoutPage:
    meta: dict[str, Any]
    negotiation: dict[str, Any]
    proposals: list[dict[str, Any]]
    delivery_options: list[DeliveryOption] = field(default_factory=list)


@dataclass
class PayloadReport:
    """Where each payload field came from. Paths are relative to `variables`."""

    from_page: list[str] = field(default_factory=list)
    from_template: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _MetaCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, Any] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        values = dict(attrs)
        name, content = values.get("name"), values.get("content")
        if not name or content is None:
            return
        try:
            decoded: Any = json.loads(content)
        except ValueError:
            decoded = content
        self.meta[name.removeprefix("serialized-")] = decoded


def _walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict under `value`, shallowest first."""
    queue = deque([value])
    while queue:
        node = queue.popleft()
        if isinstance(node, dict):
            yield node
            queue.extend(node.values())
        elif isinstance(node, list):
            queue.extend(node)


def _strip_typename(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_typename(v) for k, v in value.items() if k != "__typename"}
    if isinstance(value, list):
        return [_strip_typename(v) for v in value]
    return value


def _amount(value: Any) -> str:
    return f"{Decimal(str(value)):.2f}"


def _parse_price(text: str) -> str | None:
    match = _PRICE_RE.search(text)
    if not match:
        return "0.00" if _FREE_RE.search(text) else None
    number = match.group().rstrip(".,")
    separators = [c for c in number if c in ".,"]
    if not separators:
        return _amount(number)
    last = separators[-1]
    decimals = number.rsplit(last, 1)[1]
    # A single separator before exactly three digits groups thousands: "1,000".
    if len(separators) == 1 and len(decimals) == 3:
        return _amount(number.replace(last, ""))
    whole = number.rsplit(last, 1)[0].replace(".", "").replace(",", "")
    return _amount(f"{whole}.{decimals}")


def _delivery_options(page_html: str) -> list[DeliveryOption]:
    """Read shipping options from rendered markup, matching on the handle's shape."""
    last_seen: dict[str, int] = {}
    for match in re.finditer(rf'(?:id|value|for)="[^"]*?({_HANDLE})[^"]*"', page_html):
        last_seen[match.group(1)] = match.end()

    options = []
    for handle, end in last_seen.items():
        # The price sits right after the handle, so a short window can't reach
        # the next option or the order summary.
        tail = page_html[end:end + 600]
        closing = tail.find("</strong>")
        snippet = tail[: closing if closing != -1 else 200]
        amount = _parse_price(_TAG_RE.sub(" ", "<" + snippet))
        if amount is not None:
            options.append(DeliveryOption(handle, amount))
    return options


def parse_checkout_html(page_html: str) -> CheckoutPage:
    collector = _MetaCollector()
    collector.feed(page_html)

    negotiation = None
    for node in _walk_dicts(collector.meta):
        if any(
            _PROPOSAL_KEY_RE.search(k) and isinstance(v, dict) and v
            for k, v in node.items()
        ):
            negotiation = node
            break
    if negotiation is None:
        raise CheckoutParseError("No buyer or seller proposal in the page's meta tags")

    # Buyer values first: they're what this checkout has actually selected.
    proposal_keys = sorted(
        (k for k, v in negotiation.items()
         if _PROPOSAL_KEY_RE.search(k) and isinstance(v, dict)),
        key=lambda k: (not k.lower().startswith("buyer"), k),
    )
    return CheckoutPage(
        meta=collector.meta,
        negotiation=negotiation,
        proposals=[negotiation[k] for k in proposal_keys],
        delivery_options=_delivery_options(page_html),
    )


class _TemplateFiller:
    def __init__(
        self,
        page: CheckoutPage,
        report: PayloadReport,
        *,
        queue_token: str | None,
        delivery_handle: str | None,
        delivery_amount: str | None,
        expectation_handles: list[str],
    ) -> None:
        self.report = report
        self.queue_token = queue_token
        self.delivery_handle = delivery_handle
        self.delivery_amount = delivery_amount
        self.expectation_handles = expectation_handles
        self.proposals = page.proposals
        self.root = [*page.proposals, page.negotiation, page.meta]
        self.customer = next(
            (d for d in _walk_dicts(page.proposals) if "presentmentCurrency" in d), {}
        )

    def fill(self, template: dict[str, Any], scope: list[dict], path: str = "") -> dict:
        return {
            key: self._field(key, value, scope, f"{path}/{key}")
            for key, value in template.items()
        }

    def _field(self, key: str, template: Any, scope: list[dict], path: str) -> Any:
        forced = self._forced(key, template, path)
        if forced is not _MISSING:
            self.report.from_page.append(path)
            return forced
        if isinstance(template, dict):
            children = [h for h in self._find(key, True, scope, path)
                        if isinstance(h, dict) and h]
            # No match keeps the scope, for wrappers like `sessionInput`.
            return self.fill(template, children or scope, path)
        if isinstance(template, list):
            return self._list(key, template, scope, path)
        return self._leaf(key, template, scope, path)

    def _forced(self, key: str, template: Any, path: str) -> Any:
        if key == "queueToken" and self.queue_token:
            return self.queue_token
        if key == "deliveryExpectationLines":
            # Signed and tied to one session, so a captured value is never reusable.
            return [{"signedHandle": h} for h in self.expectation_handles]
        is_handle = isinstance(template, str) and _HANDLE_RE.fullmatch(template)
        if self.delivery_handle and (
            is_handle or path.endswith("/deliveryStrategyByHandle/handle")
        ):
            return self.delivery_handle
        if self.delivery_amount and re.search(
            r"/deliveryLines\[\d+\]/expectedTotalPrice/value/amount$", path
        ):
            return _amount(self.delivery_amount)
        return _MISSING

    def _names(self, key: str, path: str) -> list[str]:
        parent = re.sub(r"\[\d+\]$", "", path.rsplit("/", 2)[-2]) if path.count("/") > 1 else ""
        return [key, *ALIASES.get(f"{parent}/{key}", ()), *ALIASES.get(key, ())]

    def _find(self, key: str, container: bool, scope: list[dict], path: str) -> list[Any]:
        for name in self._names(key, path):
            hits = []
            sources = self.root if name.startswith("^") else scope
            steps = name.removeprefix("^").split(".")
            for source in sources:
                node: Any = source
                for step in steps:
                    if node is None:  # A null parent means its children are null too.
                        break
                    node = node.get(step, _MISSING) if isinstance(node, dict) else _MISSING
                if node is not _MISSING:
                    hits.append(node)
            if hits:
                return hits
        # A field may have moved deeper. Only objects and lists are searched this
        # way, since a loose match on a name like `amount` could send a wrong price.
        if container and scope is not self.root and key not in _NOT_SEARCHED_DEEP:
            for source in scope:
                for name in self._names(key, path):
                    for node in _walk_dicts(source):
                        if name in node:
                            return [node[name]]
        return []

    def _list(self, key: str, template: list, scope: list[dict], path: str) -> list:
        lists = [h for h in self._find(key, True, scope, path) if isinstance(h, list)]
        item = template[0] if template else None
        if not lists:
            self.report.from_template.append(path)
            return [
                self.fill(entry, [], f"{path}[{i}]") if isinstance(entry, dict) else entry
                for i, entry in enumerate(template)
            ]
        source = next((entries for entries in lists if entries), [])
        if source:
            self.report.from_page.append(path)
            return [
                self.fill(item, [entry], f"{path}[{i}]")
                if isinstance(item, dict) and isinstance(entry, dict)
                else _strip_typename(entry)
                for i, entry in enumerate(source)
            ]
        # On first load the page has no delivery lines, but the request still needs one.
        if key == "deliveryLines" and isinstance(item, dict):
            return [self.fill(item, [], f"{path}[0]")]
        self.report.from_page.append(path)
        return []

    def _leaf(self, key: str, template: Any, scope: list[dict], path: str) -> Any:
        hits = self._find(key, template is None, scope, path)
        if template is not None:
            hits = [h for h in hits if not isinstance(h, (dict, list))]
        value = next((h for h in hits if h is not None), None)
        customer_key = _CUSTOMER_FIELDS.get(key)
        if value is None and customer_key and self.customer.get(customer_key):
            self.report.from_page.append(path)
            return self.customer[customer_key]
        if hits:
            # A null on the page also clears a stale value from a captured template.
            self.report.from_page.append(path)
            return self._convert(key, value, template)
        self.report.from_template.append(path)
        return copy.deepcopy(template)

    @staticmethod
    def _convert(key: str, value: Any, template: Any) -> Any:
        if value == "" and template is None:
            return None
        if key == "amount" and isinstance(value, (str, int, float)):
            amount = Decimal(str(value))
            # Taxes are sent as "0" while other amounts are sent as "50.00".
            if amount.is_zero() and isinstance(template, str) and template == "0":
                return "0"
            return _amount(amount)
        return _strip_typename(value)


def _load_template(template: dict[str, Any] | str | None) -> dict[str, Any]:
    if template is None:
        return copy.deepcopy(DEFAULT_TEMPLATE)
    loaded = json.loads(template) if isinstance(template, str) else copy.deepcopy(template)
    if not isinstance(loaded.get("variables"), dict):
        raise CheckoutParseError("The template has no `variables` object")
    return loaded


def build_proposal_payload_with_report(
    page_html: str,
    discount_code: str | None,
    *,
    template: dict[str, Any] | str | None = None,
    queue_token: str | None = None,
    delivery_handle: str | None = None,
    delivery_amount: str | None = None,
    delivery_expectation_handles: Iterable[str] = (),
    operation_id: str | None = None,
) -> tuple[dict[str, Any], PayloadReport]:
    """Return the JSON body for the request and a report of where values came from.

    `template` is a payload captured from any checkout, as a dict or JSON string.
    Its fields decide what gets sent, and its session values are replaced.
    `queue_token` is the one from the latest Proposal response, for follow-ups.
    Pass `delivery_handle` and `delivery_amount` if the HTML has no rendered
    shipping options, or to choose an option other than the first.
    """
    page = parse_checkout_html(page_html)
    payload = _load_template(template)
    report = PayloadReport()

    shipping_required = next(
        (p["isShippingRequired"] for p in page.proposals if "isShippingRequired" in p),
        True,
    )
    if delivery_handle is None and page.delivery_options:
        chosen = page.delivery_options[0]
        delivery_handle = chosen.handle
        if delivery_amount is None:
            delivery_amount = chosen.amount
        if len(page.delivery_options) > 1 and any(
            "deliveryStrategyByHandle" in node for node in _walk_dicts(payload["variables"])
        ):
            report.warnings.append(
                f"{len(page.delivery_options)} shipping options on the page; used the first"
            )
    # Only a template that selects a specific shipping option needs these values.
    selects_option = any(
        "deliveryStrategyByHandle" in node for node in _walk_dicts(payload["variables"])
    )
    if (
        selects_option
        and shipping_required
        and (delivery_handle is None or delivery_amount is None)
    ):
        raise CheckoutParseError(
            "No shipping option in the HTML. Pass delivery_handle and "
            "delivery_amount from a previous Proposal response."
        )

    variables = payload["variables"]
    variables.pop("reduction", None)
    filler = _TemplateFiller(
        page,
        report,
        queue_token=queue_token,
        delivery_handle=delivery_handle,
        delivery_amount=delivery_amount,
        expectation_handles=list(delivery_expectation_handles),
    )
    filled = filler.fill(variables, filler.root)

    for name in ("sessionToken", "queueToken", "merchandiseLines"):
        if any(p.endswith(f"/{name}") for p in report.from_template):
            raise CheckoutParseError(f"Could not find `{name}` in the page's meta tags")

    delivery = filled.get("delivery")
    if not shipping_required and isinstance(delivery, dict):
        delivery["deliveryLines"] = []
        report.warnings.append(
            "This checkout needs no shipping, so deliveryLines is empty. "
            "noDeliveryRequired is unconfirmed: compare it with a captured request."
        )
    if discount_code:
        filled["reduction"] = {"code": discount_code}

    payload["variables"] = filled
    if operation_id:
        payload["id"] = operation_id
    return payload, report


def build_proposal_payload(
    page_html: str, discount_code: str | None, **options: Any
) -> dict[str, Any]:
    """Same as `build_proposal_payload_with_report`, without the report."""
    return build_proposal_payload_with_report(page_html, discount_code, **options)[0]
