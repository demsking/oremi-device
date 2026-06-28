Oremi Device captures microphone audio and connects it to Oremi services:

- **Ohunerin** detects wake words and environmental sounds.
- **Andika** transcribes speech after Ohunerin detects a wake word.
- **MQTT** exposes events, device controls, availability, and Home Assistant
  discovery entities.

The application monitors audio hardware while it runs. It can switch to another
compatible microphone when the active device disappears and switch back when a
preferred device becomes available again.

## Requirements

- Python 3.12, or Docker
- An MQTT broker
- Running Ohunerin and either Andika or whisper.cpp
- A microphone unless `OREMI_DEVICE_MICROPHONE_ENABLED=false` is set
- Optional speaker hardware for the MQTT speaker controls

## Installation

### From PyPI with pip

```bash
pip install oremi-device
```

### From PyPI with uv

```bash
uv tool install oremi-device
```

## Quick Start

### Using pip-installed package

After installation, you can run the device directly:

```bash
$ export OREMI_DEVICE_NODE_ID=living-room
$ export OREMI_DEVICE_LANGUAGE=fr
$ export OREMI_DEVICE_LOCATION="Douala, Cameroon"
$ export OREMI_DEVICE_PREFERRED_CURRENCY=XAF
$ export OREMI_DEVICE_OHUNERIN_HOST=localhost
$ export OREMI_DEVICE_ANDIKA_HOST=localhost
$ export OREMI_DEVICE_MQTT_BROKER=localhost

$ oremi-device
```

### Using Docker

The application requires a node ID and the addresses of the Ohunerin,
Andika, and MQTT services:

```bash
docker run --rm -it \
  --network host \
  --device /dev/snd:/dev/snd \
  -v oremi-device-data:/var/lib/oremi-device \
  -e OREMI_DEVICE_NODE_ID=living-room \
  -e OREMI_DEVICE_LANGUAGE=fr \
  -e "OREMI_DEVICE_LOCATION=Douala, Cameroon" \
  -e OREMI_DEVICE_PREFERRED_CURRENCY=XAF \
  -e OREMI_DEVICE_OHUNERIN_HOST=127.0.0.1 \
  -e OREMI_DEVICE_ANDIKA_HOST=127.0.0.1 \
  -e OREMI_DEVICE_MQTT_BROKER=127.0.0.1 \
  demsking/oremi-device
```

`--network host` is used here so the container can reach services bound to the
host. Use Docker service names instead when all services share a Docker
network. PulseAudio installations may also need the PulseAudio socket and
cookie mounted into the container.

### Using Docker Compose

The examples below run Oremi Device with its required services on one Docker
network. They mount `/dev/snd` into the device container so ALSA microphones are
available inside the container and keep Oremi Device runtime settings in the
`oremi-device-data` volume.

Create a minimal Mosquitto configuration first:

```bash
mkdir -p compose/mosquitto
cat > compose/mosquitto/mosquitto.conf <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
```

#### Compose With Andika

Use this stack when transcription is handled by the Oremi Andika WebSocket
service:

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/var/lib/oremi-device
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: andika
      OREMI_DEVICE_ANDIKA_HOST: andika
      OREMI_DEVICE_ANDIKA_PORT: 5315
      OREMI_DEVICE_ANDIKA_MODEL: vosk-model-small-fr-0.22
      OREMI_DEVICE_ANDIKA_SAMPLERATE: 16000
      OREMI_DEVICE_MQTT_BROKER: mosquitto
      OREMI_DEVICE_MQTT_PORT: 1883
      OREMI_DEVICE_MQTT_TOPIC: oremi/device
      OREMI_DEVICE_MQTT_DISCOVERY: 'true'
    depends_on:
      - ohunerin
      - andika
      - mosquitto

  ohunerin:
    image: demsking/oremi-ohunerin:4.0.0b4
    restart: unless-stopped
    ports:
      - '5023:5023'

  andika:
    image: demsking/oremi-andika
    restart: unless-stopped
    ports:
      - '5315:5315'
    volumes:
      - vosk-models:/usr/share/vosk

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    ports:
      - '1883:1883'
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  vosk-models:
```

Save it as `docker-compose.andika.yaml`, then start it:

```bash
docker compose -f docker-compose.andika.yaml up -d
docker compose -f docker-compose.andika.yaml logs -f oremi-device
```

For English, set `OREMI_DEVICE_LANGUAGE=en` and use an English Andika model,
for example `vosk-model-small-en-us-0.15`.

#### Compose With whisper.cpp

Use this stack when transcription is handled by the official whisper.cpp HTTP
server. The `whisper-model` service downloads the French multilingual `base`
model once into the `whisper-models` volume; the `whisper` service then serves
it on `http://whisper:8080`.

Model selection happens in two places:

