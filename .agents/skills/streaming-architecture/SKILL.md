# Streaming Architecture

## Purpose
Help coding agents preserve and improve streaming behavior across Oremi Device and its external services.

## Principles
- Prefer streaming over full-message buffering on latency-sensitive paths.
- Start downstream work as soon as a valid upstream result is available.
- Avoid unnecessary sequential stages when contracts permit overlap.
- Reuse persistent WebSocket/HTTP connections where appropriate.
- Minimize round trips and connection setup on the critical path.
- Do not introduce buffering merely to simplify implementation.
- Preserve ordering and cancellation semantics.

## Critical-path reasoning
For every change, identify:
- producer;
- consumer;
- first useful byte/event;
- final completion event;
- buffering boundaries;
- serialization boundaries;
- network boundaries.

Distinguish:
- time to first result;
- time to final result;
- time to first audio byte;
- time to audible playback.

## Oremi Device
Respect the existing wake-word gate, Andika transcription turn, Akorin command pipeline, TTS backend, and speaker lifecycle. Any change that overlaps stages must preserve their public contracts and cancellation behavior.
