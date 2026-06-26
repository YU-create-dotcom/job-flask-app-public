# 就活管理ダッシュボード

就職活動の予定、メール、GD・面接ログ、自己分析、企業研究を一元管理するために開発した Flask 製Webアプリです。

このリポジトリは企業提出用の公開版です。APIキー、Google認証情報、スプレッドシートID、実際の就活データ、メール本文、データベースファイルは含めていません。

## 主な機能

- Google Sheets の予定データをもとにしたカレンダー表示
- Gmail / Google Apps Script で整理した就活メールの一覧表示
- GD・面接ログの登録、一覧、詳細表示、削除
- OpenAI API によるGD・面接ログへの厳しめのAIフィードバック
- 自己分析情報の登録、カテゴリ管理、削除
- 自己分析内容を参照した個別最適化フィードバック
- 企業研究メモの登録、編集、削除
- OpenAI利用額 / 残高の簡易メーター
- Renderデプロイ向けの起動設定とデータ移行補助

## 使用技術

- Python / Flask
- Flask-SQLAlchemy
- SQLite / PostgreSQL対応
- HTML / CSS / JavaScript
- OpenAI API
- Google Sheets API
- Gmail / Google Apps Script
- Gunicorn / Render

## ディレクトリ構成

```text
.
├─ app.py
├─ export_app_data.py
├─ requirements.txt
├─ Procfile
├─ gunicorn.conf.py
├─ DEPLOY_RENDER.md
├─ .env.example
├─ static/
│  └─ style.css
└─ templates/
   ├─ _openai_credit_meter.html
   ├─ company_research.html
   ├─ gd_detail.html
   ├─ gd_feedback.html
   ├─ gd_form.html
   ├─ gd_logs.html
   ├─ index.html
   └─ self_profile.html
```

## セットアップ

```bash
git clone https://github.com/YU-create-dotcom/job-flask-app-public.git
cd job-flask-app-public
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`.env.example` を参考に `.env` を作成します。

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5
GOOGLE_CREDENTIALS_FILE=credentials.json
SPREADSHEET_ID=
SHEET_NAME=シート1
MAIL_SPREADSHEET_ID=
MAIL_SHEET_NAME=就活管理
```

Google Sheets / Gmail連携を設定しなくても、該当APIは空データを返すため、アプリ本体は起動できます。

```bash
python app.py
```

ブラウザで `http://127.0.0.1:5000` を開きます。

## セキュリティ上の扱い

公開版では、以下をGitHubに含めない方針にしています。

- `.env`
- `credentials.json`
- `service_account.json`
- Google / Firebase / OpenAI の認証情報
- スプレッドシートIDなどの実運用ID
- SQLiteデータベース
- CSV、Excelなどの実データ
- 実際の企業名、選考情報、メール本文、個人情報

## 工夫した点

- 就活で散らばりやすい予定、メール、面接ログ、自己分析、企業研究を1つの画面体験にまとめました。
- 外部データ連携は環境変数とローカル認証ファイルへ分離し、公開リポジトリに秘密情報を残さない構成にしました。
- AIフィードバックでは、単なる励ましではなく、評価軸、点数、改善案、深掘り質問まで出力するプロンプトを設計しました。
- ローカルSQLiteからRender向けPostgreSQL構成へ移しやすいよう、データエクスポートとインポート用の仕組みを用意しました。
- モバイルでも使えるよう、ダッシュボードやナビゲーションのレスポンシブ表示を調整しています。

## デプロイ

Renderへのデプロイ手順は [DEPLOY_RENDER.md](DEPLOY_RENDER.md) を参照してください。

## 補足

このリポジトリはポートフォリオ公開用です。実際の認証情報、Gmail取得データ、企業の選考情報、個人の就活ログは含まれていません。
