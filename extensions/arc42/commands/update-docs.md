---
description: "Reconcile the arc42 architecture context, ADRs, and glossary with an implementation"
---

# Update architecture documentation

Bring the in-repo architecture context in line with what was just implemented. You inspect and
update **documentation only**; you do not change application behavior or the engine.

## Runtime note

This command runs **unattended** inside an automated Spec Kit workflow:

- **Never ask questions** and never wait for confirmation. Make informed defaults and record them.
- **Never request permissions.**
- **Never block.** If documentation and code genuinely contradict each other, stop and report the
  contradiction in your final message; do not silently pick a side.

## Steps

### Step 1: Enter through the index

Read [`docs/architecture/README.md`](../../../docs/architecture/README.md) first. It maps the
twelve arc42 sections to files and tiers. Read only the sections your change touches:

- **Tier 1** ([`AGENTS.md`](../../../AGENTS.md), §1, §2) is always-on.
- **Tier 2** (§3, §5, §6, §7, §8, §9) loads on demand through the index.
- **Tier 3** (§4, §10, §11, §12) is reference-only; touch it only when a decision or quality
  requirement changed.

### Step 2: Determine what changed

Inspect the implementation you just produced:

- the feature directory declared in `.specify/feature.json` (`specs/<feature>/`);
- the working-tree diff (`git diff` and `git status`);
- any new or changed public behavior, boundaries, constraints, or decisions.

Map the change to sections: new components or files to §5, new runtime behavior to §6, a changed
constraint or boundary to §2, a changed convention to §8, a new or reversed decision to §9 + a new
ADR, new vocabulary to §12.

### Step 3: Update only what is affected

- Prefer minimal edits over rewrites.
- Keep the section's `arc42`/`Tier` header and required headings intact.
- Do **not** duplicate content across sections; link instead.
- Every diagram must be a fenced ` ```mermaid ` block. Never embed a `png`, `svg`, or any other
  image.
- Keep files under 500 lines; split a section only along a real boundary.
- Record a new decision as the next numbered ADR under `docs/decisions/` and list it in
  `docs/decisions/README.md` and §9 in the same change.
- Add or amend the glossary entry when you introduce or rename a domain term.

### Step 4: Surface conflicts

If the code contradicts a documented constraint, boundary, or decision, do **not** edit the
document to match the code or the code to match the document. Report the exact conflict, the two
sources, and stop.

### Step 5: Verify and report

Run the documentation tests and report the result:

```bash
python -m pytest tests/docs -q
```

If no architecture document was affected, say so explicitly — an empty update is a valid outcome.
Always end with a summary naming the files you changed (or why none changed).

$ARGUMENTS
