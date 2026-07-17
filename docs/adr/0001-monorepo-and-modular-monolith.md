# ADR 0001: Monorepo and modular monolith

- Status: accepted
- Date: 2026-07-10

## Decision

Keep server, web, future shared client, infrastructure, scripts, and architecture
records in one repository. Deploy the API as one modular monolith backed by one
PostgreSQL database.

## Rationale

The v0.1.0 risk is semantic correctness, not independent service scaling. A
monorepo makes API/client contract changes atomic; explicit API, application,
domain, and infrastructure boundaries retain a path to later extraction without
introducing distributed transactions now.

