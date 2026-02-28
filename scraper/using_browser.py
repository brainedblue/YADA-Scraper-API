# browser-based scrape layers (stealth + full evasion)

import asyncio
import random
import re
import time
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, BrowserContext, Route, Request
from playwright_stealth import stealth_async

from .preventing_detection import (
    FakeIdentity,
    TRACKER_DOMAINS,
    make_identity,
    random_sleep,
    small_pause,
    fake_mouse_move,
    rand_point,
)
from .stealth_js import inject_stealth_scripts, inject_helper_scripts
from .breaking_captcha import CaptchaSolver

# reuse one solver instance
_solver = CaptchaSolver()


class BrowseOutput:
    def __init__(self, success, html=None, status_code=0, reason="", response_time=0.0, layer=""):
        self.success = success
        self.html = html
        self.status_code = status_code
        self.reason = reason
        self.response_time = response_time
        self.layer = layer


async def _do_scroll(page, max_scrolls=8, timeout=10.0):
    start = time.time()
    prev_h = 0

    for i in range(max_scrolls):
        if (time.time() - start) >= timeout:
            break

        current_h = await page.evaluate("document.body.scrollHeight")

        amt = random.randint(300, 700)
        await page.evaluate(f"window.scrollBy(0, {amt})")

        await asyncio.sleep(small_pause() + random.uniform(0.3, 0.8))

        new_h = await page.evaluate("document.body.scrollHeight")
        if new_h == prev_h and i > 2:
            break
        prev_h = new_h


    if random.random() < 0.3:
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(small_pause())


async def _wait_loaded(page, timeout=10000):
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass


async def stealth_scrape(url, fingerprint=None, timeout=20.0, retries=1):
    if fingerprint is None:
        fingerprint = make_identity()

    start = time.time()

    for attempt in range(retries + 1):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-extensions",
                        "--disable-infobars",
                    ],
                )

                ctx = await browser.new_context(
                    user_agent=fingerprint.ua_string,
                    viewport={
                        "width": fingerprint.scr_w,
                        "height": fingerprint.scr_h,
                    },
                    locale=fingerprint.lang,
                    timezone_id=fingerprint.tz,
                    color_scheme="light",
                    permissions=["geolocation"],
                )

                page = await ctx.new_page()

                await stealth_async(page)
                await inject_stealth_scripts(page)


                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout * 1000),
                )

                status = response.status if response else 0

                await _wait_loaded(page)


                await _do_scroll(page, max_scrolls=5, timeout=8.0)

                html = await page.content()

                if status in (403, 503) or _is_blocked(html):
                    solved, msg = await _try_solve_captcha(page)
                    if solved:
                        html = await page.content()
                        if not _is_blocked(html):
                            await browser.close()
                            return BrowseOutput(
                                success=True, html=html, status_code=200,
                                reason=f"CAPTCHA solved! {msg}",
                                response_time=time.time() - start,
                                layer="browser_stealth",
                            )

                    await browser.close()
                    return BrowseOutput(
                        success=False, html=html, status_code=status,
                        reason=f"Still blocked. {msg}",
                        response_time=time.time() - start,
                        layer="browser_stealth",
                    )

                await browser.close()
                return BrowseOutput(
                    success=True, html=html, status_code=status,
                    reason="Stealth browser worked!",
                    response_time=time.time() - start,
                    layer="browser_stealth",
                )

        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(random_sleep(base=2.0, jitter=1.0))
                fingerprint = make_identity()
                continue

            return BrowseOutput(
                success=False, status_code=0,
                reason=f"Stealth browser failed: {type(e).__name__}",
                response_time=time.time() - start,
                layer="browser_stealth",
            )


