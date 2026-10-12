"""How he said it, not what he asked for.

The model is good at answering and careless about feelings: told to fetch a fact
it will fetch the fact and walk straight past the fact that he was teasing it, or
tired, or pleased. So the read is made here, in code, and handed to it with the
message - the same way the router hands it the tools it may need.

Two questions, both cheap and both regex:

  read       bad news, big news, teasing, praising, complaining, joking,
             frustrated, curious, or neutral - what the message is doing to her,
             emotionally, and the reaction that shows it (MOOD_CUES)
  smalltalk  whether this is conversation rather than a task. Small talk is a
             first-class path: "how are you" is not a request to do anything, and
             she must not turn it into work.

Deliberately not a model call. It runs on every message, it must not cost a
round trip, and a wrong guess should be cheap to read and cheap to fix - a line
in a pattern here rather than a retrained anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Order matters: the first that matches wins, so the sharper reads come first.
# Each pattern is what he would actually type, not a thesaurus.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "bad_news",
        re.compile(
            r"\b(died|passed away|funeral|put down|got (fired|laid off|sacked|dumped|rejected)|"
            r"lost my (job|dog|cat|grandma|grandpa|gran|mum|mom|dad|friend|wallet|phone)|"
            r"broke up|split up|didn'?t get (the|in|it|that|my)|i failed|failed (my|the)|"
            r"(bad|sad|terrible|awful) news|in (the )?hospital)\b",
            re.I,
        ),
    ),
    (
        "surprising",
        re.compile(
            r"\b(guess what|you won'?t believe|i (got|landed) (the|a|my) (job|offer|place|promotion|internship)|"
            r"i (won|passed|did it|made it|got in)|we won|got promoted|i'?m (engaged|getting married|pregnant)|"
            r"(big|great|amazing|good) news)\b",
            re.I,
        ),
    ),
    (
        "teasing",
        re.compile(
            r"\b(cringy|cringe|corny|cheesy|lame|silly|goofy|dork(y)?|show ?off|"
            r"(you'?re|that'?s|that was|this is|a bit|so|very|kinda|kind of) (weird|odd|strange|awkward|dramatic|extra))\b"
            # "a bit much", not "so much easier"
            r"|\b(a bit|a little|bit|way too|too|that'?s|that was) much\b(?! (better|easier|more|nicer|faster|appreciated))"
            r"|\b(sure(,| ) ?(you are|you do|jan)|if you say so|okay then|whatever you say)\b"
            r"|\bnot (that )?(impressive|great|amazing)\b"
            r"|\b(show|showing) off\b",
            re.I,
        ),
    ),
    (
        "joking",
        re.compile(
            r"\b(haha+|hehe+|lol|lmao|rofl|:\)|:-\)|:d|xd)\b"
            r"|\b(just kidding|only joking|i'?m joking|jk|kidding)\b"
            r"|\b(knock knock|tell me a joke|say something funny)\b"
            # a joke told to her: the riddle, then the punchline
            r"|\b(why did|why do|why don'?t|what do you call|how do you|what did the)\b[^?]*\?\s*\S+(\s+\S+)+",
            re.I,
        ),
    ),
    (
        "praising",
        re.compile(
            r"\b(good|great|nice|well|lovely|excellent|brilliant|perfect|amazing|awesome|clever|smart|impressive) "
            r"(job|work|one|girl|going|answer|catch|find|idea|call)\b"
            r"|\b(thank you|thanks|ta|cheers)\b"
            r"|\b(you'?re (the best|amazing|brilliant|clever|good at|great)|love (it|that|you)|"
            r"i'?m impressed|that('?s| was) (perfect|brilliant|exactly right|spot on|really good))\b"
            r"|\bwell done\b|\bgood (girl|one)\b",
            re.I,
        ),
    ),
    (
        "frustrated",
        re.compile(
            r"\b(for (god'?s|f\w*k'?s|christ'?s) sake|oh come on|come ON|seriously\?|"
            r"stop it|forget it|never ?mind|ugh|argh|urgh|damn it|dammit)\b"
            r"|\b(that'?s (not|wrong)|you (keep|always) (getting|get|got) (it|that) wrong|"
            r"no,? (that'?s|i said|listen)|i (already )?(told|said) you)\b"
            r"|\b(wrong again|not what i (asked|said|meant))\b",
            re.I,
        ),
    ),
    (
        "complaining",
        re.compile(
            r"\b((i'?m|i am|feeling)( \w+){0,2} (tired|exhausted|knackered|shattered|stressed|"
            r"fed up|sick of|done|struggling|stuck|lost|sad|ill|sick|unwell|worn out|burnt out))\b"
            r"|\b(long day|rough day|bad day|hard day|terrible day|awful day|can'?t sleep|didn'?t sleep|no sleep)\b"
            r"|\b(hurts?|aching|headache|my back|my neck|my eyes)\b"
            r"|\b(nothing'?s working|everything'?s broken|it (keeps|won'?t) (crashing|breaking|working))\b",
            re.I,
        ),
    ),
    (
        # two or more vague references in one breath: she can't know what he means
        "unclear",
        re.compile(
            r"(?:the thing|that thing|thingy|the other (?:one|thing)|from before|like last time|you know the|whatsit|whatchamacallit)"
            r".*(?:the thing|that thing|thingy|the other (?:one|thing)|from before|like last time|you know the|whatsit|whatchamacallit)",
            re.I,
        ),
    ),
    (
        "curious",
        re.compile(
            r"\b(i wonder|wonder (if|why|how|what)|how (come|does|do) .*\?|"
            r"what'?s (it like|that like)|do you (ever|actually|really) )\b"
            r"|\b(what do you (think|reckon)|any thoughts|your opinion|would you )\b",
            re.I,
        ),
    ),
)

# Conversation rather than a task: greetings, how-are-yous, reactions to her,
# asides about him. If one of these matches and nothing asks for work, she talks.
_SMALL_TALK = re.compile(
    r"^\W*(hi|hey|hello|yo|morning|good morning|good afternoon|good evening|hiya)\b"
    r"|\bhow are you\b|\bhow'?s it going\b|\byou (alright|ok|okay)\b|\bhow have you been\b"
    r"|\bwhat (are|were) you (doing|up to)\b|\bare you (bored|okay|ok|alright|busy|there)\b"
    r"|\b(miss(ed)? (me|you)|talk to me|say something|keep me company)\b"
    r"|\b(good ?night|goodnight|see you|bye|talk later|i'?m off)\b"
    r"|\b(you'?re funny|you'?re (so )?(cute|sweet|silly)|i like you|do you like me)\b",
    re.I,
)

# Anything that clearly asks for work overrides the small-talk read. Note that
# being a question is NOT on this list: "how are you" and "what are you doing"
# are questions and they are pure conversation. Only asking for work is work.
_TASK = re.compile(
    r"\b(open|close|show|find|search|look up|google|play|pause|stop|save|delete|move|copy|"
    r"write|read|send|set|make|create|build|run|start|volume|mute|screenshot|zoom|scroll|"
    r"what time|what'?s the time|remind|calculate|convert|translate)\b",
    re.I,
)

# "anyway", "by the way", "forget that" - he has moved on, and she should too
_TOPIC_SHIFT = re.compile(
    r"^\W*(anyway|anyhow|by the way|btw|changing the subject|on another note|"
    r"forget (that|it|about it)|never ?mind that|different question|unrelated)\b"
    r"|\b(anyway|by the way)\b[,\s-]",
    re.I,
)

# What each read asks of her, in her own terms. This is the whole point: the model
# is told how to BE, not what to say.
GUIDANCE: dict[str, str] = {
    "teasing": (
        "He is teasing you. Take it - play along, sulk theatrically, or fire back. "
        "Never defensive, never apologise for having fun, never explain the joke."
    ),
    "praising": (
        "He is pleased with you. Take the compliment - proud, or pleased and a little "
        "sheepish - in one short line, then move on. No gushing, no 'thank you so much'."
    ),
    "complaining": (
        "Something is wearing on him. Notice it FIRST, warmly and briefly, before "
        "anything else. Do not fix it unless he asks; sympathy beats advice here."
    ),
    "frustrated": (
        "He is fed up, possibly with you. Short and warm. No jokes, no cues that "
        "celebrate, no defending yourself. If you got it wrong, own it in three words "
        "and put it right."
    ),
    "joking": "He is joking. Play along - laugh out loud ([laugh]), match his register, land one line, do not over-explain.",
    "curious": "He is curious rather than tasking you. Be curious back: answer, then wonder with him.",
    "unclear": "He's being vague and you can't tell what he means. Don't guess - ask one short question to pin it down.",
    "surprising": (
        "He has big news. React BIG and first - a gasp, genuine delight - before anything "
        "else, then ask him about it."
    ),
    "bad_news": (
        "He has had bad news. Soften: slow down, say you're sorry simply and warmly, and "
        "ask gently. No jokes, no silver linings, no fixing."
    ),
}

# The emotional moments get a big, visible reaction that fits, not whatever the
# model happened to write: a joke gets a laugh (with its sound), teasing a sulk, a
# compliment a sheepish one, big news starry eyes, bad news a droop. The reply opens
# with one of these (the first that didn't just play); brain.StreamingReply enforces it.
MOOD_CUES: dict[str, tuple[str, ...]] = {
    "joking": ("giggle", "wink"),
    "teasing": ("sulking", "embarrassed"),
    "praising": ("sheepish", "embarrassed", "heartHands"),
    "surprising": ("starryEyed", "excitedBounce"),
    "bad_news": ("sad", "concerned"),
    "complaining": ("concerned", "sad"),
    "frustrated": ("sheepish", "concerned"),
    "curious": ("headTilt", "curious"),
    "unclear": ("confused", "headTilt"),
}


@dataclass(frozen=True)
class Read:
    """How his message landed, and what that asks of her."""

    mood: str
    smalltalk: bool
    topic_shift: bool

    @property
    def guidance(self) -> str:
        return GUIDANCE.get(self.mood, "")

    @property
    def cues(self) -> tuple[str, ...]:
        """The reactions this moment calls for, best first (empty when neutral)."""
        return MOOD_CUES.get(self.mood, ())

    def section(self) -> str:
        """The block that goes to the model with his message, or "" when there is
        nothing worth saying - a plain task in a plain mood needs no coaching."""
        lines = []
        if self.guidance:
            lines.append(f"How he said it: {self.mood.replace('_', ' ')}. {self.guidance}")
        if self.cues:
            lines.append(f"Show it: open with <cue>{self.cues[0]}</cue> (or <cue>{self.cues[-1]}</cue>).")
        if self.smalltalk:
            lines.append(
                "This is conversation, not a task. Talk with him - do not call a tool, "
                "do not turn it into work, and do not offer to do anything unless he asks."
            )
        if self.topic_shift:
            lines.append(
                "He has changed the subject. Let the old one go without a word about it - "
                "no 'anyway', no summarising what you were doing - and follow him."
            )
        if not lines:
            return ""
        return "## How he said it\n\n" + "\n".join(lines)


def read(text: str) -> Read:
    """Classify one message from him. Never raises; neutral when nothing matches."""
    said = (text or "").strip()
    mood = "neutral"
    for name, pattern in _PATTERNS:
        if pattern.search(said):
            mood = name
            break
    chatty = bool(_SMALL_TALK.search(said)) and not _TASK.search(said)
    return Read(mood=mood, smalltalk=chatty, topic_shift=bool(_TOPIC_SHIFT.search(said)))
