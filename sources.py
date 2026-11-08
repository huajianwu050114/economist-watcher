"""Read public issue metadata. Never attempts to access paywalled files."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

CATEGORY_URL = "https://magazinelib.com/all/the-economist/"
RSSHUB_URL = "https://rsshub.app/magazinelib/latest-magazine/the+economist"
USER_AGENT = "EconomistWatcher/1.0 (personal issue monitoring; contact via repository owner)"
MONTH = r"January|February|March|April|May|June|July|August|September|October|November|December"
DATE_DMY = re.compile(rf"\b(\d{{1,2}})\s+({MONTH})\s+(20\d{{2}})\b", re.I)
DATE_MDY = re.compile(rf"\b({MONTH})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I)


@dataclass(frozen=True)
class Issue:
    key: str
    date: str
    edition: str
    title: str
    link: str

    def as_dict(self) -> dict[str, str]:
        return {"date": self.date, "edition": self.edition, "title": self.title, "link": self.link}


def fetch_text(url: str, *, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
    with urlopen(req, timeout=timeout) as res:
        raw = res.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("Metadata response too large")
        encoding = res.headers.get_content_charset() or "utf-8"
    return raw.decode(encoding, errors="replace")


class HeadingLinkParser(HTMLParser):
    """Only capture anchors inside H2/H3; avoids menu/sidebar false positives."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading = None
        self.link = None
        self.parts: list[str] = []
        self.matches: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3") and self.heading is None:
            self.heading = tag
            self.link = None
            self.parts = []
        if self.heading and tag == "a" and self.link is None:
            self.link = dict(attrs).get("href")

    def handle_data(self, data):
        if self.heading:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.heading == tag:
            title = " ".join("".join(self.parts).split())
            if self.link and title:
                self.matches.append((title, self.link))
            self.heading = None
            self.link = None
            self.parts = []


def html_candidates(page: str, *, base_url: str = CATEGORY_URL) -> list[tuple[str, str]]:
    parser = HeadingLinkParser()
    parser.feed(page)
    return [(title, urljoin(base_url, link)) for title, link in parser.matches]


def _xml_text(element: ET.Element, name: str) -> str:
    # ElementTree finds either RSS child or Atom child without knowing namespace.
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == name:
            return (child.text or "").strip()
    return ""


def feed_candidates(feed: str) -> list[tuple[str, str]]:
    root = ET.fromstring(feed)
    candidates = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        title = _xml_text(node, "title")
        link = _xml_text(node, "link")
        if not link:
            for child in node:
                if child.tag.rsplit("}", 1)[-1] == "link":
                    link = child.attrib.get("href", "")
                    if child.attrib.get("rel", "alternate") == "alternate":
                        break
        if title and link:
            candidates.append((title, link))
    return candidates


def _parse_date(title: str) -> str | None:
    m = DATE_DMY.search(title)
    if m:
        day, month, year = m.groups()
        raw = f"{day} {month.title()} {year}"
        fmt = "%d %B %Y"
    else:
        m = DATE_MDY.search(title)
        if not m:
            return None
        month, day, year = m.groups()
        raw = f"{month.title()} {day} {year}"
        fmt = "%B %d %Y"
    try:
        return datetime.strptime(raw, fmt).date().isoformat()
    except ValueError:
        return None


def _edition(title: str) -> str:
    t = title.casefold()
    if "asia" in t:
        return "asia"
    if "middle east" in t or "africa" in t:
        return "middle-east-africa"
    if "europe" in t:
        return "europe"
    if re.search(r"\b(usa|us edition|united states)\b", t):
        return "usa"
    if re.search(r"\b(uk|britain|united kingdom)\b", t):
        return "uk"
    return "unspecified"


def to_issue(title: str, link: str) -> Issue | None:
    title = " ".join(title.split())
    if not re.match(r"^the economist(?:\s|\s*[—–:-])", title, re.I):
        return None
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {"magazinelib.com", "www.magazinelib.com"}:
        return None
    # Only issue posts; never a search/category link.
    if not parsed.path.startswith("/all/the-economist-"):
        return None
    date = _parse_date(title)
    if not date:
        return None
    edition = _edition(title)
    return Issue(f"{date}:{edition}", date, edition, title, link)


def normalize(candidates: list[tuple[str, str]], edition: str = "asia") -> list[Issue]:
    out: dict[str, Issue] = {}
    for title, url in candidates:
        issue = to_issue(title, url)
        if issue is not None and (edition == "all" or issue.edition == edition):
            out[issue.key] = issue
    return sorted(out.values(), key=lambda i: (i.date, i.edition), reverse=True)


def load_issues(edition: str = "asia", *, fixture: str | None = None) -> tuple[list[Issue], str]:
    if fixture:
        with open(fixture, "r", encoding="utf-8") as f:
            text = f.read()
        raw = feed_candidates(text) if text.lstrip().startswith("<?xml") or text.lstrip().startswith("<rss") else html_candidates(text)
        issues = normalize(raw, edition)
        if not issues:
            raise RuntimeError("Fixture contains no matching issues")
        return issues, "fixture"

    errors = []
    for kind, url in (("magazinelib-category", CATEGORY_URL), ("rsshub", RSSHUB_URL)):
        try:
            body = fetch_text(url)
            raw = html_candidates(body, base_url=url) if kind == "magazinelib-category" else feed_candidates(body)
            # An accessible listing with only editions excluded by filter is not a success.
            issues = normalize(raw, edition)
            if not issues:
                raise ValueError("No matching issues found: HTML layout changed, feed is empty, or edition absent")
            return issues, kind
        except Exception as exc:
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Both metadata sources failed:\n" + "\n".join(errors))
