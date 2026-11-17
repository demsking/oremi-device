# AGENTS.md

Guidance for future coding agents (LLMs or automated tools) modifying, fixing,
testing, or extending **Oremi Device**. This file applies to the entire project
unless a more specific `AGENTS.md` exists in a subdirectory.

> **Accuracy key used throughout this document**
>
> - **Observed** — directly confirmed in the repository source, tests, or
>   config. Treated as an existing project rule.
> - **Inference** — strongly supported by the code but not stated explicitly.
> - **Recommendation** — a proposed guideline, _not_ an existing convention.
>
> The existing code is the source of truth. When a document (including this one,
> or `pages/DOCUMENTATION.md`) disagrees with the code, the code wins.

---

## 1. Project Overview

**Observed.** Oremi Device (package `oremi-device`, version in
`pyproject.toml`, currently `1.0.0b20`) is a Python 3.12 asyncio command-line
application that is the audio endpoint of the Oremi smart-home ecosystem. It:

- captures microphone audio via **miniaudio** (`device/core/audio.py`);
- streams that audio to **Oremi Ohunerin** (wake-word / sound detection) and
  **Oremi Andika** (speech-to-text) over WebSockets;
- sends final transcriptions to **Oremi Akọrin** over HTTP for NLP/command
  orchestration;
- synthesizes responses with **Oremi Izwi** or an OpenAI-compatible
  **Edge-TTS** server;
- plays audio through **ffmpeg -> miniaudio** (`device/core/speaker.py`);
- publishes state, events, controls, and Home Assistant MQTT discovery via
  **paho-mqtt** (`device/core/mqtt.py`);
- exposes a **Model Context Protocol (MCP)** server over streamable HTTP
  (`device/core/mcp.py`, `device/mcp/`).

**Observed** pipeline (a wake word gates the transcription turn; Ohunerin runs
continuously while Andika listens only between the wake word and the final
result):

```text
Microphone
    |
    v
Oremi Device --(audio frames)--> Oremi Ohunerin (wake word / sound detection)
    |
    | wakeword event
    v
Oremi Device --(audio frames)--> Oremi Andika (STT)
    |
    | final transcription
    v
Oremi Akorin (NLP / command orchestration)
    |
    | ProcessingResponse (commands)
    v
Oremi Device -> Oremi Izwi / Edge-TTS (TTS) -> Oremi Device -> Speaker
```

**Observed.** There is no in-process machine-learning model and no database.
All STT/TTS/NLP is performed by external services. The only local persistence
is a JSON runtime-settings cache (see §7).

---

## 2. Architecture

### 2.1 Entry points (Observed)

- `device/__main__.py` -> `main()`: calls `parse_arguments()` then
  `asyncio.run(start())`. Catches `KeyboardInterrupt` (silently) and any
  other exception (logs and `sys.exit(1)`).
- `device/__init__.py` defines `async def start()` and, at module import time,
  executes `app = start()`. That module-level call creates an **un-awaited
  coroutine** and emits a `RuntimeWarning: coroutine 'start' was never awaited`
  whenever `device` is imported (observed test output). It does not start the
  application by itself.
- `DeviceApplication.run()` in `device/core/app.py` is the real orchestrator.
- Console script: `oremi-device = "device.__main__:main"` (`pyproject.toml`).
- Module execution: `python -m device` (used by `.vscode/launch.json` and
  `Dockerfile` CMD).

### 2.2 Orchestration (Observed)

`DeviceApplication` (`device/core/app.py`) owns:

- `self.settings` — the singleton `Settings` from `get_settings()`.
- `self.queues` — a dict of `asyncio.Queue` keyed by event name:
  `device_change`, `microphone_mute`, `speaker_change`, `speaker_mute`,
  `speaker_volume`, `player_play`, `player_stop`, `language_change`,
  `device_context_change`, `processing`, `voice_change`, `transcription`,
  `service_enabled`.
- `self.audio` — an `AudioService` (`device/services/audio_service.py`).
- `self.ha_device` — a `HomeAssistantDevice` MQTT client
  (`device/core/mqtt.py`).
- `self.mcp` — a `FastMCP` server started as a background task.
- `self.tts` — a `TTSManager` (`device/services/tts_manager.py`).
- `self.executor` — a `CommandExecutor` (`device/services/command_executor.py`).
- `self.components` / `self.component_configs` — instances/configs built from
  the `COMPONENTS` registry.
- `self.shared_resources` — a `SharedResources` TypedDict handed to every
  component (see §6.3).
- `self.shutdown_event` — set by SIGINT/SIGTERM (`_setup_signals`) or by
  `shutdown_event.set()` in tests.

`run()` order (Observed): configure logging -> log settings groups -> register
signals -> build `AudioService`, initialize hardware -> build MQTT client ->
build/register MCP and start it -> build `TTSManager` + `CommandExecutor` ->
load components from `COMPONENTS` -> start each component with its config and
`shared_resources` -> wire MQTT callbacks + connect + set availability ->
fetch TTS voices -> publish HA discovery -> start `monitor_devices`,
`_event_loop_processor`, `_geocode_retry_loop` background tasks -> play the
`ready` cue -> **await `shutdown_event`** -> teardown (availability offline,
cancel executor, stop components, play `shutdown` cue, cancel background
tasks, close audio stream, stop speaker, disconnect MQTT).

### 2.3 Component model (Observed)

`device/core/components.py` defines the extension points:

- `Component(Generic[ComponentConfigModel], abc.ABC)` — `name`, `task`,
  `start(config, shared_resources)`, `stop()`.
- `AudioStreamComponent` — adds `needs_audio = True`, `listening_task`, and
  `on_device_changed(new_stream)` / `on_mute_changed(muted)`.
- `HttpComponent` — `needs_audio = False` for HTTP-only services.
- `SharedResources` TypedDict, `ActiveStreamContainer`, `DeviceState`.

`device/components/__init__.py` is the registry:

```python
COMPONENTS: dict[str, tuple[type[BaseModel], type[Component]]] = {
  "ohunerin": (OhunerinConfig, OhunerinComponent),
  "andika":   (AndikaConfig, Speech2Text),
  "akorin":   (AkorinConfig, AkorinComponent),
}
```

> **Observed drift.** The module docstring in `core/components.py` still
> mentions an "Injini" component and describes Andika as an audio-stream
> transcriber. The registry does not contain "Injini", and the STT component
> class is `Speech2Text` (registered under the key/config `"andika"`), which
> is an `AudioStreamComponent`. Trust the registry, not the docstring.

### 2.4 Event loop and cross-thread safety (Observed)

- `_event_loop_processor()` creates one `asyncio.Task` per queue `get()`
  plus a shutdown task, waits with `asyncio.FIRST_COMPLETED`, cancels pending
  tasks, and dispatches `_handle_event(event_type, data)`.
- MQTT callbacks run on the paho network thread and **must** marshal into the
  loop with `self.loop.call_soon_threadsafe(queue.put_nowait, ...)`. This
  pattern is used throughout `_setup_mqtt_callbacks()` and must be preserved.
- Background tasks are appended to `self.background_tasks` and cancelled and
  gathered on shutdown.

### 2.5 Layer boundaries (Observed, with one caveat)

- `device/core/` — transport/device mechanics (audio capture, speaker, MQTT,
  STT controller, detector, listener, TTS abstraction, playback model, MCP
  device model, settings, package).
- `device/components/` — service-specific integrations (Ohunerin, Akorin,
  Izwi, Edge-TTS) and `components/transcribers/` (Andika WS, whisper.cpp).
- `device/services/` — orchestration helpers `AudioService`, `TTSManager`,
  `CommandExecutor`.
- `device/mcp/` — MCP tool/resource/prompt registration.
- `device/utils/` — small shared helpers (`logger`, `context`, `url`).

**Observed caveat.** `device/core/app.py` imports concrete component classes
(`OhunerinComponent`) and service classes directly, and `device/core/stt.py`
lives in `core` but implements the "andika" component. So `core` is not a
strict lower layer; it is a technical package that also contains the STT
controller. Do not assume a clean dependency direction.

---

## 3. Repository Structure

