// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
/**
 * Wire format for whatever the panel is asked to show. The backend composes an
 * arbitrary sequence of these; the panel renders them in order and knows nothing
 * about what a "research result" is. Add a block kind here and in ContentBlocks.tsx.
 */

export interface HeadingBlock {
  kind: "heading";
  text: string;
  /** 2 is a section, 3 a subsection. Defaults to 2. */
  level?: 2 | 3;
}

export interface TextBlock {
  kind: "text";
  text: string;
}

export interface QuoteBlock {
  kind: "quote";
  text: string;
  attribution?: string;
}

export interface ImageBlock {
  kind: "image";
  /** Local path under public/, or a data: URI. Never a remote URL. */
  src: string;
  alt: string;
  caption?: string;
}

export interface SourceRef {
  index: number;
  title: string;
  publisher: string;
  year: number;
}

export interface SourceListBlock {
  kind: "sourceList";
  label?: string;
  sources: SourceRef[];
}

/** A link he can click: opens in his own Chrome (through core, never from here). */
export interface LinkBlock {
  kind: "link";
  text: string;
  url: string;
  /** e.g. the site name */
  note?: string;
}

/** A capture of the part of a page that answered. data: URI; clickable when url is set. */
export interface ScreenshotBlock {
  kind: "screenshot";
  src: string;
  caption?: string;
  url?: string;
}

/** A YouTube video card. thumbnail is a data: URI. */
export interface VideoBlock {
  kind: "video";
  title: string;
  channel: string;
  duration: string;
  url: string;
  thumbnail?: string;
}

/** A day of the weather block's forecast (tools/dashboard.weather). */
export interface WeatherDay {
  day: string;
  high: number;
  low: number;
  rain: number;
  sky: string;
}

/** His city's weather now and the next days (the daily briefing). */
export interface WeatherBlock {
  kind: "weather";
  city: string;
  sky: string;
  temp?: number;
  high?: number;
  low?: number;
  /** today's rain chance, percent */
  rain?: number;
  /** days running with rain, today included (0: dry) */
  streak?: number;
  days?: WeatherDay[];
  url?: string;
}

/** A price with its day's change and recent closes: gold, a stock, a currency. */
export interface PriceBlock {
  kind: "price";
  label: string;
  value: string;
  change: string;
  /** true up, false down, absent: no direction (unchanged, or not published) */
  up?: boolean | null;
  note?: string;
  spark?: number[];
  url?: string;
}

/** A news story: its headline (in English), outlet, the others carrying it, its picture. */
export interface StoryBlock {
  kind: "story";
  title: string;
  url: string;
  source: string;
  also?: string[];
  /** data: URI */
  image?: string;
  /** the headline as the outlet wrote it (Vietnamese), when translated */
  original?: string;
}

/** A framed region of other blocks with its own label and look: a lecture note's
 *  key points, homework, definitions - and what she researched online, which must
 *  never look like what the lecturer said (core/irene/lecture_note.py). */
export interface BoxBlock {
  kind: "box";
  tone: "points" | "homework" | "definitions" | "research" | string;
  title: string;
  blocks: ContentBlock[];
}

export type ContentBlock =
  | BoxBlock
  | WeatherBlock
  | PriceBlock
  | StoryBlock
  | HeadingBlock
  | TextBlock
  | QuoteBlock
  | ImageBlock
  | SourceListBlock
  | LinkBlock
  | ScreenshotBlock
  | VideoBlock;

export interface PanelContent {
  title: string;
  subtitle?: string;
  blocks: ContentBlock[];
}
