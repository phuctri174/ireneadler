// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { CoreSocket, CorpusUpdate } from "../link/coreSocket";
import "./CorpusRecorder.css";

// The voice corpus recorder's display (core/irene/corpus.py drives it). Same
// pattern as the gesture captures: ctrl+alt+shift+r starts it, Irene guides by voice,
// this shows the sentence big enough to read from a metre away, its progress, a
// live mic meter and the take ("take 2 of 3"). He just reads; core hears when he
// is done, checks the take and moves on. While a session runs, space (redo the
// take) and escape (stop) are held as global keys (src-tauri corpus_keys) because
// this window is click-through and never has focus.

interface Props {
  core: CoreSocket;
}

const STATUS: Record<string, string> = {
  take: "",
  ready: "read it when you're ready",
  recording: "listening…",
  checking: "checking…",
  saved: "saved ✓",
  redo: "once more",
  no_mic: "no microphone",
};

const REASON: Record<string, string> = {
  quiet: "too quiet",
  clipped: "clipped - a touch softer",
  short: "cut short",
  words: "heard something different",
};

export function CorpusRecorder({ core }: Props) {
  const [view, setView] = useState<CorpusUpdate | null>(null);
  const [level, setLevel] = useState(0);
  const holding = useRef(false);

  useEffect(() => {
    const stop = core.onMessage((message) => {
      if (message.type === "mic_level") {
        setLevel(message.value);
        return;
      }
      if (message.type !== "corpus") return;
      const { type: _type, ...update } = message;
      const over = update.phase === "stopped" || update.phase === "complete" || update.phase === "no_mic";
      // the global space/escape keys: held for the session, let go the moment it ends
      if (!over && !holding.current) {
        holding.current = true;
        void invoke("corpus_keys", { on: true }).catch((cause: unknown) => console.error("[irene] corpus keys", cause));
      } else if (over && holding.current) {
        holding.current = false;
        void invoke("corpus_keys", { on: false }).catch((cause: unknown) => console.error("[irene] corpus keys", cause));
      }
      setView((previous) => ({ ...(previous ?? {}), ...update }));
      if (over) window.setTimeout(() => setView((v) => (v && v.phase === update.phase ? null : v)), update.phase === "complete" ? 6000 : 2500);
    });
    return () => {
      stop();
      if (holding.current) void invoke("corpus_keys", { on: false }).catch(() => undefined);
    };
  }, [core]);

  if (!view) return null;
  const takes = view.takes ?? 3;
  const status =
    view.phase === "redo"
      ? `${STATUS.redo} - ${REASON[view.reason ?? ""] ?? view.reason}`
      : view.phase === "recording" && view.remainingMs != null
        ? `finishing in ${(view.remainingMs / 1000).toFixed(1)} s…`
        : view.phase === "stopped"
          ? `saved - ${view.done} of ${view.total} sentences done`
          : view.phase === "complete"
            ? `all ${view.total} sentences recorded`
            : (STATUS[view.phase] ?? "");

  return (
    <div className={`corpus is-${view.phase}`} role="status">
      <div className="corpus-head readout">
        <span>VOICE CORPUS</span>
        <span className="corpus-progress">
          {view.index ?? view.done} / {view.total}
        </span>
        {view.split === "test" ? <span className="corpus-split">HELD-OUT TEST</span> : null}
      </div>
      {view.text ? <div className="corpus-text">{view.text}</div> : null}
      <div className="corpus-takes">
        {Array.from({ length: takes }, (_, k) => (
          <span key={k} className={`corpus-take${k + 1 < (view.take ?? 1) ? " is-done" : k + 1 === (view.take ?? 1) ? " is-now" : ""}`} />
        ))}
        <span className="corpus-take-label readout">
          take {view.take ?? 1} of {takes}
        </span>
      </div>
      <div className="corpus-meter">
        <div className="corpus-meter-fill" style={{ width: `${Math.round(Math.min(1, level) * 100)}%` }} />
      </div>
      <div className="corpus-status readout">{status}</div>
      <div className="corpus-keys readout">space: redo the take · esc: stop and save</div>
    </div>
  );
}

export default CorpusRecorder;
