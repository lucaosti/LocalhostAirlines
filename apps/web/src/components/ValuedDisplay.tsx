import type { Valued } from "../api/valued";
import { isAvailable, isConflicting, isUnavailable, isUnknown } from "../api/valued";

/**
 * Renders any Valued<T> field. This is the one place a `Valued` value should
 * be unwrapped for display — every other component consumes its rendered
 * output rather than reaching into `.state` itself, so the "never render a
 * wrapped value without narrowing" rule (docs/api.md §13) has exactly one
 * place to hold.
 */
export function ValuedDisplay<T>({
  valued,
  render,
}: {
  valued: Valued<T>;
  render: (value: T) => React.ReactNode;
}) {
  if (isAvailable(valued)) {
    return (
      <span className="valued valued--available">
        {render(valued.value)}
        <FreshnessBadge freshness={valued.freshness} confidence={valued.confidence} />
      </span>
    );
  }

  if (isConflicting(valued)) {
    return (
      <span className="valued valued--conflicting">
        {render(valued.value)}
        <span className="valued__warning">
          {valued.alternatives.length} other source{valued.alternatives.length === 1 ? "" : "s"}{" "}
          disagree
        </span>
        <FreshnessBadge freshness={valued.freshness} confidence={valued.confidence} />
      </span>
    );
  }

  if (isUnavailable(valued)) {
    // Absence, not ignorance (spec P3): the source stated there is none.
    return <span className="valued valued--unavailable">Not available</span>;
  }

  if (isUnknown(valued)) {
    // Ignorance, not absence: the source could not be consulted. Rendering
    // this identically to "Not available" is exactly the failure spec P3
    // exists to prevent, so the reason is always shown.
    return (
      <span className="valued valued--unknown">
        Unknown
        <span className="valued__reason" title={JSON.stringify(valued.reason)}>
          ({valued.reason.code}
          {valued.reason.source ? ` — ${valued.reason.source}` : ""}
          {valued.reason.circuit ? `, circuit ${valued.reason.circuit}` : ""})
        </span>
      </span>
    );
  }

  // Exhaustiveness: if a fifth state is ever added to Valued<T>, this line
  // fails to compile until every branch above handles it.
  return valued satisfies never;
}

function FreshnessBadge({
  freshness,
  confidence,
}: {
  freshness: Valued<unknown>["freshness"];
  confidence: Valued<unknown>["confidence"];
}) {
  return (
    <span className={`freshness freshness--${freshness.toLowerCase()}`}>
      {freshness} · {confidence}
    </span>
  );
}