**Observed** (source files only; caches/venv omitted):

```text
AGENTS.md, README.md, CONTRIBUTING.md, LICENSE, LICENSE_HEADER.txt
pyproject.toml, uv.lock, Makefile, devbox.json, compose.yaml, Dockerfile
ruff.toml, .pylintrc, tox.ini, bandit.yaml, .pre-commit-config.yaml
.editorconfig, .env.example, .envrc, .gitlab-ci.yml, .hadolint.yaml
.prettierrc, .tmuxinator.yml, .tmux.conf, .gitattributes, .dockerignore
device/
  __init__.py            # defines async start(); module-level app = start()
  __main__.py            # CLI entry: parse_arguments + asyncio.run(start())
  core/
    app.py               # DeviceApplication orchestrator
    args.py              # argparse (only --version today)
    audio.py             # Audio capture (miniaudio) + device matching
    components.py        # Component / AudioStreamComponent / HttpComponent
    cues.py              # SoundCue / ConversationEvent literals, cue paths
    detector.py          # SoundDetector (Ohunerin detection events)
    geocode.py           # Nominatim geocoding + "unavailable" tracking
    listener.py          # AudioListener (mic frames -> websocket)
    mcp.py               # McpDevice + Pydantic response models
    models.py            # Pydantic config/command/conversation models
    mqtt.py              # HomeAssistantDevice (topics, discovery, state)
    package.py           # APP_NAME/VERSION/DESCRIPTION/URL from pyproject
    playback.py          # PlaybackState / PlaybackQueueItem
    settings.py          # Settings (pydantic-settings) + runtime cache
    speaker.py           # Speaker playback (ffmpeg + miniaudio playback)
    stt.py               # Speech2Text ("andika") + connection/loop control
    timezone.py          # timezonefinder wrapper
    tts.py               # BaseTTSClient, TTSVoice, voices_for_language
  components/
    __init__.py          # COMPONENTS registry
    ohunerin.py          # OhunerinComponent (WebSocket + audio)
    akorin.py            # AkorinClient + AkorinComponent (HTTP)
    izwi.py              # IzwiClient (TTS)
    edge_tts.py          # OpenAIEdgeTTSClient (TTS)
    transcribers/
      base.py            # BaseTranscriber, SupportedModel
      andika_ws.py       # AndikaTranscriber (WebSocket)
      whisper_cpp.py     # WhisperCppListener (HTTP + WAV)
  mcp/
    tools.py             # register_mcp_tools
    resources.py         # register_mcp_resources
    prompts.py           # register_mcp_prompts
  services/
    audio_service.py     # AudioService (mic/speaker lifecycle, device monitor)
    tts_manager.py       # TTSManager (backend client + voice state)
    command_executor.py  # CommandExecutor (execute ProcessingResponse)
  utils/
    logger.py            # configure_logging
    context.py           # build/validate/parse device context
    url.py               # safe_url (redacts credentials)
  sounds/                # bundled .ogg cues + LICENSE.txt
tests/                   # pytest suite (one file per area)
config/                  # mosquitto.conf, ohunerin.json, pulse-client.conf
pages/                   # published docs site (DOCUMENTATION.md is the manual)
scripts/generate-docs-files.py
typings/geopy/           # local type stubs for geopy
```

> **Observed drift.** The pre-existing `AGENTS.md` referenced `bin/` and
> `mosquitto/` directories and a `config/` "example runtime configuration".
> `bin/` and `mosquitto/` do **not** exist; Mosquitto config lives at
> `config/mosquitto.conf`.

Where an agent is most likely to work: `device/core/audio.py`,
`device/core/speaker.py`, `device/core/mqtt.py`, `device/core/app.py`,
`device/core/settings.py`, `device/core/models.py`,
`device/components/*.py`, `device/services/*.py`, and the matching file in
`tests/`.

---

## 4. Core Components

### 4.1 `Audio` — microphone capture (`device/core/audio.py`)

- **Responsibility (Observed):** select an input device and run a miniaudio
  `CaptureDevice`, fan out PCM frames to subscribers.
- **Primary API:** `Audio(dtype="int16", samplerate=16000, blocksize=4000,
device_index=None, device_name=None, loop=None)`; `start_stream()`,
  `stop()`, `close()`, `restart_stream()`; `async __aenter__/__aexit__`
  (reference-counted start/stop); `subscribe() -> asyncio.Queue[bytes]` /
  `unsubscribe(queue)`; `async data(queue=None)`; `is_active()`;
  static helpers `find_compatible_device()`, `find_device_by_name()`,
  `get_compatible_input_devices()`, `is_physical_microphone()`,
  `match_device_name()`.
- **Dependencies:** `miniaudio`.
- **Input:** device list from `miniaudio.Devices().get_captures()`; config
  from `AudioService`.
- **Output:** `bytes` PCM chunks (signed 16-bit little-endian, mono,
  `samplerate`).
- **Important (Observed):**
  - The capture callback runs on miniaudio's thread and marshals frames with
    `self.loop.call_soon_threadsafe(self._publish_audio_data, bytes(data))`.
  - `subscribe()` returns a bounded queue (`maxsize=100`). When at least one
    subscriber exists, frames are delivered **only** to subscriber queues; the
    default `self.audio_queue` is not filled. When a queue is full the oldest
    frame is dropped (`get_nowait` then `put_nowait`).
  - Device selection order: explicit index -> explicit name (a numeric string is
    treated as an index; otherwise fuzzy match) -> `find_compatible_device()`.
  - `blocksize` is stored and reported by `info` but is **not** passed to
    `miniaudio.CaptureDevice` (only `input_format`, `nchannels=1`,
    `sample_rate`, `device_id` are). Resampling from the native rate is done
    by miniaudio when the device's native rate differs.
  - `BLACKLISTED_KEYWORDS` hide virtual/monitor devices; if no physical
    device is found the code falls back to any input device.
- **Exceptions:** `AudioDeviceError` (query failure, invalid index, no
  compatible device, stream init failure).

### 4.2 `AudioListener` — mic -> WebSocket (`device/core/listener.py`)

- **Responsibility (Observed):** subscribe to `Audio`, forward frames to a
  websockets `ClientConnection`.
- **API:** `AudioListener(audio_stream, websocket, stop_message=None)`,
  `async listening()`.
- **Behavior (Observed):** `async with self.audio_stream`; 1.0 s receive
  timeout and 2.0 s send timeout; after 3 consecutive timeouts it calls
  `audio_stream.restart_stream()`; on close it unsubscribes and (if set)
  `asyncio.shield`s a `stop_message`.
- **Important:** websocket sends are awaited on the event loop; PCM is binary
  bytes only (no headers/encoding).

### 4.3 `SoundDetector` — Ohunerin detection events (`device/core/detector.py`)

- **Responsibility (Observed):** parse JSON messages from the Ohunerin
  WebSocket, threshold-filter, publish MQTT events, set the wake-word event.
- **Message shape (Observed, `DetectedSound`):** `type` (`"sound" |
"wakeword"`), `sound` (str), `score` (float), `datetime` (ISO 8601).
- **Publish topic (Observed):** `DETECTION_EVENT_TOPIC = "event"` ->
  `<mqtt_topic>/nodes/<node_id>/event`.
- **API:** `detecting()`, `process_detected_sound(data)`,
  `schedule_clearing_task(data)`, `clear_sound_after_delay(data)`,
  `send_clearing_message(data)`, `terminate()`.
- **Threshold/clearing (Observed):** only `score >= threshold` events are
  processed; wake-word events always publish and set `wakeword_event`; sound
  events are suppressed while the same `sound` is already active; after
  `settings.delay` seconds a retained `"..."` clearing payload is published.
- The publisher argument is duck-typed: it accepts an object with
  `publish_event(topic, payload, retain=...)` (the real `HomeAssistantDevice`)
  or a callable.

### 4.4 `Speech2Text` ("andika") — STT controller (`device/core/stt.py`)

- **Responsibility (Observed):** an `AudioStreamComponent[AndikaConfig]`
  that switches between the Andika WebSocket backend and the whisper.cpp HTTP
  backend, waits for the wake word, opens/closes the transcription turn, and
  publishes partial/final transcriptions.
