#!/usr/bin/env python3
"""
Search Google Jobs via SerpAPI — no browser required.
Uses 2 broad keywords to stay within the 100 searches/month free tier.
(2 keywords × 2 runs/day × 22 working days = 88 searches/month)
Outputs JSON to stdout.
"""

import json
import os
import sys

import serpapi as _serpapi

# Two broad queries cover all target roles within the free tier limit
SEARCH_QUERIES = [
    "AI engineer OR backend engineer OR data engineer OR MLOps Israel",
    "cybersecurity engineer OR security engineer OR penetration tester Israel",
]


def run():
    api_key = os.environ.get("SERPAPI_KEY", "")

    if not api_key:
        print(json.dumps({"jobs": [], "error": "SERPAPI_KEY not set"}))
        return

    jobs = []
    seen_ids: set[str] = set()

    for query in SEARCH_QUERIES:
        try:
            params = {
                "engine": "google_jobs",
                "q": query,
                "location": "Israel",
                "hl": "en",
                "chips": "date_posted:today",
                "api_key": api_key,
            }

            results = dict(_serpapi.search(params))

            if "error" in results:
                print(f"[google] SerpAPI error: {results['error']}", file=sys.stderr)
                continue

            for r in results.get("jobs_results", []):
                job_id = r.get("job_id") or str(abs(hash(r.get("title", "") + r.get("company_name", ""))))

                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Check if any apply option links to LinkedIn Easy Apply
                apply_options = r.get("apply_options", [])
                linkedin_apply_url = ""
                external_apply_url = ""

                for opt in apply_options:
                    link = opt.get("link", "")
                    if "linkedin.com" in link:
                        linkedin_apply_url = link
                    elif not external_apply_url:
                        external_apply_url = link

                # Prefer LinkedIn apply link; fall back to first external link
                apply_url = linkedin_apply_url or external_apply_url or ""

                # Extract LinkedIn job ID from the apply URL if present
                li_job_id = ""
                if "linkedin.com/jobs/view/" in apply_url:
                    li_job_id = apply_url.split("/jobs/view/")[1].split("/")[0].split("?")[0]

                jobs.append({
                    "id": f"google_{job_id}",
                    "job_id": li_job_id,          # populated only if LinkedIn apply available
                    "title": r.get("title", ""),
                    "company": r.get("company_name", ""),
                    "url": apply_url or f"https://www.google.com/search?q={r.get('title','')}+{r.get('company_name','')}",
                    "source": "google",
                    "location": r.get("location", "Israel"),
                    "easy_apply": bool(linkedin_apply_url),   # True only if LinkedIn Easy Apply found
                    "description_snippet": (r.get("description") or "")[:200],
                })

        except Exception as e:
            print(f"[google] Query '{query}' error: {e}", file=sys.stderr)

    print(json.dumps({"jobs": jobs, "error": None, "count": len(jobs)}))


if __name__ == "__main__":
    run()
