"""RSS/Atomフィードからニュースを収集する。標準ライブラリのみ使用。

対応形式: RSS 2.0 / RSS 1.0 (RDF) / Atom。
名前空間の有無に依存しないよう、タグのローカル名で判定する。
Google News RSS (news.google.com/rss/search?q=site:...) にも対応し、
タイトル末尾の「 - 媒体名」を自動除去する。
"""
from __future__ import annotations

import gzip
import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (compatible; news-agent/1.1)"
FETCH_TIMEOUT = 20


@dataclass
class Article:
    title: str
    link: str
    source: str
    published: str = ""
    summary: str = ""
    ai_summary: str = ""

    @property
    def uid(self) -> str:
        return hashlib.sha256(self.link.encode("utf-8")).hexdigest()[:16]


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if data[:2] == b"\x1f\x8b":  # gzipマジックナンバー
        data = gzip.decompress(data)
    return data


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _local(tag: str) -> str:
    """名前空間を除いたローカルタグ名を返す。"""
    return tag.rsplit("}", 1)[-1]


def _child_text(elem, name: str) -> str:
    for child in elem:
        if _local(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _entry_link(entry) -> str:
    """RSSの<link>テキスト、またはAtomの<link href=...>を解決する。"""
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        if child.text and child.text.strip():          # RSS 1.0 / 2.0
            return child.text.strip()
        href = child.get("href", "")                    # Atom
        if href:
            if child.get("rel") in (None, "alternate"):
                return href
            fallback = fallback or href
    return fallback


def _clean_google_news_title(title: str, link: str) -> str:
    """Google News経由のタイトル末尾「 - 媒体名」を除去する。"""
    if "news.google.com" in link and " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def parse_feed(xml_bytes: bytes, source_name: str) -> list[Article]:
    """RSS 2.0 / RSS 1.0 (RDF) / Atom をパースする。壊れたフィードは空リスト。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    articles: list[Article] = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in ("item", "entry"):
            continue
        title = html.unescape(_child_text(node, "title"))
        link = _entry_link(node)
        if not title or not link:
            continue
        body = (_child_text(node, "description")
                or _child_text(node, "summary")
                or _child_text(node, "content"))
        published = (_child_text(node, "pubDate")
                     or _child_text(node, "date")        # RSS 1.0 (dc:date)
                     or _child_text(node, "updated")
                     or _child_text(node, "published"))
        articles.append(Article(
            title=_clean_google_news_title(title, link),
            link=link,
            source=source_name,
            published=published,
            summary=_strip_html(body)[:500],
        ))
    return articles


def collect_all(feeds: list[dict], logger=print) -> list[Article]:
    """全フィードを収集。個別フィードの失敗は全体を止めない。"""
    articles: list[Article] = []
    for feed in feeds:
        name, url = feed["name"], feed["url"]
        limit = int(feed.get("max_items", 15))
        try:
            parsed = parse_feed(fetch_url(url), name)[:limit]
            logger(f"[collect] {name}: {len(parsed)}件")
            articles.extend(parsed)
        except Exception as e:  # noqa: BLE001 - フィード単位で握りつぶして継続
            logger(f"[collect] {name}: 失敗 ({e}) — スキップして継続")
    return articles
