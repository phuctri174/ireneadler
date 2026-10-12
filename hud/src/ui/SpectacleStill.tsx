import { useEffect, useRef } from "react";
import { drawSpectacle } from "./spectacle";

/**
 * Dev only (?view=spectacle&t=8400): one frame of the boot spectacle at t ms, the
 * size of the window - for looking at the acts frame by frame, and screenshots.
 */
export function SpectacleStill() {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const node = canvas.current;
    const ctx = node?.getContext("2d");
    if (!node || !ctx) return;
    const params0 = new URLSearchParams(window.location.search);
    // the live scale (boot.tsx renders at 0.6), or full size for screenshots
    const scale = Number(params0.get("scale") ?? 1);
    const w = window.innerWidth;
    const h = window.innerHeight;
    node.width = Math.round(w * scale);
    node.height = Math.round(h * scale);
    const params = new URLSearchParams(window.location.search);
    if (params.get("lum")) {
      // the average brightness every 20 ms: for proving nothing strobes
      const out: number[] = [];
      for (let t = 0; t < 12000; t += 20) {
        drawSpectacle(ctx, t, w, h, scale);
        const d = ctx.getImageData(0, 0, node.width, node.height).data;
        let sum = 0;
        for (let i = 0; i < d.length; i += 16) sum += (0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) * (d[i + 3] / 255);
        out.push(sum / (d.length / 16) / 255);
      }
      (window as unknown as { __lum: number[] }).__lum = out;
      document.title = "lum done";
      return;
    }
    if (params.get("bench")) {
      // every 50 ms of the sequence: how long a frame takes to draw, per act
      const times: [number, number][] = [];
      for (let t = 0; t < 12000; t += 50) {
        const a = performance.now();
        drawSpectacle(ctx, t, w, h, scale);
        ctx.getImageData(0, 0, 1, 1);
        times.push([t, performance.now() - a]);
      }
      const worst = [...times].sort((x, y) => y[1] - x[1]).slice(0, 8).map(([t, ms]) => `${t}:${ms.toFixed(1)}`);
      const mean = times.reduce((n, [, ms]) => n + ms, 0) / times.length;
      document.title = `mean ${mean.toFixed(1)} ms; worst ${worst.join(" ")}`;
      return;
    }
    const t = Number(params.get("t") ?? 0);
    drawSpectacle(ctx, t, w, h, scale);
  }, []);
  return <canvas ref={canvas} style={{ position: "fixed", inset: 0, width: "100vw", height: "100vh", background: "#03080c" }} />;
}
