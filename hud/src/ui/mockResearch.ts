// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
import type { ContentBlock, PanelContent, SourceRef } from "./content";

// Stand-in for a backend result until core/ speaks over the socket. It exists to
// exercise every block kind the renderer claims to support - if a kind is added
// to content.ts, add an instance of it here.

const SOURCES: SourceRef[] = [
  { index: 1, title: "Streaming architectures for conversational speech", publisher: "Interspeech", year: 2024 },
  { index: 2, title: "Quantisation tradeoffs below eight bits", publisher: "MLSys", year: 2024 },
  { index: 3, title: "Small-footprint keyword spotting in reverberant rooms", publisher: "ICASSP", year: 2023 },
  { index: 4, title: "Contextual biasing for end-to-end recognition", publisher: "ACL", year: 2024 },
  { index: 5, title: "Perceptual thresholds in spoken turn-taking", publisher: "CHI", year: 2022 },
  { index: 6, title: "Chunking strategies for retrieval over personal corpora", publisher: "EMNLP", year: 2024 },
  { index: 7, title: "Prosody modelling for long-form synthesis", publisher: "SSW", year: 2023 },
  { index: 8, title: "Mid-air gesture fatigue and interaction duration", publisher: "UIST", year: 2023 },
  { index: 9, title: "Auditing locality claims in on-device assistants", publisher: "PETS", year: 2025 },
  { index: 10, title: "Evaluation gaps in interactive assistant benchmarks", publisher: "NeurIPS Datasets", year: 2024 },
];

/** Vendored, not fetched: the image block has to prove a local source works. */
function latencyBudgetSvg(): string {
  const stages: { label: string; ms: number; color: string }[] = [
    { label: "WAKE", ms: 18, color: "#5ef2b8" },
    { label: "ASR", ms: 84, color: "#22e0ff" },
    { label: "LLM TTFT", ms: 96, color: "#b892ff" },
    { label: "TTS", ms: 41, color: "#ffb648" },
  ];
  const width = 640;
  const height = 210;
  const left = 96;
  const scale = (width - left - 24) / 260;

  let bars = "";
  stages.forEach((stage, index) => {
    const y = 42 + index * 38;
    bars +=
      `<text x="${left - 12}" y="${y + 15}" fill="#8fbfd0" font-family="monospace" font-size="13" text-anchor="end">${stage.label}</text>` +
      `<rect x="${left}" y="${y}" width="${(stage.ms * scale).toFixed(1)}" height="21" fill="${stage.color}" opacity="0.85"/>` +
      `<text x="${(left + stage.ms * scale + 10).toFixed(1)}" y="${y + 16}" fill="#d8f6ff" font-family="monospace" font-size="13">${stage.ms} ms</text>`;
  });

  const budget = left + 250 * scale;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">` +
    `<rect width="${width}" height="${height}" fill="#04111a"/>` +
    `<text x="24" y="26" fill="#22e0ff" font-family="monospace" font-size="13" letter-spacing="2">TURN LATENCY BUDGET</text>` +
    `<line x1="${budget}" y1="34" x2="${budget}" y2="${height - 34}" stroke="#ff5c5c" stroke-width="1.5" stroke-dasharray="5 4"/>` +
    `<text x="${budget - 8}" y="${height - 20}" fill="#ff5c5c" font-family="monospace" font-size="12" text-anchor="end">250 ms ceiling</text>` +
    bars +
    `</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

const BLOCKS: ContentBlock[] = [
  { kind: "heading", text: "Summary" },
  {
    kind: "text",
    text: "Voice assistants that run entirely on local hardware have moved from research curiosity to practical deployment in the span of roughly four years. The shift was driven less by any single breakthrough than by the convergence of three trends: speech recognition models small enough to fit comfortably in consumer GPU memory, quantisation techniques that preserve accuracy at four to eight bits per weight, and a growing unwillingness among users to route private conversation through third-party infrastructure. The result is a class of system that answers in under a second, works without a network connection, and leaves no transcript on a server the user does not control.",
  },
  {
    kind: "quote",
    text: "A privacy policy is a promise about behaviour. Locality is a property of the architecture. Only one of the two survives a change of management.",
    attribution: "Auditing locality claims in on-device assistants, PETS 2025",
  },
  { kind: "heading", text: "Latency as the primary design constraint" },
  {
    kind: "text",
    text: "The perceptual threshold for conversational turn-taking sits somewhere near two hundred and fifty milliseconds. Below it, a response feels like an answer; above it, it feels like a wait. This single number constrains nearly every architectural decision in a local assistant. Wake word detection must run continuously at negligible cost. Transcription must begin before the user stops speaking. Generation must produce its first token quickly even if total throughput is modest. Synthesis must start emitting audio before the full response text exists.",
  },
  {
    kind: "image",
    src: latencyBudgetSvg(),
    alt: "Stacked latency budget: wake word 18ms, ASR 84ms, LLM time-to-first-token 96ms, TTS 41ms, against a 250ms ceiling.",
    caption: "FIG 01 — measured turn budget, RTX 5060 Ti, float16 throughout",
  },
  { kind: "heading", text: "Stage detail", level: 3 },
  {
    kind: "text",
    text: "Systems that treat these four stages as independent services, each optimised in isolation, reliably feel slower than the sum of their parts would suggest. The gaps between stages are where the budget is actually lost: buffer handoffs, model warm-up, and the decision point at which a partial transcript is considered final.",
  },
  { kind: "heading", text: "Gesture and gaze as complements to voice" },
  {
    kind: "text",
    text: "Voice is a poor medium for spatial reference. Saying which window, which paragraph, or which of several similar items is slower and less reliable than pointing. Hand tracking from a single consumer camera has become accurate enough to supply that missing channel. The engineering difficulties are less about detection accuracy than about interaction design: continuous tracking produces a cursor that never rests, so filtering is mandatory and the choice of filter is perceptible. Fatigue is the binding constraint on any design requiring a raised arm.",
  },
  { kind: "heading", text: "Open problems" },
  {
    kind: "text",
    text: "Three problems recur across every implementation surveyed. The first is graceful degradation: what a local system should do when asked something beyond its knowledge, where the honest answer is an admission of ignorance and the tempting answer is a fluent fabrication. The second is memory across sessions, which every user expects and almost no system implements well. The third is evaluation — benchmarks measure knowledge and reasoning, not whether a system feels responsive or recovers cleanly from a misheard word.",
  },
  { kind: "sourceList", label: "SOURCES — 10 OF 14", sources: SOURCES },
];

export const MOCK_CONTENT: PanelContent = {
  title: "LOCAL-FIRST VOICE INTERFACES",
  subtitle: "SYNTHESIS OF 14 SOURCES · CONFIDENCE MODERATE",
  blocks: BLOCKS,
};
