# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
"""Stakes on a game of rock-paper-scissors: what he bet, held for the game, and the
consequence the CODE's outcome maps to.

The split is the chess one (chess_game.py: the engine decides, she talks): the
outcome is rps.py's - her sealed throw against the classifier's read of his - and
the model never judges who won. The model does exactly two things here:

  1. PARSE   his words at game start into Stakes {win, lose, draw, best_of}. What it
             returns is checked before anything is held: every word of a consequence
             must be one HE said (no invented stakes), win and lose must sit in the
             clauses he said them in (a swapped pair is caught), both must be there.
             Anything off and she asks - she never guesses. And she reads the parsed
             stakes back and waits for his yes before the count (app.py).
  2. NARRATE her reaction to the outcome - written ahead of time, while he gets
             ready, and checked: a short reaction, no consequence of any side, no throw,
             never the opposite result. The consequence sentence after it is ALWAYS the
             code's (consequence_sentence). A reaction that fails is dropped for a
             template; with no model at all, the templates say the same thing.

consequence(stakes, outcome) is the only place an outcome becomes a consequence.
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Awaitable, Callable

log = logging.getLogger("irene.rps")

# he is putting something on it: "if I win...", "loser buys...", "bet you...", "stakes"
_STAKE_WORDS = re.compile(
    r"\bif\s+(?:i|you)\s+(?:win|won|lose|lost|beat|draw|tie)\b|\b(?:loser|winner)\b|\bwhoever\s+(?:wins|loses)\b"
    r"|\b(?:bet|wager|stakes?|on\s+the\s+line)\b|\bfor\s+who(?:ever)?\b",
    re.I,
)
_BEST_OF_3 = re.compile(r"\bbest\s+(?:of|out\s+of)\s+(?:three|3)\b|\b(?:two|2)\s+out\s+of\s+(?:three|3)\b|\bfirst\s+to\s+(?:two|2)\b", re.I)

# words that carry no meaning of their own in a consequence - pronouns, helpers,
# filler: what is left must all be words he said
_GLUE = set(
    """i you me my your mine yours we us our he she it they them their irene a an the to of for and or but
    is am are be been was were will would shall should have has had do does did must got get gets getting
    has have then so that this just also too some any one with on in at by up as if when then
    can could may might let lets let's i'll you'll i'm you're i've you've gotta gonna want wants
    has to have to need needs""".split()
)


def mentions(text: str) -> bool:
    """He has put something on this game (worth parsing)."""
    return bool(_STAKE_WORDS.search(text or ""))


def best_of(text: str) -> int:
    return 3 if _BEST_OF_3.search(text or "") else 1


@dataclass
class Stakes:
    """What happens, from HIS side: `win` if he wins, `lose` if he loses, `draw` if he
    said what a draw means (None: a draw is replayed with the same stakes). Each is a
    short phrase as Irene says it to him ("you study computer science")."""

    win: str
    lose: str
    draw: str | None = None
    best_of: int = 1
    said: str = ""
    parsed_at: str = ""
    confirmed_at: str = ""

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Ask:
    """The stakes can't be held yet - she asks this instead of guessing."""

    kind: str  # "missing" | "missing_win" | "missing_lose" | "unclear"
    why: str
    partial: dict | None = None


def consequence(stakes: Stakes, outcome: str) -> str | None:
    """THE mapping: the code's outcome ("him" - he won, "her" - she won, "draw") to
    the consequence he stated for it. None: a draw he set nothing for."""
    return {"him": stakes.win, "her": stakes.lose, "draw": stakes.draw}[outcome]


# ---- parsing -----------------------------------------------------------------------------------------


def parse_messages(said: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "He is about to play rock-paper-scissors with Irene (\"you\" in his words is Irene). Find the stakes he "
                "stated and QUOTE them. Reply with JSON only:\n"
                '{"he_wins": quote|null, "he_loses": quote|null, "draw": quote|null, "loser_does": quote|null, "winner_does": quote|null}\n'
                "- he_wins: what happens if HE wins; he_loses: if HE loses. \"if you win\" (Irene wins) means he loses.\n"
                "- loser_does / winner_does: a consequence for whoever loses or wins, either of them (\"loser buys tea\" -> "
                "loser_does: \"buys tea\"; \"for who picks the film\" -> winner_does: \"picks the film\").\n"
                "- draw: ONLY if he said what a draw or tie means.\n"
                "- Each quote is copied EXACTLY, word for word, from his message: only the consequence, without the "
                "\"if I win\" part. Anything he did not say is null. Never write a word he didn't say."
            ),
        },
        {"role": "user", "content": said},
    ]


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _GLUE and len(w) > 1]


