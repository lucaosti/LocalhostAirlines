import type { ObservationResponse } from "../api/client";
import { ValuedDisplay } from "./ValuedDisplay";

/**
 * Renders the M1 search's results. An empty list here means "the search
 * completed and found nothing" — structurally distinct from the loading
 * state the caller shows before the search reaches READY: a NOT_AVAILABLE-
 * shaped result must not look identical to still-loading (spec P3).
 */
export function SearchResults({ observations }: { observations: ObservationResponse[] }) {
  if (observations.length === 0) {
    return <p>No observations for this route and month.</p>;
  }

  return (
    <ul className="search-results">
      {observations.map((obs) => (
        <li key={obs.itinerary_id}>
          <ValuedDisplay
            valued={obs.price}
            render={(v) => `${(v.amount_minor / 100).toFixed(2)} ${v.currency}`}
          />
          <span className="search-results__source"> via {obs.source}</span>
          {obs.slices.map((slice, sliceIndex) => (
            // Index as key is fine here: slice order within one offer is
            // fixed by the server and never reordered client-side.
            <ol key={sliceIndex} className="search-results__slice">
              {slice.segments.map((seg) => (
                <li key={`${seg.marketing_carrier}${seg.flight_number}-${seg.departure_utc}`}>
                  {seg.marketing_carrier}
                  {seg.flight_number}: {seg.origin} → {seg.destination} (
                  {new Date(seg.departure_utc).toLocaleString()})
                </li>
              ))}
            </ol>
          ))}
          {obs.limitations.length > 0 && (
            <p className="search-results__limitations">{obs.limitations.join("; ")}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
