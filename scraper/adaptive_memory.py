# remembers which methods work for which sites

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse



DEFAULT_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "site_memory.json",
)


@dataclass
class SiteInfo:
    domain: str
    best_method: Optional[str] = None
    bad_methods: list = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    avg_response_time: float = 0.0
    last_scrape_time: float = 0.0
    captcha_detected: Optional[str] = None
    notes: str = ""

    def to_dict(self):
        return {
            "domain": self.domain,
            "best_layer": self.best_method,
            "failed_layers": self.bad_methods,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "avg_response_time": round(self.avg_response_time, 3),
            "last_scrape_time": self.last_scrape_time,
            "captcha_detected": self.captcha_detected,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            domain=data.get("domain", ""),
            best_method=data.get("best_layer"),
            bad_methods=data.get("failed_layers", []),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            avg_response_time=data.get("avg_response_time", 0.0),
            last_scrape_time=data.get("last_scrape_time", 0.0),
            captcha_detected=data.get("captcha_detected"),
            notes=data.get("notes", ""),
        )


class SiteMemory:

    EXPIRY = 86400  # 24h

    def __init__(self, memory_path=DEFAULT_SAVE_PATH):
        self.memory_path = memory_path
        self.profiles = {}
        self._load()

    def suggest_method(self, url):
        domain = self._get_domain(url)
        info = self.profiles.get(domain)

        if not info:
            return None

        age = time.time() - info.last_scrape_time
        if age > self.EXPIRY:
            return None

        if info.best_method:
            return info.best_method

        return None

    def get_bad_methods(self, url):
        domain = self._get_domain(url)
        info = self.profiles.get(domain)

        if not info:
            return []

        age = time.time() - info.last_scrape_time
        if age > self.EXPIRY:
            return []

        return list(info.bad_methods)

    def record_success(self, url, layer, response_time, captcha=None):
        domain = self._get_domain(url)
        info = self.profiles.get(domain, SiteInfo(domain=domain))

        info.best_method = layer
        info.success_count += 1
        info.last_scrape_time = time.time()


        if info.avg_response_time == 0:
            info.avg_response_time = response_time
        else:
            info.avg_response_time = (
                info.avg_response_time * 0.7 + response_time * 0.3
            )

        if captcha:
            info.captcha_detected = captcha

        self.profiles[domain] = info
        self._save()

    def record_failure(self, url, layer, reason="", captcha=None):
        domain = self._get_domain(url)
        info = self.profiles.get(domain, SiteInfo(domain=domain))

        if layer not in info.bad_methods:
            info.bad_methods.append(layer)

        info.fail_count += 1
        info.last_scrape_time = time.time()
        info.notes = reason

        if captcha:
            info.captcha_detected = captcha

        self.profiles[domain] = info
        self._save()

    def record_attempt(self, url, layer_attempts, success_layer=None):
        domain = self._get_domain(url)

        for attempt in layer_attempts:
            layer = attempt.get("layer", "")
            ok = attempt.get("success", False)
            t = attempt.get("time", 0.0)
            captcha = attempt.get("captcha_detected")

            if ok and layer == success_layer:
                self.record_success(url, layer, t, captcha)
            elif not ok:
                self.record_failure(url, layer, attempt.get("reason", ""), captcha)

    def get_profile(self, url):
        domain = self._get_domain(url)
        info = self.profiles.get(domain)
        return info.to_dict() if info else None

    def get_all_profiles(self):
        return [p.to_dict() for p in self.profiles.values()]

    def clear(self):
        self.profiles = {}
        self._save()

    def _load(self):
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, "r") as f:
                    data = json.load(f)
                self.profiles = {
                    domain: SiteInfo.from_dict(profile_data)
                    for domain, profile_data in data.items()
                }
            except (json.JSONDecodeError, KeyError, TypeError):
                self.profiles = {}

    def _save(self):
        data = {
            domain: info.to_dict()
            for domain, info in self.profiles.items()
        }
        try:
            with open(self.memory_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    @staticmethod
    def _get_domain(url):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return urlparse(url).netloc.lower()
