import { createFileRoute } from "@tanstack/react-router";
import { ValuedDemo } from "../components/ValuedDemo";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  return (
    <main>
      <h1>Foundation skeleton</h1>
      <p>Demonstrates the Valued&lt;T&gt; provenance envelope (docs/api.md §3).</p>
      <ValuedDemo />
    </main>
  );
}
