# Local Job Application Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the existing job-application agent from Claude Code Cloud routines to a local twice-daily Claude cron on Daniel's Windows PC, expand search to Comeet + Greenhouse + Lever via SerpAPI, and add Playwright-MCP-driven auto-apply for non-LinkedIn ATS jobs with strict canned-answer policy and a 14-day DRY_RUN gate.

**Architecture:** Three-phase per-run flow. Phase 1 is a Python pipeline (`scripts/run_agent.py`) that does workday check → dedup sync → multi-source search → filter → in-process LinkedIn auto-apply via the existing voyager API path. Phase 2 is a Claude+Playwright-MCP runbook for non-LinkedIn ATS jobs (Comeet/Greenhouse/Lever/open-web), driven from the cron prompt. Phase 3 posts a summary to ClickUp Chat via the ClickUp MCP tool.

**Tech Stack:** Python 3.13, `linkedin-api`, `google-search-results` (SerpAPI), `gspread`, `python-dotenv`, `pytest` (new — minimal), Playwright MCP (Claude side), ClickUp MCP (Claude side), local `CronCreate`.

**Spec reference:** `docs/superpowers/specs/2026-04-27-local-job-agent-design.md`

---

## Pre-flight: Branch + git hygiene

- [ ] **Pre-flight Step 1: Confirm clean working tree before starting**

```bash
git status
```
Expected: only the spec commit (already pushed in this session) and untracked files we don't touch (`Daniel_Lonkry_Resume.pdf`, the Hebrew xlsx). No staged changes.

- [ ] **Pre-flight Step 2: Sync with origin**

```bash
git fetch origin
git status -uno
```
If branch is behind, decide with the user whether to pull. Do not auto-pull — the user said `master` is 1 commit behind `origin/master` and we haven't reviewed that commit yet.

- [ ] **Pre-flight Step 3: Create feature branch**

```bash
git checkout -b feat/local-job-agent
```

---

## Task 1: Update `.gitignore` for new artifacts

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add new ignore entries**

Edit `.gitignore` to ensure these patterns are present (some already exist, just add the missing ones):

```gitignore
# Credentials — NEVER commit these
.env
*.env
*credentials*.json
service_account*.json
config/applicant.json

# Runtime data — regenerated each run
data/resume.pdf
data/jobs_*.json
data/new_jobs.json
data/run_summary.json
data/errors.log
data/failed_sheet_writes.json
data/dry_run_log.jsonl
data/unanswered_questions.log
data/apply_logs/
data/chrome_profile/

# Keep the dedup cache so it acts as a local backup
# (data/applied_jobs.json is intentionally tracked)

# Python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
.pytest_cache/

# Playwright
.playwright/
```

The new entries vs current: `config/applicant.json`, `data/dry_run_log.jsonl`, `data/unanswered_questions.log`, `data/apply_logs/`, `data/chrome_profile/`, `.pytest_cache/`.

- [ ] **Step 2: Verify nothing already-tracked is now hidden**

```bash
git status --ignored
```
Expected: ignored files listed are only the new artifacts; no surprise file shows as ignored that should have stayed tracked.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore Playwright artifacts and applicant config"
```

---

## Task 2: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Replace the file contents**

Drop `GOOGLE_DRIVE_RESUME_FILE_ID` (resume is local now) and add `DRY_RUN`, `RESUME_PDF_PATH`. Final content:

```dotenv
# ============================================================
# Job Application Agent — Environment Variables
# ============================================================
# Copy to .env (gitignored) and fill in real values.
# NEVER commit real credentials to Git.
# ============================================================

# ---- Applicant Profile ----
APPLICANT_FIRST_NAME=Daniel
APPLICANT_LAST_NAME=Lankry
APPLICANT_EMAIL=lankrydaniel7@gmail.com
APPLICANT_PHONE=+972XXXXXXXXX
APPLICANT_CITY=Tel Aviv
APPLICANT_LINKEDIN_URL=https://www.linkedin.com/in/your-profile/
APPLICANT_GITHUB_URL=https://github.com/your-username
APPLICANT_PORTFOLIO_URL=
APPLICANT_YEARS_EXPERIENCE=3

# ---- Google Service Account (for Sheets only) ----
# Create in Google Cloud Console, enable Sheets API, paste full JSON
# on a single line (replace newlines inside the private key with \n).
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"...","private_key_id":"...","private_key":"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n","client_email":"...@....iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}

# ---- Google Sheets ----
# From sheet URL: docs.google.com/spreadsheets/d/{THIS_PART}/edit
# Share sheet with the service account email (Editor access).
GOOGLE_SHEETS_APPLIED_SHEET_ID=1aBcDeFgHiJkLmNoPqRsTuVwXyZ