- **Backends (Observed):** `settings.transcription_backend` is `"andika"` or
  `"whisper.cpp"`; `_run()` dispatches to `_activate_on_wakeword()` or
  `_run_whisper()`.
- **Andika URI (Observed):**
  `ws(s)://{andika_host}:{andika_port}/ws?model=...&samplerate=...&show-words=False&max-alternatives=0&language=...`
  (`wss` when `andika_cert_file` is set).
- **Turn control (Observed):** `_wait_for_activation()` awaits and clears
  `wakeword_event`; `_wait_for_transcription_turn()` waits for the
  transcription-complete event or the listening task with
  `settings.conversation_timeout`; on timeout it emits a `"cancelled"`
  conversation event.
- **Name/alias (Observed):** `name` is `"andika"`; `AndikaComponent` is a
  backward-compatibility alias for `Speech2Text`; `AndikaSupportedModel` is an
  alias for `SupportedModel`.
- **MQTT topics (Observed, via the transcriber):**
  `transcription/partial` and `transcription/result`.
- **whisper.cpp (Observed, `WhisperCppListener`):** captures one utterance
  with RMS-based silence detection
  (`whisper_silence_threshold`, `whisper_silence_duration`), builds a mono
  16-bit WAV, and `POST`s it multipart to `{whisper_url}/inference`.

### 4.5 `Speaker` — playback (`device/core/speaker.py`)

- **Responsibility (Observed):** own output-device selection, volume/mute,
  ducking, and blocking decode+playback via an ffmpeg subprocess feeding a
  miniaudio `PlaybackDevice`.
- **API:** `Speaker(device_name=None, *, volume=1.0, muted=False)`;
  `select_device(name)`, `verify_device()`, `set_volume(v)`,
  `set_muted(b)`; `play_url(url, *, method="GET", body=None, headers=None,
interrupt=True, duckable=True)`; `play_file(path, *, interrupt=False,
duckable=False)`; `stop()`, `pause()`, `resume()`;
  static `get_compatible_output_devices()`; properties `device_name`,
  `info`, `volume`, `muted`, `gain`, `output_channels`; ducking
  `begin_ducking()` / `end_ducking()` / `playback_gain(duckable=...)`.
- **Playback format (Observed):** ffmpeg emits `-f f32le -acodec pcm_f32le
-ac <output_channels> -ar 48000`; `PlaybackDevice` is `FLOAT32`,
  `output_channels` (2 by default), `48000` Hz. Volume/mute/ducking are
  applied in Python by scaling float samples.
- **Important:** `play_url`/`play_file` are **blocking** and must be called
  with `asyncio.to_thread(...)` (as `DeviceApplication.play_sound_cue` and
  `CommandExecutor` do). `pause`/`resume` use POSIX `SIGSTOP`/`SIGCONT`
  on the ffmpeg process. `play_url` rejects non-HTTP(S) URLs, validates HTTP
  methods and header injection, and requires a body for `POST`.
- **Exceptions:** `SpeakerDeviceError`, `SpeakerPlaybackError`.
- **Runtime dependency (Observed):** the `ffmpeg` executable must be on
  `PATH`; the Docker image installs it. Missing ffmpeg raises
  `SpeakerPlaybackError`.

### 4.6 `HomeAssistantDevice` — MQTT (`device/core/mqtt.py`)

- **Responsibility (Observed):** central MQTT client; topic construction;
  retained state publications; full Home Assistant discovery configs; player
  state.
- **API (observed highlights):** `connect()`, `disconnect()`,
  `publish_event()`, `publish_node()`, `publish_discovery_configs(...)`,
  `get_*_topic()` helpers, `set_availability()`, `set_mute_state()`,
  `set_speaker_state()`, `set_speaker_mute_state()`,
  `set_speaker_volume_state()`, `set_player_state()`,
  `set_conversation_state()`, `publish_language_state()`,
  `publish_device_context()`, `publish_device_context_value()`,
  `publish_voice_state()`.
- **Client (Observed):** `paho.mqtt.client.Client(CallbackAPIVersion.VERSION2,
client_id="oremi-device-<node_id>")`; `connect(broker, port, keepalive=0)`
  then `loop_start()`. Username/password are only set when a username is
  present.
- **Topic scheme (Observed):** `<mqtt_topic>/nodes/<node_id>/...`.
  `get_node_id()` returns `oremi-device-<node_id>`.
- **Alias:** `MqttDevice` is a backward-compatibility alias for
  `HomeAssistantDevice`.

### 4.7 `TTSManager` + TTS clients

- **`TTSManager` (`device/services/tts_manager.py`)** selects the backend
  from `tts_backend`: `IzwiClient` when `izwi_url` is set, otherwise
  `OpenAIEdgeTTSClient` when `edge_tts_url` is set, otherwise no client.
  `fetch_voices()` populates `available_voices` and picks the active voice
  via `update_voice_for_language()`. `get_active_voice_names()`,
  `set_voice()`.
- **`BaseTTSClient` / `TTSVoice` / `TTSSynthesisRequest`**
  (`device/core/tts.py`) are the abstraction. `synthesize_request()` returns
  a frozen dataclass describing a request for `Speaker.play_url()` (it does
  not perform I/O).
- **`IzwiClient` (`device/components/izwi.py`):** `GET
{base}/api/tts/voices`; `POST {base}/api/tts/stream` with JSON
  `{text, voice, audio_format: "wav", language?}`.
- **`OpenAIEdgeTTSClient` (`device/components/edge_tts.py`):** `GET
{base}/v1/voices`; `POST {base}/v1/audio/speech` with
  `{model, input, voice, response_format, speed}` and
  `Authorization: Bearer <edge_tts_api_key>`. Voice parsing tolerates several
  metadata shapes.
- **`voices_for_language()`** matches a device language against
  multilingual/auto markers, language names, and `xx-` prefixes.

### 4.8 `CommandExecutor` — command execution

(`device/services/command_executor.py`)

- **Responsibility (Observed):** execute a validated `ProcessingResponse`
  command list in order.
- **Command handling:** `SpeakCommand`/`AnnounceCommand` -> synthesize via
  `TTSManager.current_voice` and `speaker.play_url` in a thread task;
  `PlayCommand` -> stop previous playback and start a new thread task;
  `PlayerCommand` (`stop|pause|resume`) -> speaker control;
  `AlarmCommand`/`ReminderCommand` -> schedule an asyncio task keyed by
  `id`; `CancelScheduledCommand` -> cancel; `SetVolumeCommand`/`MuteCommand`
  -> update speaker and HA state. Volume changes also request the debounced
  confirmation cue through the `volume_feedback` callback supplied by
  `DeviceApplication`.
- **State:** `playback_task`, `speech_task`, `scheduled_tasks`;
  `cancel_active()` stops the speaker and awaits/clears active tasks.

### 4.9 `AudioService` (`device/services/audio_service.py`)

- **Responsibility (Observed):** create/own the `Audio` and `Speaker`
  instances, expose `needs_audio` (= `microphone_enabled`),
  `speaker_enabled`, `audio_stream`, `speaker`, `device_state`,
  `speaker_state`.
- `initialize_hardware()` builds the mic (on `AudioDeviceError` it logs and
  leaves `audio_stream=None`) and then the speaker (non-fatal: logs a warning
  and disables speaker support on `SpeakerDeviceError`). The two are
  independent: a microphone failure must never skip speaker initialization.
- `change_audio_device(target, components)` closes the old stream, creates a
  new `Audio` in a thread, and notifies every `AudioStreamComponent` via
  `on_device_changed(...)` (or `None` on failure).
- `monitor_devices(queue)` polls capture device names every 3.0 s and pushes
  `"__auto_select__"` to the `device_change` queue on change.

### 4.10 MCP surface (`device/core/mcp.py`, `device/mcp/`)

- **Server (Observed, `app.py`):** `FastMCP(name="Oremi Device", host=
settings.server_host, port=settings.server_port, stateless_http=True,
json_response=True, streamable_http_path="/mcp", ...)`, started with
  `mcp.run_streamable_http_async()` as a background task.
