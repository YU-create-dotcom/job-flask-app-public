from flask import Flask, render_template, jsonify, request, redirect, session, url_for
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from openai import OpenAI
from urllib import parse, request as url_request
import os
import json
import time
import base64
import unicodedata
import hmac
import secrets
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-before-production")
if os.getenv("RENDER") and app.config["SECRET_KEY"] == "change-this-before-production":
    raise RuntimeError("SECRET_KEY must be configured on Render")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.getenv("RENDER"))

# =========================
# SQLite設定
# =========================
database_url = os.getenv("DATABASE_URL", "sqlite:///gd_logs.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if database_url.startswith("postgresql+"):
    # Render may suspend both the web service and its database. Connections
    # left in SQLAlchemy's pool are then invalid when the service wakes up.
    # Check a pooled connection before using it and replace stale connections
    # automatically instead of returning a one-off 500 response.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

service_database_url = os.getenv("SERVICE_DATABASE_URL", "")
if service_database_url.startswith("postgres://"):
    service_database_url = service_database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif service_database_url.startswith("postgresql://"):
    service_database_url = service_database_url.replace("postgresql://", "postgresql+psycopg://", 1)
if service_database_url:
    app.config["SQLALCHEMY_BINDS"] = {
        "service": {
            "url": service_database_url,
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    }
db = SQLAlchemy(app)

# =========================
# OpenAI設定
# =========================
openai_client = (
    OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=240.0,
        max_retries=1,
    )
    if os.getenv("OPENAI_API_KEY")
    else None
)

JST = ZoneInfo("Asia/Tokyo")


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_jst(value, fmt="%Y-%m-%d %H:%M"):
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JST).strftime(fmt)


app.jinja_env.filters["jst"] = to_jst


def read_float_env(name, default=0):
    try:
        return float(os.getenv(name, default) or default)
    except ValueError:
        return default


OPENAI_CREDIT_LIMIT_USD = read_float_env("OPENAI_MONTHLY_CREDIT_LIMIT_USD")
OPENAI_CREDIT_BALANCE_USD = read_float_env("OPENAI_CREDIT_BALANCE_USD", -1)
OPENAI_CREDIT_CONFIG_PATH = os.path.join(app.instance_path, "openai_credit.json")


def read_manual_credit_config():
    try:
        with open(OPENAI_CREDIT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    balance = data.get("balance")
    limit = data.get("limit")
    return {
        "balance": float(balance) if balance is not None else None,
        "limit": float(limit) if limit is not None else None,
    }


def write_manual_credit_config(balance, limit=None):
    os.makedirs(app.instance_path, exist_ok=True)
    data = {"balance": balance}
    if limit is not None:
        data["limit"] = limit

    with open(OPENAI_CREDIT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# Google Sheets設定
# =========================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

def load_google_credentials():
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    credentials_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")

    if credentials_json:
        credentials_info = json.loads(credentials_json)
        return ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, scope)

    if credentials_base64:
        normalized_base64 = "".join(credentials_base64.strip().split())
        padding = len(normalized_base64) % 4
        if padding:
            normalized_base64 += "=" * (4 - padding)

        try:
            decoded_credentials = base64.b64decode(normalized_base64).decode("utf-8")
            credentials_info = json.loads(decoded_credentials)
        except Exception as exc:
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_BASE64 is invalid. Paste only the Base64 output "
                "generated from credentials.json, not the PowerShell command itself."
            ) from exc
        return ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, scope)

    return ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)


SPREADSHEET_ID = "1aripBFJDo9-RkxrDDRfds7YhRZqvPpzjuTZkjJxshmo"
SHEET_NAME = "シート1"

MAIL_SPREADSHEET_ID = "1cBRZsd6qF64l6pWNN0gFRaboZBDIOB2DCoJs8_aNNBc"
MAIL_SHEET_NAME = "就活管理"

gspread_client = None


def get_gspread_client():
    global gspread_client
    if gspread_client is None:
        creds = load_google_credentials()
        gspread_client = gspread.authorize(creds)
    return gspread_client


def get_event_sheet():
    spreadsheet = get_gspread_client().open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