# ---- LinkedIn ----
LINKEDIN_EMAIL=your-email@gmail.com
LINKEDIN_PASSWORD=your-linkedin-password

# ---- SerpAPI (multi-source Google searches) ----
# Sign up at serpapi.com. Free tier (100/mo) is insufficient — plan to
# upgrade to Developer ($50/mo, 5,000 searches) once verified working.
SERPAPI_KEY=your-serpapi-key

# ---- ClickUp ----
CLICKUP_API_TOKEN=pk_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
CLICKUP_CHAT_CHANNEL_ID=XXXXXXXXXXXXXXXXXX

# ---- Run Settings ----
MAX_APPLICATIONS_PER_RUN=20

# ---- Phase 2 (Playwright auto-apply) ----
# Set DRY_RUN=true for the first 14 working days. While true, every
# apply attempt (LinkedIn API + Playwright) goes through every step
# EXCEPT the final submit, and is logged for review.
DRY_RUN=true

# Resume PDF path, relative to project root.
RESUME_PDF_PATH=Daniel_Lonkry_Resume.pdf
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "feat: drop Drive resume var, add DRY_RUN and RESUME_PDF_PATH"
```

---

## Task 3: Create `config/applicant.example.json`

**Files:**
- Create: `config/applicant.example.json`

- [ ] **Step 1: Create the directory and file**

```bash
mkdir -p config
```

Create `config/applicant.example.json`:

```json
{
  "first_name": "Daniel",
  "last_name": "Lankry",
  "full_name": "Daniel Lankry",
  "email": "lankrydaniel7@gmail.com",
  "phone": "+972XXXXXXXXX",
  "phone_country_code": "+972",
  "address_line_1": "",
  "city": "Tel Aviv",
  "state_region": "Tel Aviv District",
  "postal_code": "",
  "country": "Israel",
  "linkedin_url": "https://www.linkedin.com/in/your-profile/",
  "github_url": "https://github.com/your-username",
  "portfolio_url": "",
  "resume_pdf_path": "Daniel_Lonkry_Resume.pdf",
  "years_experience": 3,
  "current_company": "",
  "current_title": "",
  "highest_education": "",
  "school_name": "",
  "graduation_year": "",
  "work_authorization_israel": "Yes - Israeli citizen",
  "visa_sponsorship_needed": "No",
  "willing_to_relocate": "No",
  "remote_preference": "Hybrid",
  "salary_expectation_ils": "Not disclosed at this stage",
  "notice_period": "30 days",
  "earliest_start_date": "Negotiable",
  "gender": "Prefer not to say",
  "ethnicity": "Prefer not to say",
  "veteran_status": "Not applicable",
  "disability_status": "Prefer not to say",
  "how_did_you_hear": "Online job board",
  "cover_letter_short": "I am excited to apply and bring my background in software engineering to your team.",
  "cover_letter_long": null
}
```

- [ ] **Step 2: Commit**

```bash
git add config/applicant.example.json
git commit -m "feat: add applicant.example.json template (canned answers)"
```

---

## Task 4: Delete `scripts/resume_manager.py`

**Files:**
- Delete: `scripts/resume_manager.py`

- [ ] **Step 1: Verify nothing imports it**

```bash
grep -r "resume_manager" scripts/ docs/ routines.md 2>/dev/null
```
Expected: only `routines.md` references it (Step 2 of the old prompt). That doc is going to be superseded by Task 9's cron prompt — note it but don't fix `routines.md` here.

- [ ] **Step 2: Delete the file**

```bash
git rm scripts/resume_manager.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: delete resume_manager.py — resume is local, not downloaded"
```

---

## Task 5: Set up minimal pytest infra

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest==8.3.3
```

- [ ] **Step 2: Create empty test package**

```bash
mkdir -p tests
```

Create empty `tests/__init__.py`:

```python
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
"""Test fixtures for the job-agent test suite."""
import os
import sys
from pathlib import Path

# Make scripts/ importable as a package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)
```

- [ ] **Step 4: Install dependencies (one-time setup)**

```bash
python -m venv venv
source venv/Scripts/activate    # Git Bash on Windows
pip install -r requirements.txt
```

- [ ] **Step 5: Verify pytest discovers nothing yet**

```bash
pytest -q
```
Expected: `no tests ran in ...s`. Exit code 5 is fine here (no tests collected).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/
git commit -m "test: add pytest infra (venv, conftest)"
```

---

## Task 6: Add DRY_RUN guard to `apply_linkedin.py` (TDD)

**Files:**
- Modify: `scripts/apply_linkedin.py`
- Test: `tests/test_apply_linkedin_dry_run.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_apply_linkedin_dry_run.py`:

```python
"""Verify DRY_RUN env flag short-circuits the LinkedIn easyApply POST."""
import os
import pytest

import apply_linkedin


