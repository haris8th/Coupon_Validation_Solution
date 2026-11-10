# Shopify discount code validator

Checks whether discount codes still work on Shopify stores, without placing an order.

For each store it opens a real checkout once in a browser, saves the request the
checkout page sends to Shopify (the `Proposal` payload), then replays that request
with each code swapped in. Shopify's response says whether the code applied.

It stops at the checkout page: it never enters customer details or pays. It does not
try to get past logins, captchas or queues, and reports them instead.

## Setup

Python 3.10 or newer.

```bash
pip install -U playwright requests
```

```bash
playwright install chromium
```

If Google Chrome is installed it is used in preference to the bundled Chromium.

## Quick start

```bash
python validate_codes.py codes.csv
```

This is the only command most runs need. It captures any checkout it doesn't already
have, validates every code, and writes `validation/validated.csv`.

## The scripts

| File | What it does |
| --- | --- |
| `validate_codes.py` | The main entry point. Reads a sheet of codes, validates each one, writes the results. |
| `shopify_checkout.py` | Opens a store, adds a product to the cart, reaches checkout and saves the page, cookies and payload. Used by the validator, and runnable on its own. |
| `shopify_proposal.py` | Builds the `Proposal` payload from a saved checkout page. A library with no command line; standard library only. |

## validate_codes.py

```bash
python validate_codes.py codes.csv --checkouts checkouts --out validation
```

### Input sheet

A CSV or TSV (the delimiter is detected). Header names are matched without regard to
case, and extra columns are ignored.

| Column | Accepted headers | Required |
| --- | --- | --- |
| Store | `Homepage`, `Website`, `URL`, `Store`, `Site`, `Domain`, `Home page` | yes |
| Code | `Code`, `Coupon`, `Coupon code`, `Discount code`, `Promo code`, `Voucher`, `Codes` | yes |
| Brand | `Brand`, `Brand name`, `Merchant`, `Store name` | no |
| Region | `Region`, `Country`, `Geo`, `Locale` | no |

Rows missing a store or a code are skipped.

```csv
Brand,Homepage,Region,Code
Example Brand,https://www.example.com,us,SAVE10
Example Brand,https://www.example.com,us,WELCOME15
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `sheet` | required | The CSV/TSV of codes. |
| `--checkouts` | `checkouts` | Folder where store payloads are saved and looked up. |
| `--out` | `validation` | Output folder. |
| `--workers` | `3` | Stores processed at once. Each worker has its own browser. |
| `--no-capture` | off | Only use saved payloads. Never opens a browser. |
| `--show-browser` | off | Capture in a visible browser window instead of headless. |
| `--log` | `<out>/validation_log.txt` | Log file. Each run is appended. |

### How a store is handled

1. Codes are grouped by store. One worker handles a store from start to finish, so a
   store never receives several requests at once. Different stores run in parallel.
2. If `checkouts/<checkout-host>/payload.json` exists, it is reused and no browser opens.
3. If there is no saved payload, the checkout is captured in a browser first.
4. Each code is put into `variables.reduction.code` and POSTed to
   `/checkouts/internal/graphql/persisted?operationName=Proposal` with the saved cookies.
5. If the response shows the saved session is dead (HTTP 401/403/419/429, a non-JSON
   page, or a throttle/captcha/unauthorized message), the checkout is captured again,
   once per store, and the code is retried.

### Verdicts

| `status` | `valid` | Meaning |
| --- | --- | --- |
| `valid` | `yes` | The response contains `DiscountCodeTrigger`: the discount applied. |
| `invalid` | `no` | The response carries an explicit rejection marker (such as `REDUCTION_..._INVALID` or `DISCOUNT_CODE_NOT_FOUND`), or is a clean response with no trigger. |
| `error` | blank | The request failed, or the response was not JSON, even after a re-capture. |
| `no_payload` | blank | The store's checkout could not be captured. `reason` gives the capture status. |

A code that is real but doesn't apply to the one product in the test cart (wrong
collection, minimum spend not met) is reported as `invalid`.

### Output

```
validation/
  validated.csv               one row per code
  validation_log.txt          timestamped console output, appended each run
  responses/<domain>/<code>.json   the raw response for every code
