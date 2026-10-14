"""Her long-term memory: what she keeps across restarts, and what she recalls for a
message.

Kept (each as it happens, never by re-reading old files):
  turn      an exchange: his words and what she said back
  fact      something he told her about himself or what should hold ("my brother
            Trác...", "I prefer short answers") - his sentence, verbatim (memory.py)
  research  a question she looked up, and her answer
  lecture   a lecture she listened to: its title and summary

Recalled per message, inside the per-message context (Conversation.context) - never
stored in the history, so it costs prefill on that message only and never grows the
conversation's KV cache - and capped at a token budget (config/memory.yaml).
Relevance is hybrid: a small embedding model (bge-small-en-v1.5, on the CPU by
default: no VRAM) for meaning, plus his own words for names ("Trác" and "Trac" are
the same word here) - a name the embedding has never seen is still found.
"Last week", "yesterday", "on Monday" select by date instead.

Forgetting deletes: the rows go, SQLite overwrites their bytes (secure_delete) and
the write-ahead log is truncated; the same words come out of logs/turns.jsonl,
core.log and his voice turns (forget()). Expiry is per kind (config/memory.yaml).

Two stores, never mixed: his (his commands - the HUD, the live mic) and the dev
store (test scripts, dev replays, evals), by the same rule as tools/sandbox.py.
Everything is local: the model loads from core/models/, offline.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import yaml

log = logging.getLogger("irene.recall")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "memory.yaml"
STORE_DIR = ROOT / "core" / "data" / "memory"
MODEL_DIR = ROOT / "core" / "models" / "bge-small-en-v1.5"
LOGS = ROOT / "core" / "logs"
VOICE_TURNS = ROOT / "core" / "voice_data" / "turns"

KINDS = ("turn", "fact", "research", "lecture")
# bge's instruction for a search query (passages are embedded as they are)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CHARS_PER_TOKEN = 3.5  # gemma, her prose (brain._tokens)
# how he wants her to be, whatever he is asking: always recalled, within this much
STANDING_TOKENS = 80
_STANDING = re.compile(r"\bi (?:prefer|like it when|hate it when|'d rather|would rather)\b|\bfrom now on\b|\bcall me\b|\b(?:always|never) (?:\w+ )?(?:me|answer|say|use|call|tell)\b|\bkeep (?:it|your answers?|things) \w+", re.I)


@dataclass
class Policy:
    enabled: bool = True
    device: str = "cpu"
    budget_tokens: int = 350
    recall_budget_tokens: int = 600
    min_similarity: float = 0.60
    keep_days: dict = field(default_factory=lambda: {"turn": 90, "fact": 0, "research": 365, "lecture": 0})
    max_items: int = 20000


def load_policy(path: Path = CONFIG) -> Policy:
    p = Policy()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return p
    for key in ("enabled", "device", "budget_tokens", "recall_budget_tokens", "min_similarity", "max_items"):
        if key in raw:
            setattr(p, key, type(getattr(p, key))(raw[key]))
    p.keep_days = {**p.keep_days, **{k: int(v or 0) for k, v in (raw.get("keep_days") or {}).items()}}
    return p


POLICY = load_policy()


# ---- words -----------------------------------------------------------------

_STOP = set(
    "a an the and or but if of to in on at for with about from by as is are was were be been am i me my you your we our "
    "he she it they them this that these those what which who whom when where why how do did does done have has had "
    "can could would should will shall may might must not no yes so just than then there here tell told say said ask "
    "asked thing things something anything remember recall again last week yesterday today talk talked talking us "
    "find found look looked up researched research irene please know let lets get got some any all one".split()
)


def fold(text: str) -> str:
    """Lowercase, accents off: "Trác" and "Trac" are one word."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).replace("đ", "d")


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fold(text)) if w not in _STOP and len(w) > 1]


# ---- the embedding model ------------------------------------------------------


