# Asyncio Performance

## Purpose
Optimize Oremi Device's asyncio execution without changing observable behavior unnecessarily.

## Review areas
- event-loop blocking;
- task scheduling;
- cancellation;
- queue contention;
- timeout placement;
- thread-pool usage;
- connection reuse;
- excessive coroutine/task creation;
- unnecessary context switches;
- synchronous libraries used from async code.

## Rules
- Keep latency-critical coroutines short and non-blocking.
- Do not use `time.sleep()` in async code.
- Do not call synchronous HTTP clients from latency-sensitive async paths.
- Avoid wrapping inherently asynchronous operations in unnecessary threads.
- Use `asyncio.to_thread()` for genuinely blocking operations.
- Give long-running tasks explicit names and cleanup paths.
- Never create background tasks without ownership and shutdown behavior.

## Verification
Use focused benchmarks or tests when changing scheduling, queues, timeouts, or task structure.
