"""Tests for src/untether/utils/durations.py."""

from __future__ import annotations

import pytest

from untether.utils.durations import parse_go_duration_seconds


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15m", 900.0),
        ("1h30m", 5400.0),
        ("0.5h", 1800.0),
        ("90s", 90.0),
        ("250ms", 0.25),
    ],
)
def test_parse_go_duration_seconds_valid(value: str, expected: float) -> None:
    assert parse_go_duration_seconds(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "15", "-5s"])
def test_parse_go_duration_seconds_invalid(value: str) -> None:
    assert parse_go_duration_seconds(value) is None


def test_parse_go_duration_seconds_never_raises() -> None:
    for garbage in ["\x00", "🎉", "  \t\n  "]:
        assert parse_go_duration_seconds(garbage) is None
    # Not garbage — a huge but well-formed value; must not raise, may return a large float.
    parse_go_duration_seconds("999999999999999999999999999h")
