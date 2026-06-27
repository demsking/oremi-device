# Oremi Device

[![Buy me a beer](https://img.shields.io/badge/Buy%20me-a%20beer-1f425f.svg)](https://www.buymeacoffee.com/demsking)

Oremi Device captures microphone audio and connects it to Oremi services:

- **Oremi Ohunerin** detects wake words and environmental sounds.
- **Oremi Andika** transcribes speech after Ohunerin detects a wake word.
- **Oremi Izwi** or an OpenAI-compatible Edge-TTS server synthesizes spoken NLP responses when configured.
- **MQTT** exposes events, device controls, availability, and Home Assistant
  discovery entities.

The application monitors audio hardware while it runs. It can switch to another
compatible microphone when the active device disappears and switch back when a
preferred device becomes available again.

## Documentation

All project documentation—including architecture details, configuration
reference, and the Home Assistant integration guide—can be found at:
https://demsking.gitlab.io/oremi-device/

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

Licensed under the Apache License, Version 2.0. See [LICENSE](https://gitlab.com/demsking/oremi-device/-/blob/main/LICENSE).
