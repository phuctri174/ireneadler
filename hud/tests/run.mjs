import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const OUT = ".verify";
const require = createRequire(import.meta.url);

// board templates are found by Vite's import.meta.glob at runtime; here they are
// compiled as one more entry and the glob is swapped for static imports below
const TEMPLATE_DIR = "src/board/templates";
const templateFiles = readdirSync(TEMPLATE_DIR).filter((f) => f.endsWith(".ts") && f !== "index.ts" && !f.startsWith("_"));

// one invocation per entry point: a module with no local imports lands flat in
// OUT; one that imports across folders (led/) keeps its tree under OUT
for (const entry of [
  "src/tracking/gestures.ts",
  "src/tracking/gameMode.ts",
  "src/tracking/zoomFeatures.ts",
  "src/tracking/kamaeFeatures.ts",
  "src/tracking/strikeFeatures.ts",
  "src/tracking/strikeEvent.ts",
  "src/tracking/strikeKind.ts",
  "src/tracking/framing.ts",
  "src/face/reactions.ts",
  "src/tracking/frameLoop.ts",
  "src/led/compose.ts",
  "src/face/micro.ts",
  "src/face/idle.ts",
  templateFiles.map((f) => `${TEMPLATE_DIR}/${f}`),
]) {
  const tsc = spawnSync(
    process.execPath,
    [
      require.resolve("typescript/bin/tsc"),
      ...[entry].flat(),
      "--ignoreConfig",
      "--outDir",
      OUT,
      "--module",
      "esnext",
      "--target",
      "es2020",
      "--moduleResolution",
      "bundler",
      "--resolveJsonModule",
      "--strict",
    ],
    { stdio: "inherit" },
  );
  if (tsc.status !== 0) process.exit(tsc.status ?? 1);
}

const walk = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });

for (const path of walk(OUT)) {
  if (!path.endsWith(".js")) continue;
  const patched = readFileSync(path, "utf8").replace(
    /(from\s+")(\.\.?\/[^"]+?)(")/g,
    (match, head, spec, tail) => (spec.endsWith(".js") || spec.endsWith(".json") ? match : `${head}${spec}.js${tail}`),
  );
  writeFileSync(path, patched);
}

{
  const index = join(OUT, "board", "templates", "index.js");
  const imports = templateFiles.map((f, i) => `import * as __t${i} from "./${f.replace(/\.ts$/, ".js")}";`).join("\n");
  const table = `{ ${templateFiles.map((f, i) => `"./${f}": __t${i}`).join(", ")} }`;
  const source = readFileSync(index, "utf8").replace(/import\.meta\.glob\([^)]*\)/, table);
  writeFileSync(index, `${imports}\n${source}`);
}

// gestures.verify exits the process when done, so it runs last
await import("./frameLoop.verify.mjs");
await import("./led.verify.mjs");
await import("./reactions.verify.mjs");
await import("./cues.verify.mjs");
await import("./idle.verify.mjs");
await import("./entrances.verify.mjs");
await import("./figure.verify.mjs");
await import("./board.verify.mjs");
await import("./gameMode.verify.mjs");
await import("./gameHand.verify.mjs");
// the strike threshold and shiai footwork on made-up bodies
await import("./strikeEvent.verify.mjs");
// shiai's block, on made-up bodies
await import("./strikeKind.verify.mjs");
await import("./framing.verify.mjs");
// the parity tests replay real captured frames (his hand and body - personal, so
// never committed): with no golden file in the checkout they are skipped, saying so
for (const [test, needs] of [["./zoom.verify.mjs", ["zoom.golden.json", "zoom.engine.json"]], ["./kamae.verify.mjs", ["kamae.golden.json"]], ["./strike.verify.mjs", ["strike.golden.json"]]]) {
  const missing = needs.filter((name) => !existsSync(new URL(name, import.meta.url)));
  if (missing.length) console.log(`${test.slice(2, -11)}: skipped - no ${missing.join(", ")} (captured frames stay local; the trainer writes them)`);
  else await import(test);
}
await import("./gestures.verify.mjs");
