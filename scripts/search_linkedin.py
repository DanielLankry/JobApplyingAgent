#!/usr/bin/env python3
"""
Search LinkedIn for Easy Apply jobs using the linkedin-api library.
No browser required — pure HTTP via LinkedIn's internal API.
Outputs JSON to stdout.
"""

import json
import os
import sys
import time

from apply_linkedin import _get_api

SEARCH_KEYWORDS = [
    "Backend Engineer",
    "Backend Developer",
    "Data Engineer",
    "Machine Learning Engineer",
    "AI Engineer",
    "Generative AI Engineer",
    "LLM Engineer",
    "MLOps Engineer",
    "Cybersecurity Engineer",
    "Security Engineer",
    "Penetration Tester",
    "Data Scientist",
]

MAX_PER_KEYWORD = 10


def run():
    # Reuse apply_linkedin's auth helper — it prefers LINKEDIN_LI_AT cookie auth
    # (avoiding CHALLENGE on new IPs) and falls back to email/password.
    api = _get_api()
    if api is None:
        print(json.dumps({"jobs": [], "error": "LinkedIn auth failed — set LINKEDIN_LI_AT cookie or LINKEDIN_EMAIL/PASSWORD"}))
        return

    # Cap session redirects so a rate-limited / dead cookie fails in seconds
    # instead of looping 30 times per keyword (which can blow the parent
    # subprocess timeout when LinkedIn anti-bot kicks in).
    api.client.session.max_redirects = 3

    jobs = []
    seen_ids: set[str] = set()
    consecutive_redirect_failures = 0

    for keyword in SEARCH_KEYWORDS:
        try:
            results = api.search_jobs(
                keywords=keyword,
                location_name="Israel",
                listed_at=86400,       # last 24 hours
                easy_apply=True,       # Easy Apply only
                limit=MAX_PER_KEYWORD,
            )
            consecutive_redirect_failures = 0  # reset on success

            for r in results:
                # URN looks like "urn:li:fs_normalized_jobPosting:1234567890"
                urn = (
                    r.get("trackingUrn")
                    or r.get("jobPostingUrn")
                    or r.get("entityUrn")
                    or ""
                )
                job_id = urn.split(":")[-1]

                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = (
                    r.get("title")
                    or r.get("jobTitle")
                    or ""
                )
                company = (
                    r.get("companyName")
                    or (r.get("primaryDescription") or {}).get("text", "")
                    or ""
                )
                location = (
                    r.get("formattedLocation")
                    or (r.get("secondaryDescription") or {}).get("text", "")
                    or "Israel"
                )

                jobs.append({
                    "id": f"linkedin_{job_id}",
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "source": "linkedin",
                    "location": location,
                    "easy_apply": True,
                    "description_snippet": "",
                })

            time.sleep(1)  # avoid rate limiting between keyword searches

        except Exception as e:
            print(f"[linkedin] '{keyword}' search error: {e}", file=sys.stderr)
            # If the session is being killed by LinkedIn anti-bot (manifests as
            # TooManyRedirects on every call), bail early — retrying just burns
            # the subprocess timeout. Cookie likely needs to cool off or refresh.
            if "redirect" in str(e).lower():
                consecutive_redirect_failures += 1
                if consecutive_redirect_failures >= 2:
                    print("[linkedin] aborting search — session rate-limited (li_at may need refresh)",
                          file=sys.stderr)
                    break

    print(json.dumps({"jobs": jobs, "error": None, "count": len(jobs)}))


if __name__ == "__main__":
    run()