- **Registered tools (Observed, `device/mcp/tools.py`):**
  `get_device_status`, `list_voices`, `update_device_settings`,
  `list_output_devices`, `list_input_devices`, `set_active_input_device`,
  `set_active_output_device`, `play_tool`, `pause_tool`, `resume_tool`,
  `stop_tool`, `next_tool`, `previous_tool`, `seek`, `get_volume`,
  `set_volume`, `mute_tool`, `unmute_tool`, `get_queue`, `enqueue`,
  `remove_from_queue`, `clear_queue`, `play_url`, `get_now_playing`,
  `get_device_capabilities`, `sleep_timer_tool`.
- **Registered resources (Observed, `device/mcp/resources.py`):**
  `device:///status`, `device:///settings`, `device:///speakers`,
  `device:///playing`, `device:///queue`, `device:///volume`,
  `device:///capabilities`.
- **Registered prompts (Observed, `device/mcp/prompts.py`):**
  `configure_device`, `adjust_audio`, `play_media`, `pause_playback`,
  `resume_playback`, `stop_playback`, `next_track`, `previous_track`,
  `restart_track`, `set_volume_prompt`, `increase_volume`,
  `decrease_volume`, `mute_speaker`, `unmute_speaker`, `speaker_status`,
  `whats_playing`, `sleep_timer`.
- Mutation tools call `app.apply_settings_updates(...)` so changes are applied
  to running subsystems and persisted to the runtime cache.
- `McpDevice.playback_state` lazily returns the speaker's `PlaybackState` or
  a fallback so MCP works without hardware.

---

## 5. Audio Pipeline (facts, no invented parameters)

All values below are **Observed** in code/tests.

**Capture**

- Library: `miniaudio.CaptureDevice`.
- Format: `int16` (`miniaudio.SampleFormat.SIGNED16`) by default;
  `FORMAT_MAP` also supports `float32` and `int32` if `dtype` is changed.
- Channels: `1` (mono), hard-coded for capture.
- Sample rate: `16000` Hz default (`Audio.samplerate`; `AndikaConfig.samplerate`
  is also `16000`).
- Native device format info (samplerate/channels/format) is captured for
  logging but capture is always requested at the target rate; miniaudio handles
  conversion.
- Block/buffer: `blocksize=4000` is stored and reported but not passed to
  miniaudio.

**Distribution**

- Frames are `bytes` (16-bit PCM). Each subscriber gets its own bounded
  `asyncio.Queue` (`maxsize=100`); on overflow the oldest frame is dropped.
- Reference counting: `Audio.__aenter__` starts the stream when the first
  user enters; `__aexit__` stops it when the last user leaves. Multiple
  components (Ohunerin + Andika) share one capture device this way.

**Transmission to STT/detection**

- Ohunerin: raw PCM frames over `ws(s)://<host>:<port>/ws?features=...&language=...`.
- Andika: raw PCM frames over
  `ws(s)://<host>:<port>/ws?model=...&samplerate=...&show-words=False&max-alternatives=0&language=...`
  and a final `{"eof": 1}` sentinel from `AudioListener.stop_message`.
- whisper.cpp: frames are accumulated into memory, RMS-gated for
  speech/silence, and posted as a mono 16-bit WAV.

**Playback**

- Decoder: `ffmpeg -nostdin -loglevel error -i <source> -f f32le -acodec
pcm_f32le -ac <channels> -ar 48000 pipe:1`.
- Sink: `miniaudio.PlaybackDevice(output_format=FLOAT32, nchannels=2,
sample_rate=48000, device_id=...)` (channels from `Speaker._output_channels`,
  which is 2).
- Volume/mute/ducking are applied in Python to float32 samples. Ducking gain is
  `0.25` for duckable streams.
- Bundled cues are `.ogg` files in `device/sounds/`, resolved by
  `core/cues.get_sound_cue_path(cue)`; the `SoundCue` literal lists all 12.
- `PlaybackState` (`core/playback.py`) maintains a queue, current index,
  simulated position, pause state, and an optional sleep timer for MCP.

---

## 6. Oremi Services Integration

### 6.1 Oremi Ohunerin (wake word + sound detection)

- **Protocol (Observed):** WebSocket client (`websockets.asyncio.client.connect`)
  for detection, plus a synchronous `httpx.get` for the sound list.
- **Endpoint:** `ws(s)://{ohunerin_host}:{ohunerin_port}/ws?features=<comma>&language=<lang>`;
  `/api/sounds` (HTTP) to list sounds.
- **TLS (Observed):** when `ohunerin_cert_file` is set it loads an
  `ssl.SSLContext(PROTOCOL_TLS_CLIENT)` with
  `load_verify_locations(...)` and uses `wss`/`https`.
- **Reconnection (Observed):** `OhunerinComponent._run` loops forever with
  exponential backoff starting at 2.0 s, doubling to a 60 s cap, resetting to
  2.0 s on a successful connection. Cancellation is handled cleanly.
- **Data format:** JSON `DetectedSound` (see §4.3).
- **Error handling (Observed):** `httpx.HTTPStatusError` from
  `/api/sounds` is logged and `[]` is returned; connection errors are logged
  and retried.
- **Config:** `ohunerin_host` (required while the microphone is enabled),
  `ohunerin_port`, `ohunerin_threshold`, `ohunerin_cert_file`,
  `sound_detection_enabled` (ambient sound detection; wake-word detection is
  always active); per-component `OhunerinConfig.features` (default both
  features) and `threshold` (default 0.65).

### 6.2 Oremi Andika (STT)

- **Protocol (Observed):** WebSocket audio streaming + JSON results; HTTP for
  the model list.
- **Endpoint:** `ws(s)://{andika_host}:{andika_port}/ws?...`; `/api/models`
  (HTTP).
- **Data format (Observed, `AndikaTranscriber`):** incoming JSON with either
  `partial` or `text`; final text is stripped; payload is republished to
  MQTT with `ensure_ascii=False` (Unicode preserved) and a
  `MessageExpiryInterval = settings.delay` property at QoS 1.
- **MQTT topics (Observed):** `transcription/partial` (partial only) and
  `transcription/result`.
- **Error handling / timeouts (Observed):** connection or listening failures
  during a turn produce a `"cancelled"` conversation event and trigger the
  voice error handler (error cue plus a localized TTS announcement); the STT
  turn is bounded by `settings.conversation_timeout`.
- **Config:** `transcription_backend` (default `andika`), `andika_host`
  (required when backend is andika), `andika_port`, `andika_cert_file`,
  `andika_model`, `andika_samplerate`.
- **whisper.cpp alternative:** `whisper_url` (required when selected),
  `whisper_silence_threshold`, `whisper_silence_duration`; `POST
{whisper_url}/inference` with `files={"file": ("utterance.wav", wav,
"audio/wav")}` and form fields `language` and `response_format=json`.
- **No retry loop (Observed):** unlike Ohunerin, the Andika transcription turn
  is per-conversation; failures cancel the turn rather than retry.

### 6.3 Oremi Akọrin (NLP orchestration)

- **Protocol (Observed):** HTTP `POST` via `httpx.AsyncClient`.
- **Endpoint (Observed):** `{akorin_url}/api/agent/` (trailing slash is part
  of `AkorinClient.endpoint`).
- **Request body (Observed):**
  `{"message": <text>, "context": {"preferences": <device context>,
"language": <lang>}, "tags": ["device_id:<node_id>"]}`.
  (Note: `pages/DOCUMENTATION.md` shows `language` at the top level and a
  different context shape; the code above is authoritative.)
- **Response (Observed):** validated against `ProcessingResponse` and pushed
  onto the `processing` queue for `CommandExecutor.execute_response`.
- **Timeout:** per-component `AkorinConfig.timeout` (default 30.0 s).
- **Error handling (Observed):** `httpx.HTTPError`/`TimeoutError` and
  `ValidationError`/`ValueError` produce an error cue plus a localized
  `AnnounceCommand` (`ERROR_MESSAGE` for fr/en). Cancellation propagates.
