#!/usr/bin/env python3
"""
Job Application Agent Orchestrator.

Usage:
  python scripts/main.py --action=aggregate
  python scripts/main.py --action=apply
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import dedup_manager
from apply_job import apply_to_job

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

NEW_JOBS_FILE = os.path.join(DATA_DIR, "new_jobs.json")
SUMMARY_FILE = os.path.join(DATA_DIR, "run_summary.json")
ERRORS_FILE = os.path.join(DATA_DIR, "errors.log")

# Roles that should be excluded
EXCLUDED_TITLE_KEYWORDS = [
    "full-stack", "fullstack", "full stack",
    "frontend", "front-end", "front end",
    "mobile", "ios", "android", "flutter", "react native",
    "qa ", " qa", "quality assurance", "sdet",
    "sales", "marketing", "hr ", " hr", "human resource",
    "project manager", "product manager", "scrum master",
    "technical writer", "devrel", "developer relations",
]

MAX_PER_RUN = int(os.environ.get("MAX_APPLICATIONS_PER_RUN", "20"))


def _load_json(path: str) -> dict | list:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _log_error(msg: str):
    timestamp = datetime.utcnow().isoformat()
    with open(ERRORS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"ERROR: {msg}", file=sys.stderr)


def _is_excluded(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in EXCLUDED_TITLE_KEYWORDS)


def aggregate():
    """Merge all search results, filter out duplicates and excluded roles, write new_jobs.json."""
    applied_data = _load_json(os.path.join(DATA_DIR, "applied_jobs.json"))
    applied_urls: set[str] = set(applied_data.get("applied_urls", []))
    applied_ids: set[str] = {u.rstrip("/").split("/")[-1] for u in applied_urls}

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    source_files = [
        ("linkedin", "jobs_linkedin.json"),
        ("indeed", "jobs_indeed.json"),
        ("google", "jobs_google.json"),
    ]

    for source, filename in source_files:
        path = os.path.join(DATA_DIR, filename)
        data = _load_json(path)
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        err = data.get("error") if isinstance(data, dict) else None
        if err:
            _log_error(f"{source}: {err}")

        for job in jobs:
            job_id = job.get("id", "")
            job_url = job.get("url", "").rstrip("/")

            if not job_url:
                continue
            if job_id in seen_ids:
                continue
            if job_url in applied_urls or job_url + "/" in applied_urls:
                continue
            if job_id in applied_ids:
                continue
            if _is_excluded(job.get("title", "")):
                continue

            seen_ids.add(job_id)
            all_jobs.append(job)

    # Respect max applications cap (priority by source order above)
    capped = all_jobs[:MAX_PER_RUN]

    with open(NEW_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(capped, f, ensure_ascii=False, indent=2)

    total_found = len(all_jobs)
    skipped = sum(
        len(_load_json(os.path.join(DATA_DIR, fn)).get("jobs", []))
        for _, fn in source_files
    ) - total_found
    print(f"New jobs to apply: {len(capped)} (found: {total_found}, already applied: max ~{skipped})")
    return capped


def apply_all():
    """Apply to every job in new_jobs.json and write run_summary.json."""
    jobs: list[dict] = _load_json(NEW_JOBS_FILE) if os.path.exists(NEW_JOBS_FILE) else []
    if not isinstance(jobs, list):
        jobs = []

    if not jobs:
        print("No new jobs to apply to.")
        summary = {"applied": 0, "failed": 0, "applications": [], "errors": [], "total_new": 0}
        with open(SUMMARY_FILE, "w") as f:
            json.dump(summary, f, indent=2)
        return summary

    applied = []
    failed = []
    errors = []

    for i, job in enumerate(jobs, 1):
        print(f"[{i}/{len(jobs)}] Applying: {job.get('title')} @ {job.get('company')} ({job.get('source')})")
        try:
            result = apply_to_job(job)
            if result.get("success"):
                # Write to Google Sheets immediately
                dedup_manager.append_to_sheet(job, status="Applied")
                # Update local dedup cache
                dedup_manager.mark_applied_local(job.get("url", ""))
                applied.append(job)
                print(f"  ✅ Applied successfully")
            else:
                reason = result.get("reason", "Unknown")
                dedup_manager.append_to_sheet(job, status="Failed", notes=f"Auto-apply failed: {reason}")
                failed.append({**job, "reason": reason})
                _log_error(f"Apply failed: {job.get('title')} @ {job.get('company')} — {reason}")
                print(f"  ❌ Failed: {reason}")

        except Exception as e:
            msg = str(e)
            failed.append({**job, "reason": msg})
            _log_error(f"Apply exception: {job.get('title')} @ {job.get('company')} — {msg}")
            errors.append(msg)
            print(f"  ❌ Exception: {msg}")

        # Rate limiting between applications
        time.sleep(4)

    now = datetime.utcnow()
    run_type = "MORNING" if now.hour < 12 else "EVENING"

    summary = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M UTC"),
        "run_type": run_type,
        "total_new": len(jobs),
        "applied": len(applied),
        "failed": len(failed),
        "skipped_dedup": 0,  # filled by aggregate step
        "applications": applied,
        "failed_jobs": failed,
        "errors": errors,
    }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nRun complete: {len(applied)} applied, {len(failed)} failed")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["aggregate", "apply"], required=True)
    args = parser.parse_args()

    if args.action == "aggregate":
        aggregate()
    elif args.action == "apply":
        apply_all()
