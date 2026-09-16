# Story 7 - Agent-matched styling templates

> As a workflow user, I want the Cockpit to match the visual style of the coding agent I already
> use so that the workspace feels like one environment.

| Field | Value |
|---|---|
| ID | S7 |
| Requirements | FR-7 |
| Dependencies | S1; themes the S2-S6 surfaces |

## Acceptance criteria

- Cockpit ships named styling templates: a neutral `cockpit` default and at least three coding
  agent template (`opencode`, `github copilot`, `claude`), each a self-contained set of theme tokens.
- The active template is selected from the project's default integration in
  `.specify/integration.json`; an explicit override is available at launch.
- An unknown, missing, or malformed template falls back to the default with a non-fatal notice.
- Templates change only visual tokens (colors and accent styling). Layout, wording, controls,
  and behavior are identical across templates.
- All required tokens are validated. A template missing a required token is rejected and the
  fallback is logged.
- The resolved template name is visible in the app so the active style is unambiguous.
- Text, focus, and status states remain distinguishable under every shipped template
  (legibility and contrast check).
- Adding a template requires no application code change.

## Tests

- Unit tests cover template discovery, token validation, selection from the project
  integration, explicit override, and fallback.
- Textual tests assert the selected tokens are applied and that layout and behavior are
  identical across templates.