def get_mail_sheet():
    mail_spreadsheet = get_gspread_client().open_by_key(MAIL_SPREADSHEET_ID)
    return mail_spreadsheet.worksheet(MAIL_SHEET_NAME)


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
    created_at = db.Column(db.DateTime, default=utc_now)

class SelfProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

class SelfProfileCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    position = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

class CompanyResearch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    industry = db.Column(db.String(200))
    business = db.Column(db.Text)
    history = db.Column(db.Text)
    details = db.Column(db.Text)
    features = db.Column(db.Text)
    motivation = db.Column(db.Text)
    career_plan = db.Column(db.Text)
    appeal = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class ServiceUser(db.Model):
    """Read and manage accounts that belong to job-flask-app-service.

    This model deliberately uses a separate database bind. The personal app's
    own records remain in DATABASE_URL; only the service account table is read
    from SERVICE_DATABASE_URL.
    """

    __bind_key__ = "service"
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active_account = db.Column(db.Boolean, default=True, nullable=False)
    ai_balance = db.Column(db.Numeric(10, 6), nullable=False)
    ai_limit = db.Column(db.Numeric(10, 2), nullable=False)
    ai_model = db.Column(db.String(50), nullable=False)
    sheet_id = db.Column(db.String(200))
    sheet_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, nullable=False)


def admin_login_is_valid(login_id, password):
    expected_id = os.getenv("ADMIN_LOGIN_ID", "")
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    return bool(expected_id and expected_password) and hmac.compare_digest(login_id, expected_id) and hmac.compare_digest(password, expected_password)


