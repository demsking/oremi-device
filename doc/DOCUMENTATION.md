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
  -e OREMI_DEVICE_NODE_ID=living-room \
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
available inside the container.

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
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
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
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
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

## Configuration

Configuration is loaded from environment variables with the `OREMI_DEVICE_` prefix.
Values may be placed in a `.env` file in the working directory. Environment variables
take precedence over `.env` values.

### Required Settings

| Environment variable         | Description                                        |
| ---------------------------- | -------------------------------------------------- |
| `OREMI_DEVICE_NODE_ID`       | Unique node identifier used in MQTT device topics. |
| `OREMI_DEVICE_OHUNERIN_HOST` | Ohunerin server host or IP address.                |
| `OREMI_DEVICE_MQTT_BROKER`   | MQTT broker host or IP address.                    |

The transcription backend has one additional required setting:

| Backend       | Required environment variable | Description                       |
| ------------- | ----------------------------- | --------------------------------- |
| `andika`      | `OREMI_DEVICE_ANDIKA_HOST`    | Andika server host or IP address. |
| `whisper.cpp` | `OREMI_DEVICE_WHISPER_URL`    | whisper.cpp HTTP server base URL. |

### Optional Settings

| Environment variable                     | Default                    | Description                                                                   |
| ---------------------------------------- | -------------------------- | ----------------------------------------------------------------------------- |
| `OREMI_DEVICE_LANGUAGE`                  | `fr`                       | Processing language; supported values are `fr` and `en`.                      |
| `OREMI_DEVICE_MICROPHONE_DEVICE_INDEX`   | Auto                       | Preferred microphone index.                                                   |
| `OREMI_DEVICE_MICROPHONE_DEVICE`         | Auto                       | Preferred microphone name; takes precedence over the index.                   |
| `OREMI_DEVICE_MICROPHONE_ENABLED`        | `true`                     | Enable microphone initialization and audio capture.                           |
| `OREMI_DEVICE_SPEAKER_ENABLED`           | `true`                     | Enable speaker initialization and MQTT speaker controls.                      |
| `OREMI_DEVICE_DELAY`                     | `3`                        | Sound-event cooldown in seconds and transcription message expiry interval.    |
| `OREMI_DEVICE_CONVERSATION_TIMEOUT`      | `15`                       | Maximum seconds to wait for a final transcription after a wake word.          |
| `OREMI_DEVICE_TRANSCRIPTION_BACKEND`     | `andika`                   | Transcriber: `andika` or `whisper.cpp`.                                       |
| `OREMI_DEVICE_OHUNERIN_PORT`             | `5023`                     | Ohunerin server port.                                                         |
| `OREMI_DEVICE_OHUNERIN_THRESHOLD`        | `0.65`                     | Minimum accepted Ohunerin confidence score.                                   |
| `OREMI_DEVICE_ANDIKA_PORT`               | `5315`                     | Andika server port.                                                           |
| `OREMI_DEVICE_ANDIKA_MODEL`              | `vosk-model-small-fr-0.22` | Vosk model identifier sent to Andika.                                         |
| `OREMI_DEVICE_ANDIKA_SAMPLERATE`         | `16000`                    | Audio sample rate sent to Andika.                                             |
| `OREMI_DEVICE_WHISPER_URL`               | Unset                      | whisper.cpp server URL; required for the `whisper.cpp` backend.               |
| `OREMI_DEVICE_WHISPER_SILENCE_THRESHOLD` | `500`                      | PCM RMS level above which whisper.cpp capture counts as speech.               |
| `OREMI_DEVICE_WHISPER_SILENCE_DURATION`  | `1.0`                      | Seconds of silence that finish a whisper.cpp utterance.                       |
| `OREMI_DEVICE_IZWI_URL`                  | Unset                      | Izwi base URL. When unset, speech synthesis and voice discovery are disabled. |
| `OREMI_DEVICE_CERT_FILE`                 | Unset                      | CA certificate for TLS connections to Oremi services.                         |
| `OREMI_DEVICE_MQTT_PORT`                 | `1883`                     | MQTT broker port.                                                             |
| `OREMI_DEVICE_MQTT_USERNAME`             | Unset                      | MQTT username.                                                                |
| `OREMI_DEVICE_MQTT_PASSWORD`             | Unset                      | MQTT password.                                                                |
| `OREMI_DEVICE_MQTT_TOPIC`                | `oremi/device`             | Base topic for events, availability, and controls.                            |
| `OREMI_DEVICE_MQTT_DISCOVERY`            | `true`                     | Enable Home Assistant MQTT discovery.                                         |
| `OREMI_DEVICE_MQTT_DISCOVERY_PREFIX`     | `homeassistant`            | Home Assistant discovery topic prefix.                                        |

Positive numeric values and valid port ranges are checked at startup. Boolean
values accept standard forms such as `true` and `false`. For example, a `.env`
file for a device without local audio hardware can contain:

