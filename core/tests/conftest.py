"""Every test is a test script: nothing it runs may reach his apps (CLAUDE.md).

Tools act for real only for his own commands (tools/sandbox.py). A test that
calls a tool directly has no command origin, so the sandbox falls back to dev
mode - set here for every test - and his media session and his Chrome are
stubbed out as well, so a test can never pause his music or open a tab.
A test that checks the real path (keys sent, a launch) stubs the sender itself.
"""
import os

import pytest

# his own config (location, Chrome account, names) is never what a test checks: every
# loader resolves to the committed example (tools/localconfig.py) - before anything
# is imported, since some read their config at import time
os.environ["IRENE_EXAMPLE_CONFIG"] = "1"


@pytest.fixture(autouse=True)
def _research_fixtures_never_expire(monkeypatch):
    """Research expires after a day (tools/research.py EXPIRE_S); the fixtures carry
    fixed, older ids. Tests of the expiry itself set EXPIRE_S back."""
    from tools import research

    monkeypatch.setattr(research, "EXPIRE_S", 10 * 365 * 24 * 3600)


@pytest.fixture(autouse=True)
def _never_his_apps(monkeypatch):
    monkeypatch.setenv("IRENE_DEV", "1")
    from tools import browser, media

    async def no_session():
        return None

    monkeypatch.setattr(media, "his_session", no_session)

    import subprocess
    import types

    def no_launch(*_a, **_k):
        raise AssertionError("a test tried to launch Chrome (his, or hers)")

    # browser.py's own subprocess only: nothing else loses Popen
    monkeypatch.setattr(browser, "subprocess", types.SimpleNamespace(
        Popen=no_launch, DETACHED_PROCESS=subprocess.DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP=subprocess.CREATE_NEW_PROCESS_GROUP))
