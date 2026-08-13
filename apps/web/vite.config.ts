import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Static build served by Caddy (docs/adr/0004-vite-spa-over-nextjs.md).
// The router plugin generates src/routeTree.gen.ts from the routes/ directory
// before the React plugin runs.
export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react()],
  server: {
    // Bound to all interfaces so the dev-profile container is reachable from
    // the host (CLAUDE.md §6, Docker Compose dev profile).
    host: true,
    port: 5173,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
