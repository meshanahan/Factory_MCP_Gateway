# AGENTS.md

> Conventions and guardrails for building **mcp-gateway**, a governed MCP gateway that sits between AI coding agents (e.g. Factory Droids) and downstream MCP servers. Read this file fully before planning or implementing.

## Project

`mcp-gateway` is a centralized control plane for Model Context Protocol traffic. AI agents connect to **one** gateway endpoint instead of to many MCP servers directly. The gateway authenticates the caller, enforces per-role access control over tools, injects downstream credentials the agent never sees, and writes an immutable audit record of every tool invocation. The buyer is a platform-engineering / security org that must approve autonomous agents touching internal systems — so the product's job is to make agent tool-use **provably governed**.

This is an MVP for a demo. Favor a small, correct, legible system over breadth. Every capability must be demonstrable in under two minutes.

## Architecture

The gateway is simultaneously:
- **North side — an MCP server** that the agent/client connects to (transport: **stdio** for the local demo).
- **South side — an MCP client** that connects to one or more downstream MCP servers (transport: stdio for mock servers; design the south side so HTTP downstreams can be added without refactoring).

Request path for every tool call: agent → gateway (authn → policy check → credential injection → route) → downstream server → response → audit write → agent.

Four core components, kept in separate modules:
1. **Proxy / aggregation** — connect to downstream servers from a registry, aggregate their tool lists, **namespace** tools per server, and route invocations to the correct downstream.
2. **Policy engine (RBAC)** — config-driven allowlist mapping a caller role to permitted tools. **Deny by default.** Evaluated at invocation time, before any downstream contact.
3. **Audit log** — append-only structured records persisted to **SQLite**.
4. **Credential resolver** — holds downstream secrets, injects them on south-side calls, and guarantees they never cross the north side or land in audit/error output.

An optional read-only **dashboard** renders the audit stream and highlights denied calls. Build it only after the four components above pass tests.

## Tech stack & conventions

- **Language:** TypeScript, strict mode. Full type coverage; no `any` in committed code.
- **MCP:** official TypeScript SDK (`@modelcontextprotocol/sdk`). Register tools with `server.registerTool`; define input schemas with **Zod**, including constraints and descriptions.
- **Tool naming:** action-oriented, prefixed by downstream server to prevent collisions — `github__create_pr`, `database__run_query`, `slack__post_message` (double underscore separates namespace from tool).
- **Annotations:** set `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` accurately on proxied tools. `database__run_query` is `destructiveHint: true`.
- **Errors:** actionable messages that name the cause and the fix (e.g. `"Tool 'database__run_query' is not permitted for role 'code-droid'. Allowed: github__*, slack__post_message."`). Never leak secrets, stack traces, or downstream internals to the north side.
- **Config:** YAML. `config/servers.yaml` = downstream registry; `config/policy.yaml` = role → allowed tools. Treat config as untrusted input; validate on load.
- **Secrets:** read from environment / a secrets file referenced by the registry. Never hard-code; never commit real values.

## Repo layout

```
mcp-gateway/
  AGENTS.md
  package.json
  tsconfig.json
  src/
    index.ts             # north-side MCP server entrypoint
    proxy/               # downstream client mgmt, tool aggregation, routing
    policy/              # RBAC engine + policy loader (fail-closed)
    audit/               # SQLite audit logger
    credentials/         # secret resolution + south-side injection
    config/
      servers.yaml
      policy.yaml
  mock-servers/          # github, database, slack — minimal MCP servers w/ canned responses
  dashboard/             # optional read-only audit UI (build last)
  tests/
  .factory/              # mission/spec artifacts — committed, not gitignored
```

## Security & governance invariants (non-negotiable — these are the acceptance criteria)

1. **Deny by default.** Any tool not explicitly allowed for the caller's role is denied.
2. **Fail closed.** If policy or registry config cannot be loaded or parsed, deny all calls; do not start in an open state.
3. **No downstream contact on denial.** A denied invocation must never reach a downstream server. Prove it with a spy/mock asserting the downstream was not called.
4. **Audit completeness.** Every invocation — allowed *or* denied — produces exactly one audit record containing: timestamp, caller identity/role, namespaced tool, redacted parameters, decision (allow/deny), downstream latency (if any), and error class (if any).
5. **No secret leakage.** Downstream credentials must never appear in: the tool list exposed north, parameters echoed back, audit records, or error messages. Add a test that scans audit output for known secret values and fails if found.
6. **Namespacing integrity.** Two downstream servers exposing the same tool name must remain individually addressable and routable.

## Testing standards (TDD — write tests first)

- Unit: policy engine allow/deny matrix across roles and tools, including the deny-by-default and fail-closed paths.
- Integration: end-to-end route of an *allowed* call to the correct downstream and back.
- Security: (a) denied call does not touch downstream; (b) audit record emitted for both outcomes; (c) no secret in audit/error output.
- Run `npm run build` (must compile clean) and smoke-test the north side with `npx @modelcontextprotocol/inspector` before declaring done.

## Essential commands

```
npm install
npm run build        # tsc, must pass with zero errors
npm test             # all tests green before any "done"
npm run dev          # start gateway (stdio) for local/manual testing
npm run mocks        # start the three mock downstream servers
```

## Out of scope for the MVP (do not build unless asked)

SSO/OIDC integration, multi-tenant org hierarchy, rate limiting, prompt-injection scanning, HA/clustering, and a write-capable dashboard. Note them as the production roadmap; do not implement them now.
