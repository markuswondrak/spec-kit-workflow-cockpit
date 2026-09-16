# 0003. Minimum terminal size is 88 x 36 with a reversible resize guard

- Status: Accepted
- Supersedes: -

## Context

The gate review must fit a branching graph, a file list, meaningful document content, the context
path, and the declared decisions without clipping.

## Decision

Set the minimum supported terminal size to **88 x 36**. Below it, a resize-guard widget replaces
the layout with current and required dimensions; the app never exits. Wide layouts place Runway
beside Focus; 88-111 columns stack Runway above Focus.

## Consequences

- The gate surface is guaranteed legible at the minimum size.
- Resizing back above the minimum restores the layout without restarting.
- Layout choices must be validated at 88 x 36, 120 x 40, and 144 x 46.

## Rejected alternatives

- **Letting content clip:** hides decisions and content the user must see.
- **Exiting below a minimum:** loses an active run's context.
