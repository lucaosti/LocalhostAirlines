import { useQuery } from "@tanstack/react-query";
import type { Valued } from "../api/valued";
import { staleTimeMsForAll } from "../api/valued";
import { ValuedDisplay } from "./ValuedDisplay";

interface DemoFare {
  price: Valued<{ amount_minor: number; currency: string }>;
  award: Valued<{ points: number; program: string }>;
}

// Stands in for a real endpoint until a domain router exists (M3). The shape
// mirrors docs/api.md §3 exactly, covering all four states plus the
// CONFLICTING alternatives array, so the rendering path is exercised for real
// rather than only at the type level.
async function fetchDemoFare(): Promise<DemoFare> {
  return {
    price: {
      state: "AVAILABLE",
      value: { amount_minor: 74200, currency: "EUR" },
      freshness: "CACHED",
      confidence: "MEDIUM",
      source: "travelpayouts",
      retrieved_at: new Date().toISOString(),
      age_seconds: 21600,
    },
    award: {
      state: "UNKNOWN",
      freshness: "UNKNOWN",
      confidence: "NONE",
      source: "award_scraper",
      retrieved_at: new Date().toISOString(),
      reason: { code: "BLOCKED", source: "award_scraper", circuit: "OPEN" },
    },
  };
}

export function ValuedDemo() {
  const query = useQuery({
    queryKey: ["demo-fare"],
    queryFn: fetchDemoFare,
    // Per-response staleness (docs/api.md §13, rule 6): derived from the
    // freshness actually returned, not a fixed default. TanStack Query's
    // StaleTime type requires a concrete number even before data exists, so
    // the fallback below only ever applies to the very first render.
    staleTime: (q) =>
      q.state.data ? staleTimeMsForAll([q.state.data.price, q.state.data.award]) : 60_000,
  });

  if (query.isPending) return <p>Loading…</p>;
  if (query.isError) return <p>Failed to load.</p>;

  return (
    <dl>
      <dt>Cash price</dt>
      <dd>
        <ValuedDisplay
          valued={query.data.price}
          render={(v) => `${(v.amount_minor / 100).toFixed(2)} ${v.currency}`}
        />
      </dd>
      <dt>Award</dt>
      <dd>
        <ValuedDisplay valued={query.data.award} render={(v) => `${v.points} ${v.program}`} />
      </dd>
    </dl>
  );
}
