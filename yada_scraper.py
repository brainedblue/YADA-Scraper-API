# fastapi scraper endpoints

import asyncio
import sys
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# fix for windows async stuff
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from scraper import ScraperEngine



app = FastAPI(
    title="Web Scraper",
    description="Multi-layer web scraper with anti-detection and smart fallback",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ScraperEngine()



class BulkRequest(BaseModel):
    urls: list[str]
    mode: str = "auto"
    extract: bool = True


class BulkResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[dict]




@app.get("/scrape")
async def do_scrape(
    url: str = Query(..., description="URL to scrape"),
    mode: str = Query("auto", description="auto / static / browser"),
    extract: bool = Query(True, description="extract content or return raw html"),
):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = await engine.scrape(url=url, mode=mode, extract=extract)
    return result.to_dict()


@app.get("/scrape/compare")
async def do_compare(
    url: str = Query(..., description="URL to compare all layers on"),
    extract: bool = Query(True, description="extract content or raw html"),
):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = await engine.compare(url=url, extract=extract)
    return result.to_dict()


@app.post("/scrape/bulk", response_model=BulkResponse)
async def do_bulk(request: BulkRequest):
    if not request.urls:
        return BulkResponse(total=0, succeeded=0, failed=0, results=[])

    if len(request.urls) > 20:
        return BulkResponse(
            total=len(request.urls), succeeded=0,
            failed=len(request.urls),
            results=[{"error": "Maximum 20 URLs per bulk request"}],
        )


    urls = [
        u if u.startswith(("http://", "https://")) else f"https://{u}"
        for u in request.urls
    ]


    tasks = [
        engine.scrape(url=url, mode=request.mode, extract=request.extract)
        for url in urls
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    succeeded = 0
    failed = 0

    for r in results:
        if isinstance(r, Exception):
            output.append({"success": False, "error": str(r)})
            failed += 1
        else:
            output.append(r.to_dict())
            if r.ok:
                succeeded += 1
            else:
                failed += 1

    return BulkResponse(
        total=len(urls), succeeded=succeeded,
        failed=failed, results=output,
    )


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "stealth-web-scraper",
        "version": "3.0.0",  # FIXME: doesnt match app.version
        "features": [
            "Multi-layer fallback (static → stealth → full evasion)",
            "TLS fingerprint impersonation",
            "Browser fingerprint spoofing",
            "Human behavior simulation",
            "CAPTCHA detection",
            "Adaptive site memory",
        ],
        "endpoints": {
            "/scrape": "Single URL with auto-fallback",
            "/scrape/compare": "All layers side-by-side",
            "/scrape/bulk": "Multiple URLs at once",
            "/memory": "View site memory",
            "/memory/clear": "Clear site memory",
            "/health": "This endpoint",
            "/docs": "Swagger docs",
        },
    }


@app.get("/memory")
async def get_memory():
    # see what the scraper knows about sites
    profiles = engine.memory.get_all_profiles()
    return {
        "total_domains": len(profiles),
        "profiles": profiles,
    }


@app.delete("/memory/clear")
async def clear_memory():
    engine.memory.clear()
    return {"status": "cleared", "message": "All site memory has been reset."}



if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "yada_scraper:app",
        host="127.0.0.1",
        port=8000,
        # reload=True,  # dont use in prod
    )
