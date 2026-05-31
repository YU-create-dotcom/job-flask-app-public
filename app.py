from flask import Flask, render_template, jsonify, request, redirect, url_for
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from openai import OpenAI
import os

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError:
    gspread = None
    ServiceAccountCredentials = None


load_dotenv()

app = Flask(__name__)

# =========================
# SQLite設定
# =========================
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gd_logs.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# =========================
# OpenAI設定
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# Google Sheets設定
# =========================
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "シート1")

MAIL_SPREADSHEET_ID = os.getenv("MAIL_SPREADSHEET_ID")
MAIL_SHEET_NAME = os.getenv("MAIL_SHEET_NAME", "就活管理")


def get_gspread_client():
    if gspread is None or ServiceAccountCredentials is None:
        return None

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        GOOGLE_CREDENTIALS_FILE,
        scope
    )
    return gspread.authorize(creds)


def get_sheet(spreadsheet_id, sheet_name):
    if not spreadsheet_id:
        return None

    client = get_gspread_client()
    if client is None:
        return None

    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet.worksheet(sheet_name)


# =========================
# DBモデル
# =========================
class GDLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    log_type = db.Column(db.String(20), nullable=False)
    company = db.Column(db.String(100))
    theme = db.Column(db.String(200))
    role = db.Column(db.String(100))
    situation = db.Column(db.Text)
    my_action = db.Column(db.Text)
    result = db.Column(db.Text)
    reflection = db.Column(db.Text)
    ai_feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


class SelfProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