- **Concurrency (Observed):** a new transcription cancels any in-flight
  request; `is_cancellation_request()` skips "stop/cancel" style
  transcriptions. Wait cues are played on `wait_cue_delay` then every
  `wait_cue_interval` while waiting.
- **Disabled when unset (Observed):** if `akorin_url` is `None`,
  `AkorinComponent.start` logs a warning and returns without starting the
  loop. Direct MQTT `processing/result` messages still work.
- **Config:** `akorin_url` (`HttpUrl | None`, default None),
  `AkorinConfig.wait_cue_delay` (2.0), `wait_cue_interval` (4.0),
  `timeout` (30.0), `conversation_history_limit` (12; helpers exist in
  `akorin.py` but history is not yet sent in the request body — Observed).

### 6.4 MQTT broker

- **Client:** paho-mqtt v2 Callback API. `keepalive=0`, `loop_start()`.
- **Auth:** `mqtt_username`/`mqtt_password` optional; password is never
  logged (masked by `log_group`).
- **Reconnect (Observed):** the `disconnect_callback` calls
  `ha_device.connect()` again when the audio stream is active; otherwise it
  logs the disconnect.
- **Subscriptions (Observed, on connect):** microphone select/mute, speaker
  select/mute/volume, player play/stop, `processing/result` (all gated by
  whether audio/speaker are enabled), language, and every device-context
  field; then publishes the retained device-context aggregate.
- **Home Assistant discovery (Observed):** published when
  `mqtt_discovery` is true, under `mqtt_discovery_prefix`; entities share a
  device descriptor keyed by `oremi-device-<node_id>`. Disabled capabilities
  clear their retained configs by publishing an empty payload.

### 6.5 Model Context Protocol (MCP)

- **Transport (Observed):** `streamable_http_path="/mcp"`, `stateless_http=True`,
  `json_response=True`, on `server_host:server_port` (default
  `127.0.0.1:5048`).
- **No authentication (Observed):** the MCP server has no auth layer; the
  default bind is loopback. Treat exposing it beyond loopback as a security
  change requiring review. (**Recommendation:** do not change the default bind
  without explicit need.)

---

## 7. Configuration

### 7.1 Mechanism (Observed)

- `device/core/settings.py` defines `Settings` as a pydantic-settings
  `BaseSettings` with
  `SettingsConfigDict(env_prefix="OREMI_DEVICE_", env_file=".env",
extra="ignore")`.
- Every field maps to `OREMI_DEVICE_<FIELD_UPPERCASED>`; a local `.env` file
  is also read. `.env.example` is the committed sample.
- `get_settings()` is `lru_cache`d and returns `Settings` after applying
  the runtime cache. Tests must call `get_settings.cache_clear()` when
  manipulating the environment (see `tests/test_args.py`).
- Validators: `preferred_currency` is upper-cased and must match
  `^[A-Z]{3}$`; `timezone` must be a valid IANA zone; a model validator
  enforces backend-conditional requirements.
- Errors: `format_settings_errors()` converts Pydantic failures into
  `OREMI_DEVICE_* ...` messages, but it is currently **only used by tests**;
  the CLI catches the `ValidationError` generically and exits 1 (see §9).

### 7.2 Required settings (Observed)

- `node_id` and `mqtt_broker` are always required.
- Microphone-conditional:
  - `ohunerin_host` required when `microphone_enabled` (wake-word detection
    is always active).
  - `andika_host` required when `microphone_enabled`, `andika_enabled`, and
    `transcription_backend == "andika"` (default).
  - `whisper_url` required when `microphone_enabled`, `andika_enabled`, and
    `transcription_backend == "whisper.cpp"`.
- Speaker-conditional:
  - `edge_tts_url` required when `speaker_enabled` and
    `tts_backend == "edge-tts"`.

### 7.3 Defaults and runtime cache (Observed)

Key defaults: `server_host=127.0.0.1`, `server_port=5048`, `language=fr`,
`timezone=UTC`, `temperature_unit=celsius`, `preferred_currency=XAF`,
`measurement_system=metric`, `distance_unit=kilometer`, `time_format=24h`,
`date_format=DD/MM/YYYY`, `first_day_of_week=monday`,
`microphone_enabled=True`, `microphone_muted=False`, `speaker_enabled=True`,
`speaker_volume=1.0`, `delay=3`, `conversation_timeout=15.0`,
`sound_detection_enabled=True`, `ohunerin_port=5023`,
`ohunerin_threshold=0.25`, `andika_enabled=True`,
`transcription_backend=andika`, `andika_port=5022`,
`andika_model=zhifeixie/Mega-ASR`, `andika_samplerate=16000`,
`tts_backend=izwi`, `edge_tts_model=tts-1`,
`edge_tts_response_format=mp3`, `edge_tts_speed=1.0`, `mqtt_port=1883`,
`mqtt_topic=oremi/device`, `mqtt_discovery=True`,
`mqtt_discovery_prefix=homeassistant`, `log_level=INFO`, `log_file=None`.

- `data_path` default is `$XDG_DATA_HOME/oremi-device` (or
  `~/.local/share/oremi-device`); the Docker image sets `/oremi/data`.
  **Observed drift:** `pages/DOCUMENTATION.md` claims a `/oremi/data`
  default; that is the container value, not the library default.
- Runtime cache: `setting_path = data_path / f"{node_id}.json"`. On startup
  `get_settings()` reads it and overrides mutable settings. It is written by
  `update_runtime_settings_cache()` after MQTT/MCP changes. Invalid or
  unreadable caches are logged and ignored. `data/` is git-ignored.

### 7.4 Secrets / never commit (Observed + Recommendation)

- `OREMI_DEVICE_MQTT_PASSWORD` and `OREMI_DEVICE_EDGE_TTS_API_KEY` are
  secrets; `log_group()` masks exactly these two fields as `<set>`/`<unset>`.
- Real `.env` files, TLS certificate/key files, recorded audio, MQTT
  payloads, and the per-node runtime cache contain sensitive or user data.
  **Never commit them.** (The committed `.env.example` uses placeholder
  values only.)
- `compose.yaml` contains a development database key for another Oremi
  service; do not replicate hard-coded credentials and do not copy such values
  into new files or this document.

### 7.5 Documentation/code contradictions to resolve (Observed)

`pages/DOCUMENTATION.md` is partly stale. When touching these areas, prefer
the code and update the docs:

| Documented                                            | Actual code                                                                      |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- | ----- | -------- |
| `OREMI_DEVICE_CERT_FILE`                              | Replaced by `ohunerin_cert_file` and `andika_cert_file`.                         |
| Exit code 2 with formatted validation errors          | `__main__.main` logs and exits 1; `format_settings_errors` is test-only.         |
| MCP tool `list_audio_devices`                         | Actual tools are `list_input_devices` and `list_output_devices`.                 |
| Separate `PauseCommand`/`ResumeCommand`/`StopCommand` | One `PlayerCommand` with `type` in `stop                                         | pause | resume`. |
| Akorin request has top-level `language`               | `language` is nested under `context`.                                            |
| `conversation/continue/set` topic                     | No such topic in code (only `conversation/state`).                               |
| HA sensor `state_topic` `.../events/detection`        | `SoundDetector` publishes to `.../event` (discovery/publish mismatch — see §11). |

---

## 8. Development

All commands below **exist in the repository** unless marked otherwise. This
sandbox could not run `uv` (read-only cache); tests were run successfully with
`.venv/bin/python -m pytest` (169 passed).

**Environment / dependencies** (`Makefile`, `devbox.json`, `pyproject.toml`)

- `make install` — removes `.venv`, creates a Python 3.12 venv via Devbox,
  and runs `uv sync`.
- `make update` — `uv sync --upgrade` + `devbox update` + `prek update`.
- `make outdated`, `make shell` (tmuxinator), `make stop`.
- `uv sync` / `uv lock` — direct uv equivalents; Devbox's shell hook also runs
  `uv sync`.
- Python: 3.12 only (`requires-python = ">=3.12"`; Docker
  `python:3.12-alpine3.21`).

**Run the application**

- `uv run python -m device` (the launch config and Dockerfile use
  `python -m device`).
