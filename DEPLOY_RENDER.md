# Render deploy notes

## Render settings

- Service type: Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

`gunicorn.conf.py` sets a 300-second worker timeout for long AI feedback requests.

## Environment variables

Set these in Render, not in GitHub.

- `OPENAI_API_KEY`
- `OPENAI_ADMIN_API_KEY` optional, for organization cost API access
- `OPENAI_MODEL`
- `OPENAI_MONTHLY_CREDIT_LIMIT_USD`
- `OPENAI_CREDIT_BALANCE_USD` optional manual fallback
- `GOOGLE_CREDENTIALS_BASE64`
- `SPREADSHEET_ID`
- `SHEET_NAME`
- `MAIL_SPREADSHEET_ID`
- `MAIL_SHEET_NAME`

`GOOGLE_CREDENTIALS_BASE64` should be the Base64-encoded contents of `credentials.json`.

PowerShell command to create the value locally:

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content -Raw credentials.json)))
```

If the OpenAI organization costs API returns 403, the site uses `OPENAI_CREDIT_BALANCE_USD` as the displayed balance instead.

## Data storage warning

The app uses SQLite by default. On Render's normal filesystem, SQLite data can be lost on redeploy or restart unless a persistent disk or external database is configured.

For serious long-term use, configure either:

- Render persistent disk and keep SQLite there, or
- a managed PostgreSQL database and set `DATABASE_URL`.

## Import local app data

GD/interview logs, self-profile entries, and company research entries are stored in the app database, not in Google Sheets. To copy local data to Render, first configure persistent storage such as PostgreSQL and set `DATABASE_URL`.

Then run this locally from the project directory:

```powershell
python export_app_data.py --copy
```

The command copies the exported payload to the clipboard. Add it to Render as:

- `APP_DATA_IMPORT_BASE64`: pasted clipboard value
- `APP_DATA_IMPORT_REPLACE`: `0`

Deploy the latest commit. The app imports this payload only when those app tables are empty. Use `APP_DATA_IMPORT_REPLACE=1` only if you intentionally want to replace the existing Render app data.
