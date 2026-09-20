# Real-Time Audio

## Purpose
Guide coding agents modifying Oremi Device audio capture, transport, buffering, and playback.

## Critical pipeline
Microphone -> audio capture -> subscriber queues -> Ohunerin/Andika -> Akorin -> TTS -> ffmpeg -> speaker.

## Rules
- Treat audio callbacks as hard real-time-sensitive paths.
- Never perform network I/O, logging at excessive volume, allocation-heavy work, or blocking operations inside an audio callback.
- Preserve the established capture format unless the task explicitly changes the contract.
- Keep producer/consumer queue behavior bounded and intentional.
- Analyze buffer duration, not only queue item count.
- Avoid unnecessary PCM conversions and copies.
- Keep capture and playback formats synchronized with their respective devices.
- Treat buffer growth as latency growth.
- Prefer small, stable buffers over large safety buffers when the service can sustain them.
- Any change to sample rate, channels, sample format, block size, or queue depth requires tests and an end-to-end latency review.

## Latency review
For audio changes, calculate or estimate:
- duration represented by each audio frame;
- maximum queueing delay;
- worst-case buffering delay;
- device startup delay;
- decoder startup delay;
- network transmission delay.

## Oremi Device
The current repository documents mono 16-bit 16 kHz capture and f32le 48 kHz playback. Treat those as existing contracts unless the task explicitly changes them.
