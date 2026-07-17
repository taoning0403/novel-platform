# Generated API contract

FastAPI OpenAPI is exported to `openapi.json`; `openapi-typescript` generates
`src/schema.d.ts`. Run from the repository root:

```bash
pnpm api:generate
pnpm api:check
```

Do not hand-edit the generated files. The Web package imports component schemas through
`@novel-platform/api-client` and keeps transport/authentication behavior in its fetch adapter.