```dotenv
OREMI_DEVICE_NODE_ID=living-room
OREMI_DEVICE_OHUNERIN_HOST=ohunerin
OREMI_DEVICE_ANDIKA_HOST=andika
OREMI_DEVICE_IZWI_URL=http://izwi:5215
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
Ohunerin with the newly selected language.

## MQTT

Examples below use the default base topic `oremi/device` and a node ID of
`living-room`. Events, controls, states, and availability are scoped below
`oremi/device/nodes/living-room`; the table lists suffixes relative to that
node prefix.

### Events

| Topic suffix            | Payload              | Notes                                                                                                      |
| ----------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------- |
| `event`                 | JSON detection event | Wake words and ambient sounds, distinguished by the payload's `type` field.                                |
| `transcription/partial` | JSON transcription   | Non-retained partial Andika result, QoS 1.                                                                 |
| `transcription/result`  | JSON transcription   | Non-retained final Andika result, QoS 1. This is also the Home Assistant transcription sensor state topic. |
| `conversation/state`    | UTF-8 state          | Retained lifecycle state: `idle`, `listening`, `processing`, or `speaking`.                                |

The `event` topic carries the detected-sound model for both wake words and
ambient sounds:

| Field   | Type   | Required | Description                                     |
| ------- | ------ | -------- | ----------------------------------------------- |
| `date`  | string | Yes      | ISO 8601 date-time when the sound was detected. |
| `score` | number | Yes      | Detection confidence score.                     |
| `sound` | string | Yes      | Detected ambient sound or wake-word name.       |
| `type`  | string | Yes      | Event discriminator: `sound` or `wakeword`.     |

The `sound` value is converted to a lowercase slug before publication. Ambient
sound events use this shape:

```json
{
  "type": "sound",
  "sound": "baby-cry-infant-cry",
  "score": 0.91,
  "date": "2026-06-19T12:04:10.123456"
}
```

Wake-word events use the same model with `"type": "wakeword"` and activate
Andika transcription. Home Assistant's wake-word and ambient-sound sensors both
subscribe to `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/event` and select messages by
their `type` field.

After the delay expires, the service publishes a retained clearing message with
`"sound": "..."` when no event of that type remains active.

The fixed MQTT subscription patterns are
`<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/transcription/partial` for partial results
and `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/transcription/result` for final results.
The `+` wildcard represents the node ID. Both payloads are the raw Andika JSON
response; the node is identified by the scoped MQTT topic.

See the [Andika models documentation](https://demsking.gitlab.io/oremi-andika/#models/)
for details about the
[PartialResult](https://demsking.gitlab.io/oremi-andika/#models/PartialResult)
and [FinalResult](https://demsking.gitlab.io/oremi-andika/#models/FinalResult)
models.

A partial response is published as:

```json
{
  "partial": "..."
}
```

A final response is published as:

```json
{
  "text": "turn on the living room light"
}
```

#### Conversation State And Sound Cues

The retained `conversation/state` topic exposes the interaction lifecycle:

| State        | Meaning                                                                  | Sound cue                                                               |
| ------------ | ------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| `idle`       | No conversation is active.                                               | Cancellation cue when listening times out or produces no usable speech. |
| `listening`  | A wake word was detected and Andika is capturing the request.            | Listening confirmation cue.                                             |
| `processing` | A final transcription was published and the device is waiting for NLP.   | Thinking cue.                                                           |
| `speaking`   | Izwi speech is playing for a response, announcement, alarm, or reminder. | Announcements first play a notification cue.                            |

A normal spoken interaction follows:

```text
idle -> listening -> processing -> speaking -> idle
```

An empty transcription or listening timeout follows `listening -> idle` and
plays the cancellation cue. Media is temporarily ducked while cues and speech
play; the configured volume and its MQTT state do not change. `set_volume`
commands play a short feedback tick after applying the new volume.

The device also plays a ready cue after MQTT and all configured components have
started and availability is published as `online`. During graceful shutdown it
stops capture and active playback, publishes availability as `offline`, plays a
shutdown cue, and then disconnects from MQTT.

The bundled cues come from Kenney's
[Interface Sounds](https://kenney.nl/assets/interface-sounds) pack, released
under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). The exact
source-file mapping and license are included in
`oremi_device/sounds/LICENSE.txt`.

An external NLP service can publish a response to the same node's
`processing/result` topic. A response containing only `message` is spoken with
the active Oremi Izwi voice:

```json
{
  "message": "Il est 13h30"
}
```

#### NLP Device Commands

For explicit device behavior, include a `commands` array. Commands execute in
array order. When the array is present, the device does not automatically speak
the top-level `message`; add a `speak` or `announce` command when speech is
required. Unknown command types and unknown fields are rejected.

```json
{
  "message": "Optional text for clients and logs",
  "commands": [
    { "type": "speak", "text": "Lecture de votre station" },
    { "type": "play", "url": "https://radio.example/live.mp3" }
  ]
}
```

The supported commands are:

| Type               | Required fields       | Optional fields           | Behavior                                                            |
| ------------------ | --------------------- | ------------------------- | ------------------------------------------------------------------- |
| `speak`            | `text`                | `voice`                   | Synthesizes a conversational response while ducking active media.   |
| `announce`         | `text`                | `voice`                   | Synthesizes a foreground announcement while ducking active media.   |
| `play`             | `url`                 | None                      | Interrupts current playback and plays an HTTP or HTTPS media URL.   |
| `pause`            | None                  | None                      | Pauses current playback.                                            |
| `resume`           | None                  | None                      | Resumes paused playback.                                            |
| `stop`             | None                  | None                      | Stops current playback.                                             |
| `alarm`            | `id`, `at`            | `message`, `url`, `voice` | Schedules an announcement, followed by an optional alarm media URL. |
| `reminder`         | `id`, `at`, `message` | `voice`                   | Schedules a spoken announcement.                                    |
| `cancel_scheduled` | `id`                  | None                      | Cancels an alarm or reminder with the matching ID.                  |
| `set_volume`       | `volume`              | None                      | Sets speaker volume to an integer percentage from `0` to `100`.     |
| `mute`             | `muted`               | None                      | Mutes when `true` and unmutes when `false`.                         |
| `set_voice`        | `voice`               | None                      | Selects a voice available for the active device language.           |

`voice` defaults to the active voice. A command-specific voice must exist in
Izwi's voice list. The Home Assistant voice selector and `set_voice` only accept
voices matching the active device language.

##### Speech And Playback

Use `speak` for conversational responses and `announce` for notifications.
Both play over active media. While speech is playing, the device temporarily
reduces the media stream to 25% of its current gain so the message remains
clear. Speech itself uses the normal speaker gain. The configured volume and
its MQTT/Home Assistant state do not change, and media gain is restored even
when synthesis fails or playback is canceled. Spoken alarms and reminders use
the same ducking behavior.

```json
{
  "commands": [
    { "type": "set_volume", "volume": 60 },
    { "type": "announce", "text": "La porte d'entrée est ouverte" }
  ]
}
```

Player commands can be combined in the same ordered array, although `pause` and
`resume` are normally sent as separate responses while media is playing.

##### Alarms And Reminders

The `at` field must be a timezone-aware ISO 8601 timestamp. An alarm or reminder
scheduled in the past runs as soon as the command is processed. IDs contain
letters, digits, underscores, or hyphens and are at most 64 characters. Sending
another `alarm` or `reminder` with the same ID replaces the previous schedule.

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

Schedules are held in device memory and are lost when the process restarts.
The NLP service should retain or recreate schedules when persistence is
required.

Invalid JSON, unavailable voices, naive timestamps, values outside their
documented ranges, and non-HTTP media URLs are rejected. Izwi speech uses the
`/api/synthesize/stream` endpoint: short requests use GET query parameters,
while long requests use a POST JSON body. The active voice defaults to the
first available voice matching the device language.

### Device Controls

Node availability is retained at
`oremi/device/nodes/<node-id>/available` with an `online` or `offline` payload.

| Command topic                                      | State topic                                          | Payload                                                   |
| -------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
| `oremi/device/nodes/<node-id>/language/set`        | `oremi/device/nodes/<node-id>/language/state`        | A UTF-8 language string. Discovery offers `fr` and `en`.  |
| `oremi/device/nodes/<node-id>/voice/set`           | `oremi/device/nodes/<node-id>/voice/state`           | An Izwi voice matching the active device language.        |
| `oremi/device/nodes/<node-id>/microphone/set`      | `oremi/device/nodes/<node-id>/microphone/state`      | A microphone name exposed by discovery.                   |
| `oremi/device/nodes/<node-id>/microphone/mute/set` | `oremi/device/nodes/<node-id>/microphone/mute/state` | `ON` mutes capture; `OFF` unmutes it.                     |
| `oremi/device/nodes/<node-id>/speaker/set`         | `oremi/device/nodes/<node-id>/speaker/state`         | A speaker name exposed by discovery.                      |
| `oremi/device/nodes/<node-id>/speaker/mute/set`    | `oremi/device/nodes/<node-id>/speaker/mute/state`    | `ON` mutes the speaker; `OFF` unmutes it.                 |
| `oremi/device/nodes/<node-id>/speaker/volume/set`  | `oremi/device/nodes/<node-id>/speaker/volume/state`  | Integer percentage from `0` to `100`.                     |
| `oremi/device/nodes/<node-id>/player/play/set`     | `oremi/device/nodes/<node-id>/player/state`          | An HTTP or HTTPS audio URL; state is `playing` or `idle`. |
| `oremi/device/nodes/<node-id>/player/stop/set`     | `oremi/device/nodes/<node-id>/player/state`          | Any payload stops playback.                               |

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

- language selection
- Izwi voice selection, filtered by the active language when Izwi is configured
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
