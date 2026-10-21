// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { note as perfNote, take as takePerf } from "./perf";
import type { RefObject } from "react";
import { HandLandmarker } from "@mediapipe/tasks-vision";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { emitTo, listen } from "@tauri-apps/api/event";
import { EVENT_DASHBOARD, EVENT_DASHBOARD_FOCUS, EVENT_DASHBOARD_OPEN, EVENT_DASHBOARD_READY, EVENT_PANEL_CONTENT, EVENT_PANEL_LINK_DEV, EVENT_PANEL_LINK_OPEN } from "./dashboard/Dashboard";
import { invoke } from "@tauri-apps/api/core";
import { boardSnapshot } from "./board/snapshot";
import { useHandTracking } from "./tracking/useHandTracking";
import { Reticle } from "./tracking/Reticle";
import { onFrame } from "./tracking/frameLoop";
import { neutralScrollDebug } from "./ui/scrollDebug";
import type { PanelScrollDebug } from "./ui/scrollDebug";
import { holdInteraction, noteInteraction } from "./face/interaction";
import { clearPanel, getPanel, onPanel, pushPanel, setLinkOpener, togglePanel as togglePanelContent } from "./ui/panelChannel";
import { MainInterface } from "./ui/MainInterface";
import type { MainAction } from "./ui/MainInterface";
import { ASSISTANT_STATES, EMOTIONS } from "./face/faceState";
import type { AssistantState, Emotion } from "./face/faceState";
import { streamedLevel } from "./face/audioLevel";
import { CoreSocket } from "./link/coreSocket";
import { REACTIONS, showReaction } from "./face/reactions";
import { gameHand } from "./face/gameHandBus";
import { ACTIVITIES, currentActivity, cycleActivity, isActivity, showActivity } from "./face/activity";
import { SUMMON_TAIL_MS } from "./led/summon";
import { keikoReact } from "./led/scenes";
import { showReadout } from "./led/readout";
import { currentStudy, studyOn, studyState } from "./led/study";
import { currentScore, scoreOn, shiaiScore } from "./led/score";
import { ENTRANCE_NAMES, ENTRANCES, isEntrance } from "./led/entrances";
import type { EntranceName } from "./led/entrances";
import entranceRegistry from "../../config/entrances.json";
import { prepare } from "./board/board";
import { liveEcho } from "./board/templates/chessboard";
import type { Prepared } from "./board/board";
import type { SummonTimes } from "./led/summon";
import { summonTail } from "./led/summon";
import { setSyntheticPoint } from "./tracking/synthetic";
import { CAPTURE_PROFILES, GestureCapture } from "./ui/GestureCapture";
import { CorpusRecorder } from "./ui/CorpusRecorder";
import type { VoiceStage } from "./led/listening";
import type { CaptureRun } from "./ui/GestureCapture";
import { CommandBar } from "./ui/CommandBar";
import { MOCK_CONTENT } from "./ui/mockResearch";
import type { PanelContent } from "./ui/content";

// PANEL with nothing ever shown: say so, rather than showing mock content as if real
const EMPTY_PANEL: PanelContent = {
  title: "Panel",
  blocks: [{ kind: "text", text: "Nothing to show yet. Results appear here when Irene has something for you." }],
};
import {
  CROSS_GAP_LATCH,
  DWELL_HOLD_MS,
  DWELL_RADIUS,
  POINT_THUMB_MAX_EXTENSION,
  SCROLL_MIDDLE_EXTEND_LATCH_RATIO,
  ZOOM_SPREAD_CLOSED,
} from "./tracking/gestures";
import { neutralDiag } from "./tracking/gestures";
import type { GestureState } from "./tracking/gestures";
import { LectureBadge } from "./ui/LectureBadge";
import type { LectureStatus } from "./ui/LectureBadge";
import "./App.css";

// a board drawing builds up: each element a sentence brings up starts this long after the last
const BUILD_STAGGER_MS = 320;
const SKELETON_COLOR = "#22e0ff";
const JOINT_COLOR = "#ffffff";
const CURSOR_JOINT = 8;
const MIDDLE_JOINT = 12;
const THUMB_JOINT = 4;
const DEBUG_KEY = "F9";
// The operator keys are global as ctrl+alt+shift+F6..F11 (lib.rs, hud/HOTKEYS.md);
// plain F9/F10 here work only while the HUD itself has focus, so they take
// nothing from other apps.
const CLOSE_KEY = "Escape";
const CALIBRATE_KEY = "F10";
const CALIB_TERMINAL_MS = 500;
const EVENT_TOGGLE_DEBUG = "irene://toggle-debug";
const EVENT_VISIBILITY = "irene://visibility";
const EVENT_TOGGLE_CALIBRATE = "irene://toggle-calibrate";
const EVENT_SUMMON = "irene://summon";
const EVENT_CYCLE_STATE = "irene://cycle-state";
const EVENT_CYCLE_EMOTION = "irene://cycle-emotion";
const EVENT_TOGGLE_PANEL = "irene://toggle-panel";
const EVENT_CYCLE_REACTION = "irene://cycle-reaction";
const EVENT_CYCLE_ACTIVITY = "irene://cycle-activity";
// F11 preview of the summon sequence: when "Irene Adler" starts in the cached clip
// (core/assets/summon.json part2_at)
const SUMMON_PREVIEW_PART2_MS = 3040;
// ctrl+alt+t: open the command bar (typed input until there is a microphone)
const EVENT_COMMAND_BAR = "irene://command-bar";
// ctrl+alt+shift+c: guided capture of parallel vs crossed fingers, for tuning the summon gate
const EVENT_CAPTURE = "irene://capture";
// the voice corpus recorder: "start" (ctrl+alt+shift+r), "redo" (space), "stop" (escape)
const EVENT_CORPUS = "irene://corpus";
/** Skit mode (ctrl+alt+shift+k / x): "start" or "abort", passed to core. */
const EVENT_SKIT = "irene://skit";
/** Her z-order's decisions - raised, dropped, pinned (src-tauri/src/zorder.rs). */
const EVENT_ZORDER = "irene://zorder";
// backend-facing: payload is a PanelContent to show, or null to dismiss
const EVENT_PANEL = "irene://panel";
// backend-facing: payload is a reaction name, see face/reactions.ts
const EVENT_REACTION = "irene://reaction";
// emitted by lib.rs on summon; forwarded to core, which owns the voice
const EVENT_SPEAK = "irene://speak";
// after a show, whether Windows says the window is visible (lib.rs show_main)
const EVENT_SHOWN = "irene://shown";
const EVENT_CURSOR = "irene://cursor";
// the hand pointer moves to the dashboard after this long at the screen edge
// the OS pointer (pointer.rs): fingertip travel across the camera frame -> screen
// widths of cursor travel; the two-finger scroll's dead band and full-speed span
// (in camera-frame heights from where it began), and its top speed in wheel units
const POINTER_GAIN = 1.95;
// the still-hand deadband (frame units, frame units per second, ms)
const STILL_RADIUS = 0.012;
const STILL_SPEED = 0.08;
const STILL_MS = 120;
// the scroll as it worked on her main interface's panel (git b04f80f): speed at
// full deflection, the faster way back up, the neutral band (fraction of half the
// frame). SCROLL_MAX_SPEED doubled from 550 (he: far too slow) - tune from here.
const SCROLL_MAX_SPEED = 1100;
const SCROLL_UP_BOOST = 1.35;
// The bands, in the camera frame (0 top, 1 bottom) - measured on his hand. The
// old panel centred them on the frame's middle: upper reachable, lower not. His
// re-test (11:08, 353 readings): the two-finger pose latches 79-92% of the time
// from y 0.0 to 0.6, 32% at 0.6-0.7, ~0% below that - and 168 readings were past
// the frame's bottom edge (y > 1, all four fingers reading alike). So both
// regions sit inside 0.0-0.6, mirror images around 0.40: neutral 0.33-0.47,
// upper from 0.33 to full speed at 0.20, lower from 0.47 to full speed at 0.60.
const SCROLL_CENTRE_Y = 0.4;
const SCROLL_NEUTRAL_HALF = 0.07;
const SCROLL_FULL_SPAN = 0.13;
/** The scroll rule: where his two fingertips are in the CAMERA frame (0 top, 1
 *  bottom - no monitor's geometry involved) -> -1..1 (+ = down the page) and the
 *  region. Upper scrolls down, lower up, a neutral band between, full speed the
 *  same distance past each edge. */
function scrollRate(y: number): { rate: number; region: "UPPER" | "NEUTRAL" | "LOWER"; off: number } {
  const off = y - SCROLL_CENTRE_Y;
  const past = Math.abs(off) - SCROLL_NEUTRAL_HALF;
  if (past <= 0) return { rate: 0, region: "NEUTRAL", off };
  let rate = -Math.sign(off) * Math.min(past / SCROLL_FULL_SPAN, 1);
  if (rate < 0) rate *= SCROLL_UP_BOOST;
  return { rate, region: off < 0 ? "UPPER" : "LOWER", off };
}

// wheel units per pixel: a 120 notch is ~100 px in Chrome
const WHEEL_PER_PX = 1.2;
// scroll diagnostics: how often, and how far out both fingers must be to count
const SCROLL_DIAG_MS = 250;
const SCROLL_DIAG_EXT = 0.12;
const EVENT_POINTER = "irene://pointer";
// a tool's prop stays at least this long, so a tool that answers at once still shows it
const TOOL_PROP_MIN_MS = 1500;
// he stopped typing this long ago: she looks back up
const TYPING_IDLE_MS = 1400;
// F11: how long each expression holds in the preview
const EXPRESSION_PREVIEW_MS = 2200;
const DOMAIN_EXPANSION = "domain_expansion";

