# Story 10 - arc42 context layer for agents

> As a coding agent working in this repository, I want the architecture context to live in-repo as
> a navigable arc42 structure so that I load the right constraints and decisions instead of
> reverse-engineering intent from the code, session after session.

| Field | Value |
|---|---|
| ID | S10 |
| Requirements | Quality requirements; architecture context (see [§10 Quality Requirements](../docs/architecture/10-quality-requirements.md)) |
| Dependencies | S1-S6; coordinates with S9 CI |

Source principle: code is the source of truth for behavior; the in-repo arc42 set under
`docs/architecture/` is the source of truth for intent and constraints. Requirements keep only the
backlog (epic and story slices); the former design documents (`PRD.md`, `ARCHITECTURE.md`,
`TUI_DESIGN.md`, `UI_DESIGN.md`, `engine-contract.md`) are superseded by the arc42 set.

## Acceptance criteria

- Architecture documentation lives in the repository as Markdown under `docs/architecture/`,
  mapped to the twelve arc42 sections, with one file per section as in
  [`docs/architecture/README.md`](../docs/architecture/README.md).
- The root [`AGENTS.md`](../AGENTS.md) is the only always-on context file. It carries universal
  constraints as explicit rules **with their rationale**, the top-three quality goals, setup/test
  commands, and pointers (no content) to `docs/architecture/README.md`, `docs/glossary.md`, and
  `docs/decisions/README.md`.
- `docs/architecture/README.md` is a lightweight index (roughly 200 tokens) with a
  `Section | File | Load when` table so an agent can enter at the relevant section and stop.
- Tier 2 sections load on demand and are only reached through the index: §3 Context & Scope,
  §5 Building Block View, §6 Runtime View, §7 Deployment View, §8 Crosscutting Concepts,
  §9 Architecture Decisions.
- Tier 3 reference sections exist and are never loaded automatically: §4 Solution Strategy,
  §10 Quality Requirements, §11 AI Debt Register.
- `docs/glossary.md` is the §12 glossary and pins domain vocabulary (for example Run, Gate,
  Snapshot, Feature File, Supervisor, Story slice) so synonyms are not treated as interchangeable.
- `docs/decisions/README.md` indexes numbered ADRs; the resolved decisions formerly in
  `ARCHITECTURE.md` §8 ([§9 Architecture Decisions](../docs/architecture/09-architecture-decisions.md))
  become the initial ADR set, each recording what was decided and what was rejected.
- §11 is a structured AI Debt Register: a list of patterns present in the codebase that are known
  debt and must not be replicated, each with a location and the safe alternative. It is a pointer
  from `AGENTS.md`, not auto-loaded content.
- Every diagram is a fenced Mermaid block. No documentation file embeds a `png`, `svg`, or other
  raster/vector image.
- §8 Crosscutting Concepts holds the gold-standard reference implementation for this codebase's
  conventions (services without Textual imports, render-path isolation, bounded reads), shown as
  code and paired with an explicit correct-versus-incorrect contrast.
- Domain scopes use nested `AGENTS.md` inheritance: root for universal constraints, and a nested
  file only where a real boundary exists (`tests/`, `workflow_ui/prototype/`). A nested file never
  repeats the root.
- Documentation is living: any change that alters a documented constraint, boundary, or decision
  updates the matching doc in the same commit as the code.
- The arc42 set does not contradict the code or the product contract. Conflicts are surfaced to a
  human, never silently resolved by editing docs to match observed code, or code to match docs.
- This documentation replaces all former design documents (but not the epic and story slices) in
  the `./requirements` folder.
- [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) links (does not
  duplicate) `AGENTS.md`, `docs/architecture/README.md`, `docs/decisions/README.md`, and
  `docs/glossary.md` as its development-guidance pointers.
- The `lean-flow` workflow ends with an `update-documentation` step that invokes a new
  `arc42-context` extension command, so the living-documentation rule is enforced by the
  dogfooding workflow rather than left to convention.

## Tests

- A structure test asserts every required arc42 file exists, carries its section number and tier,
  and contains the headings the index promises.
- A link test resolves every pointer in `AGENTS.md` and `docs/architecture/README.md`, and every
  ADR and section reference in the doc set.
- A format test asserts no image embeds exist and that diagrams are Mermaid fenced blocks.
- A budget test asserts the always-on context (`AGENTS.md` plus referenced Tier 1 material) stays
  under an explicit token/line ceiling, and that the architecture index stays near its target.
- An ADR test asserts every ADR is listed in `docs/decisions/README.md` and every listed ADR
  resolves to a file.
- A CI check runs these with the S9 lint/test workflow and fails on any broken link, orphaned ADR,
  or missing section.
- The `arc42` extension installs with `specify extension add --dev ./extensions/arc42` and
  `speckit workflow info lean-flow` lists the `update-documentation` command step.