- `oremi-device` after installation (console script).
- Only CLI flag today is `--version` / `-v` (`device/core/args.py`); there
  is **no** other configuration flag.

**Tests**

- `make tests` -> `uv run pytest tests/ -v`.
- `uv run pytest` (pytest config sets `testpaths = ["tests"]` and
  `asyncio_mode = "auto"`).
- `uv run pytest tests/test_args.py` / `...::test_name`.
- `make coverage` -> `uv run pytest --cov=server` — **Observed bug:** there is
  no `server` package; coverage will not measure `device`. Use
  `uv run pytest --cov=device` instead. (**Recommendation:** fix the Makefile
  target rather than relying on it.)
- `make coverage-html` has the same `--cov=server` issue.

**Formatting / linting / typing / security**

- Ruff config `ruff.toml`: `indent-width = 2`, `line-length = 128`,
  `quote-style = "double"`, `target-version = "py312"`, select
  `E,F,W,RUF` with `fix = true`.
- `make fix` -> `ruff check . --fix`.
- `make lint` -> `devbox run prek run --all-files` (whole repo; use only when
  requested).
- Pre-commit framework (run via `prek`): trailing whitespace, AST/JSON/YAML/
  TOML checks, merge-conflict, debug statements, private-key detection,
  license-header insertion (`LICENSE_HEADER.txt`, current year), import
  reordering, Ruff, mypy (strict; tests excluded; `--ignore-missing-imports`),
  Bandit (`bandit.yaml`), hadolint on the Dockerfile, and a local `tests`
  hook that runs `make tests`.
- `tox.ini` carries flake8/pycodestyle/pydocstyle settings and `.pylintrc`
  is present, but neither flake8 nor pylint is wired into pre-commit. Treat
  `ruff.toml` + mypy as the enforced tools; do not introduce new linters.
- Type stubs for `geopy` live in `typings/geopy/` and are excluded from
  pre-commit.

**Packaging / container**

- `make package` (`uv build --wheel` + `twine check`), `make pypi`,
  `make image` (buildx multi-arch), `make image-test`, `make live`.
- `make bump VERSION=x.y.z`, `alpha`/`beta`/`rc`/`patch`/`minor`/
  `major`, `release`, `publish`.
- Docker: multi-stage Alpine build; `ffmpeg`, `alsa-lib`,
  `pulseaudio-utils`, `tzdata` installed at runtime; `CMD ["python",
"/oremi/device"]`; data volume `/oremi/data`.

**Commands that do NOT exist (Observed)**

- `make test` (singular) — the target is `make tests`.
- `make docs` exists but runs `serve -l 9652 pages/` (local static serve).
- `scripts/generate-docs-files.py` imports `akorin` (a different project)
  and `fastapi`; it does not run in this repository. Do not rely on it.

---

## 9. Testing

- **Framework (Observed):** pytest with `pytest-asyncio` in `auto` mode
  (`pyproject.toml`); `pytest.mark.asyncio` is used on async tests.
- **Layout:** `tests/` mirrors functionality: `test_args.py` (settings),
  `test_audio.py`, `test_speaker.py`, `test_detector.py`,
  `test_init.py` (component URI/registry), `test_andika.py`,
  `test_akorin.py`, `test_mqtt.py`, `test_mcp.py`,
  `test_processing.py` (commands + TTS clients), `test_main.py` (app and
  device-context helpers). 169 tests pass in the current tree.
- **Conventions (Observed):**
  - Helper `_make_settings(**kwargs)` builds `Settings(_env_file=None,
**defaults)` with the required fields and `.env` disabled.
  - `tests/conftest.py` has an **autouse** fixture that monkeypatches
    `device.core.settings.get_location_geocode` so tests never hit the
    network.
  - `tests/test_args.py` clears the `get_settings` lru*cache and deletes
    `OREMI_DEVICE*\*` env vars for isolation.
  - Boundaries are mocked with `unittest.mock.patch` / `MagicMock` /
    `AsyncMock` / `monkeypatch`: `miniaudio.Devices`,
    `miniaudio.CaptureDevice`, `miniaudio.PlaybackDevice`,
    `paho.mqtt.client.Client`, `httpx.AsyncClient.get`,
    `websockets.asyncio.client.connect` (as `device.components.ohunerin.connect`),
    `device.core.app.AudioService`, `HomeAssistantDevice`, `FastMCP`,
    `TTSManager`, `CommandExecutor`.
  - Fake async iterables/websockets are small local classes
    (`AsyncMessages`, `MockWebSocket`, `BlockingWebSocket`,
    `WhisperAudioStub`).
  - `caplog` is used to assert log content; `pytest.mark.parametrize` for
    input matrices.
- **No hardware or network required (Observed):** every device/network access
  is patched or stubbed. Adding a test that actually opens a microphone,
  speaker, broker, or remote service would violate the suite's contract.
- **What needs mocks:** anything touching `miniaudio`, paho MQTT, httpx,
  websockets, geopy/timezonefinder network/geo lookups, and the ffmpeg
  subprocess (the `Speaker` tests patch `miniaudio.PlaybackDevice` and use
  real short values; `ffmpeg` itself is not exercised end-to-end).
- **Commands:** see §8. The pre-commit `tests` hook runs the full
  `make tests`.

---

## 10. Coding Conventions

All items are **Observed** unless marked otherwise.

- **Python version:** 3.12. Do not use syntax newer than 3.12.
- **Indentation / style:** 2 spaces, double quotes, trailing newline, LF
  (`.editorconfig`, `ruff.toml`). Ruff's formatter line length is 128
  (`E501` is ignored in Ruff's lint config, but `tox.ini` mentions 120 for
  flake8, which is not enforced by pre-commit). Follow 128.
- **License header:** every Python file carries the exact
  `LICENSE_HEADER.txt` header; the `insert-license` hook updates the year.
  Do not remove it.
- **Imports:** one name per line, alphabetically ordered, grouped stdlib (with
  `from __future__ import annotations` first when present), then third-party,
  then `device.*` (`reorder-python-imports`). No wildcard imports. The code
  uses `from typing import X` rather than `typing.X`. `from __future__
import annotations` is only present in some modules (`playback.py`,
  `mcp/tools.py`, `core/mcp.py`) — do not add it everywhere.
- **Typing:** annotate new/changed functions and methods. Use PEP 604 unions
  (`str | None`), builtin generics (`dict[str, Any]`, `list[T]`),
  `Literal`, `TypedDict`; abstract interfaces use `abc.ABC` +
  `Generic[...]` rather than `Protocol`; Pydantic v2 models for structured
  data. `ClassVar` for class constants, `property` for computed state.
- **Naming:** `snake_case` functions/variables/modules; `PascalCase` classes;
  `UPPER_SNAKE_CASE` module constants; leading underscore for private
  members. Fields whose lowercase name shadows builtins/config semantics use
  `# pylint: disable=invalid-name` (`id`, `at`, `ok`).
- **Models:** Pydantic v2 `BaseModel` for config/commands/DTOs; discriminated
  unions via `Annotated[..., Field(discriminator="type")]`; `ConfigDict(
extra="forbid")` on `Command` so unknown fields are rejected (see §11).
- **Exceptions:** custom domain exceptions are declared next to the subsystem
  that raises them (`AudioDeviceError`, `SpeakerDeviceError`,
  `SpeakerPlaybackError`). Use `raise ... from error` to chain. Broad
  `except Exception` is used around network/optional paths and logged.
- **Logging:** module-level `logger = logging.getLogger(__name__)`; f-strings
  for messages; `logger.debug/info/warning/error/exception`. Never `print`.
- **Async/sync:** asyncio throughout; blocking audio decode, geocoding, and
  device enumeration run via `asyncio.to_thread(...)`. Long-running tasks are
  created with `loop.create_task(..., name="...")` and registered with
  `handle_task_done`. Use `asyncio.shield` where a cleanup send must
  survive cancellation (`AudioListener`).
- **Docstrings:** triple double-quoted; present on public classes/functions and
  some `TypedDict`s; not universal. `pydocstyle` ignores
  `D101,D102,D103,D212,D400` in `tox.ini`.
- **Comments:** used to explain non-obvious constraints; some section
  separators (`# ── ... ──`) in `command_executor.py`.
