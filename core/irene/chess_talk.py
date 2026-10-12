"""What Irene says while she plays chess - the lines, the faces, the openings.

Every line is chosen by the game (chess_game.py) from what the ENGINE found, so it
is true: a "nice one" is a move the engine rates, "that hangs your knight" is a
knight her best reply takes, "I think I'm losing" is a position the engine scores
against her. Playful and trash-talky, never a lecture: no "you should have...".

Many lines per moment, never the same twice running; each moment has the faces
that fit it (cues.json names), never the same face twice running either.
"""
from __future__ import annotations

import random
import re

LINES: dict[str, tuple[str, ...]] = {
    "start_he_white": (
        "Ooh, chess! You're white, sir - your move.",
        "A game? Yes! White's yours. Go on, impress me.",
        "Board's up. You go first - I'll try to be nice. Briefly.",
        "Let's play! You're white. No pressure. Some pressure.",
        "Chess! My favourite. Your move, Mister Tri.",
    ),
    "start_she_white": (
        "I'm white? Then I'm starting. Watch this.",
        "Ooh, I get first move. Lovely.",
        "Fine, I'll go first. Brace yourself.",
    ),
    "stop": (
        "Okay, board's away. We'll call that one a draw. For your sake.",
        "Game over, then. I was just getting going!",
        "Fine, we'll stop. I'll remember where everything was.",
    ),
    "he_resigns": (
        "You resign? I accept. Graciously. Mostly graciously.",
        "Resigning? Well played anyway, sir. Rematch whenever you're ready.",
        "I'll take it! Good game, Mister Tri.",
        "A wise resignation. Painful, but wise.",
    ),
    "she_resigns": (
        "Okay... I resign. That was really well played, sir.",
        "I know when I'm beaten. I resign - good game.",
        "Fine! I resign. Don't let it go to your head.",
    ),
    "takeback": (
        "Fine, take it back. Just this once.",
        "Takeback granted. I'm being very generous today.",
        "Undone. I saw nothing. Go again.",
        "Okay, back it goes. Your move - again.",
    ),
    "nothing_to_take_back": (
        "Nothing to take back yet!",
        "You haven't even moved yet, sir.",
    ),
    "which": (
        "Which one - {options}?",
        "Hmm, {options}?",
        "Say which: {options}?",
    ),
    "illegal": (
        "Can't do that one - {reason}. Try again?",
        "Nope, {reason}. Still your move.",
        "Ah-ah. {reason}. Go again.",
        "Not legal, sir - {reason}. Have another go.",
    ),
    "not_a_move": (
        "Sorry, which move was that?",
        "I didn't catch the move - say it again?",
    ),
    # --- his move --------------------------------------------------------------
    "his_good": (
        "Ooh, nice one.",
        "Okay... that's actually good.",
        "Hey! Who taught you that?",
        "Annoyingly strong move, sir.",
        "Fine. That's good. I hate it.",
        "Ooh. I didn't want you to find that.",
        "Look at you, playing properly!",
    ),
    "hangs": (
        "Wait... that hangs your {piece}.",
        "Um. Your {piece} is just... sitting there.",
        "Did you mean to leave your {piece} like that?",
        "Oh, your poor {piece}.",
    ),
    "blunder": (
        "Ooh. Are you sure about that?",
        "Hmm. I wouldn't have played that. But thank you!",
        "That's... a choice.",
        "Bold. Very bold. Possibly too bold.",
    ),
    "dubious": (
        "Hm. Interesting.",
        "Okay... not sure about that one.",
        "Mm-hm. If you say so.",
        "Curious choice, sir.",
    ),
    "he_takes": (
        "Hey! My {piece}!",
        "Rude. That was my {piece}.",
        "You took my {piece}! I'll remember that.",
    ),
    "check_by_him": (
        "Check? Rude.",
        "Ooh, check.",
        "Hey! My king!",
    ),
    # --- her move ----------------------------------------------------------------
    "her_move": (
        "{move}.",
        "{move}.",
        "Hmm... {move}.",
        "I'll play {move}.",
        "My move: {move}.",
        "{move}. Your turn.",
        "Let's see... {move}.",
    ),
    "she_takes": (
        "And I'll take that {piece}. {move}.",
        "Your {piece} is mine now - {move}.",
        "{move}. Thank you for the {piece}!",
        "Mm, {piece}. Delicious. {move}.",
    ),
    "take_hanging": (
        "That hangs your {piece} - and I'll take it. {move}.",
        "Your {piece} was hanging, sir. Was. {move}.",
        "Free {piece}! {move}. Thank you!",
    ),
    "spare_hanging": (
        "Your {piece}'s hanging, by the way. I'm feeling generous. {move}.",
        "I could take your {piece}... but I won't. {move}.",
    ),
    "check_by_her": (
        "Check!",
        "And... check.",
        "Check. Your king looks nervous.",
        "Check! Careful now.",
    ),
    "opening_his": (
        "The {name}? Really?",
        "Ooh, the {name}. Bold.",
        "The {name}, of course.",
        "Ah, the {name}. I know this one.",
    ),
    "opening_hers": (
        "We're in the {name} now.",
        "That makes it a {name}. Classic.",
        "Hello, {name}.",
    ),
    # --- the position after her move -----------------------------------------------
    "winning": (
        "This is going rather well for me.",
        "Don't look now, but I'm winning.",
        "Mm. I like my position.",
        "You might want to start worrying, sir.",
    ),
    "losing": (
        "I think I'm losing this...",
        "Okay, this is not going to plan.",
        "Hmm. I don't love my position.",
        "Give me a minute. I'm... regrouping.",
    ),
    "even_again": (
        "Okay, we're level again.",
        "And it's anyone's game again.",
    ),
    "she_sees_mate": (
        "Ooh. I see something. Do you?",
        "I think I have a mate coming. No pressure!",
    ),
    "he_has_mate": (
        "...You have a mate, don't you. Don't tell me.",
        "Oh no. Oh no no. I see it.",
    ),
    # --- the end -----------------------------------------------------------------
    "she_mates": (
        "Checkmate! [laugh] Good game, sir.",
        "And that's mate! Better luck next time, Mister Tri.",
        "Checkmate! Rematch? You look like you want a rematch.",
    ),
    "he_mates": (
        "Checkmate... you got me. Well played.",
        "Noooo. Okay. That's mate. Rematch?",
        "Checkmate. I demand a rematch.",
    ),
    "draw": (
        "That's a draw! Nobody wins. Very diplomatic of us.",
        "A draw. I'll take it.",
        "Stalemate! Neither of us is happy.",
    ),
}

