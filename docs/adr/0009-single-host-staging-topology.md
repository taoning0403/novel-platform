# ADR 0009: Single-host staging topology

- Status: accepted
- Date: 2026-07-11

## Context

v0.2.0 needs a real-network integration environment on a 2 vCPU, approximately 2 GiB RAM
Ubuntu host. The current milestone has no Redis, worker, object storage, upload pipeline, or
production availability requirement. Database migration, private networking, durable storage,
backup verification, and a future same-origin HTTPS transition must remain explicit.

## Decision

Use a staging-only Compose file with PostgreSQL, one-shot Alembic migration, one Uvicorn worker,
and an unprivileged Nginx container serving the production Web build and proxying `/api/`.
Publish only Nginx. Put Web/API and API/PostgreSQL on separate internal networks, persist
PostgreSQL under `/srv/novel-platform/data`, and keep secrets in a server-local mode-600 file.
Updates back up the database, stop the public application, migrate, require the database
revision to equal the code head, and only then restart API/Web. Application rollback never
implies an automatic database downgrade.

## Consequences

The environment is reproducible, low-memory, same-origin, and suitable for continued staging
work without expanding v0.2.0 scope. Single-host failure remains a downtime event. HTTP/IP use
cannot pass the Secure Cookie gate, so the deployment stays explicitly staging with HTTPS
pending until a domain and trusted certificate are configured and the acceptance is rerun.
