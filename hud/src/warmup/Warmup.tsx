// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";

/* The warm-up surface: a full-screen black window on each monitor while the
   displays wake from screens-off (src-tauri: warmup), so the first frame they
   show is SOMETHING - not her boot playing into a dead panel. A dim counter
   shows the seconds since Windows reported the displays ON: the first number he
   can read is the real gap between Windows' word and an image (core.log has
   Windows' side). */

export function Warmup() {
  const [onAt, setOnAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    document.documentElement.style.background = "#000";
    document.body.style.background = "#000";
    document.body.style.margin = "0";
    const pending = listen<{ onAt: number | null }>("irene://warmup", (event) => setOnAt(event.payload.onAt));
    const timer = window.setInterval(() => setNow(Date.now()), 100);
    return () => {
      window.clearInterval(timer);
      void pending.then((unlisten) => unlisten());
    };
  }, []);
  const since = onAt ? Math.max(0, (now - onAt) / 1000).toFixed(1) : null;
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "grid",
        placeItems: "center",
        background: "#000",
        color: "rgba(34, 224, 255, 0.55)",
        font: "600 28px 'Cascadia Mono', Consolas, monospace",
        letterSpacing: "0.12em",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div>{since === null ? "WAKING DISPLAYS" : `${since} s`}</div>
        <div style={{ fontSize: 16, marginTop: 10, color: "rgba(216, 246, 255, 0.35)" }}>since Windows reported the displays on</div>
      </div>
    </div>
  );
}
