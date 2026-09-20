# Distributed Systems Resilience

## Purpose
Guide changes involving Oremi Device's external Ohunerin, Andika, Akorin, Izwi, MQTT, and MCP interfaces.

## Principles
- Assume external services can be slow, unavailable, restarted, or partially responsive.
- Use explicit timeouts.
- Keep retry policies local to the owning component.
- Use bounded exponential backoff where retries are appropriate.
- Do not retry non-idempotent operations blindly.
- Preserve cancellation during retries and waits.
- Avoid retry storms.
- Reuse healthy connections where appropriate.
- Fail fast on the conversational critical path when waiting longer cannot improve the user experience.

## Review
For each external call inspect:
- connection establishment;
- timeout;
- retry;
- cancellation;
- response validation;
- partial failure;
- cleanup;
- observability.

## Oremi Device
Preserve the documented Ohunerin reconnect behavior and the per-conversation Andika/Akorin semantics unless the task explicitly changes them.