def service_database_is_configured():
    return bool(service_database_url)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("job_admin_authenticated"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_csrf_token():
    return session.setdefault("job_admin_csrf_token", secrets.token_urlsafe(32))


def require_admin_csrf():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("job_admin_csrf_token", "")
    if not expected or not hmac.compare_digest(submitted, expected):
        raise ValueError("不正な操作です。画面を再読み込みしてからやり直してください。")


MIGRATION_MODELS = {
    "gd_log": (
        GDLog,
        [
            "id", "log_type", "company", "theme", "role", "situation",
            "my_action", "result", "reflection", "ai_feedback", "created_at",
        ],
        ["created_at"],
    ),
    "self_profile": (
        SelfProfile,
        ["id", "category", "title", "content", "created_at"],
        ["created_at"],
    ),
    "self_profile_category": (
        SelfProfileCategory,
        ["id", "name", "position", "created_at"],
        ["created_at"],
    ),
    "company_research": (
        CompanyResearch,
        [
            "id", "company_name", "industry", "business", "history", "details",
            "features", "motivation", "career_plan", "appeal", "created_at", "updated_at",
        ],
        ["created_at", "updated_at"],
    ),
}

DEFAULT_SELF_PROFILE_CATEGORIES = [
    "学チカ",
    "自己PR",
    "強み",
    "弱み",
    "就活の軸",
    "苦しかった経験",
    "最も努力した経験",
    "チームで取り組んだ経験",
    "小中高の部活・習い事",
    "大学のサークル",
    "なりたい大人",
    "キャリアプラン",
    "若手のキャリアプラン",
    "留年の理由",
    "物理は続けないのか",
    "その他",
]


def parse_import_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def decode_import_payload(encoded_payload):
    normalized_payload = "".join((encoded_payload or "").strip().split())
    padding = len(normalized_payload) % 4
    if padding:
        normalized_payload += "=" * (4 - padding)
    decoded_payload = base64.b64decode(normalized_payload).decode("utf-8")
    return json.loads(decoded_payload)


def import_app_data_payload(payload, replace=False):
    if replace:
        for table_name in ("company_research", "self_profile_category", "self_profile", "gd_log"):
            model, _, _ = MIGRATION_MODELS[table_name]
            db.session.query(model).delete()

    imported_counts = {}
    for table_name, (model, allowed_fields, datetime_fields) in MIGRATION_MODELS.items():
        rows = payload.get(table_name, [])
        imported_counts[table_name] = 0

        for row in rows:
            values = {field: row.get(field) for field in allowed_fields if field in row}
            for field in datetime_fields:
                if field in values:
                    values[field] = parse_import_datetime(values[field])

            db.session.merge(model(**values))
            imported_counts[table_name] += 1

    db.session.commit()
    return imported_counts


def ensure_self_profile_categories():
    if SelfProfileCategory.query.count():
        return

    for position, name in enumerate(DEFAULT_SELF_PROFILE_CATEGORIES, start=1):
        db.session.add(SelfProfileCategory(name=name, position=position))
    db.session.commit()


def get_self_profile_categories():
    return SelfProfileCategory.query.order_by(
        SelfProfileCategory.position.asc(),
        SelfProfileCategory.id.asc(),
    ).all()


def normalize_position(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not normalized.isdigit():
        return None
    return int(normalized)


def import_startup_data_if_configured():
    encoded_payload = os.getenv("APP_DATA_IMPORT_BASE64")
    if not encoded_payload:
        return

    existing_count = (
        GDLog.query.count()
        + SelfProfile.query.count()
        + CompanyResearch.query.count()
    )
    replace = os.getenv("APP_DATA_IMPORT_REPLACE", "0") == "1"
    if existing_count and not replace:
        return

    payload = decode_import_payload(encoded_payload)
    import_app_data_payload(payload, replace=replace)


def get_openai_monthly_costs():
    api_key = os.getenv("OPENAI_ADMIN_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI APIキーが設定されていません。"

    now = datetime.now()
    start = datetime(now.year, now.month, 1)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1)
    else:
        end = datetime(now.year, now.month + 1, 1)

    query = parse.urlencode({
        "start_time": int(time.mktime(start.timetuple())),
        "end_time": int(time.mktime(end.timetuple())),
        "bucket_width": "1d",
    })
    api_url = f"https://api.openai.com/v1/organization/costs?{query}"
    req = url_request.Request(
        api_url,
        headers={"Authorization": f"Bearer {api_key}"}
    )

    try:
        with url_request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return None, f"OpenAI使用額を取得できませんでした: {e}"

    total_cost = 0.0
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount", {})
            total_cost += float(amount.get("value", 0) or 0)

    return total_cost, None


@app.route("/api/openai/credit")
def api_openai_credit():
    manual_config = read_manual_credit_config()
    limit = manual_config["limit"] if manual_config["limit"] is not None else OPENAI_CREDIT_LIMIT_USD
    configured_balance = manual_config["balance"]
    if configured_balance is None and OPENAI_CREDIT_BALANCE_USD >= 0:
        configured_balance = OPENAI_CREDIT_BALANCE_USD

    if configured_balance is not None:
        percent = None
        if limit > 0:
            percent = max(0, min(100, (configured_balance / limit) * 100))

        return jsonify({
            "ok": True,
            "source": "configured_balance",
            "balance": round(configured_balance, 4),
            "limit": limit,
            "percent": round(percent, 1) if percent is not None else None,
        })

    used, error = get_openai_monthly_costs()

    if error:
        return jsonify({
            "ok": False,
            "error": error,
            "limit": limit,
        })

    remaining = None
    percent = None
    if limit > 0:
        remaining = max(limit - used, 0)
        percent = max(0, min(100, (remaining / limit) * 100))

    return jsonify({
        "ok": True,
        "source": "organization_costs",
        "used": round(used, 4),
        "limit": limit,
        "balance": round(remaining, 4) if remaining is not None else None,
        "remaining": round(remaining, 4) if remaining is not None else None,
        "percent": round(percent, 1) if percent is not None else None,
    })


@app.route("/api/openai/credit/manual", methods=["POST"])
def api_openai_credit_manual():
    data = request.get_json(silent=True) or {}

    try:
        balance = float(data.get("balance"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "残高を数字で入力してください。"}), 400

    if balance < 0:
        return jsonify({"ok": False, "error": "残高は0以上で入力してください。"}), 400

    limit = data.get("limit")
    if limit in ("", None):
        limit = OPENAI_CREDIT_LIMIT_USD if OPENAI_CREDIT_LIMIT_USD > 0 else None
    else:
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "上限額を数字で入力してください。"}), 400

    write_manual_credit_config(balance, limit)
    return jsonify({"ok": True})

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


