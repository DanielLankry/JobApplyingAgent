# Local Job Application Agent — Design

**Date:** 2026-04-27
**Status:** Approved (design); pre-implementation
**Owner:** Daniel Lankry
**Supersedes:** Cloud routines `trig_01UEhwUL6p1pkaYaFNFqSZZm` (morning) and `trig_01PVoATaa9dPSQi4yZ8Bq85j` (evening), which will be paused after the local agent is verified and deleted after ~14 working days of stable local runs.

---

## 1. Goal

A fully local, twice-daily job-search-and-apply agent that runs from this Windows PC via a local Claude Code cron, searches LinkedIn + Comeet + Greenhouse + Lever + open-web, auto-applies where it can confidently do so, and posts a per-run summary to a ClickUp Chat channel.

**Working schedule:** Sunday–Thursday, 09:00 and 17:00 Israel time (`Asia/Jerusalem`), skipping major Israeli public holidays (handled by `scripts/check_workday.py`).

---

## 2. Non-goals

- Auto-applying through LinkedIn via browser automation. LinkedIn aggressively detects automation; we keep LinkedIn on the existing `linkedin-api` library to avoid account restriction.
- Workday auto-apply. Workday requires per-tenant account creation; out of scope. Workday-hosted jobs surface in the "Manual" bucket.
- LLM-invented answers to free-text questions. The agent never guesses; it bails to manual.
- Cloud-side execution. The remote routines on Claude Code Cloud are being retired in favor of this local agent.
- Mobile/native apps. Web only.

---

## 3. High-level architecture

Each cron run executes three phases:

1. **Search & filter (Python, ~30s)** — `scripts/run_agent.py` runs the workday check, searches all sources, dedups against the Google Sheet, filters out excluded titles, and writes `data/new_jobs.json`. It also handles LinkedIn auto-apply in-process via `apply_linkedin.py`.

2. **Non-LinkedIn auto-apply (Claude + Playwright MCP, ~10–15 min)** — Claude reads `data/new_jobs.json`, filters to `source != "linkedin"`, and processes each job through the Playwright apply procedure (Section 8). Each attempt classifies as `applied`, `manual`, `failed`, or (if `DRY_RUN=true`) `dry_run`.

3. **Report (Claude, ~5s)** — Claude reads `data/run_summary.json` and posts the formatted summary to ClickUp Chat via the ClickUp MCP tool.

The cron prompt that fires twice a day is intentionally short. Most logic lives in:
- The Python pipeline (search, dedup, LinkedIn apply, summary writes)
- `config/applicant.json` (canned answers — no LLM-invented content)
- This spec's Section 8 (Playwright apply procedure, including bail-out rules)

---

## 4. Source list & search strategy

