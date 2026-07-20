"""Slack Incoming Webhookへの通知。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MAX_TEXT_PER_BLOCK = 2900  # Slackのsectionブロック上限3000文字に対する安全マージン


class NotifyError(RuntimeError):
    pass


def _chunk_text(text: str, limit: int = MAX_TEXT_PER_BLOCK) -> list[str]:
    """改行境界を優先して分割する。"""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # 1行が上限超えの異常系も救う
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks or [""]


def build_blocks(digest_text: str, date_label: str) -> list[dict]:
    blocks: list[dict] = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"📰 朝のニュースダイジェスト {date_label}", "emoji": True},
    }]
    for chunk in _chunk_text(digest_text):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    blocks.append({"type": "divider"})
    return blocks


def build_blocks_from_items(items: list[dict], date_label: str) -> list[dict]:
    """記事ごとに独立した section + divider を積み、読みやすく区切る。"""
    blocks: list[dict] = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"📰 朝のニュース速報 {date_label}", "emoji": True},
    }]
    for i in items:
        text = f"*{i['title']}*({i['source']})\n{i['summary']}\n<{i['url']}|記事を読む>"
        for chunk in _chunk_text(text):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
        blocks.append({"type": "divider"})
    return blocks


def post_to_slack(digest_text: str, date_label: str,
                  webhook_url: str | None = None,
                  items: list[dict] | None = None) -> None:
    webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise NotifyError("SLACK_WEBHOOK_URL が未設定です")

    blocks = build_blocks_from_items(items, date_label) if items else build_blocks(digest_text, date_label)

    payload = json.dumps({
        "text": f"朝のニュースダイジェスト {date_label}",  # 通知プレビュー用フォールバック
        "blocks": blocks,
        "unfurl_links": False,  # URL先の画像/リンクプレビューを抑制
        "unfurl_media": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            if resp.status >= 300 or body.strip() not in ("ok", ""):
                raise NotifyError(f"Slack応答異常: {resp.status} {body[:200]}")
    except urllib.error.HTTPError as e:
        raise NotifyError(f"Slack送信失敗 {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
    except urllib.error.URLError as e:
        raise NotifyError(f"Slack接続失敗: {e}") from e