- `whisper-model` runs `./models/download-ggml-model.sh <model> /models`.
- `whisper` points `-m` at the downloaded `/models/ggml-<model>.bin` file.

Use the multilingual `base` model for French. Use `base.en` only for English;
models ending in `.en` are English-only and should not be used with
`OREMI_DEVICE_LANGUAGE=fr`.

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/var/lib/oremi-device
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: whisper.cpp
      OREMI_DEVICE_WHISPER_URL: http://whisper:8080
      OREMI_DEVICE_WHISPER_SILENCE_THRESHOLD: 500
      OREMI_DEVICE_WHISPER_SILENCE_DURATION: 1.0
      OREMI_DEVICE_MQTT_BROKER: mosquitto
      OREMI_DEVICE_MQTT_PORT: 1883
      OREMI_DEVICE_MQTT_TOPIC: oremi/device
      OREMI_DEVICE_MQTT_DISCOVERY: 'true'
    depends_on:
      - ohunerin
      - whisper
      - mosquitto

  ohunerin:
    image: demsking/oremi-ohunerin:4.0.0b4
    restart: unless-stopped
    ports:
      - '5023:5023'

  whisper-model:
    image: ghcr.io/ggml-org/whisper.cpp:main
    volumes:
      - whisper-models:/models
    command:
      - ./models/download-ggml-model.sh base /models

  whisper:
    image: ghcr.io/ggml-org/whisper.cpp:main
    restart: unless-stopped
    ports:
      - '8080:8080'
    volumes:
      - whisper-models:/models:ro
    command:
      - whisper-server --host 0.0.0.0 --port 8080 -m /models/ggml-base.bin
    depends_on:
      whisper-model:
        condition: service_completed_successfully

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    ports:
      - '1883:1883'
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  whisper-models:
```

Save it as `docker-compose.whisper.yaml`, then start it:

```bash
docker compose -f docker-compose.whisper.yaml up -d
docker compose -f docker-compose.whisper.yaml logs -f whisper oremi-device
```

The first start downloads the model. Later starts reuse the `whisper-models`
volume. To force a different model after changing the Compose file, remove the
volume first:

```bash
docker compose -f docker-compose.whisper.yaml down
docker volume rm "$(basename "$PWD")_whisper-models"
docker compose -f docker-compose.whisper.yaml up -d
```

The server must bind to `0.0.0.0` inside its container. Binding it to
`127.0.0.1` makes it unreachable through Docker's published port. Do not expose
the unauthenticated whisper.cpp HTTP endpoint to an untrusted network.

Oremi Device uses the stock whisper.cpp `/inference` endpoint. After a wake
word, it records until silence or `OREMI_DEVICE_CONVERSATION_TIMEOUT`, sends an
in-memory WAV to `http://whisper:8080/inference`, and publishes the final text
to `transcription/result`. whisper.cpp does not produce Andika-style partial
messages, so no `transcription/partial` messages are published with this
backend.

For English, download and serve `base.en` instead:

```yaml
services:
  whisper-model:
    command: './models/download-ggml-model.sh base.en /models'

  whisper:
    command: 'whisper-server --host 0.0.0.0 --port 8080 -m /models/ggml-base.en.bin -l en'
```

Then set `OREMI_DEVICE_LANGUAGE=en`. Keep using the multilingual `base` model
for French and other non-English languages.

#### Compose With Edge-TTS

