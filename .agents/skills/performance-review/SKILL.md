# Performance Review

## Purpose
Perform a focused performance review of changes to Oremi Device.

## Checklist
Review every relevant change for:
- end-to-end latency regression;
- event-loop blocking;
- audio callback safety;
- queue growth;
- backpressure;
- unnecessary serialization;
- unnecessary buffer copies;
- connection setup overhead;
- HTTP/WebSocket round trips;
- task creation overhead;
- CPU usage;
- memory allocations;
- timeout behavior;
- cancellation behavior;
- startup latency;
- cold vs warm performance.

## Required output
When asked to review performance:
1. Identify the critical path.
2. Identify the likely bottleneck.
3. Explain the mechanism causing latency or resource cost.
4. Prefer measured evidence.
5. Propose the smallest safe change.
6. Identify regression tests or benchmarks.

Never replace measurement with intuition.
