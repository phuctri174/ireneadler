import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import type { Vec2 } from "../tracking/oneEuro";
import type { GestureState } from "../tracking/gestures";
import { onFrame } from "../tracking/frameLoop";
import { Face } from "../face/Face";
import { invoke } from "@tauri-apps/api/core";
import { BOOT_MS, BootSpectacle, PANEL_BURST_MS, Scramble } from "./boot";
import "./boot.css";
import type { VoiceStage } from "../led/listening";
import { STATE_LABEL } from "../face/faceState";
import type { AssistantState, Emotion } from "../face/faceState";
import { SILENT_LEVEL, cachedLevel } from "../face/audioLevel";
import type { AudioLevelSource } from "../face/audioLevel";
import { REACTION_LABEL, REACTION_MS, onReaction } from "../face/reactions";
import { ACTIVITY_LABEL, currentActivity, onActivity } from "../face/activity";
import type { SummonTimes } from "../led/summon";
import type { EntranceName } from "../led/entrances";
import type { Prepared } from "../board/board";
import hudConfig from "../../../config/hud.json";
import { Brackets, Scanlines, Sweep, TickRail } from "./Chrome";
import "./MainInterface.css";

export type MainAction = "listen" | "panel" | "mute" | "sleep";

// Emergency controls: small, quiet, docked in the bottom-left corner - the
// fallback for when voice control fails, not the way Irene is normally driven.
// Dwell-selected. What each does lives with its owner (App); this only reports
// the choice.
const ACTIONS: { id: MainAction; label: string }[] = [
  { id: "listen", label: "LISTEN" },
  { id: "panel", label: "PANEL" },
  { id: "mute", label: "MUTE" },
  { id: "sleep", label: "SLEEP" },
];

const FLARE_MS = 900;
const FLASH_MS = 320;

const { interface: SIZE } = hudConfig;

/** The interface fills the window: its design size scaled uniformly, and the
 *  leftover of a different aspect laid out (wider or taller), never stretched. */
function uiFit(): { scale: number; width: number; height: number } {
  const scale = Math.min(window.innerWidth / SIZE.width, window.innerHeight / SIZE.height);
  return { scale, width: window.innerWidth / scale, height: window.innerHeight / scale };
}

function Icon({ id, muted }: { id: MainAction; muted: boolean }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (id) {
    case "listen":
      return (
        <svg viewBox="0 0 24 24" {...common}>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" />
        </svg>
      );
    case "panel":
      return (
        <svg viewBox="0 0 24 24" {...common}>
          <rect x="3.5" y="4.5" width="17" height="15" rx="1.5" />
          <path d="M14 4.5v15M16.5 8.5h1.5M16.5 11.5h1.5" />
        </svg>
      );
    case "mute":
      return (
        <svg viewBox="0 0 24 24" {...common}>
          <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" />
          {muted ? <path d="M16 9.5l5 5M21 9.5l-5 5" /> : <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />}
        </svg>
      );
    case "sleep":
      return (
        <svg viewBox="0 0 24 24" {...common}>
          <path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" />
        </svg>
      );
  }
}

export interface MainInterfaceProps {
  state: AssistantState;
  emotion: Emotion;
  visible: boolean;
  cursor: RefObject<Vec2>;
  gestures: RefObject<GestureState>;
  /** Bumped when the arrival flare should fire - keyed to the summon clip by App. */
  summonCount: number;
  /** The domain-expansion sequence's timing while one plays. */
  summon?: SummonTimes | null;
  level?: AudioLevelSource;
  /** TTS output is off: the face shows it and the MUTE control is latched. */
  muted?: boolean;
  /** Rendered in the face well, under her face (the command bar). */
  bar?: ReactNode;
  /** He is typing to her. */
  typing?: boolean;
  /** The summon entrance playing now. */
  entrance?: { name: EntranceName; at: number } | null;
  /** The illustration board while she draws. */
  board?: { drawing: Prepared; at: number } | null;
  /** Voice input on her face (led/listening.ts). */
  voice?: VoiceStage | null;
  onAction?: (action: MainAction) => void;
}

