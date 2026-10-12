"""Voice: the microphone to her conversation, and back.

  asleep      only a wake phrase counts ("Hey Irene", "Irene Adler")
  awake       for follow_up_seconds after she finishes (or after LISTEN), anything
              he says is for her - no wake word; bare "Irene" is fine too
  speaking    she is talking: the mic listens for barge-in, and if he speaks over
              her she stops at once and hears him

A wake phrase on its own is a summon: "Hey Irene" plays a random entrance,
"Irene Adler" the Victorian one; with words after it ("Hey Irene, what time is
it?") she just answers. Everything he says goes through exactly the path a typed
command does (Core.on_command), so fillers, entrance context and her cues all
hold over voice. A transcript Whisper was not sure of is never acted on: she
asks him to say it again.

The HUD hears about it as {"type": "voice", "phase": ...}:
  listening  awake and waiting for him     hearing   he is talking
  silence    remainingMs / totalMs of the end-of-speech wait (her countdown)
  thinking   transcribing                  asleep    back to wake words only
  off        no microphone
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from . import react as cues
from . import stt, wake
from .listen import Event, MicListener, complete_phrase, pitch_falls
from .voice_data import VoiceData, similarity
from .wer import number_words

if TYPE_CHECKING:
    from .app import Core

log = logging.getLogger("irene.voice")

SAY_AGAIN = ("Sorry, say that again?", "Sorry - once more?", "I didn't quite catch that. Say it again?")
# how long LISTEN waits for him to start
LISTEN_WINDOW_S = 10.0
# barge-in: her volume the instant he may be talking over her, and how much more
# of him to hear before deciding it is really him
BARGE_DUCK = 0.3
BARGE_LISTEN_S = 0.6
# paused over a maybe-him: how long before she carries on if no utterance ends
# (and the longest she waits while he is still talking)
BARGE_HOLD_S = 4.0
# an unsure first look gets a second, on only the newest audio
BARGE_SECOND_LOOK_S = 0.8
BARGE_TAIL_S = 1.5
# stopping her takes a surer transcript than talking to her when she is quiet:
# live, his "What are you doing?" over her came through at -0.2; a voice from the
# room she then stopped for ("That's what the dark bar definitely happens.") at -0.76
BARGE_MIN_LOGPROB = -0.6
BARGE_HOLD_MAX_S = 12.0
# the speculative start: if he goes on talking within this long of her answering
# his first words, it was one sentence - her early answer is dropped and the two
# halves go through together
MERGE_S = 1.5
# ...but only once the new sound is checked as him: this much of it first (Round 11:
# her own answer's sound and voice, leaking past the echo canceller, raised a VAD
# "speech" event 0.8 s in - her answer was cut after two words, his first words
# waited for his next sentence, and the model answered both at once)
CONTINUE_CHECK_S = 0.6
# a dropped early answer whose "he went on" turns out to be nothing of his: his
# first words are answered on their own after this long, never left waiting
CARRY_FLUSH_S = 3.0
# one wake phrase can reach on_heard twice (the peek and the end of speech)
SUMMON_DEDUPE_S = 3.0


class Voice:
    def __init__(self, core: "Core", config: dict | None = None):
        self.core = core
        self.config = config or stt.settings()
        w = self.config["wake"]
        self.bare_while_awake = bool(w.get("bare_name_while_awake", True))
        self.follow_up_s = float(w.get("follow_up_seconds", 8))
        self.stt = stt.Transcriber(self.config)
        self.data = VoiceData(stt.ROOT / "core" / self.config["data"]["dir"], bool(self.config["data"].get("save_turns", True)))
        self.mic: MicListener | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.awake_until = 0.0
        # her window is on screen (the HUD says so): then she listens, no wake word -
        # whatever summoned her (a hotkey summon used to leave her asleep)
        self.visible = False
        self._peeking = False
        self._say_again = 0
        self._busy = False  # transcribing or handing a turn over
        # the speculative start: the first look's transcript, for the utterance it
        # ended early (generation, heard); and what was answered early, and when
        self.speculate = bool(self.config["end_of_speech"].get("speculative", True))
        self._draft: tuple[int, stt.Heard] | None = None
        self._early: tuple[float, str] | None = None
        self._carry: str | None = None
        self._early_origin = "replay"  # set with every early answer; never "mic" by default
        self.available = False
        # what she has said lately: her own voice coming back through the speakers
        # must never be taken for his (a barge-in, a wake phrase, a command)
        # A whole research answer is queued in one go and then spoken for up to a
        # minute: kept for all of it (6 lines used to push her early sentences out
        # before she had said them, and her echo of them got through as him)
        self.her_lines: collections.deque[tuple[float, str]] = collections.deque(maxlen=64)
        # while she is speaking (and 20 s after), everything queued for this answer
        # counts as hers, however long ago it was queued
        self._spoke_from = 0.0
        self._spoke_until = 0.0
        # a barge-in being checked: she is paused (Speaker.hold) until his whole
        # utterance is heard; when it started, and what the first look heard
        self._held_at: float | None = None
        self._held_first = ""
        # only his voice is ever acted on (speaker_id.py): a song, a video, the room
        # and her own voice through the speakers never become a turn or a barge-in.
        # Loaded in _ready (never in tests that build a Voice without a mic)
        spk = self.config.get("speaker") or {}
        self.speaker_check = bool(spk.get("enabled", True))
        self.speaker_threshold = float(spk.get("threshold", 0.45))
        self.verifier = None
        self._summoned_at = (-1e9, "")

    # ---- lifecycle -------------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> bool:
        self.loop = loop
        # what the mic heard and decided, in core/logs/voice.log (local only)
        from logging.handlers import RotatingFileHandler

        logs = stt.ROOT / "core" / "logs"
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / "voice.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
        # config voice.yaml debug: true also logs what the barge-in guard measures
        if self.config.get("debug"):
            handler.setLevel(logging.DEBUG)
            for name in ("irene.listen", "irene.voice"):
                logging.getLogger(name).setLevel(logging.DEBUG)
        for name in ("irene.voice", "irene.listen", "irene.corpus", "irene.stt"):
            logging.getLogger(name).addHandler(handler)
        if not self._open_mic():
            # no microphone, or still held by a previous run: keep trying
            self._retry = loop.create_task(self._reopen())
            return False
        return self._ready(loop)

    def _open_mic(self) -> bool:
        try:
            self.mic = MicListener(self.config, self._event, self._barge, self._level)
            self.mic.start()
            return True
        except Exception as error:  # no microphone, or it is in use
            log.warning("microphone not available (%s) - voice off for now", error)
            self.mic = None
            return False

    async def _reopen(self) -> None:
        while not self.available:
            await asyncio.sleep(5.0)
            if self._open_mic():
                assert self.loop is not None
                self._ready(self.loop)
                log.info("microphone open - voice on")
                self._hud({"phase": "asleep"})

    def _ready(self, loop: asyncio.AbstractEventLoop) -> bool:
        self.available = True
        self.core.bridge.state_listeners.append(self._on_state)
        if self.core.speaker is not None:
            mic = self.mic
            self.core.speaker.taps.append(mic.feed_playback)
        self._watcher = loop.create_task(self._watch())
        if self.speaker_check:
            loop.run_in_executor(None, self._load_verifier)
        return True

    def _load_verifier(self) -> None:
        from .speaker_id import Verifier

        # on the CPU by default: the GPU's 16 GB are full with the model, Whisper and
        # her voice, and a full card stalls her face (an embedding is ~50 ms on CPU)
        verifier = Verifier(self.speaker_threshold, device=str((self.config.get("speaker") or {}).get("device", "cpu")))
        if not verifier.available:
            log.error("speaker check OFF: no ECAPA model in core/models/ecapa-voxceleb - every voice is acted on")
            return
        try:
            if verifier.enrol():
                self.verifier = verifier
                log.info("speaker check ON: only his voice is acted on (threshold %.2f)", verifier.threshold)
        except Exception:
            log.exception("speaker check OFF: enrolling his voiceprint failed")

    async def not_his_voice(self, audio: np.ndarray | None, where: str) -> str:
        """"" if this is him (or the check is off); else why not - logged with the
        similarity, so the threshold can be tuned from core/logs/voice.log."""
        verifier = self.verifier
        if verifier is None or audio is None or len(audio) == 0:
            return ""
        ok, score = await asyncio.get_running_loop().run_in_executor(None, verifier.is_him, audio)
        if ok:
            log.info("speaker check (%s): him (similarity %.2f)", where, score)
            return ""
        log.info("speaker check (%s): NOT his voice - ignored (similarity %.2f < %.2f, %.1f s)", where, score, verifier.threshold, len(audio) / 16000)
        return f"not his voice ({score:.2f})"

    async def _watch(self) -> None:
        """Tell the HUD when the follow-up window runs out: back to wake words only.
        And keep the mic alive: a device that stops delivering audio (unplugged,
        default changed, a driver hiccup) is reopened, never left silently deaf."""
        was = False
        while True:
            await asyncio.sleep(0.5)
            mic = self.mic
            if mic is not None and not self.core.corpus.active and mic.last_block_age > 3.0:
                log.error("microphone delivered nothing for %.1f s - reopening it", mic.last_block_age)
                self._hud({"phase": "off"})
                try:
                    mic.stop()
                except Exception:
                    log.exception("closing the dead microphone failed")
                if self._open_mic():
                    self.core.speaker and self.core.speaker.taps.append(self.mic.feed_playback)
                    self._hud({"phase": "listening" if self.awake else "asleep"})
                    log.info("microphone reopened")
                continue
            now = self.awake
            if was and not now and self.core.bridge.current_state not in ("speaking", "thinking"):
                self._hud({"phase": "asleep"})
            was = now

    def stop(self) -> None:
        if self.mic:
            self.mic.stop()

    @property
    def awake(self) -> bool:
        return self.visible or time.monotonic() < self.awake_until

    def set_visible(self, visible: bool) -> None:
        """Her window was shown or hidden: visible, she listens without a wake word."""
        if visible == self.visible:
            return
        self.visible = visible
        if not visible:
            # hidden is "go away": wake phrases only from now, no follow-up window
            self.awake_until = 0.0
        log.info("window %s: %s", "shown" if visible else "hidden", "listening, no wake word" if visible else "wake words only")
        if self.available:
            self._hud({"phase": "listening" if self.awake else "asleep"})

    def wake_for(self, seconds: float) -> None:
        self.awake_until = time.monotonic() + seconds

    def sleep(self) -> None:
        self.awake_until = 0.0
        self._hud({"phase": "listening" if self.awake else "asleep"})

    # ---- from the HUD / Core ---------------------------------------------------

    def heard_her(self, text: str) -> None:
        """A line she is saying (Core calls this for everything she speaks)."""
        if text and text.strip():
            self.her_lines.append((time.monotonic(), text.strip()))

    def _her_recent(self, within_s: float = 20.0) -> list[str]:
        """Her lines that could be coming back through the speakers now."""
        now = time.monotonic()
        speaking = getattr(getattr(self.core, "bridge", None), "current_state", None) == "speaking"
        until = now if speaking else self._spoke_until
        # this answer's lines: queued up to half a minute before she began saying them
        this_answer = now - until <= within_s and self._spoke_from > 0
        return [line for at, line in self.her_lines if now - at <= within_s or (this_answer and at >= self._spoke_from - 30.0)]

    def is_her(self, text: str, within_s: float = 20.0) -> bool:
        """Whether `text` is her own recent speech, heard back through the speakers."""
        if not text.strip():
            return False
        recent = self._her_recent(within_s)
        if not recent:
            return False
        joined = " ".join(recent)
        heard = " ".join(_echo_words(text))
        return any(similarity(heard, " ".join(_echo_words(line))) >= 0.6 for line in recent) or _covered(text, joined) or _spelled_like(text, joined)

    async def listen_now(self) -> bool:
        """The LISTEN button: awake without a wake word."""
        if not self.available:
            return False
        self.wake_for(LISTEN_WINDOW_S)
        self._hud({"phase": "listening"})
        return True

    def _on_state(self, state: str) -> None:
        now = time.monotonic()
        if state == "speaking" and now - self._spoke_until > 2.0:
            self._spoke_from = now
        if state != "speaking":
            self._spoke_until = now
        if not self.mic:
            return
        # while she talks the mic only listens for barge-in
        if self.mic.barge != (state == "speaking"):
            log.debug("state %s: barge %s", state, "on" if state == "speaking" else "off")
        self.mic.barge = state == "speaking"
        if state == "listening" and self.mic.dump:
            # debug: what the echo canceller was given during her last answer
            try:
                pairs = list(self.mic.dump)
                self.mic.dump.clear()
                np.savez_compressed(stt.ROOT / "core" / "logs" / "aec_dump.npz", mic=np.concatenate([m for m, _ in pairs]), ref=np.concatenate([r for _, r in pairs]))
                log.debug("aec dump: %d blocks", len(pairs))
            except Exception:
                log.exception("aec dump failed")
        if state == "listening" and self.awake:
            # she has finished: a follow-up needs no wake word for a while
            self.wake_for(self.follow_up_s)
            self._hud({"phase": "listening"})
        elif state == "listening":
            # her window ran out while she was busy: the HUD must not show the mic
            # while only a wake phrase is heard (the "just a mic, and she ignores
            # everything" freeze)
            self._hud({"phase": "asleep"})

    # ---- from the mic thread ---------------------------------------------------

    def _hud(self, message: dict) -> None:
        self.core.bridge.send_threadsafe({"type": "voice", **message})

    def _level(self, rms: float) -> None:
        corpus = getattr(self.core, "corpus", None)
        if corpus is not None and corpus.active:
            self.core.bridge.send_threadsafe({"type": "mic_level", "value": round(min(1.0, rms * 8), 3)})

    def _barge(self, audio: np.ndarray) -> None:
        assert self.loop is not None
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._check_barge(audio)))

    async def _check_barge(self, audio: np.ndarray) -> None:
        """Loud, sure speech over her. She ducks at once - he hears her yield the
        moment he starts - and listens a little longer, so Whisper has enough of him
        to be sure: him, and she stops; her own echo or the room, and she comes back
        up. The words decide."""
        speaker = self.core.speaker
        if speaker is not None:
            speaker.gain = BARGE_DUCK
        try:
            if not self.stt.loaded:
                await asyncio.get_running_loop().run_in_executor(None, self.stt.load)
            await asyncio.sleep(BARGE_LISTEN_S)
            if self.mic is not None and self.mic.endpointer.speaking:
                audio = self.mic.endpointer.audio()
            # her own voice through the speakers is not his: that ends it here
            if await self.not_his_voice(audio, "barge-in"):
                if self.mic:
                    self.mic.endpointer.reset()
                    self.mic.barge = self.core.bridge.current_state == "speaking"
                return
            heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(audio, beam_size=1, prompt=False))
            why = self.not_him(heard)
            log.info(
                "barge candidate: heard %r (logprob %.2f, no-speech %.2f, %.1f s) -> %s",
                heard.text, heard.avg_logprob, heard.no_speech_prob, heard.seconds, f"no: {why}" if why else "maybe him - pausing her to hear all of it",
            )
            if why and why != "her own words" and self.mic is not None and self.mic.endpointer.speaking:
                # a second look at only the newest audio: the first starts ~0.8 s
                # before the trigger, mostly her echo - live, his replayed "What are
                # you doing?" was heard as "offers upon us keep forward" (her words,
                # unsure) and thrown away
                await asyncio.sleep(BARGE_SECOND_LOOK_S)
                if self.mic is not None and self.mic.endpointer.speaking:
                    tail = self.mic.endpointer.audio()[-int(BARGE_TAIL_S * 16000):]
                    heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(tail, beam_size=1, prompt=False))
                    why = self.not_him(heard)
                    log.info(
                        "barge second look: heard %r (logprob %.2f, %.1f s) -> %s",
                        heard.text, heard.avg_logprob, heard.seconds, f"no: {why}" if why else "maybe him - pausing her to hear all of it",
                    )
            if why:
                if self.mic:
                    self.mic.guard.coupling *= 1.2
                    self.mic.endpointer.reset()
                    self.mic.barge = self.core.bridge.current_state == "speaking"
                return
            if self._early is not None and time.monotonic() - self._early[0] <= MERGE_S:
                # her early answer to his first words, and he is still going: that one
                # is dropped at once (the speculative start), nothing to hold
                await self._barge_in()
                return
            self._hold(heard.text)
        finally:
            if speaker is not None:
                speaker.gain = 1.0

    def not_him(self, heard: stt.Heard) -> str:
        """Why a transcript heard over her is NOT him talking - "" if it is. Only
        confident human speech that is not her own voice stops her."""
        words = _words(heard.text)
        # her name always stops her ("Irene, wait") - never taken for her echo
        named = wake.find(heard.text, awake=True, bare_while_awake=True) is not None
        return (
            "nothing" if not words
            else "not English" if not heard.english
            else "her own words" if not named and self.is_her(heard.text)
            else "mostly her words" if not named and _mostly_hers(heard.text, " ".join(self._her_recent()))
            else "Whisper's noise phrase" if heard.hallucinated
            else "unsure" if not self.stt.confident(heard)
            else f"not sure enough to stop her (logprob {heard.avg_logprob:.2f})" if heard.avg_logprob < BARGE_MIN_LOGPROB
            else "too short" if len(words) < 2
            else ""
        )

    def _hold(self, first: str) -> None:
        """Maybe him: she pauses mid-word - nothing is cancelled - while the rest of
        what he says is heard. Only the whole utterance decides."""
        speaker = self.core.speaker
        if speaker is not None:
            speaker.hold()
        self._held_at = time.monotonic()
        self._held_first = first
        self._hud({"phase": "hearing"})
        started = self._held_at
        asyncio.get_running_loop().call_later(BARGE_HOLD_S, lambda: asyncio.ensure_future(self._hold_expired(started)))

    async def _hold_expired(self, started: float) -> None:
        if self._held_at != started:
            return
        if self.mic is not None and self.mic.endpointer.speaking and time.monotonic() - started < BARGE_HOLD_MAX_S:
            # he is still talking: give it longer
            asyncio.get_running_loop().call_later(1.0, lambda: asyncio.ensure_future(self._hold_expired(started)))
            return
        self._carry_on("nothing followed")

    def _carry_on(self, why: str) -> None:
        """Not him after all: she picks up exactly where she paused."""
        log.info("barge-in: not him (%s) - she carries on where she paused", why)
        self._held_at = None
        speaker = self.core.speaker
        if speaker is not None:
            speaker.release()
        if self.mic is not None:
            self.mic.endpointer.reset()
            self.mic.barge = self.core.bridge.current_state == "speaking"
        self._hud({"phase": "listening" if self.awake else "asleep"})

    def _event(self, event: Event) -> None:
        """From the mic thread: onto the event loop - to the corpus recorder while a
        session runs, to the conversation otherwise."""
        assert self.loop is not None
        corpus = getattr(self.core, "corpus", None)
        if corpus is not None and corpus.active:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(corpus.on_event(event)))
            return
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._handle(event)))

    async def _barge_in(self) -> None:
        """He spoke over her: stop talking at once and hear him."""
        log.info("barge-in: he spoke over her")
        core = self.core
        if self._continued():
            # her early answer to his first words: he was still going (this path is
            # the barge check's: the voice and words were already found to be his)
            await core.retract_turn(why="he spoke over her early answer")
            self.wake_for(self.follow_up_s)
            self._hud({"phase": "hearing"})
            return
        if core.speaker:
            core.speaker.stop()
        if core._turn and not core._turn.done():
            core._turn.cancel()
            # let the cancel land: his words must not meet a "she is busy" guard
            await asyncio.wait([core._turn], timeout=2.0)
        await core.on_summon_skip({})
        self.wake_for(self.follow_up_s)
        self._hud({"phase": "hearing"})
        await core.bridge.state("listening")

    async def _handle(self, event: Event) -> None:
        skit = getattr(self.core, "skit", None)
        if skit is not None and skit.active:
            await self._skit_event(event, skit)
            return
        if event.kind in ("speech", "end"):
            log.debug("endpointer %s (state %s, awake %s)", event.kind, self.core.bridge.current_state, self.awake)
        if event.kind == "speech" and getattr(self.core, "booting", False):
            # he may be speaking over her boot-up: a half-second of it, checked as his
            asyncio.ensure_future(self._skip_boot_if_him())
        if event.kind == "speech":
            # lazy: Whisper loads the first time anyone speaks, while he is still talking
            if not self.stt.loaded:
                asyncio.get_running_loop().run_in_executor(None, self.stt.load)
            if self._early is not None and time.monotonic() - self._early[0] <= MERGE_S:
                # he paused, she started on his first words - and something is heard.
                # Him going on? Checked before anything is dropped: her own voice or
                # sound, or the room, must never cut her answer (she carries on)
                asyncio.ensure_future(self._check_continued(event.generation))
            if self.awake:
                self.wake_for(max(self.follow_up_s, 30.0))  # his turn runs as long as he talks
                self._hud({"phase": "hearing"})
        elif event.kind == "resume" and self.awake:
            self._hud({"phase": "hearing"})
        elif event.kind == "silence" and self.awake:
            self._hud({"phase": "silence", "remainingMs": round(event.remaining * 1000), "totalMs": round(event.total * 1000)})
        elif event.kind == "peek":
            if not self.awake and self.stt.loaded and not self._peeking:
                asyncio.ensure_future(self._peek(event))
        elif event.kind == "check":
            asyncio.ensure_future(self._judge(event))
        elif event.kind == "end" and event.audio is not None:
            await self._utterance(event.audio, event.generation)

    async def _skit_event(self, event: Event, skit) -> None:
        """A skit is running (skit.py): his voice only marks his turns - nothing is
        transcribed, nothing is a wake phrase, a command or a barge-in. The HUD
        still sees him talking (hearing, the silence countdown), as it always does."""
        if event.kind == "speech" and self.visible:
            self._hud({"phase": "hearing"})
        elif event.kind == "silence" and self.visible:
            self._hud({"phase": "silence", "remainingMs": round(event.remaining * 1000), "totalMs": round(event.total * 1000)})
        elif event.kind == "end" and event.audio is not None:
            if await self.not_his_voice(event.audio, "skit"):
                return
            said = None
            if skit.wants_words:
                # a wake beat: which phrase it was (Irene Adler picks her Victorian
                # scene) - the only words a skit ever looks at
                loop = asyncio.get_running_loop()
                if not self.stt.loaded:
                    await loop.run_in_executor(None, self.stt.load)
                heard = await loop.run_in_executor(None, lambda: self.stt.transcribe(event.audio))
                said = heard.text
                log.info("skit wake beat: heard %r", said)
            skit.heard(len(event.audio) / 16000, said)
            if self.visible:
                self._hud({"phase": "listening"})

    async def _skip_boot_if_him(self) -> None:
        await asyncio.sleep(0.5)
        if self.mic is None or not self.mic.endpointer.speaking or not getattr(self.core, "booting", False):
            return
        if await self.not_his_voice(self.mic.endpointer.audio(), "speech over the boot-up"):
            return
        await self.core.skip_boot()

    async def _peek(self, event: Event) -> None:
        """Asleep, and someone has been talking for a while: is "Hey Irene" in the
        last few seconds? Room talk never pauses long enough for the end-of-speech
        check, so the wake phrase used to be swallowed into it and never heard."""
        self._peeking = True
        try:
            if await self.not_his_voice(event.audio, "wake inside speech"):
                return
            heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(event.audio, beam_size=1, prompt=False))
            found = wake.find_within(heard.text) if heard.english and not self.is_her(heard.text) else None
            if found is None or self.mic is None or self.mic.endpointer.generation != event.generation:
                return
            log.info("summon path 0: wake phrase inside ongoing speech (%s) - cut it out", found.phrase)
            self.mic.endpointer.reset()
            said = "Irene Adler." if found.phrase == "adler" else "Hey Irene."
            await self.on_heard(stt.Heard(said, heard.avg_logprob, heard.no_speech_prob, heard.seconds, heard.ms), event.audio, False)
        finally:
            self._peeking = False

    def _continued(self) -> bool:
        """He is talking again right after she answered his first words early."""
        if self._early is None or time.monotonic() - self._early[0] > MERGE_S:
            return False
        self._carry = self._early[1]
        self._early = None
        log.info("speculative start: he went on - dropping the early answer (%r waits for the rest of his sentence)", self._carry)
        carried = self._carry
        asyncio.get_running_loop().call_later(CARRY_FLUSH_S, lambda: asyncio.ensure_future(self._flush_carry(carried)))
        return True

    async def _check_continued(self, generation) -> None:
        """Speech right after her early answer: is it HIM going on? A moment of it,
        checked against his voiceprint and her own words; only then is her answer
        dropped. Anything else and she carries on - logged either way."""
        await asyncio.sleep(CONTINUE_CHECK_S)
        if self._early is None or self.mic is None:
            return
        if not self.mic.endpointer.speaking:
            log.info("speculative start: a blip after her early answer, gone in %.1f s - she carries on", CONTINUE_CHECK_S)
            return
        audio = self.mic.endpointer.audio()[-int(1.5 * 16000):]
        if await self.not_his_voice(audio, "after her early answer"):
            log.info("speculative start: the sound after her early answer is not his voice (her echo, her sound, the room) - she carries on")
            return
        heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(audio, beam_size=1, prompt=False))
        why = self.not_him(heard) if heard.text.strip() else "nothing"
        if why and why != "too short":
            log.info("speculative start: after her early answer, heard %r -> not him (%s) - she carries on", heard.text, why)
            return
        if self._continued():
            await self.core.retract_turn(why=f"he went on: {heard.text!r}")

    async def _flush_carry(self, carried: str) -> None:
        """Her early answer was dropped because he seemed to go on - and nothing of
        his followed: his first words get their answer now, on their own."""
        if self._carry != carried:
            return  # used: his sentence ended and went through with it
        if self.mic is not None and self.mic.endpointer.speaking:
            # still talking: the rest is coming; look again in a moment
            asyncio.get_running_loop().call_later(1.0, lambda: asyncio.ensure_future(self._flush_carry(carried)))
            return
        self._carry = None
        if self.mic is not None:
            self.mic.endpointer.reset()
        log.info("speculative start: nothing of his followed in %.1f s - answering %r on its own", CARRY_FLUSH_S, carried)
        await self.core.on_command({"text": carried, "via": "voice", "_origin": self._early_origin})

    def _origin(self) -> str:
        """Whose words these are for the sandbox: his live mic, or a dev replay."""
        replayed = bool(self.mic is not None and getattr(self.mic, "_replaying", False))
        return "replay" if replayed else "mic"

    def _small_talk(self, text: str) -> bool:
        quick = getattr(self.core, "quick", None)
        if quick is None:
            return False
        found = wake.find(text, awake=True, bare_while_awake=True)
        return quick.match(found.rest if found and found.rest else text) is not None

    async def _judge(self, event: Event) -> None:
        """Did the sentence clearly end? A quick look at the words and the pitch.

        If it did - or it is small talk, which ends clearly by its nature - she
        answers from this look at once (the speculative start): the utterance ends
        at the next silent block, not after the rest of the wait."""
        if not self.stt.loaded or event.audio is None or self.mic is None:
            return
        heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(event.audio, beam_size=1))
        complete = complete_phrase(heard.text)
        ended = complete and (heard.text.rstrip().endswith("?") or pitch_falls(event.audio))
        early = self.speculate and complete and self.stt.confident(heard) and (ended or self._small_talk(heard.text))
        log.debug("end-of-speech check: %s", "answer now" if early else "ended" if ended else "keep listening")
        if early:
            self._draft = (event.generation, heard)
        self.mic.endpointer.verdict(ended or early, event.generation, now=early)

    async def _utterance(self, audio: np.ndarray, generation: int | None = None) -> None:
        if self._held_at is not None:
            await self._decide_barge(audio)
            return
        if await self.not_his_voice(audio, "utterance"):
            # never transcribed, never a turn, never reaches the model
            self._draft = None
            if self.awake:
                self._hud({"phase": "listening"})
            if self._carry is not None:
                # his first words were held for "the rest" - and the rest is not his:
                # they are answered on their own, never left waiting for his next turn
                carried, self._carry = self._carry, None
                log.info("speculative start: what followed was not his voice - answering %r on its own", carried)
                await self.core.on_command({"text": carried, "via": "voice", "_origin": self._early_origin})
            return
        was_awake = self.awake
        if was_awake:
            self._hud({"phase": "thinking"})
        loop = asyncio.get_running_loop()
        draft = self._draft[1] if self._draft and self._draft[0] == generation else None
        self._draft = None
        carry, self._carry = self._carry, None
        if draft is not None:
            await self._answer_early(_joined(carry, draft), carry, audio, was_awake or self.awake or carry is not None)
            return
        heard = _joined(carry, await loop.run_in_executor(None, lambda: self.stt.transcribe(audio)))
        # the words are logged only once they turn out to be for her (on_heard):
        # the mic also hears other people in the room, and that is not ours to keep
        log.info("heard %.1f s (logprob %.2f, no-speech %.2f, %.0f ms)", heard.seconds, heard.avg_logprob, heard.no_speech_prob, heard.ms)
        await self.on_heard(heard, audio, was_awake or self.awake or carry is not None)

    async def _decide_barge(self, audio: np.ndarray) -> None:
        """She is paused over speech: the whole utterance, the full transcript. Him,
        and her answer stops for his turn; anything else, and she carries on."""
        self._draft = None
        if await self.not_his_voice(audio, "barge-in decision"):
            self._carry_on("not his voice")
            return
        heard = await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(audio))
        why = self.not_him(heard)
        log.info(
            "barge-in decision: heard %r (logprob %.2f, no-speech %.2f, %.1f s; first look %r) -> %s",
            heard.text, heard.avg_logprob, heard.no_speech_prob, heard.seconds, self._held_first, f"not him: {why}" if why else "him - she stops",
        )
        if why:
            self._carry_on(why)
            return
        self._held_at = None
        await self._barge_in()
        await self.on_heard(heard, audio, True)

    async def _answer_early(self, heard: stt.Heard, carry: str | None, audio: np.ndarray, awake: bool, final: stt.Heard | None = None) -> None:
        """The speculative start: act on the first look's words now. Small talk needs
        nothing more; anything else is checked against the full transcript (beam 3,
        while the model is already reading), and a turn begun on different words is
        started over with the right ones. `final`: that transcript, given (tests)."""
        log.info("heard %.1f s early (logprob %.2f, %.0f ms): answering now", heard.seconds, heard.avg_logprob, heard.ms)
        acted = await self.on_heard(heard, audio, awake)
        if acted != "command":
            return
        self._early = (time.monotonic(), heard.text)
        # where those words came from: anything re-sent with them keeps it (a dev
        # replay stays sandboxed - tools/sandbox.py)
        self._early_origin = self._origin()
        if self._small_talk(heard.text):
            return
        if final is None:
            final = _joined(carry, await asyncio.get_running_loop().run_in_executor(None, lambda: self.stt.transcribe(audio)))
        if _words(final.text) == _words(heard.text) or not (self.stt.confident(final) and final.english):
            return
        log.info("the full transcript differs from the first look - starting over with it")
        if self._early and self._early[1] == heard.text:
            self._early = (self._early[0], final.text)
        await self.on_heard(final, audio, True, retract=True)

    async def on_heard(self, heard: stt.Heard, audio: np.ndarray, awake: bool, retract: bool = False) -> str:
        """What to do with one utterance. Split out so it is testable without a mic.
        Returns what it did: command, summon, say_again or ignored. `retract`: this
        replaces the turn just started on a first look at the same words."""
        core = self.core
        if not _words(heard.text):
            log.info("nothing in it - ignored")
            return "ignored"
        if self.is_her(heard.text):
            log.info("heard her own voice back - ignored: %r", heard.text)
            return "ignored"
        if not heard.english:
            # other people talking in the room (or him, not to her): never acted on,
            # never answered, never kept
            log.info("not English - ignored, not saved")
            return "ignored"
        if heard.hallucinated:
            log.info("Whisper's noise phrase - ignored")
            return "ignored"
        found = wake.find(heard.text, awake=awake, bare_while_awake=self.bare_while_awake)
        if not awake and found is None:
            return "ignored"  # not for her - and not logged
        log.info("for her: %r", heard.text)
        text = found.rest if found else heard.text
        if found and not found.rest:
            # a wake phrase on its own: a summon (or, already awake, just "yes?")
            # one summon per utterance: the peek relabels any non-Adler wake "Hey Irene"
            kind = "adler" if found.phrase == "adler" else "summon"
            if kind == self._summoned_at[1] and time.monotonic() - self._summoned_at[0] < SUMMON_DEDUPE_S:
                # one "Hey Irene" heard twice: inside ongoing speech (path 0) and at its
                # end, 13 ms apart - live, that queued three entrances
                log.info("summon path 1: %r is the summon already under way - not again", heard.text)
                return "summon"
            self._summoned_at = (time.monotonic(), kind)
            log.info("summon path 1: wake phrase %r heard (%s, awake %s, window visible %s)", heard.text, found.phrase, awake, self.visible)
            self._save(audio, heard, {"wake": found.phrase, "action": "summon"})
            if found.phrase == "adler":
                await core.summon_by_voice(adler=True)
            elif not self.visible:
                # her window is not up: a wake phrase ALWAYS brings it, exactly like
                # ctrl+alt+i - even inside the follow-up window (live, 13 of 60 wakes
                # came while she was still "awake" from a summon whose window never
                # showed, and got only "Mm-hm?" with no window)
                await core.summon_by_voice(adler=False)
            else:
                await core.say("Mm-hm?", react=cues.fallback("hmm?", avoid=core.last_react))
            self.wake_for(60.0)  # through the entrance and greeting; then the follow-up window
            return "summon"
        if not self.stt.confident(heard):
            # addressed to her: a wake phrase, or right after she spoke (the follow-up
            # window). Awake only because she is on screen, an unsure transcript is
            # most likely the room - live, a 6.8 s murmur heard as "Show." asked
            # "say that again?" and cut off her research answer. And never over her
            # own turn in progress.
            addressed = found is not None or time.monotonic() < self.awake_until
            busy = getattr(core, "_turn", None) is not None and not core._turn.done()
            if not addressed or busy:
                log.info("unsure and %s - ignored", "she is busy" if busy else "not addressed to her")
                return "ignored"
            self._say_again += 1
            self._save(audio, heard, {"action": "say_again", "confident": False})
            self.wake_for(self.follow_up_s + 4)
            line = SAY_AGAIN[self._say_again % len(SAY_AGAIN)]
            # a puzzled head tilt, not a facepalm: it is the mic's fault, not his
            await core.say(line, react=cues.of_family(("headTilt", "sheepish", "confused"), avoid=core.last_react))
            return "say_again"
        busy = getattr(core, "_turn", None) is not None and not core._turn.done()
        if busy and found is None and not retract:
            # she is working on something: only her name interrupts it ("Irene,
            # stop"). Live, room talk ("Look into it. Let me look out.") heard while
            # she researched cancelled the answer and ran a nonsense search
            log.info("she is busy - speech without her name does not interrupt")
            return "ignored"
        corrected = self.data.correction_for(text, "spoken")
        if not retract:
            self._save(audio, heard, {"wake": found.phrase if found else None, "action": "command", "text": corrected or text})
        self.wake_for(60.0)  # she is working on it; the window restarts when she finishes
        # his voice, or a dev replay of it from a test script (never real: tools/sandbox.py)
        command = {"text": corrected or text, "via": "voice", "_origin": self._origin()}
        if retract:
            command["retract"] = True
        await core.on_command(command)
        return "command"

    def _save(self, audio: np.ndarray, heard: stt.Heard, meta: dict) -> None:
        try:
            self.data.save_turn(audio, heard.text, {"avg_logprob": round(heard.avg_logprob, 3), "no_speech_prob": round(heard.no_speech_prob, 3), "ms": round(heard.ms), **meta})
        except OSError as error:
            log.warning("could not save the voice turn: %s", error)


def _words(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _joined(carry: str | None, heard: stt.Heard) -> stt.Heard:
    """The first half of a sentence he paused in (answered early, then dropped),
    joined to the rest."""
    if not carry:
        return heard
    import dataclasses

    return dataclasses.replace(heard, text=f"{carry.rstrip()} {heard.text.lstrip()}")


_SPLITS = {"onto": "on to", "into": "in to", "cannot": "can not", "gonna": "going to", "wanna": "want to", "gotta": "got to", "alright": "all right"}


_ORDINAL_END = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def _ordinal(n: int) -> str:
    words = number_words(n).split()
    last = words[-1]
    words[-1] = _ORDINAL_END.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return " ".join(words)


def _spell_numbers(t: str) -> str:
    """Numbers as she SAYS them, the way Whisper may write them back: her "8th Dan"
    is spoken "eighth Dan" and came back as "eighth day an" - live (Round 8) the
    digits never matched the words, and she stopped to answer her own sentence."""
    import re

    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", t)
    t = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: _ordinal(int(m.group(1))), t)
    # a year is said in pairs: 1939 -> nineteen thirty nine
    t = re.sub(r"\b(1[1-9]|20)(\d\d)\b", lambda m: f"{number_words(int(m.group(1)))} {number_words(int(m.group(2))) if m.group(2) != '00' else 'hundred'}", t)
    t = re.sub(r"\d+(?:\.\d+)?", lambda m: " point ".join(number_words(int(p)) for p in m.group(0).split(".")) if len(m.group(0)) < 10 else m.group(0), t)
    return t.replace("-", " ")


def _echo_words(text: str) -> list[str]:
    """Words as she and Whisper may each write them: her [laugh] tags out,
    contractions and "onto" spelled out, so "can't hold onto it" and "can hold on
    to it" line up."""
    import re

    t = (text or "").lower().replace("\u2019", "'")
    t = re.sub(r"\[[^\]]*\]|<[^>]+>", " ", t)
    t = _spell_numbers(t)
    t = re.sub(r"\b(can|won|don|didn|isn|wasn|aren|doesn|couldn|wouldn|shouldn)'t\b", lambda m: {"can": "can", "won": "will"}.get(m.group(1), m.group(1)[:-1] if m.group(1).endswith("n") else m.group(1)) + " not", t)
    t = re.sub(r"'(s|re|ll|ve|d|m)\b", "", t)
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", t):
        out.extend(_SPLITS.get(w, w).split())
    return out


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _covered(text: str, said: str) -> bool:
    """Whether `text` is a fragment of what she just said, cut mid-way by the mic:
    nearly all its words, IN HER ORDER, within a short stretch of her words. Just
    sharing the words is not enough - live, his "What are you doing?" was thrown
    away as her echo because she had said "what", "are", "you" and "doing".

    Loose where the mic and Whisper are: a word either side may be missing
    ("can't" heard as "can"), spellings differ ("onto" / "on to"), and a word may
    be misheard a little. Live, "Black can hold on to it" - her own sentence -
    stopped her mid-answer as if he had spoken."""
    words = _echo_words(text)
    hers = _echo_words(said)
    if len(words) < 2 or not hers:
        return False
    # a short fragment must match word for word; a longer one may lose a quarter
    need = len(words) if len(words) <= 4 else int(len(words) * 0.75 + 0.999)
    span = int(len(words) * 1.5) + 2
    same = [[_same_word(w, h) for h in hers] for w in words]
    for start in range(len(hers)):
        if not any(same[i][start] for i in range(len(words))):
            continue
        # longest common in-order run of his words inside her next `span` words
        window = range(start, min(len(hers), start + span))
        best = [0] * (len(words) + 1)
        for j in window:
            prev = 0
            for i in range(1, len(words) + 1):
                keep = best[i]
                if same[i - 1][j]:
                    best[i] = prev + 1
                elif best[i - 1] > best[i]:
                    best[i] = best[i - 1]
                prev = keep
        if best[len(words)] >= need:
            return True
    return False


