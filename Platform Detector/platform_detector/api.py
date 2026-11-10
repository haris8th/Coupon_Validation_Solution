"""FastAPI app: GET /detect?url=  and  POST /detect/batch (JSON or CSV upload)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .detector import Detector, Settings
from .io_utils import parse_json_urls, read_urls_from_csv, results_to_csv

MAX_BATCH = 5000


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "detector", None) is None:  # tests may inject one
        app.state.detector = Detector(Settings())
    yield
    await app.state.detector.aclose()


app = FastAPI(title="Platform Detector", version="1.0.0", lifespan=lifespan)


def _det(request: Request) -> Detector:
    return request.app.state.detector


@app.get("/health")
async def health(request: Request):
    return {"ok": True, "cached_domains": len(_det(request).cache)}


@app.get("/detect")
async def detect(request: Request, url: str = Query(..., description="Domain or URL"),
                 refresh: bool = False, browser: Optional[bool] = None):
    res = await _det(request).detect(url, refresh=refresh, use_browser=browser)
    return res.to_dict()


@app.post("/detect/batch")
async def detect_batch(request: Request, refresh: bool = False, browser: Optional[bool] = None,
                       format: str = Query("json", pattern="^(json|csv)$")):
    """Body: JSON list / {"urls": [...]}, raw text/csv, or multipart upload with a `file` field.

    Add ?format=csv to get CSV back instead of JSON.
    """
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise ValueError("multipart upload needs a 'file' field")
            urls = read_urls_from_csv((await upload.read()).decode("utf-8", errors="replace"))
        elif "csv" in ctype or ctype.startswith("text/plain"):
            urls = read_urls_from_csv((await request.body()).decode("utf-8", errors="replace"))
        else:
            urls = parse_json_urls(await request.body())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not urls:
        raise HTTPException(400, "no URLs found")
    if len(urls) > MAX_BATCH:
        raise HTTPException(413, f"batch limited to {MAX_BATCH} URLs")
    results = [r.to_dict() for r in await _det(request).detect_many(urls, refresh=refresh, use_browser=browser)]
    if format == "csv":
        return PlainTextResponse(results_to_csv(results), media_type="text/csv")
    return results
