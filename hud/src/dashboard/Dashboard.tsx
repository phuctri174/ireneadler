// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { emitTo, listen } from "@tauri-apps/api/event";
import { ContentBlocks } from "../ui/ContentBlocks";
import type { PanelContent } from "../ui/content";
import { setLinkOpener } from "../ui/panelChannel";
import "../ui/chrome.css";
import "../ui/boot.css";
import { BOOT_COUNT_AT_MS, BootLayers, BootStatus, PANEL_BOOT_MS, Scramble } from "../ui/boot";
import hudConfig from "../../../config/hud.json";
import { LectureBadge } from "../ui/LectureBadge";
import type { LectureStatus } from "../ui/LectureBadge";
import "./Dashboard.css";

/* Her panel, on the second screen (his MSI, portrait). One large CENTRE - what he
   is looking at - and context rails around it. What she shows (research, sources,
   videos: the old popup's content) takes the centre; otherwise the dashboard cards
   cycle through it by themselves, like a deck advancing. Cycling holds while he
   interacts (mouse, hand, voice) or while she has put something there, and
   resumes after idle. Core's readings and her content arrive through the main
   window (one socket, his HUD's); every item opens in HIS Chrome. */

export const EVENT_DASHBOARD = "irene://dashboard";
export const EVENT_DASHBOARD_READY = "irene://dashboard-ready";
export const EVENT_DASHBOARD_OPEN = "irene://dashboard-open";
export const EVENT_DASHBOARD_FOCUS = "irene://dashboard-focus";
/** Her panel content (or null: closed), relayed from the main window's panelChannel. */
export const EVENT_PANEL_CONTENT = "irene://panel-content";
/** A link clicked in her content: the main window sends it to core (open_link). */
export const EVENT_PANEL_LINK_OPEN = "irene://panel-link-open";
/** Dev hook: "click" the Nth clickable thing in her content. */
export const EVENT_PANEL_LINK_DEV = "irene://panel-link-dev";

export interface NewsItem { title: string; url: string; source: string; at?: string; image?: string; also?: string[] }
export interface Day { day: string; high: number; low: number; rain: number; sky: string }
export interface Weather { title: string; city: string; temp: number; feels: number; humidity: number; wind: number; sky: string; days: Day[]; url: string }
export interface Stock { title: string; symbol: string; price: number; currency: string; change: number; spark: number[]; url: string }
export interface SystemLoad { cpu?: number; gpu?: number; ram?: number; vram?: number; ram_gb?: string; vram_gb?: string }
export interface Timer { label: string; ends: number; total?: number }
/** One of her last researches (core/irene/dashboard.py): a card that brings it back. */
export interface ResearchItem { id: string; title: string; at: string; sources: number; image?: string; kind?: "research" | "lecture"; length?: string }
export interface DashboardState {
  news: NewsItem[];
  weather: Weather | null;
  stocks: Stock[];
  system: SystemLoad;
  timers: Timer[];
  research: ResearchItem[];
  stale: Record<string, boolean>;
  /** a lecture being captured (core/irene/lecture.py), else null */
  lecture?: LectureStatus | null;
  /** the mode she thinks she is in (core's mode guard), or null for none - always shown */
  mode?: string | null;
}


type CardId = "panel" | "news" | "markets" | "weather" | "system" | "timers" | "research";

const EMPTY: DashboardState = { news: [], weather: null, stocks: [], system: {}, timers: [], research: [], stale: {} };
// how long a card holds the centre before the next slides in
// after he touches anything (mouse, hand, voice), how long before cycling resumes
const IDLE_MS = 30000;
// her content holds the centre this long before the deck moves on again
const HER_HOLD_MS = 180000;
// a card's way in and out (Dashboard.css "the deal"): how long the outgoing page
// stays mounted, sliding away under the new one - hers is dealt in hard, the
// cycle's gently (it turns every few seconds)
const TRANSITION_MS: Record<Deal, number> = { deal: 1150, soft: 850 };
/** How a page lands on the stage: dealt hard (her content), or gently (the cycle). */
type Deal = "deal" | "soft";
// the cycle (config/hud.json "panel"): how long each card holds the centre - the
// visual cards (system, weather) longest; looking good over reading time
const DWELL_MS: Partial<Record<CardId, number>> = (hudConfig as { panel?: { dwellMs?: Partial<Record<CardId, number>> } }).panel?.dwellMs ?? {};
const DEFAULT_DWELL_MS = 3000;
// the fixed order he asked for (her content, when there is any, goes first; a
// running timer right after the system card)
const CYCLE_ORDER: CardId[] = ["system", "weather", "timers", "news", "markets", "research"];

// readouts count from zero: during a boot, not before the timeline says so
let countFrom = 0;
/** The boot's self-test: when the panel's cue went (0 = not booting), and how many
 *  readouts have mounted since - each one's turn in the cascade down the layout. */
let selfTestFrom = 0;
let selfTestSeq = 0;
/** The self-test window, from the cue (ui/boot.tsx: ACT 3). */
const SELF_TEST_AT = 3600;
const SELF_TEST_STEP = 70;
/** Dev captures freeze the boot at a moment (window.__bootSeek = ms from the cue). */
function bootNow(now: number): number {
  const seek = import.meta.env.DEV ? (window as unknown as { __bootSeek?: number }).__bootSeek : undefined;
  return seek !== undefined && selfTestFrom ? selfTestFrom + seek : now;
}
// the centre's zoom, as the old panel did it (git b04f80f, ui/Panel.tsx)
const MIN_ZOOM_SCALE = 0.7;
const MAX_ZOOM_SCALE = 2;
const CARD_LABEL: Record<CardId, string> = {
  panel: "Irene", news: "News", markets: "Markets", weather: "Weather", system: "System", timers: "Timers", research: "Research",
};
const SECTION_CARD: Record<string, CardId> = { news: "news", stocks: "markets", weather: "weather" };

