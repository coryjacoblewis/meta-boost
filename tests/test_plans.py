"""Tests for the freemium plan gate.

These cover the growth logic behind the Free→Pro funnel — the rules that decide
when a user hits the paywall and how the usage meter fills — independent of the
Streamlit UI that consumes them.
"""

from __future__ import annotations

import pytest

from plans import (
    FREE_LIMIT,
    FREE_PLAN,
    PRO_PLAN,
    DailyUsage,
    at_free_limit,
    try_consume_daily,
    usage_fraction,
)

# --- at_free_limit -------------------------------------------------------------


def test_free_user_not_gated_below_limit() -> None:
    assert at_free_limit(FREE_PLAN, 0) is False
    assert at_free_limit(FREE_PLAN, FREE_LIMIT - 1) is False


def test_free_user_gated_at_and_above_limit() -> None:
    assert at_free_limit(FREE_PLAN, FREE_LIMIT) is True
    assert at_free_limit(FREE_PLAN, FREE_LIMIT + 5) is True


def test_pro_user_never_gated() -> None:
    assert at_free_limit(PRO_PLAN, 0) is False
    assert at_free_limit(PRO_PLAN, FREE_LIMIT) is False
    assert at_free_limit(PRO_PLAN, 9999) is False


def test_at_free_limit_respects_custom_limit() -> None:
    assert at_free_limit(FREE_PLAN, 1, limit=1) is True
    assert at_free_limit(FREE_PLAN, 4, limit=5) is False


# --- usage_fraction ------------------------------------------------------------


@pytest.mark.parametrize(
    "used,expected",
    [(0, 0.0), (1, 1 / 3), (2, 2 / 3), (3, 1.0)],
)
def test_usage_fraction_scales_with_usage(used: int, expected: float) -> None:
    assert usage_fraction(used, limit=3) == pytest.approx(expected)


def test_usage_fraction_clamps_over_limit() -> None:
    # Never exceed a full bar even if usage somehow overshoots the limit.
    assert usage_fraction(10, limit=3) == 1.0


def test_usage_fraction_handles_nonpositive_limit() -> None:
    # A zero/negative limit means there is no free allowance — treat as full.
    assert usage_fraction(0, limit=0) == 1.0


def test_usage_fraction_floors_negative_usage() -> None:
    assert usage_fraction(-2, limit=3) == 0.0


# --- try_consume_daily (global demo guard) -------------------------------------


def test_daily_guard_allows_and_increments_until_limit() -> None:
    usage = DailyUsage(day="2026-07-17", count=0)
    usage, ok = try_consume_daily(usage, "2026-07-17", limit=2)
    assert ok is True and usage.count == 1
    usage, ok = try_consume_daily(usage, "2026-07-17", limit=2)
    assert ok is True and usage.count == 2
    usage, ok = try_consume_daily(usage, "2026-07-17", limit=2)
    assert ok is False and usage.count == 2  # capped; count untouched


def test_daily_guard_blocks_immediately_when_already_full() -> None:
    usage = DailyUsage(day="2026-07-17", count=2)
    usage, ok = try_consume_daily(usage, "2026-07-17", limit=2)
    assert ok is False
    assert usage.count == 2


def test_daily_guard_rolls_over_at_new_day() -> None:
    usage = DailyUsage(day="2026-07-17", count=99)
    usage, ok = try_consume_daily(usage, "2026-07-18", limit=2)
    assert ok is True
    assert usage.day == "2026-07-18"
    assert usage.count == 1  # fresh day starts from zero, then this generation


def test_daily_guard_first_ever_generation_starts_the_day() -> None:
    usage = DailyUsage(day="", count=0)
    usage, ok = try_consume_daily(usage, "2026-07-17", limit=200)
    assert ok is True
    assert usage.day == "2026-07-17"
    assert usage.count == 1
