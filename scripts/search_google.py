#!/usr/bin/env python3
"""
Search Google Jobs (google.com/search?ibp=htl;jobs) for matching roles in Israel.
Extracts job cards from Google's job panel and outputs JSON to stdout.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from browser_utils import create_browser, human_delay

# Google job search queries — each produces a Google Jobs panel
SEARCH_QUERIES = [
    "backend engineer jobs Israel 2025",
    "data engineer jobs Israel 2025",
    "machine learning engineer jobs Israel",
    "AI engineer jobs Israel",
    "generative AI jobs Israel",
    "MLOps engineer jobs Israel",
    "cybersecurity engineer jobs Israel",
    "penetration tester jobs Israel",
    "AppSec engineer jobs Israel",
    "data scientist jobs Israel",
    "LLM engineer jobs Israel",
]

MAX_JOBS_PER_QUERY = 6


def search_google_jobs(page, query: str) -> list[dict]:
    jobs = []
    try:
        encoded = query.replace(" ", "+")
        url = f"https://www.google.com/search?q={encoded}&ibp=htl;jobs"
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_delay(2, 3)

        # Click into Google Jobs panel if it exists
        try:
            panel = page.wait_for_selector("[data-hveid] .tNxQIb, .KLsYvd", timeout=5000)
        except Exception:
            panel = None

        # Try to get job cards from the panel
        cards = page.query_selector_all(
            "li.iFjolb, .PwjeAc, [class*='job-result'], .gws-plugins-horizon-jobs__li-ed"
        )

        for card in cards[:MAX_JOBS_PER_QUERY]:
            try:
                title_el = card.query_selector(
                    ".BjJfJf, .sH3zEc, [class*='title'], h3"
                )
                company_el = card.query_selector(
                    ".vNEEBe, .nJlQNd, [class*='company']"
                )
                link_el = card.query_selector("a[href]")

                if not title_el:
                    continue

                href = ""
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    if href.startswith("/"):
                        href = "https://www.google.com" + href

                title = title_el.inner_text().strip()
                company = company_el.inner_text().strip() if company_el else ""

                jobs.append({
                    "id": f"google_{hash(title + company)}",
                    "title": title,
                    "company": company,
                    "url": href,
                    "source": "google",
                    "location": "Israel",
                    "description_snippet": "",
                    "easy_apply": False,  # Google links to external sites
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[google] Search '{query}' error: {e}", file=sys.stderr)

    return jobs


def run():
    p, browser, context = create_browser()
    page = context.new_page()

    try:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        for query in SEARCH_QUERIES:
            jobs = search_google_jobs(page, query)
            for job in jobs:
                if job["id"] not in seen_ids and job["url"]:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            human_delay(3, 5)  # Respect Google rate limits

        print(json.dumps({"jobs": all_jobs, "error": None, "count": len(all_jobs)}))

    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    run()
