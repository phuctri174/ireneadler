// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useRef } from "react";
import { note as perfNote } from "../perf";
import { onFrame } from "../tracking/frameLoop";
import { SILENT_LEVEL } from "./audioLevel";
import type { AudioLevelSource } from "./audioLevel";
import type { AssistantState, Emotion } from "./faceState";
import { onReaction } from "./reactions";
import type { ReactionEvent } from "./reactions";
import { ACTIVITY_LOOP_MS, IDLE_ACTIVITIES, currentActivity, onActivity, showActivity } from "./activity";
import type { ActivityEvent } from "./activity";
import { compose } from "../led/compose";
import { CELLS, Frame, INK } from "../led/grid";
import { LedRenderer, parseColor } from "../led/render";
import type { Rgb } from "../led/render";
import type { SummonTimes } from "../led/summon";
import type { EntranceName } from "../led/entrances";
import type { Prepared } from "../board/board";
import type { VoiceStage } from "../led/listening";
import { MicroExpressions } from "./micro";
import { IdleLife, glanceGaze } from "./idle";
import { lastInteraction } from "./interaction";
import { REACTION_MS } from "./reactions";
import { onGameHand } from "./gameHandBus";
import { currentScore } from "../led/score";
import { gameHandDone, gameHandOn } from "../led/gameHand";
import type { GameHand } from "../led/gameHand";
import "./Face.css";

const BREATHE_MS = 4200;
const ACCENT_FADE_MS = 220;

const STATE_TOKEN: Record<AssistantState, string> = {
  dormant: "--slate",
  listening: "--cyan",
  thinking: "--amber",
  speaking: "--mint",
  error: "--red",
};

/** At most 60 face frames a second (a hair under, so a 60 Hz display still gets every one). */
const FACE_FRAME_MS = 1000 / 60 - 1.5;

function fadeAlpha(deltaSeconds: number, milliseconds: number): number {
  // exponential approach; tau chosen so `milliseconds` lands at ~90%
  const tau = milliseconds / 1000 / 2.303;
  return 1 - Math.exp(-deltaSeconds / tau);
}

export interface FaceProps {
  state: AssistantState;
  emotion: Emotion;
  /** Short-window RMS of Irene's own speech. */
  level?: AudioLevelSource;
  /** TTS output is off; a glyph on the matrix says so. */
  muted?: boolean;
  /** Timing of the domain-expansion sequence, while one is running. */
  summon?: SummonTimes | null;
  /** Visible on screen - idle scenes only play to an audience. */
  visible?: boolean;
  /** He is typing to her: she looks down at the bar, curious. */
  typing?: boolean;
  /** A summon entrance playing, from when it was heard. */
  entrance?: { name: EntranceName; at: number } | null;
  /** The illustration board, when she is drawing. */
  board?: { drawing: Prepared; at: number } | null;
  /** Voice input: listening, hearing him, the end-of-speech countdown. */
  voice?: VoiceStage | null;
}