def _said(word: str, heard: list[str]) -> bool:
    """`word` is one he said - or the same word in another form (study/studies/studying,
    buy/buys)."""
    stem = word[:5] if len(word) > 5 else word
    return any(
        h == word
        or (len(stem) >= 4 and h.startswith(stem))
        or (len(h) >= 4 and word.startswith(h[:5]))
        or (len(word) >= 3 and h.startswith(word) and len(h) - len(word) <= 3)
        or (len(h) >= 3 and word.startswith(h) and len(word) - len(h) <= 3)
        for h in heard
    )


# his voice -> hers, word by word: his "I" is "you" to her; his "you" (Irene) is "I"/"me"
_HIS_TO_HERS = {"i": "you", "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "i'm": "you're",
                "i'll": "you'll", "i've": "you've", "i'd": "you'd", "your": "my", "yours": "mine", "yourself": "myself",
                "you're": "I'm", "you'll": "I'll", "you've": "I've", "you'd": "I'd", "irene's": "my"}
# after her "I", a verb drops the third person: "Irene picks" -> "I pick"
_THIRD = {"has": "have", "does": "do", "is": "am", "goes": "go"}
_CLAUSE_START = {"", "and", "then", "so", "or", "but"}


def _bare(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


def _first_person(verb: str) -> str:
    if verb in _THIRD:
        return _THIRD[verb]
    if verb.endswith("ies") and len(verb) > 4:
        return verb[:-3] + "y"
    if re.search(r"(sh|ch|ss|x|o)es$", verb):
        return verb[:-2]
    if verb.endswith("s") and not verb.endswith("ss"):
        return verb[:-1]
    return verb


def her_voice(phrase: str) -> str:
    """A consequence as he said it ("I study architecture", "you have to tell me a
    joke" - you being Irene) as she says it to him ("you study architecture", "I have
    to tell you a joke")."""
    words = phrase.split()
    out: list[str] = []
    for i, word in enumerate(words):
        bare = _bare(word)
        tail = word[len(word.rstrip(".,!?;:")):]
        prev = _bare(words[i - 1]) if i else ""
        if bare in ("you", "irene"):
            # his "you" is Irene: "I" starting a clause, "me" anywhere else
            out.append(("I" if prev in _CLAUSE_START else "me") + tail)
        elif bare == "am" and prev == "i":
            out.append("are" + tail)
        elif bare == "are" and prev == "you":
            out.append("am" + tail)
        elif bare in _HIS_TO_HERS:
            out.append(_HIS_TO_HERS[bare] + tail)
        elif prev == "irene" and out[-1] == "I":
            out.append(_first_person(bare) + tail)
        else:
            out.append(word)
    return " ".join(out)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _locate(quote: str, said: str) -> int | None:
    """Where his words contain `quote` word for word (punctuation and case aside), as
    an index into the normalised text - None if he never said it."""
    q, s = _norm(quote), _norm(said)
    if not q:
        return None
    at = f" {s} ".find(f" {q} ")
    return at if at >= 0 else None


def _marks(said: str) -> list[tuple[int, str]]:
    """Each "if I win" / "if you win" / "if I lose" / "on a draw" in his normalised
    words: (where it ends, the side it opens - from HIS side)."""
    s = _norm(said)
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"\b(?:if|when)\s+(i|you)\s+(win|won|lose|lost)\b", s):
        he_wins = (m.group(2) in ("win", "won")) == (m.group(1) == "i")
        out.append((m.end(), "win" if he_wins else "lose"))
    for m in re.finditer(r"\b(?:if\s+(?:it's\s+|it\s+is\s+|we\s+)?(?:a\s+)?(?:draw|tie)|on\s+a\s+(?:draw|tie))\b", s):
        out.append((m.end(), "draw"))
    return sorted(out)


# a quote that came with its own "if I win," at the front
_LEAD = re.compile(r"^(?:and\s+|then\s+|but\s+)?(?:if|when)\s+(?:i|you)\s+(?:win|won|lose|lost)\s+")


_OPENER = re.compile(r"\b(?:if|when)\s+(i|you)\s+(win|won|lose|lost)\b|\b(?:if\s+(?:it'?s\s+|it\s+is\s+|we\s+)?(?:a\s+)?(?:draw|tie)|on\s+a\s+(?:draw|tie))\b", re.I)


