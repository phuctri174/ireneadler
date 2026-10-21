// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
// One target frame per animation frame, from everything that is going on. Layers,
// back to front: face -> activity scene -> summon entrance -> gesture pose -> game hand ->
// summon sequence -> status glyphs. Who owns the face's expression, strongest
// first: summon, pose, entrance, scene, then the plain state/emotion.

import { drawReadout } from "./readout";
import type { Activity } from "../face/activity";
import type { AssistantState, Emotion } from "../face/faceState";
import type { Reaction } from "../face/reactions";
import { reactionEnvelope, REACTION_MS } from "../face/reactions";
import { drawFace, drawMuted, drawNotes } from "./face";
import type { FaceLook } from "./face";
import { COLS } from "./grid";
import type { Frame } from "./grid";
import { POSES, drawPose, poseMotion } from "./poses";
import { applyMotion, emotionMotion, hop } from "./motion";

// a "big" reaction (core attached_shows): the pose's own movement this much larger,
// and a hop up into it over its first moments - full body, not just the face
export const BIG_REACTION_GAIN = 2.2;
export const BIG_REACTION_HOP_PX = 4;
export const BIG_REACTION_HOP_MS = 900;
import { drawListening, voiceShown } from "./listening";
import type { VoiceStage } from "./listening";
import { drawScene, drawSceneBackdrop, sceneLook } from "./scenes";
import { theatreFor } from "./theatre";
import { drawBoard } from "../board/board";
import type { Prepared } from "../board/board";
import { drawEntrance, entranceActive, entranceLook } from "./entrances";
import type { EntranceName } from "./entrances";
import { REVEAL_MS, drawDomainHair, drawSummon, drawSummonBurst, domainShift, summonActive, summonLook } from "./summon";
import { drawBubble } from "./bubble";
import { drawGameHand } from "./gameHand";
import { drawScore } from "./score";
import type { ShiaiScore } from "./score";
import type { GameHand } from "./gameHand";
import type { SummonTimes } from "./summon";

export interface Stage {
  state: AssistantState;
  emotion: Emotion;
  /** When that emotion arrived (performance.now()): her body moves with it (led/motion.ts). */
  emotionAt?: number | null;
  level: number;
  now: number;
  blinking: boolean;
  muted: boolean;
  reaction: { name: Reaction; at: number; big?: boolean } | null;
  activity: { name: Activity; at: number } | null;
  summon: SummonTimes | null;
  /** The illustration board (board/board.ts) and when it was shown. */
  board?: { drawing: Prepared; at: number } | null;
  /** A summon entrance (led/entrances.ts), from when it was heard. */
  entrance?: { name: EntranceName; at: number } | null;
  /** Micro-expressions (face/micro.ts): small glances and a brief blended feeling. */
  gazeX?: number;
  gazeY?: number;
  flash?: Emotion | null;
  /** Idle life (face/idle.ts): she is humming, since this performance.now(). */
  humming?: number | null;
  /** Voice input (led/listening.ts): listening, hearing, the end-of-speech countdown. */
  voice?: VoiceStage | null;
  /** Her hand in a hand game (led/gameHand.ts): the count, her throw, the shrug. */
  gameHand?: GameHand | null;
  /** Shiai's running score (led/score.ts), on the left of the dojo. */
  score?: ShiaiScore | null;
}

/**
 * ONE scene on the matrix at a time: of an activity scene, a summon entrance and
 * the summon sequence, only the newest draws - a new scene clears the previous one
 * (two of them drawn over each other were a mess). The illustration board is not a
 * scene: it takes the whole matrix while it is up (and the HUD stops any scene
 * when a drawing arrives).
 */
export function oneScene(stage: Stage): Stage {
  const now = stage.now;
  const summon = stage.summon && summonActive(stage.summon, now) ? stage.summon : null;
  const entrance = stage.entrance && entranceActive(stage.entrance.name, now - stage.entrance.at) ? stage.entrance : null;
  const candidates: { kind: "activity" | "entrance" | "summon"; at: number }[] = [];
  if (stage.activity) candidates.push({ kind: "activity", at: stage.activity.at });
  if (entrance) candidates.push({ kind: "entrance", at: entrance.at });
  if (summon) candidates.push({ kind: "summon", at: summon.start });
  if (candidates.length < 2) return stage;
  const newest = candidates.reduce((a, b) => (b.at >= a.at ? b : a));
  return {
    ...stage,
    activity: newest.kind === "activity" ? stage.activity : null,
    entrance: newest.kind === "entrance" ? stage.entrance : null,
    summon: newest.kind === "summon" ? stage.summon : null,
  };
}

