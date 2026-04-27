# Job Application Agent — Local Routine

You are the **Local Job Application Agent** for **Daniel Lankry**, running on
his Windows PC.

## How this routine fires

This file is the single source of truth for the agent's run procedure.
It runs in any of three ways:

1. **Local Claude cron** — fires automatically twice a day on Israeli working
   days (`7 9,17 * * 0-4` IL time) **as long as a Claude Code session is
   alive on the PC**. The cron prompt simply says "follow `routines.md`".
2. **Manual run by Daniel** — Daniel types `follow routines.md` in any
   Claude Code session in the project, or pastes the steps below directly.
3. **Recovery / catch-up run** — if the PC was off at 09:00 IL, Daniel can
   trigger a manual run from the most recent missed slot.

The agent does NOT need the PC to be running 24/7 — only at the moments a
run is desired. Missed slots are simply skipped (the dedup list ensures
no duplicate applications).

---

## Run procedure

### Step 1 — Phase 1: search & LinkedIn auto-apply (Python)

Working directory: the project root (`C:\Users\Daniel\Desktop\Files\Projects\JobApplayingAgent`).

Run the Phase 1 entrypoint, preferring the project's venv if it exists
(falls back to system Python so a missing venv doesn't break the run):

```bash
if [ -x "venv/Scripts/python.exe" ]; then
  venv/Scripts/python.exe scripts/run_agent.py
else
  python scripts/run_agent.py
fi
```

**If the first stdout line is `SKIP`** — today is a non-working day or an
Israeli public holiday. Stop and exit immediately. Do nothing else.

Otherwise, the script has produced:
- `data/jobs_linkedin.json` and `data/jobs_google.json` (raw search results)
- `data/new_jobs.json` (filtered, deduped, capped at `MAX_APPLICATIONS_PER_RUN`)
- `data/run_summary.json` (partial — LinkedIn pass complete, Phase 2 still pending)

It has also already applied to all LinkedIn Easy Apply jobs in-process.
If `DRY_RUN=true` (the first 14 working days), those LinkedIn jobs landed
under the `dry_run` bucket — they were NOT actually submitted and were NOT
written to the Google Sheet, so they remain re-applyable when DRY_RUN flips.

### Step 2 — Phase 2: non-LinkedIn auto-apply (Playwright MCP)

Read `data/new_jobs.json`. Filter to jobs where `source != "linkedin"`
(these are Comeet, Greenhouse, Lever, and other open-web ATS results).

For each such job, follow the **Playwright apply procedure** in
`docs/superpowers/specs/2026-04-27-local-job-agent-design.md` Section 8.
Use the `mcp__playwright__*` tools. Honor `DRY_RUN` from `.env`.

After each job:
- Update `data/run_summary.json` counters (`applied` / `manual` / `failed` /
  `dry_run`) and append the job to the matching list.
- For non-`dry_run` outcomes, write to the Google Sheet:
  ```bash
  python -c "import sys; sys.path.insert(0, 'scripts'); import dedup_manager as d; d.append_to_sheet(JOB_DICT, status=STATUS, notes=NOTES)"
  ```
  (Substitute real values for `JOB_DICT`, `STATUS`, `NOTES`.)

**Hard rules** (Section 8 of the spec — never violated):
- **Never invent answers.** If a required field has no match in
  `config/applicant.json`, classify as `manual` and bail.
- **Never check a checkbox** unless it maps to a canned `true` answer.
- **Never proceed past a captcha or bot challenge** — bail to `manual`.
- **Always screenshot to `data/apply_logs/<utc-ts>_<job-id>.png`** before
  any submit (or before bailing on a filled form, for forensics).
- During `DRY_RUN=true`: log to `data/dry_run_log.jsonl` and **do not** click
  submit.

### Step 3 — Report to ClickUp Chat (MCP)

Read `data/run_summary.json`. Build a summary message in this exact format:

```
Job Agent | {MORNING if UTC hour < 12 else EVENING} Run | {YYYY-MM-DD}

Applied: {applied}  |  Manual: {manual}  |  Found: {total_new}  |  Failed: {failed}  |  DryRun: {dry_run}

Applied this run:
{bullet list — max 10 lines — format: • [Job Title] @ [Company] ([source])}
{If more than 10: "+ X more" on the last line}

Needs manual apply:
{bullet list of manual_jobs — format: • [Job Title] @ [Company] — [URL]}
{Or "None" if empty}

Errors: {list errors or "None"}
```

Post via the **ClickUp MCP tool** to the channel whose ID is in
`CLICKUP_CHAT_CHANNEL_ID` (read from environment).

---

## Failure handling

- A failure in one search source must NOT stop the others.
- A failure in one apply attempt must NOT stop the next.
- All errors land in `data/errors.log` with a UTC timestamp.
- If any phase errors out, **still attempt Step 3** with whatever counts
  exist, and include the error string in the "Errors" line.
- If Sheets writes fail mid-run, fall back to `data/failed_sheet_writes.json`
  (handled automatically by `dedup_manager.append_to_sheet`).

---

## Configuration files (must exist before first run)

| File | Purpose |
|---|---|
| `.env` | All credentials (LinkedIn, SerpAPI, Google service account, ClickUp) + `DRY_RUN`, `RESUME_PDF_PATH` |
| `config/applicant.json` | Canned answers for ATS form fields (Phase 2) |
| `Daniel_Lonkry_Resume.pdf` | The resume — local file, no Drive download |

Both `.env` and `config/applicant.json` are gitignored. Templates exist
at `.env.example` and `config/applicant.example.json`.

---

## Target roles & exclusions

Both lists are enforced by `scripts/run_agent.py` and the search scripts.
Source of truth is the spec; this is a quick reference.

**Apply to (any of):**
Backend Engineer / Backend Developer / API Developer ·
Data Engineer / Data Platform / Analytics Engineer ·
ML Engineer / Machine Learning Engineer / AI Engineer / AI Developer ·
GenAI / LLM Engineer / Prompt Engineer / AI Deployment Engineer ·
MLOps / AI Ops / Model Deployment ·
Data Scientist / Applied Scientist ·
Cybersecurity / Security Engineer / Pen Tester / AppSec / DevSecOps /
Red Team / Security Researcher ·
Cloud Engineer (with AI or Security focus) / Solutions Architect (AI/Security)

**Do NOT apply to:**
Full-Stack · Frontend · Mobile · QA/SDET · Sales · Marketing · HR ·
Project Manager · Product Manager · Scrum Master · Technical Writer ·
DevRel.

---

## DRY_RUN policy

- Default is `DRY_RUN=true`. Active for the first 14 working days starting
  from the first local fire.
- During DRY_RUN, every apply attempt (LinkedIn API + Playwright) runs
  every step **except** the final submit. Outcomes are classified as
  `dry_run` and logged to `data/dry_run_log.jsonl` and `data/apply_logs/`.
- DRY_RUN entries do **not** write to the Google Sheet and do **not** add
  to `data/applied_jobs.json` — so jobs stay re-applyable when the flag
  flips to `false`.
- After 14 working days of stable runs, Daniel reviews `dry_run_log.jsonl`
  end-to-end. If satisfied, he flips `DRY_RUN=false` in `.env`.
- Cloud routines (`trig_01UEhwUL6p1pkaYaFNFqSZZm`, `trig_01PVoATaa9dPSQi4yZ8Bq85j`)
  remain paused throughout this window as a safety backup.
