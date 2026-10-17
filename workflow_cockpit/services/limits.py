"""Shared read bounds for engine run files.

One constant, one meaning: every reader that opens ``state.json`` compares the
file size against :data:`MAX_STATE_BYTES` before reading, so discovery and the
live view can never disagree about which runs are readable. The bound is
documented in arc42 section 3.

The value follows research R3: a composed run embeds the YAML of the root
sequence plus one frozen definition per bound call and keeps them after
completion. The launch-copy workflow bound is 512 KiB, so several bound calls
at depth fit well inside 4 MiB while a runaway file is still refused.
"""

from __future__ import annotations

#: Largest ``state.json`` Cockpit reads, in bytes (4 MiB).
MAX_STATE_BYTES = 4 * 1024 * 1024
