# Story 8 - Render Markdown in the review view

> As a workflow user, I want feature files that are Markdown to render as formatted documents so
> that specs, plans, and tasks read like prose instead of raw source.

| Field | Value |
|---|---|
| ID | S8 |
| Requirements | FR-2, FR-3 (review rendering) |
| Dependencies | S3 |

## Acceptance criteria

- Files with a Markdown extension (`*.md`, `*.markdown`) under the declared feature directory
  render as formatted documents: headings, emphasis, lists, blockquotes, inline code, fenced
  code, tables, and links.
- Rendering is read-only and preserves normal document scrolling.
- Non-Markdown text files keep the existing plain-content rendering.
- Binary files remain metadata-only.
- Large Markdown files honor the existing bounded preview and explicit full-load action.
- Malformed or unsupported Markdown renders as readable text without error or content loss.
- Rendering never blocks the UI and preserves the selected path, filter, and scroll across
  refresh.
- `$EDITOR` continues to open the raw source file, not the rendered view.
- The gate message, declared options, confirmation, and decision semantics are unchanged.

## Tests

- Unit tests cover Markdown detection and fallback for unknown extensions.
- Textual tests assert headings, lists, and code render as formatted output while non-Markdown
  files stay plain.
- Tests cover a large Markdown preview, malformed Markdown, and rendering while paused with a
  completed refresh.
