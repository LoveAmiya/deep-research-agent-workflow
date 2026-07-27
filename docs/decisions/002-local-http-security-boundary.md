# ADR-002: Keep the report workbench local by default

## Status

Accepted

## Date

2026-07-27

## Context

The report workbench executes multi-step LLM and research workflows. A single HTTP request can consume significant time and model quota, while the project is intended for local demonstrations rather than public hosting.

## Decision

The server binds to loopback by default. Non-loopback binding requires an explicit bearer token. Request bodies, question length, concurrent runs and task duration are bounded. The existing JSON and SSE endpoints remain, with additive status and cancellation contracts and one structured error shape.

## Consequences

- Local startup remains credential-free.
- Docker and other non-loopback listeners require a configured token.
- Cancellation is cooperative at pipeline event boundaries; a timed-out worker retains its execution slot until it exits.
- This boundary does not claim production authentication, TLS termination or public multi-user isolation.
