#!/usr/bin/env python3
"""
Search LinkedIn for matching jobs using Easy Apply filter.
Outputs JSON array of job dicts to stdout.
"""

import json
import os
import sys
import time

# Scripts directory on path for browser_utils import
sys.path.insert(0, os.path.dirname(__file__))
from browser_utils import create_browser, human_delay

# Job keywords to search — each becomes its own LinkedIn search query
SEARCH_KEYWORDS = [
    "Backend Engineer Israel",
    "Backend Developer Israel",
    "Data Engineer Israel",
    "Machine Learning Engineer Israel",
    "AI Engineer Israel",
    "Generative AI Engineer Israel",
    "LLM Engineer Israel",
    "MLOps Engineer Israel",
    "Cybersecurity Engineer Israel",
    "Security Engineer Israel",
    "Penetration Tester Israel",
    "AppSec Engineer Israel",
    "Data Scientist Israel",
    "AI Deployment Engineer Israel",
]

MAX_JOBS_PER_KEYWORD = 10


def login(page, email: str, password: str) -> bool:
    try:
        page.goto("https://www.linkedin.com/login", timeout=30000)
        page.fill("#username", email)
        page.fill("#password", password)
        page.click("button[type='submit']")
        page.wait_for_url("**/feed/**", timeout=20000)
        return True
    except Exception as e:
        print(f"[linkedin] Login failed: {e}", file=sys.stderr)
        return False


def search_keyword(page, keyword: str) -> list[dict]:
    jobs = []
    try:
        encoded = keyword.replace(" ", "%20")
        # f_AL=true  → Easy Apply only
        # f_TPR=r86400 → last 24 hours
        url = (
            f"https://www.linkedin.com/jobs/search/?keywords={encoded}"
            f"&location=Israel&f_AL=true&f_TPR=r86400&start=0"
        )
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        human_delay(2, 4)

        # Scroll to load more results
        for _ in range(3):
            page.keyboard.press("End")
            human_delay(1, 2)

        job_cards = page.query_selector_all("li.jobs-search-results__list-item")
        for card in job_cards[:MAX_JOBS_PER_KEYWORD]:
            try:
                title_el = card.query_selector(".job-card-list__title, .base-search-card__title")
                company_el = card.query_selector(
                    ".job-card-container__company-name, .base-search-card__subtitle"
                )
                link_el = card.query_selector("a.job-card-list__title, a.base-card__full-link")
                location_el = card.query_selector(
                    ".job-card-container__metadata-item, .job-search-card__location"
                )

                if not title_el or not link_el:
                    continue

                href = link_el.get_attribute("href") or ""
                # Normalize to canonical job URL
                if "/jobs/view/" in href:
                    job_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                else:
                    url = href.split("?")[0]
                    job_id = url.rstrip("/").split("/")[-1]

                jobs.append({
                    "id": f"linkedin_{job_id}",
                    "title": title_el.inner_text().strip(),
                    "company": company_el.inner_text().strip() if company_el else "",
                    "url": url,
                    "source": "linkedin",
                    "location": location_el.inner_text().strip() if location_el else "Israel",
                    "description_snippet": "",
                    "easy_apply": True,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[linkedin] Search '{keyword}' error: {e}", file=sys.stderr)

    return jobs


def run():
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    if not email or not password:
        print(json.dumps({"jobs": [], "error": "LinkedIn credentials not set"}))
        return

    p, browser, context = create_browser()
    page = context.new_page()

    try:
        if not login(page, email, password):
            print(json.dumps({"jobs": [], "error": "LinkedIn login failed"}))
            return

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        for keyword in SEARCH_KEYWORDS:
            jobs = search_keyword(page, keyword)
            for job in jobs:
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            human_delay(2, 4)

        print(json.dumps({"jobs": all_jobs, "error": None, "count": len(all_jobs)}))

    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    run()
