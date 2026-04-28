#!/usr/bin/env python3
"""
Search Google for matching jobs via SerpAPI across four sources:
  - Google Jobs (engine=google_jobs)             -> source="google"
  - boards.greenhouse.io site search             -> source="greenhouse"
  - comeet.co site search                        -> source="comeet"
  - jobs.lever.co site search                    -> source="lever"

Uses SerpAPI's HTTPS endpoint directly via the `requests` library — no
SDK dependency (the various `serpapi` and `google-search-results` PyPI
packages have churning APIs and conflicting installs; calling the REST
endpoint sidesteps that).

Outputs one merged JSON payload to stdout. Each job is tagged with its
source so Phase 2 can route apply behavior correctly.
"""

import json
import os
import sys

import requests


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
HTTP_TIMEOUT = 30


# Single broad google_jobs query. The engine itself does role matching.
GOOGLE_JOBS_QUERY = (
    "AI engineer OR backend engineer OR data engineer OR MLOps OR "
    "cybersecurity engineer OR ML engineer Israel"
)

# Site-restricted searches. Each tuple: (source_tag, domain, query).
SITE_SEARCHES = [
    ("greenhouse", "boards.greenhouse.io",
     'site:boards.greenhouse.io ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
    ("comeet", "comeet.co",
     'site:comeet.co ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
    ("lever", "jobs.lever.co",
     'site:jobs.lever.co ("Backend" OR "ML" OR "AI" OR "Data" OR "Security") Israel'),
]


def _serpapi_get(params: dict) -> dict:
    """Hit the SerpAPI REST endpoint and return the JSON response."""
    resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _normalize_google_jobs(results: dict) -> list[dict]:
    out = []
    for r in results.get("jobs_results", []) or []:
        job_id = r.get("job_id") or str(
            abs(hash(r.get("title", "") + r.get("company_name", "")))
        )

        apply_options = r.get("apply_options", []) or []
        linkedin_apply_url = ""
        external_apply_url = ""
        for opt in apply_options:
            link = opt.get("link", "")
            if "linkedin.com" in link:
                linkedin_apply_url = link
            elif not external_apply_url:
                external_apply_url = link
        apply_url = linkedin_apply_url or external_apply_url or ""

        li_job_id = ""
        if "linkedin.com/jobs/view/" in apply_url:
            li_job_id = apply_url.split("/jobs/view/")[1].split("/")[0].split("?")[0]

        out.append({
            "id": f"google_{job_id}",
            "job_id": li_job_id,
            "title": r.get("title", ""),
            "company": r.get("company_name", ""),
            "url": apply_url or f"https://www.google.com/search?q={r.get('title','')}+{r.get('company_name','')}",
            "source": "google",
            "location": r.get("location", "Israel"),
            "easy_apply": bool(linkedin_apply_url),
            "description_snippet": (r.get("description") or "")[:200],
        })
    return out


def _normalize_site_search(results: dict, source_tag: str) -> list[dict]:
    """Convert SerpAPI google-engine organic_results into normalized jobs.
    For ATS sites we don't get clean company/title splits — title is the
    page title, company is parsed best-effort from the URL path."""
    out = []
    for r in results.get("organic_results", []) or []:
        url = r.get("link", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")

        if not url:
            continue

        # Best-effort company extraction from URL slug.
        company = ""
        try:
            path = url.split("//", 1)[-1].split("/", 1)[1]
            parts = [p for p in path.split("/") if p]
            if source_tag == "greenhouse" and parts:
                company = parts[0]
            elif source_tag == "lever" and parts:
                company = parts[0]
            elif source_tag == "comeet":
                if len(parts) >= 2 and parts[0].lower() == "jobs":
                    company = parts[1]
                elif parts:
                    company = parts[0]
        except Exception:
            company = ""

        job_id = str(abs(hash(url)))

        out.append({
            "id": f"{source_tag}_{job_id}",
            "job_id": "",
            "title": title,
            "company": company,
            "url": url,
            "source": source_tag,
            "location": "Israel",
            "easy_apply": False,
            "description_snippet": snippet[:200],
        })
    return out


def _run_google_jobs(api_key: str) -> list[dict]:
    params = {
        "engine": "google_jobs",
        "q": GOOGLE_JOBS_QUERY,
        "location": "Israel",
        "hl": "en",
        "chips": "date_posted:today",
        "api_key": api_key,
    }
    try:
        results = _serpapi_get(params)
        if "error" in results:
            print(f"[google] SerpAPI error: {results['error']}", file=sys.stderr)
            return []
        return _normalize_google_jobs(results)
    except Exception as e:
        print(f"[google] error: {e}", file=sys.stderr)
        return []


def _run_site_search(api_key: str, source_tag: str, query: str) -> list[dict]:
    params = {
        "engine": "google",
        "q": query,
        "hl": "en",
        "tbs": "qdr:w",        # past week — daily filter was empirically too tight for ATS sites
        "num": 20,
        "api_key": api_key,
    }
    try:
        results = _serpapi_get(params)
        if "error" in results:
            print(f"[{source_tag}] SerpAPI error: {results['error']}", file=sys.stderr)
            return []
        return _normalize_site_search(results, source_tag)
    except Exception as e:
        print(f"[{source_tag}] error: {e}", file=sys.stderr)
        return []


def run():
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        print(json.dumps({"jobs": [], "error": "SERPAPI_KEY not set"}))
        return

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    def _add_unique(jobs: list[dict]):
        for j in jobs:
            jid = j.get("id", "")
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            all_jobs.append(j)

    _add_unique(_run_google_jobs(api_key))
    for source_tag, _domain, query in SITE_SEARCHES:
        _add_unique(_run_site_search(api_key, source_tag, query))

    print(json.dumps({"jobs": all_jobs, "error": None, "count": len(all_jobs)}))


if __name__ == "__main__":
    run()
