import { useState } from "react";
import type { SearchIn } from "../api/client";

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

/** M1's search is one origin, one destination, one month, deliberately —
 * not the multi-origin/date-range form the M3-extended resource will
 * eventually need. */
export function SearchForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (input: SearchIn) => void;
  disabled: boolean;
}) {
  const [origin, setOrigin] = useState("MXP");
  const [destination, setDestination] = useState("NRT");
  const [departMonth, setDepartMonth] = useState("2026-10");

  const monthValid = MONTH_PATTERN.test(departMonth);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          origin: origin.toUpperCase(),
          destination: destination.toUpperCase(),
          depart_month: departMonth,
        });
      }}
    >
      <h2>Search</h2>
      <label>
        Origin (IATA)
        <input
          value={origin}
          onChange={(e) => setOrigin(e.target.value)}
          maxLength={3}
          minLength={3}
          required
        />
      </label>
      <label>
        Destination (IATA)
        <input
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          maxLength={3}
          minLength={3}
          required
        />
      </label>
      <label>
        Departure month
        <input
          value={departMonth}
          onChange={(e) => setDepartMonth(e.target.value)}
          placeholder="YYYY-MM"
          required
        />
      </label>
      <button type="submit" disabled={disabled || !monthValid}>
        {disabled ? "Searching…" : "Search"}
      </button>
    </form>
  );
}
