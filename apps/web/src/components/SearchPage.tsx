import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { SearchIn, UserResponse } from "../api/client";
import { createSearch, getSearch, getSearchResults } from "../api/client";
import { LoginForm } from "./LoginForm";
import { SearchForm } from "./SearchForm";
import { SearchResults } from "./SearchResults";

const TERMINAL_STATES = new Set(["ready", "failed"]);

/** Orchestrates the M1 walking skeleton end to end: sign in, trigger a
 * search, poll it to completion, show what came back (issue #44). */
export function SearchPage() {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [searchId, setSearchId] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: createSearch,
    onSuccess: (search) => setSearchId(search.id),
  });

  const searchQuery = useQuery({
    queryKey: ["search", searchId],
    queryFn: () => getSearch(searchId as string),
    enabled: searchId !== null,
    // Poll while the search is still in flight; stop once it reaches a
    // terminal state so this doesn't hammer the API forever on a page left
    // open (spec §29's state machine — PENDING/RUNNING are non-terminal).
    refetchInterval: (query) =>
      query.state.data && TERMINAL_STATES.has(query.state.data.state) ? false : 1000,
    // TanStack Query pauses interval polling while the document is hidden by
    // default. Found running this against a real browser tab (issue #44):
    // switch away mid-search and the page silently stops updating until
    // refocused. A search here resolves in well under a second today, but
    // M3's real multi-source searches will not, so this is worth being
    // correct about now rather than rediscovering it later.
    refetchIntervalInBackground: true,
  });

  const resultsQuery = useQuery({
    queryKey: ["search-results", searchId],
    queryFn: () => getSearchResults(searchId as string),
    enabled: searchQuery.data?.state === "ready",
  });

  if (user === null) {
    return <LoginForm onLoggedIn={setUser} />;
  }

  return (
    <div>
      <p>Signed in as {user.username}.</p>
      <SearchForm
        onSubmit={(input: SearchIn) => createMutation.mutate(input)}
        disabled={createMutation.isPending || (searchQuery.data ? !TERMINAL_STATES.has(searchQuery.data.state) : false)}
      />

      {searchQuery.isPending && searchId !== null && <p>Starting search…</p>}

      {searchQuery.data?.state === "pending" && <p>Waiting for a worker to pick this up…</p>}
      {searchQuery.data?.state === "running" && <p>Searching…</p>}

      {searchQuery.data?.state === "failed" && (
        <p role="alert">
          Search failed: {searchQuery.data.failure_reason ?? "unknown reason"}. This is a
          normal source outcome (spec §26), not a bug — the failure classification is recorded
          rather than the search silently vanishing.
        </p>
      )}

      {searchQuery.data?.state === "ready" && resultsQuery.isPending && <p>Loading results…</p>}
      {searchQuery.data?.state === "ready" && resultsQuery.data && (
        <SearchResults observations={resultsQuery.data} />
      )}
    </div>
  );
}