# the faces for each moment, best first (config/cues.json names)
CUES: dict[str, tuple[str, ...]] = {
    "start": ("firedUp", "excited", "happy"),
    "stop": ("shrug", "wave"),
    "he_resigns": ("bow", "proud", "smug"),
    "she_resigns": ("bow", "sad", "sheepish"),
    "takeback": ("fingerWag", "wink", "innocent"),
    "which": ("headTilt", "confused"),
    "illegal": ("fingerWag", "headTilt"),
    "his_good": ("starryEyed", "surprised", "amused"),
    "hangs": ("shocked", "smug", "peeking"),
    "blunder": ("amused", "headTilt", "innocent"),
    "dubious": ("headTilt", "amused", "thinking"),
    "he_takes": ("sulking", "surprised"),
    "check_by_him": ("surprised", "sulking"),
    "her_move": ("focused", "thinking", "airTap"),
    "she_takes": ("wink", "smug", "proud"),
    "take_hanging": ("smug", "innocent", "wink"),
    "spare_hanging": ("innocent", "wink"),
    "check_by_her": ("firedUp", "wink", "smug"),
    "winning": ("smug", "proud", "cool"),
    "losing": ("concerned", "dizzy", "peeking"),
    "even_again": ("phew", "focused"),
    "she_mates": ("excitedBounce", "proud", "cool"),
    "he_mates": ("sobbing", "sad", "bow"),
    "draw": ("shrug", "phew"),
}

