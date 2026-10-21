// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useRef, useState } from "react";

/* Her boot-up: a title sequence, ~11.5 s, drawn on one canvas over her whole
   interface (ui/spectacle.ts - the acts, the camera, the light). Her panel on the
   second screen is held hidden the whole time (Rust holds it on show) and bursts in
   with its own entrance as her name lands: the HUD sends the cue (panel_burst) at
   ACT.panel, or at once if the boot is skipped. Core plays the soundtrack on the
   same clock - the boot's own accents, and on a voice summon the music under them,
   dropping out for the held beat of silence - and waits BOOT_S before the entrance;
   speaking skips it.

     0      COLD     darkness; one point of light; a CRT line opens
     1100   SYSTEMS  six subsystems arrive from behind the screen, one at a time
     3700   SWEEP    the diagnostic sweep; the swarm locks into order (5300)
     5600   COLLAPSE everything implodes; a flash
     6000   SILENCE  held darkness, one heartbeat
     6900   NAME     I R E N E, each typing its word: It's Really Everything, No
                     Exaggeration - held, folded back into IRENE (9300), ADLER (9750)
     10200  PANEL    a bolt leaves for the second screen: the panel's SURGE
     10900  ARRIVAL  a shutter of light opens onto her interface; a last flash (11600)
     12000  done - the entrance plays (and only now her face)

   THE PANEL runs the same clock (its cue at 0) - one system, peaks staggered so the
   eye is pulled back and forth, never two climaxes at once:
     0      its CRT powers on (line, hold, open) - ITS peak while hers is a dark
            cold start; 900 a bolt leaves it for her screen (-> her CORE at 1100)
     820    brackets, cards cascade, readouts scramble, ticker spins up - busy
            but small while her subsystems land one by one
     5450   her second sweep leaves her screen's left edge and crosses the panel
     5600   both go dark together for the silence; one shared heartbeat (6500)
     6900   her NAME: the panel stays quiet underneath - a soft tick per letter
     10200  her bolt arrives: the panel's SURGE - its biggest moment - while her
            name settles and lifts away
     11600  the final flare: both at the same instant                             */

import { ACT, SPECTACLE_MS, drawSpectacle } from "./spectacle";

export const BOOT_MS = SPECTACLE_MS;
/** The panel starts with her: its cue goes at t = 0, both screens on one clock. */
export const PANEL_BURST_MS = 0;
/** The panel's sequence runs the whole boot, beat for beat with hers. */
export const PANEL_BOOT_MS = SPECTACLE_MS;
/** The panel's stages run from its burst (0 = it boots the moment it appears). */
export const PANEL_LAG_MS = 0;
/** When the panel's readouts start counting, after its cue (the screen is open). */
export const BOOT_COUNT_AT_MS = 950;

/** The status line's steps: when each one takes over, and what it says. */
export const BOOT_STEPS: [number, string][] = [
  [0, "COLD START"],
  [ACT.systems, "SUBSYSTEMS"],
  [ACT.sweep, "DIAGNOSTIC"],
  [ACT.silence, "…"],
  [ACT.name, "IDENTITY"],
  [ACT.panel, "PANEL · SECOND SCREEN"],
  [ACT.arrival, "ONLINE"],
];

const NOISE = "█▓▒░<>/\\|#$%&@*+=0123456789ABCDEF";

/**
 * Text that scrambles through random characters, then locks onto its value left
 * to right - from `at` ms after the boot began, over `dur` ms. Outside a boot it
 * is just the text.
 */
export function Scramble({ text, run, at, dur = 700, digits = false }: { text: string; run: number; at: number; dur?: number; digits?: boolean }) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    if (!run) {
      setShown(text);
      return;
    }
    const start = performance.now();
    const chars = [...text];
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - start;
      if (elapsed >= at + dur) {
        setShown(text);
        window.clearInterval(timer);
        return;
      }
      const locked = elapsed < at ? 0 : Math.floor(((elapsed - at) / dur) * chars.length);
      // a clock spins through digits (keeping its separators); text through noise
      const pool = digits ? DIGITS : NOISE;
      setShown(chars.map((c, i) => (i < locked || c === " " || (digits && !/[0-9]/.test(c)) ? c : pool[Math.floor(Math.random() * pool.length)])).join(""));
    }, 45);
    return () => window.clearInterval(timer);
  }, [run, text, at, dur, digits]);
  return <>{shown}</>;
}

const DIGITS = "0123456789";

