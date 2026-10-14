import { useEffect, useState } from "react";
import "./LectureBadge.css";

/** core/irene/lecture.py LectureCapture.status(): a lecture being captured. */
export interface LectureStatus {
  /** epoch ms when the capture started */
  started: number;
  words: number;
  seconds: number;
  device: string;
  /** chunks waiting for Whisper */
  backlog: number;
}

export function elapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const two = (n: number): string => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(sec)}` : `${two(m)}:${two(sec)}`;
}

/** The indicator while she listens to a lecture: a pulsing dot, how long, how many
 *  words so far. Shown on both screens; it ticks on its own between core's updates. */
export function LectureBadge({ status, compact = false }: { status: LectureStatus; compact?: boolean }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className={compact ? "lecture-badge is-compact" : "lecture-badge"} role="status" aria-live="polite">
      <span className="lecture-dot" aria-hidden="true" />
      <span className="lecture-label">LECTURE</span>
      <span className="lecture-time">{elapsed(now - status.started)}</span>
      <span className="lecture-words">{status.words.toLocaleString()} words</span>
    </div>
  );
}