function clock(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number): string => value.toString().padStart(2, "0");
  return `T+${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function MainInterface({
  state,
  emotion,
  visible,
  cursor,
  gestures,
  summonCount,
  summon = null,
  level,
  muted = false,
  bar,
  typing = false,
  entrance = null,
  board = null,
  voice = null,
  onAction,
}: MainInterfaceProps) {
  const root = useRef<HTMLDivElement | null>(null);
  const buttons = useRef<(HTMLDivElement | null)[]>([]);
  const signal = useRef<HTMLDivElement | null>(null);
  const uptime = useRef<HTMLSpanElement | null>(null);
  const action = useRef(onAction);
  const look = useRef({ state, visible });

  action.current = onAction;
  look.current = { state, visible };

  // one read per frame shared by the face and the signal meter
  const source = useMemo(() => cachedLevel(level ?? SILENT_LEVEL), [level]);

  useEffect(() => {
    const apply = (): void => {
      const style = root.current?.style;
      if (!style) return;
      const fit = uiFit();
      style.setProperty("--ui-scale", fit.scale.toFixed(4));
      style.setProperty("--ui-w", `${fit.width.toFixed(1)}px`);
      style.setProperty("--ui-h", `${fit.height.toFixed(1)}px`);
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, []);

  // The flare is a mounted element rather than a toggled class: a class would be
  // wiped by the next render, and a fresh element replays its animation for free.
  const [flare, setFlare] = useState(0);
  useEffect(() => {
    if (summonCount === 0) return;
    setFlare(summonCount);
    const timer = window.setTimeout(() => setFlare(0), FLARE_MS);
    return () => window.clearTimeout(timer);
  }, [summonCount]);

  // names what is on the matrix, so a gesture or scene is never a guess
  const [reaction, setReaction] = useState<string | null>(null);
  const [scene, setScene] = useState<string | null>(() => {
    const name = currentActivity().name;
    return name ? ACTIVITY_LABEL[name] : null;
  });
  useEffect(() => {
    let timer = 0;
    const stopReaction = onReaction((event) => {
      setReaction(REACTION_LABEL[event.name]);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setReaction(null), REACTION_MS);
    });
    const stopActivity = onActivity((event) => setScene(event.name ? ACTIVITY_LABEL[event.name] : null));
    return () => {
      stopReaction();
      stopActivity();
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    const started = performance.now();
    let rects: DOMRect[] = [];
    let lastSelect = gestures.current.selectCount;
    let flashIndex = -1;
    let flashUntil = 0;
    let shownClock = "";

    const measure = (): void => {
      rects = buttons.current.map((node) => node?.getBoundingClientRect() ?? new DOMRect());
    };

    measure();
    window.addEventListener("resize", measure);
    const remeasure = window.setInterval(measure, 500);

    const stop = onFrame((now) => {
      const { state: current, visible: shown } = look.current;

      const meter = signal.current;
      if (meter) {
        const rms = current === "speaking" ? source.read(now) : 0;
        meter.style.transform = `scaleX(${rms.toFixed(3)})`;
      }

      const stamp = clock(now - started);
      if (uptime.current && stamp !== shownClock) {
        uptime.current.textContent = stamp;
        shownClock = stamp;
      }

      const gesture = gestures.current;
      const point = cursor.current;
      const x = point.x * window.innerWidth;
      const y = point.y * window.innerHeight;

      let hovered = -1;
      if (shown) {
        for (let i = 0; i < rects.length; i += 1) {
          const rect = rects[i];
          // round buttons: hit-test the circle, not its box
          const r = rect.width / 2;
          const dx = x - (rect.left + r);
          const dy = y - (rect.top + rect.height / 2);
          if (r > 0 && dx * dx + dy * dy <= r * r) {
            hovered = i;
            break;
          }
        }
      }

      if (gesture.selectCount !== lastSelect) {
        lastSelect = gesture.selectCount;
        const target = ACTIONS[hovered];
        if (target) {
          flashIndex = hovered;
          flashUntil = now + FLASH_MS;
          action.current?.(target.id);
        }
      }

      const flashing = now < flashUntil;
      for (let i = 0; i < buttons.current.length; i += 1) {
        const node = buttons.current[i];
        if (!node) continue;
        node.classList.toggle("is-hover", i === hovered);
        node.classList.toggle("is-flash", flashing && i === flashIndex);
        const progress = i === hovered ? gesture.dwellProgress : 0;
        node.style.setProperty("--dwell", progress.toFixed(3));
      }
    });

    return () => {
      stop();
      window.clearInterval(remeasure);
      window.removeEventListener("resize", measure);
    };
  }, [cursor, gestures, source]);

  // the boot-up: every time she is shown, her frame, brackets, labels, readouts
  // and cards come up in sequence (~1.2 s) before the entrance; skipped when he
  // speaks over it (core sends boot_skip -> "irene-boot-skip")
  const [booting, setBooting] = useState(0);
  useEffect(() => {
    if (!visible) return;
    setBooting((n) => n + 1);
    const done = window.setTimeout(() => setBooting(0), BOOT_MS);
    // her panel bursts in on the second screen as the name lands (Rust holds it
    // hidden until this cue) - or straight away if he skips the boot
    let burst = false;
    const release = (): void => {
      if (burst) return;
      burst = true;
      void invoke("panel_burst").catch(() => undefined);
    };
    const cue = window.setTimeout(release, PANEL_BURST_MS);
    const skip = () => {
      setBooting(0);
      release();
    };
    window.addEventListener("irene-boot-skip", skip);
    return () => {
      window.clearTimeout(done);
      window.clearTimeout(cue);
      window.removeEventListener("irene-boot-skip", skip);
    };
  }, [visible]);

  const classes = ["irene", `is-${state}`, visible ? "is-visible" : "", muted ? "is-muted" : "", booting ? "is-booting" : ""]
    .filter(Boolean)
    .join(" ");
  const tag = reaction ? `REACT · ${reaction}` : scene ? `SCENE · ${scene}` : "FACE ARRAY";

  return (
    <div
      className={classes}
      ref={root}
      aria-hidden={!visible}
    >
      <div className="irene-shell">
        {flare > 0 ? <div className="irene-flare" key={flare} aria-hidden="true" /> : null}
        <Brackets large />
        <Scanlines />
        <Sweep style={{ top: 0 }} />

        <header className="irene-head">
          <div className="irene-meters">
            <div className="irene-meter">
              <span className="readout">MOOD</span>
              <b className="readout">
                <Scramble text={emotion.toUpperCase()} run={booting} at={1400} dur={500} />
              </b>
            </div>
            <div className="irene-meter is-wide">
              <span className="readout">{muted ? "MUTE" : "SIG"}</span>
              <div className="irene-bar">
                <div className="irene-bar-fill" ref={signal} />
              </div>
            </div>
            <div className="irene-meter">
              <span className="readout">UP</span>
              <b className="readout" ref={uptime}>
                T+00:00:00
              </b>
            </div>
          </div>
          <div className="irene-badge">
            <span className="irene-badge-wing" aria-hidden="true" />
            <div className="irene-badge-plate">
              <span className="irene-badge-gem" aria-hidden="true" />
              <span className="irene-mark">
                <Scramble text="IRENE ADLER" run={booting} at={4100} dur={700} />
              </span>
              <span className="irene-badge-gem" aria-hidden="true" />
            </div>
            <span className="irene-badge-wing is-right" aria-hidden="true" />
            <div className="irene-expand">
              <b>I</b>t&rsquo;s <b>R</b>eally <b>E</b>verything, <b>N</b>o <b>E</b>xaggeration
            </div>
          </div>
          <div className="irene-status">
            <span className="irene-lamp" />
            <span className="irene-status-text">
              <Scramble text={STATE_LABEL[state]} run={booting} at={1600} dur={600} />
            </span>
          </div>
        </header>

        <TickRail count={60} major={5} className="irene-rail" />

        <div className="irene-well">
          <Brackets />
          <div className="irene-well-tag readout">
            OPT&middot;01 &mdash; {tag}
            {muted ? " · MUTED" : ""}
          </div>
          <Face state={state} emotion={emotion} level={source} muted={muted} summon={summon} visible={visible} typing={typing} entrance={entrance} board={board} voice={voice} />
          <div className="irene-well-scale">
            <TickRail count={13} major={3} vertical />
          </div>
          {bar}
        </div>

        <footer className="irene-foot">
          <span className="readout">LOCAL &middot; NO NET</span>
          <span className="readout">CTRL+ALT+I &middot; SUMMON</span>
        </footer>

        <nav className="irene-dock" aria-label="Emergency controls">
          {ACTIONS.map((item, index) => {
            const latched = item.id === "mute" && muted;
            return (
              <div
                key={item.id}
                className={latched ? "irene-dock-btn is-on" : "irene-dock-btn"}
                title={latched ? "UNMUTE" : item.label}
                ref={(node) => {
                  buttons.current[index] = node;
                }}
              >
                <Icon id={item.id} muted={muted} />
                <span className="irene-dock-label">{latched ? "UNMUTE" : item.label}</span>
              </div>
            );
          })}
        </nav>
      </div>
      <BootSpectacle run={booting} />
    </div>
  );
}

export default MainInterface;