# TODO: add proxy support
async def full_scrape(url, fingerprint=None, timeout=30.0, retries=1):
    if fingerprint is None:
        fingerprint = make_identity()

    start = time.time()
    parsed = urlparse(url)
    homepage = f"{parsed.scheme}://{parsed.netloc}/"

    for attempt in range(retries + 1):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-extensions",
                        "--disable-infobars",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                    ],
                )

                ctx = await browser.new_context(
                    user_agent=fingerprint.ua_string,
                    viewport={
                        "width": fingerprint.scr_w,
                        "height": fingerprint.scr_h,
                    },
                    locale=fingerprint.lang,
                    timezone_id=fingerprint.tz,
                    color_scheme="light",
                    permissions=["geolocation"],
                    java_script_enabled=True,
                )

                page = await ctx.new_page()

                await stealth_async(page)
                await inject_stealth_scripts(page)

                # block trackers/analytics
                await page.route("**/*", _block_trackers)

                # warm up cookies on homepage first
                if url != homepage:
                    try:
                        await page.goto(
                            homepage,
                            wait_until="domcontentloaded",
                            timeout=8000,
                        )
                        await asyncio.sleep(random_sleep(base=1.5, jitter=0.5))
                        await _act_human(page, fingerprint, quick=True)
                    except Exception:
                        pass


                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout * 1000),
                )

                status = response.status if response else 0

                await _wait_loaded(page)

                await inject_helper_scripts(page)

                await _act_human(page, fingerprint, quick=False)
                await _scroll_around(page, fingerprint)

                html = await page.content()

                if status in (403, 503) or _is_blocked(html):
                    solved, msg = await _try_solve_captcha(page)
                    if solved:
                        html = await page.content()
                        if not _is_blocked(html):
                            await browser.close()
                            return BrowseOutput(
                                success=True, html=html, status_code=200,
                                reason=f"CAPTCHA solved! {msg}",
                                response_time=time.time() - start,
                                layer="browser_full",
                            )

                    await browser.close()
                    return BrowseOutput(
                        success=False, html=html, status_code=status,
                        reason=f"Still blocked after full evasion. {msg}",
                        response_time=time.time() - start,
                        layer="browser_full",
                    )

                await browser.close()
                return BrowseOutput(
                    success=True, html=html, status_code=status,
                    reason="Full evasion worked!",
                    response_time=time.time() - start,
                    layer="browser_full",
                )

        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(random_sleep(base=3.0, jitter=1.5))
                fingerprint = make_identity()
                continue

            return BrowseOutput(
                success=False, status_code=0,
                reason=f"Full evasion failed: {type(e).__name__}",
                response_time=time.time() - start,
                layer="browser_full",
            )


async def _act_human(page, fp, quick=False):
    vw, vh = fp.scr_w, fp.scr_h

    num_moves = random.randint(1, 3) if quick else random.randint(3, 6)

    pos = (vw // 2, vh // 2)

    for _ in range(num_moves):
        target = rand_point(vw, vh)

        path = fake_mouse_move(pos, target, num=random.randint(12, 25))

        for pt in path:
            try:
                await page.mouse.move(
                    max(0, min(pt[0], vw)),
                    max(0, min(pt[1], vh)),
                )
            except Exception:
                break
            await asyncio.sleep(random.uniform(0.005, 0.02))

        pos = target

        await asyncio.sleep(small_pause() + random.uniform(0.1, 0.5))

    # maybe hover over a link
    # tried page.keyboard.press('Tab') here but it triggers bot detection
    if random.random() < 0.4 and not quick:
        try:
            links = await page.query_selector_all("a")
            if links:
                link = random.choice(links[:10])
                box = await link.bounding_box()
                if box:
                    target = (
                        int(box["x"] + box["width"] / 2),
                        int(box["y"] + box["height"] / 2),
                    )
                    path = fake_mouse_move(pos, target)
                    for pt in path:
                        try:
                            await page.mouse.move(pt[0], pt[1])
                        except Exception:
                            break
                        await asyncio.sleep(random.uniform(0.01, 0.03))
                    await asyncio.sleep(random_sleep(base=0.8, jitter=0.3))
        except Exception:
            pass


async def _scroll_around(page, fp):
    num_scrolls = random.randint(4, 10)

    for i in range(num_scrolls):
        dist = random.randint(150, 500)

        # sometimes go back up
        if i > 2 and random.random() < 0.2:
            dist = -random.randint(50, 200)

        await page.evaluate(f"window.scrollBy(0, {dist})")

        pause = random_sleep(base=0.8, jitter=0.4)
        await asyncio.sleep(pause)


        try:
            at_bottom = await page.evaluate(
                "(window.innerHeight + window.scrollY) >= document.body.scrollHeight - 50"
            )
            if at_bottom and i > 2:
                break
        except Exception:
            break


async def _block_trackers(route, request):
    url = request.url.lower()

    for domain in TRACKER_DOMAINS:
        if domain in url:
            await route.abort()
            return


    bad_paths = [
        "/fingerprint", "/fp.js", "/bot-detect",
        "/challenge-platform", "/cdn-cgi/challenge",
    ]
    for path in bad_paths:
        if path in url:
            await route.abort()
            return

    await route.continue_()

# moved these out of the function for perf
_block_patterns = [
    re.compile(r"access\s+denied", re.I),
    re.compile(r"blocked", re.I),
    re.compile(r"captcha", re.I),
    re.compile(r"checking your browser", re.I),
    re.compile(r"cf-browser-verification", re.I),
]

def _is_blocked(html):
    if not html:
        return True

    snippet = html[:3000]
    hits = sum(1 for p in _block_patterns if p.search(snippet))

    return hits >= 2


async def _try_solve_captcha(page):
    if not _solver.available:
        return False, "No AI key, can't solve."

    try:
        result = await _solver.solve(page, captcha_type="auto")

        if result.solved:
            await asyncio.sleep(3)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            return True, f"AI solved {result.captcha_type}!"
        else:
            return False, f"AI failed: {result.error}"

    except Exception as e:
        return False, f"AI error: {type(e).__name__}"
