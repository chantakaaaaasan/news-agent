# SLACK_SETUP.md — Slack通知の仕組みを作る完全マニュアル

このエージェントからSlackへ通知を届けるまでの手順書。所要時間は約10分。Slackの管理権限(アプリのインストール許可)が必要。

## 全体像

```
news-agent ──HTTPS POST──▶ Incoming Webhook URL ──▶ 指定チャンネルに投稿
```

「Incoming Webhook」は、URLに対してJSONをPOSTするだけでメッセージを投稿できるSlackの仕組み。ボットトークンや複雑な権限設定は不要で、このエージェントの用途(一方向の通知)には最適。

---

## 手順1: Slackアプリを作成する

1. ブラウザで https://api.slack.com/apps を開く(通知先ワークスペースにログインした状態で)
2. **「Create New App」** をクリック
3. **「From scratch」** を選択
4. 以下を入力して **「Create App」**:
   - App Name: `朝のニュースダイジェスト`(任意の名前でよい)
   - Pick a workspace: 通知を届けたいワークスペースを選択

## 手順2: Incoming Webhookを有効化する

1. 作成したアプリの設定画面で、左メニューの **「Incoming Webhooks」** をクリック
2. 右上のトグルを **On** に切り替える
3. ページ下部の **「Add New Webhook to Workspace」** をクリック
4. 投稿先チャンネル(例: `#news-digest`)を選択して **「許可する」**
   - 専用チャンネルを事前に作っておくことを推奨(通知が流れて他の会話を邪魔しない)
5. 発行された **Webhook URL** をコピーする。形式は次の通り:
   ```
   https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX
   ```

> ⚠️ **このURLは秘密情報。** URLを知っている人は誰でもそのチャンネルに投稿できる。コード・config.json・Gitリポジトリに書かない。漏れた場合はアプリ設定画面からWebhookを削除して再発行する。

## 手順3: 疎通確認(エージェントを動かす前に単体で)

ターミナルから直接POSTして、チャンネルに届くことを確認する:

```bash
curl -X POST -H 'Content-Type: application/json' \
  -d '{"text": "疎通テスト: news-agentからの通知です"}' \
  https://hooks.slack.com/services/T.../B.../XXX...
```

- チャンネルに「疎通テスト」が届けばOK(応答は `ok` の3文字)
- `invalid_token` / `no_service` → URLのコピーミスか失効。手順2からやり直す
- `channel_not_found` → 連携先チャンネルが削除されている。Webhookを再発行する

## 手順4: エージェントに環境変数として渡す

### ローカル実行の場合
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../XXX..."
export ANTHROPIC_API_KEY="sk-ant-..."
python3 -m news_agent.main --dry-run   # まず送信せず内容確認
python3 -m news_agent.main             # 本番送信
```

### cron実行の場合
crontab内で直接定義する(cronはシェルの環境変数を引き継がない点に注意):
```cron
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../XXX...
ANTHROPIC_API_KEY=sk-ant-...
0 7 * * * cd /path/to/news-agent && /usr/bin/python3 -m news_agent.main >> cron.log 2>&1
```

### GitHub Actionsの場合
1. リポジトリの **Settings → Secrets and variables → Actions → New repository secret**
2. `SLACK_WEBHOOK_URL` と `ANTHROPIC_API_KEY` を登録
3. `.github/workflows/daily-news.yml` が自動で参照する(編集不要)
4. **Actionsタブ → daily-news-digest → Run workflow** で手動実行し、Slack到達を確認

## 手順5: 通知の見た目を確認する

初回の本番実行後、Slackで以下を確認:

- ヘッダー「📰 朝のニュースダイジェスト YYYY-MM-DD」が表示されている
- 記事が「• *タイトル*(媒体名)+ 要約 + 記事リンク」の形で並んでいる
- リンクをクリックすると記事に飛べる(Google News経由の記事はリダイレクトを挟む。正常)

---

## 実装の仕組み(触る人向け)

通知の実体は `news_agent/notify.py`。押さえるべき仕様は3つ:

1. **Block Kit形式で送っている。** `header` ブロック+ `section`(mrkdwn)ブロックの構成。`text` フィールドも併送しており、これはスマホのプッシュ通知プレビューに使われる。
2. **1ブロック2,900文字で自動分割。** Slackのsectionブロックは3,000文字上限のため、`_chunk_text()` が改行境界で分割する。長いダイジェストでも送信エラーにならない。
3. **失敗はNotifyError例外。** main.py側で捕捉され、**送信失敗時はstate.json(既読)を保存しない**ため、次回実行時に同じ記事が再送される(通知の取りこぼし防止)。

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `SLACK_WEBHOOK_URL が未設定です` | 環境変数が渡っていない | 手順4を再確認。cronは特に注意 |
| `Slack送信失敗 403: invalid_token` | URL失効(アプリ削除・再インストール等) | 手順2で再発行し環境変数を更新 |
| `Slack送信失敗 404: no_service` | URLの打ち間違い | コピーし直す |
| 届くが文字化けする | (通常起きない)自前改造でエンコード指定を変えた | `Content-Type: application/json` のまま、UTF-8で送る |
| 毎日同じ記事が再送される | 送信は成功しているがstate.jsonが保存されていない | 実行ディレクトリの書き込み権限、GitHub Actionsならstate.jsonコミットのステップを確認 |
| チャンネルを変えたい | Webhookはチャンネル固定 | 新しいチャンネル向けWebhookを発行し、環境変数を差し替える |

## セキュリティの要点

- Webhook URLとAPIキーは**環境変数のみ**。`git diff` にこれらの文字列が出たらコミットしない
- リポジトリを公開する場合、過去コミットに秘密情報が混ざっていないか確認(`git log -p | grep hooks.slack.com`)
- Webhookは投稿専用で、チャンネルの読み取りはできない(漏洩時の被害は「スパム投稿される」に限定される)。それでも漏れたら即再発行
