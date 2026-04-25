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

from linkedin_api import Linkedin

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
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    if not email or not password:
        print(json.dumps({"jobs": [], "error": "LINKEDIN_EMAIL or LINKEDIN_PASSWORD not set"}))
        return

    try:
        api = Linkedin(email, password, authenticate=True)
    except Exception as e:
        print(json.dumps({"jobs": [], "error": f"LinkedIn login failed: {e}"}))
        return

    jobs = []
    seen_ids: set[str] = set()

    for keyword in SEARCH_KEYWORDS:
        try:
            results = api.search_jobs(
                keywords=keyword,
                location_name="Israel",
                listed_at=86400,       # last 24 hours
                easy_apply=True,       # Easy Apply only
                limit=MAX_PER_KEYWORD,
            )

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

    print(json.dumps({"jobs": jobs, "error": None, "count": len(jobs)}))


if __name__ == "__main__":
    run()
