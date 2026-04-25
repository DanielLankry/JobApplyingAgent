#!/usr/bin/env python3
"""Download the latest resume PDF from Google Drive."""

import io
import json
import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "resume.pdf")


def download_resume():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    file_id = os.environ.get("GOOGLE_DRIVE_RESUME_FILE_ID", "")

    if not sa_json or not file_id:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_DRIVE_RESUME_FILE_ID not set",
              file=sys.stderr)
        sys.exit(1)

    try:
        creds_info = json.loads(sa_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {e}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )

    service = build("drive", "v3", credentials=creds)

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(buf.getvalue())

    size_kb = len(buf.getvalue()) // 1024
    print(f"Resume downloaded: {OUTPUT_PATH} ({size_kb} KB)")


if __name__ == "__main__":
    download_resume()
