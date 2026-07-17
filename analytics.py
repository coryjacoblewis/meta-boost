"""Lightweight funnel analytics for Meta-Boost.

Two self-contained surfaces — no database, no external provider, no keys:

  * **Structured event logs** — one compact JSON line per funnel event, emitted
    through the stdlib logger so they show up in `streamlit run` output and in
    Streamlit Cloud's log viewer for offline/aggregate analysis.
  * **A per-session funnel tally** — small counters ``app.py`` renders in the
    sidebar so the growth funnel is visible while you use the app.

Only *categorical* brief fields (goal, channel, tone) are ever logged — never the
free-text business description — so the logs stay privacy-safe. The counting and
derivation logic here is pure, so it can be unit-tested without Streamlit; the
session-state store and the logging sink live in ``app.py``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("meta_boost.analytics")

# Funnel event names — stable keys, safe to aggregate on in log tooling.
EVENT_FORM_SUBMIT = "form_submit"
EVENT_GENERATE = "generate"
EVENT_RESULT_SHOWN = "result_shown"
EVENT_UPGRADE_CLICK = "upgrade_click"
EVENT_UPGRADE_CONFIRM = "upgrade_confirm"


def configure(level: int = logging.INFO) -> None:
    """Ensure the analytics logger emits at ``level``.

    Idempotent. Events propagate to whatever handler the host (Streamlit / the
    root logger) has configured, so this just guarantees the level is low enough
    for INFO events to pass.
    """
    logger.setLevel(level)


def format_event(event: str, fields: dict[str, object]) -> str:
    """Render an event as a compact, deterministic JSON line.

    Keys are sorted so lines are stable and easy to diff/grep; ``None`` values are
    dropped so absent fields don't clutter the output.
    """
    payload: dict[str, object] = {"event": event}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def log_event(event: str, **fields: object) -> None:
    """Emit a single structured event line to the analytics logger."""
    logger.info(format_event(event, fields))


@dataclass
class Funnel:
    """Per-session funnel tally, rendered in the sidebar."""

    form_submits: int = 0  # valid briefs submitted
    generations: int = 0  # generation attempts that reached the engine
    results: int = 0  # attempts that produced a usable result
    upgrade_clicks: int = 0  # times the upgrade dialog was opened


def success_rate(funnel: Funnel) -> float | None:
    """Share of generation attempts that produced a result.

    Bounded to [0, 1]; ``None`` when there are no attempts yet (nothing to divide).
    """
    if funnel.generations <= 0:
        return None
    return min(funnel.results / funnel.generations, 1.0)
