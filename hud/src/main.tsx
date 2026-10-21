// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { Dashboard } from "./dashboard/Dashboard";
import { Ring } from "./pointer/Ring";
import { Warmup } from "./warmup/Warmup";
import { SpectacleStill } from "./ui/SpectacleStill";

// one frontend, three windows: Irene (main), her panel on the second screen, and
// the ring that follows the cursor while his hand drives it
const view = new URLSearchParams(window.location.search).get("view");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{view === "dashboard" ? <Dashboard /> : view === "ring" ? <Ring /> : view === "warmup" ? <Warmup /> : view === "spectacle" && import.meta.env.DEV ? <SpectacleStill /> : <App />}</React.StrictMode>,
);