export function Face({ state, emotion, level, muted = false, summon = null, visible = true, typing = false, entrance = null, board = null, voice = null }: FaceProps) {
  const root = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const look = useRef({ state, emotion, level: level ?? SILENT_LEVEL, muted, summon, visible, typing, entrance, board, voice });

  look.current = { state, emotion, level: level ?? SILENT_LEVEL, muted, summon, visible, typing, entrance, board, voice };

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const renderer = new LedRenderer(node);
    const target = new Frame();
    const values = new Float32Array(CELLS);
    const inks = new Uint8Array(CELLS);

    const css = getComputedStyle(document.documentElement);
    const token = (name: string): Rgb => parseColor(css.getPropertyValue(name) || "#ffffff");
    renderer.setColor(INK.pink, [255, 95, 162]);
    renderer.setColor(INK.white, [234, 255, 255]);
    renderer.setColor(INK.amber, token("--amber"));
    renderer.setColor(INK.red, token("--red"));
    renderer.setColor(INK.iceCore, [168, 228, 255]);
    renderer.setColor(INK.iceRing, [60, 150, 255]);
    renderer.setColor(INK.cyan, token("--cyan"));
    renderer.setColor(INK.green, [40, 196, 104]);
    renderer.setColor(INK.violet, [176, 150, 255]);
    // palette tokens are constants; read them once, not per frame
    const stateRgb = Object.fromEntries(
      (Object.keys(STATE_TOKEN) as AssistantState[]).map((name) => [name, token(STATE_TOKEN[name])]),
    ) as Record<AssistantState, Rgb>;
    const accent: Rgb = [...stateRgb[look.current.state]];

    const resize = (): void => renderer.resize();
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    // the interface scales with a CSS transform, which ResizeObserver doesn't see
    const remeasure = window.setInterval(resize, 1000);

    let reaction: ReactionEvent | null = null;
    let activity: ActivityEvent = currentActivity();
    // her hand in a hand game (led/gameHand.ts): each of core's messages folded in at
    // the instant it happened
    let hand: GameHand | null = null;
    const stopGameHand = onGameHand(({ event, at }) => {
      hand = gameHandOn(hand, event, at);
    });
    const stopReaction = onReaction((event) => {
      reaction = event;
    });
    const stopActivity = onActivity((event) => {
      activity = event;
    });

    const micro = new MicroExpressions();
    // when the current feeling arrived: her body moves with it from then (led/motion.ts)
    let feeling: { emotion: Emotion; at: number } | null = null;
    // idle life (face/idle.ts): glances, a stretch, humming, a short scene
    const idle = new IdleLife(Object.fromEntries(IDLE_ACTIVITIES.map((name) => [name, ACTIVITY_LOOP_MS[name]])));

    // a 128x72 LED face needs no more than 60 frames a second: the loop runs at the
    // monitor's rate (158-190 Hz measured), and every drawn frame is GPU work the
    // LLM and the trackers share. Fades use the real time between drawn frames.
    let lastDrawn = 0;
    const stop = onFrame((now, frameDelta) => {
      // asleep, her window stays up for the hand pointer (pointer.rs) but she is not
      // on it: nothing to draw (the hidden window used to pause this by itself)
      if (!look.current.visible) {
        lastDrawn = 0;
        return;
      }
      if (lastDrawn && now - lastDrawn < FACE_FRAME_MS) return;
      if (lastDrawn) perfNote("gap", now - lastDrawn);
      const deltaSeconds = lastDrawn ? (now - lastDrawn) / 1000 : frameDelta;
      lastDrawn = now;
      const frameStart = performance.now();
      const { state: current, emotion: mood, level: source, muted: silent, summon: times, visible: shown, typing: keys, entrance: arriving, board: drawing, voice: hearing } = look.current;

      const life = micro.update(now, { state: current, emotion: mood, typing: keys && current !== "speaking" });
      if (feeling?.emotion !== mood) feeling = { emotion: mood, at: now };

      // a finite activity ends after its loops; idle scenes are one loop each
      if (activity.name && activity.loops > 0 && now - activity.at >= ACTIVITY_LOOP_MS[activity.name] * activity.loops) {
        showActivity(null);
      }
      // what idle life is doing now; anything real (a reply's cue, a tool's prop, a
      // drawing, an entrance, a summon) owns the face instead
      const mine = idle.current();
      const ownReaction = reaction !== null && now - reaction.at < REACTION_MS && !(mine?.kind === "stretch" && reaction.name === "stretch");
      const ownActivity = activity.name !== null && !(mine?.kind === "scene" && activity.name === mine.scene);
      const beat = idle.update(now, {
        state: current,
        visible: shown,
        lastInteraction: lastInteraction(),
        busy: ownReaction || ownActivity || !!arriving || !!drawing || !!times || !!hand,
      });
      if (beat.stopped?.kind === "scene" && activity.name === beat.stopped.scene) showActivity(null);
      if (beat.stopped?.kind === "stretch" && reaction?.name === "stretch") reaction = null;
      if (beat.started?.kind === "scene" && beat.started.scene) showActivity(beat.started.scene, 1);
      if (beat.started?.kind === "stretch") reaction = { name: "stretch", at: now };
      const glance = beat.beat?.kind === "glance" ? glanceGaze(beat.beat, now) : null;

      // accent eases between state colours like the old CSS colour transition
      const want = stateRgb[current];
      const k = fadeAlpha(deltaSeconds, ACCENT_FADE_MS);
      let moved = false;
      for (let c = 0; c < 3; c += 1) {
        const next = Math.abs(want[c] - accent[c]) < 1 ? want[c] : accent[c] + (want[c] - accent[c]) * k;
        if (Math.round(next) !== Math.round(accent[c])) moved = true;
        accent[c] = next;
      }
      if (moved || deltaSeconds === 0) {
        renderer.setColor(INK.accent, [Math.round(accent[0]), Math.round(accent[1]), Math.round(accent[2])]);
      }

      compose(target, {
        state: current,
        emotion: mood,
        emotionAt: feeling.at,
        level: current === "speaking" ? source.read(now) : 0,
        now,
        blinking: life.blinking,
        gazeX: glance ? glance.x : life.gazeX,
        gazeY: glance ? glance.y : life.gazeY,
        // typing to her makes her curious, unless core has set a feeling of its own
        flash: life.flash ?? (keys && mood === "neutral" && current !== "speaking" ? "curious" : null),
        muted: silent,
        reaction,
        activity: activity.name ? { name: activity.name, at: activity.at } : null,
        summon: times,
        entrance: arriving,
        board: drawing,
        humming: beat.beat?.kind === "hum" ? beat.beat.at : null,
        voice: hearing,
        gameHand: hand,
        score: currentScore(),
      });
      if (hand && gameHandDone(hand, now)) hand = null;

      // every cell eases toward its target at the rate its layer asked for
      for (let i = 0; i < CELLS; i += 1) {
        const goal = target.value[i];
        // a lit cell takes its layer's colour even when its brightness is steady
        // (eyes going white-hot and back); a fading-out cell keeps its colour
        if (goal > 0.02) inks[i] = target.ink[i];
        const cur = values[i];
        if (goal === cur) continue;
        const next = cur + (goal - cur) * fadeAlpha(deltaSeconds, target.fade[i]);
        values[i] = Math.abs(goal - next) < 0.004 ? goal : next;
      }
      renderer.draw(values, inks);
      perfNote("face", performance.now() - frameStart);

      const face = root.current;
      if (face) {
        // slow breathe only while dormant with nothing playing
        const breathe =
          current === "dormant" && !activity.name
            ? 0.82 + 0.18 * (0.5 + 0.5 * Math.sin((now / BREATHE_MS) * Math.PI * 2))
            : 1;
        face.style.setProperty("--face-breathe", breathe.toFixed(3));
      }
    });

    return () => {
      stop();
      stopReaction();
      stopGameHand();
      stopActivity();
      observer.disconnect();
      window.clearInterval(remeasure);
    };
  }, []);

  return (
    <div className={`face is-${state}`} ref={root} aria-hidden="true">
      <canvas className="face-canvas" ref={canvas} />
    </div>
  );
}

export default Face;
