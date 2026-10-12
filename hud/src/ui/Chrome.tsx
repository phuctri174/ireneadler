import type { CSSProperties } from "react";
import "./chrome.css";

/** Four corner brackets. Purely decorative; sits inside a positioned parent. */
export function Brackets({ large = false }: { large?: boolean }) {
  return (
    <div className={large ? "brackets is-lg" : "brackets"} aria-hidden="true">
      <span className="tl" />
      <span className="tr" />
      <span className="bl" />
      <span className="br" />
    </div>
  );
}

export interface TickRailProps {
  count?: number;
  /** Every nth tick is drawn long. */
  major?: number;
  vertical?: boolean;
  className?: string;
}

/** Measurement-style tick marks. */
export function TickRail({ count = 24, major = 4, vertical = false, className }: TickRailProps) {
  const classes = ["tickrail", vertical ? "is-vertical" : "", className ?? ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} aria-hidden="true">
      {Array.from({ length: count }, (_unused, index) => (
        <i key={index} className={index % major === 0 ? "major" : undefined} />
      ))}
    </div>
  );
}

/** Low-opacity scanline + grid texture. */
export function Scanlines() {
  return <div className="scanlines" aria-hidden="true" />;
}

/** A thin bright edge with a light travelling along it. */
export function Sweep({ style }: { style?: CSSProperties }) {
  return <div className="sweep" style={style} aria-hidden="true" />;
}
