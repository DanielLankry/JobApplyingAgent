"""Smoke tests for run_agent: workday gate, aggregation, dry-run-aware apply."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_run_agent():
    sys.path.insert(0, str(ROOT / "scripts"))
    if "run_agent" in sys.modules:
        del sys.modules["run_agent"]
    import run_agent
    return run_agent


def test_aggregate_filters_excluded_titles_and_dedups(tmp_path, monkeypatch):
    run_agent = _import_run_agent()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "applied_jobs.json").write_text(json.dumps({
        "applied_urls": ["https://www.linkedin.com/jobs/view/111/"]
    }))
    (data_dir / "jobs_linkedin.json").write_text(json.dumps({"jobs": [
        {"id": "linkedin_111", "job_id": "111", "title": "Backend Engineer",
         "company": "Acme", "url": "https://www.linkedin.com/jobs/view/111/",
         "source": "linkedin"},
        {"id": "linkedin_222", "job_id": "222", "title": "Frontend Developer",
         "company": "Beta", "url": "https://www.linkedin.com/jobs/view/222/",
         "source": "linkedin"},
        {"id": "linkedin_333", "job_id": "333", "title": "ML Engineer",
         "company": "Gamma", "url": "https://www.linkedin.com/jobs/view/333/",
         "source": "linkedin"},
    ]}))
    (data_dir / "jobs_google.json").write_text(json.dumps({"jobs": [
        {"id": "greenhouse_444", "title": "Senior Backend Engineer",
         "company": "delta", "url": "https://boards.greenhouse.io/delta/jobs/444",
         "source": "greenhouse"},
    ]}))

    monkeypatch.setattr(run_agent, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(run_agent, "NEW_JOBS_FILE",
                        str(data_dir / "new_jobs.json"))
    monkeypatch.setattr(run_agent, "ERRORS_FILE",
                        str(data_dir / "errors.log"))
    monkeypatch.setenv("MAX_APPLICATIONS_PER_RUN", "20")

    capped = run_agent.aggregate()

    titles = sorted(j["title"] for j in capped)
    # Excluded "Frontend Developer" filtered; already-applied
    # "Backend Engineer @ Acme" deduped by URL; survivors:
    # ML Engineer, Senior Backend Engineer
    assert titles == ["ML Engineer", "Senior Backend Engineer"]


def test_skip_returns_skip_on_non_workday():
    """Subprocess invocation: FORCE_SKIP=true must produce SKIP as first line."""
    env = {**os.environ, "FORCE_SKIP": "true"}
    result = subprocess.run(
        [sys.executable, "scripts/run_agent.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    first_line = result.stdout.splitlines()[0].strip()
    assert first_line == "SKIP"


def test_dry_run_does_not_mark_linkedin_applied(tmp_path, monkeypatch):
    """In DRY_RUN, apply_to_job returns dry_run; run_agent must NOT call
    dedup_manager.mark_applied_local or append_to_sheet for those jobs."""
    run_agent = _import_run_agent()
    import apply_linkedin
    import dedup_manager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "new_jobs.json").write_text(json.dumps([
        {"id": "linkedin_999", "job_id": "999", "title": "ML Engineer",
         "company": "Acme", "url": "https://www.linkedin.com/jobs/view/999/",
         "source": "linkedin"},
    ]))

    sheet_calls = []
    local_calls = []
    monkeypatch.setattr(dedup_manager, "append_to_sheet",
                        lambda *a, **kw: sheet_calls.append((a, kw)))
    monkeypatch.setattr(dedup_manager, "mark_applied_local",
                        lambda url: local_calls.append(url))
    monkeypatch.setattr(run_agent, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(run_agent, "NEW_JOBS_FILE",
                        str(data_dir / "new_jobs.json"))
    monkeypatch.setattr(run_agent, "SUMMARY_FILE",
                        str(data_dir / "run_summary.json"))
    monkeypatch.setattr(run_agent, "ERRORS_FILE",
                        str(data_dir / "errors.log"))

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("LINKEDIN_EMAIL", "x@y.z")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "pw")

    monkeypatch.setattr(apply_linkedin, "_get_api", lambda: object())
    # Avoid the 4s sleep between jobs in tests
    monkeypatch.setattr(run_agent.time, "sleep", lambda *_a, **_kw: None)

    summary = run_agent.apply_linkedin_jobs()

    assert summary["dry_run"] == 1
    assert summary["applied"] == 0
    assert sheet_calls == []
    assert local_calls == []