class Embedder:
    """bge-small-en-v1.5 (33M parameters, 384 dimensions), loaded once."""

    def __init__(self, path: Path = MODEL_DIR, device: str = "cpu"):
        self.path, self.device = path, device
        self._lock = threading.Lock()
        self._model = None
        self._tok = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModel, AutoTokenizer

            started = time.perf_counter()
            device = self.device if self.device != "cuda" or torch.cuda.is_available() else "cpu"
            self._tok = AutoTokenizer.from_pretrained(str(self.path), local_files_only=True)
            model = AutoModel.from_pretrained(str(self.path), local_files_only=True).eval()
            if device == "cuda":
                model = model.half()
            self._model = model.to(device)
            self.device = device
            log.info("memory: embedding model ready on %s in %.1fs", device, time.perf_counter() - started)

    def encode(self, texts: list[str], query: bool = False) -> np.ndarray:
        import torch

        self.load()
        if query:
            texts = [QUERY_PREFIX + t for t in texts]
        with self._lock, torch.inference_mode():
            batch = self._tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt").to(self.device)
            vec = self._model(**batch).last_hidden_state[:, 0].float()
            vec = torch.nn.functional.normalize(vec, dim=-1)
        return vec.cpu().numpy().astype(np.float32)


EMBEDDER = Embedder(device=POLICY.device)


# ---- the store ----------------------------------------------------------------------


@dataclass
class Item:
    id: int
    kind: str
    at: float
    about: str
    text: str
    session: str = ""
    score: float = 0.0

    def tokens(self) -> int:
        return math.ceil((len(self.about) + len(self.text) + 24) / CHARS_PER_TOKEN)

    def line(self, now: float) -> str:
        when = _when_label(self.at, now)
        label = {"turn": "talked", "fact": "he told you", "research": "you researched", "lecture": "lecture"}[self.kind]
        about = f" {self.about}:" if self.about and self.kind in ("research", "lecture") else ""
        return f"- [{when}, {label}]{about} {self.text}"


