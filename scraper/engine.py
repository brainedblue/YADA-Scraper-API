# scraper engine - orchestrates the layers

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .preventing_detection import make_identity, FakeIdentity
from .simple_scraping import quick_scrape, QuickResult
from .using_browser import stealth_scrape, full_scrape, BrowseOutput
from .content_polishing import parse_page, PageData
from .adaptive_memory import SiteMemory



CAPTCHA_PATTERNS = {
    "cloudflare_turnstile": [
        re.compile(r"challenges\.cloudflare\.com/turnstile", re.I),
        re.compile(r"cf-turnstile", re.I),
    ],
    "recaptcha_v2": [
        re.compile(r"google\.com/recaptcha/api", re.I),
        re.compile(r"g-recaptcha", re.I),
        re.compile(r"grecaptcha", re.I),
    ],
    "recaptcha_v3": [
        re.compile(r"recaptcha/api\.js\?.*render=", re.I),
        re.compile(r"grecaptcha\.execute", re.I),
    ],
    "hcaptcha": [
        re.compile(r"hcaptcha\.com/1/api", re.I),
        re.compile(r"h-captcha", re.I),
    ],
    "datadome": [
        re.compile(r"datadome\.co", re.I),
        re.compile(r"dd\.js", re.I),
    ],
    "perimeterx": [
        re.compile(r"perimeterx\.net", re.I),
        re.compile(r"px-captcha", re.I),
    ],
    "cloudflare_challenge": [
        re.compile(r"checking your browser", re.I),
        re.compile(r"cf-browser-verification", re.I),
        re.compile(r"just a moment\.\.\.", re.I),
    ],
    "generic_captcha": [
        re.compile(r"captcha", re.I),
    ],
}


def find_captcha(html):
    if not html:
        return None

    chunk = html[:15000]  # only check the top part

    for ctype in [
        "cloudflare_turnstile", "recaptcha_v3", "recaptcha_v2",
        "hcaptcha", "datadome", "perimeterx", "cloudflare_challenge",
        "generic_captcha",
    ]:
        for r in CAPTCHA_PATTERNS[ctype]:
            if r.search(chunk):
                return ctype

    return None



CAPTCHA_DESCRIPTIONS = {
    "cloudflare_turnstile": "Cloudflare Turnstile — need a solver service for this.",
    "recaptcha_v2": "Google reCAPTCHA v2 — the clicky one.",
    "recaptcha_v3": "Google reCAPTCHA v3 — invisible score thing.",
    "hcaptcha": "hCaptcha — image stuff.",
    "datadome": "DataDome — really hard to bypass.",
    "perimeterx": "PerimeterX — also very hard.",
    "cloudflare_challenge": "Cloudflare Browser check — usually stealth browser works but not here.",
    "generic_captcha": "Found some kind of CAPTCHA but not sure which one.",
}


def _figure_out_error(attempts, last_html=None):
    info = {
        "summary": "",
        "details": [],
        "captcha_detected": None,
        "captcha_info": None,
        "suggestion": "",
    }

    ctype = find_captcha(last_html) if last_html else None

    if ctype:
        info["captcha_detected"] = ctype
        info["captcha_info"] = CAPTCHA_DESCRIPTIONS.get(ctype, "Unknown CAPTCHA.")

    for att in attempts:
        name = att["layer"]
        reason = att.get("reason", "")
        code = att.get("status_code", 0)

        detail = f"Layer '{name}'"
        if code == 403:
            detail += ": Blocked (403 Forbidden)."
        elif code == 503:
            detail += ": 503 — probably a challenge page."
        elif code >= 400:
            detail += f": Got an error code {code}."
        elif "challenge" in reason.lower():
            detail += ": Found an anti-bot challenge."
        elif "javascript" in reason.lower():
            detail += ": Needs JavaScript to work."
        elif "thin content" in reason.lower():
            detail += ": Page was almost empty."
        else:
            detail += f": {reason}"

        info["details"].append(detail)

    failed = len([a for a in attempts if not a.get("success")])
    total = len(attempts)

    if ctype:
        info["summary"] = f"Blocked by {ctype}. All {failed}/{total} layers failed."
        info["suggestion"] = f"Try using a CAPTCHA solver for {ctype}."
    elif any(a.get("status_code") == 403 for a in attempts):
        info["summary"] = f"Banned! {failed}/{total} layers were blocked."
        info["suggestion"] = "Try using a proxy or wait a bit."
    else:
        info["summary"] = f"Tried {total} layers, none of them worked."
        info["suggestion"] = "The site might have really tough security."

    return info


@dataclass
class ScrapeResult:
    ok: bool
    url: str
    data: Optional[dict] = None
    winning_layer: str = ""
    elapsed: float = 0.0
    tries: list = field(default_factory=list)
    err: str = ""
    notes: Optional[dict] = None

    def to_dict(self):
        out = {
            "success": self.ok,
            "url": self.url,
            "content": self.data,
            "layer_used": self.winning_layer,
            "total_time": round(self.elapsed, 3),
            "layer_attempts": self.tries,
            "error": self.err,
        }
        if self.notes:
            out["diagnosis"] = self.notes
        return out


@dataclass
class CompareData:
    url: str
    total_time: float
    layers: list = field(default_factory=list)
    fastest: Optional[str] = None
    tip: str = ""

    def to_dict(self):
        return {
            "url": self.url,
            "total_time": round(self.total_time, 3),
            "layers": self.layers,
            "fastest_successful": self.fastest,
            "recommendation": self.tip,
        }


