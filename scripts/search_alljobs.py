#!/usr/bin/env python3
"""
Search AllJobs.co.il for matching jobs.
Outputs JSON to stdout.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from browser_utils import create_browser, human_delay

# Hebrew + English keywords for AllJobs
SEARCH_KEYWORDS = [
    "Backend Engineer",
    "Data Engineer",
    "Machine Learning",
    "AI Engineer",
    "Generative AI",
    "MLOps",
    "Cybersecurity",
    "Security Engineer",
    "Penetration Tester",
    "Data Scientist",
    "מהנדס תוכנה",     # Software Engineer (Hebrew)
    "מדען נתונים",      # Data Scientist (Hebrew)
    "אבטחת מידע",       # Information Security (Hebrew)
]

MAX_JOBS_PER_KEYWORD = 8


def login(page, email: str, password: str) -> bool:
    try:
        page.goto("https://www.alljobs.co.il/login", timeout=30000)
        human_delay(1, 2)

        # Try common login field selectors
        for sel in ["#email", "input[name='email']", "input[type='email']"]:
            try:
                page.fill(sel, email, timeout=3000)
                break
            except Exception:
                continue

        for sel in ["#password", "input[name='password']", "input[type='password']"]:
            try:
                page.fill(sel, password, timeout=3000)
                break
            except Exception:
                continue

        for sel in ["button[type='submit']", "input[type='submit']", ".login-btn"]:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        human_delay(2, 3)
        return "login" not in page.url.lower()
    except Exception as e:
        print(f"[alljobs] Login failed: {e}", file=sys.stderr)
        return False


def search_keyword(page, keyword: str) -> list[dict]:
    jobs = []
    try:
        encoded = keyword.replace(" ", "+")
        url = f"https://www.alljobs.co.il/SearchResults.aspx?q={encoded}&sortby=1"
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_delay(2, 3)

        # AllJobs job cards — selector may vary; try multiple patterns
        cards = page.query_selector_all(
            ".single-job, .job-item, article.job, [class*='job-card'], [class*='JobItem']"
        )

        for card in cards[:MAX_JOBS_PER_KEYWORD]:
            try:
                title_el = card.query_selector(
                    "h2, h3, .job-title, [class*='title'], a[href*='jobinfo']"
                )
                company_el = card.query_selector(
                    ".company-name, [class*='company'], [class*='employer']"
                )
                link_el = card.query_selector("a[href*='jobinfo'], a[href*='job-']")

                if not title_el:
                    continue

                href = ""
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    if not href.startswith("http"):
                        href = "https://www.alljobs.co.il" + href

                job_id = href.split("jobid=")[-1].split("&")[0] if "jobid=" in href else href.split("/")[-1].split("?")[0]

                jobs.append({
                    "id": f"alljobs_{job_id}" if job_id else f"alljobs_{hash(href)}",
                    "title": title_el.inner_text().strip(),
                    "company": company_el.inner_text().strip() if company_el else "",
                    "url": href,
                    "source": "alljobs",
                    "location": "Israel",
                    "description_snippet": "",
                    "easy_apply": True,
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[alljobs] Search '{keyword}' error: {e}", file=sys.stderr)

    return jobs


def run():
    email = os.environ.get("ALLJOBS_EMAIL", "")
    password = os.environ.get("ALLJOBS_PASSWORD", "")

    if not email or not password:
        print(json.dumps({"jobs": [], "error": "AllJobs credentials not set"}))
        return

    p, browser, context = create_browser()
    page = context.new_page()

    try:
        login(page, email, password)  # non-fatal if login fails; some results visible anyway

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        for keyword in SEARCH_KEYWORDS:
            jobs = search_keyword(page, keyword)
            for job in jobs:
                if job["id"] not in seen_ids and job["url"]:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            human_delay(2, 3)

        print(json.dumps({"jobs": all_jobs, "error": None, "count": len(all_jobs)}))

    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    run()
