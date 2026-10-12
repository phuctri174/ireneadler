"""The fast path: a simple command's reply straight from a template once its tool has
run - no second LLM call. Only for short, single-purpose messages ("pause", "volume
to 30", "set a timer for 10 minutes", "what time is it") whose tool succeeded;
anything more ("pause it and tell me a joke") goes back to the model as usual.

Each template has a few phrasings and a cue, so the fast replies still sound like
her and still move her face.
"""
from __future__ import annotations

import random
import re

from .react import act_out

MAX_WORDS = 10
_MORE = re.compile(r"\b(and|then|also|but|why|explain|tell me|what about)\b", re.I)
_RESUME = re.compile(r"\b(resume|unpause|play|continue|start|back on)\b", re.I)


def _pick(options: list[str]) -> str:
    return random.choice(options)


def _time(args: dict, result: str, said: str):
    if args.get("until"):
        return None  # a countdown reads better in her own words
    m = re.search(r"(\d{1,2}):(\d{2}):\d{2}", result)
    if not m:
        return None
    hm = f"{int(m.group(1))}:{m.group(2)}"
    return _pick([f"Right! It's {hm}, sir.", f"Okay! {hm} on the dot, sir.", f"Hmm... {hm} right now."]), _pick(["curious", "happy", "proud"])


def _timer(args: dict, result: str, said: str):
    m = re.search(r"ends at (\d{1,2}:\d{2})", result)
    minutes = args.get("minutes")
    if not m or minutes is None:
        return None
    length = f"{minutes:g} minutes" if minutes != 1 else "one minute"
    label = f" for the {args['label']}" if args.get("label") else ""
    return (
        _pick([f"On it! Timer's on{label} - {length}. I'll call you at {m.group(1)}.", f"Done! {length}{label}. Back at you at {m.group(1)}, sir.", f"Ta-da! {length}{label}. See you at {m.group(1)}."]),
        _pick(["salute", "thumbsUp"]),
    )


def _song(result: str) -> str:
    """The title a media result names ("paused: Shape of You at 1:02"), short."""
    m = re.search(r":\s*(.+?)(?:\s+at \d+:\d\d)?$", result)
    title = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", m.group(1)).strip() if m else ""
    return title[:60]


def _media_trouble(result: str):
    """What she says when a media command did not do what he asked - never a
    cheerful "Paused!" over a key that never left (live, in dev mode)."""
    if result.startswith(("nothing is playing in my browser; not sent", "nothing is playing that I can see; not sent")):
        return _pick(["Hmm, I'm in test mode, so I can't press the media keys - and nothing's playing in my browser.", "Test mode, sir - no media keys from me, and my browser's quiet."]), _pick(["sheepish", "confused"])
    if result.startswith(("nothing is playing in my browser; key sent", "nothing is playing that I can see; key sent")):
        return None  # the key went: the normal line, it's his player
    if result.startswith("already paused"):
        return _pick([f"It's already paused, sir - {_song(result)}.", "Already on hold!"]), _pick(["headTilt", "curious"])
    if result.startswith("already playing"):
        return _pick([f"It's already playing - {_song(result)}.", "Still going, sir!"]), _pick(["headTilt", "happy"])
    if result.startswith(("tried to", "no next", "there's nothing")):
        return _pick(["Hmm, the player didn't budge.", "Hm. That didn't work - the player ignored me."]) if result.startswith("tried") else ("There's nothing to skip to, sir." if result.startswith("no next") else "That's the first one - nothing before it."), _pick(["sheepish", "confused"])
    return None


def _play_pause(args: dict, result: str, said: str):
    trouble = _media_trouble(result)
    if trouble:
        return trouble
    song = _song(result)
    if result.startswith("playing again") or (args.get("action") == "play" and not result.startswith("paused")):
        return _pick([f"Okay! And we're back{' - ' + song if song else ''}.", "Right! Playing again, sir.", "Yay! Resumed."]), _pick(["peace", "happy"])
    return _pick([f"Got it! Paused{' - ' + song if song else ''}.", "Done! Paused, sir.", "Okay! On hold for you."]), _pick(["thumbsUp", "salute"])


