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


class BagEmbedder:
    """Stands in for her embedding model in tests (no 130 MB model, no threads
    importing transformers): a hashed bag of words, normalised."""

    ready = True

    def load(self):
        pass

    def encode(self, texts, query=False):
        import hashlib

        import numpy as np

        from irene import recall

        out = np.zeros((len(texts), 384), np.float32)
        for row, text in enumerate(texts):
            for w in recall.words(text):
                out[row, int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


@pytest.fixture(autouse=True)
def _memory_never_his(monkeypatch, tmp_path):
    """Her long-term memory in a test is a fresh one in a temp folder: a test never
    reads or writes his (or the dev run's) memories."""
    from irene import recall

    embedder = BagEmbedder()
    store = recall.Store(tmp_path / "memory" / "memory.sqlite", embedder)
    monkeypatch.setattr(recall, "EMBEDDER", embedder)
    monkeypatch.setattr(recall, "HIS", store)
    monkeypatch.setattr(recall, "DEV", store)
    yield
    recall.flush()
    store.close()


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


@pytest.fixture(autouse=True)
def _lectures_never_his(monkeypatch, tmp_path):
    """His captured lectures and their notes stay out of every test: the lecture store
    (and the notes kept in it) is a fresh temp folder."""
    from irene import lecture, lecture_note

    store = tmp_path / "lectures"
    monkeypatch.setattr(lecture, "STORE", store)
    monkeypatch.setattr(lecture_note, "STORE", store)
