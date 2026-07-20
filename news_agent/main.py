"""毎朝のニュースダイジェスト・パイプライン。

フロー: 収集 → 既読除外 → Slack通知(記事ごとに独立ブロック) → 状態保存
使い方:
    python -m news_agent.main               # 本番実行
    python -m news_agent.main --dry-run     # Slackに送らず標準出力に表示
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import collect, notify

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
STATE_TTL_DAYS = 7


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg.get("feeds"), "config.json の feeds が空です"
    cfg.setdefault("max_articles", 10)
    cfg.setdefault("timezone_offset_hours", 9)  # JST
    return cfg


def load_state(path: Path | None = None) -> dict:
    path = path or STATE_PATH
    if not path.exists():
        return {"seen": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"seen": {}}  # 破損時は作り直す(送信重複より欠損を許容)


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE_PATH
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STATE_TTL_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def select_balanced(articles: list[collect.Article], limit: int) -> list[collect.Article]:
    """媒体間ラウンドロビンで最大limit件を選ぶ(1媒体の独占を防ぐ)。"""
    by_source: dict[str, list[collect.Article]] = {}
    order: list[str] = []
    for a in articles:
        if a.source not in by_source:
            by_source[a.source] = []
            order.append(a.source)
        by_source[a.source].append(a)

    selected: list[collect.Article] = []
    while len(selected) < limit and any(by_source.values()):
        for src in order:
            if by_source[src]:
                selected.append(by_source[src].pop(0))
                if len(selected) >= limit:
                    break
    return selected


def dedupe(articles: list[collect.Article], state: dict) -> list[collect.Article]:
    seen = state.setdefault("seen", {})
    fresh, now = [], datetime.now(timezone.utc).isoformat()
    for a in articles:
        if a.uid in seen:
            continue
        seen[a.uid] = now
        fresh.append(a)
    return fresh


def run(dry_run: bool = False, logger=print) -> int:
    cfg = load_config()
    tz = timezone(timedelta(hours=cfg["timezone_offset_hours"]))
    date_label = datetime.now(tz).strftime("%Y-%m-%d")

    # 1. 収集
    articles = collect.collect_all(cfg["feeds"], logger=logger)
    if not articles:
        logger("[main] 全フィード取得失敗。異常終了します。")
        return 2

    # 2. 既読除外 + 上限
    state = load_state()
    fresh = select_balanced(dedupe(articles, state), cfg["max_articles"])
    if not fresh:
        logger("[main] 新着なし。通知をスキップして正常終了。")
        save_state(state)
        return 0
    logger(f"[main] 新着 {len(fresh)}件を処理します")

    # 3. RSS説明文をそのまま使用(AI要約スキップ = API呼び出し0)
    items = []
    for a in fresh:
        items.append({"title": a.title, "url": a.link, "source": a.source,
                      "summary": a.summary})  # RSS に付属する description をそのまま使う

    # 4. ダイジェストを機械的に組立(dry-run表示用。Slack送信は記事ごとブロックを使う)
    digest = f"📰 朝のニュース速報 {date_label}\n\n" + "\n".join(
        f"• *{i['title']}*({i['source']})\n  {i['summary']}\n  <{i['url']}|記事を読む>"
        for i in items
    )

    # 5. 通知(記事ごとに独立したブロックに分けて読みやすくする)
    if dry_run:
        logger("=" * 40 + f"\n[DRY-RUN] {date_label}\n" + digest + "\n" + "=" * 40)
    else:
        notify.post_to_slack(digest, date_label, items=items)
        logger("[main] Slackに送信完了")

    # 6. 状態保存(送信成功後のみ — 失敗時は次回再送させる)
    save_state(state)
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="朝のニュースダイジェスト")
    parser.add_argument("--dry-run", action="store_true", help="Slackに送らず表示のみ")
    args = parser.parse_args()
    try:
        sys.exit(run(dry_run=args.dry_run))
    except Exception as e:  # noqa: BLE001
        print(f"[main] 致命的エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli()