def clause_spans(said: str) -> dict[str, str]:
    """What follows each "if I win" / "if you win" / "if it's a draw" in his words, up
    to the next such clause or the end of the sentence - by HIS side. The fallback for
    a side the model's quotes missed (they are his words either way)."""
    out: dict[str, str] = {}
    found = list(_OPENER.finditer(said or ""))
    for i, m in enumerate(found):
        if m.group(1):
            side = "win" if (m.group(2).lower() in ("win", "won")) == (m.group(1).lower() == "i") else "lose"
        else:
            side = "draw"
        stop = found[i + 1].start() if i + 1 < len(found) else len(said)
        text = re.split(r"[.!?;]", said[m.end():stop])[0]
        text = re.sub(r"^[\s,:-]+(?:(?:and|then)\s+)?|[\s,:-]+$", "", text, flags=re.I)
        text = re.sub(r"\s+(?:and|but|or|so)$", "", text, flags=re.I).strip(" ,")
        if text and side not in out:
            out[side] = text
    return out


def _side_after(rest: str) -> str | None:
    """The side a clause opening RIGHT after a consequence gives it ("... if I win")."""
    m = re.match(r"\s*(?:if|when)\s+(i|you)\s+(win|won|lose|lost)\b", rest)
    if m:
        return "win" if (m.group(2) in ("win", "won")) == (m.group(1) == "i") else "lose"
    if re.match(r"\s*(?:if\s+(?:it's\s+|it\s+is\s+|we\s+)?(?:a\s+)?(?:draw|tie)|on\s+a\s+(?:draw|tie))\b", rest):
        return "draw"
    return None


def _side_at(at: int, marks: list[tuple[int, str]]) -> str | None:
    """The clause his words at `at` fall in: the last marker before them."""
    side = None
    for end, which in marks:
        if end <= at:
            side = which
    return side


def check(raw: str, said: str) -> Stakes | Ask:
    """The model's quotes, checked against his words. Stakes only when every one is
    his, word for word, and sits in the clause it is claimed for."""
    try:
        got = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            got = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            got = None
    if not isinstance(got, dict):
        return Ask("unclear", f"unreadable parse: {str(raw)[:120]!r}")
    q = {k: (got.get(k).strip(" .,!?") if isinstance(got.get(k), str) and got.get(k).strip(" .,!?") else None)
         for k in ("he_wins", "he_loses", "draw", "loser_does", "winner_does")}
    # The model finds the spans; WHICH outcome a span belongs to is read off his
    # sentence by code - the clause it sits in ("if I win ...", "if you win ...") or
    # the word before it ("loser ...", "for who ...") - never taken from the model's
    # labels, which a 12B model swaps often enough to matter.
    marks = _marks(said)
    words = _norm(said)
    sides: dict[str, str] = {}
    roles: dict[str, str] = {}
    for key, quote in q.items():
        if quote is None:
            continue
        quote = _LEAD.sub("", _norm(quote))
        at = _locate(quote, said)
        if at is None:
            return Ask("unclear", f"{key} = {quote!r} isn't word for word what he said", q)
        before = words[:at].split()[-2:]
        role = "lose" if before[-1:] == ["loser"] or before == ["who", "loses"] or before == ["whoever", "loses"] else \
            "win" if before[-1:] in (["winner"], ["who"], ["whoever"]) or before in (["who", "wins"], ["whoever", "wins"]) else None
        # "you buy me lunch if I win": the clause can come right after its consequence
        # the clause it opens right after wins ("if I win X, if I lose Y": X is the
        # win); else one opening right after it; else the clause it falls in
        right_after = any(0 <= at - end and words[end:at].split() in ([], ["then"]) for end, _ in marks)
        side = None if role else (_side_at(at, marks) if right_after else _side_after(words[at + len(quote):]) or _side_at(at, marks))
        if role:
            if roles.get(role, quote) != quote:
                return Ask("unclear", f"two different things for the {role}r", q)
            roles[role] = quote
        elif side:
            if sides.get(side, quote) != quote:
                # the longer span wins only if it contains the other
                if quote in sides[side] or sides[side] in quote:
                    quote = max(quote, sides[side], key=len)
                else:
                    return Ask("unclear", f"two different things for his {side}", q)
            sides[side] = quote
        else:
            return Ask("unclear", f"{key} = {quote!r} isn't tied to a win, a loss or a draw", q)
    # a side he stated in an "if" clause that the model's quotes missed: that clause
    for side, text in clause_spans(said).items():
        if side not in sides and not roles:
            sides[side] = text
            log.info("rps stakes: %s taken from his clause (the model missed it): %r", side, text)
    win = her_voice(sides["win"]) if "win" in sides else None
    lose = her_voice(sides["lose"]) if "lose" in sides else None
    # "loser buys tea", "for who picks the film": one phrase binds both of them -
    # he does it if the role is his, she does it otherwise
    for role, quote in roles.items():
        verb = quote.split()
        base = " ".join([_first_person(_bare(verb[0]))] + verb[1:])
        his, hers = f"you {base}", f"I {base}"
        if role == "lose":
            lose, win = lose or his, win or hers
        else:
            win, lose = win or his, lose or hers
    q = {"win": win, "lose": lose, "draw": sides.get("draw")}
    if not win and not lose:
        return Ask("missing", "no stakes found", q)
    if not win:
        return Ask("missing_win", "no consequence for his win", q)
    if not lose:
        return Ask("missing_lose", "no consequence for his loss", q)
    if _norm(win) == _norm(lose):
        return Ask("unclear", "win and lose came out the same", q)
    return Stakes(win=win, lose=lose, draw=her_voice(sides["draw"]) if "draw" in sides else None, best_of=best_of(said), said=said,
                  parsed_at=datetime.now().isoformat(timespec="milliseconds"))


