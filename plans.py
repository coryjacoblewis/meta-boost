"""Freemium plan logic + demo cost guards for Meta-Boost.

Pure functions with no Streamlit dependency, so the Free→Pro growth gate and the
public-demo spend guard can be unit-tested in isolation from the UI. ``app.py``
passes in the relevant session/shared values; nothing here touches
``st.session_state`` or the Streamlit cache.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

FREE_PLAN = "Free"
PRO_PLAN = "Pro"

FREE_LIMIT = 3  # campaign generations per session on the Free plan

# Global ceiling on generations/day across ALL demo users. The public demo runs
# on the maintainer's shared API key, so a per-session limit alone can't bound
# spend (sessions reset on refresh). This caps worst-case cost regardless of how
# many sessions hit it. Override with the DEMO_DAILY_LIMIT env var.
DAILY_GLOBAL_LIMIT = int(os.getenv("DEMO_DAILY_LIMIT", "200"))


def at_free_limit(plan: str, gen_count: int, limit: int = FREE_LIMIT) -> bool:
    """True when a Free-plan user has used up their session generations.

    Pro users are never gated; Free users are gated once ``gen_count`` reaches
    ``limit``.
    """
    return plan == FREE_PLAN and gen_count >= limit


def usage_fraction(gen_count: int, limit: int = FREE_LIMIT) -> float:
    """Fraction of the free allowance used, clamped to [0, 1] for a progress bar."""
    if limit <= 0:
        return 1.0
    return min(max(gen_count, 0) / limit, 1.0)


# --- Global daily demo guard ---------------------------------------------------


@dataclass
class DailyUsage:
    """Process-wide generation tally for a single UTC day."""

    day: str  # ISO date (YYYY-MM-DD); "" before the first generation
    count: int


def try_consume_daily(
    usage: DailyUsage, today: str, limit: int = DAILY_GLOBAL_LIMIT
) -> tuple[DailyUsage, bool]:
    """Attempt to consume one unit of the global daily allowance.

    Rolls the tally over at UTC day boundaries. Returns the (possibly rolled-over
    and incremented) usage plus whether the generation is allowed — ``False`` once
    the day's cap is reached, in which case the count is left untouched.
    """
    if usage.day != today:
        usage = DailyUsage(day=today, count=0)
    if usage.count >= limit:
        return usage, False
    return DailyUsage(day=today, count=usage.count + 1), True
