# Latency Profiling

## Purpose
Measure conversational latency instead of relying on subjective claims that a change is faster.

## Required methodology
When performance is relevant, identify timestamps for as many of these milestones as the architecture supports:

T0 = microphone/audio frame available
T1 = wake word detected
T2 = STT turn started
T3 = first partial transcription
T4 = final transcription
T5 = Akorin request started
T6 = Akorin response received
T7 = TTS request started
T8 = first audio byte available
T9 = playback started

Report relevant deltas:
- wakeword latency = T1-T0
- STT first-result latency = T3-T2
- speech completion latency = T4-T3
- NLP latency = T6-T5
- TTS first-byte latency = T8-T7
- audio startup latency = T9-T8
- end-to-end latency = T9-T0

## Statistics
Prefer p50, p95, and p99 over single measurements.

## Rules
- Do not claim a performance improvement without measurement.
- Separate cold-start and warm-path measurements.
- Record test environment and workload.
- Measure before and after when optimizing.
- Avoid instrumentation that materially changes timing.
- Prefer monotonic clocks for latency measurements.

## Oremi Device
Instrumentation must not log raw user speech, credentials, API keys, or audio payloads.