# Openings by their moves (SAN), longest match wins - just their names, so she can
# say "the Sicilian, really?". Not a book: the engine plays the moves.
OPENINGS: tuple[tuple[str, str], ...] = (
    ("e4 c5", "Sicilian"),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6", "Najdorf"),
    ("e4 c5 Nc3", "Closed Sicilian"),
    ("e4 c5 c3", "Alapin"),
    ("e4 e6", "French"),
    ("e4 c6", "Caro-Kann"),
    ("e4 d5", "Scandinavian"),
    ("e4 d6", "Pirc"),
    ("e4 g6", "Modern Defence"),
    ("e4 Nf6", "Alekhine"),
    ("e4 Nc6", "Nimzowitsch Defence"),
    ("e4 e5 f4", "King's Gambit"),
    ("e4 e5 Nc3", "Vienna"),
    ("e4 e5 Bc4", "Bishop's Opening"),
    ("e4 e5 Qh5", "Wayward Queen"),
    ("e4 e5 Nf3 Nf6", "Petrov"),
    ("e4 e5 Nf3 d6", "Philidor"),
    ("e4 e5 Nf3 Nc6 Bb5", "Ruy Lopez"),
    ("e4 e5 Nf3 Nc6 Bc4", "Italian"),
    ("e4 e5 Nf3 Nc6 Bc4 Nf6", "Two Knights"),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5 b4", "Evans Gambit"),
    ("e4 e5 Nf3 Nc6 d4", "Scotch"),
    ("e4 e5 Nf3 Nc6 Nc3 Nf6", "Four Knights"),
    ("d4 d5 c4", "Queen's Gambit"),
    ("d4 d5 c4 dxc4", "Queen's Gambit Accepted"),
    ("d4 d5 c4 e6", "Queen's Gambit Declined"),
    ("d4 d5 c4 c6", "Slav"),
    ("d4 d5 Bf4", "London"),
    ("d4 Nf6 Bf4", "London"),
    ("d4 d5 Nf3 Nf6 Bf4", "London"),
    ("d4 Nf6 c4 g6", "King's Indian"),
    ("d4 Nf6 c4 g6 Nc3 d5", "Grünfeld"),
    ("d4 Nf6 c4 e6 Nc3 Bb4", "Nimzo-Indian"),
    ("d4 Nf6 c4 e6 Nf3 b6", "Queen's Indian"),
    ("d4 Nf6 c4 c5 d5 b5", "Benko Gambit"),
    ("d4 f5", "Dutch"),
    ("d4 e5", "Englund Gambit"),
    ("c4", "English"),
    ("Nf3", "Réti"),
    ("f4", "Bird's Opening"),
    ("b3", "Larsen"),
    ("g4", "Grob"),
    ("e4 e5 Ke2", "Bongcloud"),
)


def opening(history: list[str]) -> tuple[str, int]:
    """The longest named opening the game's moves start with: (name, its plies)."""
    best, plies = "", 0
    clean = [m.rstrip("+#") for m in history]
    for moves, name in OPENINGS:
        seq = moves.split()
        if len(seq) > plies and clean[: len(seq)] == seq:
            best, plies = name, len(seq)
    return best, plies


class Lines:
    """Her lines and faces for each moment, never the same twice running."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self._last: dict[str, str] = {}
        self._last_cue: str | None = None

    def pick(self, kind: str, **fill) -> str:
        pool = LINES.get(kind)
        if not pool:
            return ""
        options = [line for line in pool if line != self._last.get(kind)] or list(pool)
        line = self.rng.choice(options)
        self._last[kind] = line
        text = line.format(**fill) if fill else line
        # a filled-in move or reason that starts a sentence: capitalised
        return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)

    def cue(self, kind: str | None) -> str | None:
        family = CUES.get(kind or "", ())
        if not family:
            return None
        choice = next((c for c in family if c != self._last_cue), family[0])
        self._last_cue = choice
        return choice