def _next(args: dict, result: str, said: str):
    trouble = _media_trouble(result)
    if trouble:
        return trouble
    song = _song(result) if result.startswith("skipped to") else ""
    if song:
        return _pick([f"Done! Next up: {song}.", f"Skipped! Now it's {song}."]), _pick(["giggle", "thumbsUp"])
    return _pick(["Done! Skipped.", "Okay! Next one, coming up.", "Right! Skipping - onwards."]), _pick(["giggle", "thumbsUp"])


def _previous(args: dict, result: str, said: str):
    trouble = _media_trouble(result)
    if trouble:
        return trouble
    if result.startswith("back to the start"):
        return _pick(["Back to the start of this one!", "From the top, sir!"]), _pick(["thumbsUp", "curious"])
    return _pick(["Okay! Going back one.", "Right! Rewinding a track, sir.", "Got it! Back to the last one."]), _pick(["thumbsUp", "curious"])


def _volume(args: dict, result: str, said: str):
    m = re.search(r"volume is now (\d+)%", result)
    if not m:
        return None
    return _pick([f"Done! Volume's at {m.group(1)}, sir.", f"Okay! {m.group(1)} percent.", f"Right! {m.group(1)} percent it is."]), _pick(["thumbsUp", "salute", "happy"])


def _mute(args: dict, result: str, said: str):
    if "muted" in result:
        return _pick(["Done! Muted.", "Okay! All quiet now.", "Got it! Sound's off, sir."]), _pick(["thumbsUp", "wink"])
    m = re.search(r"volume (\d+)%", result)
    return (f"Okay! Sound's back on, {m.group(1)} percent." if m else "Okay! Sound's back on."), _pick(["happy", "thumbsUp"])


def _panel(args: dict, result: str, said: str):
    if result.startswith("panel closed"):
        return _pick(["Done! Panel's away.", "Okay! Tucked away, sir.", "Got it! Panel closed."]), _pick(["thumbsUp", "wink"])
    what = "the sources" if "its sources" in result else "the videos" if "its videos" in result else "it"
    return _pick([f"Ta-da! {what[:1].upper() + what[1:]}, on the panel.", f"Here you go! {what[:1].upper() + what[1:]} - on the panel, sir.", f"Okay! Putting {what} up now."]), _pick(["proud", "peace", "thumbsUp"])


def _performed(args: dict, result: str, said: str):
    return _pick(["Ta-da! Did you like my little show, sir?", "And... scene! That's a few of my favourites.", "Hehe, that's me! Want an encore?"]), _pick(["proud", "wink", "happy"])


def _saved(args: dict, result: str, said: str):
    m = re.search(r"saved the panel as (.+?) in (Desktop|Downloads)", result)
    if not m:
        return None
    name, where = m.group(1), f"your {m.group(2)}"
    return _pick([f"Saved! It's on {where} as {name}.", f"Done! {name} is on {where}, sir.", f"Tucked away - {name}, on {where}."]), _pick(["satisfied", "thumbsUp", "salute"])


def _opened(args: dict, result: str, said: str):
    m = re.search(r"opened (.+?) \((desktop|downloads)\)", result)
    name = m.group(1).rsplit(".", 1)[0] if m else "it"
    return _pick([f"Opening {name} for you!", f"Here it is - {name}, open.", f"Done! {name} is open, sir."]), _pick(["presentBoard", "thumbsUp", "proud"])


def _screens(args: dict, result: str, said: str):
    # always a template, never a model call (in a sandboxed test too: the result
    # says so in the log) - a slow model reply made his next words "busy" and lost
    return _pick(["Screens off. Say my name when you want them back.", "Lights out, Mister Tri. I'm still listening.",
                  "Going dark - just call me."]), _pick(["lightsOut", "yawn", "pillowHands"])


TEMPLATES = {
    "screens_off": _screens,
    "open_file": _opened,
    "save_panel_pdf": _saved,
    "perform": _performed,
    "show_panel": _panel,
    "get_time": _time,
    "set_timer": _timer,
    "media_play_pause": _play_pause,
    "media_next": _next,
    "media_previous": _previous,
    "set_volume": _volume,
    "change_volume": _volume,
    "mute": _mute,
}