class ScraperEngine:

    def __init__(self):
        self.memory = SiteMemory()

    async def scrape(self, url, mode="auto", extract=True):
        start = time.time()
        attempts = []
        fp = make_identity()

        if mode == "static":
            res = await self._try_static(url, fp, start, attempts, extract)
        elif mode == "browser":
            res = await self._try_browser(url, fp, start, attempts, extract)
        else:
            res = await self._try_auto(url, fp, start, attempts, extract)

        # remember what happened
        self.memory.record_attempt(
            url, res.tries,
            success_layer=res.winning_layer if res.ok else None,
        )

        return res

    async def compare(self, url, extract=True):
        start = time.time()
        layers = []
        best_time = float("inf")
        best_layer = None

        # static
        fp1 = make_identity()
        s = await quick_scrape(url, fingerprint=fp1)
        layer_info = {
            "layer": "static",
            "display_name": "Layer 1: Static",
            "success": s.success, "status_code": s.status_code,
            "reason": s.reason, "time": round(s.response_time, 3),
            "preview": None,
        }
        if s.success and s.html and extract:
            ext = parse_page(s.html, url)
            layer_info["preview"] = ext.main_text[:200] + "..."
            if s.response_time < best_time:
                best_time = s.response_time
                best_layer = "static"
        layers.append(layer_info)

        # stealth browser
        fp2 = make_identity()
        b = await stealth_scrape(url, fingerprint=fp2)
        layer_info = {
            "layer": "browser_stealth",
            "display_name": "Layer 2: Stealth Browser",
            "success": b.success, "status_code": b.status_code,
            "reason": b.reason, "time": round(b.response_time, 3),
            "preview": None,
        }
        if b.success and b.html and extract:
            ext = parse_page(b.html, url)
            layer_info["preview"] = ext.main_text[:200] + "..."
            if b.response_time < best_time:
                best_time = b.response_time
                best_layer = "browser_stealth"
        layers.append(layer_info)

        # full evasion
        fp3 = make_identity()
        f = await full_scrape(url, fingerprint=fp3)
        layer_info = {
            "layer": "browser_full",
            "display_name": "Layer 3: Full Evasion Browser",
            "success": f.success, "status_code": f.status_code,
            "reason": f.reason, "time": round(f.response_time, 3),
            "preview": None,
        }
        if f.success and f.html and extract:
            ext = parse_page(f.html, url)
            layer_info["preview"] = ext.main_text[:200] + "..."
            if f.response_time < best_time:
                best_time = f.response_time
                best_layer = "browser_full"
        layers.append(layer_info)

        tip = "Use static if it works, it's faster!" if best_layer == "static" else "Needs a browser for this one."
        return CompareData(url=url, total_time=time.time()-start, layers=layers, fastest=best_layer, tip=tip)

    async def _try_auto(self, url, fp, start, attempts, extract):
        # PERF: static first because its ~10x faster
        html = None
        skip = self.memory.get_bad_methods(url)

        if "static" not in skip:
            res = await quick_scrape(url, fingerprint=fp)
            attempts.append({"layer": "static", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
            if res.success:
                return self._pack_result(url, res.html, "static", start, attempts, extract)
            html = res.html

        if "browser_stealth" not in skip:
            fp = make_identity()
            res = await stealth_scrape(url, fingerprint=fp)
            attempts.append({"layer": "browser_stealth", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
            if res.success:
                return self._pack_result(url, res.html, "browser_stealth", start, attempts, extract)
            html = res.html or html

        fp = make_identity()
        res = await full_scrape(url, fingerprint=fp)
        attempts.append({"layer": "browser_full", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
        if res.success:
            return self._pack_result(url, res.html, "browser_full", start, attempts, extract)

        diag = _figure_out_error(attempts, res.html or html)
        return ScrapeResult(False, url, winning_layer="none", elapsed=time.time()-start, tries=attempts, err=diag["summary"], notes=diag)

    async def _try_static(self, url, fp, start, attempts, extract):
        res = await quick_scrape(url, fingerprint=fp)
        attempts.append({"layer": "static", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
        if res.success:
            return self._pack_result(url, res.html, "static", start, attempts, extract)
        diag = _figure_out_error(attempts, res.html)
        return ScrapeResult(False, url, winning_layer="static", elapsed=time.time()-start, tries=attempts, err=diag["summary"], notes=diag)

    async def _try_browser(self, url, fp, start, attempts, extract):
        res = await stealth_scrape(url, fingerprint=fp)
        attempts.append({"layer": "browser_stealth", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
        if res.success:
            return self._pack_result(url, res.html, "browser_stealth", start, attempts, extract)
        
        fp = make_identity()
        res = await full_scrape(url, fingerprint=fp)
        attempts.append({"layer": "browser_full", "success": res.success, "status_code": res.status_code, "reason": res.reason, "time": res.response_time})
        if res.success:
            return self._pack_result(url, res.html, "browser_full", start, attempts, extract)
        
        diag = _figure_out_error(attempts, res.html)
        return ScrapeResult(False, url, winning_layer="browser", elapsed=time.time()-start, tries=attempts, err=diag["summary"], notes=diag)

    def _pack_result(self, url, html, layer, start, attempts, extract):
        if extract:
            ext = parse_page(html, url)
            data = ext.to_dict()
        else:
            data = {"html": html}

        ctype = find_captcha(html)
        notes = None
        if ctype:
            notes = {"captcha": ctype, "note": "Got content but also found a CAPTCHA."}

        return ScrapeResult(True, url, data=data, winning_layer=layer, elapsed=time.time()-start, tries=attempts, notes=notes)