# =========================
# 日付変換
# =========================
def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    formats = [
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


# =========================
# トップページ
# =========================
@app.route("/")
def index():
    return render_template("index.html")


# =========================
# Google Sheets → カレンダー予定API
# =========================
@app.route("/api/events")
def api_events():
    sheet = get_sheet(SPREADSHEET_ID, SHEET_NAME)

    if sheet is None:
        return jsonify([])

    rows = sheet.get_all_values()
    events = []

    for row in rows[1:]:
        company = row[1] if len(row) > 1 else ""
        completed = row[3] if len(row) > 3 else ""
        summary = row[6] if len(row) > 6 else ""
        deadline = row[7] if len(row) > 7 else ""
        join_date = row[8] if len(row) > 8 else ""

        if not company:
            continue

        is_incomplete = str(completed).upper() in ["FALSE", "NO", "未完了", ""]

        deadline_dt = parse_date(deadline)
        if deadline_dt:
            events.append({
                "title": f"{company}：ES締切",
                "company": company,
                "category": "ES締切",
                "summary": summary,
                "date": deadline_dt.strftime("%Y-%m-%d"),
                "time": deadline_dt.strftime("%H:%M"),
                "incomplete": is_incomplete
            })

        join_dt = parse_date(join_date)
        if join_dt:
            events.append({
                "title": f"{company}：インターン",
                "company": company,
                "category": "インターン",
                "summary": summary,
                "date": join_dt.strftime("%Y-%m-%d"),
                "time": join_dt.strftime("%H:%M"),
                "incomplete": False
            })

    return jsonify(events)


@app.route("/api/mails")
def api_mails():
    mail_sheet = get_sheet(MAIL_SPREADSHEET_ID, MAIL_SHEET_NAME)

    if mail_sheet is None:
        return jsonify([])

    rows = mail_sheet.get_all_values()
    mails = []

    for row in rows[1:]:
        mails.append({
            "received_at": row[0] if len(row) > 0 else "",
            "company": row[1] if len(row) > 1 else "",
            "subject": row[2] if len(row) > 2 else "",
            "category": row[3] if len(row) > 3 else "",
            "deadline": row[4] if len(row) > 4 else "",
            "snippet": row[5] if len(row) > 5 else "",
            "gmail_url": row[6] if len(row) > 6 else "",
            "message_id": row[7] if len(row) > 7 else "",
            "status": row[8] if len(row) > 8 else "",
        })

    return jsonify(mails[:20])


@app.route("/api/mails/all")
def api_mails_all():
    mail_sheet = get_sheet(MAIL_SPREADSHEET_ID, MAIL_SHEET_NAME)

    if mail_sheet is None:
        return jsonify([])

    rows = mail_sheet.get_all_values()
    return jsonify(rows)


@app.route("/mail/details")
def mail_details():
    mail_sheet = get_sheet(MAIL_SPREADSHEET_ID, MAIL_SHEET_NAME)

    if mail_sheet is None:
        rows = [["受信日時", "企業名", "件名", "分類", "締切", "本文", "URL", "ID", "状態"]]
    else:
        rows = mail_sheet.get_all_values()

    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>受信メール詳細</title>
        <style>
            body {
                font-family: sans-serif;
                margin: 0;
                padding: 12px 16px;
                background: #f5f5f5;
            }

            h1 {
                font-size: 24px;
                margin: 0 0 12px;
            }

            .table-wrap {
                width: 100%;
                height: calc(100vh - 80px);
                overflow: auto;
                background: white;
                border: 1px solid #ccc;
            }

            table {
                border-collapse: collapse;
                table-layout: fixed;
                width: 1800px;
                font-size: 12px;
            }

            th, td {
                border: 1px solid #ccc;
                padding: 4px 6px;
                vertical-align: top;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                height: 24px;
                cursor: pointer;
            }

            th {
                background: #d9ead3;
                position: sticky;
                top: 0;
                z-index: 2;
            }

            tr:nth-child(even) {
                background: #fafafa;
            }

            th:nth-child(1), td:nth-child(1) { width: 130px; }
            th:nth-child(2), td:nth-child(2) { width: 180px; }
            th:nth-child(3), td:nth-child(3) { width: 360px; }
            th:nth-child(4), td:nth-child(4) { width: 90px; }
            th:nth-child(5), td:nth-child(5) { width: 120px; }
            th:nth-child(6), td:nth-child(6) { width: 620px; }
            th:nth-child(7), td:nth-child(7) { width: 160px; }
            th:nth-child(8), td:nth-child(8) { width: 160px; }
            th:nth-child(9), td:nth-child(9) { width: 90px; }

            .cell-modal {
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.4);
                align-items: center;
                justify-content: center;
                z-index: 999;
            }

            .cell-modal-content {
                background: white;
                width: 70vw;
                max-height: 70vh;
                overflow-y: auto;
                padding: 20px;
                border-radius: 8px;
                font-size: 15px;
                line-height: 1.6;
                white-space: pre-wrap;
            }

            .close-btn {
                float: right;
                font-size: 18px;
                cursor: pointer;
                border: none;
                background: #eee;
                padding: 4px 10px;
            }
        </style>
    </head>
    <body>
        <h1>受信メール詳細</h1>

        <div class="table-wrap">
            <table>
    """

    for i, row in enumerate(rows):
        html += "<tr>"
        for j, cell in enumerate(row):
            tag = "th" if i == 0 else "td"
            safe_cell = str(cell).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            if j == 6 and str(cell).startswith("http"):
                html += f'<{tag} title="{safe_cell}"><a href="{safe_cell}" target="_blank">Gmailで開く</a></{tag}>'
            else:
                html += f'<{tag} onclick="showCellText(this)" title="{safe_cell}">{safe_cell}</{tag}>'
        html += "</tr>"

    html += """
            </table>
        </div>

        <div id="cellModal" class="cell-modal" onclick="closeCellText()">
            <div class="cell-modal-content" onclick="event.stopPropagation()">
                <button class="close-btn" onclick="closeCellText()">×</button>
                <div id="cellText"></div>
            </div>
        </div>

        <script>
            function showCellText(cell) {
                const text = cell.innerText;
                document.getElementById("cellText").innerText = text;
                document.getElementById("cellModal").style.display = "flex";
            }

            function closeCellText() {
                document.getElementById("cellModal").style.display = "none";
            }
        </script>
    </body>
    </html>
    """

    return html


# =========================
# GD・面接ログ追加
# =========================
@app.route("/gd/new", methods=["GET", "POST"])
def gd_new():
    if request.method == "POST":
        log = GDLog(
            log_type=request.form.get("log_type", ""),
            company=request.form.get("company", ""),
            theme=request.form.get("theme", ""),
            role=request.form.get("role", ""),
            situation=request.form.get("situation", ""),
            my_action=request.form.get("my_action", ""),
            result=request.form.get("result", ""),
            reflection=request.form.get("reflection", "")
        )
        db.session.add(log)
        db.session.commit()
        return redirect(url_for("gd_logs"))

    return render_template("gd_form.html")


# =========================
# GD・面接ログ一覧
# =========================
@app.route("/gd/logs")
def gd_logs():
    logs = GDLog.query.order_by(GDLog.created_at.desc()).all()
    return render_template("gd_logs.html", logs=logs)


@app.route("/gd/detail/<int:log_id>")
def gd_detail(log_id):
    log = GDLog.query.get_or_404(log_id)
    return render_template("gd_detail.html", log=log)


# =========================
# 自己分析情報
# =========================
@app.route("/self-profile", methods=["GET", "POST"])
def self_profile():
    if request.method == "POST":
        profile = SelfProfile(
            category=request.form.get("category", ""),
            title=request.form.get("title", ""),
            content=request.form.get("content", "")
        )
        db.session.add(profile)
        db.session.commit()
        return redirect(url_for("self_profile"))

    profiles = SelfProfile.query.order_by(SelfProfile.created_at.desc()).all()

    categories = [
        "学チカ",
        "強み",
        "弱み",
        "就活の軸",
        "苦しかった経験",
        "小中高の部活・習い事",
        "その他"
    ]

    return render_template(
        "self_profile.html",
        profiles=profiles,
        categories=categories
    )


# =========================
# AIフィードバック
# =========================
@app.route("/gd/feedback/<int:log_id>")
def gd_feedback(log_id):
    log = GDLog.query.get_or_404(log_id)

    if log.ai_feedback:
        return render_template("gd_feedback.html", log=log, feedback=log.ai_feedback)

    if openai_client is None:
        feedback = "OPENAI_API_KEY が設定されていないため、AIフィードバックは利用できません。"
        return render_template("gd_feedback.html", log=log, feedback=feedback)

    prompt = f"""
あなたは就活のGD・面接対策コーチです。
以下の記録をもとに、評価者視点で具体的にフィードバックしてください。

【種類】
{log.log_type}

【企業名】
{log.company}

【テーマ】
{log.theme}

【自分の役割】
{log.role}

【状況】
{log.situation}

【自分の発言・行動】
{log.my_action}

【結果】
{log.result}

【反省】
{log.reflection}

出力は必ず以下の形式にしてください。

【1. 良かった点】
箇条書きで具体的に。

【2. 評価されやすいポイント】
評価者がどこを見ているかを具体的に。

【3. 改善点】
次回改善すべき行動を具体的に。

【4. 次回使える発言例】
そのままGDで使える発言例を複数。

【5. 面接や自己PRに転用できる強み】
この経験をどう自己PRに使えるか。

【6. 次回意識すべき行動】
次のGD・面接で意識すること。
"""

    try:
        response = openai_client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            input=prompt
        )
        feedback = response.output_text

        log.ai_feedback = feedback
        db.session.commit()

    except Exception as e:
        feedback = f"AIフィードバックの取得中にエラーが発生しました。\n\n{e}"

    return render_template("gd_feedback.html", log=log, feedback=feedback)


# =========================
# 起動
# =========================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000,
        use_reloader=False
    )