Use this stack when spoken responses should be synthesized by the
OpenAI-compatible Edge-TTS container:

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/var/lib/oremi-device
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: andika
      OREMI_DEVICE_ANDIKA_HOST: andika
      OREMI_DEVICE_ANDIKA_PORT: 5315
      OREMI_DEVICE_ANDIKA_MODEL: vosk-model-small-fr-0.22
      OREMI_DEVICE_ANDIKA_SAMPLERATE: 16000
      OREMI_DEVICE_TTS_BACKEND: edge-tts
      OREMI_DEVICE_EDGE_TTS_URL: http://edge-tts:5050
      OREMI_DEVICE_EDGE_TTS_API_KEY: your_api_key_here
      OREMI_DEVICE_EDGE_TTS_LOCALE: fr-FR
      OREMI_DEVICE_MQTT_BROKER: mosquitto
      OREMI_DEVICE_MQTT_PORT: 1883
      OREMI_DEVICE_MQTT_TOPIC: oremi/device
      OREMI_DEVICE_MQTT_DISCOVERY: 'true'
    depends_on:
      - ohunerin
      - andika
      - edge-tts
      - mosquitto

  ohunerin:
    image: demsking/oremi-ohunerin:4.0.0b4
    restart: unless-stopped
    ports:
      - '5023:5023'

  andika:
    image: demsking/oremi-andika
    restart: unless-stopped
    ports:
      - '5315:5315'
    volumes:
      - vosk-models:/usr/share/vosk

  edge-tts:
    image: travisvn/openai-edge-tts:latest
    restart: unless-stopped
    ports:
      - '5050:5050'
    environment:
      API_KEY: your_api_key_here
      PORT: 5050

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    ports:
      - '1883:1883'
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  vosk-models:
```

Save it as `docker-compose.edge-tts.yaml`, then start it:

```bash
docker compose -f docker-compose.edge-tts.yaml up -d
docker compose -f docker-compose.edge-tts.yaml logs -f edge-tts oremi-device
```

Use a locale matching `OREMI_DEVICE_LANGUAGE`, for example `fr-FR` for French
or `en-US` for English. The Edge-TTS API key only needs to match the `API_KEY`
configured on the Edge-TTS service.

## Configuration

Configuration is loaded from environment variables with the `OREMI_DEVICE_` prefix.
Values may be placed in a `.env` file in the working directory. Environment variables
take precedence over `.env` values.

### Required Settings

- **`OREMI_DEVICE_NODE_ID`** – Unique node identifier used in MQTT device topics.
- **`OREMI_DEVICE_OHUNERIN_HOST`** – Ohunerin server host or IP address.
- **`OREMI_DEVICE_MQTT_BROKER`** – MQTT broker host or IP address.

The transcription backend has one additional required setting:

- **`andika` backend**: `OREMI_DEVICE_ANDIKA_HOST` – Andika server host or IP address.
- **`whisper.cpp` backend**: `OREMI_DEVICE_WHISPER_URL` – whisper.cpp HTTP server base URL.

### Optional Settings

#### Audio Hardware

- **`OREMI_DEVICE_MICROPHONE_DEVICE_INDEX`** – Preferred microphone index. Default: Auto.
- **`OREMI_DEVICE_MICROPHONE_DEVICE`** – Preferred microphone name; takes precedence over the index. Default: Auto.
- **`OREMI_DEVICE_MICROPHONE_ENABLED`** – Enable microphone initialization and audio capture. Default: `true`.
- **`OREMI_DEVICE_SPEAKER_ENABLED`** – Enable speaker initialization and MQTT speaker controls. Default: `true`.
- **`OREMI_DEVICE_DATA`** – Directory used to persist runtime settings changed through
  MQTT/Home Assistant controls. Oremi Device stores them in `<node-id>.json` inside this directory.
  Default: `$XDG_DATA_HOME/oremi-device`, or `~/.local/share/oremi-device` when `XDG_DATA_HOME` is unset.
  The Docker image sets this to `/var/lib/oremi-device`.

#### Transcription

- **`OREMI_DEVICE_TRANSCRIPTION_BACKEND`** – Transcriber: `andika` or `whisper.cpp`. Default: `andika`.
- **`OREMI_DEVICE_DELAY`** – Sound-event cooldown in seconds and transcription message expiry interval. Default: `3`.
- **`OREMI_DEVICE_CONVERSATION_TIMEOUT`** – Maximum seconds to wait for a final transcription after a wake word. Default: `15`.

#### Device Context

These preferences are published as a retained MQTT device-context document and
are exposed through Home Assistant controls when MQTT discovery is enabled.
Services that need user preferences can subscribe to the context topic and
react when it changes.

- **`OREMI_DEVICE_LANGUAGE`** – Processing language; supported values are `fr` and `en`. Default: `fr`.
- **`OREMI_DEVICE_LOCATION`** – Free-form address or place description for the device. Default: empty.
  The retained device-context timezone is inferred from this value and falls back to `Africa/Douala`.
- **`OREMI_DEVICE_TEMPERATURE_UNIT`** – Preferred temperature unit: `celsius` or `fahrenheit`. Default: `celsius`.
- **`OREMI_DEVICE_PREFERRED_CURRENCY`** – Preferred ISO 4217 currency code. Default: `XAF`.
- **`OREMI_DEVICE_MEASUREMENT_SYSTEM`** – Preferred measurement system: `metric` or `imperial`. Default: `metric`.
- **`OREMI_DEVICE_DISTANCE_UNIT`** – Preferred distance unit: `kilometer` or `mile`. Default: `kilometer`.
- **`OREMI_DEVICE_TIME_FORMAT`** – Preferred time format: `12h` or `24h`. Default: `24h`.
- **`OREMI_DEVICE_DATE_FORMAT`** – Preferred date format: `DD/MM/YYYY`, `MM/DD/YYYY`, or `YYYY-MM-DD`. Default: `DD/MM/YYYY`.
- **`OREMI_DEVICE_FIRST_DAY_OF_WEEK`** – Preferred first day of week: `monday`, `sunday`, or `saturday`. Default: `monday`.

#### Ohunerin Wake Word

- **`OREMI_DEVICE_OHUNERIN_PORT`** – Ohunerin server port. Default: `5023`.
- **`OREMI_DEVICE_OHUNERIN_THRESHOLD`** – Minimum accepted Ohunerin confidence score. Default: `0.65`.

#### Andika Transcription

- **`OREMI_DEVICE_ANDIKA_PORT`** – Andika server port. Default: `5315`.
- **`OREMI_DEVICE_ANDIKA_MODEL`** – Vosk model identifier sent to Andika. Default: `vosk-model-small-fr-0.22`.
- **`OREMI_DEVICE_ANDIKA_SAMPLERATE`** – Audio sample rate sent to Andika. Default: `16000`.

#### whisper.cpp Transcription

- **`OREMI_DEVICE_WHISPER_URL`** – whisper.cpp server URL; required for the `whisper.cpp` backend. Default: Unset.
- **`OREMI_DEVICE_WHISPER_SILENCE_THRESHOLD`** – PCM RMS level above which whisper.cpp capture counts as speech. Default: `500`.
- **`OREMI_DEVICE_WHISPER_SILENCE_DURATION`** – Seconds of silence that finish a whisper.cpp utterance. Default: `1.0`.

#### Speech Synthesis

- **`OREMI_DEVICE_TTS_BACKEND`** – Speech synthesis backend: `izwi` or `edge-tts`. Default: `izwi`.

##### Oremi Izwi

- **`OREMI_DEVICE_IZWI_URL`** – Oremi Izwi base URL. When unset, speech synthesis and voice discovery are disabled. Default: Unset.

##### Edge-TTS

- **`OREMI_DEVICE_EDGE_TTS_URL`** – OpenAI-compatible Edge-TTS base URL; required when `OREMI_DEVICE_TTS_BACKEND=edge-tts`. Default: Unset.
- **`OREMI_DEVICE_EDGE_TTS_API_KEY`** – Bearer token sent to Edge-TTS. Default: `your_api_key_here`.
- **`OREMI_DEVICE_EDGE_TTS_LOCALE`** – Edge voice locale requested from `/v1/voices`. Default: `fr-FR` for French and `en-US` for English.
- **`OREMI_DEVICE_EDGE_TTS_MODEL`** – Model value sent to `/v1/audio/speech`. Default: `tts-1`.
- **`OREMI_DEVICE_EDGE_TTS_RESPONSE_FORMAT`** – Audio format requested from Edge-TTS: `mp3`, `opus`, `aac`, `flac`, `wav`, or `pcm`. Default: `mp3`.
- **`OREMI_DEVICE_EDGE_TTS_SPEED`** – Speech speed sent to Edge-TTS. Default: `1.0`.

#### MQTT

- **`OREMI_DEVICE_MQTT_PORT`** – MQTT broker port. Default: `1883`.
- **`OREMI_DEVICE_MQTT_USERNAME`** – MQTT username. Default: Unset.
- **`OREMI_DEVICE_MQTT_PASSWORD`** – MQTT password. Default: Unset.
- **`OREMI_DEVICE_MQTT_TOPIC`** – Base topic for events, availability, and controls. Default: `oremi/device`.
- **`OREMI_DEVICE_MQTT_DISCOVERY`** – Enable Home Assistant MQTT discovery. Default: `true`.
- **`OREMI_DEVICE_MQTT_DISCOVERY_PREFIX`** – Home Assistant discovery topic prefix. Default: `homeassistant`.

#### Security

- **`OREMI_DEVICE_CERT_FILE`** – CA certificate for TLS connections to Oremi services. Default: Unset.

Positive numeric values and valid port ranges are checked at startup. Boolean
values accept standard forms such as `true` and `false`. For example, a `.env`
file for a device without local audio hardware can contain:

```dotenv
OREMI_DEVICE_NODE_ID=living-room
OREMI_DEVICE_LANGUAGE=fr
OREMI_DEVICE_LOCATION=Douala, Cameroon
OREMI_DEVICE_TEMPERATURE_UNIT=celsius
OREMI_DEVICE_PREFERRED_CURRENCY=XAF
OREMI_DEVICE_MEASUREMENT_SYSTEM=metric
OREMI_DEVICE_DISTANCE_UNIT=kilometer
OREMI_DEVICE_TIME_FORMAT=24h
OREMI_DEVICE_DATE_FORMAT=DD/MM/YYYY
OREMI_DEVICE_FIRST_DAY_OF_WEEK=monday
OREMI_DEVICE_OHUNERIN_HOST=ohunerin
OREMI_DEVICE_ANDIKA_HOST=andika
OREMI_DEVICE_TTS_BACKEND=edge-tts
OREMI_DEVICE_EDGE_TTS_URL=http://edge-tts:5050
OREMI_DEVICE_EDGE_TTS_API_KEY=your_api_key_here
OREMI_DEVICE_MQTT_BROKER=mqtt
OREMI_DEVICE_MICROPHONE_ENABLED=false
OREMI_DEVICE_SPEAKER_ENABLED=false
```

Missing or invalid settings stop startup with exit code `2`. The application
prints only actionable environment-variable errors; it does not expose raw
setting values, Pydantic diagnostics, or a Python traceback:

```text
oremi-device: configuration error
  - OREMI_DEVICE_OHUNERIN_HOST is required
  - OREMI_DEVICE_ANDIKA_HOST is required
  - OREMI_DEVICE_NODE_ID is required
  - OREMI_DEVICE_MQTT_BROKER is required