ECHO_LETTERS = 0.8


def _spelled_like(text: str, said: str) -> bool:
    """Whether `text` is a stretch of what she said, letter for letter - for the
    words Whisper splits and misspells. Live, her "Then there's the sakigawa" came
    back as "Then there's the saki gowl": only three of its five words matched, and
    it stopped her mid-answer. Letters with the spaces out ("thentherethesakigowl"
    against "thentherethesakigawa") still line up. The letters must run together
    in her order: words she merely also used, scattered, never add up."""
    import difflib

    heard = "".join(_echo_words(text))
    hers = "".join(_echo_words(said))
    n = len(heard)
    if n < 12 or len(hers) < n:
        return False
    best = 0.0
    for start in range(0, len(hers) - n + 1):
        window = hers[start : start + n + 2]
        if window[0] != heard[0] and window[1:2] != heard[1:2]:
            continue
        matcher = difflib.SequenceMatcher(None, heard, window, autojunk=False)
        if matcher.quick_ratio() < ECHO_LETTERS:
            continue
        best = max(best, matcher.ratio())
        if best >= ECHO_LETTERS:
            return True
    return False


# small words that say nothing about whose sentence it is
_FILLER = {"they", "they're", "there", "their", "this", "that", "what", "with", "from", "have", "your", "you're", "will", "would", "could", "should", "about", "just", "like", "then", "than", "when", "where", "which", "were", "been", "being", "into", "onto", "also", "really", "very", "some", "more", "much", "here", "it's", "that's", "okay", "well", "wait", "stop", "sorry"}


def _mostly_hers(text: str, said: str) -> bool:
    """Heard over her, mostly HER content words: her echo, misheard past matching
    ("They're accepting the gambit to fly" while she explained accepting the
    gambit). Only for a barge-in - after she stops, "tell me more about accepting
    the gambit" is his, and it is never asked here."""
    content = [w for w in _echo_words(text) if len(w) >= 4 and w not in _FILLER]
    hers = [w for w in _echo_words(said) if len(w) >= 4]
    if len(content) < 2 or not hers:
        return False
    found = sum(1 for w in content if any(_same_word(w, h) for h in hers))
    return found >= 2 and found / len(content) >= 0.6
