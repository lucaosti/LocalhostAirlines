import { createFileRoute } from "@tanstack/react-router";
import { SearchPage } from "../components/SearchPage";

export const Route = createFileRoute("/search")({
  component: SearchRoute,
});

function SearchRoute() {
  return (
    <main>
      <h1>M1 walking skeleton</h1>
      <p>One source (Travelpayouts), one route, end to end (spec §5, §86).</p>
      <SearchPage />
    </main>
  );
}
