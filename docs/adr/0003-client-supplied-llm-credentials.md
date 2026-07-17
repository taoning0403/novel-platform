# ADR 0003: Client-supplied LLM credentials

- Status: proposed for a future phase
- Date: 2026-07-10

## Decision

v0.1.0 implements no LLM call or API-key setting. Before such integration, the
project will design a client-supplied credential flow with explicit lifetime,
redaction, transport, persistence, and provider-boundary rules. Credentials must
never enter Edition metadata, logs, error details, or acceptance artifacts.

## Consequences

No placeholder secret columns or premature provider abstraction are introduced in
the core version-model phase.