# unmistakable panel commands: no model call at all (the model sometimes answers
# "show me the sources" by listing them in <display> instead)
_LEAD = r"^\s*(?:(?:ok(?:ay)?|so|and|now|actually|great|nice|cool|thanks)[,!.]?\s+)*(?:(?:can|could|would) you\s+|please\s+)*"
_TAIL = r"(?:\s+(?:please|now|again|sir))*\s*[.!?]*\s*$"
_WHERE = r"(?:\s+up)?\s+(?:on|onto|to)\s+(?:the\s+|your\s+|my\s+)?(?:panel|screen|second screen)"
_PANEL_ON = re.compile(_LEAD + r"(?:show|put|pull up|bring up|display)(?:\s+me)?\s+(it|that|this|them|the (?:last |latest )?(?:research|results?|sources|links|videos|answer))" + _WHERE + _TAIL, re.I)
_PANEL_WHAT = re.compile(_LEAD + r"(?:show|pull up|bring up)(?:\s+me)?\s+the\s+(sources|links|videos|research|results)" + r"(?:\s+(?:again|you found|from (?:that|the research)))?" + _TAIL, re.I)
_PANEL_OFF = re.compile(_LEAD + r"(?:close|hide|dismiss|clear)\s+(?:the\s+|your\s+)?panel" + _TAIL, re.I)


# "perform some for me", "show me your tricks": the show, her own pick - unless he
# named the action himself (act_out handles "show me a kendo strike")
_PERFORM = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|now|irene|go on)\W+)*(?:please\W+)?perform\b|\b(?:can|could|would|will) you perform\b|\bperform (?:some|a few|something|for me|a little)\b|\bshow (me )?(off|your (moves|tricks|faces|expressions|skills))\b|\b(do|show me) (some|a few) (tricks|expressions|faces|moves)\b|\ba little show\b", re.I)


# "save this as a PDF", "save the panel to downloads", "keep this for later"
_SAVE = re.compile(
    _LEAD + r"(?:save|keep|export|store)\s+(?:this|it|that|the (?:panel|research|results?|sources|page))"
    r"(?:\s+(?:as|to|in|into|on)\s+(?:a\s+|an\s+|my\s+|the\s+)?(?:pdf|desktop|downloads?(?: folder)?))*(?:\s+for later)?" + _TAIL,
    re.I,
)


# the everyday media, volume and clock commands, said whole: no model call - the
# tool runs at once and the reply is a template that opens with a cached lead-in
_THING = r"(?:\s+(?:it|this|that|this one|the (?:music|song|video|track|playback|sound)|music|song|track))?"
_PAUSE = re.compile(_LEAD + r"(?:pause|stop (?:the )?(?:music|song|video|playback))" + _THING + r"(?:\s+for (?:a )?(?:sec|second|moment|bit|minute))?" + _TAIL, re.I)
_RESUME = re.compile(_LEAD + r"(?:resume|unpause|play|continue|keep playing)" + _THING + _TAIL, re.I)
_NEXT = re.compile(_LEAD + r"(?:skip|next)" + _THING + r"(?:\s+(?:song|track|one|video))?" + _TAIL, re.I)
_PREVIOUS = re.compile(_LEAD + r"(?:previous|go back(?: one)?|last(?=\s+(?:song|track|one|video)))(?:\s+(?:song|track|one|video))?" + _TAIL, re.I)
_MUTE = re.compile(_LEAD + r"(un)?mute" + r"(?:\s+(?:it|the sound|the audio|sound|audio|everything|the volume|the music))?" + _TAIL, re.I)
_SET_VOLUME = re.compile(_LEAD + r"(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+|at\s+)?(\d{1,3}|half|max(?:imum)?|full)(?:\s*%|\s+percent)?" + _TAIL, re.I)
_CHANGE_VOLUME = re.compile(
    _LEAD + r"(?:turn\s+(?:it|the (?:volume|sound|music))\s+(up|down)|volume\s+(up|down)|(louder|quieter|softer))"
    r"(?:\s+(a bit|a little|a tad|a lot|much|way))?" + _TAIL,
    re.I,
)
# his monitors off - every way he says it, answered without the model (Round 11:
# "turn off the screen" went to the model, which sometimes called set_volume or
# asked him to confirm). Whisper often hears his "off" as "up" or "on" ("turn up
# the screen please" -> set_volume, five times live); a screen is never the
# volume, and while he is talking to her the screens are on - so "turn up/on the
# screen" here is his "off", misheard. (In screens-off mode only wake phrases are
# heard; a screen *brightness* request has more words and never matches.)
_SCREENS_OFF = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|so|and|now|hey|irene|wait|alright|right)[,!.]?\s+)*(?:(?:can|could|would|will) you\s+|please\s+|(?:help|let) me\s+(?:to\s+)?|i want you to\s+)*"
    r"(?:(?:turn|switch|shut|power|put)\s+(?:off|up|on|down|out)\s+(?:the\s+|my\s+|your\s+|all\s+(?:the\s+)?|both\s+(?:the\s+)?)?(?:screens?|monitors?|displays?)"
    r"|(?:turn|switch|shut|power|put)\s+(?:the\s+|my\s+|your\s+|all\s+(?:the\s+)?|both\s+(?:the\s+)?)?(?:screens?|monitors?|displays?)\s+(?:off|up|on|down|out)"
    r"|(?:kill|darken|blank)\s+(?:the\s+|my\s+|your\s+|all\s+(?:the\s+)?)?(?:screens?|monitors?|displays?)"
    r"|(?:the\s+|my\s+)?(?:screens?|monitors?|displays?)\s+(?:off|dark|down)"
    r"|lights\s+out)"
    r"(?:\s+(?:for me|for now|now|please|irene|sir|thanks|thank you|again))*\s*[.!?]*\s*$",
    re.I,
)
_WHAT_TIME = re.compile(_LEAD + r"(?:what(?:'s| is)\s+the\s+time|what\s+time\s+is\s+it(?:\s+now)?|(?:got|tell me)\s+the\s+time|time\s+check)" + _TAIL, re.I)