```

## Runtime Behavior

At startup, Oremi Device:

1. Loads and validates the environment settings.
2. Initializes the preferred microphone and speaker when enabled.
3. Connects to MQTT and subscribes to this node's control topics.
4. Starts the Ohunerin and Andika components with their configured settings.
5. Streams microphone audio continuously to Ohunerin.
6. Starts streaming audio to Andika after a wake-word event and stops after
   Andika returns a final transcription or the conversation timeout expires.

Ohunerin and Andika reconnect with exponential backoff when their WebSocket
connections fail. The application also polls for audio-device changes and
updates Home Assistant discovery options when devices appear or disappear.

The microphone mute control pauses audio streaming without stopping the service
connections. A language command updates the retained MQTT state and reconnects
Ohunerin with the newly selected language. Device-context commands update the
retained context document so subscribing services can immediately react to
preference changes.

## MQTT

All MQTT topics use the prefix `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/`
for device-specific communication. Wildcard subscriptions use `+` in place of
the node ID where appropriate.

### Events

#### Sound Event

Detected sounds from the environment, including both wake words and ambient sounds.

- **Topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/event`
- **Retained:** No
- **QoS:** 0

**Model:**

```typescript
interface SoundEvent {
  /** Event discriminator: 'sound' or 'wakeword' */
  type: 'sound' | 'wakeword';
  /** Detected ambient sound or wake-word name, converted to lowercase slug */
  sound: string;
  /** Detection confidence score (0.0 to 1.0) */
  score: number;
  /** ISO 8601 date-time when the sound was detected */
  date: string;
}
```

