# 0009. The interactive gate contract applies to any workflow-capable engine

- Status: Accepted
- Supersedes: -

## Context

A gate without `verdict_input` is answered by writing one mapped choice to the engine's managed
PTY. That mapping was recorded against an exact build (`1.0.6` / `1.0.6.dev0`) and every other
version was rejected before Start as "not verified". Because preflight already bounds the version
range (`>=1.0,<2.0`) and probes for the required workflow commands and flags, the exact-release
allow-list added no safety the range and probe did not already provide. It did block ordinary
in-range builds: issue #3 reports `specify 1.0.5.dev0` unable to start any workflow with
interactive gates.

## Decision

The recorded `PromptContract` is the default for every `specify` build that parses as a version.
`resolve_contract` returns it for any parseable version and `None` only for an unparseable string.
The range check and capability probe remain the version barrier. Readiness is still inferred only
from authoritative persisted state (a live PTY child whose run is `running` at a declared
non-verdict gate); PTY output is never parsed.

## Consequences

- Interactive gates work on any supported, workflow-capable CLI, not only the recorded release.
- The recorded contract stays the single source of truth shared by the fake, PTY, and real-engine
  tests; no per-version branching remains.
- If a future engine changes the prompt, the failure is contained: a rejected index leaves the run
  `running`, the coordinator marks the attempt `UNVERIFIED` after its bounded watch, and only Abort
  is offered; an engine that pauses instead leaves the gate blocked with zero bytes written.

## Rejected alternatives

- **Exact-version allow-list:** requires a new recorded contract for every patch and prerelease and
  blocks compatible engines, as issue #3 shows.
- **Exact allow-list plus an override:** adds a second path to test and document for a case the
  range and probe already cover.
- **Parsing PTY output to prove the prompt:** makes presentation depend on diagnostic text and
  breaks the engine-opaque boundary (ADR 0004).