# "open that PDF you saved", "open the file from earlier", "open the Queen's Gambit PDF"
_OPEN_SAVED = re.compile(
    _LEAD + r"(?:open|pull up|show me)\s+(?:up\s+)?(?:that|the|my|this)\s+"
    r"(?:(?:pdf|file|document)\s+(?:(?:that\s+)?(?:you|we)\s+(?:just\s+)?(?:saved|made|exported)(?:\s+(?:earlier|before|for me))?|from\s+(?:earlier|before|just now))"
    r"|((?:[\w'-]+\s+){1,5}?)(?:pdf|file)(?:\s+(?:you|we)\s+(?:just\s+)?saved)?)" + _TAIL,
    re.I,
)


def _saved_match(named: str | None) -> bool:
    """A named file goes straight to open_file only if she saved one by that name
    ("open my tax file" is his file: the model searches for it first)."""
    if not named:
        return True
    from tools.files import _find_saved

    return _find_saved(named) is not None


def _call(name: str, args: dict | None = None) -> str:
    import json

    return f"<tool_call>{json.dumps({'name': name, 'arguments': args or {}})}</tool_call>"


def _everyday(said: str) -> str | None:
    if _PAUSE.match(said):
        return _call("media_play_pause", {"action": "pause"})
    if _RESUME.match(said):
        return _call("media_play_pause", {"action": "play"})
    if _NEXT.match(said):
        return _call("media_next")
    if _PREVIOUS.match(said):
        return _call("media_previous")
    if m := _MUTE.match(said):
        return _call("mute", {"on": not m.group(1)})
    if m := _SET_VOLUME.match(said):
        level = m.group(1).lower()
        percent = 50 if level == "half" else 100 if level.startswith(("max", "full")) else min(100, int(level))
        return _call("set_volume", {"percent": percent})
    if m := _CHANGE_VOLUME.match(said):
        up = (m.group(1) or m.group(2) or "").lower() == "up" or (m.group(3) or "").lower() == "louder"
        size = (m.group(4) or "").lower()
        step = 5 if size in ("a bit", "a little", "a tad") else 25 if size in ("a lot", "much", "way") else 10
        return _call("change_volume", {"delta": step if up else -step})
    if _WHAT_TIME.match(said):
        return _call("get_time")
    return None


# the weather, the sunset: always a search (the model once invented a sunset time,
# and New York's weather), in his city unless he names another (home.py)
_ASK_WEATHER = re.compile(
    r"\b(weather|forecast|sunrise|sunset|(will|is|going to|gonna) (it )?(rain|snow)|how (hot|cold|warm) is it|temperature (today|outside|now|tomorrow|tonight))\b",
    re.I,
)


def _weather(said: str) -> str | None:
    if not _ASK_WEATHER.search(said) or _MORE.search(said) or len(said.split()) > 16:
        return None
    from .home import HOME

    return _call("research", {"question": HOME.localise(said.strip())})