/**
 * Core picks the entrance; this is the same rule for when core is down (the
 * entrance then plays silently): by weight, never the one that played last.
 */
function pickEntrance(last: string | null): string {
  const pool = entranceRegistry.entrances.filter((e) => e.name !== last && (e.name === DOMAIN_EXPANSION || isEntrance(e.name)));
  const total = pool.reduce((sum, e) => sum + e.weight, 0);
  let roll = Math.random() * total;
  for (const e of pool) {
    roll -= e.weight;
    if (roll <= 0) return e.name;
  }
  return pool[pool.length - 1].name;
}

function LiveMetrics({ gestures }: { gestures: RefObject<GestureState> }) {
  const dwell = useRef<HTMLSpanElement | null>(null);
  const index = useRef<HTMLSpanElement | null>(null);
  const middle = useRef<HTMLSpanElement | null>(null);
  const thumb = useRef<HTMLSpanElement | null>(null);
  const gap = useRef<HTMLSpanElement | null>(null);
  const spread = useRef<HTMLSpanElement | null>(null);
  const cross = useRef<HTMLSpanElement | null>(null);
  const scroll = useRef<HTMLSpanElement | null>(null);
  const zoom = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    const stop = onFrame(() => {
      const state = gestures.current;
      if (dwell.current) dwell.current.textContent = state.dwellProgress.toFixed(2);
      if (index.current) index.current.textContent = state.indexExtension.toFixed(3);
      if (middle.current) middle.current.textContent = state.middleExtension.toFixed(3);
      if (thumb.current) thumb.current.textContent = state.thumbExtension.toFixed(3);
      if (gap.current) gap.current.textContent = state.thumbIndexRatio.toFixed(3);
      if (spread.current) spread.current.textContent = state.spread.toFixed(3);
      if (cross.current) cross.current.textContent = state.crossGap.toFixed(3);
      if (scroll.current) scroll.current.textContent = state.scrollPointY.toFixed(3);
      if (zoom.current) zoom.current.textContent = state.zoomFactor.toFixed(3);
    });
    return stop;
  }, [gestures]);

  return (
    <>
      <div className="hud-row">
        <span className="hud-label">DWELL</span>
        <span className="hud-value" ref={dwell}>
          0.00
        </span>
      </div>
      <div className="hud-row">
        <span className="hud-label">INDEX</span>
        <span className="hud-value" ref={index}>
          0.000
        </span>
      </div>
      <div className="hud-row">
        <span className="hud-label">MIDDLE</span>
        <span className="hud-value" ref={middle}>
          0.000
        </span>
      </div>
      <div className="hud-hint">point &lt; 0.06 · scroll &gt; {SCROLL_MIDDLE_EXTEND_LATCH_RATIO}</div>
      <div className="hud-row">
        <span className="hud-label">THUMB</span>
        <span className="hud-value" ref={thumb}>
          0.000
        </span>
      </div>
      <div className="hud-hint">point &lt; {POINT_THUMB_MAX_EXTENSION}</div>
      <div className="hud-row">
        <span className="hud-label">GAP</span>
        <span className="hud-value" ref={gap}>
          0.000
        </span>
      </div>
      <div className="hud-hint">point &gt; 0.58</div>
      <div className="hud-row">
        <span className="hud-label">SPREAD</span>
        <span className="hud-value" ref={spread}>
          0.000
        </span>
      </div>
      <div className="hud-hint">zoom-closed needs spread &lt; {ZOOM_SPREAD_CLOSED}</div>
      <div className="hud-row">
        <span className="hud-label">X GAP</span>
        <span className="hud-value" ref={cross}>
          0.000
        </span>
      </div>
      <div className="hud-hint">crossed (summon) &lt; {CROSS_GAP_LATCH}</div>
      <div className="hud-row">
        <span className="hud-label">SCRL Y</span>
        <span className="hud-value" ref={scroll}>
          0.000
        </span>
      </div>
      <div className="hud-row">
        <span className="hud-label">ZOOM</span>
        <span className="hud-value" ref={zoom}>
          1.000
        </span>
      </div>
    </>
  );
}

function Calibration({
  gestures,
  scrollDebug,
}: {
  gestures: RefObject<GestureState>;
  scrollDebug: RefObject<PanelScrollDebug>;
}) {
  const out = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    console.log("[calib] ON - console.log every frame; terminal summary twice a second");
    let frame = 0;
    let lastWarn = 0;

    // a stale engine instance (dev hot-reload) can predate a diag field;
    // never let the debug overlay take the app down
    const n = (value: number | undefined): number => (typeof value === "number" ? value : 0);
    const t = (value: string | undefined): string => value ?? "-";

    const stop = onFrame(() => {
      const s = gestures.current;
      const d = s.diag ?? neutralDiag();
      const sc = scrollDebug.current;
      frame += 1;

      const fingers =
        `thumb ${n(d.thumb).toFixed(3)}  index ${n(d.index).toFixed(3)}  mid ${n(d.middle).toFixed(3)}  ` +
        `ring ${n(d.ring).toFixed(3)}  pinky ${n(d.pinky).toFixed(3)}`;

      const text =
        `frame ${frame}   mode ${s.mode.toUpperCase()}   hand ${s.handPresent ? "yes" : "no"}
` +
        `
FINGERS
  ${fingers}
  class ${t(d.classes)}
` +
        `
ZOOM
` +
        `  allFiveOpen   ${d.allFiveOpen}   fails: ${t(d.openFail)}
` +
        `  allFiveClosed ${d.allFiveClosed}   fails: ${t(d.closedFail)}
` +
        `  spread ${s.spread.toFixed(3)}   factor ${s.zoomFactor.toFixed(3)}   ` +
        `frame-delta ${d.zoomDelta >= 0 ? "+" : ""}${n(d.zoomDelta).toFixed(4)}
` +
        `  state: ${t(d.zoom)}
` +
        `
SUMMON
` +
        `  bone gap ${s.crossGap.toFixed(3)} palm (gate: crossed < ${CROSS_GAP_LATCH})   old cross ${s.crossing.toFixed(3)} = 1 - ratio
` +
        `  dist(8,12) tipGap     ${n(d.crossTipGap).toFixed(4)}  (${n(d.crossTipGapPalm).toFixed(3)} palm)
` +
        `  dist(5,9)  knuckleGap ${n(d.crossKnuckleGap).toFixed(4)}  (${n(d.crossKnuckleGapPalm).toFixed(3)} palm)
` +
        `  ratio tipGap/knuckleGap ${n(d.crossRatio).toFixed(3)}   palmSpan ${n(d.palmSpan).toFixed(4)}
` +
        `  BONE 6->8 x 10->12  ${t(d.boneTip)}
` +
        `  BONE 6->7 x 10->11  ${t(d.boneDip)}   (no tips)
` +
        `  finger gate: ${t(d.summonGate)}
` +
        `  state: ${t(d.summon)}
` +
        `
SCROLL
` +
        `  scrlY ${s.scrollPointY.toFixed(3)} (raw ${n(d.scrollPointRaw).toFixed(3)})  handY ${sc.handY}px  ` +
        `rect top ${sc.rectTop} h ${sc.rectHeight}
` +
        `  centred ${sc.centred.toFixed(3)}  region ${sc.region}
` +
        `  rate ${sc.rate.toFixed(3)}  ${sc.pxPerSec.toFixed(0)} px/s  ` +
        `scrollTop ${sc.scrollTop}/${sc.scrollMax}
` +
        `  state: ${sc.reason}
` +
        `
POINT
  state: ${t(d.point)}`;

      if (out.current) out.current.textContent = text;

      const line =
        `[calib] f=${frame} mode=${s.mode} | th=${n(d.thumb).toFixed(2)} ix=${n(d.index).toFixed(2)} ` +
          `md=${n(d.middle).toFixed(2)} rg=${n(d.ring).toFixed(2)} pk=${n(d.pinky).toFixed(2)} ` +
          `[${t(d.classes)}] | ` +
          `open=${d.allFiveOpen}(${t(d.openFail)}) closed=${d.allFiveClosed}(${t(d.closedFail)}) ` +
          `spread=${s.spread.toFixed(3)} zf=${s.zoomFactor.toFixed(3)} dz=${n(d.zoomDelta).toFixed(4)} ` +
          `zoom[${t(d.zoom)}] | cross=${s.crossing.toFixed(3)} ` +
          `tipGap=${n(d.crossTipGap).toFixed(4)} knuckleGap=${n(d.crossKnuckleGap).toFixed(4)} ` +
          `ratio=${n(d.crossRatio).toFixed(3)} palm=${n(d.palmSpan).toFixed(4)} ` +
          `boneTip[${t(d.boneTip)}] boneDip[${t(d.boneDip)}] ` +
          `gate[${t(d.summonGate)}] summon[${t(d.summon)}] | ` +
          `scrlY=${s.scrollPointY.toFixed(3)} raw=${n(d.scrollPointRaw).toFixed(3)} handY=${sc.handY} rect=${sc.rectTop}+${sc.rectHeight} ` +
          `centred=${sc.centred.toFixed(3)} region=${sc.region} rate=${sc.rate.toFixed(3)} ` +
          `px/s=${sc.pxPerSec.toFixed(0)} scroll[${sc.reason}] | point[${t(d.point)}]`;

      console.log(line);
      const now = performance.now();
      if (now - lastWarn >= CALIB_TERMINAL_MS) {
        lastWarn = now;
        console.warn(line);
      }
    });

    return () => {
      console.log("[calib] OFF");
      stop();
    };
  }, [gestures, scrollDebug]);

  return (
    <div className="hud-calib">
      <div className="hud-calib-title">CALIBRATION — F10 to stop</div>
      <pre ref={out} className="hud-calib-body" />
    </div>
  );
}

