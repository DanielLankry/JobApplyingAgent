#!/usr/bin/env python3
"""
Apply to a single job given its dict. Returns a result dict.
Called from main.py for each job in new_jobs.json.

Supports:
  - LinkedIn Easy Apply  (multi-step modal form)
  - AllJobs / Drushim    (site-native form)
  - Indeed Apply         (Indeed's own apply flow)
  - Generic form         (best-effort for any other URL)
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from browser_utils import create_browser, human_delay, safe_fill, safe_click, upload_file

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESUME_PATH = os.path.join(DATA_DIR, "resume.pdf")


def _profile() -> dict:
    return {
        "first_name": os.environ.get("APPLICANT_FIRST_NAME", ""),
        "last_name": os.environ.get("APPLICANT_LAST_NAME", ""),
        "email": os.environ.get("APPLICANT_EMAIL", ""),
        "phone": os.environ.get("APPLICANT_PHONE", ""),
        "city": os.environ.get("APPLICANT_CITY", "Israel"),
        "linkedin": os.environ.get("APPLICANT_LINKEDIN_URL", ""),
        "github": os.environ.get("APPLICANT_GITHUB_URL", ""),
        "years_experience": os.environ.get("APPLICANT_YEARS_EXPERIENCE", "3"),
    }


def _cover_letter(job: dict, profile: dict) -> str:
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    snippet = job.get("description_snippet", "")
    skill = ""
    if snippet:
        # Pull first meaningful word cluster from snippet as main skill
        words = snippet.split()
        skill = " ".join(words[:4]) if len(words) >= 4 else snippet[:50]
    if not skill:
        # Derive from job title
        title_lower = title.lower()
        if "cyber" in title_lower or "security" in title_lower:
            skill = "cybersecurity and security engineering"
        elif "machine learning" in title_lower or "ml" in title_lower:
            skill = "machine learning and AI systems"
        elif "data" in title_lower:
            skill = "data engineering and analytics"
        elif "ai" in title_lower or "generative" in title_lower:
            skill = "AI and generative AI systems"
        else:
            skill = "backend engineering and software development"

    return (
        f"Dear {company} Team,\n\n"
        f"I am excited to apply for the {title} position. "
        f"My experience in {skill} aligns well with this opportunity, "
        f"and I am eager to contribute to your team.\n\n"
        f"Best regards,\n"
        f"{profile['first_name']} {profile['last_name']}\n"
        f"{profile['email']} | {profile['phone']}\n"
        f"{profile['linkedin']}"
    )


def _fill_generic_form(page, profile: dict, cover: str):
    """Best-effort form fill for common field patterns."""
    safe_fill(page, "input[name*='first'][type='text']", profile["first_name"])
    safe_fill(page, "input[name*='last'][type='text']", profile["last_name"])
    safe_fill(page, "input[name*='name']:not([name*='company']):not([name*='first']):not([name*='last'])", f"{profile['first_name']} {profile['last_name']}")
    safe_fill(page, "input[type='email']", profile["email"])
    safe_fill(page, "input[type='tel']", profile["phone"])
    safe_fill(page, "input[name*='phone']", profile["phone"])
    safe_fill(page, "input[name*='city']", profile["city"])
    safe_fill(page, "input[name*='linkedin']", profile["linkedin"])
    safe_fill(page, "input[name*='github']", profile["github"])
    safe_fill(page, "input[name*='experience']", profile["years_experience"])

    # Cover letter text areas
    for sel in ["textarea[name*='cover']", "textarea[name*='letter']", "textarea[name*='message']", "textarea"]:
        try:
            el = page.query_selector(sel)
            if el and not el.input_value():
                el.fill(cover)
                break
        except Exception:
            continue

    # Resume upload
    for sel in ["input[type='file'][name*='resume']", "input[type='file'][name*='cv']", "input[type='file']"]:
        if os.path.exists(RESUME_PATH):
            upload_file(page, sel, RESUME_PATH)
            break


def apply_linkedin(page, job: dict, profile: dict) -> dict:
    """Handle LinkedIn Easy Apply multi-step modal."""
    try:
        page.goto(job["url"], timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        human_delay(2, 3)

        # Find and click the Easy Apply button
        for sel in [
            "button.jobs-apply-button",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='easy apply']",
            ".jobs-apply-button",
        ]:
            if safe_click(page, sel, timeout=5000):
                break
        else:
            return {"success": False, "reason": "No Easy Apply button found"}

        human_delay(1, 2)

        # Step through the multi-step modal (up to 10 pages)
        for step in range(10):
            # Fill visible form fields
            _fill_generic_form(page, profile, _cover_letter(job, profile))
            human_delay(1, 2)

            # Check if we've reached the final review/submit page
            submit_btn = page.query_selector("button[aria-label*='Submit application'], button[aria-label*='submit']")
            if submit_btn:
                submit_btn.click()
                human_delay(2, 3)
                return {"success": True, "reason": "Submitted"}

            # Try "Next" or "Review"
            next_clicked = False
            for sel in [
                "button[aria-label='Continue to next step']",
                "button[aria-label*='Next']",
                "button[aria-label*='Review']",
                "footer button.artdeco-button--primary",
            ]:
                if safe_click(page, sel, timeout=3000):
                    next_clicked = True
                    break

            if not next_clicked:
                return {"success": False, "reason": "Could not advance form — manual review needed"}

            human_delay(1, 2)

        return {"success": False, "reason": "Form exceeded max steps"}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def apply_generic(page, job: dict, profile: dict) -> dict:
    """Best-effort application on AllJobs, Drushim, Indeed, or any other site."""
    try:
        page.goto(job["url"], timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        human_delay(2, 3)

        # Look for "Apply" button in multiple languages (Hebrew + English)
        apply_labels = [
            "Apply", "Apply Now", "הגש מועמדות", "שלח קורות חיים",
            "הגשת מועמדות", "Submit Application",
        ]
        clicked = False
        for label in apply_labels:
            for sel in [
                f"button:has-text('{label}')",
                f"a:has-text('{label}')",
                f"input[value='{label}']",
            ]:
                try:
                    el = page.wait_for_selector(sel, timeout=2000)
                    if el:
                        el.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            return {"success": False, "reason": "No apply button found"}

        human_delay(2, 3)
        _fill_generic_form(page, profile, _cover_letter(job, profile))
        human_delay(1, 2)

        # Submit
        for sel in ["button[type='submit']", "input[type='submit']", "button:has-text('Submit')", "button:has-text('שלח')"]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    human_delay(2, 3)
                    return {"success": True, "reason": "Submitted"}
            except Exception:
                continue

        return {"success": False, "reason": "Could not find submit button"}

    except Exception as e:
        return {"success": False, "reason": str(e)}


def apply_to_job(job: dict) -> dict:
    """Entry point: apply to one job and return result dict."""
    profile = _profile()

    p, browser, context = create_browser()
    page = context.new_page()

    try:
        source = job.get("source", "")
        if source == "linkedin":
            # Login to LinkedIn first
            email = os.environ.get("LINKEDIN_EMAIL", "")
            password = os.environ.get("LINKEDIN_PASSWORD", "")
            if email and password:
                page.goto("https://www.linkedin.com/login", timeout=30000)
                safe_fill(page, "#username", email)
                safe_fill(page, "#password", password)
                safe_click(page, "button[type='submit']")
                try:
                    page.wait_for_url("**/feed/**", timeout=20000)
                except Exception:
                    pass
                human_delay(2, 3)
            result = apply_linkedin(page, job, profile)
        else:
            result = apply_generic(page, job, profile)

        result["job"] = job
        return result

    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    # Accept a JSON job dict from stdin or command line for testing
    if len(sys.argv) > 1:
        job = json.loads(sys.argv[1])
    else:
        job = json.loads(sys.stdin.read())
    result = apply_to_job(job)
    print(json.dumps(result, ensure_ascii=False, indent=2))
