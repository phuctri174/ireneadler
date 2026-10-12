"""Story mode: he is telling her about his life, and she is his friend, not his fixer.

An assistant hears "my coworker took credit for my slides" and starts drafting an
email to HR. A friend says "she did NOT." This module is the switch between those
two registers, made in code (like sentiment.py) so it does not depend on the model
noticing:

  read()      is this message a story - him recounting something that happened -
              rather than asking for something? Or a continuation of the story he
              was just telling ("and then she...", "right?!")?
  beat        what the story is doing to her as his friend: he was wronged (angry
              on his behalf), a twist (shocked), something sad, something lovely,
              something absurd - or he was the one in the wrong (a friend says so,
              gently)
  people      everyone he has mentioned this session, with how he described them,
              so "Trác" in the fourth message is the Trác from the first
  advice      whether he actually ASKED what to do. Only then may she advise; the
              reply guard (brain.StreamingReply) drops advice he didn't ask for

Stateless: everything is derived from his messages in the conversation, so a
history replayed by the evals reads exactly like a live session.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---- is it a story? ------------------------------------------------------------------

# someone did or said something: a subject, then a reporting or doing verb in the past
_SUBJECT = (
    r"(?:he|she|they|we|i|nobody|no\s+one|everyone|everybody|someone|somebody|my\s+\w+(?:\s+\w+)?|this\s+(?:guy|girl|dude|woman|man|person|kid|lady)|"
    r"the\s+(?:boss|manager|teacher|sensei|guy|girl|landlord|driver|waiter|waitress|neighbou?r)|[A-Z][\w'’]+)"
)
_DID = (
    r"(?:said|says|told|tells|asked|goes|went|was\s+like|is\s+like|yelled|shouted|texted|messaged|called|"
    r"replied|answered|laughed|cried|blamed|accused|ignored|ghosted|cancell?ed|forgot|lied|stole|took|"
    r"left|quit|showed\s+up|turned\s+up|walked\s+(?:in|out|off)|started|decided|tried|kept|"
    r"didn'?t|wouldn'?t|couldn'?t|refused|broke|dumped|kissed|slapped|snapped|posted|sent|"
    r"brought|made|got|had|gave|threw|ate|spilled|missed|won|lost|failed|passed|fell|tripped|"
    r"complained|bragged|admitted|apologi[sz]ed|interrupted|embarrassed|humiliated|"
    r"invited|uninvited|picked|chose|showed|copied|reported|scolded|shouted|screamed|"
    r"sat|stood|realised|realized|ended\s+up|found\s+out|noticed|saw|heard|met|ran\s+into|walked\s+into|came\s+(?:in|into|over|back)|"
    r"announced|confessed|showed\s+me|grabbed|pushed|hugged|visited)"
)
_NARRATIVE = re.compile(rf"\b{_SUBJECT}\s+(?:just\s+|actually\s+|literally\s+|then\s+|even\s+|still\s+|totally\s+)?{_DID}\b", re.I)

# how a story is opened or carried along
_STORY_OPENER = re.compile(
    r"\b(?:so\s+(?:today|yesterday|this\s+morning|last\s+night|tonight|at\s+work|in\s+class|at\s+practice|at\s+kendo)|"
    r"you\s+won'?t\s+believe|guess\s+what\s+\w+\s+(?:did|said)|story\s+time|"
    r"let\s+me\s+tell\s+you\s+(?:about|what)|i\s+have\s+to\s+tell\s+you|"
    r"(?:the\s+)?drama|spill(?:ing)?\s+the\s+tea|so\s+there'?s\s+this|"
    r"remember\s+(?:\w+|my\s+\w+)\s*\?|"
    r"(?:today|yesterday|this\s+morning|last\s+night|earlier)\s*,?\s+(?:at\s+\w+\s*,?\s+)?(?:my|this|the|he|she|they|we|i)\b)",
    re.I,
)
_CONTINUE = re.compile(
    r"^\W*(?:and\s+then|so\s+then|then|and|but|so|anyway\s+so|okay\s+so|like|and\s+like|"
    r"right\s*\?|exactly|i\s+know|ikr|seriously|honestly|literally|wait|oh\s+and|plus|"
    r"no\s+but|the\s+worst\s+part|the\s+best\s+part|and\s+the\s+thing\s+is|after\s+that|turns\s+out)\b"
    r"|\b(?:who\s+does\s+that|can\s+you\s+believe|isn'?t\s+that|right\s*\?\s*$|like\s+what\s*\?)",
    re.I,
)

# a request: work for her, not a story (wins over everything but an advice question)
_REQUEST = re.compile(
    r"^\W*(?:(?:hey\s+)?irene\W+)?(?:can\s+you|could\s+you|would\s+you|will\s+you|please|"
    r"open|close|show|find|search|look\s+up|google|play|pause|save|delete|move|copy|"
    r"write|read|send|set|make|create|build|run|start|turn|switch|draw|explain|tell\s+me\s+(?:about|how|what|why)|"
    r"what'?s\s+the|what\s+is|what\s+are|who\s+is|who\s+was|how\s+do|how\s+does|how\s+many|how\s+much|"
    r"when\s+is|where\s+is|why\s+is|why\s+does|remind|calculate|convert|translate|zoom|scroll)\b",
    re.I,
)

# work asked for anywhere in the message ("...she said 3pm, can you set a reminder?")
_ASKS_WORK = re.compile(
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:open|close|show|find|search|look|play|pause|save|"
    r"write|read|send|set|make|create|remind|put|draw|check|turn|switch|start|stop|get|pull|bring)\b"
    r"|\bremind\s+me\b|\bset\s+(?:a|an)\s+(?:timer|reminder|alarm)\b|\blook\s+(?:it|that|him|her)\s+up\b",
    re.I,
)

# a question about the world ("Who won the Ballon d'Or?"), not a story
_QUESTION = re.compile(r"^\W*(?:who|what|when|where|why|how|which|whose|is|are|was|were|do|does|did|can|could|will|would)\b[^.!]*\?\s*$", re.I)

# he asks for her advice: then, and only then, she gives it
_ADVICE_ASKED = re.compile(
    r"\b(?:what\s+(?:should|do|would|can)\s+i\s+(?:do|say|tell|text|reply)|what\s+would\s+you\s+(?:do|say)|"
    r"should\s+i\b|do\s+you\s+think\s+i\s+should|would\s+you\s+(?:have|do)|any\s+advice|"
    r"(?:give|need)\s+(?:me\s+)?(?:some\s+)?advice|how\s+(?:do|should|can)\s+i\s+(?:deal|handle|fix|talk|respond|reply|tell|get)|"
    r"help\s+me\s+(?:figure|decide|think|work\s+out|with\s+this)|what'?s\s+the\s+move|"
    r"was\s+i\s+(?:wrong|right|out\s+of\s+line|the\s+asshole|being)|am\s+i\s+(?:wrong|overreacting|crazy|the\s+asshole)|"
    r"tell\s+me\s+(?:honestly|the\s+truth)|be\s+honest)\b",
    re.I,
)

# advice, in her reply: what the guard drops when he never asked for it
ADVICE = re.compile(
    r"\b(?:you\s+(?:should|could|might\s+want\s+to|need\s+to|have\s+to|ought\s+to|must)|"
    r"(?:maybe|perhaps)\s+(?:you|try|talk|tell|just|ask|consider)|"
    r"(?:have|did)\s+you\s+(?:tried|considered|thought\s+about|talked\s+to)|why\s+don'?t\s+you|"
    r"i'?d\s+(?:suggest|recommend|advise)|i\s+(?:suggest|recommend|advise)|my\s+advice|"
    r"it\s+might\s+(?:help|be\s+worth|be\s+good)|it'?s\s+(?:worth|best\s+to|important\s+to)|"
    r"try\s+(?:to|talking|telling|asking|setting|being)|consider\s+\w+ing|"
    r"(?:talk|speak)\s+to\s+(?:her|him|them|your)\s+(?:about|directly|calmly)|"
    r"set\s+(?:some\s+)?boundaries|communicat(?:e|ion)\s+is\s+key|"
    r"if\s+i\s+were\s+you|the\s+best\s+(?:thing|way)\s+(?:to|is)|next\s+time,?\s+(?:you|try|just)|"
    r"(?:email|report\s+(?:it|her|him|them))\s+to\s+(?:hr|your)|go\s+to\s+hr|"
    r"take\s+a\s+deep\s+breath|focus\s+on\s+(?:yourself|what\s+you)|let\s+it\s+go|"
    r"^\W*(?:honestly\W+|okay\W+|so\W+)?(?:don'?t\s+let|tell\s+(?:him|her|them|your)|go\s+to\s+(?:your|the|hr)|call\s+(?:him|her|them)\s+out|"
    r"confront\s+(?:him|her|them)|stand\s+up\s+(?:to|for))|directly\s+(?:tell|confront|talk))\b",
    re.I,
)

# ---- the beat: what the story does to her ----------------------------------------------

# he was wronged: she is angry on his behalf
_WRONGED = re.compile(
    r"\b(?:blamed\s+me|yelled\s+at\s+me|shouted\s+at\s+me|screamed\s+at\s+me|took\s+(?:the\s+)?credit|"
    r"stole\s+my|ignored\s+me|ghosted\s+me|cancell?ed\s+on\s+me|stood\s+me\s+up|lied\s+(?:to\s+me|about)|"
    r"talk(?:ed|ing)\s+(?:shit\s+)?behind\s+my\s+back|threw\s+me\s+under\s+the\s+bus|left\s+me\s+out|"
    r"called\s+me\s+(?:a|an|stupid|lazy|useless|fat|ugly|dumb)|insulted|humiliated\s+me|"
    r"embarrassed\s+me\s+in\s+front|made\s+fun\s+of\s+me|laughed\s+at\s+me|mocked|"
    r"didn'?t\s+even\s+(?:say|thank|apologi[sz]e|invite|ask|tell)|never\s+(?:paid|gave)\s+(?:me\s+)?back|"
    r"cut\s+in\s+(?:line|front)|so\s+rude|was\s+rude|rude\s+to\s+me|disrespect\w*|"
    r"scolded\s+me|accused\s+me|uninvited\s+me|copied\s+my|reported\s+me|kicked\s+me\s+out|"
    r"on\s+purpose|cheated\s+on|cheated\s+me|ripped\s+me\s+off|scammed|"
    r"without\s+(?:knocking|asking|permission|telling\s+me)|didn'?t\s+do\s+(?:anything|a\s+thing|any\s+of\s+it)|did\s+(?:nothing|zero)|"
    r"(?:said|told\s+\w+(?:\s+\w+)?)\s+(?:that\s+)?(?:he|she|they)\s+did\s+(?:half|most|all|it)|took\s+all\s+the)\b",
    re.I,
)
# he was in the wrong: a friend tells him, gently
_HIS_FAULT = re.compile(
    r"\bi\s+(?:kind\s+of\s+|sort\s+of\s+|maybe\s+|might\s+have\s+|may\s+have\s+)?"
    r"(?:yelled\s+at|shouted\s+at|snapped\s+at|swore\s+at|ghosted|ignored|blocked|lied\s+to|stood\s+(?:her|him|them)\s+up|"
    r"called\s+(?:her|him|them)\s+(?:a|an|stupid|lazy|useless|an?\s+idiot)|"
    r"read\s+(?:her|his|their)\s+(?:texts|messages|phone|diary)|went\s+through\s+(?:her|his|their)\s+phone|"
    r"forgot\s+(?:my\s+\w+'?s|her|his|their|our)\s+(?:birthday|anniversary)|didn'?t\s+(?:show\s+up|reply\s+for\s+(?:a\s+week|days|weeks))|"
    r"skipped\s+(?:her|his|their)\s+(?:wedding|birthday|party|funeral))\b"
    r"|\bwas\s+(?:i|that)\s+(?:wrong|too\s+much|out\s+of\s+line|harsh|mean)\b"
    r"|\bmaybe\s+i\s+(?:overreacted|was\s+(?:wrong|harsh|mean|too\s+much))\b"
    r"|\bam\s+i\s+(?:the\s+asshole|wrong|overreacting)\b",
    re.I,
)
_SHOCK = re.compile(
    r"\b(?:you\s+won'?t\s+believe|out\s+of\s+nowhere|all\s+of\s+a\s+sudden|turns\s+out|in\s+front\s+of\s+everyone|"
    r"broke\s+up|dumped|quit\s+(?:on\s+the\s+spot|her\s+job|his\s+job|today)|got\s+fired|slapped|punched|"
    r"secretly|behind\s+(?:her|his|their)\s+back|engaged|getting\s+married|eloped|pregnant|cheating|caught\s+(?:him|her|them)|"
    r"asked\s+me\s+to\s+(?:give|be|do)\s+(?:the|a|her|his)|weeks?\s+ago\s+and|"
    r"walked\s+out|stormed\s+out|plot\s+twist|no\s+one\s+saw\s+(?:it|that)\s+coming|the\s+whole\s+(?:class|office|dojo|room))\b",
    re.I,
)
_SAD = re.compile(
    r"\b(?:cried|crying|in\s+tears|felt\s+(?:so\s+|really\s+)?(?:bad|awful|terrible|small|stupid|alone|left\s+out|invisible)|"
    r"nobody\s+(?:came|noticed|cared|showed)|no\s+one\s+(?:came|noticed|cared|showed)|left\s+out|lonely|"
    r"hurt\s+my\s+feelings|really\s+hurt|heartbroken|passed\s+away|"
    r"(?:my|our|his|her)\s+(?:\w+\s+)?(?:dog|cat|mom|mum|dad|grandma|grandpa|gran|friend|uncle|aunt|brother|sister|cousin|pet)\s+died|i\s+miss\s+(?:her|him|them)|"
    r"(?:didn'?t|did\s+not|doesn'?t)\s+(?:recogni[sz]e|remember)\s+me|forgot\s+who\s+i\s+(?:was|am)|i\s+felt\s+so\s+\w+)\b",
    re.I,
)
_DELIGHT = re.compile(
    r"\b(?:finally|said\s+yes|she\s+likes\s+me|he\s+likes\s+me|asked\s+me\s+out|won|got\s+(?:the|my|first|an?)\s+\w+|"
    r"complimented|praised\s+me|so\s+happy|so\s+proud|best\s+day|nailed\s+it|passed|promoted|"
    r"thanked\s+me|loved\s+it|cheered|clapped|ippon|beat\s+(?:him|her|them|my\s+\w+)|"
    r"(?:was|is)\s+the\s+best\s+(?:one|\w+)|best\s+\w+\s+(?:this|of\s+the)\s+(?:year|quarter|month|class|team)|"
    r"proud\s+of\s+me|said\s+i\s+(?:did|was)\s+(?:great|amazing|good))\b",
    re.I,
)
_ABSURD = re.compile(
    r"\b(?:lol|lmao|haha+|so\s+dumb|ridiculous|who\s+does\s+that|absolutely\s+unhinged|unhinged|"
    r"tripped|fell\s+(?:over|down|asleep)|spilled|wrong\s+(?:room|class|bus|person|lecture|train|house|door|meeting|building|floor|exam|seat)|"
    r"embarrassing|cringe|you\s+can'?t\s+make\s+this\s+up|in\s+(?:his|her)\s+pyjamas|accidentally)\b",
    re.I,
)

# the beat -> the reactions it calls for, best first (cues.json names)
BEAT_CUES: dict[str, tuple[str, ...]] = {
    "wronged": ("fuming", "headShake", "shocked"),
    "his_fault": ("headTilt", "amused", "fingerWag"),
    "shock": ("shocked", "surprised", "starryEyed"),
    "sad": ("sad", "concerned"),
    "delight": ("excitedBounce", "starryEyed", "happy"),
    "absurd": ("giggle", "amused", "dizzy"),
    "following": ("listenClose", "thinking", "curious", "headTilt"),
}

# how each beat asks her to be, as his friend - the feel, never lines to say
BEAT_GUIDANCE: dict[str, str] = {
    "wronged": (
        "Someone did him wrong. Be on his side, out loud - indignant FOR him (\"she did NOT\", \"excuse me?\"). "
        "Never ask what HE did to deserve it."
    ),
    "his_fault": (
        "In this bit HE was the one out of line, and a real friend says so: your first line calls "
        "it, lightly and with affection - say back to him exactly what HE did, the bad bit in capitals, "
        "with a raised eyebrow (\"You did WHAT to him?\", \"Okay, that one's on you, Mister Tri.\"), then ask "
        "what happened next. Not a plain \"Seriously?\" - name what he did. Never a lecture, never what he "
        "should have done."
    ),
    "shock": "A twist. Jaw on the floor - react to the twist itself (\"no WAY\", \"wait, back up\").",
    "sad": "This one stings. Soften: a quiet, warm line that you're sorry, no silver lining, then gently ask.",
    "delight": "Good stuff happened. Be thrilled with him - big, genuine, then ask for the best part.",
    "absurd": "It's absurd. Laugh with him ([laugh] fits), then ask what happened next.",
    "following": "You're following along. Keep him going: a tiny reaction and a question about what happened.",
}


# ---- people -------------------------------------------------------------------------------

_ROLES = (
    "boss|manager|supervisor|coworker|co-worker|colleague|teammate|classmate|roommate|flatmate|housemate|"
    "friend|best friend|bestie|girlfriend|boyfriend|ex|crush|wife|husband|partner|"
    "mom|mum|mother|dad|father|sister|brother|cousin|aunt|uncle|grandma|grandpa|"
    "teacher|professor|lecturer|sensei|coach|neighbour|neighbor|landlord|senpai|kohai|tutor|student|intern|client|"
    "date|mate|buddy"
)
_ROLE_NAME = re.compile(rf"\bmy\s+((?:best\s+)?(?:{_ROLES}))\s*,?\s+([A-ZÀ-Ỹ][\w'’]+)", re.U)
_NAME_ROLE = re.compile(rf"\b([A-ZÀ-Ỹ][\w'’]+)\s*,?\s+(?:is\s+)?(?:my|our)\s+((?:best\s+)?(?:{_ROLES}))\b", re.U)
_BARE_ROLE = re.compile(rf"\bmy\s+((?:best\s+)?(?:{_ROLES}))\b", re.I)
_CAPITAL = re.compile(r"(?<![\w'’])([A-ZÀ-Ỹ][a-zà-ỹ'’]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+)?)", re.U)

# capitalised words that are not people
_NOT_NAMES = {
    "i", "i'm", "i've", "i'd", "i'll", "irene", "mister", "tri", "sir", "so", "and", "but", "then", "okay", "ok", "oh",
    "well", "the", "a", "an", "he", "she", "they", "we", "it", "this", "that", "my", "his", "her", "their", "our",
    "you", "your", "like", "literally", "honestly", "seriously", "anyway", "wait", "no", "yes", "yeah", "yep", "nope",
    "today", "yesterday", "tonight", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "god", "omg", "lol", "lmao", "hr", "ok", "guess", "remember", "after", "before",
    "what", "who", "why", "how", "when", "where", "which", "is", "was", "are", "did", "do", "does", "can", "could",
    "would", "should", "not", "never", "also", "plus", "even", "just", "right", "exactly", "because", "if",
    "kendo", "keiko", "dojo", "men", "kote", "do", "english", "vietnamese", "vietnam", "hanoi", "saigon", "japan",
    "japanese", "google", "zalo", "facebook", "instagram", "tiktok", "messenger", "discord", "teams", "slack",
    "python", "windows", "chrome", "youtube", "christmas", "tet", "story", "drama", "dude", "bro", "man", "girl",
    "ugh", "wow", "hey", "hi", "hello", "dear", "hmm", "um", "uh", "well", "now", "there", "here", "first", "then",
}


def _fold(name: str) -> str:
    """A name compared the way he says it: Whisper may or may not write the
    diacritics (Trác / Trac), so both are the same person."""
    plain = unicodedata.normalize("NFKD", name)
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip("'’")


@dataclass
class Person:
    name: str
    role: str = ""
    mentions: int = 0
    # what he said about them, his words, the latest first (short clauses)
    said: list[str] = field(default_factory=list)
    # "he" / "she" / "they", from his own words about them ("" until he says)
    pronoun: str = ""


_HE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)
_ROLE_PRONOUN = {
    "girlfriend": "she", "wife": "she", "mom": "she", "mum": "she", "mother": "she", "sister": "she", "aunt": "she",
    "grandma": "she", "boyfriend": "he", "husband": "he", "dad": "he", "father": "he", "brother": "he", "uncle": "he",
    "grandpa": "he",
}


def _pronoun(text: str) -> str:
    he, she = bool(_HE.search(text)), bool(_SHE.search(text))
    return "he" if he and not she else "she" if she and not he else ""


def _clause(text: str, name: str) -> str:
    """The bit of his message about this person: the sentence that names them."""
    key = _fold(name)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if key in {_fold(w) for w in re.findall(r"[\wÀ-ỹ'’]+", sentence)}:
            words = sentence.strip().split()
            return " ".join(words[:16]) + ("..." if len(words) > 16 else "")
    return ""


def people(messages: list[str]) -> list[Person]:
    """Everyone he has named, in order of first mention: the same name (with or
    without its diacritics) is the same person, and "my boss" named once is that
    person whenever he says "my boss" again."""
    found: dict[str, Person] = {}
    roles: dict[str, str] = {}  # role -> folded name

    def note(name: str, text: str, role: str = "") -> None:
        key = _fold(name)
        if key in _NOT_NAMES or len(key) < 2:
            return
        p = found.get(key)
        if p is None:
            p = found[key] = Person(name)
        if role and not p.role:
            p.role = role.lower()
            roles[role.lower()] = key

    last: str | None = None  # the person he spoke of most recently
    for text in messages:
        counted: set[str] = set()
        for m in _ROLE_NAME.finditer(text):
            note(m.group(2), text, m.group(1))
        for m in _NAME_ROLE.finditer(text):
            note(m.group(1), text, m.group(2))
        for m in _CAPITAL.finditer(text):
            name = m.group(1)
            first = name.split()[0]
            start = m.start()
            sentence_start = start == 0 or bool(re.search(r"[.!?]\s*$|^\W*$", text[:start]))
            key = _fold(first)
            if key in _NOT_NAMES:
                continue
            # a capital at a sentence start is a name only if it's known already, or
            # it is doing something ("Trác texted me")
            if sentence_start and key not in found and not re.match(rf"{re.escape(first)}\s+(?:just\s+|then\s+)?{_DID}\b", text[start:], re.I):
                continue
            note(first, text)
        # "my boss" again: the boss he named before
        for m in _BARE_ROLE.finditer(text):
            key = roles.get(m.group(1).lower())
            if key:
                counted.add(key)
        for key, p in found.items():
            if re.search(rf"(?<![\w]){re.escape(p.name)}(?![\w])", text) or _fold(p.name) in {_fold(w) for w in re.findall(r"[\wÀ-ỹ'’]+", text)}:
                counted.add(key)
        # his pronoun for them: from a message about one person only ("Trác... he"),
        # or about nobody named, meaning the last one ("what should I do about him?")
        about = counted if counted else ({last} if last else set())
        if len(about) == 1:
            key = next(iter(about))
            said = _pronoun(text)
            if said and not found[key].pronoun:
                found[key].pronoun = said
        for key in counted:
            p = found[key]
            last = key
            if not p.pronoun and p.role in _ROLE_PRONOUN:
                p.pronoun = _ROLE_PRONOUN[p.role]
            p.mentions += 1
            clause = _clause(text, p.name) or (text.strip()[:90] if p.role and re.search(rf"\bmy\s+{re.escape(p.role)}\b", text, re.I) else "")
            if clause and clause not in p.said:
                p.said.insert(0, clause)
                del p.said[3:]
    return list(found.values())


# ---- the read --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tale:
    """He is telling her a story (or carrying on with one)."""

    beat: str
    advice_asked: bool
    continuing: bool
    cast: tuple[Person, ...] = ()
    # everyone he has named is a man and he has never said "she": her "she"/"her"
    # can only be the model guessing a gender from a name (gemma does, for Trác)
    men_only: bool = False

    @property
    def cues(self) -> tuple[str, ...]:
        return ("thinking", "firedUp", "headTilt") if self.advice_asked else BEAT_CUES[self.beat]

    def section(self, openers: list[str] | None = None) -> str:
        """`openers`: how her last few replies began - never again this session."""
        people_right = "Get his people right: he, she, or they, as he said."
        if self.advice_asked:
            lines = [
                "## He's asking your advice about his story",
                "",
                "He told you something from his life and now he is ASKING YOU what he should do (or "
                "whether he was wrong). You're his close friend, so answer it: two or three spoken "
                "sentences of real, concrete advice - what you would actually do, honest and on his "
                f"side (if he was in the wrong, say so kindly). No lists, no HR-speak, no tools. {people_right}",
                f"Open with <cue>{self.cues[0]}</cue> (or <cue>{self.cues[1]}</cue>).",
            ]
        else:
            lines = [
                "## He's telling you a story",
                "",
                "He is recounting something from his life - not asking you for anything. You are his "
                "close friend hearing it, not an assistant. React like a friend: short, big, honest "
                "interjections (\"no way\", \"she did NOT\", \"okay that's actually insane\", \"wait, back up\"), "
                "a line or two at most, then ONE follow-up question about the story itself - who, what "
                "happened next, what did he say, how did that go. Take his side.",
                "Your first words react to the SPECIFIC thing that happened - name it, with feeling "
                "(\"Your own SLIDES?!\", \"At grandma's party?!\", \"He said that to your FACE?\") - never a "
                f"generic opener like \"Seriously?\" or \"Oh wow\". {people_right}",
                "Do NOT fix it. No advice, no suggestions, no \"you should\", \"maybe try\", \"have you "
                "considered\" - he didn't ask. No tools, no drawing, no summary of what he said.",
                f"This bit: {BEAT_GUIDANCE[self.beat]} Open with <cue>{self.cues[0]}</cue> (or <cue>{self.cues[1]}</cue>).",
                "Shape: <speak><cue>reaction</cue>Your reaction! <cue>curious</cue>Then a real question about what happened?</speak> "
                "- the question is not optional; a friend wants the rest of the story.",
            ]
            if openers:
                lines.append("Already used this session - do not open with any of these again: " + " / ".join(f'"{o}"' for o in openers))
        if self.cast:
            lines.append("")
            lines.append(
                "People in his story so far (this session) - the same name is the same person; "
                "remember what he told you about them and bring it back when it fits:"
            )
            for p in self.cast:
                role = f" (his {p.role})" if p.role else ""
                said = f": \"{p.said[0]}\"" if p.said else ""
                pronoun = {"he": " - a man: he/him", "she": " - a woman: she/her"}.get(p.pronoun, "")
                lines.append(f"- {p.name}{role}{pronoun}, mentioned {p.mentions}x{said}")
        return "\n".join(lines)


def _beat(text: str) -> str:
    if _HIS_FAULT.search(text):
        return "his_fault"
    if _WRONGED.search(text):
        return "wronged"
    if _SAD.search(text):
        return "sad"
    if _SHOCK.search(text):
        return "shock"
    if _ABSURD.search(text):
        return "absurd"
    if _DELIGHT.search(text):
        return "delight"
    return "following"


def is_story(text: str) -> bool:
    """He is recounting something, not asking for something."""
    said = (text or "").strip()
    if not said:
        return False
    if _REQUEST.search(said) and not _STORY_OPENER.search(said):
        return False
    if _ASKS_WORK.search(said) or _QUESTION.match(said):
        return False
    narrative = len(_NARRATIVE.findall(said))
    opener = bool(_STORY_OPENER.search(said))
    # one clear "she said/he did" plus anything story-like, or two of them, or an opener
    return opener or narrative >= 2 or (narrative >= 1 and (len(said.split()) >= 7 or _beat(said) != "following"))


def read(text: str, earlier: list[str] | None = None) -> Tale | None:
    """Story mode for this message, or None. `earlier`: his previous messages this
    session, oldest first (tool results and notes excluded)."""
    said = (text or "").strip()
    earlier = [m for m in (earlier or []) if m and not m.startswith("[")]
    advice = bool(_ADVICE_ASKED.search(said))
    story = is_story(said)
    continuing = False
    if not story:
        recent = earlier[-2:]
        told = any(is_story(m) for m in recent)
        if told and not ((_REQUEST.search(said) or _ASKS_WORK.search(said)) and not advice) and (
            _CONTINUE.search(said) or advice or bool(_NARRATIVE.search(said)) or bool(_beat(said) != "following")
        ):
            story = continuing = True
    if not story:
        return None
    beat = _beat(said)
    if beat == "following":
        # "and then he did it again": the story's beat carries on until a new one
        for m in reversed(earlier[-3:]):
            if is_story(m) and _beat(m) != "following":
                beat = _beat(m)
                break
    cast = people([*earlier, said])
    # only the people this story is about: everyone named in the session, most
    # mentioned first, at most six
    cast.sort(key=lambda p: -p.mentions)
    named = [p.pronoun for p in cast if p.pronoun]
    men_only = bool(named) and all(n == "he" for n in named) and not any(_SHE.search(m) for m in [*earlier, said])
    return Tale(beat, advice, continuing, tuple(cast[:6]), men_only)


def is_advice(sentence: str) -> bool:
    """A sentence of her reply that tells him what to do."""
    return bool(ADVICE.search(sentence or ""))


# her reaction when every sentence the model wrote was advice he didn't ask for:
# a friend's line and a question back (never twice the same in a row)
FALLBACKS: dict[str, tuple[str, ...]] = {
    "wronged": ("Excuse me?! No. Then what happened?", "Okay, that is NOT okay. What did you say?", "Wow. Unbelievable. And then?"),
    "his_fault": ("Hmm... okay, that one's a little on you. What happened after?", "Ooh. Mister Tri. ...And then what?"),
    "shock": ("No WAY. Wait - back up.", "Shut up! What happened next?", "Wait, what?! Then what?"),
    "sad": ("Oh no... I'm sorry. How are you feeling about it?", "That really stings. What happened after?"),
    "delight": ("Stop it! Tell me everything.", "Yes! What was the best part?"),
    "absurd": ("[laugh] No! Then what?", "Okay that's actually insane. Keep going."),
    "following": ("Mm-hm. And then?", "Wait, who's that?", "Okay... then what happened?"),
}
_last_fallback = ""


def fallback(beat: str) -> str:
    global _last_fallback
    import random

    options = [line for line in FALLBACKS.get(beat, FALLBACKS["following"]) if line != _last_fallback]
    _last_fallback = random.choice(options)
    return _last_fallback


def opener_key(sentence: str) -> str:
    """A reply's first sentence, compared loosely (case, punctuation, diacritics)."""
    return re.sub(r"[^a-z ]", "", _fold(sentence)).strip()