class Store:
    """One SQLite file, with every row's vector and words held in memory: a search
    is a matrix product and a dictionary lookup, never a disk read."""

    def __init__(self, path: Path, embedder: Embedder | None = None):
        self.path, self.embedder = path, embedder or EMBEDDER
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self.items: list[Item] = []
        self.vectors = np.zeros((0, 384), np.float32)
        self.index: dict[str, set[int]] = {}

    def _open(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
            # forgetting overwrites: freed pages are zeroed, not left readable
            db.execute("PRAGMA secure_delete = ON")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at REAL NOT NULL, "
                       "about TEXT NOT NULL, text TEXT NOT NULL, session TEXT NOT NULL, vec BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self._db = db
            self._load()
        return self._db

    def _load(self) -> None:
        rows = self._db.execute("SELECT id, kind, at, about, text, session, vec FROM items ORDER BY id").fetchall()
        self.items = [Item(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]
        self.vectors = np.stack([np.frombuffer(r[6], np.float32) for r in rows]) if rows else np.zeros((0, 384), np.float32)
        self._reindex()

    def _reindex(self) -> None:
        self.index = {}
        for k, item in enumerate(self.items):
            for w in set(words(f"{item.about} {item.text}")):
                self.index.setdefault(w, set()).add(k)

    def __len__(self) -> int:
        with self._lock:
            self._open()
            return len(self.items)

    def meta(self, key: str, value: str | None = None) -> str | None:
        with self._lock:
            db = self._open()
            if value is not None:
                db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
                return value
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def add(self, kind: str, text: str, about: str = "", at: float | None = None, session: str = "") -> Item | None:
        text, about = " ".join((text or "").split()), " ".join((about or "").split())
        if kind not in KINDS or not text:
            return None
        vec = self.embedder.encode([f"{about}: {text}" if about else text])[0]
        at = time.time() if at is None else at
        with self._lock:
            db = self._open()
            # the same thing kept twice (a fact said again) replaces the older one
            same = [i for i in self.items if i.kind == kind and fold(i.text) == fold(text) and fold(i.about) == fold(about)]
            if same:
                self._delete([i.id for i in same])
            cur = db.execute("INSERT INTO items (kind, at, about, text, session, vec) VALUES (?, ?, ?, ?, ?, ?)",
                             (kind, at, about, text, session, vec.tobytes()))
            item = Item(cur.lastrowid, kind, at, about, text, session)
            self.items.append(item)
            self.vectors = np.vstack([self.vectors, vec[None, :]])
            for w in set(words(f"{about} {text}")):
                self.index.setdefault(w, set()).add(len(self.items) - 1)
        return item

    def _delete(self, ids: list[int]) -> int:
        if not ids:
            return 0
        db = self._open()
        db.executemany("DELETE FROM items WHERE id = ?", [(i,) for i in ids])
        gone = set(ids)
        keep = [k for k, item in enumerate(self.items) if item.id not in gone]
        self.items = [self.items[k] for k in keep]
        self.vectors = self.vectors[keep] if keep else np.zeros((0, 384), np.float32)
        self._reindex()
        return len(gone)

    def delete(self, ids: list[int]) -> int:
        """Gone for good: the rows, their bytes in the file (secure_delete), the log."""
        with self._lock:
            n = self._delete(list(ids))
            if n:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return n

    def search(self, query: str, k: int = 8, kinds: tuple[str, ...] = KINDS, exclude_session: str = "") -> list[Item]:
        """The items most about `query`: by meaning (cosine) and by his words (a
        rare word - a name - weighs more), fused by rank."""
        with self._lock:
            self._open()
            if not self.items:
                return []
            pool = [n for n, item in enumerate(self.items) if item.kind in kinds and (not exclude_session or item.session != exclude_session)]
            if not pool:
                return []
            if not self.embedder.ready:
                # still loading at startup: no memory for this message, rather than a
                # turn that waits 15 s for the model
                log.info("memory: embedding model not loaded yet - nothing recalled")
                return []
            qvec = self.embedder.encode([query], query=True)[0]
            sims = self.vectors[pool] @ qvec
            by_meaning = [pool[i] for i in np.argsort(-sims)[: k * 2]]
            sim_of = {pool[i]: float(sims[i]) for i in range(len(pool))}
            # his words: idf-weighted overlap
            allowed = set(pool)
            n_items = len(self.items)
            hits: dict[int, float] = {}
            rare: set[int] = set()
            for w in set(words(query)):
                found = self.index.get(w, set()) & allowed
                if found:
                    idf = math.log(1 + n_items / len(found))
                    for n in found:
                        hits[n] = hits.get(n, 0.0) + idf
                    # a word few items share (a name, a project) is evidence by itself
                    if len(found) <= max(1, n_items // 4):
                        rare |= found
            by_words = sorted(hits, key=lambda n: -hits[n])[: k * 2]
            fused: dict[int, float] = {}
            for rank, n in enumerate(by_meaning):
                if sim_of[n] >= POLICY.min_similarity:
                    fused[n] = fused.get(n, 0.0) + 1 / (60 + rank)
            for rank, n in enumerate(by_words):
                # a word in common counts when it is rare enough to mean something
                if n in rare:
                    fused[n] = fused.get(n, 0.0) + 1 / (60 + rank)
            ranked = sorted(fused, key=lambda n: -fused[n])[:k]
            out = []
            for n in ranked:
                item = self.items[n]
                out.append(Item(item.id, item.kind, item.at, item.about, item.text, item.session, round(sim_of[n], 3)))
            return out

    def between(self, start: float, end: float, kinds: tuple[str, ...] = KINDS, exclude_session: str = "") -> list[Item]:
        with self._lock:
            self._open()
            return [replace(i) for i in self.items if i.kind in kinds and start <= i.at < end and (not exclude_session or i.session != exclude_session)]

    def standing(self, exclude_session: str = "") -> list[Item]:
        """His standing preferences, newest first."""
        with self._lock:
            self._open()
            return [replace(i) for i in reversed(self.items) if i.kind == "fact" and _STANDING.search(i.text) and (not exclude_session or i.session != exclude_session)]

    def session_items(self, session: str) -> list[Item]:
        with self._lock:
            self._open()
            return [i for i in self.items if i.session == session]

    def prune(self, policy: Policy | None = None, now: float | None = None) -> int:
        """Expired items by kind (keep_days, 0 = forever), then the oldest turns past
        max_items."""
        policy = policy or POLICY
        now = now or time.time()
        with self._lock:
            self._open()
            old = [i.id for i in self.items if policy.keep_days.get(i.kind, 0) and now - i.at > policy.keep_days[i.kind] * 86400]
            n = self._delete(old)
            over = len(self.items) - policy.max_items
            if over > 0:
                turns = sorted((i for i in self.items if i.kind == "turn"), key=lambda i: i.at)[:over]
                n += self._delete([i.id for i in turns])
            if n:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                log.info("memory: pruned %d item(s) (%d kept)", n, len(self.items))
            return n

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


HIS = Store(STORE_DIR / "memory.sqlite")
DEV = Store(STORE_DIR / "memory-dev.sqlite")


def current() -> Store:
    """His store for his commands; the dev store for anything else (tools/sandbox.py)."""
    from tools import sandbox

    return DEV if sandbox.os_input_blocked() else HIS


# writes leave the turn: one thread, in order
_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")


def _write(store: Store, kind: str, text: str, about: str = "", session: str = "", at: float | None = None):
    if not POLICY.enabled:
        return None

    def run():
        try:
            item = store.add(kind, text, about, at, session)
            if item is not None:
                log.info("memory (%s): kept %s %r", "his" if store is HIS else "dev", kind, (about or text)[:70])
        except Exception:  # noqa: BLE001 - memory must never take a turn down
            log.exception("memory: could not keep a %s", kind)

    return _WRITER.submit(run)


def remember_turn(said: str, answer: str, session: str, store: Store | None = None):
    said, answer = " ".join(said.split()), " ".join(answer.split())
    if len(said.split()) < 3 or said.startswith("["):
        return None  # "thanks", "stop": not worth a memory
    return _write(store or current(), "turn", f'He said: "{said[:300]}" You said: "{answer[:400]}"', session=session)


def remember_fact(said: str, session: str, store: Store | None = None):
    return _write(store or current(), "fact", said[:300], session=session)


def remember_research(question: str, answer: str, session: str, store: Store | None = None):
    return _write(store or current(), "research", answer[:700], about=question[:160], session=session)


def remember_lecture(title: str, summary: str, at: float | None = None, store: Store | None = None):
    return _write(store or current(), "lecture", summary[:900], about=title[:160], at=at)


def flush(timeout: float = 30.0) -> None:
    """Wait for the writes queued so far (tests, evals, shutdown)."""
    _WRITER.submit(lambda: None).result(timeout)


def new_session() -> str:
    return uuid.uuid4().hex[:12]


# ---- when ----------------------------------------------------------------------

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WHEN = re.compile(
    r"\b(yesterday|today|this morning|last night|tonight|this week|last week|the other day|last month|this month|recently|lately"
    r"|(\d+|a|one|two|three|four|five|six|seven|a few|few) (day|week)s? ago|(?:on |last )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.I,
)
_NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "a few": 3, "few": 3}


def when(text: str, now: datetime | None = None) -> tuple[float, float, str] | None:
    """The time span his words name ("last week", "on Monday", "3 days ago"), as
    (start, end, how he said it) - or None."""
    m = _WHEN.search(text or "")
    if m is None:
        return None
    now = now or datetime.now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    said = m.group(0).lower()
    span: tuple[datetime, datetime]
    if said == "today" or said == "this morning" or said == "tonight":
        span = (day, now + timedelta(seconds=1))
    elif said == "yesterday":
        span = (day - timedelta(days=1), day)
    elif said == "last night":
        span = (day - timedelta(hours=8), day + timedelta(hours=5))
    elif said == "this week":
        span = (day - timedelta(days=day.weekday()), now + timedelta(seconds=1))
    elif said == "last week":
        monday = day - timedelta(days=day.weekday())
        span = (monday - timedelta(days=7), monday)
    elif said in ("the other day", "recently", "lately"):
        span = (day - timedelta(days=7), day)
    elif said == "this month":
        span = (day.replace(day=1), now + timedelta(seconds=1))
    elif said == "last month":
        first = day.replace(day=1)
        span = ((first - timedelta(days=1)).replace(day=1), first)
    elif m.group(2):
        n = int(m.group(2)) if m.group(2).isdigit() else _NUM[m.group(2).lower()]
        unit = 7 if m.group(3).lower() == "week" else 1
        centre = day - timedelta(days=n * unit)
        # "3 days ago" is that day; "two weeks ago" is that week, give or take
        span = (centre, centre + timedelta(days=1)) if unit == 1 else (centre - timedelta(days=3), centre + timedelta(days=4))
    else:
        target = _WEEKDAYS.index(m.group(4).lower())
        back = (day.weekday() - target) % 7 or 7
        start = day - timedelta(days=back)
        span = (start, start + timedelta(days=1))
    return span[0].timestamp(), span[1].timestamp(), said


def _when_label(at: float, now: float) -> str:
    then = datetime.fromtimestamp(at)
    days = (datetime.fromtimestamp(now).date() - then.date()).days
    ago = "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"
    return f"{then.strftime('%a')} {then.day} {then.strftime('%b')}, {ago}"


# ---- asking about the past -----------------------------------------------------

_PAST = re.compile(
    r"\b(?:what|which|who|when|where|how)\b.{0,40}\b(?:did|have|had) (?:i|we|you)\b.{0,30}\b(?:tell|told|say|said|mention|talk|discuss|research|look|ask|decide|learn|hear)"
    r"|\bdid i (?:ever )?(?:tell|mention|say)\b|\bremember (?:when|what|that|the|my|me)\b|\bdo you remember\b|\bwe (?:talked|spoke|chatted) about\b"
    r"|\b(?:that|the) (?:thing|stuff|article|page|research) (?:i|we|you) (?:researched|looked up|found|read)\b|\bi (?:researched|looked up)\b"
    r"|\bwhat (?:do you know|did you learn) about (?:me|my)\b|\b(?:last|previous) (?:time|session|conversation)\b|\bthe lecture (?:on|about|from)\b"
    r"|\b(?:that|the) (?:\w+ ){0,2}you (?:recommended|suggested|mentioned|told me about|found)\b|\bwhat (?:you|i) (?:told|said to) (?:me|you)\b"
    r"|\bfrom (?:that|the) (?:\w+ ){0,3}(?:lecture|class|lesson|talk)\b|\bremind me\W+(?:what|when|where|who|which|how)\b"
    # his people and his dates: only he could have told her ("what's my boss called
    # again?", "when is my cousin's wedding?") - never something to look up
    r"|\b(?:what|who|when|where)(?:'s| is| was| are| were)? my (?:\w+ ){0,2}?(?:sister|brother|mom|mum|mother|dad|father|parents?|wife|husband"
    r"|girlfriend|boyfriend|partner|son|daughter|kids?|cousin|uncle|aunt|grandma|grandpa|grandmother|grandfather|niece|nephew|roommate"
    r"|colleague|coworker|classmate|boss|manager|teacher|sensei|coach|friend|neighbou?r|landlord|dog|cat|pet|birthday|anniversary)(?:'s)?\b"
    r"|\bmy \w+(?:'s)? (?:name|birthday|wedding|job) again\b"
    # "which city is my brother studying in?" (live: researched instead)
    r"|\b(?:what|which|who|when|where|how)\b(?:\s+\w+){0,3}?\s+(?:is|was|are|were|does|did)\s+my\s+(?:\w+\s+)?(?:sister|brother|mom|mum|mother|dad"
    r"|father|parents?|wife|husband|girlfriend|boyfriend|partner|son|daughter|cousin|uncle|aunt|grandma|grandpa|roommate|colleague|coworker"
    r"|classmate|boss|manager|teacher|sensei|coach|friend)\b"
    # his own results: "what score did I get on my exam?" (live eval: "87 out of 100")
    r"|\bwhat (?:\w+ ){0,2}did i (?:get|score|make|earn|win)\b|\bhow did i do (?:on|in|at)\b",
    re.I,
)

RECALL_HINT = (
    "He is asking about something from before. Answer from this conversation or from 'From your memory' "
    "below - only what is really there, never an invented detail, and no tool (don't research it again). "
    "If neither has it, say plainly you don't remember that one. It's a question, not a complaint: no apology."
)


# something he tells her about himself or his people - kept as a fact even when the
# session notes (memory.py) wouldn't note it; a question about it is not one
_ABOUT_HIM = re.compile(
    r"\b(?:is|are|was) my\b|\bmy (?:\w+ ){0,2}(?:brother|sister|mom|mum|mother|dad|father|parents|wife|husband|girlfriend|boyfriend|partner"
    r"|friend|son|daughter|boss|teacher|sensei|coach|project|work|job|company|car|dog|cat|birthday|address|team|class|course|deadline"
    r"|exam|university|school|major|landlord|neighbou?r)\b(?! (?:is|was) (?:it|that)\b)"
    r"|\bi (?:work|live|study|grew up|was born) (?:at|in|for|on)\b|\bi'?m (?:from|allergic|a |an )",
    re.I,
)
_QUESTION = re.compile(r"\?\s*$|^\W*(?:what|which|who|whom|whose|when|where|why|how|did|do|does|is|are|can|could|would|will|should|remind|tell me|find|show|forget|delete)\b", re.I)


def about_him(text: str) -> bool:
    """A statement about himself worth keeping ("Trác is my younger brother")."""
    return bool(_ABOUT_HIM.search(text or "")) and not _QUESTION.search(text or "")


def asks(text: str) -> bool:
    """A question (or "remind me", "do you remember") - not a statement he wants kept."""
    return bool(_QUESTION.search(text or "")) or bool(re.search(r"\bdo you remember\b|\bremind me\b", text or "", re.I))


def asks_past(text: str) -> bool:
    # a date alone isn't the past: "what should I cook tonight?" looks ahead (it once
    # pulled 9 memories, ~700 tokens, into a dinner question) - and "remind me what
    # today's date is" is about now
    if _NOW.search(text or ""):
        return False
    return bool(_PAST.search(text or "")) or bool(when(text) and _PAST_VERB.search(text or ""))


_NOW = re.compile(r"\btoday'?s date\b|\bwhat (?:day|time|date|year|month) (?:is it|it is)\b|\bthe (?:date|time) (?:today|now)\b", re.I)


_PAST_VERB = re.compile(r"\b(?:did|was|were|had|said|told|talked|spoke|chatted|discussed|asked|mentioned|went|happened|looked|found|heard|learned|watched|read)\b", re.I)


@dataclass
class Recalled:
    section: str = ""
    items: list[Item] = field(default_factory=list)
    ms: float = 0.0
    past: bool = False


LAST = Recalled()


def recall(text: str, session: str = "", store: Store | None = None, now: float | None = None) -> Recalled:
    """What she remembers that bears on `text`, as a context section within the token
    budget: by date when he names one, else by relevance. Nothing from this session
    (it is in the history already). The last one is kept in LAST (its time, for the
    turn log)."""
    global LAST
    LAST = _recall(text, session, store, now)
    return LAST


def _recall(text: str, session: str, store: Store | None, now: float | None) -> Recalled:
    if not POLICY.enabled:
        return Recalled()
    started = time.perf_counter()
    store = store or current()
    now = now or time.time()
    past = asks_past(text)
    budget = POLICY.recall_budget_tokens if past else POLICY.budget_tokens
    try:
        span = when(text, datetime.fromtimestamp(now))
        if span is not None and past:
            # "what did we talk about last week": that span's exchanges, oldest first,
            # thinned evenly to the budget - plus what he asked about by topic in it
            found = store.between(span[0], span[1], exclude_session=session)
            topical = [i for i in store.search(text, k=4, exclude_session=session) if span[0] <= i.at < span[1]]
            found = sorted({i.id: i for i in [*topical, *found]}.values(), key=lambda i: i.at)
        else:
            found = store.search(text, k=8, exclude_session=session)
    except Exception:  # noqa: BLE001 - a broken memory is no memory, never a broken turn
        log.exception("memory: recall failed")
        return Recalled(ms=(time.perf_counter() - started) * 1000)
    chosen, used = [], 0
    # how he wants things ("I prefer short answers", "call me Ken") holds in every
    # session, relevant or not - a small slice of the budget, newest first
    standing = [i for i in store.standing(exclude_session=session) if i.id not in {f.id for f in found}]
    for item in standing:
        if used + item.tokens() > STANDING_TOKENS:
            break
        chosen.append(item)
        used += item.tokens()
    if span is not None and past and found:
        # spread across the span rather than its first day
        step = max(1, len(found) // max(1, budget // 60))
        found = found[::step]
    for item in found:
        cost = item.tokens()
        if used + cost > budget:
            if item.kind == "turn":
                continue
            item.text = item.text[: max(0, int((budget - used - 20) * CHARS_PER_TOKEN))].rsplit(" ", 1)[0] + "..."
            cost = item.tokens()
            if used + cost > budget or len(item.text) < 40:
                continue
        chosen.append(item)
        used += cost
    ms = (time.perf_counter() - started) * 1000
    if not chosen:
        section = RECALL_HINT + "\n## From your memory\nNothing from earlier sessions is kept about this. Unless this conversation has it, you do not know it: say so in one short sentence (\"I don't remember you telling me about that\") - never make up an answer." if past else ""
        return Recalled(section, [], ms, past)
    lines = [item.line(now) for item in (sorted(chosen, key=lambda i: i.at) if span else chosen)]
    head = "## From your memory (earlier sessions - his words and yours; dates are when)"
    if span is not None and past:
        head += f"\nWhat you remember from {span[2]}:"
    section = "\n".join([*([RECALL_HINT] if past else []), head, *lines])
    return Recalled(section, chosen, ms, past)


# ---- forgetting -------------------------------------------------------------------


def to_forget(about: str, store: Store | None = None) -> list[Item]:
    """What 'forget what I told you about X' means: the kept items about X - by his
    words where they match (a name), else the closest in meaning, tightly."""
    store = store or current()
    keys = set(words(about))
    found = store.search(about, k=40)
    with store._lock:
        by_words = [i for i in store.items if keys and keys <= set(words(f"{i.about} {i.text}"))]
    picked = {i.id: i for i in by_words}
    for i in found:
        if i.score >= POLICY.min_similarity + 0.08 or (keys and keys & set(words(f"{i.about} {i.text}"))):
            picked.setdefault(i.id, i)
    return sorted(picked.values(), key=lambda i: i.at)


def forget(items: list[Item], store: Store | None = None) -> dict:
    """Delete `items` - from the memory, and their words from the logs and his voice
    turns, so nothing kept still says it."""
    store = store or current()
    gone = store.delete([i.id for i in items])
    phrases = set()
    for i in items:
        if i.kind == "turn":
            phrases.update(re.findall(r'"([^"]{12,})"', i.text))
        else:
            phrases.add(i.text)
    phrases = {p for p in phrases if len(p) >= 12}
    scrubbed = scrub(phrases) if store is HIS else {}
    log.info("memory: forgot %d item(s); scrubbed %s", gone, scrubbed)
    return {"deleted": gone, **scrubbed}


def scrub(phrases: set[str], logs: Path = LOGS, voice: Path = VOICE_TURNS) -> dict:
    """His words out of every file that kept them: turns.jsonl rows go, log lines are
    blanked, voice turns (audio and transcript) are deleted."""
    if not phrases:
        return {}
    folded = [fold(p) for p in phrases]
    # JSON files keep "Trác" as "Trác": read the escapes back first
    unescape = lambda s: re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)  # noqa: E731
    hit = lambda line: any(p in fold(unescape(line)) for p in folded)  # noqa: E731
    out = {"log_lines": 0, "voice_turns": 0}
    for path in [logs / "turns.jsonl", *sorted(logs.glob("core.log*"))]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue
        kept, changed = [], 0
        for line in lines:
            if hit(line):
                changed += 1
                if path.suffix != ".jsonl":
                    kept.append(line[:24] + "[forgotten at his request]\n")
            else:
                kept.append(line)
        if changed:
            out["log_lines"] += changed
            path.write_text("".join(kept), encoding="utf-8")
    if voice.exists():
        for meta in voice.glob("*/*.json"):
            try:
                if hit(meta.read_text(encoding="utf-8", errors="replace")):
                    for f in meta.parent.glob(meta.stem + ".*"):
                        f.unlink(missing_ok=True)
                    out["voice_turns"] += 1
            except OSError:
                continue
    return out


# ---- what was there before memory ---------------------------------------------


def backfill(store: Store | None = None) -> int:
    """Once: the research and lecture summaries already on disk become memories."""
    store = store or HIS
    if store.meta("backfilled"):
        return 0
    n = 0
    from tools import research as research_tool

    for path in sorted(Path(research_tool.STORE).glob("*.json")):
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        question, answer = r.get("question", ""), r.get("answer") or r.get("summary") or ""
        if question and answer:
            store.add("research", str(answer)[:700], question[:160], at=path.stat().st_mtime)
            n += 1
    lectures = ROOT / "core" / "data" / "lectures"
    for path in sorted(lectures.glob("*/summary.json")) if lectures.exists() else []:
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = s.get("meta") or {}
        if s.get("overview"):
            store.add("lecture", lecture_text(s), lecture_title(s, meta), at=meta.get("started") or path.stat().st_mtime)
            n += 1
    store.meta("backfilled", str(time.time()))
    log.info("memory: %d earlier research and lecture summaries kept", n)
    return n


def lecture_title(summary: dict, meta: dict | None) -> str:
    """"the lecture of Mon 12 Oct: Eigenvalues" - a capture has no title of its own."""
    started = (meta or {}).get("started")
    day = datetime.fromtimestamp(started).strftime("%a %d %b") if started else "a past day"
    first = next((s.get("title") for s in summary.get("sections", []) if s.get("title")), "")
    return f"the lecture of {day}" + (f": {first}" if first else "")


def lecture_text(summary: dict) -> str:
    sections = "; ".join(s.get("title", "") for s in summary.get("sections", []) if s.get("title"))
    return f"{summary.get('overview', '')} Sections: {sections}".strip()
