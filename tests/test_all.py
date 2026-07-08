"""ネットワーク不要のテスト一式。python -m unittest discover tests で実行。"""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from news_agent import collect, main, notify, summarize

RSS_SAMPLE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>RSS Article 1</title><link>https://example.com/1</link>
<description>&lt;p&gt;Body &lt;b&gt;one&lt;/b&gt;&lt;/p&gt;</description>
<pubDate>Wed, 08 Jul 2026 06:00:00 GMT</pubDate></item>
<item><title>RSS Article 2</title><link>https://example.com/2</link>
<description>Body two</description></item>
</channel></rss>"""

ATOM_SAMPLE = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Test</title>
<entry><title>Atom Article</title>
<link rel="alternate" href="https://example.com/atom1"/>
<summary>Atom body</summary><updated>2026-07-08T06:00:00Z</updated></entry>
</feed>"""


def fake_api_response(text: str) -> bytes:
    return json.dumps({"content": [{"type": "text", "text": text}]}).encode()


class FakeHTTPResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body, self.status = body, status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCollect(unittest.TestCase):
    def test_parse_rss(self):
        arts = collect.parse_feed(RSS_SAMPLE, "TestSrc")
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].title, "RSS Article 1")
        self.assertEqual(arts[0].link, "https://example.com/1")
        self.assertEqual(arts[0].summary, "Body one")  # HTMLタグ除去
        self.assertEqual(arts[0].source, "TestSrc")

    def test_parse_atom(self):
        arts = collect.parse_feed(ATOM_SAMPLE, "AtomSrc")
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].link, "https://example.com/atom1")
        self.assertEqual(arts[0].summary, "Atom body")

    def test_broken_xml_returns_empty(self):
        self.assertEqual(collect.parse_feed(b"<not-xml", "X"), [])

    def test_collect_all_survives_feed_failure(self):
        def fake_fetch(url, timeout=20):
            if "bad" in url:
                raise urllib.error.URLError("down")
            return RSS_SAMPLE
        with mock.patch.object(collect, "fetch_url", fake_fetch):
            arts = collect.collect_all(
                [{"name": "Bad", "url": "https://bad.example"},
                 {"name": "Good", "url": "https://good.example"}],
                logger=lambda *a: None)
        self.assertEqual(len(arts), 2)  # Badは飛ばしGoodは取れる

    def test_uid_is_stable(self):
        a = collect.Article("t", "https://example.com/x", "s")
        b = collect.Article("different title", "https://example.com/x", "s")
        self.assertEqual(a.uid, b.uid)


RDF_SAMPLE = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://example.jp/"><title>RDF Test</title></channel>
<item rdf:about="https://example.jp/a1"><title>RDF&amp;記事</title>
<link>https://example.jp/a1</link>
<description>本文RDF</description><dc:date>2026-07-08T06:00:00+09:00</dc:date></item>
</rdf:RDF>""".encode("utf-8")

GNEWS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>重要ニュース - 時事通信</title>
<link>https://news.google.com/rss/articles/abc123</link>
<description>&lt;a href="x"&gt;概要&lt;/a&gt;</description></item>
</channel></rss>""".encode("utf-8")


class TestCollectV2(unittest.TestCase):
    def test_parse_rdf_rss10(self):
        arts = collect.parse_feed(RDF_SAMPLE, "RDFSrc")
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].title, "RDF&記事")  # エンティティ復元
        self.assertEqual(arts[0].link, "https://example.jp/a1")
        self.assertEqual(arts[0].published, "2026-07-08T06:00:00+09:00")

    def test_google_news_title_source_stripped(self):
        arts = collect.parse_feed(GNEWS_SAMPLE, "時事通信")
        self.assertEqual(arts[0].title, "重要ニュース")  # 「 - 時事通信」除去
        self.assertEqual(arts[0].summary, "概要")

    def test_non_google_title_untouched(self):
        # 通常フィードでは「 - 」を含むタイトルを削らない
        arts = collect.parse_feed(RSS_SAMPLE, "S")
        self.assertEqual(arts[0].title, "RSS Article 1")
        self.assertEqual(
            collect._clean_google_news_title("A - B", "https://example.com/x"), "A - B")

    def test_gzip_response_decompressed(self):
        import gzip as _gz

        class GzResp:
            def read(self):
                return _gz.compress(RSS_SAMPLE)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=GzResp()):
            data = collect.fetch_url("https://example.com/feed")
        self.assertEqual(len(collect.parse_feed(data, "S")), 2)

    def test_max_items_per_feed(self):
        with mock.patch.object(collect, "fetch_url", lambda u, timeout=20: RSS_SAMPLE):
            arts = collect.collect_all(
                [{"name": "S", "url": "https://x", "max_items": 1}],
                logger=lambda *a: None)
        self.assertEqual(len(arts), 1)