export function compose(frame: Frame, given: Stage): void {
  frame.clear();
  const stage = oneScene(given);
  const { now } = stage;

  const reaction = stage.reaction && now - stage.reaction.at < REACTION_MS ? stage.reaction : null;
  const poseWeight = reaction ? reactionEnvelope(Math.max(0, now - reaction.at)) : 0;
  const summon = stage.summon && summonActive(stage.summon, now) ? stage.summon : null;

  // an idle scene while dormant plays with her eyes open, just not at full brightness
  const faceState: AssistantState = stage.activity && stage.state === "dormant" ? "listening" : stage.state;
  const look: FaceLook = {
    state: faceState,
    emotion: stage.flash ?? stage.emotion,
    blinking: stage.blinking,
    level: stage.level,
    now,
    gazeX: stage.gazeX ?? 0,
    gazeY: stage.gazeY ?? 0,
  };

  if (stage.humming != null) {
    // eyes smiling shut, a small closed mouth; notes drift up beside it
    look.emotion = "happy";
    look.mouth = "smile";
  }
  // a feeling moves her body - only while nothing else is moving it
  // a feeling moves her body - unless a scene, an entrance or the summon already
  // does; a gesture's own movement takes over as its pose fades in
  if (stage.emotionAt != null && !stage.activity && !stage.entrance && !summon && faceState !== "dormant") {
    applyMotion(look, emotionMotion(stage.emotion, now - stage.emotionAt), 1 - poseWeight);
  }
  if (stage.activity) {
    Object.assign(look, sceneLook(stage.activity.name, now - stage.activity.at, now));
  }
  const entrance = stage.entrance && entranceActive(stage.entrance.name, now - stage.entrance.at) ? stage.entrance : null;
  if (entrance) {
    Object.assign(look, entranceLook(entrance.name, now - entrance.at));
  }
  if (reaction && poseWeight > 0.5) {
    Object.assign(look, POSES[reaction.name].expression);
  }
  if (reaction && poseWeight > 0 && !entrance && !summon) {
    const t = now - reaction.at;
    // a big reaction: the same pose, its movement much larger, and a hop up into it
    applyMotion(look, poseMotion(reaction.name, t), poseWeight * (reaction.big ? BIG_REACTION_GAIN : 1));
    if (reaction.big && t < BIG_REACTION_HOP_MS) {
      applyMotion(look, { dy: hop(2.4, BIG_REACTION_HOP_PX * (1 - t / BIG_REACTION_HOP_MS))(t), moving: true }, poseWeight);
    }
  }
  // the board takes the matrix: her face goes to the corner, still emoting; hands,
  // props and scenes would draw over the drawing, so only their expressions stay
  const board = stage.board && !summon && !entrance ? stage.board : null;
  if (board) {
    look.layout = "corner";
    look.shiftX = 0;
    look.shiftY = 0;
    look.tilt = 0;
  }
  if (summon) {
    const s = summonLook(summon, now);
    if (s.emotion) look.emotion = s.emotion;
    // the mouth still follows the voice; the visor only covers the eyes
    if (s.steady) look.blinking = false;
  }

  // a theatrical expression (led/theatre.ts) is the whole face, held: only on the
  // plain full face - a pose, scene, entrance, summon or the board owns it otherwise.
  // Never blended away by a micro-expression's flash.
  const theatre = !board && !stage.activity && !entrance && !summon && !(reaction && poseWeight > 0.5) && (look.layout ?? "full") === "full" && faceState !== "dormant" ? theatreFor(stage.emotion) : undefined;
  const theatreT = now - (stage.emotionAt ?? now);
  if (theatre) {
    look.emotion = stage.emotion;
    theatre.look(look, theatreT);
  }

  // a scene's place (keiko's dojo) is behind everything
  if (stage.activity && !board) drawSceneBackdrop(frame, stage.activity.name, now - stage.activity.at);
  // the summon burst is behind her head, so it goes down before the face
  if (summon) drawSummonBurst(frame, summon, now);
  if (board) {
    drawBoard(frame, board.drawing, now - board.at);
    drawFace(frame, look);
    if (stage.muted) drawMuted(frame);
    return;
  }
  drawFace(frame, look);
  if (theatre) theatre.draw(frame, look, theatreT);
  if (stage.humming != null && !stage.activity) drawNotes(frame, now - stage.humming);
  if (stage.activity) drawScene(frame, stage.activity.name, now - stage.activity.at, now);
  if (entrance) drawEntrance(frame, entrance.name, now - entrance.at);
  if (reaction && poseWeight > 0) drawPose(frame, reaction.name, now - reaction.at, poseWeight);
  if (!entrance && !summon) drawGameHand(frame, stage.gameHand ?? null, now);
  if (stage.score && stage.activity?.name === "keiko" && !entrance && !summon) drawScore(frame, stage.score, now);
  if (summon) {
    drawSummon(frame, summon, now);
    // the domain: her whole face (visor, sign, eye, the black hole behind) moves down
    // to make room above it - and her white hair goes in on top
    shiftDown(frame, domainShift(summon, now));
    drawDomainHair(frame, summon, now);
    // a skit line's speech bubble, on top of it all, snapping in on the reveal
    if (summon.bubble && summon.part2 !== null) drawBubble(frame, summon.bubble, now - summon.part2 - REVEAL_MS, summon.hold ?? 3000);
  }
  if (voiceShown(stage.voice) && !entrance && !summon) drawListening(frame, stage.voice, now);
  if (stage.muted) drawMuted(frame);
  drawReadout(frame, now);
}

/** Everything drawn so far moved down by `rows` (the bottom rows drop off). */
function shiftDown(frame: Frame, rows: number): void {
  if (rows <= 0) return;
  const n = rows * COLS;
  frame.value.copyWithin(n, 0, frame.value.length - n);
  frame.ink.copyWithin(n, 0, frame.ink.length - n);
  frame.fade.copyWithin(n, 0, frame.fade.length - n);
  frame.value.fill(0, 0, n);
}
