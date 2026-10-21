# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""A cheap intent router: which tools a message could need, before the model sees it.

The system prompt stays the same for every request (Ollama reuses its cache of
it and of the whole history); what changes per message goes in one short block
right before his message - the clock, any hints, and only the tool groups the
message is plausibly about, with their signatures and rules. Every other tool
is still named in one line, so an unexpected need can still be met.

A group is chosen by keywords, or because one of its tools ran in the last two
turns (follow-ups: "and the other folder?", "turn it up a bit more").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from tools import REGISTRY
from tools.registry import catalogue


@dataclass(frozen=True)
class Group:
    name: str
    tools: tuple[str, ...]
    keywords: re.Pattern
    rules: str
    # a message that matches this is talk about the topic, not a request for the tool
    avoid: re.Pattern | None = None
    # stricter: the message is talk about this group's topic ("my screen is cracked",
    # "turn off the lights") - its tools are not offered at all, not even by name
    talk: re.Pattern | None = None


def _k(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


PERFORM_WORDS = (
    r"\bperform|what (else )?can you do|show (me )?(off|what you can do|your (moves|tricks|faces|expressions|skills|stuff))"
    r"|(some|a few|your) (tricks|expressions|faces|moves)|a little show|entertain me"
)

GROUPS: tuple[Group, ...] = (
    Group(
        "time",
        ("get_time", "set_timer"),
        _k(r"\btime\b|clock|o'?clock|timer|remind|alarm|wake me|countdown|pomodoro|\b(\d+|one|two|three|four|five|ten|fifteen|twenty|thirty|forty|sixty|ninety|half an|an) (seconds?|minutes?|hours?)\b|until|till\b|how long|days? (left|to go)|what day|date"),
        """- The "Now" section has the current local date, weekday and time. Answer the date,
  day, month, year or "is it late" straight from it - no tool.
- get_time: the exact time to the second; and with until ('18:00', '12-25') for
  "how long until 6pm" / "days until Christmas" - never count days yourself.
  Sunrise and sunset are not the clock: research them.
- set_timer: only when he asks for a timer or reminder AND says how long. If he
  gives no length ("set a timer", "remind me later"), ask how long; don't call it.""",
    ),
    Group(
        "files",
        ("list_files", "search_files", "read_and_summarize", "open_file", "organize_files", "move_to_quarantine"),
        _k(r"\bfiles?\b|folder|desktop|downloads|document|\bpdf\b|docx|\.txt|\bcv\b|resume|\btax\b|report|notes|find my|where('?s| is| are) my|delete|remove|trash|get rid|tidy|organi[sz]e|clean (up|out)|sort (out|my)|summari[sz]e|read (the|my|that|this) (file|doc)|quarantine"),
        """- search_files: when he asks where one of HIS files is, or to find it - call it
  with the key word he used ("tax", "cv") rather than asking where it might be.
  Advice or knowledge questions (which monitor, which format) are not searches.
- File tools need a file or folder he actually names. "That file" with no name:
  ask which one - never invent a path.
- list_files: what's in a folder - "what's inside the Games folder", "anything new in
  Downloads" (path "" for the root). search_files needs a word to search for.
- read_and_summarize reads HIS files only. A web link (http..., a site) is
  read_page_text, never a file tool.
- list_files / search_files / read_and_summarize: his Desktop and Downloads only.
  Name the root ("desktop" or "downloads") and a path inside it - never a full
  path like C:/Users/... . Anything else is refused by the system; say so plainly.
- organize_files: when he asks to tidy, sort or clean up a folder. Call it - never
  describe a plan yourself; the tool reads the folder and builds the real plan,
  and the system shows it to him before anything moves.
- move_to_quarantine: when he asks to delete, remove, trash or get rid of a file.
  There is no delete: say you'll quarantine it instead.
- open_file: when he asks to open one of his files (a PDF, a picture, a document)
  in its app. A file you saved this session ("open that PDF you saved", "open the
  file from earlier"): saved "last" or words from its name. Opening is not reading:
  "what does it say" is read_and_summarize.""",
        # thoughts, a desk, a life: talk, not files
        _k(r"\b(thoughts?|mind|head|ideas?|life|schedule|desk at|feelings|priorities)\b(?!.*\b(file|folder|pdf|docx?)\b)"),
        # ...and what he already did with a file ("I saved that file yesterday, don't
        # worry") is news, not a request
        talk=_k(r"\b(thoughts?|mind|head|ideas?|life|schedule|desk at|feelings|priorities)\b(?!.*\b(file|folder|pdf|docx?)\b)"
                # a request anywhere in it ("FIND the tax file I saved") is not news
                r"|^(?!.*\b(open|find|where|show|read|summari[sz]e|search|look for|locate)\b).*\b(i|i've|we)\s+(already\s+)?(saved|downloaded|sent|moved|deleted|backed up)\b"
                r"|^(?!.*\b(open|find|where|show|read|summari[sz]e|search|look for|locate)\b).*\bdon'?t worry\b"),
    ),
    Group(
        "screen",
        ("capture_screen",),
        _k(r"screen|window|\btab\b|monitor|this error|what('?s| is) (this|that)|look at (this|that|it|the)|(have|got) open|read (this|that) for me|can you see"),
        """- capture_screen: only when he asks about what's on his screen or in a window
  ("what's this error?", "read this for me"). "full" by default ("my screen");
  "active_window" only when he says window, app or tab. Never otherwise:
  a screen as a topic ("my screen is cracked") needs no tool.""",
        # the screen as a thing, not what's on it
        talk=_k(r"\b(cracked|broken|brightness|resolution|refresh rate|protector|dead pixels?|screen time|glare)\b|\b(new|buy|which|best|bigger|second) (monitor|screen)\b"),
    ),
    Group(
        "media",
        ("media_play_pause", "media_next", "media_previous", "set_volume", "change_volume", "mute"),
        _k(r"pause|resume|unpause|\bplay\b|skip|next|previous|go back|song|track|music|volume|louder|quieter|softer|speak up|\bmute\b|unmute|turn it (up|down)|too loud|can'?t hear|sound"),
        """- media_play_pause / media_next / media_previous: "pause", "resume", "unpause",
  "skip this", "next song", "go back one" - whatever is playing, in any app. Never
  say you paused, resumed, skipped or changed the volume without calling the tool.
- set_volume / change_volume / mute: his system sound. "Turn it up", "louder", "speak
  up" = change_volume +10 ("a bit" 5, "a lot" 25; down is negative); only a number
  ("volume to 30") is set_volume.""",
        _k(r"\b(let me|let's|i need to|we should) (pause|stop)\b|pause (and|to) (think|breathe|reflect)|next (week|time|year|step|question)|\b(screens?|monitors?|displays?)\b"),
        # a screen's brightness is not her volume ("my screen brightness is too low" ->
        # change_volume, 2 of 2 runs): sound tools are not offered for a screen
        talk=_k(r"\bbrightness\b|\b(screens?|monitors?|displays?)\b(?!.*\b(volume|sound|speakers?|audio|louder|quieter|mute)\b)"),
    ),
    Group(
        "web",
        ("youtube_search", "youtube_play", "open_url", "read_page_text", "open_in_my_browser"),
        _k(r"\byoutube\b|video|watch|\bplay\b|put on|song|music|open|website|\bsite\b|\bpage\b|\burl\b|\.(com|org|net|io|vn)\b|link|article|summari[sz]e (this|that|the) page|my (chrome|browser)"),
        """- youtube_play: he asks to play or put on a song, video or music - it plays in his
  own Chrome, logged in. youtube_search: he wants to find videos without playing one.
- open_url: he asks to open a site or page - it opens in his own Chrome.
  read_page_text: he asks what a page says or to summarise it (fetched silently).
- open_in_my_browser: a research source by number ("open source 2") in his Chrome.""",
        # his browser as a topic ("my Chrome keeps crashing"), not a page to open
        talk=_k(r"\b(chrome|browser|youtube)\b.*\b(crash(es|ing|ed)?|keeps|slow|lag(gy|ging)?|freez(es|ing)|broken|stuck|won'?t)\b(?!.*\b(open|play|go to)\b)"),
    ),
    Group(
        "power",
        ("screens_off", "enable_screens_off"),
        _k(r"\b(screens?|monitors?|displays?)\b.*\b(off|dark|down|sleep)\b|\b(turn|switch|shut|kill|power)\b.*\b(off|down|up|on)\b.*\b(screens?|monitors?|displays?)\b|lights out"),
        """- screens_off: he wants the monitors off while the PC stays on - "screens off",
  "turn off the screen", "turn off my monitors", "kill the displays". It always
  works, never asks. While he talks to you the screens ARE on, so "turn up / turn
  on the screen" is his "off" misheard: screens_off. A screen is NEVER the volume -
  never set_volume or change_volume for a screen. Talk ABOUT screens ("my screen is
  cracked") is not it. There is no screens_on tool: a wake phrase lights them.
- enable_screens_off: only when he asks to enable the screens-off MODE itself
  ("enable screens-off mode"). Never for "screens off".""",
        # his room's lights, a fan, the TV: not her monitors (routing eval not-power-lights)
        talk=_k(r"\b(lights?|lamps?|fan|air ?con|aircon|heater|tv|television)\b(?!.*\b(screens?|monitors?|displays?)\b)"),
    ),
    Group(
        "dashboard",
        ("open_dashboard_item",),
        _k(r"dashboard|second screen|other screen|(news|headline|story|stock|quote|weather)( item)?\b.*\b(on|from) (the|my)\b|\b(first|second|third|fourth|fifth|sixth|last|top|\d+(st|nd|rd|th)?) (news|headline|story|stock|item)|open (the )?(news|headline|story|stock|weather)"),
        """- open_dashboard_item: he points at something on the dashboard on his second
  screen - "open the second news item" (news, 2), "the top headline" (news, 1), "the
  last story" (news, -1), "open the weather" (weather, 1), "the third stock" (stocks,
  3). The numbers are the ones shown on it. A news QUESTION ("what's the latest on
  NVIDIA?") is research, not this.""",
    ),
    Group(
        "research",
        ("research",),
        _k(r"research|look (it |that |this )?up|look into|search (for|the web|online)|google (it|that|this)|find out|sources?\b|latest|news|recent|currently|right now|nowadays|this (week|month|year)|\b20[2-3]\d\b|price|cost|how much (is|does|are|do)|release|specs?\b|review|\bwho (is|was|won|invented|painted|wrote|made|discovered)|\bwhat (is|are|was|were|causes|happened|does)|what'?s (the|a|an)\b|\bwhen (is|was|did|does|will)|\bwhere (is|was|are|can)|\bwhy (is|does|do|are|did)|\bhow (does|do|did|long|tall|big|far|many|old|fast)|compare|\bvs\.?\b|versus|recipe|tell me about|weather|forecast|\b(will|is|going to|gonna) (it )?(rain|snow)|\brain(ing)? (today|tomorrow|tonight|later|this)|temperature (today|outside|now|tomorrow)|how (hot|cold|warm) is it|sunrise|sunset|near me|nearby|typhoon"),
        """- research: ALWAYS when he says research, look up, look into or find sources - even
  if you think you know. And ON YOUR OWN, without being asked, whenever you are not
  confident and current: never say "I don't know" or "I'm not sure" - research it. Also for facts that change or that you'd guess at: prices,
  specs, news, anything recent, statistics, dates, niche facts - your memory is out
  of date, so research rather than answer from it. Common knowledge you're sure of
  (the capital of Japan, why the sky is blue in a sentence) needs no tool.
- Weather, forecasts, sunrise and sunset change daily: research them, never guess.
- Pass one clear search as question. Follow-ups on the last research ("tell me more",
  "what did the second source say") answer from its result; research again only for
  a new question.""",
        _k(r"(clear|delete|erase|remove|wipe|forget|get rid of)\b.{0,25}\bresearch(es)?\b|\bresearch\b.{0,15}\b(cleared|wiped|gone)\b|\bmy (research|review|news|sources?)\b|\bpanel\b|on (the|my|your) screen|\bshow (me )?(it|that|them|the (sources?|links?|videos?|research|results?))\b|pull (it |that )?up|how are you|how('?s| is) it going|what('?s| is) (your|up)\b|about (you|yourself)|what (are|were|was) you (doing|up to|playing|practi[cs]ing)\b|what have you been (doing|up to)|do you (like|think|feel|remember)|what did (we|you) (already )?(look up|research|find)|(we|you) (already )?(looked up|researched)|what time(?! (is|does) (the )?(sunset|sunrise))|what day|timer|my (screen|files?|folder|pc|computer|desktop|downloads)|this (error|window|file)|what('?s| is) (this|that) on"),
    ),
    Group(
        "panel",
        ("show_panel", "save_panel_pdf"),
        _k(r"\bpanel\b|on (the|your|my) screen|on screen|second screen|show (me )?(it|that|this|them|those|the (sources?|links?|results?|videos?|research|details?|answer))|put (it|that|this|them) (up|on)|pull (it |that )?up|bring (it |that )?up|display (it|that|the)|sources?\b|links?\b|what you found|close (it|that)|hide (it|that)|take (it|that) (down|away)|\bpdf\b|\bsave (this|it|that|the (panel|research|results?|sources))\b|keep (this|it|that) for later|export (this|it|that)"),
        """- show_panel: when he wants a result on your panel or screen - "show it on the
  panel", "put that on the screen", "show me the sources", "pull up the Eiffel Tower
  research", "close the panel". what: his words for it ("last research", "sources",
  "videos", a topic, "that", "close"). Works for any earlier research or detailed
  answer, not only the last. Writing it in <display> does NOT put it on the panel -
  only a show_panel call does, so call it instead of repeating the content.
- save_panel_pdf: when he wants what's on the panel kept - "save this as a PDF",
  "save the panel", "keep this for later". location "desktop" unless he says
  downloads; name only if he gives one. It never overwrites.""",
        _k(r"what('?s| is) on my screen|my screen (is|has|keeps)|(read|see) my screen"),
    ),
    Group(
        "perform",
        ("perform",),
        _k(PERFORM_WORDS),
        """- perform: when he asks what you can do and to see it, or to perform, show off, or
  see your faces, expressions, tricks or moves - DO it with perform, never list them.
  sequence: 3-6 cue names that make a little story ("wave, starryEyed, kendo, giggle"),
  or "surprise". The show plays first; then say one short line about it.""",
    ),
    Group(
        "system",
        ("system_status",),
        _k(r"\bcpu\b|\bgpu\b|vram|\bram\b|memory|my (pc|computer|laptop|machine)|\bload\b|performance|how'?s (my )?(pc|computer)|temperature|usage"),
        """- system_status: his PC's CPU, GPU, RAM and VRAM load right now. Only for his
  machine, never for advice about buying or specs.""",
        _k(r"\b(buy|buying|recommend|should i get|worth it|upgrade to|best .* for)\b"),
    ),
    Group(
        "briefing",
        ("daily_briefing",),
        _k(r"what'?s new|what is new|what'?s (been )?happening|what'?s going on|anything new|any news|the news|brief me|briefing|rundown|round-?up|catch me up|fill me in|what did i miss"),
        """- daily_briefing: his daily briefing - "what's new today", "brief me", "what's
  happening", "anything new", "catch me up". It picks the few most notable things
  (his city's weather, SJC gold, his markets, world and Vietnamese news), says them
  and puts the full briefing on the panel. Never answer those from memory.
- After a briefing, "tell me more about the second one" / "more on the gold" =
  daily_briefing(expand="2") / (expand="gold") - the item of THAT briefing, not
  a new research.""",
        _k(r"\bnew (in|on|for|about) (my|the) (downloads|desktop|folder|documents)\b|what'?s new in (python|windows|ios|android|version|the (new|latest) (version|update|release))"),
    ),
    Group(
        "lecture",
        ("lecture_start", "lecture_stop", "lecture_summary", "lecture_ask", "lecture_research"),
        _k(r"\blectures?\b|seminar|webinar|take notes|transcri|listen(ing)? to (this|the|it)\b|stop listening"
           r"|(summari[sz]e|sum up|recap|record|listen to)\b.{0,25}\b(class|lesson|meeting|talk)\b|\b(class|lesson|meeting|talk)\b.{0,20}\b(about|summary|recap|over)\b"
           r"|the (second|third|first|last|next) (topic|section)"),
        """- lecture_start: when he asks you to listen to, transcribe or take notes on a lecture,
  class, talk or meeting playing on the PC. You hear the system audio, not his mic.
- lecture_stop: when he says to stop listening, or that the lecture/meeting is over.
- lecture_summary: "summarise the lecture", "what was the class about", "recap the
  meeting". It speaks the summary itself and fills the panel; after it, "more on the
  second topic" = lecture_summary(expand="2").
- lecture_ask: a question about what was SAID in the lecture he had you listen to
  ("what did they say about X", "did the professor mention the exam"). Answer only
  from what it returns, with the time; never fill gaps from your own knowledge.
- lecture_research: ONLY when he asks you to look up / research / search online for more
  on a topic of the lecture ("look up more on the second topic", "research the first
  topic") or says yes to your offer to look things up. topic = its number, title, a
  concept, or "all". "Tell me more about the second topic" is the LECTURE's words:
  lecture_summary(expand="2"), not this.
- Talk about lectures in general ("my lecture was boring", "I have class tomorrow")
  is conversation, not a tool.""",
        _k(r"\b(was|is|were) (so |really |too )?(boring|long|hard|fun|great|awful|cancell?ed)\b|\b(have|got) (a |my )?(lecture|class|meeting|exam) (tomorrow|today|tonight|later|at)\b"),
    ),
    Group(
        "forget",
        ("forget_conversation", "clear_research", "forget_memory"),
        _k(r"forget|clear (this|the|our) (chat|conversation|history)|wipe|start (fresh|over)|don'?t remember|(delete|erase|remove) (what|everything|anything) you (know|remember|kept)|(clear|delete|erase|remove|wipe|forget|get rid of)\b.{0,25}\bresearch(es)?\b|\bresearch\b.{0,15}\b(cleared|wiped|gone)\b"),
        """- forget_conversation: only when he explicitly asks you to forget or clear this
  conversation. "Forget it" / "never mind" just means drop the subject.
- clear_research: when he asks you to clear, wipe, delete or forget your RESEARCH
  ("Irene, clear your research", "wipe the research history") - it removes every
  saved research from your memory and the panel. Not forget_conversation, and never
  a new research.
- forget_memory: when he asks you to forget or delete what you remember about a
  THING - a person, a topic, a project ("forget what I told you about Trác",
  "delete what you know about my work project"). about: that thing, in his words.
  It shows him what will go and asks first. Not for what he said just now, in this
  conversation ("don't remember any of what I just said"): that is forget_conversation.""",
        _k(r"\bforget (it|about it|that)\b|never ?mind"),
    ),
)

BY_TOOL = {t: g for g in GROUPS for t in g.tools}


def groups_for(text: str, recent_tools: list[str] = ()) -> list[Group]:
    """The tool groups this message may need: by keyword, or recently used."""
    chosen = [g for g in GROUPS if g.keywords.search(text) and not (g.avoid and g.avoid.search(text))]
    for name in recent_tools:
        g = BY_TOOL.get(name)
        if g and g not in chosen:
            chosen.append(g)
    return chosen


def tools_block(text: str, recent_tools: list[str] = (), available: list[str] | None = None) -> str:
    """The per-message tools section: full detail for the likely groups, names only
    for the rest."""
    available = set(available or REGISTRY)
    # a group whose "this is talk about it" pattern matches is not offered at all - not
    # even by name: listed as "other tools", the model still reached for them ("organize
    # my thoughts" -> organize_files, "turn off the lights" -> screens_off). A tool he
    # used in the last turns stays (a follow-up is never talk).
    talk = [g for g in GROUPS if g.talk and g.talk.search(text) and not any(t in recent_tools for t in g.tools)]
    for g in talk:
        available -= set(g.tools)
    groups = [g for g in groups_for(text, recent_tools) if g not in talk]
    detailed = [t for g in groups for t in g.tools if t in available]
    # tools outside every group (added later, not routed yet) are always offered in full
    detailed += [t for t in sorted(available) if t not in BY_TOOL and t not in detailed]
    others = sorted(t for t in available if t not in detailed)
    parts = ["## Tools for this message"]
    # talk, and nothing else in it names a tool group ("...can you research repair shops?" does)
    only_talk = talk and not any(g.keywords.search(text) for g in GROUPS if g not in talk)
    if detailed and groups:
        parts.append(catalogue(detailed))
        parts += [g.rules for g in groups]
    elif only_talk:
        # with one tool hidden, the model reached for the next ("turn off the lights" ->
        # set_volume, "screen brightness is too low" -> system_status): talk is said plainly
        parts.append("This message is him talking about something, not asking you to operate anything: "
                     "answer in words (advice, sympathy, a question back). No tool.")
        return "\n".join(parts)
    elif detailed:
        parts.append(catalogue(detailed))
    else:
        parts.append("This message most likely needs no tool.")
    if others:
        parts.append(f"Other tools exist but this message doesn't call for them - don't use them unless he clearly asks: {', '.join(others)}.")
    return "\n".join(parts)