```

`validated.csv` columns: `Brand`, `Homepage`, `Region`, `Code`, `valid`, `status`,
`reason`, `domain`, `response_file`. Rows keep the order of the input sheet.

## shopify_checkout.py

Captures checkouts without validating anything. Useful for preparing payloads ahead
of time, or for seeing why a store fails.

```bash
python shopify_checkout.py sites.txt
```

`sites.txt` has one store per line, with or without `https://`. Blank lines and lines
starting with `#` are ignored, and the same store written two ways is run once.

| Option | Default | Meaning |
| --- | --- | --- |
| `sites` | required | Text file with one store per line. |
| `--out` | `checkouts` | Output folder. |
| `--workers` | `3` | Stores to run at once, one tab each. |
| `--load-everything` | off | Also load images, fonts and trackers, in case blocking them breaks a store. |

Run this way, the browser window is visible and all stores share it.

### What it does per store

1. Opens the home page, retrying temporary DNS failures and then the other
   `www`/non-`www` form.
2. Finds product links: the home page, then `products.json`, then the product sitemap,
   then the collection pages. Gift cards, samples and warranties are skipped.
3. Adds a product to the cart, trying up to three products: the Add to Cart button,
   then Buy Now, then the cart permalink (`/cart/<variant>:1`), then the cart API.
4. Reaches checkout through the cart's Check Out button, `/checkout`, a Buy/Checkout
   button, or the cart permalink.
5. Saves the checkout page, the store's cookies and the built payload.

### Output

```
checkouts/
  results.csv                 one row per store
  retry_sites.txt             stores worth running again (only if there are any)
  _homepage_map.json          homepage -> checkout URL, written by validate_codes.py
  <checkout-host>/
    checkout.html             the saved checkout page
    storage_state.json        this store's cookies and localStorage
    payload.json              the Proposal payload, without a discount code
```

The folder is named after the host the checkout ends up on, which can differ from the
homepage (for example `us.govee.com` checks out on `store.govee.com`).

`results.csv` columns: `site`, `status`, `product_url`, `checkout_url`, `added_by`,
`seconds`, `detail`.

### Statuses

| Status | Meaning |
| --- | --- |
| `ok` | Checkout reached and `payload.json` written. |
| `not_shopify` | The site is not a Shopify store. |
| `no_products_found` | No product links could be found. |
| `could_not_add_to_cart` | None of the products tried could be added. |
| `checkout_not_reached` | A product was added but no checkout page opened. |
| `checkout_without_session_data` | Checkout opened but did not expose its session token. |
| `payload_failed` | The checkout page lacked data the payload needs. `detail` says what. |
| `password_protected` | The store is behind a password page. |
| `login_required` | The store requires an account to check out. |
| `in_queue` | The store put the visit in a queue or throttled it. |
| `blocked` | A captcha or bot challenge appeared. |
| `dns_error` | The domain could not be looked up. |
| `browser_error` | The browser reported an error. `detail` has the first line. |
| `timed_out` | The store took longer than 160 seconds. |

The last three are written to `retry_sites.txt`, which can be passed straight back in:

```bash
python shopify_checkout.py checkouts/retry_sites.txt
```

## shopify_proposal.py

Turns a saved checkout page into the JSON body of a `Proposal` request.

```python
from shopify_proposal import build_proposal_payload_with_report

html = open("checkouts/store.example.com/checkout.html", encoding="utf-8").read()
payload, report = build_proposal_payload_with_report(html, "SAVE10")
```

A template (a captured payload) decides which fields are sent, and the page decides
their values. Each field is looked up by name in the JSON held in the page's `<meta>`
tags, so new fields, moved fields and different currencies, countries or line counts
need no code change. A field that can't be found keeps its template value and is
listed in `report.from_template`, so a guess is never silent.

Keyword options: `template`, `queue_token`, `delivery_handle`, `delivery_amount`,
`delivery_expectation_handles`, `operation_id`.

If Shopify renames a field, add it to the `ALIASES` table. If Shopify changes the
query hash, pass the new one as `operation_id` or update `DEFAULT_TEMPLATE["id"]`.

`CheckoutParseError` is raised when the page has no proposal, session token, queue
token or merchandise lines.

## Notes

- Saved sessions expire. The validator re-captures a dead one by itself unless
  `--no-capture` is set.
- `checkouts/` and `validation/` are in `.gitignore`. They hold session cookies, so
  don't share them.
- Timeouts, worker counts and the pause between requests are constants at the top of
  `validate_codes.py` and `shopify_checkout.py`.
