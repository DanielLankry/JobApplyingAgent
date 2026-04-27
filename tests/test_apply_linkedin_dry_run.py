"""Verify DRY_RUN env flag short-circuits the LinkedIn easyApply POST."""
import pytest

import apply_linkedin


class _FakeApi:
    """Stand-in for linkedin_api.Linkedin — apply_to_job should never touch
    its session when DRY_RUN=true."""

    class _Boom:
        def __getattr__(self, name):
            raise AssertionError(f"DRY_RUN should not access api.{name}")

    def __init__(self):
        self._LinkedIn__client = self._Boom()

    def get_job(self, *_a, **_kw):
        raise AssertionError("DRY_RUN should not call get_job()")


def test_dry_run_returns_dry_run_status_without_network(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    result = apply_linkedin.apply_to_job(_FakeApi(), job)

    assert result == {"status": "dry_run", "reason": "DRY_RUN mode"}


def test_dry_run_false_does_not_short_circuit(monkeypatch):
    """When DRY_RUN is anything other than 'true', the function proceeds past
    the short-circuit and tries to call api.get_job(). The fake api's
    AssertionError gets caught by apply_to_job's try/except and surfaces as
    a 'failed' result — its reason mentioning get_job confirms the
    short-circuit was NOT taken."""
    monkeypatch.setenv("DRY_RUN", "false")
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    result = apply_linkedin.apply_to_job(_FakeApi(), job)

    assert result["status"] == "failed"
    assert "get_job" in result["reason"]


def test_dry_run_unset_does_not_short_circuit(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    job = {"job_id": "1234567890", "title": "ML Engineer", "company": "Acme"}

    result = apply_linkedin.apply_to_job(_FakeApi(), job)

    assert result["status"] == "failed"
    assert "get_job" in result["reason"]


def test_no_job_id_returns_manual_regardless_of_dry_run(monkeypatch):
    """The 'no job_id' early-return should fire before the DRY_RUN check —
    a job with no ID can't be applied to in either mode."""
    monkeypatch.setenv("DRY_RUN", "true")
    job = {"job_id": "", "title": "ML Engineer", "company": "Acme"}

    result = apply_linkedin.apply_to_job(_FakeApi(), job)

    assert result["status"] == "manual"
    assert "No LinkedIn job ID" in result["reason"]
