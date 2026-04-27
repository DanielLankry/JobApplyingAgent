"""Test fixtures for the job-agent test suite."""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _stub_optional_imports():
    """Register lightweight stubs for third-party packages that scripts import
    at module-load time. Tests don't exercise these libraries — we just need
    the imports to succeed so the script modules can be loaded."""
    for name in ("linkedin_api", "serpapi", "gspread"):
        if name in sys.modules:
            continue
        mod = types.ModuleType(name)
        if name == "linkedin_api":
            class _Linkedin:
                def __init__(self, *_a, **_kw):
                    raise RuntimeError("linkedin_api stub — real lib not installed")
            mod.Linkedin = _Linkedin
        elif name == "serpapi":
            def _search(_params):
                raise RuntimeError("serpapi stub — real lib not installed")
            mod.search = _search
        elif name == "gspread":
            def _authorize(_creds):
                raise RuntimeError("gspread stub — real lib not installed")
            mod.authorize = _authorize
        sys.modules[name] = mod

    # google.* family — needed by dedup_manager and (formerly) resume_manager
    for full_name in (
        "google",
        "google.oauth2",
        "google.oauth2.service_account",
    ):
        if full_name in sys.modules:
            continue
        sys.modules[full_name] = types.ModuleType(full_name)

    sa_mod = sys.modules["google.oauth2.service_account"]
    if not hasattr(sa_mod, "Credentials"):
        class _Credentials:
            @classmethod
            def from_service_account_info(cls, *_a, **_kw):
                raise RuntimeError("Credentials stub — real google-auth not installed")

        sa_mod.Credentials = _Credentials


_stub_optional_imports()


def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)
