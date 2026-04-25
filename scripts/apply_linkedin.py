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
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    if not email or not password:
        return None
    try:
        return Linkedin(email, password, authenticate=True)
    except Exception as e:
        print(f"[apply] LinkedIn login failed: {e}", file=sys.stderr)
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
    Returns {"status": "applied"|"manual"|"failed", "reason": str}
    """
    job_id = job.get("job_id", "")
    if not job_id:
        return {"status": "manual", "reason": "No LinkedIn job ID — apply via URL"}

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

        # Use linkedin-api's internal authenticated session to submit
        session = api._LinkedIn__client.session
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
