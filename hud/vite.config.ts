import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// @ts-expect-error type error without @types/node package
import process from "node:process";
// @ts-expect-error type error without @types/node package
import { fileURLToPath } from "node:url";
const host = process.env.TAURI_DEV_HOST;

const REPO_CONFIG = fileURLToPath(new URL("../config", import.meta.url));

/**
 * The HUD imports its data from config/ at the repo root - cues, entrances,
 * capture profiles. fs.allow lets Vite serve those, but Vite only watches its
 * own root, so an edit to one of them used to change nothing until the app was
 * restarted: the running window kept the copy it imported at startup. That is
 * silent and it has already cost a whole capture session, recorded against a
 * profile that had been changed hours earlier. Watch the folder and reload.
 */
function watchRepoConfig() {
  return {
    name: "irene:watch-repo-config",
    configureServer(server: {
      watcher: { add: (p: string) => void; on: (e: string, fn: (f: string) => void) => void };
      ws: { send: (payload: { type: string }) => void };
      config: { logger: { info: (msg: string) => void } };
    }) {
      server.watcher.add(REPO_CONFIG);
      const reload = (file: string): void => {
        if (!file.replace(/\\/g, "/").includes("/config/")) return;
        server.config.logger.info(`config changed (${file.split(/[\\/]/).pop()}) - reloading the HUD`);
        server.ws.send({ type: "full-reload" });
      };
      server.watcher.on("change", reload);
      server.watcher.on("add", reload);
    },
  };
}

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react(), watchRepoConfig()],

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
    // the HUD reads its geometry from the repo-level config/ folder
    fs: {
      allow: [".", "../config"],
    },
  },
}));
