"""Anthropic APIでの要約。コスト最適化のためモデルを役割分担する。

- 記事1本の要約: Haiku(安い・大量処理向き)
- 最終ダイジェスト編集: Sonnet(構成力が必要な工程のみ)
高級モデル(Opus/Fable)は実行時に不要。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

MODEL_CHEAP = os.environ.get("NEWS_MODEL_CHEAP", "claude-haiku-4-5-20251001")
MODEL_EDITOR = os.environ.get("NEWS_MODEL_EDITOR", "claude-sonnet-4-6")

MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 529}


class SummarizeError(RuntimeError):
    pass


def call_claude(model: str, system: str, user: str, max_tokens: int = 1024,
                api_key: str | None = None, sleep=time.sleep) -> str:
    """Messages APIを叩く。リトライ可能なエラーは指数バックオフで再試行。"""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SummarizeError("ANTHROPIC_API_KEY が未設定です")

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            result = "\n".join(t for t in texts if t).strip()
            if not result:
                raise SummarizeError(f"空のレスポンス: {data}")
            return result
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in RETRYABLE_STATUS and attempt < MAX_RETRIES - 1:
                sleep(2 ** attempt * 2)
                continue
            raise SummarizeError(f"APIエラー {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                sleep(2 ** attempt * 2)
                continue
    raise SummarizeError(f"リトライ上限到達: {last_err}")


def summarize_article(title: str, body: str, source: str, **kw) -> str:
    """記事1本を日本語2文で要約(Haiku)。失敗時はSonnetにフォールバック。"""
    system = (
        "あなたはニュース編集者です。与えられた記事を日本語で最大2文、"
        "事実のみで要約してください。前置き・意見・絵文字は不要。要約文だけを出力。"
    )
    user = f"媒体: {source}\nタイトル: {title}\n本文抜粋: {body[:1500]}"
    try:
        return call_claude(MODEL_CHEAP, system, user, max_tokens=200, **kw)
    except SummarizeError:
        return call_claude(MODEL_EDITOR, system, user, max_tokens=200, **kw)


def build_digest(items: list[dict], date_label: str, **kw) -> str:
    """全記事要約からSlack向けダイジェストを作る(Sonnet)。"""
    system = (
        "あなたは朝刊ダイジェストの編集長です。入力(JSON)の記事群から、"
        "重要度順に最大10本を選び、Slack向けの日本語ダイジェストを作ってください。\n"
        "出力形式(厳守):\n"
        "1行目: 今日の一言サマリー(30字以内)\n"
        "以降: 各記事を「• *タイトル*(媒体名)\\n  要約1〜2文\\n  <URL|記事を読む>」の形式で。\n"
        "見出し記号(#)やコードブロックは使わない。Slackのmrkdwn記法のみ。"
    )
    user = f"日付: {date_label}\n記事一覧(JSON):\n{json.dumps(items, ensure_ascii=False)}"
    return call_claude(MODEL_EDITOR, system, user, max_tokens=2000, **kw)
