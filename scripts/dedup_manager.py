#!/usr/bin/env python3
"""
Load applied jobs from Google Sheets into local JSON for fast dedup lookups.
Also provides append_application() to record new applications to the sheet.

Usage:
  python dedup_manager.py --action=load
"""

import argparse
import json
import os
import sys
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
APPLIED_JSON = os.path.join(DATA_DIR, "applied_jobs.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_service_account_info() -> dict:
    """Resolve service-account credentials from one of two sources:

    1. GOOGLE_SERVICE_ACCOUNT_JSON_PATH — path to a JSON key file on disk
       (preferred — escapes the newline-escaping nightmare of putting a
       PEM block inside a single-line .env value).
    2. GOOGLE_SERVICE_ACCOUNT_JSON — the JSON content as a single line.

    Raises EnvironmentError with a useful message if neither works."""
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise EnvironmentError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON_PATH points to {path} but file not found"
            )
        except json.JSONDecodeError as e:
            raise EnvironmentError(
                f"Invalid JSON in service account file {path}: {e}"
            )

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise EnvironmentError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON_PATH (recommended — file path) "
            "or GOOGLE_SERVICE_ACCOUNT_JSON (single-line JSON). Neither is set."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise EnvironmentError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON failed to parse: {e}. "
            f"Tip: prefer GOOGLE_SERVICE_ACCOUNT_JSON_PATH=path/to/key.json — "
            f"single-line JSON in .env is fragile because the private_key's "
            f"newlines must be escaped as literal \\n inside the value."
        )


def _get_sheet():
    sheet_id = os.environ.get("GOOGLE_SHEETS_APPLIED_SHEET_ID", "")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEETS_APPLIED_SHEET_ID not set")

    creds = Credentials.from_service_account_info(
        _load_service_account_info(), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet.sheet1


def _detect_url_column(headers: list[str]) -> int:
    """Return 0-based index of the URL column, or -1 if not found."""
    url_names = {"url", "link", "קישור", "job url", "job link", "apply link"}
    for i, h in enumerate(headers):
        if str(h).strip().lower() in url_names:
            return i
    return -1


def load_applied_jobs():
    """Fetch all applied job URLs from Google Sheets and cache locally."""
    applied = set()

    try:
        sheet = _get_sheet()
        all_values = sheet.get_all_values()

        if not all_values:
            print("WARNING: Google Sheet is empty", file=sys.stderr)
        else:
            headers = all_values[0]
            url_col = _detect_url_column(headers)

            if url_col == -1:
                # Fallback: scan all cells for URLs
                print("WARNING: No URL column header detected; scanning all cells",
                      file=sys.stderr)
                for row in all_values[1:]:
                    for cell in row:
                        if cell.startswith("http"):
                            applied.add(cell.strip())
            else:
                for row in all_values[1:]:
                    if url_col < len(row) and row[url_col].startswith("http"):
                        applied.add(row[url_col].strip())

        print(f"Loaded {len(applied)} applied jobs from Google Sheets", file=sys.stderr)

    except Exception as e:
        print(f"WARNING: Could not load from Google Sheets: {e}", file=sys.stderr)
        # Fall through to local JSON

    # Merge with local JSON (in case Sheets is stale or unreachable)
    os.makedirs(DATA_DIR, exist_ok=True)
    local_data = {}
    if os.path.exists(APPLIED_JSON):
        try:
            with open(APPLIED_JSON) as f:
                local_data = json.load(f)
        except Exception:
            pass

    local_urls = set(local_data.get("applied_urls", []))
    merged = applied | local_urls

    with open(APPLIED_JSON, "w") as f:
        json.dump({"applied_urls": list(merged), "last_updated": datetime.utcnow().isoformat()},
                  f, indent=2)

    print(f"Dedup cache: {len(merged)} total applied jobs", file=sys.stderr)
    return merged


def is_already_applied(url: str) -> bool:
    if not os.path.exists(APPLIED_JSON):
        return False
    try:
        with open(APPLIED_JSON) as f:
            data = json.load(f)
        return url in data.get("applied_urls", [])
    except Exception:
        return False


def mark_applied_local(url: str):
    """Update local JSON immediately after applying."""
    os.makedirs(DATA_DIR, exist_ok=True)
    data = {"applied_urls": [], "last_updated": ""}
    if os.path.exists(APPLIED_JSON):
        try:
            with open(APPLIED_JSON) as f:
                data = json.load(f)
        except Exception:
            pass

    urls = set(data.get("applied_urls", []))
    urls.add(url)
    data["applied_urls"] = list(urls)
    data["last_updated"] = datetime.utcnow().isoformat()

    with open(APPLIED_JSON, "w") as f:
        json.dump(data, f, indent=2)


def append_to_sheet(job: dict, status: str = "Applied", notes: str = "Auto-applied by agent"):
    """Append one row to Google Sheets. Call immediately after each successful application."""
    try:
        sheet = _get_sheet()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        row = [
            today,
            job.get("company", ""),
            job.get("title", ""),
            job.get("url", ""),
            job.get("source", ""),
            status,
            notes,
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        print(f"Recorded in Sheets: {job.get('title')} @ {job.get('company')}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Could not write to Google Sheets: {e}", file=sys.stderr)
        # Save to fallback file for manual recovery
        fallback = os.path.join(DATA_DIR, "failed_sheet_writes.json")
        existing = []
        if os.path.exists(fallback):
            try:
                with open(fallback) as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing.append({"job": job, "status": status, "notes": notes,
                         "failed_at": datetime.utcnow().isoformat()})
        with open(fallback, "w") as f:
            json.dump(existing, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["load"], required=True)
    args = parser.parse_args()

    if args.action == "load":
        load_applied_jobs()