async def parse(chat: Callable[..., Awaitable[str]] | None, said: str) -> Stakes | Ask:
    """His words -> Stakes, or what to ask. `chat` is the model (llm.Ollama.chat)."""
    if chat is None:
        return Ask("unclear", "no model to read the stakes")
    try:
        raw = await chat(parse_messages(said), temperature=0.0, json_mode=True)
    except Exception as e:  # noqa: BLE001 - a dead model means she asks, never guesses
        log.warning("rps stakes: parse failed: %s", e)
        return Ask("unclear", f"model error: {e}")
    got = check(raw, said)
    log.info("rps stakes: parsed %r -> %s", said, got)
    return got


# ---- what she says -------------------------------------------------------------------------------------

ASK = {
    "missing": ("What's riding on it? Tell me what happens if you win, and what happens if you lose.",),
    "missing_win": ("And if you win? What do you get?", "Okay - and what happens if you win?"),
    "missing_lose": ("And if you lose? I need both sides before I seal anything.", "Fair - and if you lose?"),
    "unclear": ("I want the stakes exactly right before I seal anything. Say them once more: if you win, what happens - and if you lose?",
                "Hmm, I didn't catch the stakes cleanly. If you win, what? If you lose, what?"),
    "denied": ("Okay - tell me the stakes again. If you win, what happens? If you lose?",
               "My mistake. Once more: what happens if you win, and if you lose?"),
}


def confirm_line(stakes: Stakes) -> str:
    """The stakes read back exactly as held - code, not the model - so a swapped win and
    lose is caught before he throws."""
    parts = [f"If you win, {stakes.win}.", f"If you lose, {stakes.lose}."]
    parts.append(f"A draw, {stakes.draw}." if stakes.draw else "A draw, we go again - same stakes.")
    if stakes.best_of == 3:
        parts.insert(0, "Best of three, first to two.")
    parts.append("Deal? Ready?")
    return " ".join(parts)


# The settlement is two parts. Her REACTION - she lost a bet she set up, or won one -
# may be the model's (written ahead, checked). The CONSEQUENCE sentence is always the
# code's: the outcome's consequence, word for word, in one of these frames. So no
# model output can change, drop or swap what is announced.
REACTIONS: dict[str, tuple[str, ...]] = {
    "him": ("No. No! You actually won.", "Ugh - you got me, fair and square.", "I lost. I really lost. Okay.", "Unbelievable. You beat me."),
    "her": ("And THAT is the bet!", "Ha! Settled!", "Game, set, bet!", "Yes! I win!"),
    "draw": ("Dead even!", "A draw - and you planned for this one."),
}
CONSEQUENCE: dict[str, tuple[str, ...]] = {
    "him": ("A bet is a bet: {c}.", "As promised: {c}.", "Sealed and settled - {c}."),
    "her": ("Which means {c}. No backing out now.", "So: {c}. I'll be holding you to it.", "You said it yourself: {c}."),
    "draw": ("By your own terms: {c}.", "And a draw means {c}."),
}
SETTLE_CUES = {"him": ("outplayed", "sulking"), "her": ("triumphant", "proud"), "draw": ("standoff", "smug")}


def consequence_sentence(stakes: Stakes, outcome: str, rng: random.Random | None = None) -> str:
    """The code's sentence: this outcome's consequence, exactly as held."""
    return (rng or random).choice(CONSEQUENCE[outcome]).format(c=consequence(stakes, outcome))


