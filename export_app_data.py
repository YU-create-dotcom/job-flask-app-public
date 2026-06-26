import argparse
import base64
import json
import sqlite3
import subprocess
from pathlib import Path


TABLES = {
    "gd_log": [
        "id", "log_type", "company", "theme", "role", "situation",
        "my_action", "result", "reflection", "ai_feedback", "created_at",
    ],
    "self_profile": ["id", "category", "title", "content", "created_at"],
    "self_profile_category": ["id", "name", "position", "created_at"],
    "company_research": [
        "id", "company_name", "industry", "business", "history", "details",
        "features", "motivation", "career_plan", "appeal", "created_at", "updated_at",
    ],
}


def rows_for_table(conn, table_name, columns):
    cursor = conn.execute(
        f"select {', '.join(columns)} from {table_name} order by id"
    )
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def copy_to_clipboard(text):
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
        input=text,
        text=True,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Export local app data for Render APP_DATA_IMPORT_BASE64."
    )
    parser.add_argument(
        "--db",
        default="instance/gd_logs.db",
        help="Path to the local SQLite database.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy the generated Base64 payload to the clipboard.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        payload = {
            table_name: rows_for_table(conn, table_name, columns)
            for table_name, columns in TABLES.items()
        }

    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    if args.copy:
        copy_to_clipboard(encoded)
        counts = ", ".join(f"{name}={len(rows)}" for name, rows in payload.items())
        print(f"APP_DATA_IMPORT_BASE64 copied to clipboard. Length: {len(encoded)}. Rows: {counts}")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
