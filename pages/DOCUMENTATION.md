Oremi Device captures microphone audio and connects it to Oremi services:

- **Ohunerin** detects wake words and environmental sounds.
- **Andika** transcribes speech after Ohunerin detects a wake word.
- **Izwi** synthesizes speech for responses, announcements, alarms, and reminders.
- **Akọrin** processes final transcriptions and returns device commands.
- **MQTT** exposes events, device controls, availability, and Home Assistant
  discovery entities.

The application monitors audio hardware while it runs. It can switch to another
compatible microphone when the active device disappears and switch back when a
preferred device becomes available again.

Project repository: https://gitlab.com/demsking/oremi-device

![Oremi Device Logo](./logo.jpg)

## Deployment

### Docker Image

The official [`demsking/oremi-device`](https://hub.docker.com/r/demsking/oremi-device)
image on Docker Hub supports `linux/amd64` and `linux/arm64`. It can run as a
standalone audio endpoint or alongside Ohunerin, Akọrin, Andika, and
whisper.cpp.

The following sections describe the available installation methods, persistent
storage requirements, and Docker or Docker Compose deployments.

### Command Line

Before installing Oremi Device from PyPI, ensure the following requirements are met:

- Python 3.12 or later.
- An MQTT broker.
- Running background instances of Ohunerin, Akọrin, and your preferred speech/transcription backends.
- Functional microphone and speaker hardware (unless explicitly disabled via settings).

Oremi Device can be installed either as a standalone command-line application or as a Python package.

#### Install with uv

```sh
uv tool install oremi-device
```

#### Install with pip

```sh
python -m pip install oremi-device
```

#### Usage

```sh
$ export OREMI_DEVICE_NODE_ID=living-room
$ export OREMI_DEVICE_LANGUAGE=fr
$ export OREMI_DEVICE_LOCATION="Douala, Cameroon"
$ export OREMI_DEVICE_PREFERRED_CURRENCY=XAF
$ export OREMI_DEVICE_OHUNERIN_HOST=localhost
$ export OREMI_DEVICE_ANDIKA_HOST=localhost
$ export OREMI_DEVICE_TTS_BACKEND=izwi
$ export OREMI_DEVICE_IZWI_URL=http://localhost:5031
$ export OREMI_DEVICE_AKORIN_URL=http://localhost:5020
$ export OREMI_DEVICE_MQTT_BROKER=localhost

$ oremi-device
```

All device configuration, including server addresses, audio parameters, and UI localization context, is provided through environment variables or a `.env` file rather than command-line options.

Because it interacts directly with host audio devices for capture and output,
containerized deployments typically require binding `/dev/snd` and, where
appropriate, host networking for low-latency local routing.

### Volumes

Oremi Device uses persistent storage to track runtime modifications changed dynamically through MQTT or Home Assistant dashboard selectors.

- **`/oremi/data`**: This container directory should be bound to a persistent volume. Runtime configuration updates are tracked here under an explicit `<node-id>.json` file structure.

If this volume isn't declared, your configuration resets to environment defaults whenever the container is dropped or updated.

### Deploy with Docker

Use the official Docker image [`demsking/oremi-device`](https://hub.docker.com/r/demsking/oremi-device) to run Oremi Device on a host sharing an existing service stack:

```sh
docker run --rm -it \
  --network host \
  --device /dev/snd:/dev/snd \
  -v oremi-device-data:/oremi/data \
  --env-file <path_to_env_file> \
  demsking/oremi-device
```

Replace `<path_to_env_file>` with the path to your configuration file containing your target environment definitions.

### Deploy with Docker Compose

To quickly spin up Oremi Device alongside its core dependencies, choose one of the tailored environment compositions below. First, prepare a basic Mosquitto broker setup on your target machine:

```sh
mkdir -p compose/mosquitto
cat > compose/mosquitto/mosquitto.conf <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
```

#### Option A: Native Oremi Stack (All Oremi Components)

Use this stack configuration to deploy a fully integrated, self-hosted voice assistant ecosystem using exclusively native Oremi services: Ohunerin for wake word detection, Andika for speech-to-text, Izwi for text-to-speech synthesis, and Akọrin for NLP orchestration.

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/oremi/data
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TIMEZONE: Africa/Douala
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_AKORIN_URL: http://akorin:5020
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: andika
      OREMI_DEVICE_ANDIKA_HOST: andika
      OREMI_DEVICE_ANDIKA_PORT: 5022
      OREMI_DEVICE_ANDIKA_MODEL: zhifeixie/Mega-ASR
      OREMI_DEVICE_ANDIKA_SAMPLERATE: 16000
      OREMI_DEVICE_TTS_BACKEND: izwi
      OREMI_DEVICE_IZWI_URL: http://izwi:5031
      OREMI_DEVICE_MQTT_BROKER: mosquitto
      OREMI_DEVICE_MQTT_PORT: 1883
      OREMI_DEVICE_MQTT_TOPIC: oremi/device
      OREMI_DEVICE_MQTT_DISCOVERY: 'true'
    depends_on:
      - ohunerin
      - andika
      - izwi
      - akorin
      - mosquitto
      - ollama

  akorin:
    image: demsking/oremi-akorin
    restart: unless-stopped
    environment:
      OREMI_AKORIN_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_AKORIN_ISINMI_URL: http://isinmi:5073
      OREMI_AKORIN_OJO_URL: http://ojo:5040
      OREMI_AKORIN_REDIYO_URL: http://rediyo:5076
      OREMI_AKORIN_KANSA_URL: http://kansa:5046
      OREMI_AKORIN_MQTT_BROKER: mosquitto
    env_file:
      - .env
    depends_on:
      - mosquitto
      - ollama
      - isinmi
      - ojo
      - rediyo
      - kansa

  ohunerin:
    image: demsking/oremi-ohunerin
    restart: unless-stopped

  andika:
    image: demsking/oremi-andika
    restart: unless-stopped
    environment:
      OREMI_ANDIKA_MODEL_NAME: zhifeixie/Mega-ASR
      OREMI_ANDIKA_ENABLE_GPU: true
      OREMI_ANDIKA_USE_VLLM: true
      OREMI_ANDIKA_VLLM_GPU_MEMORY_UTILIZATION: 0.8
      OREMI_ANDIKA_VLLM_MAX_NEW_TOKENS: 64
      OREMI_ANDIKA_AUDIO_ROUTING: true
      OREMI_ANDIKA_QUALITY_THRESHOLD: 0.5
    volumes:
      - oremi-andika-data:/oremi/data
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 16gb
        reservations:
          cpus: '2.0'
          memory: 8gb
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  izwi:
    image: demsking/oremi-izwi
    restart: unless-stopped
    volumes:
      - oremi-izwi-data:/oremi/data

  isinmi:
    image: demsking/oremi-isinmi
    restart: unless-stopped
    environment:
      OREMI_ISINMI_DATABASE_ENCRYPTION_KEY: your_database_encryption_key_here
    volumes:
      - oremi-isinmi-data:/oremi/data

  ojo:
    image: demsking/oremi-ojo
    restart: unless-stopped

  rediyo:
    image: demsking/oremi-rediyo
    restart: unless-stopped
    volumes:
      - oremi-rediyo-data:/oremi/data

  kansa:
    image: demsking/oremi-kansa
    restart: unless-stopped
    volumes:
      - oremi-kansa-data:/oremi/data

  ollama:
    image: ollama/ollama
    restart: unless-stopped
    runtime: nvidia
    volumes:
      - ~/.ollama:/root/.ollama
    environment:
      CUDA_VISIBLE_DEVICES: 0

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  oremi-isinmi-data:
  oremi-rediyo-data:
  oremi-kansa-data:
  oremi-andika-data:
  oremi-izwi-data:
```

Save as `docker-compose.yaml` (or `docker-compose.oremi.yaml`), then run:

```sh
docker compose up -d
```

#### Option B: Compose with whisper.cpp (External STT)

Use this stack configuration when substituting Oremi Andika with an external `whisper.cpp` server for speech-to-text processing while retaining Oremi Izwi for text-to-speech synthesis.

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/oremi/data
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TIMEZONE: Africa/Douala
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_AKORIN_URL: http://akorin:5020
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: whisper.cpp
      OREMI_DEVICE_WHISPER_URL: http://whisper:8080
      OREMI_DEVICE_WHISPER_SILENCE_THRESHOLD: 500
      OREMI_DEVICE_WHISPER_SILENCE_DURATION: 1.0
      OREMI_DEVICE_TTS_BACKEND: izwi
      OREMI_DEVICE_IZWI_URL: http://izwi:5031
      OREMI_DEVICE_MQTT_BROKER: mosquitto
      OREMI_DEVICE_MQTT_PORT: 1883
      OREMI_DEVICE_MQTT_TOPIC: oremi/device
      OREMI_DEVICE_MQTT_DISCOVERY: 'true'
    depends_on:
      - ohunerin
      - whisper
      - izwi
      - akorin
      - mosquitto
      - ollama

  akorin:
    image: demsking/oremi-akorin
    restart: unless-stopped
    environment:
      OREMI_AKORIN_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_AKORIN_ISINMI_URL: http://isinmi:5073
      OREMI_AKORIN_OJO_URL: http://ojo:5040
      OREMI_AKORIN_REDIYO_URL: http://rediyo:5076
      OREMI_AKORIN_KANSA_URL: http://kansa:5046
      OREMI_AKORIN_MQTT_BROKER: mosquitto
    env_file:
      - .env
    depends_on:
      - mosquitto
      - ollama
      - isinmi
      - ojo
      - rediyo
      - kansa

  ohunerin:
    image: demsking/oremi-ohunerin
    restart: unless-stopped

  izwi:
    image: demsking/oremi-izwi
    restart: unless-stopped
    volumes:
      - oremi-izwi-data:/oremi/data

  isinmi:
    image: demsking/oremi-isinmi
    restart: unless-stopped
    environment:
      OREMI_ISINMI_DATABASE_ENCRYPTION_KEY: your_database_encryption_key_here
    volumes:
      - oremi-isinmi-data:/oremi/data

  ojo:
    image: demsking/oremi-ojo
    restart: unless-stopped

  rediyo:
    image: demsking/oremi-rediyo
    restart: unless-stopped
    volumes:
      - oremi-rediyo-data:/oremi/data

  kansa:
    image: demsking/oremi-kansa
    restart: unless-stopped
    volumes:
      - oremi-kansa-data:/oremi/data

  whisper-model:
    image: ghcr.io/ggml-org/whisper.cpp:main
    volumes:
      - whisper-models:/models
    command:
      - ./models/download-ggml-model.sh base /models

  whisper:
    image: ghcr.io/ggml-org/whisper.cpp:main
    restart: unless-stopped
    volumes:
      - whisper-models:/models:ro
    command:
      - whisper-server --host 0.0.0.0 --port 8080 -m /models/ggml-base.bin
    depends_on:
      whisper-model:
        condition: service_completed_successfully

  ollama:
    image: ollama/ollama
    restart: unless-stopped
    runtime: nvidia
    volumes:
      - ~/.ollama:/root/.ollama
    environment:
      CUDA_VISIBLE_DEVICES: 0

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  oremi-isinmi-data:
  oremi-rediyo-data:
  oremi-kansa-data:
  oremi-izwi-data:
  whisper-models:
```

Save as `docker-compose.whisper.yaml`, then run:

```sh
docker compose -f docker-compose.whisper.yaml up -d
```

#### Option C: Compose with Edge-TTS (External TTS)

Use this stack configuration when substituting Oremi Izwi with an external OpenAI-compatible Edge-TTS service for cloud/edge speech synthesis while retaining Oremi Andika for speech-to-text.

```yaml
services:
  oremi-device:
    image: demsking/oremi-device
    restart: unless-stopped
    devices:
      - /dev/snd:/dev/snd
    volumes:
      - oremi-device-data:/oremi/data
    environment:
      LOG_LEVEL: info
      OREMI_DEVICE_NODE_ID: living-room
      OREMI_DEVICE_LANGUAGE: fr
      OREMI_DEVICE_LOCATION: Douala, Cameroon
      OREMI_DEVICE_TIMEZONE: Africa/Douala
      OREMI_DEVICE_TEMPERATURE_UNIT: celsius
      OREMI_DEVICE_PREFERRED_CURRENCY: XAF
      OREMI_DEVICE_MEASUREMENT_SYSTEM: metric
      OREMI_DEVICE_DISTANCE_UNIT: kilometer
      OREMI_DEVICE_TIME_FORMAT: 24h
      OREMI_DEVICE_DATE_FORMAT: DD/MM/YYYY
      OREMI_DEVICE_FIRST_DAY_OF_WEEK: monday
      OREMI_DEVICE_OHUNERIN_HOST: ohunerin
      OREMI_DEVICE_OHUNERIN_PORT: 5023
      OREMI_DEVICE_AKORIN_URL: http://akorin:5020
      OREMI_DEVICE_TRANSCRIPTION_BACKEND: andika
      OREMI_DEVICE_ANDIKA_HOST: andika
      OREMI_DEVICE_ANDIKA_PORT: 5022
      OREMI_DEVICE_ANDIKA_MODEL: zhifeixie/Mega-ASR
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
      - akorin
      - edge-tts
      - mosquitto
      - ollama

  akorin:
    image: demsking/oremi-akorin
    restart: unless-stopped
    environment:
      OREMI_AKORIN_OLLAMA_BASE_URL: http://ollama:11434
      OREMI_AKORIN_ISINMI_URL: http://isinmi:5073
      OREMI_AKORIN_OJO_URL: http://ojo:5040
      OREMI_AKORIN_REDIYO_URL: http://rediyo:5076
      OREMI_AKORIN_KANSA_URL: http://kansa:5046
      OREMI_AKORIN_MQTT_BROKER: mosquitto
    env_file:
      - .env
    depends_on:
      - mosquitto
      - ollama
      - isinmi
      - ojo
      - rediyo
      - kansa

  ohunerin:
    image: demsking/oremi-ohunerin
    restart: unless-stopped

  andika:
    image: demsking/oremi-andika
    restart: unless-stopped
    environment:
      OREMI_ANDIKA_MODEL_NAME: zhifeixie/Mega-ASR
      OREMI_ANDIKA_ENABLE_GPU: true
      OREMI_ANDIKA_USE_VLLM: true
      OREMI_ANDIKA_VLLM_GPU_MEMORY_UTILIZATION: 0.8
      OREMI_ANDIKA_VLLM_MAX_NEW_TOKENS: 64
      OREMI_ANDIKA_AUDIO_ROUTING: true
      OREMI_ANDIKA_QUALITY_THRESHOLD: 0.5
    volumes:
      - oremi-andika-data:/oremi/data
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 16gb
        reservations:
          cpus: '2.0'
          memory: 8gb
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  isinmi:
    image: demsking/oremi-isinmi
    restart: unless-stopped
    environment:
      OREMI_ISINMI_DATABASE_ENCRYPTION_KEY: your_database_encryption_key_here
    volumes:
      - oremi-isinmi-data:/oremi/data

  ojo:
    image: demsking/oremi-ojo
    restart: unless-stopped

  rediyo:
    image: demsking/oremi-rediyo
    restart: unless-stopped
    volumes:
      - oremi-rediyo-data:/oremi/data

  kansa:
    image: demsking/oremi-kansa
    restart: unless-stopped
    volumes:
      - oremi-kansa-data:/oremi/data

  edge-tts:
    image: travisvn/openai-edge-tts:latest
    restart: unless-stopped
    environment:
      API_KEY: your_api_key_here
      PORT: 5050

  ollama:
    image: ollama/ollama
    restart: unless-stopped
    runtime: nvidia
    volumes:
      - ~/.ollama:/root/.ollama
    environment:
      CUDA_VISIBLE_DEVICES: 0

  mosquitto:
    image: eclipse-mosquitto:2.0.18
    restart: unless-stopped
    volumes:
      - ./compose/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

volumes:
  oremi-device-data:
  oremi-isinmi-data:
  oremi-rediyo-data:
  oremi-kansa-data:
  oremi-andika-data:
```

Save as `docker-compose.edge-tts.yaml`, then run:

```sh
docker compose -f docker-compose.edge-tts.yaml up -d
```

## Configuration

Configuration parameters are loaded exclusively out of active environment
values matching the structural block patterns declared with the designated
`OREMI_DEVICE_` prefixes. Variables can alternatively reside in a local path
`.env` module directory.

### Required Settings

- **`OREMI_DEVICE_NODE_ID`** – Unique node identifier used in MQTT device topics.
- **`OREMI_DEVICE_OHUNERIN_HOST`** – Ohunerin server host or IP address.
- **`OREMI_DEVICE_MQTT_BROKER`** – MQTT broker host or IP address.

Depending on your configured `OREMI_DEVICE_TRANSCRIPTION_BACKEND`, one additional setting is strictly enforced:

- **`andika` engine backend**: `OREMI_DEVICE_ANDIKA_HOST` must point to an active Andika engine instance.
- **`whisper.cpp` engine backend**: `OREMI_DEVICE_WHISPER_URL` must point to a target HTTP endpoint.

### Audio Hardware

- **`OREMI_DEVICE_MICROPHONE_DEVICE_INDEX`** – Explicit host system hardware device identifier index for audio recording capture mapping. Default: `None` (System Auto).
- **`OREMI_DEVICE_MICROPHONE_DEVICE`** – Specific named identifier string overlaying microphone targeting configurations. Default: `None`.
- **`OREMI_DEVICE_MICROPHONE_ENABLED`** – Controls initial loading execution structures targeting physical capturing components. Default: `true`.
- **`OREMI_DEVICE_MICROPHONE_MUTED`** – Initializes the recording input hardware engine stream in a quiet state. Default: `false`.
- **`OREMI_DEVICE_SPEAKER_ENABLED`** – Activates peripheral audio reproduction routines and sound validation configurations. Default: `true`.
- **`OREMI_DEVICE_SPEAKER_DEVICE`** – Explicit device identifier assignment mapping the designated sound driver. Default: `None`.
- **`OREMI_DEVICE_SPEAKER_MUTED`** – Initializes sound rendering outputs to silent runtime configurations. Default: `false`.
- **`OREMI_DEVICE_SPEAKER_VOLUME`** – Floating level index mapping target playback audio scales between `0.0` and `1.0`. Default: `1.0`.
- **`OREMI_DEVICE_DATA_PATH`** – Directory used for the runtime settings cache. Default: `$XDG_DATA_HOME/oremi-device` (or `~/.local/share/oremi-device`); the Docker image sets `/oremi/data`.

### Transcription Controls

- **`OREMI_DEVICE_TRANSCRIPTION_BACKEND`** – Speech analysis target platform processor type options (`andika` | `whisper.cpp`). Default: `andika`.
- **`OREMI_DEVICE_DELAY`** – Processing interval delay threshold measuring session boundaries. Default: `3`.
- **`OREMI_DEVICE_CONVERSATION_TIMEOUT`** – Limit boundary window monitoring speech capturing before cutoff. Default: `15.0`.

### Akọrin Orchestration

- **`OREMI_DEVICE_AKORIN_URL`** – Core platform destination URL hosting downstream processing microservices (`/api/agent/`). Default: `None`.

### Device Context

- **`OREMI_DEVICE_LANGUAGE`** – String literal targeting operational language profiles (`fr` | `en`). Default: `fr`.
- **`OREMI_DEVICE_LOCATION`** – Geolocation name descriptor text processed internally to extrapolate runtime coordinates. Default: `""`.
- **`OREMI_DEVICE_TIMEZONE`** – Standard valid IANA continent-region timezone text assignments. Default: `UTC`.
- **`OREMI_DEVICE_TEMPERATURE_UNIT`** – String profile selecting local display metric indicators (`celsius` | `fahrenheit`). Default: `celsius`.
- **`OREMI_DEVICE_PREFERRED_CURRENCY`** – Validated 3-letter capital currency format validation string. Default: `XAF`.
- **`OREMI_DEVICE_MEASUREMENT_SYSTEM`** – Structural layout selecting formatting standards (`metric` | `imperial`). Default: `metric`.
- **`OREMI_DEVICE_DISTANCE_UNIT`** – Targeted scaling profile definitions (`kilometer` | `mile`). Default: `kilometer`.
- **`OREMI_DEVICE_TIME_FORMAT`** – Selects hour segmentation profile presentation maps (`12h` | `24h`). Default: `24h`.
- **`OREMI_DEVICE_DATE_FORMAT`** – String mask mapping calendar logs (`DD/MM/YYYY` | `MM/DD/YYYY` | `YYYY-MM-DD`). Default: `DD/MM/YYYY`.
- **`OREMI_DEVICE_FIRST_DAY_OF_WEEK`** – Selects custom chronological weekday tracking baselines (`monday` | `sunday` | `saturday`). Default: `monday`.

### Ohunerin Wake Word

- **`OREMI_DEVICE_OHUNERIN_HOST`** – Ohunerin server host or IP address.
- **`OREMI_DEVICE_OHUNERIN_PORT`** – Connectivity port routing Ohunerin service sockets. Default: `5023`.
- **`OREMI_DEVICE_OHUNERIN_THRESHOLD`** – Minimum operational score matching confidence boundaries. Default: `0.25`.
- **`OREMI_DEVICE_OHUNERIN_CERT_FILE`** – CA certificate used for a secure Ohunerin connection. Default: `None`.

### Andika Engine

- **`OREMI_DEVICE_ANDIKA_HOST`** – Andika server host or IP address when the Andika backend is selected.
- **`OREMI_DEVICE_ANDIKA_PORT`** – Dedicated connection port routing Andika streams. Default: `5022`.
- **`OREMI_DEVICE_ANDIKA_MODEL`** – Core system tracking string designating targeted local model profiles. Default: `zhifeixie/Mega-ASR`.
- **`OREMI_DEVICE_ANDIKA_SAMPLERATE`** – Audio capture configuration sampling frequency. Default: `16000`.
- **`OREMI_DEVICE_ANDIKA_CERT_FILE`** – CA certificate used for a secure Andika connection. Default: `None`.

### Whisper Engine

- **`OREMI_DEVICE_WHISPER_SILENCE_THRESHOLD`** – Level limits assigning signal bounds to background audio filters. Default: `500`.
- **`OREMI_DEVICE_WHISPER_SILENCE_DURATION`** – Duration checks verifying silent capture buffers. Default: `1.0`.

### Speech Synthesis (TTS)

- **`OREMI_DEVICE_TTS_BACKEND`** – Synthetic engine rendering standard profile choices (`izwi` | `edge-tts`). Default: `izwi`.
- **`OREMI_DEVICE_IZWI_URL`** – System destination target routing base native synthetic voices. Default: `None`.
- **`OREMI_DEVICE_EDGE_TTS_URL`** – Server instance configuration hosting proxy synthetic providers. Default: `None`.
- **`OREMI_DEVICE_EDGE_TTS_API_KEY`** – System credentials protecting access routing validation channels. Default: `your_api_key_here`.
- **`OREMI_DEVICE_EDGE_TTS_LOCALE`** – Locale code request flag matching targets. Default: `None` (Autoresolves to local engine default match profiles).
- **`OREMI_DEVICE_EDGE_TTS_MODEL`** – Target framework label identifying backend generation layouts. Default: `tts-1`.
- **`OREMI_DEVICE_EDGE_TTS_RESPONSE_FORMAT`** – Codec selection array parameters (`mp3` | `opus` | `aac` | `flac` | `wav` | `pcm`). Default: `mp3`.
- **`OREMI_DEVICE_EDGE_TTS_SPEED`** – Dynamic rate pacing scaling index options ranging from `0.25` up through `4.0`. Default: `1.0`.
- **`OREMI_DEVICE_TTS_VOICE`** – Direct voice identity tag strings tracking active target character synthesis styles. Default: `None`.

### MQTT Broker

- **`OREMI_DEVICE_MQTT_PORT`** – Connectivity port interfacing with active system message brokers. Default: `1883`.
- **`OREMI_DEVICE_MQTT_USERNAME`** – Verification credentials accessing private server installations. Default: `None`.
- **`OREMI_DEVICE_MQTT_PASSWORD`** – System passwords validating target MQTT routing targets. Default: `None`.
- **`OREMI_DEVICE_MQTT_TOPIC`** – Root namespace path capturing runtime device activity reports. Default: `oremi/device`.
- **`OREMI_DEVICE_MQTT_DISCOVERY`** – Activates autodiscovery configurations exposing targets inside Home Assistant systems. Default: `true`.
- **`OREMI_DEVICE_MQTT_DISCOVERY_PREFIX`** – Primary discovery path root prefix targeting components. Default: `homeassistant`.

### MCP Server

- **`OREMI_DEVICE_SERVER_HOST`** – MCP server bind address. Default: `127.0.0.1`.
- **`OREMI_DEVICE_SERVER_PORT`** – MCP server port. Default: `5048`.

### Logging Settings

- `OREMI_DEVICE_LOG_LEVEL`: Optional. Defaults to `INFO`. Logging level:
  `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.
- `OREMI_DEVICE_LOG_FILE`: Optional. Path to the rotating application log file.

### Verification and Error Diagnostics

Invalid or incomplete configuration prevents startup and the command exits with
status `1`. The application logs the validation error; set the required
variables listed above before retrying.

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
  /** Detected ambient sound or wake-word name */
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
  "datetime": "2026-06-19T12:04:10.123456"
}
```

Wake-word event:

```json
{
  "type": "wakeword",
  "sound": "oremi",
  "score": 1.0,
  "datetime": "2026-06-19T12:05:22.654321"
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
- Sent to Akorin when `OREMI_DEVICE_AKORIN_URL` is configured.
- This is also the Home Assistant transcription sensor state topic.
- Subscribers can subscribe to `<OREMI_DEVICE_MQTT_TOPIC>/nodes/+/transcription/result` to receive final results from all nodes.

See the [Andika models documentation](https://demsking.gitlab.io/oremi-andika/#models/) for details about the [PartialResult](https://demsking.gitlab.io/oremi-andika/#models/PartialResult) and [FinalResult](https://demsking.gitlab.io/oremi-andika/#models/FinalResult) models.

#### Conversation State

The current lifecycle state of the device's conversation handling.

- **Topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/conversation/state`
- **Retained:** Yes
- **QoS:** 1

**States:**

- **`idle`** – No conversation is active. Cancellation cue when listening times out or produces no usable speech.
- **`listening`** – A wake word was detected and Andika is capturing the request. Listening confirmation cue.
- **`processing`** – A final transcription was published and the device is waiting for Akorin or command execution. Thinking cue.
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
- If Akorin has not answered after two seconds, the device repeats a discreet thinking cue while it continues waiting.
- If Akorin times out or returns an invalid response, the device plays a discreet error cue and announces the problem with TTS.
- A new wake-word request interrupts the current Akorin request or command execution. Stop requests such as `stop`, `annule`, or `annuler` cancel the active processing without calling Akorin.
- `set_volume` commands play a short feedback tick after applying the new volume.
- The device plays a ready cue after MQTT and all configured components have started and availability is published as `online`.
- During graceful shutdown it stops capture and active playback, publishes availability as `offline`, plays a shutdown cue, and then disconnects from MQTT.
- The bundled cues come from Kenney's [Interface Sounds](https://kenney.nl/assets/interface-sounds) pack, released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). The exact source-file mapping and license are included in `device/sounds/LICENSE.txt`.

### NLP Integration

When `OREMI_DEVICE_AKORIN_URL` is set, Oremi Device sends each non-empty final
transcription to Akorin:

- Method: `POST`
- URL: `<OREMI_DEVICE_AKORIN_URL>/api/agent/`

**Request model:**

```typescript
interface AkorinProcessRequest {
  /** Final transcription text */
  message: string;
  /** Device language, such as 'fr' or 'en' */
  language?: string;
  /** Device preference settings */
  context: AkorinContext;
  /** Includes device_id:<node-id> */
  tags: string[];
}

interface AkorinContext {
  /** Retained device preferences such as timezone and units */
  preferences: Record<string, unknown>;
}
```

**Example request:**

```json
{
  "message": "mets la radio",
  "language": "fr",
  "context": {
    "preferences": {
      "language": "fr",
      "timezone": "Africa/Douala",
      "temperature_unit": "celsius"
    }
  },
  "tags": ["device_id:living-room"]
}
```

The response is validated as the command model below and executed sequentially.
Commands that start media playback, such as `play`, are asynchronous: once the
player is running, the device returns to idle and can accept follow-up commands
such as pause, resume, stop, volume, and mute. The player only has one active
track at a time; starting another track stops the previous active playback.

For compatibility with external integrations, an NLP service can also publish a
response to the same node's `processing/result` topic:

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
  /** Whether the processing succeeded */
  ok?: boolean;
  /** Optional text for clients and logs */
  message?: string;
  /** Additional structured result data */
  data?: Record<string, unknown>;
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

#### Continue Conversation

- **Command topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/conversation/continue/set`
- **State topic:** `<OREMI_DEVICE_MQTT_TOPIC>/nodes/<OREMI_DEVICE_NODE_ID>/conversation/continue/state`
- **Payload:** `ON` enables follow-up listening for Akorin messages classified
  as needing a user answer; `OFF` disables it.

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

## Home Assistant

MQTT discovery is enabled by default. On MQTT connection, Oremi Device publishes
retained discovery configurations below `homeassistant` for:

- device context controls for language, location, timezone, units, currency,
  date/time preferences, and first day of week
- speech synthesis voice selection, filtered by the active language when a TTS
  backend is configured
- continue-conversation switch for follow-up prompts
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
`OREMI_DEVICE_DATA_PATH` to a persistent path when running in a container.
The transcription sensor follows the node's `transcription/result` topic and
extracts its state from the final JSON payload's `text` field.

## Model Context Protocol (MCP)

Oremi Device implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), allowing LLM-based agents and assistants to inspect the device's status, configure settings, and manage audio devices directly.

#### Available MCP Tools

The following tools are registered on the MCP server:

#### `get_device_status`

Retrieves the current status, audio settings, and general configuration of the device.

- **Type**: Read-only
- **Arguments**: None
- **Response**: A JSON object containing the node's profile, settings, and hardware state.

#### `list_audio_devices`

Lists all compatible microphone (input) and speaker (output) devices discovered on the host system.

- **Type**: Read-only
- **Arguments**: None
- **Response**: Discovered audio devices classified as `input_devices` and `output_devices`.

#### `list_voices`

Retrieves available text-to-speech (TTS) voices from the configured speech synthesis backend (e.g., `izwi` or `edge-tts`).

- **Type**: Read-only
- **Arguments**:
  - `language` (string, optional): A two-letter language code (e.g., `fr`, `en`) to filter voices.
- **Response**: A list of compatible voice profiles.

#### `update_device_settings`

Updates the device's runtime configuration dynamically. Changes are immediately applied to memory and persisted in the node's local configuration cache file.

- **Type**: Mutation
- **Arguments**:
  - `language` (string, optional): The device language (`fr` or `en`).
  - `location` (string, optional): Geolocation name (e.g., `"Douala, Cameroon"`).
  - `timezone` (string, optional): Standard IANA timezone (e.g., `"Africa/Douala"`).
  - `temperature_unit` (string, optional): Unit selector (`celsius` or `fahrenheit`).
  - `preferred_currency` (string, optional): Currency code (e.g., `XAF`).
  - `measurement_system` (string, optional): Measurement system (`metric` or `imperial`).
  - `distance_unit` (string, optional): Distance unit (`kilometer` or `mile`).
  - `time_format` (string, optional): Time format (`12h` or `24h`).
  - `date_format` (string, optional): Date format (`DD/MM/YYYY`, `MM/DD/YYYY`, or `YYYY-MM-DD`).
  - `first_day_of_week` (string, optional): First day of the week (`monday`, `sunday`, or `saturday`).
  - `microphone_muted` (boolean, optional): Whether to mute the microphone capture stream.
  - `speaker_muted` (boolean, optional): Whether to mute the speaker playback stream.
  - `speaker_volume` (number, optional): Playback gain scalar between `0.0` and `1.0`.
  - `tts_voice` (string, optional): Speech synthesis voice name.
- **Response**: The updated `DeviceStatus` model.

#### Available MCP Resources

The server exposes the following resources to provide raw configuration templates:

- **`device:///status`**: Exposes the active device status profile (`application/json`).
- **`device:///settings`**: Exposes raw, non-sensitive configuration settings (`application/json`).

#### Available MCP Prompts

Predefined prompts are available to help users orchestrate tasks:

- **`configure_device`**: Interactive guidance directing agents to update language, location, or timezone.
- **`adjust_audio`**: Streamlined workflow assisting users with muting states and volume level modifications.

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
oremi-device --version
```

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Oremi Device source code is licensed under the Apache License, Version 2.0.

```
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://gitlab.com/demsking/oremi-device/-/blob/main/LICENSE

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

Bundled sound assets are licensed separately.<br>
See [`device/sounds/LICENSE.txt`](https://gitlab.com/demsking/oremi-device/-/blob/main/device/sounds/LICENSE.txt)
for the full sound asset license details, including the Kenney Interface
Sounds files used by Oremi Device and original generated sounds dedicated to
the public domain under Creative Commons Zero (CC0 1.0 Universal).
