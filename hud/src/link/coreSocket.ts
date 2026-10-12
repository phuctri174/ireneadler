import type { AssistantState, Emotion } from "../face/faceState";
import type { PanelContent } from "../ui/content";

// Wire protocol with core/ - mirror of core/irene/bridge.py.
export type CoreMessage =
  | { type: "state"; value: AssistantState }
  | { type: "emotion"; value: Emotion }
  // something is opening in his Chrome: her windows step back from always-on-top
  | { type: "yield_front" }
  | { type: "intro_cursor"; hidden: boolean }
  // screens-off mode on/off (core): everything of hers away, tracking suspended
  | { type: "dark"; value: boolean }
  // he spoke over her boot-up: it jumps to its end (here and on the panel)
  | { type: "boot_skip" }
  // waking from screens-off: black surfaces on every monitor (onAt: Windows' "on", epoch ms)
  | { type: "warmup"; on: boolean; onAt: number | null }
  | { type: "audio_level"; value: number }
  | { type: "reaction"; value: string; big?: boolean }
  | { type: "panel"; value: PanelContent | null }
  | { type: "transcript"; role: "user" | "irene"; text: string }
  | { type: "muted"; value: boolean }
  | { type: "summon"; phase: SummonPhase }
  | { type: "activity"; value: string | null; loops?: number }
  // keiko (core/irene/keiko.py): start / end, or her answer to his strike
  | { type: "keiko"; action: "start" | "end" | "block" | "hit" | "strike" | "ippon"; target?: "men" | "kote" | "dou"; flags?: number }
  // a summon entrance as heard (config/entrances.json); end: back to listening
  | { type: "entrance"; phase: "start" | "end"; name?: string; ms?: number }
  // the illustration board: a <draw> spec (checked again here), or null to clear it
  | { type: "draw"; value: unknown }
  // typed conversation
  | { type: "reply"; display: string; speak: string }
  | { type: "confirm"; id: string; prompt: string }
  | { type: "confirm_done"; id: string }
  // cue: the prop she shows while it runs (config/cues.json kind "prop"), or null
  | { type: "tool"; name: string; status: string; cue?: string | null }
  | { type: "conversation"; event: "ended" | "reset" }
  | { type: "latency"; command_to_audio_ms: number }
  // a panel link he clicked: opened in his Chrome (ok), or refused
  | { type: "link_opened"; url: string; ok: boolean }
  // screen vision: hide this window from captures (on) or show it again
  | { type: "capture_shield"; on: boolean }
  // dev builds only: point a synthetic hand at (x, y) in 0..1 screen space
  | { type: "debug_point"; x: number; y: number; ms: number }
  // dev builds only: drive the UI the way a hotkey or typing would, with no OS input
  | { type: "debug_ui"; action: DebugAction; text?: string }
  // voice input (core/irene/voice_loop.py): listening, hearing, the end-of-speech
  // countdown, thinking; asleep = wake words only; off = no microphone
  | { type: "voice"; phase: VoicePhase; remainingMs?: number; totalMs?: number }
  // the voice corpus recorder (core/irene/corpus.py)
  | ({ type: "corpus" } & CorpusUpdate)
  | { type: "mic_level"; value: number }
  // a voice wake: summon exactly as ctrl+alt+i does (shows the window if hidden)
  | { type: "summon_request"; by: "voice" | "adler" }
  // skit mode (core/irene/skit.py): a take starts (hide: put her away first) or ends
  | { type: "skit"; phase: "start" | "waiting" | "end" | "error"; name?: string; note?: string; hide?: boolean; completed?: boolean; error?: string }
  // a research answer's key terms, as the sentence holding them is heard
  | { type: "board_term"; terms: string[]; title?: string }
  // an illustrated answer (core/irene/illustrate.py): the drawing, then what each
  // sentence adds to it - moves, labels, steps, points, terms - as it is heard
  | { type: "board_sync"; spec?: Record<string, unknown>; add?: Record<string, Record<string, unknown>[]>; set?: Record<string, unknown> };

export type { VoicePhase } from "../led/listening";
import type { VoicePhase } from "../led/listening";

export interface CorpusUpdate {
  phase: "take" | "ready" | "recording" | "checking" | "saved" | "redo" | "stopped" | "complete" | "no_mic";
  done: number;
  total: number;
  index?: number;
  id?: string;
  text?: string;
  take?: number;
  takes?: number;
  split?: string;
  reason?: string;
  heard?: string;
  remainingMs?: number;
  totalMs?: number;
  note?: string;
}

