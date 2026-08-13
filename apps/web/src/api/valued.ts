/**
 * The provenance envelope every externally-sourced value travels in
 * (docs/api.md §3), and the mechanism that turns the specification's
 * epistemic principles — P2 (provenance), P3 (absence vs. unavailability),
 * P4 (explicit uncertainty) — into a compile error instead of a convention
 * someone has to remember.
 *
 * The key design point: `value` and `reason` are NOT present on every member
 * of the union. TypeScript only allows accessing a property on a union type
 * if it exists on every member — so `valued.value` without first narrowing on
 * `state` is a compile error, not merely a value that happens to be `T | null`.
 * Narrowing via `state === "AVAILABLE"` is the only way in.
 */

export type FreshnessState =
  | "LIVE"
  | "FRESH"
  | "RECENT"
  | "CACHED"
  | "STALE"
  | "UNKNOWN"
  | "CONFLICTING";

export type Confidence = "HIGH" | "MEDIUM" | "LOW" | "NONE";

export interface UnknownReason {
  code: string;
  source?: string;
  circuit?: string;
}

interface Provenance {
  freshness: FreshnessState;
  confidence: Confidence;
  source: string;
  source_reference?: string;
  retrieved_at: string;
  age_seconds?: number;
}

interface Available<T> extends Provenance {
  state: "AVAILABLE";
  value: T;
}

interface Unavailable extends Provenance {
  state: "UNAVAILABLE";
}

interface Unknown extends Provenance {
  state: "UNKNOWN";
  reason: UnknownReason;
}

interface Conflicting<T> extends Provenance {
  state: "CONFLICTING";
  value: T;
  alternatives: T[];
}

export type Valued<T> = Available<T> | Unavailable | Unknown | Conflicting<T>;

export function isAvailable<T>(v: Valued<T>): v is Available<T> {
  return v.state === "AVAILABLE";
}

export function isUnavailable<T>(v: Valued<T>): v is Unavailable {
  return v.state === "UNAVAILABLE";
}

export function isUnknown<T>(v: Valued<T>): v is Unknown {
  return v.state === "UNKNOWN";
}

export function isConflicting<T>(v: Valued<T>): v is Conflicting<T> {
  return v.state === "CONFLICTING";
}

/**
 * Query staleness derived from the value's own freshness window, not a global
 * default (docs/api.md §13, rule 6). These are the client-side mirror of the
 * server's freshness policy (spec §42) — how long the client itself should
 * keep showing this response before treating it as needing a refetch.
 *
 * STALE and UNKNOWN return 0: the client should try again on the next
 * opportunity rather than sit on a value already flagged as unusable.
 */
export function staleTimeMsFor(freshness: FreshnessState): number {
  switch (freshness) {
    case "LIVE":
      return 5_000;
    case "FRESH":
      return 60_000;
    case "RECENT":
      return 5 * 60_000;
    case "CACHED":
      return 60 * 60_000;
    case "STALE":
      return 0;
    case "UNKNOWN":
      return 0;
    case "CONFLICTING":
      return 0;
  }
}

/** The most conservative staleness among several wrapped values in one
 * response — a result carries a cash price, an award, a transfer rule, each
 * with its own freshness, and the response as a whole is only as fresh as
 * its least-fresh field. */
export function staleTimeMsForAll(values: Valued<unknown>[]): number {
  if (values.length === 0) return 60_000;
  return Math.min(...values.map((v) => staleTimeMsFor(v.freshness)));
}
