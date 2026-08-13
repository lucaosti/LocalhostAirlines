# 0002 — Generic containerized host; storage over source access

**Status:** Accepted
**Date:** 13 August 2026

## Context

Version 1.0 targeted a Raspberry Pi and derived a great deal from that: minimal database
writes, short raw-data retention, few background processes, and the explicit rule (old §64)
that recomputing a search was preferable to storing its results.

Two things changed. The deployment target became an ordinary machine with 8–16 GB of RAM and
ample SSD. And ADR 0001 made most sources unofficial and fragile, which required adopting a
headless browser — impractical on a Pi alongside PostgreSQL, Redis and the application, since
Chromium consumes 400 MB–1 GB per instance on ARM.

## Options

**Keep the Pi and drop headless rendering.** Preserves the original constraints but forecloses
sources that require JavaScript, which after ADR 0001 is a material loss of coverage.

**Keep the Pi with a larger model and hard memory caps.** Workable on a Pi 5 with 8 GB, but
every component would be designed around a constraint that is not intrinsic to the problem.

**Move to an ordinary machine, fully containerized.**

## Decision

An ordinary machine — 8–16 GB RAM, SSD, x86_64 or arm64 — running Docker Compose, with
extreme portability as an explicit goal: nothing installed on the host, development and
production differing only by Compose profile, images built multi-arch for `linux/amd64` and
`linux/arm64`.

And, more consequentially, **the resource trade-off inverts:**

> Access to sources is the scarce resource. Storage is not.
> Cache aggressively, re-fetch as rarely as correctness allows, and persist raw payloads so
> history can be re-normalized without contacting the source again.

## Consequences

**Old §64 is reversed, and this is the point of the ADR.** The Pi-era rule said to spend
CPU and network rather than storage. With fragile, rate-limited, ban-prone sources, network
access is now the thing that must be conserved and storage is the thing that is cheap.

**Parser bugs become recoverable.** Retaining raw payloads means a parser fix can reprocess
history. Without them, every parsing bug is permanent data loss on sources that cannot be
queried retroactively — and for unofficial sources, parsing bugs are routine rather than
exceptional. This single consequence justifies the storage cost several times over.

**Concurrency is bounded by politeness, not by hardware.** A lower and more intelligent limit
than the one it replaces.

**Headless work is still constrained**, but for reasons of predictability rather than
survival: isolated container, hard memory cap, concurrency 1–3, scheduler-driven only, never
on an HTTP request path. No user request waits for a browser.

**The Pi-specific sections of the specification are withdrawn**: old §6.1, §59, §128, §129,
§164, §165.

**Backup becomes mandatory and is now the top operational risk.** Version 1.0 never mentioned
it. For a system whose entire value is an accumulated record that cannot be re-fetched
retroactively, an unverified backup is the most likely route to total loss.

Implemented by `spec §4`, `§6`, `§24`, `§55`, `§81`.