export type DebugAction = "summon" | "preview" | "bar_open" | "bar_close" | "bar_submit" | "capture" | "debug" | "typing" | "panel_link" | "kamae" | "hide" | "show" | "visibility_path" | "dashboard_click" | "geometry" | "pin";

/** Summon clip as heard: start of the swell, start of "Irene Adler", end of clip. */
export type SummonPhase = "start" | "part2" | "end";

export type HudMessage =
  // `by` on a summon: "sign" always gets the domain expansion, "hotkey" a random one
  | { type: "speak"; text: string; source: string; by?: string }
  // he took kamae at her (the pose watcher), or left it: she answers fired up
  | { type: "kamae"; phase: "start" | "end" }
  // keiko: a strike he made (tracking/strikeFeatures.ts), for core to answer
  | { type: "keiko_strike"; strike: string; p: number; clean: boolean }
  // a step of the voice summon on the HUD side, into core.log
  | { type: "hud_trace"; step: string }
  // her window shown or hidden (shown: she listens with no wake word)
  | { type: "visibility"; visible: boolean }
  // where the HUD's time went over the last 10 s (perf.ts)
  | ({ type: "hud_perf" } & import("../perf").PerfSummary)
  | { type: "mute"; value: boolean }
  | { type: "sleep" }
  // he typed over a summon entrance: cut it and listen
  | { type: "summon_skip" }
  | { type: "capture_shield_ack"; on: boolean }
  | { type: "hello"; role: "hud" }
  | { type: "command"; text: string }
  // the LISTEN button: hear him now, no wake word
  | { type: "listen" }
  | { type: "corpus"; action: "start" | "redo" | "stop" }
  | { type: "skit"; action: "start" | "abort" }
  | { type: "confirm_reply"; id: string; ok: boolean }
  // a link he clicked on the panel; core opens it in his Chrome if it put it there
  | { type: "open_link"; url: string }
  // a dashboard item clicked (mouse) or picked (hand): core opens it in his Chrome
  | { type: "dashboard_open"; url: string; how: string }
  | { type: "dashboard_refresh" }
  | { type: "research_recall"; id: string }
  | { type: "screens_off" }
  // gesture calibration: one take's frames, written to core/calibration/<profile>-*.jsonl
  | { type: "calibration"; profile: string; session: string; pose: string; rep: number; frames: object[] };

export const CORE_URL = "ws://127.0.0.1:8765/ws";
const RETRY_MIN_MS = 500;
const RETRY_MAX_MS = 5000;

type Listener = (message: CoreMessage) => void;
type LinkListener = (up: boolean) => void;

/**
 * One socket to core/, reconnecting forever with capped backoff. Core may start
 * before or after the HUD, or restart under it; callers never see the difference
 * beyond `onLink`. Messages sent while down are dropped, not queued - a summon
 * line replayed a minute late would be worse than silence.
 */
export class CoreSocket {
  private socket: WebSocket | null = null;
  private retryMs = RETRY_MIN_MS;
  private timer = 0;
  private closed = false;
  private up = false;
  private readonly listeners = new Set<Listener>();
  private readonly linkListeners = new Set<LinkListener>();

  constructor(private readonly url: string = CORE_URL) {}

  start(): void {
    this.closed = false;
    this.connect();
  }

  stop(): void {
    this.closed = true;
    window.clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
    this.setUp(false);
  }

  send(message: HudMessage): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  onMessage(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onLink(listener: LinkListener): () => void {
    this.linkListeners.add(listener);
    listener(this.up);
    return () => this.linkListeners.delete(listener);
  }

  private connect(): void {
    if (this.closed) return;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      // core treats every other client as a test script: only the HUD's commands
      // (his typing, his clicks) may reach his apps
      socket.send(JSON.stringify({ type: "hello", role: "hud" }));
      this.retryMs = RETRY_MIN_MS;
      this.setUp(true);
    };
    socket.onmessage = (event) => {
      let message: CoreMessage;
      try {
        message = JSON.parse(String(event.data)) as CoreMessage;
      } catch {
        return;
      }
      for (const listener of this.listeners) {
        try {
          listener(message);
        } catch (cause) {
          console.error("[irene] core message handler threw", cause);
        }
      }
    };
    // onerror is always followed by onclose; reconnect from one place
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.setUp(false);
      if (this.closed) return;
      this.timer = window.setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
    };
  }

  private setUp(up: boolean): void {
    if (this.up === up) return;
    this.up = up;
    console.log(`[irene] core link ${up ? "up" : "down"}`);
    for (const listener of this.linkListeners) listener(up);
  }
}