/** The status line ticking through the boot steps, with a progress rule. */
export function BootStatus({ run, className = "" }: { run: number; className?: string }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!run) return;
    setStep(0);
    const timers = BOOT_STEPS.map(([at], i) => window.setTimeout(() => setStep(i), at));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [run]);
  if (!run) return null;
  const [, label] = BOOT_STEPS[step];
  const pct = Math.round(((step + 1) / BOOT_STEPS.length) * 100);
  return (
    <div className={`boot-status ${className}`} aria-hidden="true">
      <span className="boot-status-tag">BOOT</span>
      <span className="boot-status-step" key={step}>
        <Scramble text={label + (step < BOOT_STEPS.length - 1 ? "…" : "")} run={run * 100 + step} at={0} dur={220} />
      </span>
      <span className="boot-status-pct">{String(pct).padStart(3, "0")}%</span>
      <span className="boot-status-rule">
        <i style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

/** The boot's layers over a window: the far grid, the beam, the stutter line and
 *  the arrival flare. `lag`: this window's delay behind her interface. */
export function BootLayers({ run, lag = 0, panel = false }: { run: number; lag?: number; panel?: boolean }) {
  if (!run) return null;
  return (
    <div className={panel ? "boot-layers is-panel" : "boot-layers"} key={run} style={{ ["--lag" as string]: `${lag}ms` }} aria-hidden="true">
      <div className="boot-grid" />
      <div className="boot-beam" />
      <div className="boot-glitch" />
      <div className="boot-flare" />
      {panel ? (
        <>
          <div className="pn-grid" />
          <div className="pn-ruler is-left" />
          <div className="pn-ruler is-right" />
          <div className="pn-dim is-width">1440</div>
          <div className="pn-dim is-height">2512</div>
          <div className="pn-note n1">SHEET 02 / PANEL &middot; PORTRAIT</div>
          <div className="pn-note n2">GRID 56 &middot; REV A</div>
          <div className="pn-note n3">IRENE / SECOND SCREEN</div>
          <div className="pn-cross">
            <div className="pn-reticle" />
          </div>
          <div className="pn-log">
            <div className="pn-log-line" style={{ ["--i" as string]: 0 }}><span>[0.000] panel.bus</span><b>init</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 1 }}><span>[0.112] fb0 2512x1440 portrait</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 2 }}><span>[0.207] link &rarr; core ws:8765</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 3 }}><span>[0.318] clock sync</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 4 }}><span>[0.401] sensors cpu gpu ram vram</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 5 }}><span>[0.522] feed /weather</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 6 }}><span>[0.611] feed /news</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 7 }}><span>[0.704] feed /markets</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 8 }}><span>[0.812] research index</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 9 }}><span>[0.903] gauges calibrated</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 10 }}><span>[1.017] ticker sync</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 11 }}><span>[1.120] layout 6 cards</span><b>OK</b></div>
            <div className="pn-log-line" style={{ ["--i" as string]: 12 }}><span>[1.204] panel ready</span><b>OK</b></div>
          </div>
          <div className="pn-coldline" />
          <div className="pn-static" />
          <div className="pn-beam" />
          <div className="pn-beam is-in" />
          <div className="pn-final" />
        </>
      ) : null}
    </div>
  );
}

/** The spectacle renders at this fraction of her interface's px (scaled up by CSS):
 *  it is all light and glow, and a full-size canvas cost 20 ms a frame - enough to
 *  make her face loop jank. */
const SPECTACLE_SCALE = 0.5;

/**
 * The spectacle over her interface while she boots: a canvas the size of her
 * interface, drawn every frame from the boot's clock until it is done (or skipped).
 */
export function BootSpectacle({ run }: { run: number }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const node = canvas.current;
    if (!run || !node) return;
    const ctx = node.getContext("2d");
    if (!ctx) return;
    const start = performance.now();
    let frame = 0;
    const draw = (): void => {
      const w = node.clientWidth;
      const h = node.clientHeight;
      const cw = Math.round(w * SPECTACLE_SCALE);
      const ch = Math.round(h * SPECTACLE_SCALE);
      if (node.width !== cw || node.height !== ch) {
        node.width = cw;
        node.height = ch;
      }
      const t = performance.now() - start;
      drawSpectacle(ctx, t, w, h, SPECTACLE_SCALE);
      if (t < SPECTACLE_MS) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      ctx.clearRect(0, 0, node.width, node.height);
    };
  }, [run]);
  if (!run) return null;
  return <canvas className="boot-spectacle" ref={canvas} aria-hidden="true" />;
}
