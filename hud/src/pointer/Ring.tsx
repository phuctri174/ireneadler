// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import "./Ring.css";

/* The ring around the real cursor while his hand steers it (src-tauri/src/pointer.rs
   moves this tiny click-through window with the cursor): it fills as a dwell runs,
   so he sees the click coming, and flashes when a click fires (dwell or pinch);
   it tightens while he pinches, and shows two arrows while he scrolls. */

export function Ring() {
  const [dwell, setDwell] = useState(0);
  const [mode, setMode] = useState("point");
  const [flash, setFlash] = useState(0);
  useEffect(() => {
    document.documentElement.classList.add("is-ring");
    const pending = listen<[number, string]>("irene://ring", (event) => {
      const [progress, next] = event.payload;
      if (next === "fire") {
        setFlash((n) => n + 1);
        setDwell(0);
        return;
      }
      setDwell(progress);
      setMode(next);
    });
    return () => void pending.then((unlisten) => unlisten());
  }, []);
  return (
    <div className={`ring is-${mode}`} style={{ ["--dwell" as string]: dwell.toFixed(3) }}>
      <div className="ring-fill" />
      <div className="ring-edge" />
      <div className="ring-dot" />
      {flash ? <div className="ring-flash" key={flash} /> : null}
      {mode === "scroll" ? <div className="ring-arrows">&#x25B2;<br />&#x25BC;</div> : null}
    </div>
  );
}
