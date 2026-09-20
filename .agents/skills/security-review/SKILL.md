# Security Review

## Purpose
Review security-sensitive changes to Oremi Device without compromising real-time behavior.

## Review areas
- MQTT authentication and topics;
- MCP exposure;
- WebSocket and HTTP endpoints;
- TLS certificate validation;
- URL handling;
- secrets and environment variables;
- command payload validation;
- subprocess invocation;
- headers and request injection;
- logging of sensitive data;
- network binding.

## Rules
- Never log credentials, API keys, certificate contents, audio payloads, or raw user speech at normal log levels.
- Preserve TLS verification.
- Validate externally supplied URLs and request methods.
- Avoid shell interpolation for subprocesses.
- Treat changing MCP bind addresses or authentication as a security-sensitive change.
- Keep secrets in configuration/environment mechanisms, never source code.
- Validate structured external responses before acting on them.
- Security changes must not accidentally introduce blocking work into the audio/event-loop critical path.

## Oremi Device
Respect the existing `safe_url`, secret masking, MCP loopback default, Pydantic validation, and external-service TLS handling documented in `AGENTS.md`.
