# 0007. The launch model is the effective base-plus-overlay definition

- Status: Accepted
- Supersedes: -

## Context

A workflow definition can be modified by enabled overlays. Cockpit must launch and render what
will actually run, not the raw base file.

## Decision

`WorkflowDefinitionResolver` applies enabled overlays before the config screen presents the step
list and inputs, and before the graph is parsed. After start, once the persisted `workflow.yml` is
complete and parseable, the resolver compares normalized parsed structures and fails on a semantic
mismatch.

## Consequences

- The displayed inputs and steps match the effective workflow.
- A mismatch between the launch definition and the persisted definition fails fast.
- S2 adds graph semantics but does not repair an intentionally incomplete S1 definition.

## Rejected alternatives

- **Parsing the base file only:** shows steps the run will not execute.
- **Trusting the persisted copy without comparison:** hides a launch/run divergence.
