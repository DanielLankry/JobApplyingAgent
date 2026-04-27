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
- For non-dry-run outcomes, also write to the Google Sheet by running:
  ```bash
  python -c "import sys; sys.path.insert(0, 'scripts'); import dedup_manager; dedup_manager.append_to_sheet(JOB_DICT, status=STATUS, notes=NOTES)"
  ```
  (Substitute the real values for JOB_DICT, STATUS, NOTES.)

Hard rules (Section 8 of the spec):
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

Applied: {applied}  |  Manual: {manual}  |  Found: {total_new}  |  Failed: {failed}  |  DryRun: {dry_run}

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