**Examples:**

Ambient sound event:

```json
{
  "type": "sound",
  "sound": "baby-cry-infant-cry",
  "score": 0.91,
  "date": "2026-06-19T12:04:10.123456"
}
```

Wake-word event:

```json
{
  "type": "wakeword",
  "sound": "oremi",
  "score": 1.0,
  "date": "2026-06-19T12:05:22.654321"
}
```

**Notes:**

- Wake-word events activate Andika transcription for the following speech.
- Home Assistant's wake-word and ambient-sound sensors subscribe to `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/event` and select messages by their `type` field.
- After the configured delay expires, the service publishes a retained clearing message with `"sound": "..."` when no event of that type remains active.

#### Partial Transcription

Incremental transcription results while speech is being captured. **This event is only available when using the `andika` transcription backend.**

- **Topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/transcription/partial`
- **Retained:** No
- **QoS:** 1

**Model:**

```typescript
interface PartialTranscription {
  /** Incrementally transcribed text as speech is captured */
  partial: string;
}
```

**Example:**

```json
{
  "partial": "turn on the living room light"
}
```

**Notes:**

- Published continuously during speech capture as the transcription is refined.
- Only supported when `OREMI_DEVICE_TRANSCRIPTION_BACKEND` is set to `andika`.
- Subscribers can subscribe to `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/transcription/partial` to receive partial results from all nodes.

#### Final Transcription

The final, complete transcription result after speech capture completes.

- **Topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/transcription/result`
- **Retained:** No
- **QoS:** 1

**Model:**

```typescript
interface FinalTranscription {
  /** Final transcribed text after speech capture completes */
  text: string;
}
```

**Example:**

```json
{
  "text": "turn on the living room light"
}
```

**Notes:**

- Published once when speech capture ends and transcription is finalized.
- This is also the Home Assistant transcription sensor state topic.
- Subscribers can subscribe to `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/transcription/result` to receive final results from all nodes.

