"""Msgspec model and decoder for `agy --output-format json` result envelope.

The Antigravity CLI (`agy`) emits a single, untagged JSON object at the end of a
`-p` / `--print` run when `--output-format json` is passed (verified on agy 1.0.16;
re-verified live on agy 1.2.12, 2026-09):

    {"conversation_id": "...", "status": "SUCCESS", "response": "...",
     "duration_seconds": 1.24, "num_turns": 1,
     "usage": {"input_tokens": ..., "output_tokens": ..., "thinking_tokens": ...,
               "cache_read_tokens": ..., "total_tokens": ...}}

On failure (confirmed live: interrupted run, invalid `--model`), `status` is
`"ERROR"` and `error` carries a human-readable message; `response`/`usage` may
still hold partial data from before the failure. `--print-timeout` expiry is
NOT a failure -- it still reports `status: "SUCCESS"` with a possibly-empty
`response`, so there's no field here to distinguish a timeout-truncated run
from a genuine completion. See docs/reference/runners/antigravity/ for the
full re-verification notes.

Every envelope observed live on 1.2.12 includes `usage.cache_read_tokens`,
which `AntigravityUsage` below now models (mapped through by
`_build_usage()` in runners/antigravity.py the same way `thinking_tokens`
is). Unknown fields are still ignored (`forbid_unknown_fields=False`) for
forward-compat with future envelope fields not yet modeled here.

Unlike the streaming engines, this is a terminal result envelope (not a JSONL
event feed), so a single struct is decoded directly — no ``tag_field`` union.
All fields are optional and unknown fields are ignored for forward-compat.
"""

from __future__ import annotations

import msgspec


class AntigravityUsage(msgspec.Struct, forbid_unknown_fields=False):
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_tokens: int | None = None


class AntigravityResult(msgspec.Struct, forbid_unknown_fields=False):
    conversation_id: str | None = None
    status: str | None = None
    response: str | None = None
    duration_seconds: float | None = None
    num_turns: int | None = None
    usage: AntigravityUsage | None = None
    # Confirmed live on agy 1.2.12 for an interrupted run (error="interrupted")
    # and an invalid --model (multi-line message listing available models).
    # Still optional since a SUCCESS envelope never sets it.
    error: str | None = None


_DECODER = msgspec.json.Decoder(AntigravityResult)


def decode_result(line: str | bytes) -> AntigravityResult:
    return _DECODER.decode(line)
