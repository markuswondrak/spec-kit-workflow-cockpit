# arc42 Documentation Update

A Spec Kit extension that keeps the repository's architecture context in sync with the code. It
provides one command, `speckit.arc42.update-docs`, which reconciles `docs/architecture/`,
`docs/decisions/`, and `docs/glossary.md` with the implementation that just happened.

The repository's `lean-flow` workflow runs it as the final `update-documentation` step, after
`implement`. It can also be invoked directly.

## Install

```bash
specify extension add --dev ./extensions/arc42
```

Remove:

```bash
specify extension remove arc42
```

## Use

```
/speckit.arc42.update-docs
```

The command:

- enters through [`docs/architecture/README.md`](../../docs/architecture/README.md) and reads only
  the sections the change touches;
- inspects the feature directory and working-tree diff;
- updates only affected sections, ADRs, and glossary entries, in the same change as the code;
- keeps diagrams as Mermaid and never embeds images;
- surfaces a documentation/code contradiction as a blocker instead of silently resolving it;
- runs `python -m pytest tests/docs -q` and reports the result.

It runs unattended: it never asks questions, never requests permissions, and reports a blocker in
its final message rather than hanging.

## License

MIT
