// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 phuctri174
export interface OneEuroConfig {
  minCutoff: number;
  beta: number;
  dCutoff: number;
}

export interface Vec2 {
  x: number;
  y: number;
}

const MS_PER_SECOND = 1000;
const MIN_DELTA_SECONDS = 1 / 240;
const MAX_DELTA_SECONDS = 1 / 5;
const TWO_PI = Math.PI * 2;

function smoothingAlpha(cutoff: number, deltaSeconds: number): number {
  const tau = 1 / (TWO_PI * cutoff);
  return 1 / (1 + tau / deltaSeconds);
}

class LowPassFilter {
  private value = 0;
  private initialized = false;

  filter(input: number, alpha: number): number {
    this.value = this.initialized ? alpha * input + (1 - alpha) * this.value : input;
    this.initialized = true;
    return this.value;
  }

  set(input: number): void {
    this.value = input;
    this.initialized = true;
  }

  reset(): void {
    this.value = 0;
    this.initialized = false;
  }
}

export class OneEuroFilter {
  private readonly config: OneEuroConfig;
  private readonly value = new LowPassFilter();
  private readonly derivative = new LowPassFilter();
  private previousValue = 0;
  private previousTimestamp = -1;

  constructor(config: OneEuroConfig) {
    this.config = { ...config };
  }

  filter(value: number, timestamp: number): number {
    if (this.previousTimestamp < 0) {
      this.previousTimestamp = timestamp;
      this.previousValue = value;
      this.value.filter(value, 1);
      this.derivative.filter(0, 1);
      return value;
    }

    const elapsed = (timestamp - this.previousTimestamp) / MS_PER_SECOND;
    const deltaSeconds = Math.min(Math.max(elapsed, MIN_DELTA_SECONDS), MAX_DELTA_SECONDS);
    this.previousTimestamp = timestamp;

    const rate = (value - this.previousValue) / deltaSeconds;
    this.previousValue = value;

    const smoothedRate = this.derivative.filter(rate, smoothingAlpha(this.config.dCutoff, deltaSeconds));
    const cutoff = this.config.minCutoff + this.config.beta * Math.abs(smoothedRate);

    return this.value.filter(value, smoothingAlpha(cutoff, deltaSeconds));
  }

  seed(value: number, timestamp: number): void {
    this.value.set(value);
    this.derivative.set(0);
    this.previousValue = value;
    this.previousTimestamp = timestamp;
  }

  reset(): void {
    this.value.reset();
    this.derivative.reset();
    this.previousValue = 0;
    this.previousTimestamp = -1;
  }
}

export class Vec2Filter {
  private readonly xFilter: OneEuroFilter;
  private readonly yFilter: OneEuroFilter;

  constructor(config: OneEuroConfig) {
    this.xFilter = new OneEuroFilter(config);
    this.yFilter = new OneEuroFilter(config);
  }

  filter(x: number, y: number, timestamp: number): Vec2 {
    return {
      x: this.xFilter.filter(x, timestamp),
      y: this.yFilter.filter(y, timestamp),
    };
  }

  filterInto(target: Vec2, x: number, y: number, timestamp: number): Vec2 {
    target.x = this.xFilter.filter(x, timestamp);
    target.y = this.yFilter.filter(y, timestamp);
    return target;
  }

  seed(x: number, y: number, timestamp: number): void {
    this.xFilter.seed(x, timestamp);
    this.yFilter.seed(y, timestamp);
  }

  reset(): void {
    this.xFilter.reset();
    this.yFilter.reset();
  }
}

export const DEFAULT_CURSOR_FILTER: OneEuroConfig = {
  minCutoff: 1.2,
  beta: 6,
  dCutoff: 1,
};
