# Cron Setup Prompt — Local Job Agent

**When to use:** Paste the block below into Claude Code Desktop (any session
inside this project) any time you want to (re)arm the local twice-daily cron
that runs the job agent. You'll need to do this:

- The first time you set up the agent on a new machine
- Once a week (the cron auto-expires after 7 days)
- After restarting Claude Code (the cron dies with the session)
- Whenever you want to be sure the cron is actually scheduled

The prompt is idempotent: it verifies first, deletes any stale cron, then
creates a fresh one. Safe to run any number of times.

---

## Paste this prompt

```
You are setting up the local twice-daily cron for the Job Application
Agent. Working directory is the project root. Be terse.

Steps, in order:

1. Verify the runbook exists:
   - Confirm routines.md is at the project root.
   - Confirm scripts/run_agent.py exists.
   - Confirm config/applicant.json exists (the real one, not just the
     example) — flag if missing but continue.
   - Confirm .env exists and contains CLICKUP_CHAT_CHANNEL_ID,
     LINKEDIN_EMAIL, SERPAPI_KEY, GOOGLE_SHEETS_APPLIED_SHEET_ID,
     GOOGLE_SERVICE_ACCOUNT_JSON. Don't print the values — just
     confirm presence.

2. List existing crons (CronList). If any cron's prompt mentions
   "Job Application Agent" or "routines.md", delete it (CronDelete).

3. Create the new cron:
   - cron expression: 7 9,17 * * 0-4
   - timezone: the local PC time (which is Asia/Jerusalem for Daniel)
   - recurring: true
   - durable: true
   - prompt:
       Local Job Application Agent run.

       Working directory: C:\Users\Daniel\Desktop\Files\Projects\JobApplayingAgent

       Open routines.md in the project root and execute it end-to-end.
       The first thing it instructs is `python scripts/run_agent.py` —
       if its first stdout line is SKIP, stop silently. Otherwise
       continue with Phase 2 (Playwright MCP for non-LinkedIn jobs) and
       Phase 3 (ClickUp MCP summary post) per the file.

4. Verify with CronList that exactly one cron matching the above expression
   is now scheduled, and report its ID.

5. Print a one-line summary in this format:
   "Cron <ID> armed: 9:07 + 17:07 IL, Sun-Thu. Expires in 7 days. Next fire: <date/time>."

If anything is missing in step 1, stop and report which file is missing.
Do not create the cron until prerequisites are confirmed.
```

---

## Notes

- The cron only fires while Claude Code is running on the PC. If your PC
  is off or Claude is closed at fire time, that slot is skipped — the
  dedup list in `data/applied_jobs.json` ensures jobs aren't re-applied
  later, so missing a slot is harmless beyond the missed applies.
- The minute is `7` (not `0`) on purpose — avoids the global cron-storm
  on top-of-hour where every scheduled job in the world fires at once.
- Schedule is `0-4` for day-of-week, which is **Sunday through Thursday**
  in standard cron (Sunday = 0). This matches Israeli working days.
- If you want to also re-enable the cloud-side routines as a backup
  (currently paused as `trig_01UEhwUL6p1pkaYaFNFqSZZm` and
  `trig_01PVoATaa9dPSQi4yZ8Bq85j`), tell the agent to also call
  RemoteTrigger update with `{"enabled": true}` on both — but note that
  the cloud routines clone from `master`, so they'd run the OLD code
  until `feat/local-job-agent` is merged.
