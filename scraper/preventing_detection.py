# anti-detection

import random
import time
from dataclasses import dataclass, field
from typing import Optional
import logging

logging.getLogger("fake_useragent").setLevel(logging.ERROR)

try:
    from fake_useragent import UserAgent as UserAgentGenerator
    _ua_gen = UserAgentGenerator(
        browsers=["Chrome", "Firefox", "Safari", "Edge"],
        os=["Windows", "macOS", "Linux"],
        min_percentage=1.0,
    )
    has_fake_ua = True
except Exception:
    _ua_gen = None
    has_fake_ua = False


# hardcoded fallbacks
FALLBACK_AGENTS = [
    ("chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    ("chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
    ("chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    ("chrome", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    ("chrome", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    ("chrome", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    # firefox ones
    ("firefox", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"),
    ("firefox", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"),
    ("firefox", "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"),
    ("safari", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15"),
    ("safari", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"),
    # ("opera", "Mozilla/5.0 (Windows ...) OPR/..."),  # removed, nobody uses opera
    # edge
    ("edge", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"),
]


def _pick_browser(ua):
    ua_lower = ua.lower()
    if "edg/" in ua_lower or "edge/" in ua_lower:
        return "edge"
    elif "firefox/" in ua_lower:
        return "firefox"
    elif "safari/" in ua_lower and "chrome/" not in ua_lower:
        return "safari"
    else:
        return "chrome"


def _get_ua(chrome_only=False):
    if has_fake_ua and _ua_gen:
        try:
            for _ in range(5):
                ua = _ua_gen.random
                fam = _pick_browser(ua)
                if not chrome_only or fam in ("chrome", "edge"):
                    return (fam, ua)
        except Exception:
            pass

    # fallback to hardcoded list
    pool = [x for x in FALLBACK_AGENTS if not chrome_only or x[0] in ("chrome", "edge")]
    if not pool:
        pool = FALLBACK_AGENTS
    fam, ua = random.choice(pool)
    return (fam, ua)


# curl_cffi impersonation targets
BROWSER_VERSIONS = {
    "chrome": [
        "chrome110", "chrome116", "chrome119", "chrome120", "chrome123",
        "chrome124", "chrome131",
    ],
    "safari": ["safari15_3", "safari15_5", "safari17_0"],
    "edge": ["edge101", "edge99"],
    "firefox": [],  # doesnt work well with curl_cffi
}


# from statcounter global stats
SCREEN_SIZES = [
    (1920, 1080, 50),
    (1366, 768, 20),
    (1536, 864, 10),
    (1440, 900, 8),
    (1680, 1050, 5),
    (2560, 1440, 4),
    (1280, 720, 3),
]


LOCALES = [
    ("en-US", "America/New_York"),
    ("en-US", "America/Chicago"),
    ("en-US", "America/Los_Angeles"),
    ("en-GB", "Europe/London"),
    ("en-AU", "Australia/Sydney"),
    ("en-CA", "America/Toronto"),
]


TRACKER_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.net",
    "hotjar.com",
    "fullstory.com",
    "datadome.co",
    "perimeterx.com",
    "px-cdn.net",
    "kasada.io",
    "fingerprintjs.com",
    "cdn.fp.measure.office.com",
]


@dataclass
class FakeIdentity:
    browser_type: str
    ua_string: str
    headers: dict
    scr_w: int
    scr_h: int
    lang: str
    tz: str
    impersonate_id: Optional[str] = None
    os_name: str = ""

    def __post_init__(self):
        if not self.os_name:
            if "Windows" in self.ua_string:
                self.os_name = "Windows"
            elif "Macintosh" in self.ua_string:
                self.os_name = "macOS"
            else:
                self.os_name = "Linux"


def _get_chrome_ver(ua):
    import re
    m = re.search(r"Chrome/(\d+)", ua)
    return m.group(1) if m else "120"


def _chrome_headers(ua):
    ver = _get_chrome_ver(ua)

    if "Windows" in ua:
        plat = '"Windows"'
    elif "Macintosh" in ua:
        plat = '"macOS"'
    else:
        plat = '"Linux"'

    is_edge = "Edg/" in ua
    if is_edge:
        brand = f'"Microsoft Edge";v="{ver}", "Chromium";v="{ver}", "Not_A Brand";v="24"'
    else:
        brand = f'"Google Chrome";v="{ver}", "Chromium";v="{ver}", "Not_A Brand";v="24"'

    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": brand,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": plat,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
    }


def _firefox_headers(ua):
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _safari_headers(ua):
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


# TODO: maybe cache this per-session?
def make_identity(chrome_only=False):
    (b_type, ua) = _get_ua(chrome_only=chrome_only)

    if b_type in ("chrome", "edge"):
        hdrs = _chrome_headers(ua)
    elif b_type == "firefox":
        hdrs = _firefox_headers(ua)
    else:
        hdrs = _safari_headers(ua)


    choices = [(w, h) for w, h, _ in SCREEN_SIZES]
    weights = [wt for _, _, wt in SCREEN_SIZES]
    w, h = random.choices(choices, weights=weights, k=1)[0]

    # jitter so its not an exact standard resolution
    w += random.randint(-15, 15)
    h += random.randint(-8, 8)
    # w, h = 1920, 1080  # was hardcoded before

    loc, timezone = random.choice(LOCALES)
    hdrs["Accept-Language"] = f"{loc},{loc.split('-')[0]};q=0.9"


    targets = BROWSER_VERSIONS.get(b_type, [])
    imp = random.choice(targets) if targets else random.choice(BROWSER_VERSIONS["chrome"])

    return FakeIdentity(
        browser_type=b_type,
        ua_string=ua,
        headers=hdrs,
        scr_w=w,
        scr_h=h,
        lang=loc,
        tz=timezone,
        impersonate_id=imp,
    )


def random_sleep(base=1.5, jitter=0.7):
    """Gaussian delay to simulate human timing."""
    t = random.gauss(base, jitter)
    return max(0.2, t)


def small_pause():
    return random.uniform(0.04, 0.25)



def fake_mouse_move(start, end, num=15):
    # bezier curve, adapted from a SO answer
    x1, y1 = start
    x2, y2 = end

    # control points for the curve
    m1x = x1 + random.randint(-80, 180)
    m1y = y1 + random.randint(-80, 180)
    m2x = x2 + random.randint(-180, 80)
    m2y = y2 + random.randint(-180, 80)

    pts = []
    for i in range(num + 1):
        t = i / num
        inv = 1 - t
        px = int(inv**3 * x1 + 3 * inv**2 * t * m1x + 3 * inv * t**2 * m2x + t**3 * x2)
        py = int(inv**3 * y1 + 3 * inv**2 * t * m1y + 3 * inv * t**2 * m2y + t**3 * x2)


        px += random.randint(-1, 1)
        py += random.randint(-1, 1)
        pts.append((px, py))

    return pts


def rand_point(max_w, max_h):
    return (
        random.randint(10, max(11, max_w - 10)),
        random.randint(10, max(11, max_h - 10)),
    )