| Source | Discovery | Apply path |
|---|---|---|
| LinkedIn | `linkedin-api` Python library (existing `search_linkedin.py`) | `apply_linkedin.py` — Easy Apply via internal voyager API |
| Comeet | SerpAPI Google query: `site:comeet.co/<role-keywords> Israel` | Playwright MCP |
| Greenhouse | SerpAPI Google query: `site:boards.greenhouse.io <role> Israel` | Playwright MCP |
| Lever | SerpAPI Google query: `site:jobs.lever.co <role> Israel` | Playwright MCP |
| Open-web | SerpAPI Google query: `"<role>" Israel hiring` | Playwright MCP (best effort; bails if form isn't recognizable) |

`scripts/search_google.py` will be extended to issue **multiple SerpAPI queries** per run (one per source × a small set of role keywords), tag each result with its `source`, and deduplicate by URL.

Per-run query budget: target ≤ 6 queries × 2 runs/day × 22 days ≈ **264 queries/month**. The free SerpAPI tier (100/mo) is insufficient; assume we move to paid SerpAPI ($50/mo, 5,000 searches) early. If we need to stay free temporarily, the fallback is to run searches **only at 09:00** and reuse `data/new_jobs.json` for the 17:00 apply pass — drops to ~132/mo, still over free tier.

### Target roles (unchanged from `routines.md`)

Backend, Data, AI/ML, Generative AI, MLOps, Data Science, Cyber, Cloud+AI/Sec.

### Excluded titles (unchanged from `main.py`)

Full-stack, frontend, mobile, QA/SDET, sales, marketing, HR, project/product manager, scrum master, technical writer, DevRel.

---

## 5. File & module layout

```
JobApplayingAgent/
├── .env                          # gitignored — real credentials
├── .env.example                  # updated: drop GOOGLE_DRIVE_RESUME_FILE_ID
├── Daniel_Lonkry_Resume.pdf      # local resume (single source)
├── config/
│   ├── applicant.json            # gitignored — canned answers (Section 7)
│   └── applicant.example.json    # committed template
├── data/
│   ├── applied_jobs.json         # local dedup mirror of Google Sheet
│   ├── new_jobs.json             # output of Phase 1 (search/aggregate)
│   ├── run_summary.json          # accumulated outcome of phases 1 + 2
│   ├── unanswered_questions.log  # questions Claude bailed on (review-and-extend)
│   ├── apply_logs/               # screenshot + DOM snapshot per apply attempt
│   ├── dry_run_log.jsonl         # what *would* have been submitted in DRY_RUN mode
│   ├── chrome_profile/           # persistent Playwright Chrome profile
│   └── errors.log
├── scripts/
│   ├── run_agent.py              # NEW — orchestrates Phase 1 end-to-end
│   ├── apply_linkedin.py         # KEEP — LinkedIn API auto-apply
│   ├── search_linkedin.py        # KEEP
│   ├── search_google.py          # EXTEND — multi-query SerpAPI driver
│   ├── dedup_manager.py          # KEEP
│   ├── check_workday.py          # KEEP
│   └── resume_manager.py         # DELETE
└── docs/superpowers/specs/
    └── 2026-04-27-local-job-agent-design.md   # this file
```

### Module responsibilities

- **`run_agent.py`** — single Phase-1 entrypoint. Loads `.env` (via `python-dotenv`), runs the workday check, verifies the local resume PDF exists, syncs the dedup list from Sheets, runs all searches in sequence (failures isolated per source), aggregates + filters, writes `new_jobs.json`, then immediately processes all LinkedIn jobs in-process via `apply_linkedin.py` and writes a partial `run_summary.json`. Exits with stdout starting `"SKIP"` if today is a non-working day.

- **`search_google.py` (extended)** — accepts a list of `(source, query)` pairs from a config block (defined in code), issues each via SerpAPI, parses results into normalized job dicts (`title`, `company`, `url`, `source`, `description_snippet`), and writes `data/jobs_google.json` with all sources merged. Each result tagged with its `source` for downstream routing.

- **`dedup_manager.py`** (existing, unchanged behavior) — `--action=load` pulls applied URLs from Sheet to `applied_jobs.json`; `append_to_sheet(job, status, notes)` appends a new row.

- **`apply_linkedin.py`** (existing, modified) — LinkedIn-only Easy Apply via voyager API. Modification: respect the `DRY_RUN` env flag — when `DRY_RUN=true`, skip the actual `easyApply` POST and return `{"status": "dry_run", "reason": "DRY_RUN mode"}`.

- **Playwright apply** — not a Python script. Lives as a documented procedure (Section 8) executed by Claude during Phase 2.

---

## 6. `.env` schema (final)

```
# ---- Applicant Profile ----
APPLICANT_FIRST_NAME=Daniel
APPLICANT_LAST_NAME=Lankry
APPLICANT_EMAIL=lankrydaniel7@gmail.com
APPLICANT_PHONE=+972...
APPLICANT_CITY=Tel Aviv
APPLICANT_LINKEDIN_URL=...
APPLICANT_GITHUB_URL=...
APPLICANT_PORTFOLIO_URL=
APPLICANT_YEARS_EXPERIENCE=3

# ---- Google Service Account (for Sheets only) ----
GOOGLE_SERVICE_ACCOUNT_JSON={...one line...}

# ---- Google Sheets ----
GOOGLE_SHEETS_APPLIED_SHEET_ID=...

# ---- LinkedIn ----
LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...

# ---- SerpAPI ----
SERPAPI_KEY=...

# ---- ClickUp ----
CLICKUP_API_TOKEN=pk_...
CLICKUP_CHAT_CHANNEL_ID=...

# ---- Run Settings ----
MAX_APPLICATIONS_PER_RUN=20
DRY_RUN=true                    # Phase 2 dry-run flag (true for first 2 weeks)
RESUME_PDF_PATH=Daniel_Lonkry_Resume.pdf  # relative to project root
```

**Removed vs. previous `.env.example`:** `GOOGLE_DRIVE_RESUME_FILE_ID` (no longer needed; resume is local).

---

## 7. `config/applicant.json` (canned answers)

This is the **only** source of answers Claude is allowed to use during Phase 2. If a required field on a form does not match a key here, the agent bails to manual. Claude **never invents answers**.

### Fields (committed as `applicant.example.json`)

```jsonc
{
  "first_name": "Daniel",
  "last_name": "Lankry",
  "full_name": "Daniel Lankry",
  "email": "lankrydaniel7@gmail.com",
  "phone": "+972...",
  "phone_country_code": "+972",
  "address_line_1": "",
  "city": "Tel Aviv",
  "state_region": "Tel Aviv District",
  "postal_code": "",
  "country": "Israel",
  "linkedin_url": "https://www.linkedin.com/in/...",
  "github_url": "https://github.com/...",
  "portfolio_url": "",
  "resume_pdf_path": "Daniel_Lonkry_Resume.pdf",
  "years_experience": 3,
  "current_company": "",
  "current_title": "",
  "highest_education": "B.Sc. ...",
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
  "cover_letter_short": "I am excited to apply and bring my background in <role-area> to your team.",
  "cover_letter_long": null
}
```

Daniel fills the real `config/applicant.json`. Anything left as `""` or `null` causes the agent to bail to manual when that field is required.

### Field-matching rules

For each form field, Claude attempts to match on (in order):
1. Exact case-insensitive match on the field's accessible name / label
2. Substring match (e.g., a form label of "First Name *" matches `first_name`)
3. Common synonyms table (e.g., `mobile` → `phone`, `linkedin profile` → `linkedin_url`)

If no match found and the field is required → bail. The unmatched label is appended to `data/unanswered_questions.log` with timestamp + job URL so Daniel can extend the canned-answers file.

---

## 8. Playwright apply procedure (per non-LinkedIn job)

Executed by Claude using `mcp__playwright__*` tools. Run sequentially per job (no parallelism).

### Per-job steps

1. **Navigate**
   - `browser_navigate` to `job.url`
   - `browser_snapshot` to get accessibility tree

2. **Pre-apply bail checks** — if any are true, classify as `manual` and skip:
   - Page contains "Sign in" / "Log in" / "Create account" as required for application
   - Captcha element detected (reCAPTCHA, hCaptcha, Cloudflare challenge)
   - Page is a Workday or Workday-clone URL (`*.myworkdayjobs.com`)
   - Page returns 404 / job no longer available

3. **Locate apply button**
   - Find element with role `button` or `link` matching `/apply|הגש מועמדות|submit application/i`
   - If multiple, prefer one with text exactly matching `Apply` or `Apply now`
   - If none → classify as `manual`, reason `"No apply button found"`

4. **Open apply form**
   - `browser_click` the apply button
   - `browser_snapshot` the resulting form

5. **Form analysis**
   - Enumerate all form inputs: text, email, tel, textarea, select, checkbox, radio, file
   - For each input, capture: accessible name/label, `required` flag, max length, options (for select/radio)

6. **Field filling**
   - For each required field, attempt match against `applicant.json` (rules in Section 7)
   - **Bail conditions** — any of these → classify as `manual`:
     - Required free-text field with `maxlength > 200` or no maxlength, no canned `cover_letter_long` (it's `null`)
     - Required field with no canned-answer match
     - Required file upload other than the single resume slot
     - Form has more than 3 "Next" steps without reaching submit
     - Required field whose value would be empty string from canned answers
   - For matched fields:
     - Text/email/tel/textarea → `browser_fill_form`
     - Select/radio → match canned answer to one of the options (case-insensitive); if none match, bail
     - Checkbox → check only if explicitly required and the canned answer for that key is `true` (e.g., `agree_to_terms`)
     - File upload (resume slot) → `browser_file_upload` with `RESUME_PDF_PATH`

7. **Pre-submit verification**
   - `browser_snapshot` the filled form
   - Confirm all required fields show non-empty values
   - `browser_take_screenshot` → save to `data/apply_logs/<UTC-timestamp>_<job-id>.png`
   - Append a JSON record to `data/apply_logs/<UTC-timestamp>_<job-id>.json` with: job, fields filled (key + value), bail-out reason if any

8. **Submit gate**
   - **If `DRY_RUN=true` (default for first 2 weeks):**
     - Append entry to `data/dry_run_log.jsonl`: `{ts, job, would_submit: true, fields, screenshot_path}`
     - Classify as `dry_run`
     - **Do not click submit**
   - **If `DRY_RUN=false`:**
     - `browser_click` the submit button
     - `browser_wait_for` either: a success indicator (URL change, text matching `/thank you|application received|submitted|תודה/i`) or a failure indicator (error text)
     - On success → classify as `applied`
     - On failure or timeout (15s) → classify as `failed`, capture screenshot

9. **Record outcome**
   - **For `applied`, `manual`, or `failed` outcomes:** append to Google Sheet via `dedup_manager.append_to_sheet(job, status=..., notes=...)` and append URL to local `applied_jobs.json` (so the job is not retried).
   - **For `dry_run` outcomes:** do **not** write to the Google Sheet, do **not** add to `applied_jobs.json`. The job stays eligible so it can be applied to live once `DRY_RUN` flips to `false`. Only `data/dry_run_log.jsonl` and the screenshot in `data/apply_logs/` are written.
   - Update in-memory counters that will be flushed to `run_summary.json`.

10. **Inter-job pause** — wait 4 seconds before next job (matches existing LinkedIn cadence).

### Hard rules (never violated)

- Never invent answers to free-text questions.
- Never check a checkbox that wasn't pre-declared as a canned `true` answer (e.g., never silently agree to a "Subscribe to marketing emails").
- Never submit without first capturing a screenshot to `apply_logs/`.
- Never proceed past a captcha; always classify those as `manual`.
- Never create an account on the company's site.
- Never reuse a Chrome session across job sites in a way that leaks cookies into the wrong domain — the persistent profile is intentional only for cookie persistence on legitimately-revisited domains.

---

## 9. Cron schedule

- **Cron expression:** `0 9,17 * * 0-4`
- **Timezone:** `Asia/Jerusalem`
- **Mechanism:** local `CronCreate` on this machine
- **Working-directory:** `C:\Users\Daniel\Desktop\Files\Projects\JobApplayingAgent`
- **Prompt:** see Section 10

The Python pipeline additionally honors `check_workday.py` for Israeli public holidays — cron may fire on a holiday Sun–Thu, but `run_agent.py` will print `SKIP` and exit cleanly.

---

## 10. Cron prompt (verbatim)

```
You are running the local Job Application Agent for Daniel Lankry.

Step 1 — Search & LinkedIn apply (Python):
Run: python scripts/run_agent.py
If the first line of stdout is "SKIP", stop and exit (non-working day).
Otherwise it has produced data/new_jobs.json and applied to all LinkedIn
jobs already, writing partial counts into data/run_summary.json.

Step 2 — Non-LinkedIn auto-apply (Playwright MCP):
Read data/new_jobs.json. For each job where source != "linkedin", follow
the per-job procedure in
docs/superpowers/specs/2026-04-27-local-job-agent-design.md
(Section 8: "Playwright apply procedure"). Honor DRY_RUN from .env.
Update data/run_summary.json after each job.

Step 3 — Report to ClickUp (MCP):
Read data/run_summary.json. Format the summary message per
routines.md "Summary message format" section. Post via the ClickUp MCP
tool to channel CLICKUP_CHAT_CHANNEL_ID. Use MORNING run type if UTC hour
< 12, otherwise EVENING.

If any phase errors out, still attempt Step 3 with whatever counts exist,
and include the error in the summary's "Errors" line.
```

---

## 11. DRY_RUN policy (first 2 weeks)

- `DRY_RUN=true` is the **default** in `.env.example` and the **required** initial value in the real `.env`.
- During DRY_RUN, the Playwright apply phase performs every step except the final submit click. It writes a JSONL record to `data/dry_run_log.jsonl` per job and a screenshot to `data/apply_logs/`.
- LinkedIn auto-apply is **also** subject to DRY_RUN: `apply_linkedin.py` checks the env flag and, if true, returns `status="dry_run"` without calling the Easy Apply endpoint.
- After 14 working days of stable runs, Daniel reviews `dry_run_log.jsonl` end-to-end. If satisfied, he flips `DRY_RUN=false`.
- Cloud routines remain **paused** (not deleted) throughout this 2-week window.

---

## 12. Cloud-routine retirement

| Day | Action |
|---|---|
| Day 1 (local cron starts) | Pause `trig_01UEhwUL6p1pkaYaFNFqSZZm` and `trig_01PVoATaa9dPSQi4yZ8Bq85j` |
| Day 14 (DRY_RUN ends, live submit) | Keep cloud routines paused as fallback |
| Day 28 (2 weeks of live runs stable) | Delete both cloud routines; update `memory/project_job_agent.md` to remove the routine IDs |

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Token consumption from Playwright runs exceeds Claude Max comfort | Cap `MAX_APPLICATIONS_PER_RUN=20`; bail-out rules are aggressive; LinkedIn never goes through Playwright |
| LinkedIn account flagged for automation | Keep LinkedIn on `linkedin-api`; Playwright never touches LinkedIn |
| Wrong values silently submitted to a real ATS | Strict canned-answer policy; pre-submit screenshot; DRY_RUN for 2 weeks; no LLM-invented answers |
| ATS site updates break selectors | Snapshot-based (accessibility tree) rather than CSS selectors; failures classify as `failed` not silent skip; review `errors.log` weekly |
| SerpAPI free-tier exhausted mid-month | Move to paid SerpAPI ($50/mo, 5,000 searches) — flagged as expected cost |
| ClickUp Chat channel ID still unknown | Hard prerequisite — listed as a setup blocker; first run cannot proceed without it |
| Captchas appear on a previously-clean ATS | Bail-out check exists; classified as `manual` |
| Playwright Chrome profile gets bot-flagged | Persistent Chrome profile, real (non-headless) Chrome via Playwright MCP defaults; 4s pause between jobs. Note: per-keystroke human-like typing isn't natively exposed by Playwright MCP `browser_fill_form` — if bot-flagging becomes a real problem in v1 we add a typing-delay wrapper in v2 |
| Cron misfires while Claude Code is closed | Document that Claude Code must be running locally for the cron to fire; consider Windows Task Scheduler fallback for v2 if reliability is a problem |

---

## 14. Out of scope (v1)

- Comeet/Greenhouse/Lever via direct ATS-API integration (would bypass Playwright but adds per-company API keys)
- Workday auto-apply
- Multi-resume support (one resume only — `Daniel_Lonkry_Resume.pdf`)
- Cover-letter generation per role
- Email + recruiter follow-up automation
- Web UI / dashboard
- Cross-machine sync of canned answers or applied-jobs state

---

## 15. Acceptance criteria

The agent is considered shipped when:

1. `python scripts/run_agent.py` runs end-to-end on Daniel's machine without errors and writes `new_jobs.json` + a partial `run_summary.json`.
2. The local cron fires successfully at the next scheduled working-day slot.
3. During DRY_RUN, Phase 2 produces at least one `data/apply_logs/*.png` showing a fully-filled form for a non-LinkedIn job, with no submission.
4. The ClickUp summary message arrives in the configured channel with non-zero `total_new` count.
5. During DRY_RUN: the Google Sheet receives a new row only for `Manual` or `Failed` non-LinkedIn outcomes (LinkedIn jobs all return `dry_run` and are not written). After DRY_RUN ends: the Sheet receives at least one `Applied` row per run with successful auto-apply.
6. After 14 working days, Daniel approves switching `DRY_RUN=false` and live applies begin.
7. Cloud routines are paused on Day 1 and deleted by Day 28.