# after "her", a word that makes it an object ("tell her about") rather than a
# possessive ("her slides")
_OBJECT_NEXT = {
    "a", "an", "the", "to", "in", "on", "at", "about", "for", "with", "and", "or", "out", "up", "down", "off", "that",
    "this", "what", "how", "if", "so", "but", "back", "again", "directly", "privately", "now", "first", "later", "too",
    "yet", "know", "from", "by", "into", "over", "away", "just", "please", "anything", "something",
}


def men_pronouns(sentence: str) -> str:
    """Her sentence with she/her about a man put right (see Tale.men_only)."""

    def case(word: str, like: str) -> str:
        return word.capitalize() if like[0].isupper() else word

    def her(m: re.Match) -> str:
        nxt = (m.group(2) or "").lower()
        word = "him" if not nxt or nxt in _OBJECT_NEXT else "his"
        return case(word, m.group(1)) + (m.group(0)[len(m.group(1)):])

    s = re.sub(r"\b(she)\b", lambda m: case("he", m.group(1)), sentence, flags=re.I)
    s = re.sub(r"\b(herself)\b", lambda m: case("himself", m.group(1)), s, flags=re.I)
    s = re.sub(r"\b(hers)\b", lambda m: case("his", m.group(1)), s, flags=re.I)
    s = re.sub(r"\b(her)\b(?=\W*(\w*))", her, s, flags=re.I)
    return s