class TestBalancedSelection(unittest.TestCase):
    def test_round_robin_prevents_monopoly(self):
        arts = ([collect.Article(f"a{i}", f"https://a/{i}", "A") for i in range(10)]
                + [collect.Article(f"b{i}", f"https://b/{i}", "B") for i in range(3)]
                + [collect.Article(f"c{i}", f"https://c/{i}", "C") for i in range(3)])
        picked = main.select_balanced(arts, 6)
        counts = {}
        for a in picked:
            counts[a.source] = counts.get(a.source, 0) + 1
        self.assertEqual(counts, {"A": 2, "B": 2, "C": 2})

    def test_fills_when_some_sources_short(self):
        arts = ([collect.Article(f"a{i}", f"https://a/{i}", "A") for i in range(10)]
                + [collect.Article("b0", "https://b/0", "B")])
        picked = main.select_balanced(arts, 6)
        self.assertEqual(len(picked), 6)
        self.assertEqual(sum(1 for a in picked if a.source == "B"), 1)


class TestSummarize(unittest.TestCase):
    def test_call_claude_success(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeHTTPResponse(fake_api_response("要約です"))):
            out = summarize.call_claude("m", "sys", "user", api_key="k")
        self.assertEqual(out, "要約です")

    def test_retry_on_429_then_success(self):
        calls = {"n": 0}

        def flaky(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    summarize.API_URL, 429, "rate", {}, io.BytesIO(b"slow down"))
            return FakeHTTPResponse(fake_api_response("ok"))

        with mock.patch("urllib.request.urlopen", flaky):
            out = summarize.call_claude("m", "s", "u", api_key="k", sleep=lambda s: None)
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 2)

    def test_non_retryable_error_raises(self):
        def bad(req, timeout=None):
            raise urllib.error.HTTPError(
                summarize.API_URL, 400, "bad", {}, io.BytesIO(b"invalid"))
        with mock.patch("urllib.request.urlopen", bad):
            with self.assertRaises(summarize.SummarizeError):
                summarize.call_claude("m", "s", "u", api_key="k", sleep=lambda s: None)

    def test_missing_api_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(summarize.SummarizeError):
                summarize.call_claude("m", "s", "u")

    def test_article_falls_back_to_editor_model(self):
        used = []

        def selective(model, system, user, max_tokens=1024, **kw):
            used.append(model)
            if model == summarize.MODEL_CHEAP:
                raise summarize.SummarizeError("haiku down")
            return "sonnet要約"

        with mock.patch.object(summarize, "call_claude", selective):
            out = summarize.summarize_article("t", "b", "s")
        self.assertEqual(out, "sonnet要約")
        self.assertEqual(used, [summarize.MODEL_CHEAP, summarize.MODEL_EDITOR])


class TestNotify(unittest.TestCase):
    def test_chunking_respects_limit(self):
        text = "\n".join(f"line {i} " + "x" * 100 for i in range(100))
        chunks = notify._chunk_text(text)
        self.assertTrue(all(len(c) <= notify.MAX_TEXT_PER_BLOCK for c in chunks))
        self.assertEqual("".join(chunks), text)

    def test_build_blocks(self):
        blocks = notify.build_blocks("hello", "2026-07-08")
        self.assertEqual(blocks[0]["type"], "header")
        self.assertEqual(blocks[1]["text"]["text"], "hello")
        self.assertEqual(blocks[-1]["type"], "divider")

    def test_post_success(self):
        captured = {}

        def fake_open(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return FakeHTTPResponse(b"ok")

        with mock.patch("urllib.request.urlopen", fake_open):
            notify.post_to_slack("digest", "2026-07-08", webhook_url="https://hooks.slack.test/x")
        self.assertIn("blocks", captured["body"])

    def test_post_missing_webhook(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(notify.NotifyError):
                notify.post_to_slack("d", "2026-07-08")


class TestMainPipeline(unittest.TestCase):
    def _run(self, tmpdir, first=True):
        state_path = tmpdir / "state.json"
        logs = []
        with mock.patch.object(main, "STATE_PATH", state_path), \
             mock.patch.object(collect, "fetch_url", lambda u, timeout=20: RSS_SAMPLE), \
             mock.patch.object(summarize, "call_claude",
                               lambda *a, **k: "モック要約"), \
             mock.patch("time.sleep", lambda s: None):
            code = main.run(dry_run=True, logger=logs.append)
        return code, logs, state_path

    def test_e2e_dry_run_and_dedupe(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            code, logs, state_path = self._run(tmp)
            self.assertEqual(code, 0)
            self.assertTrue(any("DRY-RUN" in l for l in logs))
            self.assertTrue(state_path.exists())
            # 2回目: 同じ記事は既読なので通知スキップ
            code2, logs2, _ = self._run(tmp)
            self.assertEqual(code2, 0)
            self.assertTrue(any("新着なし" in l for l in logs2))

    def test_all_feeds_down_returns_error(self):
        import tempfile
        from pathlib import Path

        def down(u, timeout=20):
            raise urllib.error.URLError("offline")

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(main, "STATE_PATH", Path(d) / "state.json"), \
                 mock.patch.object(collect, "fetch_url", down):
                code = main.run(dry_run=True, logger=lambda *a: None)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