See the [Andika models documentation](https://demsking.gitlab.io/oremi-andika/#models/) for details about the [PartialResult](https://demsking.gitlab.io/oremi-andika/#models/PartialResult) and [FinalResult](https://demsking.gitlab.io/oremi-andika/#models/FinalResult) models.

---

#### Conversation State

The current lifecycle state of the device's conversation handling.

- **Topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/conversation/state`
- **Retained:** Yes
- **QoS:** 1

**States:**

- **`idle`** – No conversation is active. Cancellation cue when listening times out or produces no usable speech.
- **`listening`** – A wake word was detected and Andika is capturing the request. Listening confirmation cue.
- **`processing`** – A final transcription was published and the device is waiting for NLP. Thinking cue.
- **`speaking`** – Izwi speech is playing for a response, announcement, alarm, or reminder. Announcements first play a notification cue.

**Example:**

```text
idle
```

**State Transitions:**

A normal spoken interaction follows:

```text
idle -> listening -> processing -> speaking -> idle
```

An empty transcription or listening timeout follows:

```text
listening -> idle
```

**Notes:**

- Media is temporarily ducked while cues and speech play; the configured volume and its MQTT state do not change.
- `set_volume` commands play a short feedback tick after applying the new volume.
- The device plays a ready cue after MQTT and all configured components have started and availability is published as `online`.
- During graceful shutdown it stops capture and active playback, publishes availability as `offline`, plays a shutdown cue, and then disconnects from MQTT.
- The bundled cues come from Kenney's [Interface Sounds](https://kenney.nl/assets/interface-sounds) pack, released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). The exact source-file mapping and license are included in `oremi_device/sounds/LICENSE.txt`.

### NLP Integration

An external NLP service can publish a response to the same node's `processing/result` topic:

- Topic: `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/processing/result`

A response containing only `message` is spoken with the active speech synthesis voice:

```json
{
  "message": "Il est 13h30"
}
```

#### NLP Response Model

```typescript
interface NLPResponse {
  /** Optional text for clients and logs */
  message?: string;
  /** Optional commands array for explicit device behavior */
  commands?: Command[];
}

type Command =
  | SpeakCommand
  | AnnounceCommand
  | PlayCommand
  | PauseCommand
  | ResumeCommand
  | StopCommand
  | AlarmCommand
  | ReminderCommand
  | CancelScheduledCommand
  | SetVolumeCommand
  | MuteCommand
  | SetVoiceCommand;
```

For explicit device behavior, include a `commands` array. Commands execute in array order. When the array is present, the device does not automatically speak the top-level `message`; add a `speak` or `announce` command when speech is required. Unknown command types and unknown fields are rejected.

```json
{
  "message": "Optional text for clients and logs",
  "commands": [
    { "type": "speak", "text": "Lecture de votre station" },
    { "type": "play", "url": "https://radio.example/live.mp3" }
  ]
}
```

#### Command Models

```typescript
/** Synthesizes a conversational response while ducking active media */
interface SpeakCommand {
  type: 'speak';
  /** Text to synthesize */
  text: string;
  /** Optional voice name (defaults to active voice) */
  voice?: string;
}

/** Synthesizes a foreground announcement while ducking active media */
interface AnnounceCommand {
  type: 'announce';
  /** Text to synthesize */
  text: string;
  /** Optional voice name (defaults to active voice) */
  voice?: string;
}

/** Interrupts current playback and plays a media URL */
interface PlayCommand {
  type: 'play';
  /** HTTP or HTTPS audio URL */
  url: string;
}

/** Pauses current playback */
interface PauseCommand {
  type: 'pause';
}

/** Resumes paused playback */
interface ResumeCommand {
  type: 'resume';
}

/** Stops current playback */
interface StopCommand {
  type: 'stop';
}

/** Schedules an announcement followed by an optional alarm media URL */
interface AlarmCommand {
  type: 'alarm';
  /** Unique identifier (letters, digits, underscores, hyphens, max 64 chars) */
  id: string;
  /** Timezone-aware ISO 8601 timestamp */
  at: string;
  /** Optional announcement message */
  message?: string;
  /** Optional alarm media URL */
  url?: string;
  /** Optional voice name (defaults to active voice) */
  voice?: string;
}

/** Schedules a spoken announcement */
interface ReminderCommand {
  type: 'reminder';
  /** Unique identifier (letters, digits, underscores, hyphens, max 64 chars) */
  id: string;
  /** Timezone-aware ISO 8601 timestamp */
  at: string;
  /** Announcement message */
  message: string;
  /** Optional voice name (defaults to active voice) */
  voice?: string;
}

/** Cancels an alarm or reminder with the matching ID */
interface CancelScheduledCommand {
  type: 'cancel_scheduled';
  /** ID of the scheduled item to cancel */
  id: string;
}

/** Sets speaker volume to an integer percentage from 0 to 100 */
interface SetVolumeCommand {
  type: 'set_volume';
  /** Volume percentage (0-100) */
  volume: number;
}

/** Mutes or unmutes the speaker */
interface MuteCommand {
  type: 'mute';
  /** true to mute, false to unmute */
  muted: boolean;
}

/** Selects a voice available for the active device language */
interface SetVoiceCommand {
  type: 'set_voice';
  /** Voice name matching the active device language */
  voice: string;
}
```

`voice` defaults to the active voice. A command-specific voice must exist in the configured speech synthesis backend's voice list. The Home Assistant voice selector and `set_voice` only accept voices matching the active device language.

##### Speech And Playback

Use `speak` for conversational responses and `announce` for notifications. Both play over active media. While speech is playing, the device temporarily reduces the media stream to 25% of its current gain so the message remains clear. Speech itself uses the normal speaker gain. The configured volume and its MQTT/Home Assistant state do not change, and media gain is restored even when synthesis fails or playback is canceled. Spoken alarms and reminders use the same ducking behavior.

```json
{
  "commands": [
    { "type": "set_volume", "volume": 60 },
    { "type": "announce", "text": "La porte d'entrée est ouverte" }
  ]
}
```

Player commands can be combined in the same ordered array, although `pause` and `resume` are normally sent as separate responses while media is playing.

##### Alarms And Reminders

The `at` field must be a timezone-aware ISO 8601 timestamp. An alarm or reminder scheduled in the past runs as soon as the command is processed. IDs contain letters, digits, underscores, or hyphens and are at most 64 characters. Sending another `alarm` or `reminder` with the same ID replaces the previous schedule.

```json
{
  "commands": [
    {
      "type": "alarm",
      "id": "weekday-morning",
      "at": "2026-06-23T07:00:00+02:00",
      "message": "Il est sept heures",
      "url": "https://media.example/alarm.mp3"
    },
    {
      "type": "reminder",
      "id": "medicine",
      "at": "2026-06-23T18:30:00+02:00",
      "message": "N'oubliez pas de prendre votre médicament"
    }
  ]
}
```

Cancel either scheduled item by ID:

```json
{
  "commands": [{ "type": "cancel_scheduled", "id": "medicine" }]
}
```

Schedules are held in device memory and are lost when the process restarts. The NLP service should retain or recreate schedules when persistence is required.

Invalid JSON, unavailable voices, naive timestamps, values outside their documented ranges, and non-HTTP media URLs are rejected. Izwi speech uses the `/api/synthesize/stream` endpoint: short requests use GET query parameters, while long requests use a POST JSON body. Edge-TTS speech uses its OpenAI-compatible `/v1/audio/speech` endpoint with Bearer authentication. The active voice defaults to the first available voice matching the device language.

### Device Controls

Node availability is retained at `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/available` with an `online` or `offline` payload.

#### Device Context

- **Aggregate state topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/context/state`
- **Aggregate payload:** Retained JSON object containing `language`, `location`,
  `timezone`, `temperature_unit`, `preferred_currency`, `measurement_system`,
  `distance_unit`, `time_format`, `date_format`, and `first_day_of_week`.
- **Field command topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/context/<field>/set`
- **Field state topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/context/<field>/state`
- **Text fields:** `location`, `timezone`, and `preferred_currency`.
- **Select fields:** `language`, `temperature_unit`, `measurement_system`,
  `distance_unit`, `time_format`, `date_format`, and `first_day_of_week`.

The legacy language topics, `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/language/set`
and `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/language/state`, are
still accepted and updated for compatibility. Home Assistant discovery exposes
language through the device-context control.

Example aggregate payload:

```json
{
  "language": "fr",
  "location": "12 Rue de Rivoli, Paris",
  "timezone": "Europe/Paris",
  "temperature_unit": "celsius",
  "preferred_currency": "EUR",
  "measurement_system": "metric",
  "distance_unit": "kilometer",
  "time_format": "24h",
  "date_format": "DD/MM/YYYY",
  "first_day_of_week": "monday"
}
```

#### Voice

- **Command topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/voice/set`
- **State topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/voice/state`
- **Payload:** A speech synthesis voice matching the active device language.

#### Microphone

- **Select command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/microphone/set`
- **Select state:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/microphone/state`
- **Select payload:** A microphone name exposed by discovery.
- **Mute command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/microphone/mute/set`
- **Mute state:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/microphone/mute/state`
- **Mute payload:** `ON` mutes capture; `OFF` unmutes it.

#### Speaker

- **Select command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/set`
- **Select state:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/state`
- **Select payload:** A speaker name exposed by discovery.
- **Mute command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/mute/set`
- **Mute state:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/mute/state`
- **Mute payload:** `ON` mutes the speaker; `OFF` unmutes it.
- **Volume command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/volume/set`
- **Volume state:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/speaker/volume/state`
- **Volume payload:** Integer percentage from `0` to `100`.

#### Player

- **Play command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/player/play/set`
- **State topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/player/state`
- **Play payload:** An HTTP or HTTPS audio URL; state is `playing` or `idle`.
- **Stop command:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/player/stop/set`
- **Stop payload:** Any payload stops playback.

For example, disable processing for this node with:

```bash
mosquitto_pub \
  -t oremi/device/nodes/living-room/microphone/mute/set \
  -m ON
```

## Logging

Logging is configured only through environment variables:

**Environment Variables:**

- `LOG_LEVEL` – Logging severity level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Invalid values fall back to `INFO`. Default: `INFO`
- `LOG_FILE` – File path for log output. Must be writable by the process. Default: Standard error (stderr)

**Example:**

```bash
$ export LOG_LEVEL=DEBUG
$ export LOG_FILE=/var/log/oremi-device.log
$ export OREMI_DEVICE_NODE_ID=living-room
$ export OREMI_DEVICE_OHUNERIN_HOST=localhost
$ export OREMI_DEVICE_ANDIKA_HOST=localhost
$ export OREMI_DEVICE_MQTT_BROKER=localhost

$ oremi-device
```

**Docker example:**

```bash
docker run --rm -it \
  --network host \
  --device /dev/snd:/dev/snd \
  -v oremi-device-data:/var/lib/oremi-device \
  -e LOG_LEVEL=DEBUG \
  -e LOG_FILE=/var/log/oremi-device.log \
  -e OREMI_DEVICE_NODE_ID=living-room \
  -e OREMI_DEVICE_OHUNERIN_HOST=127.0.0.1 \
  -e OREMI_DEVICE_ANDIKA_HOST=127.0.0.1 \
  -e OREMI_DEVICE_MQTT_BROKER=127.0.0.1 \
  -v /var/log:/var/log \
  demsking/oremi-device
```

**Notes:**

- Setting `LOG_LEVEL=DEBUG` provides verbose output useful for troubleshooting
- When using Docker, ensure the log directory is mounted with `-v` to persist logs outside the container
- If `LOG_FILE` points to a directory that doesn't exist, the process will fail to start

## Home Assistant

MQTT discovery is enabled by default. On MQTT connection, Oremi Device publishes
retained discovery configurations below `homeassistant` for:

- device context controls for language, location, timezone, units, currency,
  date/time preferences, and first day of week
- speech synthesis voice selection, filtered by the active language when a TTS
  backend is configured
- microphone selection and mute state
- speaker selection, mute state, and volume
- Ohunerin wake-word and sound sensors
- Andika transcription sensor

The entities share one device identifier derived from
`OREMI_DEVICE_NODE_ID`. Available microphones and speakers are included as
select options. When microphone or speaker support is disabled, the
corresponding retained discovery configs are cleared.

Set `OREMI_DEVICE_MQTT_DISCOVERY=false` to disable discovery or set
`OREMI_DEVICE_MQTT_DISCOVERY_PREFIX` when Home Assistant uses a custom prefix.
Changes made through the discovered Home Assistant controls are cached by
Oremi Device and applied on restart. The cache includes language, device
context preferences, microphone device and mute state, speaker device, speaker
mute and volume, and speech synthesis voice. Mount the data directory or set
`OREMI_DEVICE_DATA` to a persistent path when running in a container.
The transcription sensor follows the node's `transcription/result` topic and
extracts its state from the final JSON payload's `text` field.

### Media Player

Home Assistant does not provide a native MQTT media-player platform. To expose
Oremi as a real `media_player` with the `speaker` device class, install the
bundled integration by copying `custom_components/oremi_device` into the Home
Assistant configuration directory and restart Home Assistant:

1. **Download the archive**: Download the latest pre-packaged integration from
   [here](https://demsking.gitlab.io/oremi-device/oremi-device-homeassistant.zip).

2. Extract the archive and copy the `oremi_device` folder to your Home Assistant
   configuration directory under `custom_components/oremi_device` (ensure the
   target folder uses an underscore, not a hyphen).

   Alternatively, you can copy it manually from the cloned repository:

   ```bash
   cp -r integrations/home-assistant/oremi_device /path/to/your/homeassistant/config/custom_components/oremi_device
   ```

3. Restart Home Assistant.

With the default `oremi/device` MQTT topic, the integration discovers each
running node and Home Assistant offers it for setup. For a custom base topic,
add **Oremi Device Player** from **Settings > Devices & services**, then enter
the node ID and MQTT base topic.

The resulting `media_player` supports Home Assistant TTS and audio media-source
URLs, stop, mute, and volume controls. Playback requires `ffmpeg`; it is included
in the Docker image and must be installed separately when running from source.

## Development

Oremi Device is built with Python and uses `uv` for dependency management. The
project follows standard Python development practices with type hints, linting,
and automated testing.

For detailed information on setting up your development environment, running
tests, code style guidelines, and the pull request process, please refer to
[CONTRIBUTING.md](https://gitlab.com/demsking/oremi-device/-/blob/main/CONTRIBUTING.md).

## Versioning

Oremi Device project adheres to [Semantic Versioning](https://semver.org/)
(SemVer). Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

The current version can be found by running:

```bash
docker run --rm demsking/oremi-device --version
oremi-device --version
```

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
