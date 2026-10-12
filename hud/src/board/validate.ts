// Checking what the model drew before anything is drawn. Every template's parse()
// goes through these: a wrong type, a missing field or a value out of range throws
// BoardError, and the board then draws nothing - it never guesses and never
// crashes on a bad <draw>. Cosmetics are forgiven, facts are not: text too long
// for the matrix is clipped and "9 m" reads as 9, but an illegal move or a value
// outside its range is refused.

export class BoardError extends Error {}

export type Args = Record<string, unknown>;

export function obj(value: unknown, what = "arguments"): Args {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new BoardError(`${what} must be an object`);
  return value as Args;
}

export function num(args: Args, key: string, opts: { min?: number; max?: number; def?: number; int?: boolean } = {}): number {
  const raw = args[key];
  if (raw === undefined || raw === null) {
    if (opts.def !== undefined) return opts.def;
    throw new BoardError(`${key} is required`);
  }
  // "9 m", "60%": the number the text starts with
  const value = typeof raw === "string" && raw.trim() !== "" ? Number((/^\s*-?\d+(\.\d+)?/.exec(raw) ?? [NaN])[0]) : raw;
  if (typeof value !== "number" || !Number.isFinite(value)) throw new BoardError(`${key} must be a number`);
  if (opts.int && !Number.isInteger(value)) throw new BoardError(`${key} must be a whole number`);
  if (opts.min !== undefined && value < opts.min) throw new BoardError(`${key} must be at least ${opts.min}`);
  if (opts.max !== undefined && value > opts.max) throw new BoardError(`${key} must be at most ${opts.max}`);
  return value;
}

export function str(args: Args, key: string, opts: { def?: string; max?: number; oneOf?: readonly string[] } = {}): string {
  const raw = args[key];
  if (raw === undefined || raw === null) {
    if (opts.def !== undefined) return opts.def;
    throw new BoardError(`${key} is required`);
  }
  if (typeof raw !== "string" && typeof raw !== "number") throw new BoardError(`${key} must be text`);
  const full = String(raw).trim();
  // too long for the matrix: clipped, not refused (it is only a label)
  const value = opts.max !== undefined && !opts.oneOf && full.length > opts.max ? clip(full, opts.max) : full;
  if (opts.oneOf) {
    const match = opts.oneOf.find((o) => o.toLowerCase() === value.toLowerCase().replace(/[\s-]+/g, "_") || o.toLowerCase() === value.toLowerCase());
    if (!match) throw new BoardError(`${key} must be one of: ${opts.oneOf.join(", ")}`);
    return match;
  }
  return value;
}

export function optStr(args: Args, key: string, max = 40): string | undefined {
  return args[key] === undefined || args[key] === null ? undefined : str(args, key, { max });
}

export function bool(args: Args, key: string, def = false): boolean {
  const raw = args[key];
  if (raw === undefined || raw === null) return def;
  if (typeof raw !== "boolean") throw new BoardError(`${key} must be true or false`);
  return raw;
}

export function list(args: Args, key: string, opts: { min?: number; max?: number; def?: unknown[] } = {}): unknown[] {
  const raw = args[key];
  if (raw === undefined || raw === null) {
    if (opts.def !== undefined) return opts.def;
    throw new BoardError(`${key} is required`);
  }
  if (!Array.isArray(raw)) throw new BoardError(`${key} must be a list`);
  if (opts.min !== undefined && raw.length < opts.min) throw new BoardError(`${key} needs at least ${opts.min} item(s)`);
  if (opts.max !== undefined && raw.length > opts.max) throw new BoardError(`${key} has more than ${opts.max} items`);
  return raw;
}

export function numbers(args: Args, key: string, opts: { min?: number; max?: number; def?: number[] } = {}): number[] {
  return list(args, key, opts).map((v, i) => {
    const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
    if (typeof n !== "number" || !Number.isFinite(n)) throw new BoardError(`${key}[${i}] must be a number`);
    return n;
  });
}

export function strings(args: Args, key: string, opts: { min?: number; max?: number; def?: string[]; each?: number } = {}): string[] {
  return list(args, key, opts).map((v, i) => {
    if (typeof v !== "string" && typeof v !== "number") throw new BoardError(`${key}[${i}] must be text`);
    const s = String(v).trim();
    return opts.each !== undefined && s.length > opts.each ? clip(s, opts.each) : s;
  });
}

/** Clip a label to `n` characters for the matrix, marking the cut. */
export function clip(text: string, n: number): string {
  return text.length <= n ? text : `${text.slice(0, Math.max(1, n - 1))}.`;
}