# a follow-up he can answer, when her reply had none: the story goes on
FOLLOW_UPS: dict[str, tuple[str, ...]] = {
    "wronged": ("What did you say?", "Did anyone back you up?", "And they just got away with it?", "What happened after?", "How did you not lose it?"),
    "his_fault": ("And what happened after?", "How did they take it?", "Did you make up?", "What did they say?"),
    "shock": ("Then what?", "How did everyone react?", "Wait, how did you find out?", "What happened next?"),
    "sad": ("How are you feeling about it now?", "What happened after?", "Did anyone say anything?"),
    "delight": ("What was the best part?", "Then what?", "How did you feel?", "Tell me everything - what happened next?"),
    "absurd": ("Then what happened?", "Did anyone see?", "How did it end?", "What did everyone do?"),
    "following": ("And then?", "What happened next?", "Who was that?", "How did that go?"),
}
_WH = re.compile(r"^\W*(?:what|who|how|why|when|where|which|did|do|does|was|were|is|are|and\s+then|then|tell\s+me)\b", re.I)
_last_question = ""


def asks_back(said: list[str]) -> bool:
    """Her reply asks him something about the story: a question after her first
    reaction, or a reaction that is itself a real question ("What did he say?") -
    not just an echo ("Your own slides?!")."""
    if not said:
        return False
    if any(s.rstrip().endswith("?") for s in said[1:]):
        return True
    return said[0].rstrip().endswith("?") and bool(_WH.match(said[0]))


def follow_up(beat: str) -> str:
    global _last_question
    import random

    options = [q for q in FOLLOW_UPS.get(beat, FOLLOW_UPS["following"]) if q != _last_question]
    _last_question = random.choice(options)
    return _last_question
