#!/usr/bin/env python3
"""
Job Application Agent — Phase 1 orchestrator.

Pipeline (per cron run):
  1. Workday gate — print "SKIP" and exit 0 on non-working days.
  2. Verify the local resume PDF exists.
  3. Sync the dedup list from the Google Sheet into data/applied_jobs.json.
  4. Run both search scripts as subprocesses; on error, surviving sources still proceed.
  5. Aggregate + filter (dedup, excluded titles), write data/new_jobs.json.
  6. Apply to all LinkedIn jobs in-process via apply_linkedin.
  7. Write a partial data/run_summary.json (Phase 2 will extend it for non-LinkedIn jobs).

Stdout: first line is "SKIP" or "RUN" so the cron prompt can branch cheaply.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _early_workday_check() -> bool:
    """Cheap workday gate using only stdlib. Returns True to proceed."""
    if os.environ.get("FORCE_SKIP", "").lower() == "true":
        return False
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "check_workday.py")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    first_line = (res.stdout or "").strip().splitlines()[:1]
    return bool(first_line) and first_line[0] == "RUN"


# Bail before importing heavy third-party deps so the SKIP path works even
# when the venv hasn't been activated or some optional package is missing.
if __name__ == "__main__" and not _early_workday_check():
    print("SKIP")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dedup_manager
import apply_linkedin as apply_module

DATA_DIR = str(ROOT / "data")
NEW_JOBS_FILE = os.path.join(DATA_DIR, "new_jobs.json")
SUMMARY_FILE = os.path.join(DATA_DIR, "run_summary.json")
ERRORS_FILE = os.path.join(DATA_DIR, "errors.log")

EXCLUDED_TITLE_KEYWORDS = [
    "full-stack", "fullstack", "full stack",
    "frontend", "front-end", "front end",
    "mobile", "ios", "android", "flutter", "react native",
    "qa ", " qa", "quality assurance", "sdet",
    "sales", "marketing", "advertising", "growth",
    "account executive", "account manager", "customer success",
    "recruiter", "recruiting", "talent acquisition",
    "hr ", " hr", "human resource", "people ops",
    "project manager", "product manager", "scrum master",
    "technical writer", "devrel", "developer relations",
    "php developer", "wordpress",
]

MAX_PER_RUN = int(os.environ.get("MAX_APPLICATIONS_PER_RUN", "20"))


def _log_error(msg: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.utcnow().isoformat()
    with open(ERRORS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"ERROR: {msg}", file=sys.stderr)


def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _is_excluded(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDED_TITLE_KEYWORDS)


def _check_workday() -> bool:
    """True if today is a working day for the agent; False to skip."""
    if os.environ.get("FORCE_SKIP", "").lower() == "true":
        return False
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "check_workday.py")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    first_line = (res.stdout or "").strip().splitlines()[:1]
    return bool(first_line) and first_line[0] == "RUN"


def _verify_resume() -> str | None:
    rel = os.environ.get("RESUME_PDF_PATH", "Daniel_Lonkry_Resume.pdf")
    path = (ROOT / rel).resolve()
    if not path.exists():
        _log_error(f"Resume PDF not found at {path}")
        return None
    return str(path)


def _run_search(name: str, script: str):
    """Run a search script, capture stdout JSON, write to data/jobs_<name>.json."""
    out_path = os.path.join(DATA_DIR, f"jobs_{name}.json")
    try:
        cmd = [sys.executable, str(Path(__file__).resolve().parent / script)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.stderr:
            for line in res.stderr.splitlines():
                _log_error(f"{name} stderr: {line}")
        out = (res.stdout or "").strip()
        if not out:
            _log_error(f"{name}: empty stdout")
            return
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out)
    except Exception as e:
        _log_error(f"{name} subprocess failed: {e}")


def aggregate() -> list[dict]:
    """Merge jobs_*.json, filter dedup + excluded titles, write new_jobs.json."""
    applied_data = _load_json(os.path.join(DATA_DIR, "applied_jobs.json"))
    applied_urls: set[str] = set(applied_data.get("applied_urls", []))
    applied_ids: set[str] = {u.rstrip("/").split("/")[-1] for u in applied_urls if u}

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    source_files = [("linkedin", "jobs_linkedin.json"), ("google", "jobs_google.json")]

    for source, filename in source_files:
        data = _load_json(os.path.join(DATA_DIR, filename))
        if isinstance(data, dict):
            jobs = data.get("jobs", [])
            err = data.get("error")
        elif isinstance(data, list):
            jobs = data
            err = None
        else:
            jobs = []
            err = None
        if err:
            _log_error(f"{source}: {err}")

        for job in jobs:
            job_id = job.get("id", "")
            job_url = job.get("url", "").rstrip("/")
            if not job_url:
                continue
            if job_id in seen_ids:
                continue
            if job_url in applied_urls or (job_url + "/") in applied_urls:
                continue
            if job_id in applied_ids:
                continue
            if _is_excluded(job.get("title", "")):
                continue
            seen_ids.add(job_id)
            all_jobs.append(job)

    capped = all_jobs[:MAX_PER_RUN]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(NEW_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(capped, f, ensure_ascii=False, indent=2)
    print(f"New jobs to apply: {len(capped)} (kept after filter: {len(all_jobs)})")
    return capped


def apply_linkedin_jobs() -> dict:
    """Apply only to source=='linkedin' jobs in new_jobs.json. Writes a partial
    run_summary.json that Phase 2 (Playwright) will extend."""
    raw = _load_json(NEW_JOBS_FILE)
    jobs: list[dict] = raw if isinstance(raw, list) else []
    linkedin_jobs = [j for j in jobs if j.get("source") == "linkedin"]

    summary = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "time": datetime.utcnow().strftime("%H:%M UTC"),
        "run_type": "MORNING" if datetime.utcnow().hour < 12 else "EVENING",
        "total_new": len(jobs),
        "applied": 0,
        "manual": 0,
        "failed": 0,
        "dry_run": 0,
        "applications": [],
        "manual_jobs": [],
        "failed_jobs": [],
        "dry_run_jobs": [],
        "errors": [],
    }

    if not linkedin_jobs:
        _write_summary(summary)
        return summary

    api = apply_module._get_api()
    if not api:
        _log_error("LinkedIn auth failed — no LinkedIn applications submitted")
        summary["errors"].append("LinkedIn auth failed")
        summary["failed"] = len(linkedin_jobs)
        summary["failed_jobs"] = [{**j, "reason": "LinkedIn auth failed"} for j in linkedin_jobs]
        _write_summary(summary)
        return summary

    for i, job in enumerate(linkedin_jobs, 1):
        print(f"[{i}/{len(linkedin_jobs)}] LinkedIn: {job.get('title')} @ {job.get('company')}")
        try:
            result = apply_module.apply_to_job(api, job)
            status = result.get("status", "failed")
            reason = result.get("reason", "Unknown")

            if status == "applied":
                dedup_manager.append_to_sheet(job, status="Applied")
                dedup_manager.mark_applied_local(job.get("url", ""))
                summary["applications"].append(job)
                summary["applied"] += 1
            elif status == "manual":
                dedup_manager.append_to_sheet(job, status="Manual",
                                              notes=f"Needs manual apply: {reason}")
                summary["manual_jobs"].append({**job, "reason": reason})
                summary["manual"] += 1
            elif status == "dry_run":
                # Spec Section 8/11: dry_run does NOT write to Sheet or local applied list.
                summary["dry_run_jobs"].append(job)
                summary["dry_run"] += 1
            else:
                dedup_manager.append_to_sheet(job, status="Failed",
                                              notes=f"Auto-apply failed: {reason}")
                summary["failed_jobs"].append({**job, "reason": reason})
                summary["failed"] += 1
                _log_error(f"Apply failed: {job.get('title')} @ {job.get('company')} — {reason}")
        except Exception as e:
            msg = str(e)
            summary["failed_jobs"].append({**job, "reason": msg})
            summary["failed"] += 1
            summary["errors"].append(msg)
            _log_error(f"Apply exception: {job.get('title')} @ {job.get('company')} — {msg}")

        time.sleep(4)

    _write_summary(summary)
    print(f"\nLinkedIn pass: {summary['applied']} applied, {summary['manual']} manual, "
          f"{summary['failed']} failed, {summary['dry_run']} dry_run")
    return summary


def _write_summary(summary: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main():
    if not _check_workday():
        print("SKIP")
        return 0

    print("RUN")
    if _verify_resume() is None:
        _log_error("Resume PDF missing — aborting")
        return 1

    try:
        dedup_manager.load_applied_jobs()
    except Exception as e:
        _log_error(f"Dedup load failed: {e}")

    _run_search("linkedin", "search_linkedin.py")
    _run_search("google", "search_google.py")

    aggregate()
    apply_linkedin_jobs()
    return 0


if __name__ == "__main__":
    sys.exit(main())
