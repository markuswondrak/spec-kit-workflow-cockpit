---
description: Create a specification under specs/ and record the active feature.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Choose the feature name** from the user input: a short, action-noun style, kebab-case name of
   2-4 words (e.g. `user-auth`, `oauth2-api-integration`, `fix-payment-timeout`). Choose it
   yourself; never ask the user for it.

2. **Resolve the feature directory.** Features always live under `specs/`:
   - If `SPECIFY_FEATURE_DIRECTORY` is explicitly set, use that path as-is.
   - Otherwise use `specs/<feature-name>`.
   - Never place a feature outside `specs/`. If the directory already exists, disambiguate with a
     numeric suffix (`specs/<feature-name>-2`) so a new feature never overwrites an existing one.

3. Create the directory and write `.specify/feature.json`:
   ```json
   { "feature_directory": "specs/<feature-name>" }
   ```
   Write the actual resolved relative path, not the literal string
   `SPECIFY_FEATURE_DIRECTORY`. Downstream commands (`speckit.plan`, `speckit.tasks`,
   `speckit.implement`) read this file to locate the feature.

4. Create a specification from the user input and store it in `<feature_directory>/spec.md`.
   - Overview, functional requirements, user scenarios, success criteria
   - Every requirement must be testable
   - Make informed defaults for unspecified details
