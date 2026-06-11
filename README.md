# 就活管理ダッシュボード

就職活動に関する予定、メール、GD・面接ログ、自己分析を一元管理するために開発した Flask 製のWebアプリです。

公開用リポジトリのため、APIキー、Google認証情報、スプレッドシートID、実際の就活データ、メール本文、データベースファイルは含めていません。

## 主な機能

- Google Sheets の予定データをもとにしたカレンダー表示
- Gmail連携データの一覧表示
- GD・面接ログの登録、一覧、詳細表示、削除
- 自己分析情報の登録、一覧、詳細表示、削除
- OpenAI API を使った GD・面接ログへのAIフィードバック
- 自己分析情報を参照した個別最適化フィードバック

## 使用技術

### バックエンド

- Python
- Flask
- Flask-SQLAlchemy
- SQLite

### フロントエンド

- HTML
- CSS
- JavaScript

### 外部サービス・API

- OpenAI API
- Google Sheets API
- Gmail / Google Apps Script

## ディレクトリ構成

```text
.
├─ app.py
├─ requirements.txt
├─ .env.example
├─ static/
│  └─ style.css
└─ templates/
   ├─ index.html
   ├─ gd_form.html
   ├─ gd_logs.html
   ├─ gd_detail.html
   ├─ gd_feedback.html
   └─ self_profile.html
```

## セットアップ

### 1. リポジトリを取得

```bash
git clone https://github.com/YU-create-dotcom/job-flask-app-public.git
cd job-flask-app-public
```

### 2. 仮想環境を作成

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. ライブラリをインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数を設定

`.env.example` を参考に `.env` を作成し、自分の環境の値を設定します。

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5
GOOGLE_CREDENTIALS_FILE=credentials.json
SPREADSHEET_ID=
SHEET_NAME=シート1
MAIL_SPREADSHEET_ID=
MAIL_SHEET_NAME=就活管理
```

Google Sheets / Gmail 連携を使わない場合でも、アプリ自体は空データ表示で起動できます。

### 5. アプリを起動

```bash
python app.py
```

ブラウザで `http://127.0.0.1:5000` を開きます。

## セキュリティ上の扱い

この公開版では、以下のファイルや情報をリポジトリに含めない方針にしています。

- `.env`
- `credentials.json`
- `service_account.json`
- Google / Firebase / OpenAI の認証情報
- スプレッドシートIDなどの実運用ID
- SQLiteデータベース
- CSV、Excelなどの実データ
- 実際の企業名、選考情報、メール本文、個人情報

## 工夫した点

- 就活で散らばりやすい予定、メール、面接ログ、自己分析を1画面に集約しました。
- Google Sheets を予定管理のデータソースとして利用し、Web画面のカレンダーへ反映できる構成にしました。
- Gmailから取得した就活関連メールを一覧化し、締切や対応状況を把握しやすくしました。
- GD・面接ログと自己分析情報を組み合わせ、OpenAI APIで具体的な振り返りを生成する設計にしました。
- 公開用には認証情報や実データを環境変数・ローカルファイルに分離し、GitHub上に出さない構成にしています。

## 今後の改善予定

- モバイル表示の最適化
- デプロイ対応
- ダミーデータによるデモ画面の整備
- 統計・可視化機能の追加
- Google Apps Script 側コードのサンプル化

## 補足

このリポジトリはポートフォリオ公開用です。実際の認証情報、Gmail取得データ、企業の選考情報、個人の就活ログは含まれていません。
