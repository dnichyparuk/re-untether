"""Convert Go ``time.ParseDuration``-style strings to seconds.

Mirrors the unit set and segment grammar validated (but not converted) by
``telegram.print_timeout._DURATION_RE``.
"""

from __future__ import annotations

import re

_UNIT_S: dict[str, float] = {
    "ns": 1e-9,
    "us": 1e-6,
    "micros": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}

_SEGMENT_RE = re.compile(r"(\d+(?:\.\d+)?)(ns|us|micros|ms|s|m|h)")
_FULL_RE = re.compile(r"^(?:\d+(?:\.\d+)?(?:ns|us|micros|ms|s|m|h))+$")


def parse_go_duration_seconds(value: str) -> float | None:
    """Convert a Go ``time.ParseDuration`` string to seconds.

    Accepts multi-unit (``1h30m``) and fractional (``0.5h``) values, the
    same unit set as ``print_timeout._DURATION_RE``. Returns ``None`` on any
    parse failure — never raises.
    """
    stripped = value.strip()
    if not stripped or not _FULL_RE.match(stripped):
        return None
    total = 0.0
    for amount, unit in _SEGMENT_RE.findall(stripped):
        total += float(amount) * _UNIT_S[unit]
    return total