# "Research X", "look up X": he said the word, so it is research - live, the model
# once answered "Research how kendo dan grades work." from memory instead
_RESEARCH = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|so|now|irene|hey irene|please|can you|could you|would you)[,\s]+)*"
    r"(?:research|look up|look into|find out about|find out|google|search (?:the web|online) for)\s+(?!at\b|to\b|me\b|it\b|that\b|this\b|them\b)(.{3,})$",
    re.I,
)


def _research(said: str) -> str | None:
    m = _RESEARCH.match(said.strip())
    if not m or len(said.split()) > 30:
        return None
    from .home import HOME

    question = m.group(1).strip(" ?.!,")
    question = re.sub(r"^(?:about|on|into|for)\s+", "", question, flags=re.I)
    return _call("research", {"question": HOME.localise(question)})


# Facts that change: she researches them on her own, never from memory (Round 7).
# On the routing prompt the model answered "the latest Python" and "who runs Intel"
# confidently from memory, out of date - a question about the current state of
# anything is research, decided here, not left to its judgement.
_VOLATILE = re.compile(
    r"\b(?:latest|newest|current(?:ly)?|most recent|recent|these days|right now|nowadays|as of now|this (?:year|season|month|week)|upcoming|still the)\b"
    r"|\b(?:how much (?:does|do|is|are|will)|price of|prices? for|cost of|costs?)\b|\bcost\b"
    r"|\b(?:come out|coming out|release date|released|launch(?:es|ed|ing)?|premieres?)\b"
    r"|\bpopulation\b|\bhow many people live\b|\bwhat'?s new (?:in|with|about)\b"
    r"|\b(?:ceo|president|prime minister|chairman|head coach|leader) of\b|\bwho (?:runs|leads|owns|heads|is in charge of|coaches)\b"
    r"|\b(?:rules|requirements|regulations|criteria)\b|\bwhat do i need (?:for|to)\b",
    re.I,
)
# a question at all - and not about her, him, or his own things
_QUESTION = re.compile(r"\?\s*$|^\W*(?:what|who|when|where|which|how|is|are|does|do|did|will|can|tell me|any news)\b", re.I)
_PERSONAL = re.compile(r"\b(?:you|your|yourself)\b|\bmy (?:files?|folder|desktop|downloads|screen|pc|computer|timer|volume|music|song|panel)\b|\b(?:timer|volume|panel|the time|what time)\b", re.I)


# an opening by name ("the King's Indian", "the London System"): recognised by the
# words that name chess openings - never a table of their moves
_OPENING = re.compile(
    r"\b(?:[A-Z][\w'’-]+\s+){0,3}(?:gambit|defen[cs]e|opening|system|variation|attack)\b|\b(?:sicilian|ruy lopez|najdorf|caro[- ]kann|nimzo|gr[uü]nfeld|catalan|king'?s indian|queen'?s indian|benoni|pirc|alekhine|scandinavian|italian game|scotch game|vienna game|fried liver)\b",
    re.I,
)


def _chess_opening(said: str) -> str | None:
    """A chess opening he asks about: researched, so the board's moves come from a
    page she read (the model may misremember a line - live, it gave the London
    System the Italian's moves)."""
    text = said.strip()
    if len(text.split()) > 20 or not _QUESTION.search(text + "?") or _PERSONAL.search(text):
        return None
    if not _OPENING.search(text) or not (re.search(r"\bchess\b", text, re.I) or re.search(r"\b(?:sicilian|ruy lopez|najdorf|caro|nimzo|gr[uü]nfeld|catalan|indian|benoni|pirc|alekhine|scandinavian|italian game|london system|scotch|vienna|fried liver|gambit)\b", text, re.I)):
        return None
    question = re.sub(r"^\W*(?:explain|tell me about|what'?s|what is|describe|show me)\s+", "", text, flags=re.I).rstrip("?.! ")
    if not re.search(r"\bchess\b", question, re.I):
        question += " chess opening moves"
    return _call("research", {"question": question})


def _volatile(said: str) -> str | None:
    text = said.strip()
    if len(text.split()) > 24 or not _QUESTION.search(text) or not _VOLATILE.search(text) or _PERSONAL.search(text) or _MORE.search(text):
        return None
    from .home import HOME

    return _call("research", {"question": HOME.localise(text.rstrip("?.! "))})