def narrate_messages(stakes: Stakes, outcome: str) -> list[dict]:
    result = {
        "him": "HE WON the bet - you, Irene, LOST a bet you agreed to. React like a good loser: grudging, a little theatrical, a bit indignant.",
        "her": "YOU, Irene, WON the bet - he lost. React gleeful and triumphant, teasing him a little.",
        "draw": "It was a DRAW, and he had set a consequence for a draw. React to the tie.",
    }[outcome]
    return [
        {
            "role": "system",
            "content": (
                "You are Irene, a witty, competitive AI assistant who just played rock-paper-scissors for a bet with him. "
                "Dry humour, real feeling, the occasional 'sir' - never baby talk (no 'tee hee', no 'silly'). The result is "
                "FIXED. Write only your spoken REACTION to it - one short exclamation or sentence, under 15 words. The "
                "consequence is announced right after you, so do NOT say what happens next, do NOT mention the bet's terms, "
                "and do NOT mention the throws (rock, paper, scissors). No emoji, no asterisks, no stage directions. "
                'Reply with JSON only: {"line": string}.'
            ),
        },
        {"role": "user", "content": result},
    ]


# a line claiming SHE won / HE won - checked against the code's outcome
_SAYS_SHE_WON = re.compile(r"\b(?:i\s+(?:win|won|beat\s+you)|you\s+(?:lose|lost)|my\s+(?:win|victory))\b", re.I)
_SAYS_HE_WON = re.compile(r"\b(?:you\s+(?:win|won|beat\s+me|got\s+me)|i\s+(?:lose|lost))\b", re.I)


def narration_ok(line: str, stakes: Stakes, outcome: str) -> tuple[bool, str]:
    """Her model-written reaction is used only if it is a short reaction and nothing
    more: no consequence of any side (the code says that), no throw, and never the
    opposite result."""
    if not line or len(line) > 140 or "\n" in line or re.search(r"[<>*#\[\]{}]", line):
        return False, "shape"
    # it doesn't know the throws - a line naming one could contradict the reveal
    if re.search(r"\b(?:rock|paper|scissors?|covers?|cuts?|blunts?)\b", line, re.I):
        return False, "names a throw"
    heard = _words(line)
    for other in ("him", "her", "draw"):
        c = consequence(stakes, other)
        own = _words(c) if c else []
        if own and sum(1 for w in own if _said(w, heard)) >= max(1, len(own) // 2):
            return False, f"talks about a consequence ({other})"
    if outcome == "him" and _SAYS_SHE_WON.search(line):
        return False, "claims she won"
    if outcome == "her" and _SAYS_HE_WON.search(line):
        return False, "claims he won"
    if outcome == "draw" and (_SAYS_SHE_WON.search(line) or _SAYS_HE_WON.search(line)):
        return False, "claims a winner on a draw"
    return True, ""


async def narrate(chat: Callable[..., Awaitable[str]] | None, stakes: Stakes, outcome: str) -> str | None:
    """The model's reaction for one outcome, or None (a template reaction then)."""
    if chat is None or consequence(stakes, outcome) is None:
        return None
    try:
        raw = await chat(narrate_messages(stakes, outcome), temperature=0.9, json_mode=True)
        # emphasis asterisks would be read out: dropped, the words kept
        line = re.sub(r"\*+", "", str(json.loads(raw).get("line", ""))).strip()
    except Exception as e:  # noqa: BLE001 - the template says it instead
        log.info("rps stakes: reaction for %s failed: %s", outcome, e)
        return None
    ok, why = narration_ok(line, stakes, outcome)
    if not ok:
        log.info("rps stakes: reaction for %s dropped (%s): %r", outcome, why, line)
        return None
    return line


def settlement(stakes: Stakes, outcome: str, narrations: dict[str, str | None] | None = None,
               rng: random.Random | None = None) -> tuple[str, tuple[str, ...], str]:
    """(her line, its cue family, "model" | "template") for the settled bet: her
    reaction (the model's, if it was written for THIS outcome and passes the check
    again here) and then the code's consequence sentence."""
    reaction = (narrations or {}).get(outcome)
    source = "model"
    if not (reaction and narration_ok(reaction, stakes, outcome)[0]):
        reaction, source = (rng or random).choice(REACTIONS[outcome]), "template"
    return f"{reaction} {consequence_sentence(stakes, outcome, rng)}", SETTLE_CUES[outcome], source
