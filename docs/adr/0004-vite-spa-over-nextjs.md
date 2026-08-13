# 0004 — Vite SPA instead of Next.js

**Status:** Accepted
**Date:** 13 August 2026

## Context

Version 1.0 specified Next.js, React and TypeScript (old §119) without distinguishing Next.js
from any other React setup — the stated reasoning supported React and TypeScript, not the
framework choice.

The application's actual shape: a dense private dashboard on a LAN, no anonymous users, no
SEO, no public content, no first-paint budget for cold visitors, and progressive updates
delivered over SSE.

The original argument against Next.js was partly that a persistent Node SSR process costs
150–250 MB on a Raspberry Pi. ADR 0002 removed that constraint, and that part of the argument
must be discarded rather than quietly retained.

## Options

**Next.js as specified.** File-based routing, a large ecosystem, and server-side rendering
available if the system is ever exposed beyond the LAN. With the current host, the runtime
cost is affordable.

**Vite + React + TypeScript, static SPA.**

## Decision

Vite, React and TypeScript, built to a static bundle served directly by Caddy. TanStack Query
for server state and caching, TanStack Router for typed routing.

## Consequences

**No JavaScript runtime in production.** One fewer container, one fewer process to secure,
patch and monitor. The frontend is static files.

**Faster builds and a simpler mental model.** No server/client component boundary to reason
about, which for an application with no server rendering is pure removed complexity.

**Server-side rendering is foreclosed** without a migration. Accepted: the application is
private, and SSR would deliver nothing here.

**TanStack Query's cache becomes the mechanism for a specification requirement.** Query
staleness is configured from each value's own freshness window rather than a global default,
which is how `spec §42` reaches the client. This suits an SPA well.

**The judgement is weaker than it first appeared.** Once the RAM argument fell away, this
became a preference for simplicity over convention rather than a clear-cut technical
necessity, and it is recorded as such. If the project ever needs SSR, revisiting this is
legitimate and not a reversal of anything load-bearing.

Supersedes old §119. Implemented by `CLAUDE.md §6`.