def build_sheet_event_title(company, summary, category):
    title_parts = [company, str(summary or "").strip(), category]
    return "：".join(part for part in title_parts if part)


def format_event_datetime(start_dt, end_dt=None):
    if not start_dt:
        return ""

    if end_dt and end_dt.date() == start_dt.date():
        return f"{start_dt.strftime('%Y-%m-%d %H:%M')}〜{end_dt.strftime('%H:%M')}"

    if end_dt:
        return f"{start_dt.strftime('%Y-%m-%d %H:%M')}〜{end_dt.strftime('%Y-%m-%d %H:%M')}"

    return start_dt.strftime("%Y-%m-%d %H:%M")


# =========================
# トップページ
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if admin_login_is_valid(request.form.get("login_id", ""), request.form.get("password", "")):
            session.clear()
            session["job_admin_authenticated"] = True
            admin_csrf_token()
            next_path = request.args.get("next", "")
            if not next_path.startswith("/") or next_path.startswith("//") or "\\" in next_path:
                next_path = url_for("admin_users")
            return redirect(next_path)
        error = "管理者IDまたはパスワードが正しくありません。"
    return render_template("admin_login.html", error=error)


@app.post("/admin/logout")
@admin_required
def admin_logout():
    try:
        require_admin_csrf()
    except ValueError:
        return redirect(url_for("admin_users"))
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    message = None
    error = None
    if not service_database_is_configured():
        error = "SERVICE_DATABASE_URL が未設定です。Renderでサービス版と同じPostgreSQL接続文字列を設定してください。"
        return render_template("admin_users.html", users=[], message=message, error=error, csrf_token=admin_csrf_token())

    if request.method == "POST":
        try:
            require_admin_csrf()
            action = request.form.get("action", "")
            if action == "create":
                login_id = request.form.get("login_id", "").strip()
                display_name = request.form.get("display_name", "").strip() or login_id
                password = request.form.get("password", "")
                if not login_id or len(login_id) > 80 or len(display_name) > 100 or len(password) < 8:
                    raise ValueError("ID、表示名、パスワード（8文字以上）を確認してください。")
                if ServiceUser.query.filter_by(login_id=login_id).first():
                    raise ValueError("この利用者IDは既に使われています。")
                user = ServiceUser(
                    login_id=login_id,
                    password_hash=generate_password_hash(password),
                    display_name=display_name,
                    is_admin=False,
                    is_active_account=True,
                    ai_balance=5,
                    ai_limit=5,
                    ai_model="gpt-5.4-mini",
                    created_at=datetime.now(),
                )
                db.session.add(user)
                db.session.commit()
                message = f"{display_name}のアカウントを発行しました。"
            elif action == "update":
                user_id = request.form.get("user_id", "")
                if not user_id.isdigit():
                    raise ValueError("利用者を特定できません。")
                user = db.session.get(ServiceUser, int(user_id))
                if not user:
                    raise ValueError("利用者が見つかりません。")
                new_password = request.form.get("new_password", "")
                if new_password:
                    if len(new_password) < 8:
                        raise ValueError("新しいパスワードは8文字以上にしてください。")
                    user.password_hash = generate_password_hash(new_password)
                user.is_active_account = request.form.get("is_active") == "1"
                db.session.commit()
                message = f"{user.display_name}のアカウントを更新しました。"
            else:
                raise ValueError("不明な操作です。")
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)

    users = ServiceUser.query.order_by(ServiceUser.created_at.asc()).all()
    return render_template("admin_users.html", users=users, message=message, error=error, csrf_token=admin_csrf_token())