// a click is a click: his mouse or his hand (the OS pointer, pointer.rs) - both are
// real clicks here; core.log has the hand's own "hand click at" lines
function open(url: string): void {
  void emitTo("main", EVENT_DASHBOARD_OPEN, { url, how: "click" });
}

// ---- motion helpers -----------------------------------------------------------

/** A number that counts to its new value instead of snapping. */
function useCount(target: number | undefined, ms = 1100, full?: number): number {
  // from zero on every mount: a card coming up (or the boot-up) counts its readouts in
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  const order = useRef(-1);
  useEffect(() => {
    if (target === undefined || Number.isNaN(target)) return;
    // the boot's instrument self-test: up to FULL SCALE, a beat, then back down to
    // the real value - like a car's dashboard powering on - each readout on its turn
    const now0 = performance.now();
    if (selfTestFrom && now0 < selfTestFrom + SELF_TEST_AT + 1200) {
      if (order.current < 0) order.current = selfTestSeq++;
      const top = full ?? Math.max(Math.abs(target) * 1.5, 99);
      const begin = selfTestFrom + SELF_TEST_AT + Math.min(order.current, 16) * SELF_TEST_STEP;
      let frame = 0;
      const tick = (real: number) => {
        const t = bootNow(real) - begin;
        let v = 0;
        if (t <= 0) v = 0;
        else if (t < 420) v = top * (1 - Math.pow(1 - t / 420, 3));
        else if (t < 560) v = top;
        else if (t < 1160) {
          const k = (t - 560) / 600;
          // down with a small undershoot, then settles on the value
          v = target + (top - target) * Math.pow(1 - k, 3) - Math.sin(k * Math.PI) * 0.04 * (top - target) * (k > 0.6 ? 1 : 0);
        } else v = target;
        // never past full scale (a percentage reads 100, not 102)
        v = Math.min(v, Math.max(top, target));
        from.current = v;
        setShown(v);
        if (t < 1160 || bootNow(real) !== real) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
      return () => cancelAnimationFrame(frame);
    }
    const start = Math.max(performance.now(), countFrom);
    const a = from.current;
    let frame = 0;
    const step = (now: number) => {
      const k = Math.max(0, Math.min(1, (now - start) / ms));
      const eased = 1 - Math.pow(1 - k, 3);
      const v = a + (target - a) * eased;
      from.current = v;
      setShown(v);
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, ms, full]);
  return shown;
}

function Count({ value, digits = 0, prefix = "", suffix = "" }: { value: number | undefined; digits?: number; prefix?: string; suffix?: string }) {
  const v = useCount(value, 1100, suffix === "%" ? 100 : undefined);
  if (value === undefined) return <span className="dk-num">--</span>;
  return (
    <span className="dk-num">
      {prefix}
      {v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}
      {suffix}
    </span>
  );
}

/** A line that draws itself (stroke-dash from 1 to 0), redrawn when its data changes. */
function Graph({ points, up, area = true, className = "" }: { points: number[]; up: boolean; area?: boolean; className?: string }) {
  if (points.length < 2) return <svg className={`dk-graph ${className}`} />;
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const span = hi - lo || 1;
  const xy = points.map((p, i) => [(i / (points.length - 1)) * 100, 38 - ((p - lo) / span) * 34]);
  const line = xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const key = `${points.length}-${points[0]}-${points[points.length - 1]}`;
  return (
    <svg key={key} className={`dk-graph ${up ? "is-up" : "is-down"} ${className}`} viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
      {area ? <polygon className="dk-graph-area" points={`0,40 ${line} 100,40`} /> : null}
      <polyline className="dk-graph-line" points={line} />
    </svg>
  );
}

function Brackets() {
  return (
    <>
      <i className="dk-br dk-br-tl" />
      <i className="dk-br dk-br-tr" />
      <i className="dk-br dk-br-bl" />
      <i className="dk-br dk-br-br" />
    </>
  );
}

/** "2h ago · 14:05" - how fresh a story is, at a glance. */
function ago(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const mins = Math.max(0, Math.round((Date.now() - when.getTime()) / 60000));
  const rel = mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
  return `${rel} · ${when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

/** How long a card holds the centre (config/hud.json panel.dwellMs). */
function dwellFor(id: CardId): number {
  return DWELL_MS[id] ?? DEFAULT_DWELL_MS;
}

function money(value: number, currency: string): string {
  const digits = value >= 1000 ? 0 : 2;
  const text = value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return currency === "USD" ? `$${text}` : `${text} ${currency}`;
}

function remaining(ends: number, now: number): string {
  const left = Math.max(0, Math.round(ends - now / 1000));
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  const s = left % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function useNow(every = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(timer);
  }, [every]);
  return now;
}

// ---- the cards: each in a big (centre) and a mini (rail) form -----------------------

type Size = "big" | "mini";

function NewsCard({ s, size }: { s: DashboardState; size: Size }) {
  const items = size === "big" ? s.news.slice(0, 4) : s.news.slice(0, 3);
  if (!items.length) return <div className="dk-empty">Waiting for headlines&hellip;</div>;
  return (
    <ol className={`dk-news is-${size}`}>
      {items.map((n, i) => (
        <li key={n.url} style={{ ["--i" as string]: i }}>
          <button className="dk-story" data-url={n.url} onClick={() => open(n.url)}>
            <span className="dk-thumb">
              {n.image ? <img src={n.image} alt="" /> : <span className="dk-thumb-none">{n.source}</span>}
              <span className="dk-index">{String(i + 1).padStart(2, "0")}</span>
            </span>
            <span className="dk-news-text">
              <b>{n.title}</b>
              <span className="dk-label">
                {n.source}
                {n.also?.length ? ` +${n.also.length} more` : ""}
                {n.at ? ` · ${ago(n.at)}` : ""}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function MarketsCard({ s, size }: { s: DashboardState; size: Size }) {
  if (!s.stocks.length) return <div className="dk-empty">Waiting for quotes&hellip;</div>;
  return (
    <div className={`dk-markets is-${size}`}>
      {s.stocks.map((q, i) => (
        <button className="dk-row dk-quote" key={q.symbol} data-url={q.url} onClick={() => open(q.url)} style={{ ["--i" as string]: i }}>
          <span className="dk-index">{String(i + 1).padStart(2, "0")}</span>
          <span className="dk-quote-name">
            <b>{size === "big" ? q.title : q.symbol}</b>
            {size === "big" ? <span className="dk-label">{q.symbol}</span> : null}
          </span>
          <Graph points={q.spark} up={q.change >= 0} area={size === "big"} />
          <span className="dk-quote-price">
            <Count value={q.price} digits={q.price >= 1000 ? 0 : 2} prefix={q.currency === "USD" ? "$" : ""} />
          </span>
          <span className={q.change >= 0 ? "dk-change is-up" : "dk-change is-down"}>
            {q.change >= 0 ? "▲" : "▼"} <Count value={Math.abs(q.change)} digits={2} suffix="%" />
          </span>
        </button>
      ))}
    </div>
  );
}

/** An animated sky for Open-Meteo's words: sun, cloud, rain, storm, fog. */
function Sky({ sky, className = "" }: { sky: string; className?: string }) {
  const t = sky.toLowerCase();
  const sun = /clear|mostly clear|partly/.test(t);
  const cloud = !/^clear$|mostly clear/.test(t);
  const rain = /rain|drizzle|shower/.test(t);
  const storm = /thunder/.test(t);
  const fog = /fog/.test(t);
  return (
    <svg className={`dk-sky ${className}`} viewBox="0 0 100 100" aria-hidden="true">
      {sun ? (
        <g className="dk-sky-sun" transform={cloud ? "translate(-14 -12)" : undefined}>
          <circle cx="50" cy="50" r="15" />
          <g className="dk-sky-rays">
            {Array.from({ length: 8 }, (_, k) => (
              <line key={k} x1="50" y1="24" x2="50" y2="16" transform={`rotate(${k * 45} 50 50)`} />
            ))}
          </g>
        </g>
      ) : null}
      {cloud ? (
        <path
          className="dk-sky-cloud"
          d="M28 70 a14 14 0 0 1 2-27.8 a18 18 0 0 1 34-5.2 a13 13 0 0 1 13 12.6 a10.4 10.4 0 0 1 -1 20.4 z"
        />
      ) : null}
      {rain
        ? [34, 46, 58, 70].map((x, k) => <line key={x} className="dk-sky-drop" x1={x} y1="76" x2={x - 3} y2="86" style={{ animationDelay: `${k * 180}ms` }} />)
        : null}
      {storm ? <path className="dk-sky-bolt" d="M52 72 l-8 14 h7 l-4 11 l12 -16 h-7 l5 -9 z" /> : null}
      {fog ? [74, 82, 90].map((y, k) => <line key={y} className="dk-sky-fog" x1="20" y1={y} x2="80" y2={y} style={{ animationDelay: `${k * 400}ms` }} />) : null}
    </svg>
  );
}

function WeatherCard({ s, size }: { s: DashboardState; size: Size }) {
  const w = s.weather;
  if (!w) return <div className="dk-empty">Waiting for Open-Meteo&hellip;</div>;
  return (
    <button className={`dk-weather is-${size}`} data-url={w.url} onClick={() => open(w.url)}>
      <div className="dk-weather-now">
        <Sky sky={w.sky} className={size === "big" ? "is-big" : ""} />
        <span className="dk-temp">
          <Count value={w.temp} />
          &deg;
        </span>
        <span className="dk-weather-sky">
          <b>{w.sky}</b>
          <span className="dk-label">
            feels {w.feels}&deg; &middot; hum {w.humidity}% &middot; wind {Math.round(w.wind)} km/h
          </span>
        </span>
      </div>
      {size === "big" ? (
        <>
          <Graph points={w.days.map((d) => d.high)} up area className="dk-weather-graph" />
          <div className="dk-days">
            {w.days.map((d, i) => (
              <div className="dk-day" key={d.day} style={{ ["--i" as string]: i }}>
                <span className="dk-label">{d.day}</span>
                <Sky sky={d.sky} className="is-day" />
                <b>
                  {d.high}&deg; <span className="dk-dim">/ {d.low}&deg;</span>
                </b>
                <span className="dk-dim">{d.sky}</span>
                <span className="dk-rain">
                  <i style={{ width: `${d.rain}%` }} /> {d.rain}%
                </span>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </button>
  );
}

/** A ring gauge: the arc sweeps to its value and keeps moving with it. */
function Gauge({ value, label, detail }: { value?: number; label: string; detail?: string }) {
  const v = Math.min(100, Math.max(0, value ?? 0));
  const level = v >= 90 ? "is-hot" : v >= 70 ? "is-warm" : "";
  return (
    <div className={`dk-gauge ${level}`}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle className="dk-gauge-track" cx="50" cy="50" r="42" pathLength={100} />
        <circle className="dk-gauge-ticks" cx="50" cy="50" r="47" pathLength={100} />
        <circle className="dk-gauge-arc" cx="50" cy="50" r="42" pathLength={100} style={{ strokeDashoffset: 100 - v }} />
      </svg>
      <div className="dk-gauge-centre">
        <span className="dk-gauge-value">
          <Count value={value} />
          <small>%</small>
        </span>
        <span className="dk-label">{label}</span>
        {detail ? <span className="dk-gauge-detail">{detail}</span> : null}
      </div>
    </div>
  );
}

function SystemCard({ s, size, history }: { s: DashboardState; size: Size; history: Record<string, number[]> }) {
  const sys = s.system;
  const rows: [string, number | undefined, string | undefined][] = [
    ["CPU", sys.cpu, undefined],
    ["GPU", sys.gpu, undefined],
    ["RAM", sys.ram, sys.ram_gb ? `${sys.ram_gb} GB` : undefined],
    ["VRAM", sys.vram, sys.vram_gb ? `${sys.vram_gb} GB` : undefined],
  ];
  return (
    <div className={`dk-system is-${size}`}>
      {rows.map(([name, v, detail], i) => (
        <div className="dk-meter" key={name} style={{ ["--i" as string]: i }}>
          <Gauge value={v} label={name} detail={size === "big" ? detail : undefined} />
          {size === "big" ? <Graph points={history[name] ?? []} up area className="dk-meter-graph" /> : null}
        </div>
      ))}
    </div>
  );
}

function TimersCard({ s, size, now }: { s: DashboardState; size: Size; now: number }) {
  if (!s.timers.length) {
    return (
      <div className={`dk-clock is-${size}`}>
        <span className="dk-label">no timers running</span>
        <b>{new Date(now).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b>
      </div>
    );
  }
  return (
    <div className={`dk-timers is-${size}`}>
      {s.timers.map((t, i) => {
        const left = Math.max(0, t.ends - now / 1000);
        const done = t.total ? Math.min(1, 1 - left / t.total) : 0;
        return (
          <div className="dk-timer" key={`${t.label}-${i}`}>
            <svg className="dk-timer-ring" viewBox="0 0 100 100" aria-hidden="true">
              <circle className="dk-gauge-track" cx="50" cy="50" r="44" pathLength={100} />
              <circle className="dk-gauge-arc" cx="50" cy="50" r="44" pathLength={100} style={{ strokeDashoffset: 100 * done }} />
            </svg>
            <div className="dk-timer-centre">
              <b>{remaining(t.ends, now)}</b>
              <span className="dk-label">{t.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** A research with no picture of its own gets one drawn from its id: rings and a
 *  scan line in her palette, its topic's initial - never two alike, never blank. */
function GenThumb({ seed, title }: { seed: string; title: string }) {
  let h = 2166136261;
  for (const ch of seed + title) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  const rnd = (k: number) => ((h >>> (k * 3)) & 1023) / 1023;
  const initial = (title.match(/[A-Za-z0-9]/)?.[0] ?? "?").toUpperCase();
  return (
    <svg className="dk-gen" viewBox="0 0 160 90" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect width="160" height="90" fill="rgba(34,224,255,0.06)" />
      {[0, 1, 2, 3].map((k) => (
        <circle key={k} cx={30 + rnd(k) * 100} cy={20 + rnd(k + 4) * 50} r={10 + rnd(k + 8) * 30} fill="none" stroke="#22e0ff" strokeOpacity={0.15 + rnd(k + 2) * 0.35} />
      ))}
      <line x1="0" x2="160" y1={20 + rnd(5) * 50} y2={20 + rnd(6) * 50} stroke="#5ef2b8" strokeOpacity="0.4" />
      <text x="80" y="58" textAnchor="middle" fontFamily="Cascadia Mono, Consolas, monospace" fontSize="36" fontWeight="700" fill="#eaffff" fillOpacity="0.85">
        {initial}
      </text>
    </svg>
  );
}

/** Her last researches: each card brings that research back to the centre stage. */
function ResearchCard({ s, size }: { s: DashboardState; size: Size }) {
  if (!s.research.length) return <div className="dk-empty">No research yet.</div>;
  return (
    <ol className={`dk-research is-${size}`}>
      {(size === "mini" ? s.research.slice(0, 3) : s.research).map((r, i) => (
        <li key={r.id} style={{ ["--i" as string]: i }}>
          <button
            className="dk-research-card"
            data-research={r.id}
            onClick={(event) => {
              event.stopPropagation();
              void emitTo("main", "irene://research-recall", { id: r.id });
            }}
          >
            <span className="dk-thumb">
              {r.image ? <img src={r.image} alt="" /> : <GenThumb seed={r.id} title={r.title} />}
              <span className="dk-index">{String(i + 1).padStart(2, "0")}</span>
            </span>
            <span className="dk-research-text">
              <b>{r.title}</b>
              <span className="dk-label">
                {r.kind === "lecture" ? (
                  <>
                    <span className="dk-tag-lecture">lecture note</span> &middot; {r.at.slice(0, 10)} &middot; {r.length}
                  </>
                ) : (
                  <>
                    {r.at.slice(11) || r.at} &middot; {r.at.slice(0, 10)} &middot; {r.sources} source{r.sources === 1 ? "" : "s"}
                  </>
                )}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function PanelCard({ content }: { content: PanelContent | null }) {
  if (!content) return <div className="dk-empty">Nothing from Irene yet.</div>;
  return (
    <div className="dk-her">
      <div className="dk-her-title">{content.title}</div>
      {content.subtitle ? <div className="dk-label dk-her-sub">{content.subtitle}</div> : null}
      <div className="dk-her-body">
        <ContentBlocks blocks={content.blocks} />
      </div>
    </div>
  );
}

// ---- the panel ---------------------------------------------------------------------

export function Dashboard() {
  const root = useRef<HTMLDivElement | null>(null);
  // the panel fills its monitor: laid out at its design size (config/hud.json
  // panelDesign) and scaled uniformly; a different aspect goes to the layout
  useEffect(() => {
    const { width, height } = hudConfig.panelDesign;
    const apply = (): void => {
      const style = root.current?.style;
      if (!style) return;
      const scale = Math.min(window.innerWidth / width, window.innerHeight / height);
      style.setProperty("--dk-scale", scale.toFixed(4));
      style.setProperty("--dk-w", `${(window.innerWidth / scale).toFixed(1)}px`);
      style.setProperty("--dk-h", `${(window.innerHeight / scale).toFixed(1)}px`);
    };
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, []);
  const [state, setState] = useState<DashboardState>(EMPTY);
  const stateRef = useRef<DashboardState>(EMPTY);
  const [her, setHer] = useState<PanelContent | null>(null);
  const now = useNow();
  const history = useRef<Record<string, number[]>>({});
  const stage = useRef<HTMLDivElement | null>(null);

  // the deck: which card has the centre, which one is leaving, and the hold
  const [centre, setCentre] = useState<CardId>("system");
  // the outgoing page keeps what it showed (her previous content, when hers replaces hers)
  const [leaving, setLeaving] = useState<{ id: CardId; key: number; her: PanelContent | null; deal: Deal } | null>(null);
  const [deal, setDeal] = useState<Deal>("soft");
  const herRef = useRef<PanelContent | null>(null);
  const [turn, setTurn] = useState(0);
  const [holdUntil, setHoldUntil] = useState(0);
  const [holdWhy, setHoldWhy] = useState("");
  // the boot-up (see its effect): running, and which one - the cards remount once
  // per show (never again when it ends)
  const [booting, setBooting] = useState(0);
  const [bootSeq, setBootSeq] = useState(0);
  // the centre's zoom: true magnification (see the effect below); the readout
  const [zoomShown, setZoomShown] = useState(1);
  const scroller = useRef<HTMLDivElement | null>(null);
  const layer = useRef<HTMLDivElement | null>(null);
  const inner = useRef<HTMLDivElement | null>(null);
  const centreRef = useRef(centre);
  centreRef.current = centre;

  const cards = useMemo<CardId[]>(() => {
    const list: CardId[] = her ? ["panel"] : [];
    for (const id of CYCLE_ORDER) {
      if (id === "timers" && !state.timers.length) continue;
      if (id === "research" && !state.research.length) continue;
      list.push(id);
    }
    return list;
  }, [her, state.timers.length, state.research.length]);

  const show = useCallback((id: CardId, how: Deal = "soft", force = false, outgoing?: PanelContent | null) => {
    if (id === centreRef.current && !force) return;
    setLeaving({ id: centreRef.current, key: Date.now(), her: outgoing === undefined ? herRef.current : outgoing, deal: how });
    setCentre(id);
    setDeal(how);
    setTurn((t) => t + 1);
  }, []);

  // (a mouse move holds too: only a change of a second or more re-renders)
  const holdRef = useRef(0);
  const hold = useCallback((ms: number, why: string) => {
    const until = Date.now() + ms;
    if (until - holdRef.current < 1000) {
      setHoldWhy(why);
      return;
    }
    holdRef.current = until;
    setHoldUntil(until);
    setHoldWhy(why);
  }, []);

  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => setLeaving(null), TRANSITION_MS[leaving.deal]);
    return () => window.clearTimeout(timer);
  }, [leaving]);

  // the deck advances itself after each card's dwell, unless something holds it
  const dwell = dwellFor(centre);
  useEffect(() => {
    const wait = Math.max(dwell, holdUntil - Date.now());
    const timer = window.setTimeout(() => {
      if (Date.now() < holdUntil) return;
      const at = cards.indexOf(centreRef.current);
      show(cards[(at + 1) % cards.length]);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [cards, holdUntil, show, turn, dwell]);

  // readings and her content, relayed by the main window
  useEffect(() => {
    document.documentElement.classList.add("is-dashboard");
    setLinkOpener((url) => void emitTo("main", EVENT_PANEL_LINK_OPEN, { url, how: "click" }));
    const stops = [
      listen<DashboardState>(EVENT_DASHBOARD, (event) => {
        // a partial update (load, timers) merges into what is up
        const next = { ...EMPTY, ...stateRef.current, ...event.payload };
        stateRef.current = next;
        for (const [name, key] of [["CPU", "cpu"], ["GPU", "gpu"], ["RAM", "ram"], ["VRAM", "vram"]] as const) {
          const v = next.system[key];
          if (typeof v === "number") history.current[name] = [...(history.current[name] ?? []), v].slice(-60);
        }
        setState(next);
      }),
      listen<PanelContent | null>(EVENT_PANEL_CONTENT, (event) => {
        // what she put there before, for the page sliding away under the new one
        const before = herRef.current;
        herRef.current = event.payload;
        setHer(event.payload);
        if (event.payload) {
          // dealt onto the desk - even over her own last page
          show("panel", "deal", true, before);
          hold(HER_HOLD_MS, "Irene's content");
        } else if (centreRef.current === "panel") {
          show("news", "soft", false, before);
          holdRef.current = 0;
          setHoldUntil(0);
        }
      }),
      listen<{ section: string; number: number }>(EVENT_DASHBOARD_FOCUS, (event) => {
        const id = SECTION_CARD[event.payload.section];
        if (!id) return;
        show(id, "deal");
        hold(IDLE_MS, "voice");
        window.setTimeout(() => {
          const rows = document.querySelectorAll(`.dk-stage-card.is-in [data-url]`);
          const n = event.payload.number;
          const row = rows[n > 0 ? n - 1 : rows.length + n];
          row?.classList.add("is-picked");
          window.setTimeout(() => row?.classList.remove("is-picked"), 1200);
        }, TRANSITION_MS.soft);
      }),
      listen<string>("irene://dashboard-click-dev", (event) => {
        const [section, n] = String(event.payload).split(":");
        const selector = section === "research" ? ".dk-research [data-research]" : `.dk-${section === "markets" ? "markets" : "news"} [data-url]`;
        const rows = document.querySelectorAll<HTMLElement>(selector);
        const row = rows[Math.max(0, Number(n || 1) - 1)];
        console.log(`[irene] dev click ${section} ${n}: ${rows.length} rows, ${row ? "clicked" : "none"}`);
        row?.click();
      }),
      listen("irene://geometry-dev", () => {
        // the dev geometry hook: this layout's box against the window
        const box = root.current?.getBoundingClientRect();
        const scale = root.current?.style.getPropertyValue("--dk-scale");
        const text = box
          ? `panel geometry: layout ${box.width.toFixed(0)}x${box.height.toFixed(0)} at (${box.left.toFixed(0)}, ${box.top.toFixed(0)}) scale ${scale} in ${window.innerWidth}x${window.innerHeight}`
          : "panel geometry: no layout";
        void emitTo("main", "irene://geometry-dev-reply", text);
      }),
      listen<number>(EVENT_PANEL_LINK_DEV, (event) => {
        const clickable = document.querySelectorAll<HTMLElement>(".dk-her .cb-link, .dk-her .cb-shot.is-link, .dk-her .cb-video, .dk-her .cb-story, .dk-her .cb-price, .dk-her .cb-weather.is-link");
        const target = clickable[Number(event.payload ?? 0)];
        console.log(`[irene] panel_link ${event.payload}: ${clickable.length} clickable, ${target ? "clicked" : "none"}`);
        target?.click();
      }),
    ];
    // the main window may not be listening yet when this one loads (both start
    // together): ask again until the full readings are here - live, the panel sat on
    // "Waiting..." while the load (sent every 3 s) kept arriving
    void emitTo("main", EVENT_DASHBOARD_READY, null);
    const asking = window.setInterval(() => {
      const have = stateRef.current;
      if (have.weather || have.news.length || have.stocks.length) window.clearInterval(asking);
      else void emitTo("main", EVENT_DASHBOARD_READY, null);
    }, 2000);
    return () => {
      window.clearInterval(asking);
      setLinkOpener(null);
      for (const pending of stops) void pending.then((unlisten) => unlisten());
    };
  }, [show, hold]);

  // The zoom the old panel had, reused (git b04f80f, ui/Panel.tsx): the content is
  // laid out once at its natural size and magnified with transform: scale() - no
  // reflow - inside a layer sized to the scaled box, so the scroller scrolls it;
  // the point under the pointer stays put. His five-finger gesture (the main
  // window relays its factor, relative to where it began) and Ctrl+scroll.
  // Back to 1 when another card takes the centre.
  //
  // ONLY her research content in the centre zooms (centre === "panel"): system,
  // weather, news, markets, timers and the research history never scale - they
  // stay fixed in place, whatever his hand does. Ctrl+scroll over them is
  // swallowed too, so the webview's own page zoom can't scale them either.
  useEffect(() => {
    const body = scroller.current;
    const layerNode = layer.current;
    const content = inner.current;
    if (!body || !layerNode || !content) return;
    // the dashboard cards fill the stage at 1x; her content runs as long as it is
    const fill = centre !== "panel";
    const zoomable = centre === "panel";
    let committedScale = 1;
    let liveFactor = 1;
    let appliedScale = 0;
    let zooming = false;
    let anchorX = 0;
    let anchorY = 0;
    let naturalWidth = 0;
    let naturalHeight = 0;
    let pointer: { x: number; y: number } | null = null;

    const clampScale = (v: number) => Math.min(MAX_ZOOM_SCALE, Math.max(MIN_ZOOM_SCALE, v));

    const measure = (): void => {
      naturalWidth = body.clientWidth;
      content.style.width = `${naturalWidth}px`;
      content.style.height = fill ? `${body.clientHeight}px` : "auto";
      naturalHeight = content.offsetHeight;
      const scale = appliedScale || 1;
      layerNode.style.width = `${(naturalWidth * scale).toFixed(1)}px`;
      layerNode.style.height = `${(naturalHeight * scale).toFixed(1)}px`;
    };

    const applyScale = (scale: number): void => {
      if (scale === appliedScale) return;
      const previous = appliedScale === 0 ? 1 : appliedScale;
      const keptLeft = anchorX * previous - body.scrollLeft;
      const keptTop = anchorY * previous - body.scrollTop;
      content.style.transform = `scale(${scale.toFixed(4)})`;
      layerNode.style.width = `${(naturalWidth * scale).toFixed(1)}px`;
      layerNode.style.height = `${(naturalHeight * scale).toFixed(1)}px`;
      body.scrollLeft = anchorX * scale - keptLeft;
      body.scrollTop = anchorY * scale - keptTop;
      appliedScale = scale;
      setZoomShown(Math.round(scale * 100) / 100);
    };

    // the content point under (x, y) - in this window's px - is what stays put
    const captureAnchor = (x: number, y: number): void => {
      const rect = body.getBoundingClientRect();
      const scale = appliedScale === 0 ? 1 : appliedScale;
      // window px -> the scroller's own px (the whole panel is scaled to its screen)
      const fit = rect.width / (body.offsetWidth || rect.width || 1);
      const localX = Math.min(rect.width, Math.max(0, x - rect.left)) / fit;
      const localY = Math.min(rect.height, Math.max(0, y - rect.top)) / fit;
      anchorX = (body.scrollLeft + localX) / scale;
      anchorY = (body.scrollTop + localY) / scale;
    };
    const anchorAtPointer = (): void => {
      const rect = body.getBoundingClientRect();
      const inside = pointer && pointer.x >= rect.left && pointer.x <= rect.right && pointer.y >= rect.top && pointer.y <= rect.bottom;
      if (inside && pointer) captureAnchor(pointer.x, pointer.y);
      else captureAnchor(rect.left + rect.width / 2, rect.top + rect.height / 2);
    };

    measure();
    anchorAtPointer();
    applyScale(1);
    // pictures load, her content grows: the natural size is read again
    const grows = new ResizeObserver(() => measure());
    grows.observe(content);
    grows.observe(body);

    const onMove = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY };
    };
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      if (!zoomable) return;
      captureAnchor(event.clientX, event.clientY);
      committedScale = clampScale(committedScale * Math.exp(-event.deltaY * 0.0015));
      applyScale(clampScale(committedScale * liveFactor));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("wheel", onWheel, { passive: false });
    const pending = listen<{ active: boolean; factor: number }>("irene://panel-zoom", (event) => {
      if (!zoomable) return;
      if (event.payload.active) {
        if (!zooming) anchorAtPointer();
        zooming = true;
        liveFactor = event.payload.factor;
        hold(IDLE_MS, "your hand");
      } else if (zooming) {
        committedScale = clampScale(committedScale * liveFactor);
        liveFactor = 1;
        zooming = false;
      }
      applyScale(clampScale(committedScale * liveFactor));
    });
    return () => {
      grows.disconnect();
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("wheel", onWheel);
      void pending.then((unlisten) => unlisten());
      setZoomShown(1);
    };
  }, [centre, turn, hold, bootSeq]);

  // the panel's entrance: it is held off the screen while her boot plays and bursts
  // in on the cue as her name lands (irene://panel-burst, from Rust) - the frame
  // slams in from depth and settles, the labels type, the cards cascade (remounted,
  // so their readouts count from zero); skipped when he speaks over it
  const showRef = useRef(show);
  showRef.current = show;
  const holdRef2 = useRef(hold);
  holdRef2.current = hold;
  const centreRefForBoot = useRef({ her: false });
  centreRefForBoot.current.her = her !== null;
  useEffect(() => {
    let timer = 0;
    const shown = listen("irene://panel-burst", () => {
      // the readouts count once the frame has landed
      countFrom = performance.now() + BOOT_COUNT_AT_MS;
      selfTestFrom = performance.now();
      selfTestSeq = 0;
      // the boot owns the centre: it starts on the first card (system) and the
      // cycle waits until the boot is over
      if (!centreRefForBoot.current.her) showRef.current("system");
      holdRef2.current(PANEL_BOOT_MS, "boot");
      setBooting((n) => n + 1);
      setBootSeq((n) => n + 1);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setBooting(0), PANEL_BOOT_MS);
    });
    const skipped = listen("irene://boot-skip", () => {
      window.clearTimeout(timer);
      setBooting(0);
    });
    return () => {
      window.clearTimeout(timer);
      void shown.then((unlisten) => unlisten());
      void skipped.then((unlisten) => unlisten());
    };
  }, []);

  // the mouse: any touch holds the deck
  useEffect(() => {
    const touch = () => hold(IDLE_MS, "you");
    window.addEventListener("pointermove", touch);
    window.addEventListener("wheel", touch);
    window.addEventListener("pointerdown", touch);
    return () => {
      window.removeEventListener("pointermove", touch);
      window.removeEventListener("wheel", touch);
      window.removeEventListener("pointerdown", touch);
    };
  }, [hold]);


  const held = now < holdUntil;
  const body = (id: CardId, size: Size): ReactNode => {
    switch (id) {
      case "panel":
        return <PanelCard content={her} />;
      case "news":
        return <NewsCard s={state} size={size} />;
      case "markets":
        return <MarketsCard s={state} size={size} />;
      case "weather":
        return <WeatherCard s={state} size={size} />;
      case "system":
        return <SystemCard s={state} size={size} history={history.current} />;
      case "timers":
        return <TimersCard s={state} size={size} now={now} />;
      case "research":
        return <ResearchCard s={state} size={size} />;
    }
  };
  const stale = (id: CardId): boolean => Boolean(state.stale[id === "markets" ? "stocks" : id]);
  const rail = (ids: CardId[]) =>
    ids.map((id) => (
      <section
        key={id}
        className={`dk-mini${centre === id ? " is-centre" : ""}`}
        data-card={id}
        onClick={(event) => {
          if ((event.target as Element).closest("[data-url]")) return;
          show(id);
          hold(IDLE_MS, "you");
        }}
      >
        <Brackets />
        <header className="dk-mini-head">
          <span className="dk-label">{CARD_LABEL[id]}</span>
          {centre === id ? <span className="dk-live">on centre</span> : stale(id) ? <span className="dk-stale">last reading</span> : <span className="dk-pulse" />}
        </header>
        <div className="dk-mini-body">{body(id, "mini")}</div>
      </section>
    ));
  const date = new Date(now);
  const ticker = state.stocks.length ? [...state.stocks, ...state.stocks] : [];

  return (
    <div className={booting ? "dk is-booting" : "dk"} ref={root}>
      <BootLayers run={booting} panel />
      <BootStatus run={booting} />
      <div className={state.lecture ? "dk-frame has-lecture" : "dk-frame"} key={`frame-${bootSeq}`}>
        <Brackets />
        <header className="dk-top">
          <div className="dk-top-side">
            <span className="dk-label">Local time</span>
            <b className="dk-clockface">
              <Scramble text={date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} run={booting} at={3500} dur={800} digits />
            </b>
            <span className="dk-label">{date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</span>
            {state.timers[0] ? (
              <span className="dk-head-timer">
                {state.timers[0].label} <b>{remaining(state.timers[0].ends, now)}</b>
              </span>
            ) : null}
          </div>
          <div className="dk-badge">
            <span className="dk-badge-wing" aria-hidden="true" />
            <div className="dk-badge-plate">
              <span className="dk-badge-gem" aria-hidden="true" />
              <span className="dk-badge-name">
                <Scramble text="IRENE ADLER" run={booting} at={10300} dur={700} />
              </span>
              <span className="dk-badge-gem" aria-hidden="true" />
            </div>
            <span className="dk-badge-wing is-right" aria-hidden="true" />
            <div className={state.mode ? "dk-badge-sub dk-mode is-on" : "dk-badge-sub dk-mode"}>Mode: {state.mode ?? "none"}</div>
          </div>
          <div className="dk-top-side is-right">
            <span className="dk-label">Load</span>
            <b className="dk-clockface">
              <Count value={state.system.cpu} suffix="%" />
            </b>
            <span className="dk-label">
              gpu <Count value={state.system.gpu} suffix="%" />
            </span>
          </div>
        </header>

        {state.lecture ? <LectureBadge status={state.lecture} compact /> : null}

        <div className="dk-ticker" aria-hidden={!ticker.length}>
          <div className="dk-ticker-track" style={{ animationDuration: `${Math.max(30, ticker.length * 6)}s` }}>
            {ticker.map((q, i) => (
              <span className="dk-tick" key={`${q.symbol}-${i}`}>
                <b>{q.symbol}</b> {money(q.price, q.currency)}{" "}
                <span className={q.change >= 0 ? "is-up" : "is-down"}>
                  {q.change >= 0 ? "▲" : "▼"} {Math.abs(q.change).toFixed(2)}%
                </span>
              </span>
            ))}
          </div>
        </div>

        <div className="dk-rail">{rail(["weather", "system", "research"])}</div>

        <main className="dk-stage" ref={stage}>
          <Brackets />
          <div className="dk-stage-head">
            <span className="dk-stage-title">
              <Scramble text={CARD_LABEL[centre]} run={booting} at={6600} dur={600} />
            </span>
            <span className="dk-stage-dots">
              {cards.map((id) => (
                <i key={id} className={id === centre ? "is-on" : ""} />
              ))}
            </span>
            {zoomShown !== 1 ? <span className="dk-hold">zoom &times;{zoomShown.toFixed(2)}</span> : null}
            <span className={held ? "dk-hold is-held" : "dk-hold"}>{held ? `hold · ${holdWhy}` : "auto"}</span>
          </div>
          <div className="dk-progress">
            <i key={`${turn}-${held}`} className={held ? "is-held" : ""} style={{ animationDuration: `${dwell}ms` }} />
          </div>
          <div className="dk-stage-cards">
            {leaving ? (
              <div className={`dk-stage-card is-out fx-${leaving.deal}`} key={`out-${leaving.key}`} style={{ ["--deal-dir" as string]: turn % 2 ? 1 : -1 }}>
                <div className="dk-scroll">{leaving.id === "panel" ? <PanelCard content={leaving.her} /> : body(leaving.id, "big")}</div>
              </div>
            ) : null}
            <div className={`dk-stage-card is-in fx-${deal}`} key={`in-${centre}-${turn}`} style={{ ["--deal-dir" as string]: turn % 2 ? 1 : -1 }}>
              <div className="dk-scroll" ref={scroller}>
                <div className="dk-zoom-layer" ref={layer}>
                  <div className="dk-zoom" ref={inner}>
                    {body(centre, "big")}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="dk-scan" aria-hidden="true" />
        </main>

        <div className="dk-rail is-two">{rail(["markets", "news"])}</div>

        <footer className="dk-foot">
          <span className="dk-label">local &middot; real sources only</span>
          <span className="dk-label">say &ldquo;open the second news item&rdquo; &middot; point and hold to click</span>
        </footer>
      </div>
    </div>
  );
}