- **Backward-compatibility aliases:** `AndikaComponent = Speech2Text`,
  `AndikaSupportedModel = SupportedModel`, `MqttDevice = HomeAssistantDevice`.
  Keep them unless a task explicitly removes them.
- **`# nosec` / `# type: ignore`:** used deliberately (`subprocess` calls,
  `data_path`/`Settings()` construction, the ohunerin component lookup).
  Do not remove without verifying.
- **Commit convention (Observed in `git log`):** Conventional Commits
  `type(scope): description`, lowercase imperative, no trailing period; types
  used include `feat`, `fix`, `refactor`, `perf`, `chore`, `docs`,
  `build`, `style`, `test`. Do **not** create commits unless explicitly
  asked.

---

## 11. Error Handling

**Observed** approach and hot spots:

- **Settings validation:** `Settings()` can raise Pydantic `ValidationError`.
  `DeviceApplication.__init__` calls `get_settings()`, so the exception
  propagates to `main`, which logs `Oremi Device failed to start: ...` and
  `sys.exit(1)`. `format_settings_errors()` (clean `OREMI_DEVICE_*`
  messages) exists but is unused in production. Changing this is a behavior
  change and must update `tests/test_args.py`.
- **Microphone:** `AudioService.initialize_hardware()` logs the
  `AudioDeviceError` and continues with no capture device (components then see
  `stream=None`); speaker initialization still runs afterwards.
- **Speaker:** failure to build/verify the speaker is non-fatal —
  `AudioService` logs a warning, sets `speaker=None` and
  `speaker_enabled=False`.
- **Ohunerin:** reconnect loop with backoff (2->60 s); HTTP sound-list failure
  returns `[]`.
- **Andika/whisper:** per-turn errors are logged, the turn is cancelled, and a
  localized voice error is announced via TTS; whisper errors set the
  transcription-complete event in `finally`.
- **Akorin:** HTTP/timeout/validation errors produce the error cue and a
  localized announce response; the component keeps running.
- **TTS:** `fetch_voices` catches `ValidationError/OSError/ValueError`
  then a broad `Exception`, logging a warning; TTS simply stays unavailable.
- **MQTT:** malformed volume commands and invalid `ProcessingResponse`
  payloads are logged/ignored. `disconnect_callback` reconnects while audio is
  active.
- **Task failures:** `_handle_task_done` calls `task.result()` and logs
  unhandled task exceptions with `logger.exception`.
- **Geocoding:** `get_location_geocode` catches
  `geopy.exc.GeocoderUnavailable`, records the location, and
  `_geocode_retry_loop` retries every 60 s.
- **No global retry policy** for MCP, MQTT publish, or TTS synthesis beyond the
  local behaviors above. (**Recommendation:** if adding retries, keep them
  inside the owning component and respect cancellation.)

---

## 12. Logging and Observability

- **Framework (Observed):** stdlib `logging`, configured once in
  `DeviceApplication.run()` via `device/utils/logger.py:configure_logging`.
- **Console format:** `%(asctime)s - oremi-device - %(levelname)s -
%(message)s`, date `%Y-%m-%d %H:%M:%S`. In **DEBUG** the format is
  `%(name)s - %(levelname)s - %(message)s` (logger name shown instead of the
  app name/date).
- **File logging:** when `log_file` is set, a `RotatingFileHandler`
  (`maxBytes=5_000_000`, `backupCount=5`) is added; parent dirs are created.
- **Levels:** root level from `log_level` (default INFO). Noisy loggers are
  pinned: `watchfiles`, `httpcore.http11`, `httpcore.connection`,
  `websockets.client` -> INFO/WARNING.
- **Startup observability (Observed):** `log_group(...)` logs grouped,
  human-readable settings for Server, Logging, Runtime, Preferences,
  Microphone, Speaker, Wake Word & Sounds Detection, Transcription, Speech,
  Orchestrator, Connectivity.
- **Audio diagnostics (Observed):** `Audio._publish_audio_data` logs DEBUG
  throughput (~every 5 s: bytes/s, approximate Hz mono PCM, chunk count).
- **Secrets:** `log_group` masks `mqtt_password` and `edge_tts_api_key` as
  `<set>`/`<unset>`. `safe_url` (`device/utils/url.py`) redacts URL
  credentials and strips query/fragment for safe logging. Never log raw
  passwords, API keys, certificate contents, audio samples, or full transcribed
  user speech at INFO.
- **MQTT observability (Observed):** retained topics for availability,
  microphone/speaker state, volume, mute, language, device context,
  conversation state, player state, voice, and TTS discovery.
- **Health (Observed):** the Docker `HEALTHCHECK` greps `/proc/1/cmdline` for
  the `python /oremi/device` command.

---

## 13. Important Invariants — DO NOT BREAK

1. **Capture format:** microphone audio is mono signed 16-bit PCM at
   `Audio.samplerate` (default 16000 Hz). Ohunerin and Andika both assume the
   same shared stream. Do not change channels/dtype/rate independently for one
   consumer.
2. **Shared-stream reference counting:** every consumer must acquire the stream
   via `async with self.audio_stream`, populate a private queue with
   `subscribe()`, and `unsubscribe()` in `finally`. Stopping the stream
   while another consumer is active will silently kill its audio.
3. **Subscriber fan-out semantics:** when any subscriber exists, the default
   `Audio.audio_queue` is not fed. A consumer that calls `data()` without
   subscribing will starve.
4. **MQTT thread rule:** paho callbacks run off the event loop. Any queue/task
   interaction from them must go through `loop.call_soon_threadsafe`.
5. **Playback format:** ffmpeg decodes to `f32le / pcm_f32le / 48000 Hz /
Speaker.output_channels`; the `PlaybackDevice` must match. Changing one
   without the other breaks playback.
6. **Never block the event loop:** `Speaker.play_url`/`play_file`,
   `Audio` device enumeration, and geocoding must stay off the loop
   (`asyncio.to_thread`). Note `OhunerinComponent.get_supported_sounds()` and
   `AndikaTranscriber.get_supported_models()` use synchronous `httpx.get`
   and are called during `_publish_discovery`/startup (see §14).
7. **Command contract:** `ProcessingResponse.commands` is a discriminated
   union; `Command` sets `extra="forbid"`. Adding a field to a command
   without updating `device/core/models.py` will reject otherwise-valid
   Akorin responses. Commands execute **in array order**.
8. **MQTT topic scheme:** `<mqtt_topic>/nodes/<node_id>/...`; topic builders
   are the single source of truth in `HomeAssistantDevice`. Discovery uses the
   same scheme. Changing a topic requires updating discovery, the app
   subscriptions, and tests.
9. **Component lifecycle:** components are started during `run()` with
   `shared_resources` and may be stopped and restarted at runtime by the
   Home Assistant service switches or microphone mute. `stop()` must cancel and
   await its own tasks and must be idempotent (see `OhunerinComponent.stop` /
   `Speech2Text.stop`).
10. **SharedResources contract:** keys in `SharedResources`
    (`active_stream_container`, `wakeword_event`, `device_state`,
    `transcription_queue`, `processing_queue`, `language_state`,
    `device_context`, handlers, `voice_error_handler`, `mqtt_publisher`) are
    consumed by name with `.get(...)`. New keys must be optional.
11. **Pipeline ordering:** wake word -> listening cue -> Andika capture ->
    final transcription -> Akorin -> `processing` queue -> `CommandExecutor`.
    Do not make Andika listen before the wake word or reorder command
    execution.
12. **Akorin single in-flight request:** a new transcription cancels the
    previous request; do not run concurrent Akorin requests for one node.
13. **Runtime-settings persistence:** `apply_settings_updates` updates live
    subsystems _and_ writes the cache. Any new mutable setting must be added to
    `SettingsUpdates`/`RuntimeSettingsCache` to persist.
14. **Settings singleton:** `get_settings()` is lru-cached. Tests mutating the
    environment must clear it. Production code should not construct
    `Settings()` directly except in tests.
15. **MCP API:** tool/resource/prompt names are a public contract; changing
    them breaks clients and `tests/test_mcp.py`.
