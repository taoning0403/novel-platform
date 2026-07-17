# ADR 0006: Web token storage

- Status: accepted
- Date: 2026-07-11

## Context

Persistent JavaScript-accessible bearer credentials amplify the impact of an XSS issue. Web
reload still needs a way to restore identity without retaining the password.

## Decision

Keep the Access Token only in JavaScript memory and deliver the Refresh Token in an HttpOnly
Cookie scoped to `/api/v1/auth`. Store only the non-secret `client_instance_id` in
`localStorage`. Never put either token in localStorage or a URL. Future native clients may use
body delivery and operating-system secure credential storage.

## Consequences

Page reload performs a Cookie refresh. Multiple expired requests share one refresh and retry
once. Cookie-authenticated refresh validates Origin and production requires HTTPS plus Secure
Cookies. Web JavaScript cannot read or export the Refresh Token.
