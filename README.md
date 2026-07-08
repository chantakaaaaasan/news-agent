# news-agent 📰

毎朝ニュースを収集・AI要約してSlackに通知するエージェント。**依存ライブラリゼロ**(Python標準ライブラリのみ)。

## コスト設計

| 工程 | モデル | 頻度 |
|---|---|---|
| 記事1本の要約 | Claude Haiku(安価) | 最大10回/日 |
| ダイジェスト編集 | Claude Sonnet | 1回/日 |

上位モデルは実行時に不要。モデルは環境変数 `NEWS_MODEL_CHEAP` / `NEWS_MODEL_EDITOR` で差し替え可能。

## クイックスタート

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

python3 -m unittest discover -s tests   # 全23テスト
python3 -m news_agent.main --dry-run    # Slackに送らず確認
python3 -m news_agent.main              # 本番送信
```

毎朝の自動実行は `.github/workflows/daily-news.yml`(GitHub Actions、JST 7:00)か、cron:

```cron
0 7 * * * cd /path/to/news-agent && python3 -m news_agent.main >> cron.log 2>&1
```

## ファイル構成

- `config.json` — フィード一覧・記事数上限・タイムゾーン
- `state.json` — 既読管理(自動生成、7日でTTL掃除)
- `SLACK_SETUP.md` — Slack通知の仕組みを作る完全マニュアル
- `CLAUDE.md` — AI(Sonnet/Haiku含む)向けの構築・修正・運用規約
- `CHECKLIST.md` — セットアップ〜運用のチェックリスト

詳しい運用・トラブルシュートは **CLAUDE.md** と **CHECKLIST.md** を参照。