16. **HTTPS certificate handling:** use the per-service
    `ohunerin_cert_file`/`andika_cert_file`; do not reintroduce a single
    `cert_file`.
17. **License headers and import ordering** are enforced; do not hand-format
    against them.

---

## 14. Common Pitfalls (evidence-backed)

- **Blocking calls in async paths (Observed):**
  - `OhunerinComponent.get_supported_sounds()` performs a synchronous
    `httpx.get` and is called from `_publish_discovery()` (async context).
  - `AndikaTranscriber.get_supported_models()` performs a synchronous
    `httpx.get` and is called from `Speech2Text.start()`.
    These can stall the event loop on slow/unreachable hosts. If you touch this
    area, consider `asyncio.to_thread`, but treat it as a behavior change with
    tests.
- **Un-awaited coroutine on import (Observed):** `device/__init__.py`'s
  module-level `app = start()` emits a `RuntimeWarning` on every import and
  creates a throwaway coroutine. Do not copy this pattern; if you refactor it,
  verify `device/__main__.py` and the console script still work.
- **HA discovery/publish topic mismatch (Observed):** sensors are discovered
  with `state_topic = .../events/detection` (`mqtt.py`) but
  `SoundDetector` publishes to `.../event`. Before "fixing" either, check the
  Home Assistant contract and tests; both strings are asserted in different
  tests.
- **Documentation drift (Observed):** `pages/DOCUMENTATION.md` documents
  settings/tools/topics that do not exist (LLM/Ollama, `CERT_FILE`, exit code
  2, `list_audio_devices`, `continue_conversation`, split player commands,
  Akorin request shape). Update the docs in the same change when behavior
  changes.
- **`make coverage` measures the wrong package (`--cov=server`).**
- **`make test` does not exist; use `make tests`.**
- **`scripts/generate-docs-files.py` imports `akorin`/`fastapi`** and is
  not usable here.
- **ffmpeg is a runtime dependency** (`Speaker`); a missing binary surfaces as
  `SpeakerPlaybackError` at first playback, not at startup.
- **MQTT `keepalive=0`** disables paho keep-alive pings; the code relies on
  the paho network loop and its `disconnect_callback` reconnect. Be careful
  when changing connection settings.
- **`processing/result` is only subscribed when `speaker_enabled`** in
  `_setup_mqtt_callbacks`; NLP responses from MQTT will not execute with the
  speaker disabled.
- **Reconnect dedup/race risk (Observed):** `AudioListener` calls
  `restart_stream()` after 3 timeouts while it may itself be holding the
  stream context; `restart_stream` preserves `_active_users` but stops and
  restarts the device. Test any change to this path.
- **Speaker pause/resume are POSIX-only** (`SIGSTOP`/`SIGCONT`) and operate
  on the ffmpeg process; they are best-effort inside `try/except`.
- **`device/sounds/*.ogg` are asserted to exist** by
  `tests/test_speaker.py::test_bundled_sound_cues_exist`; renaming a cue
  requires updating the `SoundCue` literal in `core/cues.py`.
- **`extra="forbid"`** means an unexpected key in an Akorin command fails the
  whole response validation and triggers the error announce.
- **`.env.example` has a duplicated commented `TRANSCRIPTION_BACKEND` line
  and a commented `OREMI_DEVICE_CERT_FILE`** that is not a real setting.
- **`device/core/mcp.py` defines `READ_ONLY`/`MUTATION` that are not used
  there;** `device/mcp/tools.py` defines its own. Avoid duplicating further.
- **`OhunerinComponent.get_supported_sounds()` returns a raw list** from the
  server and is used to build HA discovery options; a bad response can break
  discovery (it is wrapped in a broad `try/except` in `_publish_discovery`).

---

## 15. Workflow for Coding Agents

1. **Read first.** Open the affected implementation, the matching test file,
   and — if the change is user-facing — `pages/DOCUMENTATION.md`. Use
   `grep`/`glob` to find every caller before editing.
2. **Locate the right layer.** Microphone capture -> `core/audio.py` +
   `services/audio_service.py`. Playback -> `core/speaker.py`. MQTT topics/
   discovery -> `core/mqtt.py` + `app.py`. Settings -> `core/settings.py`.
   Commands -> `core/models.py` + `services/command_executor.py`. New service
   -> `components/` + register in `components/__init__.py` + config model +
   settings.
3. **Understand interfaces.** Check the base classes in
   `core/components.py`, the `SharedResources` keys, and the `COMPONENTS`
   registry before adding or changing a component.
4. **Identify affected tests.** Search `tests/` for the module/class/function
   names and for the topic/tool names you are changing.
5. **Make the smallest change** that satisfies the task. Do not refactor
   unrelated code, rename public models, or reformat whole files.
6. **Preserve contracts** from §13 (audio format, topic scheme, command model,
   MCP names, shared resources, threading rules).
7. **Add or update a focused test.** Mock hardware/network boundaries using the
   existing patterns; assert success, failure, and cleanup where relevant.
8. **Run validation:** the focused test, then the full suite
   (`make tests` / `uv run pytest`), then pre-commit on changed files
   (`devbox run prek run`). If a check cannot run, say so explicitly — do not
   claim it passed.
9. **Verify pipeline effects.** For audio changes, confirm the capture format
   and subscriber behavior; for playback changes, confirm the
   ffmpeg/PlaybackDevice format match; for MQTT changes, confirm discovery and
   subscriptions still agree.
10. **Verify integrations** when relevant: Ohunerin reconnect, Andika URI and
    `/api/models`, Akorin request/response shape, Izwi/Edge-TTS endpoints and
    headers, whisper.cpp multipart request.
11. **Update docs** (`pages/DOCUMENTATION.md`) when configuration, MQTT
    topics/payloads, defaults, CLI, or the MCP surface change.
12. **Summarize** files changed, commands run, and residual risk.

---

## 16. Do / Don't

**DO**

- Treat the code as the source of truth; fix documentation drift in the same
  change.
- Preserve the existing module boundaries and the `COMPONENTS` registry.
- Reuse existing abstractions: `Component`/`AudioStreamComponent`/
  `HttpComponent`, `BaseTTSClient`, `BaseTranscriber`, `SharedResources`,
  `SettingsUpdates`, `HomeAssistantDevice` topic builders.
- Keep audio capture mono/16-bit/16 kHz and playback f32le/48 kHz unless the
  task explicitly changes the pipeline, and update all consumers + tests.
- Use `asyncio.to_thread` for blocking audio/network/filesystem work.
- Marshal cross-thread work with `loop.call_soon_threadsafe`.
- Cancel and await tasks you create; use `finally` for resource cleanup
  (queues, websockets, subprocesses).
- Add a focused, deterministic test for every behavior change.
- Keep the license header and import ordering; run `ruff`/pre-commit.
- Mask secrets in logs; never commit secrets, certificates, audio, or real user
  data.
- Use Conventional Commits when (and only when) asked to commit.

**DON'T**

- Don't block the event loop — no synchronous audio, `httpx`/network, or
  `subprocess` calls in async code.
- Don't call `Speaker.play_url`/`play_file` directly on the loop.
- Don't change MQTT topics, payload shapes, command models, or MCP tool names
  without updating discovery, subscriptions, docs, and tests.
- Don't add fields to `Command` subclasses without updating the models (they
  reject unknown fields).
- Don't construct `Settings()` in production code or assume the runtime cache
  is empty.
- Don't introduce `pip`/`requirements*.txt`; use `uv` and regenerate
  `uv.lock` with `uv lock`.
- Don't add a new dependency without a clear need and a `pyproject.toml`
  update.
- Don't add new linters/formatters or reformat unrelated code.
- Don't remove backward-compatibility aliases or `# nosec`/`# type: ignore`
  comments without verifying.
- Don't copy the pre-existing inaccurate claims (LLM/Ollama settings,
  `CERT_FILE`, exit code 2, `make test`, `bin/`, `mosquitto/`) into new
  work.
- Don't expose the MCP server or MQTT broker beyond their configured bind
  without an explicit security review.
- Don't overwrite or revert unrelated changes already in the working tree.
