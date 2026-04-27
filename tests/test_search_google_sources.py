"""Verify search_google produces source-tagged jobs across multiple SerpAPI
calls (Google Jobs + site-restricted Google searches for ATS hosts).

These tests mock `requests.get` since search_google.py now hits the SerpAPI
HTTPS endpoint directly rather than going through an SDK."""
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


class _FakeResponse:
    def __init__(self, payload, *, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


def _make_fake_get(responder):
    """Build a fake `requests.get` that records params and routes via responder.
    `responder(params)` may return a dict (success) or raise (network error)."""
    captured = []

    def _fake_get(url, params=None, timeout=None):
        captured.append(params)
        return _FakeResponse(responder(params))

    return _fake_get, captured


def test_run_emits_jobs_tagged_with_each_source(monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    fake_get, captured = _make_fake_get(_route_response)
    monkeypatch.setattr(search_google.requests, "get", fake_get)

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

    assert len(captured) == 4
    assert all(p.get("api_key") == "fake-key" for p in captured)


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

    def _responder(params):
        if "site:comeet.co" in params.get("q", ""):
            raise RuntimeError("simulated SerpAPI 500")
        return _route_response(params)

    fake_get, _ = _make_fake_get(_responder)
    monkeypatch.setattr(search_google.requests, "get", fake_get)
    search_google.run()

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    sources = sorted({job["source"] for job in payload["jobs"]})
    assert "comeet" not in sources
    assert {"google", "greenhouse", "lever"}.issubset(set(sources))


def test_serpapi_returns_error_field_in_payload(monkeypatch, capsys):
    """When SerpAPI itself returns an {"error": ...} payload, that source
    yields zero jobs but doesn't crash the run."""
    monkeypatch.setenv("SERPAPI_KEY", "fake-key")

    def _responder(params):
        if params.get("engine") == "google_jobs":
            return {"error": "Quota exceeded"}
        return _route_response(params)

    fake_get, _ = _make_fake_get(_responder)
    monkeypatch.setattr(search_google.requests, "get", fake_get)
    search_google.run()

    payload = json.loads(capsys.readouterr().out.strip())
    sources = {job["source"] for job in payload["jobs"]}
    assert "google" not in sources
    assert {"greenhouse", "comeet", "lever"}.issubset(sources)
