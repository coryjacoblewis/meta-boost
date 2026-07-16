"""Freemium plan logic for Meta-Boost.

Pure functions with no Streamlit dependency, so the Free→Pro growth gate can be
unit-tested in isolation from the UI. ``app.py`` passes in the relevant session
values; nothing here touches ``st.session_state``.
"""

from __future__ import annotations

FREE_PLAN = "Free"
PRO_PLAN = "Pro"

FREE_LIMIT = 3  # campaign generations per session on the Free plan


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
