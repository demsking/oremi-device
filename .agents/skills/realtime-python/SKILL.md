# Realtime Python

## Purpose
Guide coding agents working on Oremi Device toward predictable low-latency asyncio behavior.

## Core rules
- Treat the asyncio event loop as a latency-critical resource.
- Never perform blocking I/O, subprocess work, device enumeration, synchronous HTTP, filesystem-heavy work, or CPU-heavy processing directly on the event loop.
- Use `asyncio.to_thread()` for blocking operations when they cannot be made asynchronous.
- Use `loop.call_soon_threadsafe()` when crossing from external threads into asyncio.
- Bound queues and explicitly reason about backpressure, overflow, and drop behavior.
- Every task created by a change must have a clear lifecycle, cancellation path, and cleanup path.
- Preserve cancellation: do not catch `CancelledError` as a normal application error.
- Prefer connection reuse over repeated connection establishment on hot paths.
- Avoid unnecessary task creation, context switching, serialization, and buffer copying.
- Do not introduce polling where event-driven behavior is possible.

## Review checklist
For every change, inspect:
1. Event-loop blocking.
2. Task lifecycle and cancellation.
3. Thread-to-loop boundaries.
4. Queue bounds and overflow semantics.
5. Timeout behavior.
6. Retry behavior.
7. Unnecessary allocations and copies.
8. Resource cleanup.
9. Latency impact on the conversational critical path.

## Oremi Device invariants
Preserve the existing shared audio-stream lifecycle, MQTT thread handoff, and blocking Speaker API rules documented in `AGENTS.md`.