class _FakeApi:
    """Stand-in for linkedin_api.Linkedin — apply_to_job should never touch
    its session when DRY_RUN=true."""

    class _Boom:
        def __getattr__(self, name):
            raise AssertionError(f"DRY_RUN should not access api.{name}")

    def __init__(self):
        self._LinkedIn__client = self._Boom()

    def get_job(self, *_a, **_kw):
        raise AssertionError("DRY_RUN should not call get_job()")


def test_dry_run_returns_dry_run_status_without_network(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    result = apply_linkedin.apply_to_job(_FakeApi(), job)

    assert result == {"status": "dry_run", "reason": "DRY_RUN mode"}


def test_dry_run_false_does_not_short_circuit(monkeypatch):
    """When DRY_RUN is anything other than 'true', the function proceeds and
    will (in this synthetic test) raise the AssertionError from the fake
    api — confirming the short-circuit is gated on the flag."""
    monkeypatch.setenv("DRY_RUN", "false")
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    with pytest.raises(AssertionError, match="get_job"):
        apply_linkedin.apply_to_job(_FakeApi(), job)


def test_dry_run_unset_does_not_short_circuit(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    with pytest.raises(AssertionError, match="get_job"):
        apply_linkedin.apply_to_job(_FakeApi(), job)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_apply_linkedin_dry_run.py -v
```
Expected: all three tests FAIL because `apply_to_job` currently calls `api.get_job()` regardless of `DRY_RUN`.

- [ ] **Step 3: Modify `apply_linkedin.py` to honor DRY_RUN**

In `scripts/apply_linkedin.py`, modify `apply_to_job()`. Add this block immediately after the `if not job_id:` early-return (currently around lines 57-59), before the `profile = _profile()` line:

```python
def apply_to_job(api: Linkedin, job: dict) -> dict:
    """
    Attempt Easy Apply via LinkedIn's internal voyager API.
    Returns {"status": "applied"|"manual"|"failed"|"dry_run", "reason": str}
    """
    job_id = job.get("job_id", "")
    if not job_id:
        return {"status": "manual", "reason": "No LinkedIn job ID — apply via URL"}

    # DRY_RUN: skip the actual easyApply POST. Returned status feeds
    # data/run_summary.json and tells main.py NOT to mark the job as
    # applied locally or write it to the Sheet (Section 11 of spec).
    if os.environ.get("DRY_RUN", "").strip().lower() == "true":
        return {"status": "dry_run", "reason": "DRY_RUN mode"}

    profile = _profile()
    # ... rest of function unchanged
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_apply_linkedin_dry_run.py -v
```
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/apply_linkedin.py tests/test_apply_linkedin_dry_run.py
git commit -m "feat: DRY_RUN env flag short-circuits LinkedIn easyApply"
```

---

## Task 7: Multi-source search in `scripts/search_google.py` (TDD)

**Goal:** Extend `search_google.py` from "Google Jobs only" to "Google Jobs + site-restricted searches for Comeet, Greenhouse, Lever". Each result tagged with its `source` so Phase 2 can route correctly.

**Files:**
- Modify: `scripts/search_google.py`
- Test: `tests/test_search_google_sources.py`

### Background

The current `search_google.py` only uses SerpAPI's `engine: google_jobs`. To pick up Comeet/Greenhouse/Lever-hosted jobs, we add a second call path using `engine: google` with `site:` queries. Each path returns a normalized list of jobs tagged with `source ∈ {google, comeet, greenhouse, lever}`.

### Per-run query budget

- 1 × `google_jobs` call (broad, all roles) → `source=google`
- 1 × `google` site-restricted for `boards.greenhouse.io` → `source=greenhouse`
- 1 × `google` site-restricted for `comeet.co` → `source=comeet`
- 1 × `google` site-restricted for `jobs.lever.co` → `source=lever`

= 4 SerpAPI queries per run × 2 runs/day × 22 days = ~176/month (over free tier; flagged in spec).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_google_sources.py`:

```python
"""Verify search_google produces source-tagged jobs across multiple SerpAPI
calls (Google Jobs + site-restricted Google searches for ATS hosts)."""
from unittest.mock import patch, MagicMock

import search_google


def _fake_google_jobs_response():
    return {
        "jobs_results": [
            {
                "job_id": "gj-1",
                "title": "Backend Engineer",
                "company_name": "Acme",
                "location": "Tel Aviv, Israel",
                "description": "Build APIs at Acme.",
                "apply_options": [
                    {"link": "https://www.linkedin.com/jobs/view/9876543210/"}
                ],
            }
        ]
    }


def _fake_google_search_response(domain: str, host_label: str):
    """Minimal SerpAPI google-engine response shape for site:<domain> queries."""
    return {
        "organic_results": [
            {
                "title": f"Senior ML Engineer — {host_label}",
                "link": f"https://{domain}/example-co/jobs/senior-ml-engineer",
                "snippet": f"Apply for the Senior ML Engineer role hosted on {host_label}.",
            }
        ]
    }


def _route_response(params):
    """Return a fake SerpAPI dict based on the engine + q in params."""
    engine = params.get("engine")
    q = params.get("q", "")
    if engine == "google_jobs":
        return _fake_google_jobs_response()
    if "site:boards.greenhouse.io" in q:
        return _fake_google_search_response("boards.greenhouse.io", "Greenhouse")
    if "site:comeet.co" in q:
        return _fake_google_search_response("comeet.co", "Comeet")
    if "site:jobs.lever.co" in q:
        return _fake_google_search_response("jobs.lever.co", "Lever")
    return {}


def test_run_emits_jobs_tagged_with_each_source(monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    captured_calls = []

    class _FakeSearch:
        def __init__(self, params):
            captured_calls.append(params)
            self._params = params

        def get_dict(self):
            return _route_response(self._params)

    monkeypatch.setattr(search_google, "GoogleSearch", _FakeSearch)

    search_google.run()

    out = capsys.readouterr().out.strip()
    import json as _json
    payload = _json.loads(out)

    sources = sorted({job["source"] for job in payload["jobs"]})
    assert sources == ["comeet", "google", "greenhouse", "lever"]

    # Make sure every job has the required keys
    for job in payload["jobs"]:
        assert job["url"].startswith("http")
        assert job["title"]
        assert job["source"] in {"google", "comeet", "greenhouse", "lever"}
        assert job["id"].startswith(f"{job['source']}_")

    # Confirm we made exactly 4 SerpAPI calls (1 google_jobs + 3 site-restricted)
    assert len(captured_calls) == 4


def test_missing_api_key_returns_error(monkeypatch, capsys):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    search_google.run()
    out = capsys.readouterr().out.strip()
    import json as _json
    payload = _json.loads(out)
    assert payload["jobs"] == []
    assert "SERPAPI_KEY" in payload["error"]


def test_one_source_failure_does_not_kill_others(monkeypatch, capsys):
    """If a single SerpAPI call raises, others still run and we still emit
    jobs from the surviving sources."""
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    class _FakeSearch:
        def __init__(self, params):
            self._params = params

        def get_dict(self):
            if "site:comeet.co" in self._params.get("q", ""):
                raise RuntimeError("simulated SerpAPI 500")
            return _route_response(self._params)

    monkeypatch.setattr(search_google, "GoogleSearch", _FakeSearch)
    search_google.run()

    out = capsys.readouterr().out.strip()
    import json as _json
    payload = _json.loads(out)
    sources = sorted({job["source"] for job in payload["jobs"]})
    # comeet missing, others present
    assert "comeet" not in sources
    assert {"google", "greenhouse", "lever"}.issubset(set(sources))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_search_google_sources.py -v
```
Expected: tests FAIL because current `search_google.py` only does Google Jobs (no Comeet/Greenhouse/Lever) and doesn't tag results with the new source values.

- [ ] **Step 3: Replace `scripts/search_google.py` with the multi-source version**

Replace the entire file:

```python
#!/usr/bin/env python3
"""
Search Google for matching jobs via SerpAPI across four sources:
  - Google Jobs (engine=google_jobs)             -> source="google"
  - boards.greenhouse.io site search             -> source="greenhouse"
  - comeet.co site search                        -> source="comeet"
  - jobs.lever.co site search                    -> source="lever"

Outputs one merged JSON payload to stdout. Each job is tagged with its
source so Phase 2 of the agent can route apply behavior correctly.
"""

import json
import os
import sys

from serpapi import GoogleSearch


# Single broad google_jobs query. The engine itself does role matching.
GOOGLE_JOBS_QUERY = (
    "AI engineer OR backend engineer OR data engineer OR MLOps OR "
    "cybersecurity engineer OR ML engineer Israel"
)

# Site-restricted searches. Each tuple: (source_tag, domain, query_template).
# The query template gets a 'last 24h' freshness hint via tbs=qdr:d in params.
SITE_SEARCHES = [
    ("greenhouse", "boards.greenhouse.io",
     'site:boards.greenhouse.io ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
    ("comeet", "comeet.co",
     'site:comeet.co ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
    ("lever", "jobs.lever.co",
     'site:jobs.lever.co ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
]


def _normalize_google_jobs(results: dict) -> list[dict]:
    out = []
    for r in results.get("jobs_results", []) or []:
        job_id = r.get("job_id") or str(
            abs(hash(r.get("title", "") + r.get("company_name", "")))
        )

        apply_options = r.get("apply_options", []) or []
        linkedin_apply_url = ""
        external_apply_url = ""
        for opt in apply_options:
            link = opt.get("link", "")
            if "linkedin.com" in link:
                linkedin_apply_url = link
            elif not external_apply_url:
                external_apply_url = link
        apply_url = linkedin_apply_url or external_apply_url or ""

        li_job_id = ""
        if "linkedin.com/jobs/view/" in apply_url:
            li_job_id = apply_url.split("/jobs/view/")[1].split("/")[0].split("?")[0]

        out.append({
            "id": f"google_{job_id}",
            "job_id": li_job_id,
            "title": r.get("title", ""),
            "company": r.get("company_name", ""),
            "url": apply_url or f"https://www.google.com/search?q={r.get('title','')}+{r.get('company_name','')}",
            "source": "google",
            "location": r.get("location", "Israel"),
            "easy_apply": bool(linkedin_apply_url),
            "description_snippet": (r.get("description") or "")[:200],
        })
    return out


def _normalize_site_search(results: dict, source_tag: str) -> list[dict]:
    """Convert SerpAPI google-engine organic_results into normalized jobs.
    For ATS sites we don't get clean company/title splits — title is the
    page title, company is parsed best-effort from the URL path."""
    out = []
    for r in results.get("organic_results", []) or []:
        url = r.get("link", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")

        if not url:
            continue

        # Best-effort company extraction from URL slug, e.g.:
        #   boards.greenhouse.io/companyname/jobs/12345 -> "companyname"
        #   jobs.lever.co/companyname/abc -> "companyname"
        #   www.comeet.co/jobs/companyname/ID -> "companyname"
        company = ""
        try:
            path = url.split("//", 1)[-1].split("/", 1)[1]
            parts = [p for p in path.split("/") if p]
            if source_tag == "greenhouse" and parts:
                company = parts[0]
            elif source_tag == "lever" and parts:
                company = parts[0]
            elif source_tag == "comeet":
                # Comeet pattern: "jobs/<company>/<position-id>"
                if len(parts) >= 2 and parts[0].lower() == "jobs":
                    company = parts[1]
                elif parts:
                    company = parts[0]
        except Exception:
            company = ""

        # Stable ID derived from URL
        job_id = str(abs(hash(url)))

        out.append({
            "id": f"{source_tag}_{job_id}",
            "job_id": "",                   # No LinkedIn job ID for ATS-hosted listings
            "title": title,
            "company": company,
            "url": url,
            "source": source_tag,
            "location": "Israel",
            "easy_apply": False,            # Phase 2 (Playwright) handles these
            "description_snippet": snippet[:200],
        })
    return out


def _run_google_jobs(api_key: str) -> list[dict]:
    params = {
        "engine": "google_jobs",
        "q": GOOGLE_JOBS_QUERY,
        "location": "Israel",
        "hl": "en",
        "chips": "date_posted:today",
        "api_key": api_key,
    }
    try:
        results = GoogleSearch(params).get_dict()
        if "error" in results:
            print(f"[google] SerpAPI error: {results['error']}", file=sys.stderr)
            return []
        return _normalize_google_jobs(results)
    except Exception as e:
        print(f"[google] error: {e}", file=sys.stderr)
        return []


def _run_site_search(api_key: str, source_tag: str, query: str) -> list[dict]:
    params = {
        "engine": "google",
        "q": query,
        "hl": "en",
        "tbs": "qdr:d",        # "past 24 hours"
        "num": 20,
        "api_key": api_key,
    }
    try:
        results = GoogleSearch(params).get_dict()
        if "error" in results:
            print(f"[{source_tag}] SerpAPI error: {results['error']}", file=sys.stderr)
            return []
        return _normalize_site_search(results, source_tag)
    except Exception as e:
        print(f"[{source_tag}] error: {e}", file=sys.stderr)
        return []


def run():
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        print(json.dumps({"jobs": [], "error": "SERPAPI_KEY not set"}))
        return

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    def _add_unique(jobs: list[dict]):
        for j in jobs:
            jid = j.get("id", "")
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            all_jobs.append(j)

    _add_unique(_run_google_jobs(api_key))
    for source_tag, _domain, query in SITE_SEARCHES:
        _add_unique(_run_site_search(api_key, source_tag, query))

    print(json.dumps({"jobs": all_jobs, "error": None, "count": len(all_jobs)}))


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_search_google_sources.py -v
```
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/search_google.py tests/test_search_google_sources.py
git commit -m "feat: search_google.py multi-source (Google Jobs + Comeet/Greenhouse/Lever)"
```

---

## Task 8: Replace `scripts/main.py` with `scripts/run_agent.py`

**Goal:** Single Phase-1 entrypoint. Loads `.env` via dotenv, runs workday check, verifies resume, syncs dedup from Sheets, runs both search scripts as subprocesses, aggregates + filters, applies LinkedIn jobs in-process, writes a partial `data/run_summary.json` ready for Phase 2 to extend.

**Files:**
- Create: `scripts/run_agent.py`
- Delete: `scripts/main.py`
- Modify: `tests/conftest.py` (no change needed if Task 5 left `scripts/` on `sys.path`)
- Test: `tests/test_run_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_agent.py`:

```python
"""Smoke tests for the run_agent orchestrator: workday gate + aggregation +
dry-run-aware LinkedIn apply pass."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_module(monkeypatch_env: dict, *args):
    env = {**os.environ, **monkeypatch_env}
    return subprocess.run(
        [sys.executable, "scripts/run_agent.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_aggregate_filters_excluded_titles_and_dedups(tmp_path, monkeypatch):
    """Run only the aggregate stage with synthetic jobs_*.json inputs and
    confirm dedup + excluded-title filtering work."""
    import importlib
    import sys as _sys

    # Point DATA_DIR at a tmp dir
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

    # Force the module to use our tmp data dir
    if "run_agent" in _sys.modules:
        del _sys.modules["run_agent"]
    monkeypatch.setattr("os.path.dirname", lambda f: str(tmp_path / "scripts"),
                        raising=False)
    # Easier: we'll just import and override DATA_DIR after import
    _sys.path.insert(0, str(ROOT / "scripts"))
    import run_agent
    monkeypatch.setattr(run_agent, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(run_agent, "NEW_JOBS_FILE",
                        str(data_dir / "new_jobs.json"))
    monkeypatch.setattr(run_agent, "ERRORS_FILE",
                        str(data_dir / "errors.log"))
    monkeypatch.setenv("MAX_APPLICATIONS_PER_RUN", "20")

    capped = run_agent.aggregate()

    titles = sorted(j["title"] for j in capped)
    # Excluded "Frontend Developer" filtered; already-applied "Backend Engineer
    # @ Acme" deduped by URL; survivors: ML Engineer, Senior Backend Engineer
    assert titles == ["ML Engineer", "Senior Backend Engineer"]


def test_skip_returns_skip_on_non_workday(monkeypatch):
    """If check_workday prints SKIP, run_agent must echo 'SKIP' as its first
    stdout line and exit 0 without doing any work."""
    monkeypatch.setenv("FORCE_SKIP", "true")  # honored by run_agent for tests
    result = _run_module({"FORCE_SKIP": "true"})
    assert result.returncode == 0
    assert result.stdout.splitlines()[0].strip() == "SKIP"


def test_dry_run_does_not_mark_linkedin_applied(tmp_path, monkeypatch):
    """In DRY_RUN, apply_to_job returns dry_run; run_agent must NOT call
    dedup_manager.mark_applied_local or append_to_sheet for those jobs."""
    import sys as _sys
    if "run_agent" in _sys.modules:
        del _sys.modules["run_agent"]
    _sys.path.insert(0, str(ROOT / "scripts"))
    import run_agent
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

    # Stub out the LinkedIn API so apply_linkedin._get_api returns a fake
    import apply_linkedin
    monkeypatch.setattr(apply_linkedin, "_get_api", lambda: object())

    summary = run_agent.apply_linkedin_jobs()

    assert summary["dry_run"] == 1
    assert summary["applied"] == 0
    assert sheet_calls == []
    assert local_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_run_agent.py -v
```
Expected: ImportError because `run_agent` doesn't exist yet.

- [ ] **Step 3: Create `scripts/run_agent.py`**

```python
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

# Load .env relative to project root (parent of scripts/)
ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# Make sibling scripts importable
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
    "sales", "marketing", "hr ", " hr", "human resource",
    "project manager", "product manager", "scrum master",
    "technical writer", "devrel", "developer relations",
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
        # Search scripts always print a JSON envelope as the LAST stdout line
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
        jobs = data.get("jobs", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
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

    # Sync dedup list (best-effort; on failure we keep the local cache)
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
```

- [ ] **Step 4: Delete the old `scripts/main.py`**

```bash
git rm scripts/main.py
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_run_agent.py -v
```
Expected: all three tests PASS.

- [ ] **Step 6: Run the full test suite**

```bash
pytest -q
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/run_agent.py tests/test_run_agent.py
git commit -m "feat: scripts/run_agent.py — Phase 1 orchestrator (replaces main.py)"
```

---

## Task 9: Create the cron prompt file

**Files:**
- Create: `scripts/cron_prompt.md`

This file is the verbatim text the local cron will fire. The cron itself just instructs Claude to "follow `scripts/cron_prompt.md`" so we can edit the procedure without re-creating the cron.

- [ ] **Step 1: Create the file**

Create `scripts/cron_prompt.md`:

```markdown
# Job Agent Cron Prompt

You are running the Local Job Application Agent for Daniel Lankry on his
Windows PC. Working directory: the project root.

## Step 1 — Phase 1: Search & LinkedIn apply (Python)

Run:

```bash
python scripts/run_agent.py
```

If the first stdout line is `SKIP`, stop and exit immediately — today is a
non-working day or Israeli holiday.

Otherwise the script has produced `data/new_jobs.json` and applied to all
LinkedIn jobs already, writing a partial `data/run_summary.json`.

## Step 2 — Phase 2: Non-LinkedIn auto-apply (Playwright MCP)

Read `data/new_jobs.json`. Filter to jobs where `source != "linkedin"`.
For each such job, follow the procedure in
`docs/superpowers/specs/2026-04-27-local-job-agent-design.md` Section 8
("Playwright apply procedure"). Honor `DRY_RUN` from `.env`.

After each job:
- Update `data/run_summary.json` counters (`applied` / `manual` / `failed`
  / `dry_run`) and append the job to the matching list.
- For non-dry-run outcomes, the procedure also writes to the Google Sheet
  via `python -c "import sys; sys.path.insert(0, 'scripts'); import dedup_manager; dedup_manager.append_to_sheet(...)"`.

Hard rules (Section 8 of spec):
- Never invent answers. Bail to `manual` if a required field has no
  match in `config/applicant.json`.
- Never check a checkbox unless it maps to a canned `true` answer.
- Never proceed past a captcha.
- Always screenshot to `data/apply_logs/<utc-ts>_<job-id>.png` before any
  submit.
- During `DRY_RUN=true`: log to `data/dry_run_log.jsonl` and DO NOT click submit.

## Step 3 — Report to ClickUp (MCP)

Read `data/run_summary.json`. Build a summary message in this format:

```
Job Agent | {MORNING if UTC hour < 12 else EVENING} Run | {YYYY-MM-DD}

Applied: {applied}  |  Manual: {manual}  |  Found: {total_new}  |
Failed: {failed}  |  DryRun: {dry_run}

Applied this run:
{bullet list — max 10 lines — format: • [Job Title] @ [Company] ([source])}
{If more than 10: "+ X more" on the last line}

Needs manual apply:
{bullet list of manual_jobs — format: • [Job Title] @ [Company] — [URL]}
{Or "None" if empty}

Errors: {list errors or "None"}
```

Post via the ClickUp MCP tool to channel `CLICKUP_CHAT_CHANNEL_ID` (read
from environment).

## Failure handling

If any phase errors out, still attempt Step 3 with whatever counts exist,
and include the error string in the "Errors" line.
```

- [ ] **Step 2: Commit**

```bash
git add scripts/cron_prompt.md
git commit -m "docs: cron prompt — twice-daily local agent runbook"
```

---

## Task 10: Pre-flight smoke test (manual UAT)

Before wiring the cron, prove Phase 1 works end-to-end on Daniel's machine
with real credentials.

- [ ] **Step 1: Daniel fills the credentials**

Daniel does this manually (do NOT prompt for or accept secrets in the
session):

```bash
cp .env.example .env
cp config/applicant.example.json config/applicant.json
# Edit both files in an editor. Set DRY_RUN=true. Make sure
# CLICKUP_CHAT_CHANNEL_ID, GOOGLE_SHEETS_APPLIED_SHEET_ID, and
# GOOGLE_SERVICE_ACCOUNT_JSON are real. Share the Google Sheet with the
# service account email (Editor access).
```

- [ ] **Step 2: Activate venv and confirm deps**

```bash
source venv/Scripts/activate
pip install -r requirements.txt
```
Expected: `Successfully installed ...` (or "already satisfied" lines).

- [ ] **Step 3: Confirm workday gate**

```bash
python scripts/check_workday.py
```
Expected: prints either `RUN` or `SKIP — ...`. If you're running this on
Friday/Saturday, the next steps will be skipped — that's correct.

- [ ] **Step 4: Run end-to-end with DRY_RUN**

Make sure `DRY_RUN=true` is set in `.env`. Then:

```bash
python scripts/run_agent.py 2>&1 | tail -60
```

If today is a non-working day (Friday/Saturday or Israeli holiday), the
first stdout line will be `SKIP` and nothing else runs — that's correct.
For the smoke test, do this on a working day OR temporarily replace the
holiday list in `scripts/check_workday.py` to simulate a working day.

**Do not** introduce a "force run" env var; the workday gate is a real
safety mechanism and we don't want a way to bypass it permanently.

Expected output, in order:
- `RUN` as the first line (or `SKIP` if non-working day)
- LinkedIn login attempt log (stderr)
- `New jobs to apply: <N>` line
- Per-job `[i/N] LinkedIn: <title> @ <company>` lines
- For each LinkedIn job: `(dry_run)` outcome (since DRY_RUN=true)
- Final `LinkedIn pass: 0 applied, 0 manual, 0 failed, N dry_run`

- [ ] **Step 5: Inspect the artifacts**

```bash
cat data/run_summary.json | head -40
ls data/jobs_*.json data/new_jobs.json
```
Expected:
- `data/jobs_linkedin.json` and `data/jobs_google.json` both exist with
  non-empty `"jobs": [...]` arrays
- `data/new_jobs.json` is a JSON array (capped at MAX_APPLICATIONS_PER_RUN)
- `data/run_summary.json` shows `dry_run > 0` if there were LinkedIn jobs

- [ ] **Step 6: If anything fails, debug before proceeding**

Don't move to Task 11 until the smoke run produces a clean `run_summary.json`.

---

## Task 11: Configure the local Claude cron

This step is interactive — it uses `CronCreate`. The agent running this plan
should pause and confirm with Daniel before creating the cron.

- [ ] **Step 1: Confirm intent with the user**

Before calling `CronCreate`, ask Daniel:
- "Ready to schedule the local cron? It will fire at 09:00 and 17:00
  Israel time, Sundays through Thursdays."
Wait for explicit confirmation.

- [ ] **Step 2: Create the cron**

Use the `CronCreate` tool with these parameters:

- `expression`: `0 9,17 * * 0-4`
- `timezone`: `Asia/Jerusalem`
- `working_directory`: `C:\Users\Daniel\Desktop\Files\Projects\JobApplayingAgent`
- `prompt`: `Follow the runbook in scripts/cron_prompt.md from the working directory.`

(Exact field names depend on the local `CronCreate` tool's schema; load
the schema first via `ToolSearch` with `select:CronCreate` to confirm.)

- [ ] **Step 3: Verify cron is registered**

Use `CronList` to confirm the new cron entry is present. Note its ID for
the memory update in Task 13.

---

## Task 12: Pause the cloud routines

- [ ] **Step 1: Confirm with the user**

Ask: "Ready to pause the two cloud routines? They will be deleted in ~14
working days once local cron is verified stable."

- [ ] **Step 2: Pause via RemoteTrigger**

Load the `RemoteTrigger` tool schema via `ToolSearch` with
`select:RemoteTrigger`. Then call its update/pause action twice — once
each for:
- `trig_01UEhwUL6p1pkaYaFNFqSZZm` (morning)
- `trig_01PVoATaa9dPSQi4yZ8Bq85j` (evening)

Set them to a paused/disabled state per the tool's schema (most likely
`active=false`).

- [ ] **Step 3: Verify**

List remote triggers and confirm both show paused.

---

## Task 13: Update memory

**Files:**
- Modify: `C:\Users\Daniel\.claude\projects\C--Users-Daniel-Desktop-Files-Projects-JobApplayingAgent\memory\project_job_agent.md`

- [ ] **Step 1: Update the project memory**

Edit the memory file to:
- Note that local cron is now the active scheduler
- Add the new cron ID (from Task 11)
- Note the cloud routines are paused (date)
- Add: cron ends DRY_RUN and cloud-routine deletion are scheduled
  for ~14 working days after first local fire (note exact dates)

- [ ] **Step 2: Commit doesn't apply** — memory files live outside the repo. Just save the edits.

---

## Task 14: First-day end-to-end verification (manual UAT)

After the cron's first scheduled fire:

- [ ] **Step 1: Check ClickUp Chat**

Confirm the summary message arrived in the configured channel with the
correct format and nonzero `Found:` count.

- [ ] **Step 2: Check the artifacts on disk**

```bash
ls -la data/apply_logs/         # screenshots from Phase 2
cat data/dry_run_log.jsonl      # what would have been submitted
cat data/run_summary.json
cat data/errors.log
```
Expected:
- At least one screenshot per non-LinkedIn job that reached the form
- `dry_run_log.jsonl` has one entry per dry-run application
- `errors.log` is empty (or only has expected non-fatal warnings)

- [ ] **Step 3: Check the Google Sheet**

For DRY_RUN runs the Sheet should ONLY receive `Manual` or `Failed`
rows (no `Applied` rows). Confirm.

- [ ] **Step 4: Capture any `unanswered_questions.log` entries**

```bash
cat data/unanswered_questions.log
```
For each entry, decide whether to extend `config/applicant.json` so future
runs can answer it.

---

## Task 15: Open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/local-job-agent
```

- [ ] **Step 2: Create the PR**

Use `gh pr create` with a summary that references the spec and the cron
status (live, DRY_RUN active, cloud routines paused).

---

## Out of plan: 14-day DRY_RUN review

Daniel's manual review after 14 working days, not part of this plan:
- Inspect `data/dry_run_log.jsonl` and `data/apply_logs/`
- If satisfied, flip `DRY_RUN=false` in `.env`
- After another 14 working days of stable live runs: delete the two cloud
  routines and update the memory file to remove the routine IDs.
