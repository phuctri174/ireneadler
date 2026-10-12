"""Probe a model: tool-calling (native, then prompt-protocol fallback) and image input.

Run: .venv\\Scripts\\python scripts\\ollama_probe.py [model]   (default gemma3:12b)
"""
import base64
import io
import json
import re
import sys
import time

import httpx
from PIL import Image, ImageDraw

OLLAMA = "http://127.0.0.1:11434"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemma3:12b"
# thinking models answer far slower with it on; gemma3 rejects the flag entirely
THINK = {} if MODEL.startswith("gemma3") else {"think": False}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Start a countdown timer.",
            "parameters": {
                "type": "object",
                "properties": {"minutes": {"type": "number"}},
                "required": ["minutes"],
            },
        },
    },
]

CASES = [
    ("get_weather", {"city": "hanoi"}, "What's the weather in Hanoi?"),
    ("get_weather", {"city": "tokyo"}, "is it raining in tokyo right now"),
    ("get_weather", {"city": "paris"}, "Paris weather please"),
    ("get_weather", {"city": "london"}, "Do I need a jacket in London today?"),
    ("get_weather", {"city": "berlin"}, "how hot is it in berlin"),
    ("get_weather", {"city": "sydney"}, "Check the forecast for Sydney for me."),
    ("get_weather", {"city": "seoul"}, "weather seoul"),
    ("get_weather", {"city": "new york"}, "Irene, what's it like outside in New York?"),
    ("get_weather", {"city": "da nang"}, "Is it sunny in Da Nang?"),
    ("get_weather", {"city": "madrid"}, "Tell me the temperature in Madrid."),
    ("set_timer", {"minutes": 5}, "Set a timer for 5 minutes."),
    ("set_timer", {"minutes": 10}, "timer ten minutes"),
    ("set_timer", {"minutes": 30}, "Remind me in half an hour."),
    ("set_timer", {"minutes": 2}, "Start a 2 minute countdown for my tea."),
    ("set_timer", {"minutes": 15}, "can you time 15 min for me"),
    ("set_timer", {"minutes": 60}, "Set an hour-long timer."),
    ("set_timer", {"minutes": 1}, "one minute timer please"),
    ("set_timer", {"minutes": 45}, "Count down 45 minutes."),
    ("set_timer", {"minutes": 3}, "I'm boiling eggs, give me three minutes."),
    ("set_timer", {"minutes": 20}, "Put a twenty minute timer on."),
]

FALLBACK_SYSTEM = """You can call tools. Available tools (JSON schema):
{tools}

To call a tool, reply with ONLY this, nothing else:
<tool_call>{{"name": "<tool name>", "arguments": {{...}}}}</tool_call>
Otherwise reply normally."""


def args_match(want: dict, got: dict) -> bool:
    for key, value in want.items():
        g = got.get(key)
        if isinstance(value, str):
            if not isinstance(g, str) or g.strip().lower() != value:
                return False
        else:
            try:
                if float(g) != float(value):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def parse_fallback(text: str):
    m = re.search(r"<tool_call>\s*(\{.*\})\s*</tool_call>", text, re.S)
    if not m:
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return obj.get("name"), obj.get("arguments") or {}


def run_tools(client: httpx.Client, native: bool):
    ok = 0
    rows = []
    for want_name, want_args, prompt in CASES:
        body = {"model": MODEL, "stream": False, "options": {"temperature": 0}, **THINK}
        if native:
            body["messages"] = [{"role": "user", "content": prompt}]
            body["tools"] = TOOLS
        else:
            system = FALLBACK_SYSTEM.format(tools=json.dumps([t["function"] for t in TOOLS], indent=1))
            body["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        t0 = time.perf_counter()
        r = client.post(f"{OLLAMA}/api/chat", json=body)
        dt = time.perf_counter() - t0
        if r.status_code != 200:
            return None, r.text
        msg = r.json()["message"]
        if native:
            calls = msg.get("tool_calls") or []
            got = (calls[0]["function"]["name"], calls[0]["function"]["arguments"]) if calls else None
        else:
            got = parse_fallback(msg.get("content", ""))
        good = bool(got) and got[0] == want_name and args_match(want_args, got[1])
        ok += good
        rows.append((good, dt, prompt, got))
    return ok, rows


def image_probe(client: httpx.Client):
    img = Image.new("RGB", (640, 360), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((60, 80, 260, 280), fill="red")
    d.rectangle((380, 80, 580, 280), fill="blue")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    t0 = time.perf_counter()
    r = client.post(
        f"{OLLAMA}/api/chat",
        json={
            "model": MODEL,
            "stream": False,
            **THINK,
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "user",
                    "content": "Describe the shapes in this image and their colours, left to right. One sentence.",
                    "images": [b64],
                }
            ],
        },
    )
    return time.perf_counter() - t0, r.status_code, r.json().get("message", {}).get("content", r.text)


def main():
    with httpx.Client(timeout=180) as client:
        # warm load so the first case's timing isn't model load
        client.post(f"{OLLAMA}/api/chat", json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": False, **THINK})

        print("== native tools ==")
        ok, rows = run_tools(client, native=True)
        if ok is None:
            print(f"native tools rejected: {rows.strip()}")
        else:
            for good, dt, prompt, got in rows:
                print(f"  {'OK ' if good else 'BAD'} {dt:5.2f}s  {prompt!r:52} -> {got}")
            print(f"native: {ok}/{len(CASES)}")

        print("== prompt-protocol fallback ==")
        ok, rows = run_tools(client, native=False)
        for good, dt, prompt, got in rows:
            print(f"  {'OK ' if good else 'BAD'} {dt:5.2f}s  {prompt!r:52} -> {got}")
        print(f"fallback: {ok}/{len(CASES)}")

        print("== image input ==")
        dt, status, text = image_probe(client)
        print(f"  {status} {dt:.2f}s  {text.strip()}")


if __name__ == "__main__":
    sys.exit(main())
