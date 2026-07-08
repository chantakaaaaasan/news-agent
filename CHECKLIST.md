# CHECKLIST.md — 構築・運用チェックリスト

Sonnet/Haiku級のモデル(または人間)が、このシステムをゼロから立ち上げ・変更・運用するときに上から潰していくリスト。

## A. 初回セットアップ

- [ ] Python 3.10+ が入っている(`python3 --version`)
- [ ] `pip install` を一度もしていない(依存ゼロが正常。必要になったら設計ミスを疑う)
- [ ] `config.json` のフィードURLをブラウザ/`curl`で開き、XMLが返ることを全6媒体分確認した(CNN/BBCは公式RSS、ロイター/Bloomberg/時事/福島民友はGoogle News経由。理由はCLAUDE.md §2.5)
- [ ] Google News経由の4媒体で記事が0件でないことを確認した(0件なら `when:24h` → `when:48h` に緩める)
- [ ] `ANTHROPIC_API_KEY` を環境変数に設定した(コードに書いていない)
- [ ] **SLACK_SETUP.md の手順1〜3** でWebhookを発行し、`curl` での疎通テストが通った
- [ ] `SLACK_WEBHOOK_URL` を環境変数に設定した
- [ ] `python3 -m unittest discover -s tests` が全件GREEN
- [ ] `python3 -m news_agent.main --dry-run` がexit 0で、ダイジェストが標準出力に表示された
- [ ] dry-runのダイジェストを目視:「1行目サマリー+•箇条書き+リンク」の形式か。崩れていたら CLAUDE.md §5 を適用
- [ ] `rm state.json` してから本番実行 `python3 -m news_agent.main` → Slackに届いた
- [ ] もう一度実行 → 「新着なし」でスキップされた(重複排除の動作確認)

## B. 定期実行の設定(どちらか一方)

### B-1. GitHub Actions(推奨: マシン常時起動が不要)
- [ ] リポジトリのSecretsに `ANTHROPIC_API_KEY` と `SLACK_WEBHOOK_URL` を登録した
- [ ] `.github/workflows/daily-news.yml` のcron(UTC)が意図の現地時刻と一致している(JST 7:00 = UTC 22:00)
- [ ] Actionsタブから `workflow_dispatch` で手動実行し、Slack到達を確認した
- [ ] 実行後に `state.json` がbotコミットされている

### B-2. ローカルcron
- [ ] `crontab -e` に追加: `0 7 * * * cd /path/to/news-agent && /usr/bin/python3 -m news_agent.main >> cron.log 2>&1`
- [ ] cron環境に環境変数が渡っている(crontab内で `ANTHROPIC_API_KEY=...` を定義、またはラッパーシェルで `source`)
- [ ] `cron.log` に翌朝ログが出ていることを確認した

## C. 変更を入れるたび(毎回)

- [ ] 変更前にテストGREENを確認した
- [ ] 変更に対応するテストを追加した(ネットワークは全てモック)
- [ ] テスト全件GREEN
- [ ] `--dry-run` がクラッシュしない
- [ ] 秘密情報がdiffに含まれていない(`git diff` を目視)
- [ ] CLAUDE.md §2 の設計原則(依存ゼロ / モデル役割分担 / state保存順序)を破っていない

## D. 週次の運用点検(5分)

- [ ] 直近7日、毎朝通知が届いている(Actionsの実行履歴 or cron.log)
- [ ] 要約の品質劣化がない(前置き混入・形式崩れがあれば CLAUDE.md §5)
- [ ] APIコストがおおよそ想定内(目安: Haiku 10記事 + Sonnet 1回/日)
- [ ] `state.json` が肥大化していない(7日TTLで自動掃除されるので、数百行超なら異常)
- [ ] 0件のフィードが続いていないか(`[collect] ○○: 0件` が連日なら配信元のURL変更を疑い、公式サイトで新URLを確認)

## E. 障害対応の初動(順番厳守)

1. [ ] `--dry-run` をローカルで実行し、失敗箇所のログ行(`[collect]` / `[main]`)を特定
2. [ ] CLAUDE.md §4 の決定木で該当行を探す
3. [ ] 「キー・URL・外部要因」を先に潰す(コードを触るのは最後)
4. [ ] コード修正が必要なら CLAUDE.md §3 の手順で実施
