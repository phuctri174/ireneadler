import { useEffect, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Vec2 } from "./oneEuro";
import type { GestureMode, GestureState } from "./gestures";
import { onFrame } from "./frameLoop";

const SIZE = 84;
const CENTER = SIZE / 2;
const RADIUS = 30;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const SCROLL_SCALE = 1.12;
const DOT_MAX_SCALE = 1.8;
const FLASH_MS = 260;
const FLASH_SCALE = 1.9;

const MODE_COLOR: Record<GestureMode, string> = {
  idle: "#22e0ff",
  pointing: "#22e0ff",
  dwelling: "#22e0ff",
  scroll: "#5ef2b8",
  zoom: "#b892ff",
  summon: "#ff8fd0",
};

export interface ReticleProps {
  cursor: RefObject<Vec2>;
  gestures: RefObject<GestureState>;
  tracking: boolean;
}

const rootStyle: CSSProperties = {
  position: "fixed",
  left: 0,
  top: 0,
  width: SIZE,
  height: SIZE,
  marginLeft: -CENTER,
  marginTop: -CENTER,
  pointerEvents: "none",
  zIndex: 9999,
  willChange: "transform",
  transform: "translate3d(-9999px, -9999px, 0)",
  transition: "opacity 160ms ease-out",
};

const svgStyle: CSSProperties = {
  position: "absolute",
  inset: 0,
  overflow: "visible",
  willChange: "transform",
  transformOrigin: "center",
};

export function Reticle({ cursor, gestures, tracking }: ReticleProps) {
  const root = useRef<HTMLDivElement | null>(null);
  const svg = useRef<SVGSVGElement | null>(null);
  const ring = useRef<SVGCircleElement | null>(null);
  const arc = useRef<SVGCircleElement | null>(null);
  const flash = useRef<SVGCircleElement | null>(null);
  const dot = useRef<SVGCircleElement | null>(null);

  useEffect(() => {
    let width = window.innerWidth;
    let height = window.innerHeight;
    let lastSelectCount = gestures.current.selectCount;
    let flashStart = -FLASH_MS;
    let lastColor = "";

    const onResize = (): void => {
      width = window.innerWidth;
      height = window.innerHeight;
    };
    window.addEventListener("resize", onResize);

    const draw = (now: number): void => {
      const rootNode = root.current;
      const svgNode = svg.current;
      const ringNode = ring.current;
      const arcNode = arc.current;
      const flashNode = flash.current;
      const dotNode = dot.current;
      if (!rootNode || !svgNode || !ringNode || !arcNode || !flashNode || !dotNode) return;

      const point = cursor.current;
      const state = gestures.current;

      rootNode.style.transform = `translate3d(${(point.x * width).toFixed(1)}px, ${(
        point.y * height
      ).toFixed(1)}px, 0)`;

      const color = MODE_COLOR[state.mode];
      if (color !== lastColor) {
        lastColor = color;
        ringNode.setAttribute("stroke", color);
        arcNode.setAttribute("stroke", color);
        flashNode.setAttribute("stroke", color);
        dotNode.setAttribute("fill", color);
      }

      if (state.selectCount !== lastSelectCount) {
        lastSelectCount = state.selectCount;
        flashStart = now;
      }

      const scale =
        state.mode === "zoom"
          ? Math.min(Math.max(state.zoomFactor, 0.55), 1.7)
          : state.mode === "scroll"
            ? SCROLL_SCALE
            : 1;
      svgNode.style.transform = `scale(${scale.toFixed(3)})`;

      const progress = state.dwellProgress;
      arcNode.style.strokeDashoffset = `${(CIRCUMFERENCE * (1 - progress)).toFixed(2)}`;
      arcNode.style.opacity = progress > 0 ? "1" : "0";
      ringNode.style.opacity = state.mode === "idle" ? "0.55" : "1";

      const flashAge = now - flashStart;
      if (flashAge < FLASH_MS) {
        const t = flashAge / FLASH_MS;
        flashNode.style.opacity = `${(1 - t).toFixed(3)}`;
        flashNode.style.transform = `scale(${(1 + (FLASH_SCALE - 1) * t).toFixed(3)})`;
      } else if (flashNode.style.opacity !== "0") {
        flashNode.style.opacity = "0";
      }

      dotNode.style.transform = `scale(${(1 + (DOT_MAX_SCALE - 1) * progress).toFixed(3)})`;
    };

    const stop = onFrame(draw);

    return () => {
      stop();
      window.removeEventListener("resize", onResize);
    };
  }, [cursor, gestures]);

  return (
    <div ref={root} style={{ ...rootStyle, opacity: tracking ? 1 : 0.18 }}>
      <svg ref={svg} width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} style={svgStyle}>
        <circle
          ref={flash}
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={MODE_COLOR.idle}
          strokeWidth={3}
          opacity={0}
          style={{ transformOrigin: "center", willChange: "transform, opacity" }}
        />
        <circle
          ref={ring}
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={MODE_COLOR.idle}
          strokeWidth={2}
          opacity={0.55}
          style={{ transition: "stroke 120ms linear" }}
        />
        <circle
          ref={arc}
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={MODE_COLOR.idle}
          strokeWidth={4}
          strokeLinecap="round"
          opacity={0}
          style={{
            strokeDasharray: CIRCUMFERENCE,
            strokeDashoffset: CIRCUMFERENCE,
            transform: "rotate(-90deg)",
            transformOrigin: "center",
            willChange: "stroke-dashoffset",
          }}
        />
        <circle
          ref={dot}
          cx={CENTER}
          cy={CENTER}
          r={3}
          fill={MODE_COLOR.idle}
          style={{ transformOrigin: "center", willChange: "transform" }}
        />
      </svg>
    </div>
  );
}

export default Reticle;
