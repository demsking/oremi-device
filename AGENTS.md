# AGENTS.md

Guidance for coding agents working in this repository. This file applies to the
entire project unless a more specific `AGENTS.md` exists in a subdirectory.

## Project Overview

Oremi Device is a Python 3.12 command-line application that captures microphone
audio, communicates with the Ohunerin and Andika services, and publishes state,
events, controls, and Home Assistant discovery data over MQTT.

The main areas of the repository are:

- `oremi_device/core/`: CLI parsing and the audio, MQTT, detection, listener,
  speaker, model, and package infrastructure.
- `oremi_device/components/`: integrations with Ohunerin and Andika.
- `oremi_device/utils/`: small shared utilities.
- `tests/`: pytest tests corresponding to the application modules.
- `config/`: example runtime configuration.
- `bin/`, `Dockerfile`, and `mosquitto/`: container and runtime support.

## Development Environment

- Use Python 3.12; the package does not support other Python versions.
- Use `uv` for dependency management. Do not introduce `pip`-managed files or
  manually edit `uv.lock`.
- Install the environment with `make install` or `uv sync`.
- Run the application from source with `uv run python -m oremi_device`.
- Treat credentials, certificate files, MQTT payloads, and recorded audio as
  sensitive. Never commit secrets or real user data.

## Making Changes

1. Read the affected implementation, its tests, and any public documentation
   before editing.
2. Keep changes narrowly scoped. Preserve existing behavior unless the task
   explicitly changes it, and avoid unrelated refactors or dependency updates.
3. Follow established module boundaries. Keep transport and device mechanics in
   `core`, service-specific behavior in `components`, and only genuinely shared
   helpers in `utils`.
4. Prefer standard-library or existing project facilities over adding a new
   dependency. If a dependency is necessary, add it to `pyproject.toml` and
   regenerate the lockfile with `uv lock`.
5. Update tests and user-facing documentation when CLI options, configuration,
   MQTT topics or payloads, defaults, or runtime behavior change.
6. Do not overwrite, revert, or reformat unrelated work already present in the
   working tree.

## Python Conventions

- Match the existing two-space indentation and double-quote style. Ruff is
  configured in `ruff.toml` with a 128-character line length.
- Add type annotations to new and changed functions. Prefer explicit models and
  structured parsing over loosely shaped dictionaries or string manipulation.
- Keep asynchronous work non-blocking. Do not perform blocking audio, network,
  or filesystem operations directly on the event loop.
- Handle shutdown, cancellation, reconnection, and resource cleanup explicitly
  when changing long-running tasks or service connections.
- Use the project logger instead of `print` for runtime diagnostics. Do not log
  passwords, audio content, certificates, or other secrets.
- All new Python files must carry the license header from `LICENSE_HEADER.txt`.
  The pre-commit hooks may update its year.
- Add comments only when they explain a non-obvious constraint or decision.

## Testing

- Add or adjust a focused test for every behavior change or bug fix.
- Keep tests deterministic and independent of local microphones, speakers,
  brokers, remote services, timing races, and internet access. Mock these
  boundaries using the patterns already present in `tests/`.
- Run the smallest relevant test while iterating, for example:

  ```bash
  uv run pytest tests/test_args.py
  uv run pytest tests/test_args.py::test_audio_devices_default
  ```

- Before considering a change complete, run the full suite and pre-commit checks
  when feasible. Run hooks only against staged files (the default):

  ```bash
  uv run pytest
  pre-commit run
  ```

- To check all tracked files changed from `HEAD`, including unstaged changes,
  use:

  ```bash
  git diff --name-only --diff-filter=ACMR -z HEAD | xargs -0 -r pre-commit run --files
  ```

- Do not use `pre-commit run --all-files` for routine validation because it may
  modify unrelated files. `make test` and `make coverage` are available when
  the development environment is already active; `make lint` intentionally
  checks the entire repository and should only be used when requested.
- If a check cannot run because hardware or an external service is unavailable,
  report that clearly; do not claim it passed.

## Commit Convention

- Do not create a commit unless the user explicitly asks for one.
- Follow Conventional Commits using `type(scope): description`, consistent with
  the existing history. Common types include `feat`, `fix`, `docs`, `test`,
  `refactor`, `style`, `build`, and `chore`.
- Choose a short scope that identifies the affected area, such as `cli`, `mqtt`,
  `audio`, `speaker`, `andika`, or `doc`.
- Write the description in lowercase imperative form without a trailing period,
  for example `fix(cli): preserve explicit microphone selection`.
- Keep each commit focused on one logical change. Do not include unrelated files
  or user changes in the commit.
- Use a commit body when the motivation, migration steps, or non-obvious behavior
  cannot be explained by the subject alone. Mark breaking changes with `!` and a
  `BREAKING CHANGE:` footer.

## Validation Checklist

Before handing work back:

- Review the diff for accidental edits and exposed secrets.
- Confirm relevant tests cover success, failure, and cleanup paths.
- Run focused tests, then the full suite for shared or cross-module changes.
- Run pre-commit on staged or changed files for formatting, lint, security,
  license, and documentation checks.
- Verify CLI help and README examples after changing command-line behavior.
- Summarize the files changed and checks run, including any remaining risks or
  checks that were skipped.
