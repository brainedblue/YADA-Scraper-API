# static scraper - curl_cffi based, no browser needed

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession, Response

from .preventing_detection import FakeIdentity, make_identity, random_sleep


@dataclass
class QuickResult:
    success: bool
    html: Optional[str] = None
    status_code: int = 0
    needs_browser: bool = False
    reason: str = ""
    response_time: float = 0.0



JS_HINTS = [
    re.compile(r"<noscript>.*enable javascript", re.I | re.S),
    re.compile(r"you need to enable javascript", re.I),
    re.compile(r"please enable javascript", re.I),
    re.compile(r"this page requires javascript", re.I),
    re.compile(r"javascript is required", re.I),
    re.compile(r"<div id=[\"']__next[\"']>\s*</div>", re.I),  # empty next.js
    re.compile(r"<div id=[\"']root[\"']>\s*</div>", re.I),    # empty react
    re.compile(r"<div id=[\"']app[\"']>\s*</div>", re.I),     # empty vue
]


BLOCK_HINTS = [
    re.compile(r"checking your browser", re.I),
    re.compile(r"cf-browser-verification", re.I),
    re.compile(r"just a moment\.\.\.", re.I),
    re.compile(r"ray id", re.I),
    re.compile(r"ddos-guard", re.I),
    re.compile(r"attention required.*cloudflare", re.I | re.S),
    re.compile(r"blocked by.*security", re.I),
    re.compile(r"access denied", re.I),
    re.compile(r"<title>\s*403\s", re.I),
    re.compile(r"captcha", re.I),
]


def _check_if_blocked(html, status_code):
    if status_code == 403:
        return True, "Got 403'd — they probably know we're a bot"

    if status_code == 503:
        return True, "Got 503 — likely a challenge page"

    if status_code >= 400:
        return True, f"HTTP {status_code} error"

    # check for block keywords
    for pattern in BLOCK_HINTS:
        if pattern.search(html[:5000]):
            return True, f"Challenge page: {pattern.pattern[:30]}"

    # check if its just an empty js app
    for pattern in JS_HINTS:
        if pattern.search(html[:10000]):
            return True, f"Needs JS: {pattern.pattern[:30]}"

    # if theres barely any text its probably a js-only page
    # NOTE: lxml is way faster than html.parser here
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body:
        text = body.get_text(strip=True)
        if len(text) < 100:
            return True, f"Not enough text ({len(text)} chars) — likely needs JS"

    return False, ""


async def quick_scrape(url, fingerprint=None, timeout=15.0, retries=2):
    """Try to get the page without a full browser instance."""
    if fingerprint is None:
        fingerprint = make_identity()

    start = time.time()


    for attempt in range(retries + 1):
        try:
            async with AsyncSession(
                impersonate=fingerprint.impersonate_id or "chrome120",
                timeout=timeout,
            ) as session:
                response = await session.get(
                    url,
                    headers=fingerprint.headers,
                    allow_redirects=True,
                    max_redirects=5,
                )

                elapsed = time.time() - start
                html = response.text
                # print(f"[DEBUG] status={response.status_code}")

                blocked, reason = _check_if_blocked(html, response.status_code)

                if blocked:
                    return QuickResult(
                        success=False, html=html,
                        status_code=response.status_code,
                        needs_browser=True,
                        reason=reason, response_time=elapsed,
                    )

                return QuickResult(
                    success=True, html=html,
                    status_code=response.status_code,
                    needs_browser=False,
                    reason="Static scrape worked!",
                    response_time=elapsed,
                )

        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(random_sleep(base=1.0, jitter=0.5))
                fingerprint = make_identity()
                continue
            
            return QuickResult(
                success=False, status_code=0,
                needs_browser=True,
                reason=f"Static request failed: {type(e).__name__}",
                response_time=time.time() - start,
            )