# =========================
# Google Sheets → カレンダー予定API
# =========================
@app.route("/api/events")
def api_events():
    rows = get_event_sheet().get_all_values()
    events = []

    for row in rows[1:]:
        company = row[1] if len(row) > 1 else ""
        completed = row[3] if len(row) > 3 else ""
        summary = row[6] if len(row) > 6 else ""
        deadline = row[7] if len(row) > 7 else ""
        join_date = row[8] if len(row) > 8 else ""
        join_end = row[9] if len(row) > 9 else ""

        if not company:
            continue

        is_incomplete = str(completed).upper() in ["FALSE", "NO", "未完了", ""]

        deadline_dt = parse_date(deadline)
        if deadline_dt:
            modal_category = "ES締め切り"
            events.append({
                "title": f"{company}：ES締切",
                "modal_title": build_sheet_event_title(company, summary, modal_category),
                "company": company,
                "category": "ES締切",
                "summary": summary,
                "date": deadline_dt.strftime("%Y-%m-%d"),
                "time": deadline_dt.strftime("%H:%M"),
                "modal_datetime": format_event_datetime(deadline_dt),
                "incomplete": is_incomplete
            })

        join_dt = parse_date(join_date)
        if join_dt:
            join_end_dt = parse_date(join_end)
            if not join_end_dt or join_end_dt <= join_dt:
                join_end_dt = join_dt + timedelta(hours=1)

            modal_category = "インターン"
            events.append({
                "title": f"{company}：インターン",
                "modal_title": build_sheet_event_title(company, summary, modal_category),
                "company": company,
                "category": "インターン",
                "summary": summary,
                "date": join_dt.strftime("%Y-%m-%d"),
                "time": join_dt.strftime("%H:%M"),
                "end_date": join_end_dt.strftime("%Y-%m-%d"),
                "end_time": join_end_dt.strftime("%H:%M"),
                "modal_datetime": format_event_datetime(join_dt, join_end_dt),
                "incomplete": False
            })

    return jsonify(events)

@app.route("/api/mails")
def api_mails():
    mail_sheet = get_mail_sheet()
    rows = mail_sheet.get_all_values()
    mails = []

    for row in rows[1:]:
        received_at = row[0] if len(row) > 0 else ""
        company = row[1] if len(row) > 1 else ""
        subject = row[2] if len(row) > 2 else ""
        category = row[3] if len(row) > 3 else ""
        deadline = row[4] if len(row) > 4 else ""
        snippet = row[5] if len(row) > 5 else ""
        gmail_url = row[6] if len(row) > 6 else ""
        message_id = row[7] if len(row) > 7 else ""
        status = row[8] if len(row) > 8 else ""

        mails.append({
            "received_at": received_at,
            "company": company,
            "subject": subject,
            "category": category,
            "deadline": deadline,
            "snippet": snippet,
            "gmail_url": gmail_url,
            "message_id": message_id,
            "status": status
        })

    return jsonify(mails[:20])

@app.route("/api/mails/all")
def api_mails_all():
    mail_sheet = get_mail_sheet()
    rows = mail_sheet.get_all_values()
    return jsonify(rows)

@app.route("/mail/details")
def mail_details():
    mail_sheet = get_mail_sheet()
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

@app.post("/gd/delete/<int:log_id>")
def gd_delete(log_id):
    log = GDLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    return redirect(url_for("gd_logs"))

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

    category_records = get_self_profile_categories()
    categories = [category.name for category in category_records]

    return render_template(
        "self_profile.html",
        profiles=profiles,
        categories=categories,
        category_records=category_records,
    )


@app.post("/self-profile/categories")
def self_profile_categories():
    category_name = request.form.get("category_name", "").strip()
    raw_position = request.form.get("category_position", "").strip()
    delete_ids = {
        int(value)
        for value in request.form.getlist("delete_categories")
        if value.isdigit()
    }

    has_name = bool(category_name)
    has_position = bool(raw_position)
    if has_name != has_position or (not has_name and not delete_ids):
        return jsonify(ok=False, error="入力が適切ではありません"), 400

    categories = get_self_profile_categories()
    delete_categories = [category for category in categories if category.id in delete_ids]
    remaining_categories = [category for category in categories if category.id not in delete_ids]
    if delete_ids and not delete_categories:
        return jsonify(ok=False, error="入力が適切ではありません"), 400

    new_position = None
    if has_name:
        new_position = normalize_position(raw_position)
        if (
            new_position is None
            or new_position < 1
            or new_position > len(remaining_categories) + 1
            or len(category_name) > 50
            or any(category.name == category_name for category in categories)
        ):
            return jsonify(ok=False, error="入力が適切ではありません"), 400

    if not remaining_categories and not has_name:
        return jsonify(ok=False, error="項目は1つ以上必要です"), 400

    for category in delete_categories:
        db.session.delete(category)

    ordered_categories = list(remaining_categories)
    if has_name:
        new_category = SelfProfileCategory(name=category_name, position=new_position)
        ordered_categories.insert(new_position - 1, new_category)
        db.session.add(new_category)

    for position, category in enumerate(ordered_categories, start=1):
        category.position = position

    db.session.commit()
    return jsonify(ok=True, redirect=url_for("self_profile"))