# "what's new today", "brief me", "what's happening", "anything new": his daily
# briefing (tools/briefing.py) - the whole message, so "anything new in my
# downloads" (a folder) and "what's new in Python 3.13" (research) never match
_BRIEF_LEAD = (r"^\W*(?:(?:hey|hi|hello|ok(?:ay)?|so|alright|right|well|morning|good (?:morning|afternoon|evening)|irene|hey irene)\W+)*"
               r"(?:(?:can|could|would) you\s+|please\s+|(?:i want|i'd like) (?:you )?to\s+|let'?s\s+|just\s+)*")
_BRIEF_WHEN = r"(?:\s+(?:today|this morning|this afternoon|this evening|tonight|so far|right now|now|out there|in the world|around the world|lately))?"
_BRIEF = re.compile(
    _BRIEF_LEAD
    + r"(?:what'?s\s+new|what\s+is\s+new|what'?s\s+(?:been\s+)?happening|what\s+is\s+happening|what'?s\s+going\s+on|what\s+is\s+going\s+on"
    r"|anything\s+new|any\s+news|what'?s\s+the\s+news|what\s+did\s+i\s+miss|what\s+have\s+i\s+missed|catch\s+me\s+up|fill\s+me\s+in"
    r"|brief\s+me(?:\s+on\s+(?:today|the\s+day|the\s+news|what'?s\s+new|what'?s\s+happening))?"
    r"|(?:give\s+me\s+|let'?s\s+(?:have|hear)\s+|i'?d\s+like\s+|start\s+)?(?:the\s+|my\s+|a\s+|today'?s\s+|your\s+)?(?:daily\s+|morning\s+|news\s+)?(?:briefing|brief|rundown|round-?up|news\s+round-?up))"
    + _BRIEF_WHEN + _BRIEF_WHEN + r"(?:[,\s]+(?:then|please|irene|sir|mister tri))*\s*[.!?]*\s*$",
    re.I,
)
# a follow-up on one item of the briefing just given: "tell me more about the
# second one", "more on the gold", "what about NVIDIA?", "go deeper on number three"
_ORDINAL = r"(?:first|second|third|last|1st|2nd|3rd|one|two|three|number\s+(?:one|two|three|1|2|3)|[123])"
_EXPAND = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|so|and|alright|hmm|oh|wait|irene)\W+)*(?:(?:can|could) you\s+|please\s+)*"
    r"(?:tell\s+me\s+(?:a\s+bit\s+|a\s+little\s+)?more\s+(?:about|on)|(?:a\s+bit\s+|a\s+little\s+)?more\s+(?:about|on)|go\s+(?:deeper|further|into\s+more\s+detail)\s+(?:on|into)|expand\s+on|"
    r"what\s+about|details?\s+on|(?:let'?s\s+)?(?:hear|dig)\s+(?:more\s+)?(?:about|into)|zoom\s+in\s+on|explain)\s+"
    r"(?:the\s+)?(" + _ORDINAL + r"(?:\s+(?:one|item|story|thing|bit|headline))?|gold|weather|rain|nvidia|nvda|amd|microsoft|msft|bitcoin|btc|the\s+s&p|s&p(?:\s+500)?|dollar|usd(?:/vnd)?|"
    r"vietnam(?:ese)?\s+(?:one|story|news)|world\s+(?:one|story|news)|news(?:\s+story)?|story|[\w'-]+(?:\s+[\w'-]+)?\s+(?:one|story))"
    r"(?:\s+(?:please|then|irene))?\s*[.!?]*\s*$",
    re.I,
)
_SPOKEN_ORDINAL = {"first": "1", "one": "1", "1st": "1", "second": "2", "two": "2", "2nd": "2", "third": "3", "three": "3", "3rd": "3", "last": "last"}


def _briefing(said: str, recent_tools=()) -> str | None:
    text = said.strip()
    if _BRIEF.match(text):
        return _call("daily_briefing")
    if "daily_briefing" in recent_tools and (m := _EXPAND.match(text)):
        what = re.sub(r"\s+(?:one|item|story|thing|bit|headline)$", "", m.group(1).lower()).replace("number ", "").strip()
        what = _SPOKEN_ORDINAL.get(what, what)
        return _call("daily_briefing", {"expand": what})
    return None


