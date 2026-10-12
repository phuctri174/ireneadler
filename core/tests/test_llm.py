import asyncio

import httpx

from irene import llm
from irene.llm import Ollama


def _client(handler):
    o = Ollama()
    o._client = httpx.AsyncClient(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return o


def test_warm_survives_dropped_connections(monkeypatch):
    monkeypatch.setattr(llm, "WARM_RETRY_S", (0, 0))
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadError("connection dropped", request=request)

    assert asyncio.run(_client(handler).warm()) is False
    assert len(calls) == 3


def test_warm_retries_until_ollama_answers(monkeypatch):
    monkeypatch.setattr(llm, "WARM_RETRY_S", (0, 0, 0))
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("not up yet", request=request)
        return httpx.Response(200, json={"done": True})

    assert asyncio.run(_client(handler).warm()) is True
    assert len(calls) == 3
