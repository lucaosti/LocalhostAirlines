import { QueryClient } from "@tanstack/react-query";

/**
 * TanStack Query v5's `staleTime` accepts a function of the query itself, so
 * staleness can be computed from the response *after* it arrives rather than
 * guessed at query-definition time — which is what's needed here, since
 * freshness (docs/api.md §3) is data returned by the server, not something
 * known in advance from the query key.
 *
 * This default is deliberately conservative (5 minutes) for queries whose
 * data shape has no Valued<T> fields to inspect. Any query returning
 * provenance-wrapped data overrides staleTime with staleTimeMsForAll() over
 * its own fields — see src/components/ValuedDemo.tsx for the pattern.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60_000,
        retry: 2,
      },
    },
  });
}
