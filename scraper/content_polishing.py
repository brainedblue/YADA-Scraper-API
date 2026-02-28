# content extraction from html pages

from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, field
from typing import Optional
import json
import re


@dataclass
class PageData:
    url: str = ""
    title: str = ""
    description: str = ""
    canonical_url: str = ""
    language: str = ""
    main_text: str = ""
    raw_html: str = ""
    og_tags: dict = field(default_factory=dict)
    json_ld: list = field(default_factory=list)
    links: list = field(default_factory=list)
    images: list = field(default_factory=list)
    word_count: int = 0

    def to_dict(self):
        return {
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "canonical_url": self.canonical_url,
            "language": self.language,
            "main_text": self.main_text,
            "og_tags": self.og_tags,
            "json_ld": self.json_ld,
            "links": self.links[:50],  # dont send too many
            "images": self.images[:30],
            "word_count": self.word_count,
        }



JUNK_TAGS = [
    "script", "style", "noscript", "iframe", "svg",
    "nav", "footer", "header",
    "aside",
]

JUNK_CLASSES = [
    "nav", "navbar", "footer", "sidebar", "menu", "breadcrumb",
    "advertisement", "ad", "ads", "cookie", "popup", "modal",
    "social", "share", "comment", "comments",
]

JUNK_IDS = [
    "nav", "navbar", "footer", "sidebar", "menu", "header",
    "cookie-banner", "cookie-consent", "ad-container",
]


def _is_junk(tag):
    if getattr(tag, "attrs", None) is None:
        return False

    if tag.name in ("nav", "footer", "aside"):
        return True

    classes = " ".join(tag.get("class", [])).lower()
    for c in JUNK_CLASSES:
        if c in classes:
            return True

    tag_id = (tag.get("id") or "").lower()
    for jid in JUNK_IDS:
        if jid in tag_id:
            return True

    role = (tag.get("role") or "").lower()
    if role in ("navigation", "banner", "contentinfo", "complementary"):
        return True

    return False


def parse_page(html, url=""):
    soup = BeautifulSoup(html, "lxml")
    result = PageData(url=url, raw_html=html)


    if soup.title and soup.title.string:
        result.title = soup.title.string.strip()


    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        result.description = meta_desc["content"].strip()


    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        result.canonical_url = canonical["href"]


    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        result.language = html_tag["lang"]

    # og tags
    for og in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
        prop = og.get("property", "")
        content = og.get("content", "")
        if prop and content:
            result.og_tags[prop] = content


    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                result.json_ld.extend(data)
            elif isinstance(data, dict):
                result.json_ld.append(data)
        except (json.JSONDecodeError, TypeError):
            continue


    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if href and not href.startswith(("javascript:", "mailto:", "#")):
            result.links.append({"href": href, "text": text[:100]})


    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt", "")
        if src:
            result.images.append({"src": src.strip(), "alt": alt.strip()[:100]})

    # have to re-parse because decompose mutates in place
    # tried using readability-lxml here but it was overkill
    text_soup = BeautifulSoup(html, "lxml")


    for tag_name in JUNK_TAGS:
        for tag in text_soup.find_all(tag_name):
            tag.decompose()


    for tag in text_soup.find_all(True):
        if isinstance(tag, Tag) and _is_junk(tag):
            tag.decompose()


    main_content = (
        text_soup.find("main")
        or text_soup.find("article")
        or text_soup.find(id="content")
        or text_soup.find(class_="content")
        or text_soup.find(role="main")
    )

    if main_content:
        raw_text = main_content.get_text(separator="\n", strip=True)
    else:
        body = text_soup.find("body")
        raw_text = body.get_text(separator="\n", strip=True) if body else text_soup.get_text(separator="\n", strip=True)

    # clean up
    lines = [line.strip() for line in raw_text.splitlines()]
    cleaned = [line for line in lines if line]

    result.main_text = "\n".join(cleaned)
    result.word_count = len(result.main_text.split())

    return result


def get_text_fast(html):
    soup = BeautifulSoup(html, "lxml")
    for tag_name in JUNK_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    body = soup.find("body")
    text = body.get_text(separator=" ", strip=True) if body else soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()
