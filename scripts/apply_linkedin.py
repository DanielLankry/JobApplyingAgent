#!/usr/bin/env python3
"""
Apply to LinkedIn Easy Apply jobs using linkedin-api's authenticated session.
No browser required — pure HTTP calls using LinkedIn's internal API.
"""

import json
import os
import sys

from linkedin_api import Linkedin


def _profile() -> dict:
    return {
        "first_name": os.environ.get("APPLICANT_FIRST_NAME", ""),
        "last_name": os.environ.get("APPLICANT_LAST_NAME", ""),
        "email": os.environ.get("APPLICANT_EMAIL", ""),
        "phone": os.environ.get("APPLICANT_PHONE", ""),
        "linkedin": os.environ.get("APPLICANT_LINKEDIN_URL", ""),
        "years_experience": os.environ.get("APPLICANT_YEARS_EXPERIENCE", "3"),
    }


def _get_api() -> Linkedin | None:
    """
    Authenticate to LinkedIn via the unofficial voyager API.

    Strategy: prefer cookie-based auth when `LINKEDIN_LI_AT` is set —
    LinkedIn aggressively triggers a CHALLENGE on email/password login from
    a new IP, and a working `li_at` cookie skips that flow entirely. Fall
    back to email/password only if no cookie is present.

    To get the cookie:
      1. Log into linkedin.com manually in Chrome
      2. DevTools -> Application -> Cookies -> https://www.linkedin.com
      3. Copy the value of `li_at` (a long string starting with "AQE...")
      4. Set LINKEDIN_LI_AT=<that value> in .env
    """
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    li_at = os.environ.get("LINKEDIN_LI_AT", "").strip()

    if li_at:
        try:
            import requests
            from requests.cookies import RequestsCookieJar

            # linkedin-api's `_set_session_cookies` reads JSESSIONID off the jar
            # to populate the csrf-token header. li_at alone isn't enough — fetch
            # a fresh JSESSIONID from /uas/authenticate (LinkedIn issues one on
            # any anonymous GET) and combine with the user's li_at.
            seed = requests.get(
                "https://www.linkedin.com/uas/authenticate",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            jsessionid = seed.cookies.get("JSESSIONID", "").strip('"')
            if not jsessionid:
                raise RuntimeError("LinkedIn did not issue a JSESSIONID cookie")

            jar = RequestsCookieJar()
            jar.set("li_at", li_at, domain=".linkedin.com")
            jar.set("JSESSIONID", f'"{jsessionid}"', domain=".linkedin.com")

            # IMPORTANT: cookies are only attached when authenticate=True AND
            # cookies is truthy (see linkedin_api/linkedin.py:76-82). Passing
            # authenticate=False skips the cookie-set branch entirely, which is
            # why every voyager call returned "CSRF check failed" before.
            return Linkedin(email or "noop@example.com",
                            password or "noop",
                            cookies=jar,
                            authenticate=True)
        except Exception as e:
            print(f"[apply] cookie-based LinkedIn auth failed: {e}", file=sys.stderr)
            # fall through to password attempt if creds are also set

    if not email or not password:
        return None
    try:
        return Linkedin(email, password, authenticate=True)
    except Exception as e:
        print(f"[apply] LinkedIn password login failed (CHALLENGE expected from new IP — set LINKEDIN_LI_AT cookie instead): {e}",
              file=sys.stderr)
        return None


def _cover_letter(job: dict, profile: dict) -> str:
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    snippet = job.get("description_snippet", "")
    domain = snippet[:80] if snippet else title
    return (
        f"Dear {company} Team,\n\n"
        f"I am excited to apply for the {title} position. "
        f"My background in {domain} makes this a strong fit.\n\n"
        f"Best regards,\n"
        f"{profile['first_name']} {profile['last_name']}\n"
        f"{profile['email']} | {profile['phone']}"
    )


def apply_to_job(api: Linkedin, job: dict) -> dict:
    """
    Attempt Easy Apply via LinkedIn's internal voyager API.
    Returns {"status": "applied"|"manual"|"failed"|"dry_run", "reason": str}
    """
    job_id = job.get("job_id", "")
    if not job_id:
        return {"status": "manual", "reason": "No LinkedIn job ID — apply via URL"}

    # DRY_RUN: skip the actual easyApply POST. The "dry_run" status tells
    # run_agent.py NOT to mark the job as applied locally or write it to
    # the Sheet (Section 11 of the spec — jobs stay re-applyable when the
    # flag flips to false at the end of the 14-day shadow period).
    if os.environ.get("DRY_RUN", "").strip().lower() == "true":
        return {"status": "dry_run", "reason": "DRY_RUN mode"}

    profile = _profile()

    try:
        # Confirm job still has Easy Apply available
        job_details = api.get_job(job_id)
        apply_method = job_details.get("applyMethod", {})

        # LinkedIn Easy Apply keys contain "onsite" or "onsiteApply"
        is_easy_apply = any(
            "onsite" in k.lower() for k in apply_method.keys()
        )
        if not is_easy_apply:
            return {"status": "manual", "reason": "Easy Apply no longer available — external ATS"}

        # Use linkedin-api's internal authenticated session to submit.
        # Note: the attribute was name-mangled (`_LinkedIn__client`) in older
        # versions of linkedin-api; newer versions expose it as plain `client`.
        client = getattr(api, "client", None) or getattr(api, "_LinkedIn__client")
        session = client.session
        csrf = session.cookies.get("JSESSIONID", "ajax:0").strip('"')

        headers = {
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "content-type": "application/json",
            "csrf-token": csrf,
            "x-li-lang": "en_US",
            "x-restli-protocol-version": "2.0.0",
        }

        payload = {
            "jobPostingId": f"urn:li:fs_normalized_jobPosting:{job_id}",
            "contactInfo": {
                "com.linkedin.voyager.jobs.JobSeekerContactInfo": {
                    "firstName": profile["first_name"],
                    "lastName": profile["last_name"],
                    "emailAddress": profile["email"],
                    "phone": {
                        "com.linkedin.voyager.common.PhoneNumber": {
                            "number": profile["phone"],
                            "extension": "",
                        }
                    },
                }
            },
            "coverletter": _cover_letter(job, profile),
            "easyApplyJobApplicationDesiredState": "SUBMITTED",
        }

        resp = session.post(
            "https://www.linkedin.com/voyager/api/jobs/easyApply",
            headers=headers,
            json=payload,
            timeout=20,
        )

        if resp.status_code in (200, 201):
            return {"status": "applied", "reason": "Easy Apply submitted"}
        elif resp.status_code == 422:
            # Complex form with custom questions — needs manual review
            return {"status": "manual", "reason": "Complex form — apply manually via link"}
        else:
            return {"status": "failed", "reason": f"API returned {resp.status_code}"}

    except Exception as e:
        return {"status": "failed", "reason": str(e)}


if __name__ == "__main__":
    # Test: pass a job JSON as argument
    if len(sys.argv) > 1:
        job = json.loads(sys.argv[1])
        api = _get_api()
        if api:
            print(json.dumps(apply_to_job(api, job)))
        else:
            print(json.dumps({"status": "failed", "reason": "Could not authenticate"}))