function App() {
  const {
    video,
    cursor,
    handSource,
    landmarks,
    gestureRef,
    inputRef,
    poseRef,
    armPose,
    frameTiming,
    cameraInfo,
    setKeiko,
    setStrikeEvents,
    gestures,
    fps,
    detectMs,
    sourceFps,
    tracking,
    error,
    setActive,
    setSuspended,
    game,
  } = useHandTracking({
    // keiko (started by his voice - no pose trigger): a strike he made, for core
    // to answer (core/irene/keiko.py)
    onStrike: (event) => {
      console.log(`[irene] keiko strike: ${event.strike} p=${event.p.toFixed(2)}${event.clean ? " clean" : ""}`);
      core.send({ type: "keiko_strike", strike: event.strike, p: event.p, clean: event.clean });
    },
    // study mode, shiai, a calibration (core/irene/strikes.py): he struck at her -
    // binary, a threshold (tracking/strikeEvent.ts); core decides what it means
    onStrikeEvent: (event) => {
      console.log(`[irene] strike event: ${event.wrist} wrist, peak ${event.peak.toFixed(1)}, stop ${event.stopMs.toFixed(0)} ms`);
      core.send({ type: "strike_event", wrist: event.wrist, peak: event.peak, stopMs: event.stopMs });
    },
    // shiai (core/irene/shiai.py): his footwork
    onMove: (move) => {
      core.send({ type: "shiai_move", move });
    },
    // shiai: a block (tracking/strikeKind.ts); core times it against her attack
    onBlock: (hit) => {
      core.send({ type: "shiai_move", move: "block", height: hit.height, rest: hit.rest });
    },
    // dev probe (core's strike_probe): what the body did, each second
    onProbe: (stats) => {
      core.send({ type: "probe_stats", stats });
    },
  });
  // keiko is on (core's "keiko" start .. end)
  const keikoActive = useRef(false);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const scrollDebug = useRef<PanelScrollDebug>(neutralScrollDebug());

  // a hand in view is him interacting: idle life (face/idle.ts) holds off
  useEffect(
    () =>
      onFrame((now) => {
        if (gestureRef.current.handPresent) noteInteraction(now);
      }),
    [gestureRef],
  );
  const [debug, setDebug] = useState(false);
  const [calibrate, setCalibrate] = useState(false);

  // Main interface. `state` is only ever set from something that actually happened,
  // never from an animation - the face is a readout, not decoration. Real signals are
  // core/ over the socket, summon, and the operator keys below.
  const [assistant, setAssistant] = useState<AssistantState>("dormant");
  const [emotion, setEmotion] = useState<Emotion>("neutral");
  const [shellVisible, setShellVisible] = useState(false);
  // bumped when the arrival flare should fire: on "Irene Adler" as heard, or at
  // once if core is down and there is no clip to key it to
  const [flareCount, setFlareCount] = useState(0);
  // the domain-expansion sequence, stamped from core's summon phases as they arrive
  const [summonTimes, setSummonTimes] = useState<SummonTimes | null>(null);
  const summonClear = useRef(0);
  // the illustration board: her face in the corner while a drawing fills the matrix
  const [board, setBoard] = useState<{ drawing: Prepared; at: number } | null>(null);
  // the board as it is now, for the socket handler; and the research terms on it
  const boardRef = useRef(board);
  boardRef.current = board;
  const termsBoard = useRef<{ template: string; title?: string; terms: { text: string; at: number }[] } | null>(null);
  // the illustrated answer on the board, as core has built it so far
  const syncBoard = useRef<Record<string, unknown> | null>(null);
  // voice input on her face: listening, hearing, the end-of-speech countdown
  const [voice, setVoice] = useState<VoiceStage | null>(null);
  // when LISTEN was pressed: a "no microphone" answer right after it opens the bar
  const listenPressed = useRef(0);
  // a summon entrance (led/entrances.ts) playing now, and the last one, for no-repeat
  const [entrance, setEntrance] = useState<{ name: EntranceName; at: number } | null>(null);
  const entranceClear = useRef(0);
  const lastEntrance = useRef<string | null>(null);
  const playEntrance = useCallback((name: EntranceName) => {
    window.clearTimeout(entranceClear.current);
    lastEntrance.current = name;
    setEntrance({ name, at: performance.now() });
    entranceClear.current = window.setTimeout(() => setEntrance(null), ENTRANCES[name].ms + 100);
  }, []);
  const [captureRun, setCaptureRun] = useState<CaptureRun | null>(null);
  const startCapture = useCallback((profile: string) => {
    if (!CAPTURE_PROFILES.includes(profile)) {
      console.error(`[irene] unknown capture profile ${profile}`);
      return;
    }
    setCaptureRun((value) => ({ profile, n: (value?.n ?? 0) + 1 }));
  }, []);
  const [barOpen, setBarOpen] = useState(false);
  const openBar = useCallback(() => {
    noteInteraction();
    setBarOpen(true);
  }, []);
  const [barInject, setBarInject] = useState<{ text: string; n: number } | null>(null);
  const closeBar = useCallback(() => setBarOpen(false), []);
  const [typing, setTyping] = useState(false);
  const typingTimer = useRef(0);
  const noteTyping = useCallback(() => {
    noteInteraction();
    // typing over an entrance skips it: straight to her listening face
    setEntrance((value) => {
      if (value) core.send({ type: "summon_skip" });
      return null;
    });
    setTyping(true);
    window.clearTimeout(typingTimer.current);
    typingTimer.current = window.setTimeout(() => setTyping(false), TYPING_IDLE_MS);
  }, []);
  // the prop of the tool running now, so it is stopped only if it is still showing
  const toolProp = useRef<{ name: string; since: number; timer: number } | null>(null);
  const stopToolProp = useCallback(() => {
    const prop = toolProp.current;
    if (!prop) return;
    window.clearTimeout(prop.timer);
    const wait = Math.max(0, TOOL_PROP_MIN_MS - (performance.now() - prop.since));
    prop.timer = window.setTimeout(() => {
      if (currentActivity().name === prop.name) showActivity(null);
      if (toolProp.current === prop) toolProp.current = null;
    }, wait);
  }, []);

  const speechLevel = useMemo(() => streamedLevel(), []);
  const core = useMemo(() => new CoreSocket(), []);
  const [pointerOn, setPointerOn] = useState(true);
  // a lecture being captured (core's dashboard state): the badge, top right
  const [lecture, setLecture] = useState<LectureStatus | null>(null);
  const pointerOnRef = useRef(true);
  const shellUp = useRef(false);
  const [coreUp, setCoreUp] = useState(false);
  const [muted, setMuted] = useState(false);

  // a link clicked on the panel: core opens it in his own Chrome
  useEffect(() => {
    setLinkOpener((url) => {
      core.send({ type: "open_link", url });
    });
    return () => setLinkOpener(null);
  }, [core]);

  // her panel lives on the second screen: the panelChannel (what core puts on the
  // panel) and core's dashboard readings are relayed to its window; its clicks
  // (mouse or hand) come back here for core - one socket, his HUD's (tools/sandbox.py)
  useEffect(() => {
    let last: unknown = null;
    const relayPanel = (): void => {
      const content = getPanel();
      void emitTo("dashboard", EVENT_PANEL_CONTENT, content);
      core.send({ type: "hud_trace", step: `panel -> second screen: ${content ? `"${content.title}" (${content.blocks.length} blocks)` : "closed"}` });
      // something to show: the panel window comes up even if she was summoned without it
      if (content) void invoke("show_panel_window");
    };
    const stopPanel = onPanel(relayPanel);
    const stopMessages = core.onMessage((message) => {
      const kind = (message as { type: string }).type;
      if (kind === "dashboard") {
        // a partial update (load, timers) merges into the last full one
        last = { ...(last as object | null), ...(message as object) };
        // a lecture being captured: the badge on this screen too
        if ("lecture" in (message as object)) setLecture((message as unknown as { lecture: LectureStatus | null }).lecture);
        void emitTo("dashboard", EVENT_DASHBOARD, message);
      } else if (kind === "dashboard_focus") {
        void emitTo("dashboard", EVENT_DASHBOARD_FOCUS, message);
      }
    });
    const ready = listen(EVENT_DASHBOARD_READY, () => {
      if (last) void emitTo("dashboard", EVENT_DASHBOARD, last);
      // no full readings here (this window reloaded): core sends them again
      if (!last || !("news" in (last as object))) core.send({ type: "dashboard_refresh" });
      void emitTo("dashboard", EVENT_PANEL_CONTENT, getPanel());
    });
    const opened = listen<{ url: string; how: string }>(EVENT_DASHBOARD_OPEN, (event) => {
      core.send({ type: "dashboard_open", url: event.payload.url, how: event.payload.how });
    });
    // every hide says why (SLEEP, ctrl+alt+esc, tray, a close or a minimize)
    const hiddenBy = listen<string>("irene://hidden", (event) => {
      core.send({ type: "hud_trace", step: `hidden by ${event.payload}` });
    });
    // where the panel window really is after every show: monitor, position, topmost
    const placed = listen<string>("irene://panel-shown", (event) => {
      core.send({ type: "hud_trace", step: event.payload });
    });
    // a research card on the panel: core puts that research back in the centre
    const recalled = listen<{ id: string }>("irene://research-recall", (event) => {
      core.send({ type: "research_recall", id: event.payload.id });
    });
    const linked = listen<{ url: string; how: string }>(EVENT_PANEL_LINK_OPEN, (event) => {
      core.send({ type: "hud_trace", step: `panel link clicked on the second screen (${event.payload.how})` });
      core.send({ type: "open_link", url: event.payload.url });
    });
    return () => {
      stopPanel();
      stopMessages();
      for (const pending of [ready, opened, linked, placed, recalled, hiddenBy]) void pending.then((unlisten) => unlisten());
    };
  }, [core]);

  // his hand as the system-wide pointer (src-tauri/src/pointer.rs): each frame's
  // movement of his pointing fingertip moves the REAL cursor, relatively, like a
  // mouse - across both monitors; a dwell is a left click, two fingers scroll the
  // wheel. A relaxed hand is the clutch. Only the camera's hand drives it, never the
  // dev synthetic one. Ctrl+Alt+H turns it off (mouse only).
  useEffect(() => {
    let lastSelect = -1;
    let lastPinch = -1;
    let wheelRest = 0;
    let wasActive = false;
    let steeredBefore = false;
    let prevNow = 0;
    // the still-hand deadband: while his hand is (nearly) still the cursor does not
    // move at all - tremor can't drift it off the target or restart the dwell. It
    // starts following once the fingertip leaves the anchor by STILL_RADIUS, and
    // settles again after STILL_MS below STILL_SPEED.
    let anchor: { x: number; y: number } | null = null;
    let last: { x: number; y: number } | null = null;
    let moving = false;
    let slowSince = 0;
    // the dwell's story, for core.log: how far each try got, and why it stopped
    let dwellPeak = 0;
    let lastDwellLog = 0;
    // the scroll diagnostics' state
    let scrollTrying = false;
    let lastScrollLog = 0;
    let lastScrollY = 0;
    let scrollSent = 0;
    const trace = (step: string): void => {
      core.send({ type: "hud_trace", step });
    };
    // one call per CAMERA frame (~30/s), not per display refresh (165/s here): each
    // call moves the ring window too, and at the display's rate that work sat on
    // the same thread as her face
    let seenFrame: unknown = null;
    const stop = onFrame((now) => {
      const g = gestureRef.current;
      const point = cursor.current;
      const fromCamera = handSource.current === "camera";
      // mid-game the hand is a game piece: never the pointer (gameMode.ts also keeps
      // the engine's state neutral; this is the pointer's own guard)
      const active = pointerOnRef.current && fromCamera && Boolean(g?.handPresent) && Boolean(point) && !game.active(now);
      if (!active || !g || !point) {
        // his hand went while he was trying to scroll: where it was (core.log)
        if (scrollTrying && g && !g.handPresent && now - lastScrollLog > 150) {
          trace(`scroll diag: HAND LOST - last fingertip y ${lastScrollY.toFixed(3)} (0 top, 1 bottom)`);
          lastScrollLog = now;
        }
        scrollTrying = false;
        if (wasActive) void invoke("hand_pointer", { dx: 0, dy: 0, dwell: 0, click: false, wheel: 0, active: false, mode: "" });
        wasActive = false;
        steeredBefore = false;
        last = anchor = null;
        moving = false;
        lastSelect = lastPinch = -1;
        dwellPeak = 0;
        return;
      }
      if (landmarks.current === seenFrame) return;
      seenFrame = landmarks.current;
      const dt = prevNow ? Math.min(0.1, (now - prevNow) / 1000) : 0;
      prevNow = now;
      wasActive = true;
      // physical px per unit of the camera's frame
      const scale = window.screen.width * window.devicePixelRatio * POINTER_GAIN;
      let dx = 0;
      let dy = 0;
      const steering = g.pointing && !g.scroll && !g.zoom && !g.pinching;
      if (steering && last && anchor) {
        const speed = Math.hypot(point.x - last.x, point.y - last.y) / Math.max(dt, 1 / 120);
        if (!moving && Math.hypot(point.x - anchor.x, point.y - anchor.y) > STILL_RADIUS) {
          moving = true;
          // the move starts from the anchor: nothing he did is lost
          dx = (point.x - anchor.x) * scale;
          dy = (point.y - anchor.y) * scale;
        } else if (moving) {
          dx = (point.x - last.x) * scale;
          dy = (point.y - last.y) * scale;
          slowSince = speed < STILL_SPEED ? slowSince || now : 0;
          if (slowSince && now - slowSince > STILL_MS) {
            moving = false;
            anchor = { x: point.x, y: point.y };
          }
        }
      } else if (steering) {
        anchor = { x: point.x, y: point.y };
        moving = false;
      }
      last = steering ? { x: point.x, y: point.y } : null;
      if (!steering) anchor = null;

      // clicks: a dwell that completes, or a pinch (instant)
      const dwellFired = lastSelect >= 0 && g.selectCount !== lastSelect;
      const pinched = lastPinch >= 0 && g.pinchCount !== lastPinch;
      lastSelect = g.selectCount;
      lastPinch = g.pinchCount;
      const click = dwellFired || pinched;
      if (pinched) trace("pinch click");
      if (dwellFired) trace(`dwell fired (${DWELL_HOLD_MS} ms within ${DWELL_RADIUS} of the frame)`);
      if (g.dwellProgress > dwellPeak) dwellPeak = g.dwellProgress;
      if (g.dwellProgress === 0 && dwellPeak > 0) {
        if (!dwellFired && dwellPeak >= 0.15 && dwellPeak < 1 && now - lastDwellLog > 1500) {
          lastDwellLog = now;
          trace(`dwell reset at ${Math.round(dwellPeak * 100)}%: ${g.diag?.dwellReset || "?"}`);
        }
        dwellPeak = 0;
      }

      let wheel = 0;
      if (g.scroll) {
        const { rate, region, off } = scrollRate(g.scrollPointY);
        const centred = off;
        // rate > 0 reads down the page: the wheel turns toward him (negative)
        wheelRest += -rate * SCROLL_MAX_SPEED * WHEEL_PER_PX * dt;
        wheel = Math.trunc(wheelRest);
        wheelRest -= wheel;
        const sink = scrollDebug.current;
        if (sink) {
          sink.latched = true;
          sink.handY = Math.round(g.scrollPointY * 100);
          sink.centred = centred;
          sink.region = region === "NEUTRAL" ? "NEUTRAL" : region === "UPPER" ? "UPPER -> scroll down" : "LOWER -> scroll up";
          sink.rate = rate;
          sink.pxPerSec = rate * SCROLL_MAX_SPEED;
          sink.reason = region === "NEUTRAL" ? `inside neutral band |${Math.abs(off).toFixed(2)}| <= ${SCROLL_NEUTRAL_HALF}` : "scrolling";
        }
      } else {
        wheelRest = 0;
        if (scrollDebug.current) scrollDebug.current.latched = false;
      }
      // scroll diagnostics, 4/s while two fingers are up: where the fingertips are,
      // whether the pose latched (and if not, the engine's own reason), the region,
      // the rate and the wheel actually sent
      const twoUp = g.indexExtension > SCROLL_DIAG_EXT && g.middleExtension > SCROLL_DIAG_EXT;
      if (g.scroll || twoUp) {
        scrollTrying = true;
        lastScrollY = g.scroll ? g.scrollPointY : g.diag.scrollPointRaw;
        scrollSent += wheel;
        if (now - lastScrollLog >= SCROLL_DIAG_MS) {
          const raw = g.diag.scrollPointRaw;
          const judged = scrollRate(g.scroll ? g.scrollPointY : raw);
          const centred = judged.off;
          const region = judged.region;
          const rate = g.scroll ? judged.rate : 0;
          const direction = rate > 0 ? "DOWN" : rate < 0 ? "UP" : "none";
          trace(
            `scroll diag: y raw ${raw.toFixed(3)} filtered ${g.scrollPointY.toFixed(3)} off-centre ${centred.toFixed(2)} ` +
              `region ${region} | latched ${g.scroll ? "YES" : `NO (${g.diag.scroll})`} | rate ${rate.toFixed(2)} ${direction} ` +
              `${Math.round(rate * SCROLL_MAX_SPEED)} px/s | wheel sent ${scrollSent} | idx ${g.indexExtension.toFixed(2)} mid ${g.middleExtension.toFixed(2)} ` +
              `| bounds: camera frame (monitor-independent) upper<${(SCROLL_CENTRE_Y - SCROLL_NEUTRAL_HALF).toFixed(2)} lower>${(SCROLL_CENTRE_Y + SCROLL_NEUTRAL_HALF).toFixed(2)}`,
          );
          lastScrollLog = now;
          scrollSent = 0;
        }
      } else {
        scrollTrying = false;
      }
      const mode = g.scroll ? "scroll" : g.pinching ? "pinch" : steering ? "point" : "rest";
      const took = !steeredBefore && steering;
      steeredBefore = steeredBefore || steering;
      perfNote("pointer", 0);
      void invoke<[number, number] | null>("hand_pointer", { dx, dy, dwell: g.dwellProgress, click, wheel, active: true, mode }).then((at) => {
        // the first steer after his hand comes up: where the real cursor is (core.log)
        if (took && at) trace(`hand pointer steering: cursor at (${at[0]}, ${at[1]})`);
      });
    });
    return stop;
  }, [cursor, gestureRef, handSource, landmarks, core, scrollDebug]);

  // the five-finger zoom drives her panel (the second screen): the factor relative
  // to where the gesture began, every camera frame it is held, and its release
  useEffect(() => {
    let zooming = false;
    let seen: unknown = null;
    let since = 0;
    let low = 1;
    let high = 1;
    let palm = 0;
    const stop = onFrame(() => {
      const g = gestureRef.current;
      if (!g || landmarks.current === seen) return;
      seen = landmarks.current;
      if (g.zoom) {
        if (!zooming) {
          since = performance.now();
          low = high = 1;
          palm = g.diag.palmSpan;
        }
        zooming = true;
        low = Math.min(low, g.zoomFactor);
        high = Math.max(high, g.zoomFactor);
        void emitTo("dashboard", "irene://panel-zoom", { active: true, factor: g.zoomFactor });
      } else if (zooming) {
        zooming = false;
        void emitTo("dashboard", "irene://panel-zoom", { active: false, factor: 1 });
        const moved = high - low;
        core.send({
          type: "hud_trace",
          step:
            `panel zoom gesture: latched ${Math.round(performance.now() - since)} ms, factor ${low.toFixed(2)}-${high.toFixed(2)}` +
            `${moved < 0.02 ? " (did not scale - a still hand)" : ""}, palm span ${palm.toFixed(3)}`,
        });
      }
    });
    return stop;
  }, [core, gestureRef, landmarks]);

  // hand control on/off (Ctrl+Alt+H), and every hand click, into core.log
  useEffect(() => {
    void invoke<boolean>("pointer_enabled").then((on) => {
      pointerOnRef.current = on;
      setPointerOn(on);
    });
    const toggled = listen<boolean>(EVENT_POINTER, (event) => {
      pointerOnRef.current = event.payload;
      setPointerOn(event.payload);
      setActive(shellUp.current || event.payload);
      core.send({ type: "hud_trace", step: `hand pointer ${event.payload ? "ON" : "OFF - mouse only"} (ctrl+alt+h)` });
    });
    // Ctrl+Alt+Shift+O: screens-off mode (core decides whether it is enabled)
    const darken = listen("irene://screens-off", () => {
      core.send({ type: "screens_off" });
    });
    // Ctrl+Alt+Shift+L: lecture capture on/off (core decides which)
    const lecture = listen("irene://lecture", () => {
      core.send({ type: "lecture", action: "toggle" });
    });
    // Ctrl+Alt+Shift+S / +M: study mode / shiai on or off with no voice at all
    const mode = listen<string>("irene://mode", (event) => {
      core.send({ type: "mode_hotkey", mode: event.payload });
    });
    const clicked = listen<[number, number, boolean]>("irene://hand-click", (event) => {
      const [x, y, ok] = event.payload;
      core.send({ type: "hud_trace", step: `hand click at (${x}, ${y})${ok ? "" : " - Windows refused the input"}` });
    });
    return () => {
      void toggled.then((unlisten) => unlisten());
      void clicked.then((unlisten) => unlisten());
      void darken.then((unlisten) => unlisten());
      void lecture.then((unlisten) => unlisten());
      void mode.then((unlisten) => unlisten());
    };
  }, [core, setActive]);


  // where the HUD's time goes, into core.log every 10 s (perf.ts)
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (coreUp) core.send({ type: "hud_perf", ...takePerf() });
    }, 10000);
    return () => window.clearInterval(timer);
  }, [core, coreUp]);

  // her window on screen or not: core listens without a wake word while it is -
  // told on every change, and again whenever the link (re)connects
  useEffect(() => {
    if (coreUp) core.send({ type: "visibility", visible: shellVisible });
  }, [core, coreUp, shellVisible]);

  // core/ is authoritative for state, emotion and voice whenever it is connected
  useEffect(() => {
    const stopLink = core.onLink(setCoreUp);
    const stopMessages = core.onMessage((message) => {
      switch (message.type) {
        case "state":
          if (ASSISTANT_STATES.includes(message.value)) setAssistant(message.value);
          break;
        case "emotion":
          if (EMOTIONS.includes(message.value)) setEmotion(message.value);
          break;
        case "audio_level":
          speechLevel.push(message.value);
          break;
        case "reaction":
          showReaction(message.value, Boolean(message.big));
          break;
        case "warmup":
          void invoke("warmup", { on: message.on, onAt: message.onAt });
          core.send({ type: "hud_trace", step: `warm-up surfaces ${message.on ? (message.onAt ? "counting from Windows' ON" : "up") : "down"}` });
          break;
        case "skit":
          // a scripted take (core/irene/skit.py): no idle life in its pauses; a take
          // that opens on his "Hey Irene" starts with her put away
          if (message.phase === "start") {
            holdInteraction(true);
            if (message.hide) void invoke("sleep").catch(() => undefined);
          } else if (message.phase === "end" || message.phase === "error") {
            holdInteraction(false);
          }
          core.send({ type: "hud_trace", step: `skit ${message.phase}${message.name ? ` ${message.name}` : ""}${message.error ? `: ${message.error}` : ""}` });
          break;
        case "boot_skip":
          window.dispatchEvent(new Event("irene-boot-skip"));
          void emitTo("dashboard", "irene://boot-skip", null);
          break;
        case "dark":
          // screens-off mode: no detection at all while dark; only the mic listens
          setSuspended(message.value);
          void invoke("dark_mode", { on: message.value });
          core.send({ type: "hud_trace", step: `screens-off mode ${message.value ? "on: tracking suspended, windows away" : "off: tracking back"}` });
          break;
        case "intro_cursor":
          // her introduction: his cursor (and the hand's ring) gone until her greeting ends
          void invoke("intro_cursor", { hidden: message.hidden });
          core.send({ type: "hud_trace", step: `intro cursor ${message.hidden ? "hidden" : "back"}` });
          break;
        case "yield_front":
          // his Chrome is opening: it must come up in front of her, on either screen
          void invoke("yield_front");
          core.send({ type: "hud_trace", step: "yield front: her windows step back for his Chrome" });
          break;
        case "panel":
          if (message.value) {
            pushPanel(message.value);
          } else {
            clearPanel();
          }
          break;
        case "transcript":
          if (message.role === "user") noteInteraction();
          console.log(`[irene] ${message.role}: ${message.text}`);
          break;
        case "muted":
          setMuted(message.value);
          break;
        case "summon": {
          const at = performance.now();
          window.clearTimeout(summonClear.current);
          // a skit line's domain (core/irene/skit.py) carries its own hold and bubble
          const hold = typeof message.hold_ms === "number" ? message.hold_ms : undefined;
          const bubble = typeof message.bubble === "string" && message.bubble ? message.bubble : undefined;
          if (message.phase === "start") {
            setSummonTimes({ start: at, part2: null, hold, bubble });
          } else if (message.phase === "part2") {
            setFlareCount((value) => value + 1);
            setSummonTimes((value) => ({ start: value?.start ?? at, part2: at, hold: hold ?? value?.hold, bubble: bubble ?? value?.bubble }));
          }
          // end: let the lift and the drop finish, then drop the sequence
          if (message.phase !== "start") {
            summonClear.current = window.setTimeout(() => setSummonTimes(null), summonTail({ start: at, part2: at, hold }));
          }
          break;
        }
        case "keiko": {
          // keiko, started by his voice: she suits up in the dojo and faces him; the
          // body model reads his strikes until it ends
          if (message.action === "start") {
            keikoActive.current = true;
            keikoReact(null);
            setEntrance(null);
            setBoard(null);
            showActivity("keiko", 0);
            setKeiko(true);
          } else if (message.action === "end") {
            keikoActive.current = false;
            keikoReact(null);
            setKeiko(false);
            if (currentActivity().name === "keiko") showActivity(null);
          } else {
            const { action, target, flags, call, who, result, ms, label } = message;
            if (action === "countdown") showActivity("keiko", 0);
            keikoReact({ action, at: performance.now(), target, flags, call, who, result, ms, label });
          }
          break;
        }
        case "strike_events": {
          // core switches the strike detector (and shiai's footwork) on with its
          // tuning, or off (null): study mode, shiai, a 3-swing calibration
          setStrikeEvents(message.config ?? null);
          core.send({ type: "hud_trace", step: `capture strike events ${message.config ? `ON at ${message.config.strikes.threshold.toFixed(1)}${message.config.moves ? " + footwork" : ""}` : "off"}` });
          break;
        }
        case "strike_readout":
          // -Dev: the peak he just produced, against the threshold, on her face
          showReadout(message.text, performance.now());
          break;
        case "shiai": {
          // shiai: the keiko dojo, her in bogu facing him; core runs the bout and
          // sends her answers as keiko actions - and the score, the moment a point is
          // called, on the scoreboard (led/score.ts)
          shiaiScore(scoreOn(currentScore(), message, performance.now()));
          if (message.action === "start") {
            keikoActive.current = true;
            keikoReact(null);
            setEntrance(null);
            setBoard(null);
            showActivity("keiko", 0);
          } else if (message.action === "end") {
            keikoActive.current = false;
            keikoReact(null);
            if (currentActivity().name === "keiko") showActivity(null);
          }
          break;
        }
        case "study": {
          // study mode: head down over the book, the bar filling; core switches the
          // strike events on with it
          const next = studyOn(currentStudy(), message, performance.now());
          studyState(next);
          if (message.action === "start") {
            setEntrance(null);
            setBoard(null);
            showActivity("study", 0);
          } else if (message.action === "end") {
            if (currentActivity().name === "study") showActivity(null);
          }
          break;
        }
        case "activity":
          // keiko holds the stage: no other scene replaces it until it ends
          if (keikoActive.current && message.value !== "keiko") break;
          // and so does study mode
          if (currentStudy() && message.value !== "study") break;
          // one scene at a time: a new scene ends the entrance it would draw over
          if (message.value) setEntrance(null);
          showActivity(message.value, message.loops ?? 0);
          break;
        case "game_hand":
          // her LED hand in the game (led/gameHand.ts): fade in, a pump on a counted
          // word as it is heard, or the shrug after a misread
          if (message.glyph === "shrug") gameHand({ kind: "shrug" });
          else if (typeof message.beat === "number") gameHand({ kind: "beat", n: message.beat });
          else gameHand({ kind: "show" });
          break;
        case "game_mode": {
          game.set(message.on, performance.now(), message.ms, message.game ?? "");
          if (!message.on) gameHand({ kind: "hide" });
          core.send({ type: "hud_trace", step: `game mode ${message.on ? `ON (${message.game ?? "?"}, ${Math.round((message.ms ?? 0) / 1000)} s): normal gestures suspended` : "OFF: gestures back"}` });
          break;
        }
        case "game_shoot": {
          // the shoot instant is now: wait out the window, then send what the camera saw
          const t0 = performance.now();
          const { id, before, after } = message;
          // her throw shows at THE instant his hand's window is anchored to - the same
          // t0 - never before (it isn't in any earlier message)
          if (message.throw) gameHand({ kind: "throw", glyph: message.throw }, t0);
          window.setTimeout(() => {
            const frames = game.window(t0, t0 - before, t0 + after);
            const span = frames.length > 1 ? (frames[frames.length - 1].t - frames[0].t) / 1000 : 0;
            core.send({ type: "game_frames", id, frames, fps: span > 0 ? Math.round((frames.length - 1) / span) : 0 });
          }, after + 50);
          break;
        }
        case "draw": {
          // nothing is drawn over keiko, or over study mode
          if ((keikoActive.current || currentStudy()) && message.value) break;
          // checked again in full here: anything wrong draws nothing
          let refused = "";
          const drawing = message.value ? prepare(message.value, (why) => { refused = why; console.warn(`[irene] draw refused: ${why}`); }) : null;
          // a live chess board: what it drew goes back to core, checked against the game
          const spec = message.value as { template?: string; live?: boolean; ply?: number } | null;
          if (spec && spec.template === "chessboard" && spec.live) {
            const echo = drawing ? liveEcho(drawing.args as Parameters<typeof liveEcho>[0]) : null;
            core.send(echo ? { type: "chess_shown", ...echo } : { type: "chess_shown", ply: spec.ply ?? -1, fen: "", refused: refused || "not drawn" });
          }
          // a drawing takes the whole matrix: the scene under it ends, so it can't
          // come back on top of the next thing when the drawing goes
          if (drawing && currentActivity().name) showActivity(null);
          // a chess game's board moves on in place: the next position replaces the
          // last without sketching the whole board in again
          const live = Boolean(drawing && (message.value as { live?: boolean }).live && boardRef.current?.drawing.name === drawing.name);
          setBoard(drawing ? { drawing, at: live && boardRef.current ? boardRef.current.at : performance.now() } : null);
          break;
        }
        case "board_term": {
          // one more key term of the research answer she is saying: onto the terms
          // board (a new one if something else was up), stamped with the board's
          // own clock so only the new term animates
          const now = performance.now();
          const spec = termsBoard.current;
          const fresh = !spec || !boardRef.current || boardRef.current.drawing.name !== "terms";
          const at = fresh ? now : (boardRef.current?.at ?? now);
          const terms = [...(fresh ? [] : spec.terms), ...message.terms.map((text) => ({ text, at: Math.round(now - at) }))];
          const next = { template: "terms", title: fresh ? message.title || undefined : spec.title, terms };
          const drawing = prepare(next);
          if (drawing) {
            termsBoard.current = next;
            if (fresh && currentActivity().name) showActivity(null);
            // the ref too, now: the next term may arrive before React re-renders
            boardRef.current = { drawing, at };
            setBoard(boardRef.current);
          }
          break;
        }
        case "board_render": {
          // drawn off-screen by the board's own code, never on her face
          core.send({ type: "board_rendered", id: message.id, png: boardSnapshot(message.spec) });
          break;
        }
        case "board_sync": {
          // an illustrated answer: a new drawing (spec), and/or what the sentence
          // just heard adds to it, each item stamped with the board's own clock so
          // it appears - and animates - from this moment
          const now = performance.now();
          const fresh = message.spec !== undefined;
          const base = fresh ? { reveal: [], notes: [], ...message.spec } : syncBoard.current;
          if (!base || (!fresh && !boardRef.current)) break;
          const at = fresh ? now : (boardRef.current?.at ?? now);
          const next: Record<string, unknown> = { ...base };
          // whole fields replaced (a composed drawing re-laid out, a chess line
          // found): a shape it already showed keeps the moment it appeared
          const seen = new Map<string, unknown>();
          for (const old of Array.isArray(base.shapes) ? (base.shapes as Record<string, unknown>[]) : []) {
            if (typeof old.id === "string") seen.set(old.id, old.at);
          }
          // the elements a sentence brings up are drawn one after another, never all at
          // once: each new element (its shapes share an id prefix, "e3.0", "e3.1") starts
          // BUILD_STAGGER_MS after the one before it
          const order = new Map<string, number>();
          for (const [key, value] of Object.entries(message.set ?? {})) {
            next[key] =
              key === "shapes" && Array.isArray(value)
                ? (value as Record<string, unknown>[]).map((s) => {
                    if (typeof s.id === "string" && seen.has(s.id)) return { ...s, at: seen.get(s.id) };
                    const element = typeof s.id === "string" ? s.id.split(".")[0] : "";
                    if (!order.has(element)) order.set(element, order.size);
                    return { ...s, at: Math.round(now - at) + (order.get(element) ?? 0) * BUILD_STAGGER_MS };
                  })
                : value;
          }
          for (const [key, items] of Object.entries(message.add ?? {})) {
            const had = Array.isArray(next[key]) ? (next[key] as unknown[]) : [];
            next[key] = [...had, ...items.map((item) => ({ ...item, at: Math.round(now - at) }))];
          }
          const drawing = prepare(next);
          const added = [
            ...Object.entries(message.add ?? {}).map(([key, items]) => `${key} ${items.map((i) => String(i.key ?? i.text ?? "")).join(", ")}`),
            ...Object.entries(message.set ?? {}).map(([key, value]) =>
              key === "shapes" && Array.isArray(value)
                ? `shapes ${(value as Record<string, unknown>[]).filter((s) => typeof s.id === "string" && !seen.has(s.id)).map((s) => String(s.text ?? s.id)).join(", ") || "(re-laid out)"}`
                : `${key} set`,
            ),
          ].join("; ");
          if (drawing) {
            syncBoard.current = next;
            if (fresh && currentActivity().name) showActivity(null);
            boardRef.current = { drawing, at };
            setBoard(boardRef.current);
          }
          // what the board drew and when (ms on its clock), for core.log - no screenshots
          core.send({ type: "hud_trace", step: `board ${drawing ? "drew" : "REFUSED"} ${String(next.template)}${fresh ? " (new)" : ""} at ${Math.round(now - at)} ms: ${added || "-"}` });
          break;
        }
        case "conversation":
          setBoard(null);
          break;
        case "entrance":
          if (message.phase === "start" && isEntrance(message.name)) {
            // one scene at a time: the entrance replaces whatever was playing
            showActivity(null);
            setBoard(null);
            playEntrance(message.name);
          } else if (message.phase === "end") {
            window.clearTimeout(entranceClear.current);
            setEntrance(null);
          }
          break;
        case "tool":
          // deterministic: the tool's own prop while it runs, whatever the model says
          if (message.status === "running" && message.cue && isActivity(message.cue)) {
            if (toolProp.current) window.clearTimeout(toolProp.current.timer);
            toolProp.current = { name: message.cue, since: performance.now(), timer: 0 };
            showActivity(message.cue);
          } else if (message.status !== "running" && message.status !== "confirm") {
            stopToolProp();
          }
          break;
        case "reply":
          stopToolProp();
          break;
        case "debug_point":
          if (import.meta.env.DEV) setSyntheticPoint({ x: message.x, y: message.y }, message.ms);
          break;
        case "summon_request":
          // "Hey Irene" / "Irene Adler": the hotkey's own summon, through Rust, so the
          // window shows even while hidden and the summon comes back to core as usual.
          // Each step is traced into core.log ("summon path 3-6").
          voiceSummon.current = performance.now();
          core.send({ type: "hud_trace", step: `3: HUD got summon_request (${message.by}), document hidden=${document.hidden}` });
          void invoke("summon_voice", { by: message.by })
            .then(() => core.send({ type: "hud_trace", step: "4: summon_voice invoked in Rust" }))
            .catch((cause: unknown) => {
              console.error("[irene] voice summon failed", cause);
              core.send({ type: "hud_trace", step: `STOPPED at 4: summon_voice failed: ${String(cause)}` });
            });
          break;
        case "voice":
          setVoice({ phase: message.phase, at: performance.now(), remainingMs: message.remainingMs, totalMs: message.totalMs });
          if (message.phase === "hearing") noteInteraction();
          if (message.phase === "off" && performance.now() - listenPressed.current < 3000) setBarOpen(true);
          break;
        case "capture_shield": {
          // a screenshot is about to be taken: keep this window out of it
          const on = message.on;
          void invoke("capture_shield", { on })
            .catch((cause: unknown) => console.error("[irene] capture shield failed", cause))
            .finally(() => core.send({ type: "capture_shield_ack", on }));
          break;
        }
      }
    });
    core.start();
    return () => {
      stopMessages();
      stopLink();
      core.stop();
    };
  }, [core, speechLevel, stopToolProp, playEntrance]);

  // the panel's mouse path, step by step, into core.log: the window taking the
  // mouse over the panel (Rust), then the webview seeing the press and the click -
  // so a link that "doesn't open" says where it stopped
  useEffect(() => {
    const pending = listen<boolean>(EVENT_CURSOR, (event) => {
      core.send({ type: "hud_trace", step: `panel mouse: window ${event.payload ? "captures the mouse (over the panel)" : "click-through again"}` });
    });
    const where = (event: Event): string | null => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target || !target.closest(".panel-dock")) return null;
      const hit = target.closest("button, a") ?? target;
      return `${hit.tagName.toLowerCase()}.${String(hit.className || "").split(" ")[0]}`;
    };
    const onDown = (event: PointerEvent) => {
      const hit = where(event);
      if (hit) core.send({ type: "hud_trace", step: `panel mouse: pointerdown (${event.pointerType}, button ${event.button}) on ${hit}` });
    };
    const onClick = (event: MouseEvent) => {
      const hit = where(event);
      if (hit) core.send({ type: "hud_trace", step: `panel mouse: click on ${hit}` });
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("click", onClick, true);
    return () => {
      void pending.then((unlisten) => unlisten());
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("click", onClick, true);
    };
  }, [core]);

  // a voice summon in flight (performance.now() it was asked for): its steps are traced
  const voiceSummon = useRef(0);
  useEffect(() => {
    const pending = listen<boolean>(EVENT_SHOWN, (event) => {
      if (performance.now() - voiceSummon.current < 5000) {
        core.send({ type: "hud_trace", step: event.payload ? "5: window shown - Windows says visible" : "STOPPED at 5: show() ran but Windows says NOT visible" });
      }
    });
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, [core]);

  useEffect(() => {
    const pending = listen<{ text: string; source: string; by: string }>(EVENT_SPEAK, (event) => {
      if (event.payload.source === "summon" && (event.payload.by === "voice" || event.payload.by === "adler")) {
        core.send({ type: "hud_trace", step: `6: summon speak (${event.payload.by}) sent back to core` });
      }
      if (!core.send({ type: "speak", text: event.payload.text, source: event.payload.source, by: event.payload.by })) {
        console.warn("[irene] core is down; summon line not spoken");
        if (event.payload.source !== "summon") return;
        // no core to pick one: the same rule here, played silently - the hand sign
        // always gets the domain expansion, the hotkey a random one
        const name = event.payload.by === "sign" ? DOMAIN_EXPANSION : pickEntrance(lastEntrance.current);
        lastEntrance.current = name;
        if (isEntrance(name)) playEntrance(name);
        else setFlareCount((value) => value + 1);
      }
    });
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, [core, playEntrance]);

  // Operator controls, for exercising states by hand when core/ isn't driving them -
  // reachable from an unfocused window, hence the events.
  const cycleState = useCallback(() => {
    setAssistant((value) => {
      const next =
        ASSISTANT_STATES[(ASSISTANT_STATES.indexOf(value) + 1) % ASSISTANT_STATES.length];
      console.log(`[irene] state -> ${next}`);
      return next;
    });
  }, []);

  const cycleEmotion = useCallback(() => {
    setEmotion((value) => {
      const next = EMOTIONS[(EMOTIONS.indexOf(value) + 1) % EMOTIONS.length];
      console.log(`[irene] emotion -> ${next}`);
      return next;
    });
  }, []);

  // Debug push. The panel only ever appears because content was pushed to it -
  // never on launch, never on summon.
  const togglePanel = useCallback(() => {
    if (getPanel()) {
      clearPanel();
    } else {
      pushPanel(MOCK_CONTENT);
    }
  }, []);

  // F11 previews everything the matrix can show: each gesture, each scene, then the
  // domain-expansion sequence (silent, on the cached clip's timing), then off.
  const previewIndex = useRef(-1);
  const previewTimers = useRef<number[]>([]);
  const cycleReaction = useCallback(() => {
    for (const timer of previewTimers.current) window.clearTimeout(timer);
    previewTimers.current = [];
    const items = [
      ...EMOTIONS.filter((name) => name !== "neutral").map((name) => ({ kind: "expression" as const, name })),
      ...REACTIONS.map((name) => ({ kind: "reaction" as const, name })),
      ...ACTIVITIES.map((name) => ({ kind: "scene" as const, name })),
      { kind: "summon" as const, name: "domainExpansion" },
      ...ENTRANCE_NAMES.map((name) => ({ kind: "entrance" as const, name })),
    ];
    previewIndex.current = (previewIndex.current + 1) % (items.length + 1);
    const item = items[previewIndex.current];
    showActivity(null);
    setSummonTimes(null);
    setEntrance(null);
    setEmotion("neutral");
    if (!item) {
      console.log("[irene] preview -> off");
      return;
    }
    console.log(`[irene] preview ${previewIndex.current + 1}/${items.length} -> ${item.name}`);
    if (item.kind === "expression") {
      setEmotion(item.name);
      previewTimers.current = [window.setTimeout(() => setEmotion("neutral"), EXPRESSION_PREVIEW_MS)];
    } else if (item.kind === "reaction") {
      showReaction(item.name);
    } else if (item.kind === "scene") {
      showActivity(item.name);
    } else if (item.kind === "entrance") {
      playEntrance(item.name);
    } else {
      const start = performance.now();
      setSummonTimes({ start, part2: null });
      previewTimers.current = [
        window.setTimeout(() => {
          setFlareCount((value) => value + 1);
          setSummonTimes({ start, part2: performance.now() });
        }, SUMMON_PREVIEW_PART2_MS),
        window.setTimeout(() => setSummonTimes(null), SUMMON_PREVIEW_PART2_MS + SUMMON_TAIL_MS),
      ];
    }
  }, [playEntrance]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      // typing in the command bar is not an operator key
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === DEBUG_KEY) {
        event.preventDefault();
        setDebug((value) => !value);
        return;
      }
      if (event.key === CALIBRATE_KEY) {
        event.preventDefault();
        setCalibrate((value) => !value);
        return;
      }
      if (event.key === CLOSE_KEY) {
        event.preventDefault();
        void getCurrentWindow()
          .close()
          .catch((cause: unknown) => {
            console.error("window close failed", cause);
          });
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const pending = listen(EVENT_TOGGLE_DEBUG, () => setDebug((value) => !value));
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    const pending = listen(EVENT_TOGGLE_CALIBRATE, () => setCalibrate((value) => !value));
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    const pending = Promise.all([
      listen(EVENT_CYCLE_STATE, cycleState),
      listen(EVENT_CYCLE_EMOTION, cycleEmotion),
      listen(EVENT_TOGGLE_PANEL, togglePanel),
      listen(EVENT_CYCLE_REACTION, cycleReaction),
      listen(EVENT_CYCLE_ACTIVITY, cycleActivity),
      listen<string>(EVENT_CAPTURE, (event) => startCapture(event.payload)),
      listen<string>(EVENT_CORPUS, (event) => {
        const action = event.payload;
        if (action === "start" || action === "redo" || action === "stop") core.send({ type: "corpus", action });
      }),
      // ctrl+alt+shift+p: pinned on top of everything, or an ordinary window again
      // every z-order decision (src-tauri/src/zorder.rs), pin included, into core.log
      listen<string>(EVENT_ZORDER, (event) => {
        core.send({ type: "hud_trace", step: `panel z-order: ${event.payload}` });
      }),
      listen<string>(EVENT_SKIT, (event) => {
        const action = event.payload;
        if (action === "start" || action === "abort") core.send({ type: "skit", action });
      }),
      listen(EVENT_COMMAND_BAR, () => setBarOpen(true)),
      listen<PanelContent | null>(EVENT_PANEL, (event) => {
        if (event.payload) {
          pushPanel(event.payload);
        } else {
          clearPanel();
        }
      }),
      listen<string>(EVENT_REACTION, (event) => {
        showReaction(event.payload);
      }),
    ]);
    return () => {
      void pending.then((handles) => {
        for (const unlisten of handles) unlisten();
      });
    };
  }, [cycleState, cycleEmotion, togglePanel, cycleReaction]);

  // the panel's half of the dev geometry hook, relayed into core.log
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const pending = listen<string>("irene://geometry-dev-reply", (event) => core.send({ type: "hud_trace", step: event.payload }));
    return () => void pending.then((unlisten) => unlisten());
  }, [core]);

  // Dev test hooks. Tests drive the UI through these - never with OS keystrokes or
  // global shortcuts, which reach whatever app owns them (see CLAUDE.md).
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    return core.onMessage((message) => {
      if (message.type !== "debug_ui") return;
      console.log(`[irene] debug_ui ${message.action}`);
      switch (message.action) {
        case "summon":
          void invoke("summon");
          break;
        case "preview":
          cycleReaction();
          break;
        case "bar_open":
          void invoke("show").then(() => setBarOpen(true));
          break;
        case "bar_close":
          setBarOpen(false);
          break;
        case "bar_submit":
          setBarOpen(true);
          setBarInject((value) => ({ text: message.text ?? "", n: (value?.n ?? 0) + 1 }));
          break;
        case "capture":
          void invoke("show").then(() => startCapture(message.text || "summon"));
          break;
        case "debug":
          setDebug((value) => !value);
          break;
        case "typing":
          noteTyping();
          break;
        case "pin":
          // as ctrl+alt+shift+p does: pinned on top / unpinned (zorder.rs)
          void invoke("toggle_pin");
          break;
        case "hide":
          // as SLEEP does: the window hidden, for a check that starts from hidden
          void invoke("sleep");
          break;
        case "show":
          // shown without a summon (no entrance, no sound): tracking runs while shown
          void invoke("show");
          break;
        case "dashboard_click":
          // "news:2" / "markets:1": the Nth row on the panel, clicked as a mouse would
          // (the DOM's own click, never OS input)
          void emitTo("dashboard", "irene://dashboard-click-dev", message.text ?? "");
          break;
        case "visibility_path": {
          // the very handler of one way to hide or show her (tray, ctrl+alt+esc, a
          // minimize, a close) - then where both windows stand, into core.log
          const path = message.text ?? "";
          void invoke("dev_visibility_path", { path })
            .catch((cause: unknown) => core.send({ type: "hud_trace", step: `visibility path ${path} failed: ${String(cause)}` }))
            .then(() => new Promise((done) => window.setTimeout(done, 900)))
            .then(() => invoke<string>("visibility_report"))
            .then((report) => core.send({ type: "hud_trace", step: `after ${path}: ${report}` }));
          break;
        }
        case "geometry": {
          // both windows against their monitors, and each layout's box against its
          // window (both fill their screen), into core.log
          const box = document.querySelector<HTMLElement>(".irene")?.getBoundingClientRect();
          const scale = document.querySelector<HTMLElement>(".irene")?.style.getPropertyValue("--ui-scale");
          const main = box
            ? `interface ${box.width.toFixed(0)}x${box.height.toFixed(0)} at (${box.left.toFixed(0)}, ${box.top.toFixed(0)}) scale ${scale} in ${window.innerWidth}x${window.innerHeight}`
            : "no interface";
          void invoke<string>("geometry_report").then((report) => {
            // one line each: core keeps 200 characters of a trace
            for (const part of [...report.split("; "), main]) core.send({ type: "hud_trace", step: `panel geometry: ${part}` });
          });
          void emitTo("dashboard", "irene://geometry-dev", null);
          break;
        }
        case "kamae":
          // as the pose watcher would: she suits up, and core answers fired up
          showActivity(message.text === "end" ? null : "kamae", 0);
          core.send({ type: "kamae", phase: message.text === "end" ? "end" : "start" });
          break;
        case "panel_link": {
          // "click" the Nth clickable thing on the panel (text = its index), as a
          // mouse click would - the DOM's own click, never OS input
          // (her panel is on the second screen now: the click happens there)
          void emitTo("dashboard", EVENT_PANEL_LINK_DEV, Number(message.text ?? "0"));
          break;
        }
      }
    });
  }, [core, cycleReaction, noteTyping]);

  useEffect(() => {
    const pending = listen<boolean>(EVENT_VISIBILITY, (event) => {
      shellUp.current = event.payload;
      // with hand control on, tracking runs whatever she is doing
      setActive(event.payload || pointerOnRef.current);
      setShellVisible(event.payload);
      if (!event.payload) setBarOpen(false);
    });
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, [setActive]);

  // Both summon paths - crossed fingers and ctrl+alt+i - come back through the
  // backend, so the arrival is identical whichever one fired it. The spoken line
  // rides its own irene://speak event to core, which plays the cached clip and
  // reports its phases back; the flare waits for "part2".
  useEffect(() => {
    const pending = listen<string>(EVENT_SUMMON, (event) => {
      console.log(`[irene] summon: ${event.payload}`);
      setBoard(null);
      setShellVisible(true);
      setAssistant((value) => (value === "error" ? value : "listening"));
    });
    return () => {
      void pending.then((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    if (gestures.summonCount === 0) return;
    void invoke("summon").catch((cause: unknown) => {
      console.error("summon failed", cause);
    });
  }, [gestures.summonCount]);

  useEffect(() => {
    if (!debug) return;

    const draw = (): void => {
      const node = canvas.current;
      const source = video.current;
      const ctx = node?.getContext("2d");
      if (!node || !source || !ctx) return;

      const width = source.videoWidth || node.width;
      const height = source.videoHeight || node.height;
      if (node.width !== width || node.height !== height) {
        node.width = width;
        node.height = height;
      }

      ctx.clearRect(0, 0, width, height);
      const hands = landmarks.current;

      for (const points of hands ?? []) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = SKELETON_COLOR;
        ctx.beginPath();
        for (const connection of HandLandmarker.HAND_CONNECTIONS) {
          const from = points[connection.start];
          const to = points[connection.end];
          if (!from || !to) continue;
          ctx.moveTo(from.x * width, from.y * height);
          ctx.lineTo(to.x * width, to.y * height);
        }
        ctx.stroke();

        for (let i = 0; i < points.length; i += 1) {
          const point = points[i];
          const keyed = i === CURSOR_JOINT || i === MIDDLE_JOINT || i === THUMB_JOINT;
          ctx.beginPath();
          ctx.arc(point.x * width, point.y * height, keyed ? 7 : 4, 0, Math.PI * 2);
          ctx.fillStyle = keyed ? SKELETON_COLOR : JOINT_COLOR;
          ctx.fill();
        }
      }
    };

    return onFrame(draw);
  }, [debug, landmarks, video]);

  return (
    <main className={debug ? "hud hud-debug" : "hud"}>
      <div className="hud-stage" aria-hidden="true">
        <video ref={video} className="hud-video" playsInline muted />
        <canvas ref={canvas} className="hud-skeleton" />
      </div>

      {debug ? (
        <div className="hud-panel">
          <div className="hud-row">
            <span className="hud-label">FPS</span>
            <span className="hud-value">
              {fps} / {sourceFps}
            </span>
          </div>
          <div className="hud-row">
            <span className="hud-label">DETECT</span>
            <span className="hud-value">{detectMs} ms</span>
          </div>
          <div className="hud-row">
            <span className="hud-label">TRACKING</span>
            <span className={tracking ? "hud-value on" : "hud-value off"}>
              {tracking ? "LOCKED" : "NONE"}
            </span>
          </div>
          <div className="hud-row">
            <span className="hud-label">CORE</span>
            <span className={coreUp ? "hud-value on" : "hud-value off"}>
              {coreUp ? "LINK" : "DOWN"}
            </span>
          </div>
          <div className="hud-row">
            <span className="hud-label">MODE</span>
            <span className="hud-value">{gestures.mode.toUpperCase()}</span>
          </div>
          <div className="hud-row">
            <span className="hud-label">SEL / SMN</span>
            <span className="hud-value">
              {gestures.selectCount} / {gestures.summonCount}
            </span>
          </div>
          <LiveMetrics gestures={gestureRef} />
          <div className="hud-chips">
            <span className={gestures.pointing ? "hud-chip on" : "hud-chip"}>POINT</span>
            <span className={gestures.scroll ? "hud-chip on" : "hud-chip"}>SCRL</span>
            <span className={gestures.zoom ? "hud-chip on" : "hud-chip"}>ZOOM</span>
            <span className={gestures.summon ? "hud-chip on" : "hud-chip"}>SMN</span>
          </div>
          {error ? <div className="hud-error">{error}</div> : null}
        </div>
      ) : null}

      {calibrate ? <Calibration gestures={gestureRef} scrollDebug={scrollDebug} /> : null}

      {lecture ? <LectureBadge status={lecture} /> : null}

      <MainInterface
        state={assistant}
        emotion={emotion}
        visible={shellVisible}
        cursor={cursor}
        gestures={gestureRef}
        summonCount={flareCount}
        level={speechLevel}
        muted={muted}
        summon={summonTimes}
        typing={typing && barOpen}
        entrance={entrance}
        board={board}
        voice={voice}
        bar={<CommandBar open={barOpen} onOpen={openBar} onClose={closeBar} core={core} inject={barInject} onTyping={noteTyping} />}
        onAction={(item: MainAction) => {
          console.log(`[irene] action ${item}`);
          switch (item) {
            case "listen":
              // hear him now, no wake word; with no microphone (or core down), type
              listenPressed.current = performance.now();
              if (!core.send({ type: "listen" })) setBarOpen(true);
              break;
            case "panel":
              togglePanelContent(EMPTY_PANEL);
              break;
            case "mute":
              // core owns the audio, so it owns the flag; the face updates when it answers
              if (!core.send({ type: "mute", value: !muted })) {
                console.warn("[irene] core is down; mute not changed");
                showReaction("facepalm");
              }
              break;
            case "sleep":
              setBarOpen(false);
              core.send({ type: "sleep" });
              setAssistant("dormant");
              setEmotion("neutral");
              void invoke("sleep").catch((cause: unknown) => {
                console.error("sleep failed", cause);
              });
              break;
          }
        }}
      />


      <GestureCapture run={captureRun} gestures={gestureRef} input={inputRef} pose={poseRef} armPose={armPose} timing={frameTiming} camera={cameraInfo} core={core} />
      <CorpusRecorder core={core} />

      {pointerOn ? null : <Reticle cursor={cursor} gestures={gestureRef} tracking={tracking} />}
    </main>
  );
}

export default App;