def direct_call(said: str, recent_tools=()) -> str | None:
    """A tool call written for the model, for a command that needs no model to
    understand it - or None. `recent_tools`: what ran in the last turns (a
    follow-up on the briefing just given)."""
    if _SCREENS_OFF.match(said.replace(",", "")):
        return _call("screens_off")
    if (brief := _briefing(said, recent_tools)) is not None:
        return brief
    if (weather := _weather(said)) is not None:
        return weather
    if (research := _research(said)) is not None:
        return research
    if (volatile := _volatile(said)) is not None:
        return volatile
    if (opening := _chess_opening(said)) is not None:
        return opening
    if len(said.split()) > MAX_WORDS + 4:
        return None
    if len(said.split()) <= 8 and (everyday := _everyday(said)):
        return everyday
    if (m := _OPEN_SAVED.match(said)) and _saved_match(m.group(1)):
        # "open that PDF you saved", "open the file from earlier": what she saved
        return _call("open_file", {"saved": (m.group(1) or "last").strip()})
    if _SAVE.match(said):
        where = "downloads" if re.search(r"\bdownloads?\b", said, re.I) else "desktop"
        return f'<tool_call>{{"name": "save_panel_pdf", "arguments": {{"location": "{where}"}}}}</tool_call>'
    if _PERFORM.search(said) and act_out(said) is None:
        return '<tool_call>{"name": "perform", "arguments": {"sequence": "surprise"}}</tool_call>'
    if len(said.split()) > MAX_WORDS:
        return None
    what = None
    if _PANEL_OFF.match(said):
        what = "close"
    elif m := (_PANEL_ON.match(said) or _PANEL_WHAT.match(said)):
        what = m.group(1).lower().removeprefix("the ").strip()
        what = {"it": "that", "this": "that", "them": "that", "links": "sources"}.get(what, what)
    if what is None:
        return None
    return f'<tool_call>{{"name": "show_panel", "arguments": {{"what": "{what}"}}}}</tool_call>'


_ITEM_CUES = {
    ("gold", True): ("excited", "happy"), ("gold", False): ("concerned", "surprised"),
    ("market", True): ("happy", "proud"), ("market", False): ("surprised", "concerned"),
    ("weather", None): ("concerned", "sleepy"), ("world", None): ("focused", "curious"), ("vietnam", None): ("curious", "focused"),
}


def briefing_reply(result: str) -> str | None:
    """The briefing, spoken: her own sentences from tools/briefing.py (every number
    fetched, none from the model), each with a cue that fits it - the first one
    squaring her notes like a newsreader."""
    from tools import briefing

    b = briefing.LAST
    if b is None or result.startswith(("error", "declined")) or not b.speech:
        return None
    parts = []
    for k, sentence in enumerate(b.speech):
        item = b.items[k] if k < len(b.items) else None
        if k == 0:
            cue = "newsDesk"
        elif item is not None:
            up = item.board.get("up") if item.kind in ("gold", "market") else None
            cue = _pick(list(_ITEM_CUES.get((item.kind, up), ("curious",))))
        else:
            cue = "headTilt" if sentence.endswith("?") else "sheepish"
        parts.append(f"<cue>{cue}</cue>{sentence}")
    return f"<speak>{' '.join(parts)}</speak>"


def expansion_reply(result: str) -> str | None:
    """More on one item of the briefing, in her words from tools/briefing.py."""
    from tools import briefing

    if result.startswith(("error", "declined")) or not briefing.LAST_EXPANSION:
        return None
    first, *rest = briefing.LAST_EXPANSION
    return f"<speak><cue>{_pick(['focused', 'curious'])}</cue>{first} {' '.join(rest)}</speak>"


def reply(name: str, args: dict, result: str, said: str) -> str | None:
    """The finished reply (model format) for a simple command, or None to ask the model."""
    if name == "daily_briefing":
        return expansion_reply(result) if args.get("expand") else briefing_reply(result)
    fn = TEMPLATES.get(name)
    if fn is None or len(said.split()) > MAX_WORDS or _MORE.search(said):
        return None
    if re.match(r"\s*(error|declined|refused)", result, re.I):
        return None
    made = fn(args, result, said)
    if made is None:
        return None
    speak, cue = made
    return f"<speak><cue>{cue}</cue>{speak}</speak>"