@app.post("/self-profile/delete/<int:profile_id>")
def self_profile_delete(profile_id):
    profile = SelfProfile.query.get_or_404(profile_id)
    db.session.delete(profile)
    db.session.commit()
    return redirect(url_for("self_profile"))

def company_research_from_form(company=None):
    if company is None:
        company = CompanyResearch()

    company.company_name = request.form.get("company_name", "").strip()
    company.industry = request.form.get("industry", "").strip()
    company.business = request.form.get("business", "").strip()
    company.history = request.form.get("history", "").strip()
    company.details = request.form.get("details", "").strip()
    company.features = request.form.get("features", "").strip()
    company.motivation = request.form.get("motivation", "").strip()
    company.career_plan = request.form.get("career_plan", "").strip()
    company.appeal = request.form.get("appeal", "").strip()
    return company

def company_research_payload(companies):
    return [
        {
            "id": company.id,
            "company_name": company.company_name,
            "industry": company.industry or "",
            "business": company.business or "",
            "history": company.history or "",
            "details": company.details or "",
            "features": company.features or "",
            "motivation": company.motivation or "",
            "career_plan": company.career_plan or "",
            "appeal": company.appeal or "",
            "created_at": to_jst(company.created_at),
            "updated_at": to_jst(company.updated_at),
        }
        for company in companies
    ]

@app.route("/company-research")
def company_research():
    companies = CompanyResearch.query.order_by(CompanyResearch.created_at.desc()).all()
    return render_template(
        "company_research.html",
        companies=companies,
        companies_data=company_research_payload(companies)
    )

@app.post("/company-research/new")
def company_research_new():
    company = company_research_from_form()
    if company.company_name:
        db.session.add(company)
        db.session.commit()
    return redirect(url_for("company_research"))

@app.post("/company-research/edit/<int:company_id>")
def company_research_edit(company_id):
    company = CompanyResearch.query.get_or_404(company_id)
    company_research_from_form(company)
    if company.company_name:
        db.session.commit()
    return redirect(url_for("company_research"))

@app.post("/company-research/delete/<int:company_id>")
def company_research_delete(company_id):
    company = CompanyResearch.query.get_or_404(company_id)
    db.session.delete(company)
    db.session.commit()
    return redirect(url_for("company_research"))

@app.route("/gd/detail/<int:log_id>")
def gd_detail(log_id):
    log = GDLog.query.get_or_404(log_id)
    return render_template("gd_detail.html", log=log)

