#!/usr/bin/env python3
"""
Search Indeed Israel (il.indeed.com) for matching jobs.
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
    "Machine Learning Engineer",
    "AI Engineer",
    "Generative AI",
    "MLOps",
    "Cybersecurity Engineer",
    "Security Engineer",
    "Penetration Tester",
    "Data Scientist",
    "AI Deployment Engineer",
]

MAX_JOBS_PER_KEYWORD = 8


def login(page, email: str, password: str) -> bool:
    try:
        page.goto("https://secure.indeed.com/auth?hl=en_IL", timeout=30000)
        human_delay(1, 2)

        for sel in ["input[name='__email']", "input[type='email']", "#email-input"]:
            try:
                page.fill(sel, email, timeout=3000)
                break
            except Exception:
                continue

        for sel in ["button[type='submit']", ".icl-Button"]:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        human_delay(1, 2)

        for sel in ["input[name='__password']", "input[type='password']"]:
            try:
                page.fill(sel, password, timeout=5000)
                break
            except Exception:
                continue

        for sel in ["button[type='submit']", ".icl-Button"]:
            try:
                page.click(sel, timeout=3000)
                break
            except Exception:
                continue

        human_delay(3, 5)
        return "auth" not in page.url.lower()
    except Exception as e:
        print(f"[indeed] Login failed: {e}", file=sys.stderr)
        return False


def search_keyword(page, keyword: str) -> list[dict]:
    jobs = []
    try:
        encoded = keyword.replace(" ", "+")
        # fromage=1 → last 1 day; l=Israel → location
        url = f"https://il.indeed.com/jobs?q={encoded}&l=Israel&fromage=1&sort=date"
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_delay(2, 3)

        cards = page.query_selector_all(
            ".job_seen_beacon, .resultContent, [class*='jobCard'], [data-jk]"
        )

        for card in cards[:MAX_JOBS_PER_KEYWORD]:
            try:
                title_el = card.query_selector(
                    "h2.jobTitle, .jobTitle a, [class*='jobTitle'] a, a[data-jk]"
                )
                company_el = card.query_selector(
                    "[data-testid='company-name'], .companyName, span[class*='company']"
                )
                link_el = card.query_selector("a[data-jk], h2 a, a[href*='/pagead/'], a[href*='/rc/clk']")

                if not title_el:
                    continue

                jk = ""
                href = ""
                if link_el:
                    jk = link_el.get_attribute("data-jk") or ""
                    href = link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = "https://il.indeed.com" + href

                canonical_url = f"https://il.indeed.com/viewjob?jk={jk}" if jk else href

                jobs.append({
                    "id": f"indeed_{jk}" if jk else f"indeed_{hash(canonical_url)}",
                    "title": title_el.inner_text().strip(),
                    "company": company_el.inner_text().strip() if company_el else "",
                    "url": canonical_url,
                    "source": "indeed",
                    "location": "Israel",
                    "description_snippet": "",
                    "easy_apply": True,
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[indeed] Search '{keyword}' error: {e}", file=sys.stderr)

    return jobs


def run():
    email = os.environ.get("INDEED_EMAIL", "")
    password = os.environ.get("INDEED_PASSWORD", "")

    if not email or not password:
        print(json.dumps({"jobs": [], "error": "Indeed credentials not set"}))
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
