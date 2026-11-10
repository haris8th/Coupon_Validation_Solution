"""CSV / JSON helpers shared by the API and CLI."""
from __future__ import annotations

import csv
import io
import json
from typing import Iterable

URL_COLUMNS = ("url", "domain", "website", "site", "store", "store_url", "shop")
CSV_FIELDS = ("url", "domain", "platform", "confidence", "reason", "final_url", "checked_at", "stages", "evidence")


def read_urls_from_csv(text: str) -> list[str]:
    """Read URLs from a CSV. Uses a url/domain-like column if present, else column 1.

    A first row that already looks like a domain is treated as data, not a header.
    """
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if r and any(c.strip() for c in r)]
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    col = next((header.index(c) for c in URL_COLUMNS if c in header), None)
    if col is None:
        col, body = 0, (rows if "." in rows[0][0] else rows[1:])
    else:
        body = rows[1:]
    seen: set[str] = set()
    out: list[str] = []
    for r in body:
        if col < len(r):
            u = r[col].strip()
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return out


def results_to_csv(results: Iterable[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in results:
        row = dict(r)
        row["stages"] = "+".join(r.get("stages", []))
        row["evidence"] = " | ".join(r.get("evidence", []))
        w.writerow(row)
    return buf.getvalue()


def parse_json_urls(raw: bytes) -> list[str]:
    try:
        data = json.loads(raw or b"null")
    except ValueError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    if isinstance(data, dict):
        data = data.get("urls") or data.get("domains") or []
    if not isinstance(data, list):
        raise ValueError('expected a JSON list of URLs or {"urls": [...]}')
    return [str(u).strip() for u in data if str(u).strip()]