# =========================
# AIフィードバック
# =========================
@app.route("/gd/feedback/<int:log_id>")
def gd_feedback(log_id):
    log = GDLog.query.get_or_404(log_id)

    # すでにAIフィードバックが保存されている場合は、通常はAPIを呼ばずに表示
    # ?regenerate=1 のときだけ、最新の自己分析も反映して再生成する
    if log.ai_feedback and request.args.get("regenerate") != "1":
        return render_template("gd_feedback.html", log=log, feedback=log.ai_feedback)

    if not os.getenv("OPENAI_API_KEY"):
        feedback = "OPENAI_API_KEY が設定されていません。.env ファイルを確認してください。"
        return render_template("gd_feedback.html", log=log, feedback=feedback)

    self_profiles = SelfProfile.query.order_by(SelfProfile.category.asc(), SelfProfile.created_at.desc()).all()
    if self_profiles:
        self_profile_text = "\n\n".join(
            f"【{profile.category}】\nタイトル：{profile.title or '未入力'}\n内容：{profile.content}"
            for profile in self_profiles
        )
    else:
        self_profile_text = "自己分析管理にはまだ登録がありません。"

    prompt = f"""
あなたは就活のGD・面接対策コーチです。
以下のGD・面接ログと自己分析管理の内容をもとに、評価者視点で具体的にフィードバックしてください。
自己分析管理の内容は、本人の強み・価値観・過去経験として参照し、ログへの改善提案や自己PRへの転用に反映してください。

【自己分析管理】
{self_profile_text}

【GD・面接ログ】

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

以下の評価方針で、かなり厳しめに、忖度せず具体的に評価してください。
- 大雑把な励ましではなく、評価者がどう見るかを明確に書く。
- 良い点も課題も、必ずログ本文または自己分析管理の内容を根拠にする。
- 「何が足りないか」「なぜ危険か」「どう直すか」を具体的に書く。
- 自己分析管理の内容は、本人の強み・価値観・過去経験として接続する。
- 可能なら、SIer・ITコンサル志望者としてどう見えるかも触れる。
- 採点は甘くしない。一般的な学生の平均は55〜65点として扱う。
- A評価以上は、成果・具体性・壁への対処・再現性が明確な場合だけにする。
- 成果数字、周囲への影響、本人の具体的な発言や判断が薄い場合は必ず減点する。
- 「頑張った」「学んだ」だけで、行動の質や成果が曖昧な場合はC評価もためらわない。
- 褒める場合も、同時に「このままだと面接で突かれる点」を率直に書く。

ランク基準：
- S：90〜100点。即戦力級に強く、深掘りにも耐えやすい。
- A：75〜89点。選考で十分武器になるが、改善余地あり。
- B：60〜74点。素材は良いが、具体性や成果が不足。
- C：45〜59点。評価される要素はあるが、面接ではかなり突かれる。
- D：44点以下。現状では選考で弱く、構成から見直しが必要。

出力は必ず以下の形式にしてください。

【総合評価】
総合得点：xx/100点
ランク：S/A/B/C/D
一言サマリー：評価者にどう映るかを1〜2文で率直に。

【軸別スコア】
| 評価軸 | 点数 | 短評 |
|---|---:|---|
| ①結論・主張の明確さ | xx/20 |  |
| ②状況把握・課題設定 | xx/20 |  |
| ③発言・行動の質 | xx/20 |  |
| ④協調性・巻き込み力 | xx/15 |  |
| ⑤成果・学び・再現性 | xx/15 |  |
| ⑥自己分析との一貫性 | xx/10 |  |

【良かった点】
3つ挙げる。各項目は、見出し、根拠、評価される理由を書く。

【改善点】
優先度順に4つ挙げる。各項目は以下の形にする。
- 現状の問題：
- 評価者の視点：
- 改善案：
- 次回の具体アクション：

【危険信号チェック】
選考上のリスクをチェックリスト形式で挙げる。

【次回使える発言例】
GDまたは面接でそのまま使える発言例を3〜5個書く。
"""

    try:
        response = openai_client.responses.create(
            model="gpt-5.5",
            input=prompt,
            max_output_tokens=4000
        )
        feedback = response.output_text or "AIから回答本文を取得できませんでした。"

        # 初回生成したAIフィードバックをDBに保存
        log.ai_feedback = feedback
        db.session.commit()

    except Exception as e:
        app.logger.exception("AI feedback generation failed for log_id=%s", log_id)
        db.session.rollback()
        feedback = f"AIフィードバックの取得中にエラーが発生しました。\n\n{e}"

    return render_template("gd_feedback.html", log=log, feedback=feedback)


# =========================
# 起動
# =========================
with app.app_context():
    # Account records for the distributed service live in a separately managed
    # database. This app must never create or migrate that database on startup.
    db.create_all(bind_key=None)
    import_startup_data_if_configured()
    ensure_self_profile_categories()

if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        use_reloader=False
    )
