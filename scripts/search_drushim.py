#!/usr/bin/env python3
"""
Search Drushim.co.il for matching jobs.
Outputs JSON to stdout.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from browser_utils import create_browser, human_delay

SEARCH_KEYWORDS = [
    "Backend Engineer",
    "Data Engineer",
    "Machine Learning",
    "AI Engineer",
    "Generative AI",
    "MLOps",
    "Cybersecurity",
    "Security Engineer",
    "Data Scientist",
    "מהנדס תוכנה",
    "אבטחת מידע",
    "מדען נתונים",
]

MAX_JOBS_PER_KEYWORD = 8


def login(page, email: str, password: str) -> bool:
    try:
        page.goto("https://www.drushim.co.il/user/login/", timeout=30000)
        human_delay(1, 2)

        for sel in ["input[name='email']", "#email", "input[type='email']"]:
            try:
                page.fill(sel, email, timeout=3000)
                break
            except Exception:
                continue

        for sel in ["input[name='password']", "#password", "input[type='password']"]:
            try:
                page.fill(sel, password, timeout=3000)
                break
            except Exception:
                continue

        for sel in ["button[type='submit']", "input[type='submit']", ".submit-btn"]:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        human_delay(2, 3)
        return "login" not in page.url.lower()
    except Exception as e:
        print(f"[drushim] Login failed: {e}", file=sys.stderr)
        return False


def search_keyword(page, keyword: str) -> list[dict]:
    jobs = []
    try:
        encoded = keyword.replace(" ", "%20")
        url = f"https://www.drushim.co.il/search/q/{encoded}/"
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_delay(2, 3)

        # Drushim job cards
        cards = page.query_selector_all(
            ".job-item, .job-card, article, [class*='job'], li[class*='Job']"
        )

        for card in cards[:MAX_JOBS_PER_KEYWORD]:
            try:
                title_el = card.query_selector(
                    "h2, h3, .job-title, [class*='title'], a[href*='/job/']"
                )
                company_el = card.query_selector(
                    ".company, [class*='company'], [class*='employer']"
                )
                link_el = card.query_selector("a[href*='/job/'], a[href*='vacancy']")

                if not title_el:
                    continue

                href = ""
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = "https://www.drushim.co.il" + href

                job_id = href.rstrip("/").split("/")[-1] if href else str(hash(title_el.inner_text()))

                jobs.append({
                    "id": f"drushim_{job_id}",
                    "title": title_el.inner_text().strip(),
                    "company": company_el.inner_text().strip() if company_el else "",
                    "url": href,
                    "source": "drushim",
                    "location": "Israel",
                    "description_snippet": "",
                    "easy_apply": True,
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[drushim] Search '{keyword}' error: {e}", file=sys.stderr)

    return jobs


def run():
    email = os.environ.get("DRUSHIM_EMAIL", "")
    password = os.environ.get("DRUSHIM_PASSWORD", "")

    if not email or not password:
        print(json.dumps({"jobs": [], "error": "Drushim credentials not set"}))
        return

    p, browser, context = create_browser()
    page = context.new_page()

    try:
        login(page, email, password)

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
