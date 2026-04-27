"""Verify search_google produces source-tagged jobs across multiple SerpAPI
calls (Google Jobs + site-restricted Google searches for ATS hosts)."""
import json

import search_google


def _fake_google_jobs_response():
    return {
        "jobs_results": [
            {
                "job_id": "gj-1",
                "title": "Backend Engineer",
                "company_name": "Acme",
                "location": "Tel Aviv, Israel",
                "description": "Build APIs at Acme.",
                "apply_options": [
                    {"link": "https://www.linkedin.com/jobs/view/9876543210/"}
                ],
            }
        ]
    }


def _fake_google_search_response(domain: str, host_label: str):
    """Minimal SerpAPI google-engine response for site:<domain> queries."""
    return {
        "organic_results": [
            {
                "title": f"Senior ML Engineer — {host_label}",
                "link": f"https://{domain}/example-co/jobs/senior-ml-engineer",
                "snippet": f"Apply for the Senior ML Engineer role hosted on {host_label}.",
            }
        ]
    }


def _route_response(params):
    """Return a fake SerpAPI dict based on the engine + q in params."""
    engine = params.get("engine")
    q = params.get("q", "")
    if engine == "google_jobs":
        return _fake_google_jobs_response()
    if "site:boards.greenhouse.io" in q:
        return _fake_google_search_response("boards.greenhouse.io", "Greenhouse")
    if "site:comeet.co" in q:
        return _fake_google_search_response("comeet.co", "Comeet")
    if "site:jobs.lever.co" in q:
        return _fake_google_search_response("jobs.lever.co", "Lever")
    return {}


def test_run_emits_jobs_tagged_with_each_source(monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    captured_calls = []

    def _fake_search(params):
        captured_calls.append(params)
        return _route_response(params)

    monkeypatch.setattr(search_google._serpapi, "search", _fake_search)

    search_google.run()

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    sources = sorted({job["source"] for job in payload["jobs"]})
    assert sources == ["comeet", "google", "greenhouse", "lever"]

    for job in payload["jobs"]:
        assert job["url"].startswith("http")
        assert job["title"]
        assert job["source"] in {"google", "comeet", "greenhouse", "lever"}
        assert job["id"].startswith(f"{job['source']}_")

    assert len(captured_calls) == 4


def test_missing_api_key_returns_error(monkeypatch, capsys):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    search_google.run()
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["jobs"] == []
    assert "SERPAPI_KEY" in payload["error"]


def test_one_source_failure_does_not_kill_others(monkeypatch, capsys):
    """If a single SerpAPI call raises, others still run and we still emit
    jobs from the surviving sources."""
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    def _fake_search(params):
        if "site:comeet.co" in params.get("q", ""):
            raise RuntimeError("simulated SerpAPI 500")
        return _route_response(params)

    monkeypatch.setattr(search_google._serpapi, "search", _fake_search)
    search_google.run()

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    sources = sorted({job["source"] for job in payload["jobs"]})
    assert "comeet" not in sources
    assert {"google", "greenhouse", "lever"}.issubset(set(sources))
