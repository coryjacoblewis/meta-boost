"""Tests for the funnel analytics module.

Cover the pure pieces the UI relies on — the structured log line format, the
funnel derivation, and that ``log_event`` actually emits — without Streamlit.
"""

from __future__ import annotations

import json
import logging

from analytics import (
    EVENT_GENERATE,
    Funnel,
    format_event,
    log_event,
    success_rate,
)

# --- format_event --------------------------------------------------------------


def test_format_event_is_valid_json_with_event_and_fields() -> None:
    line = format_event(EVENT_GENERATE, {"goal": "Boost sales", "channel": "WhatsApp"})
    payload = json.loads(line)
    assert payload == {"event": "generate", "goal": "Boost sales", "channel": "WhatsApp"}


def test_format_event_keys_are_sorted_for_stable_lines() -> None:
    line = format_event("x", {"z": 1, "a": 2})
    # "event" sorts after "a" but before "z"; sort_keys makes the order deterministic.
    assert line.index('"a"') < line.index('"event"') < line.index('"z"')


def test_format_event_drops_none_fields() -> None:
    line = format_event(EVENT_GENERATE, {"goal": "Leads", "channel": None})
    payload = json.loads(line)
    assert "channel" not in payload
    assert payload["goal"] == "Leads"


# --- log_event -----------------------------------------------------------------


def test_log_event_emits_one_structured_info_line(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="meta_boost.analytics"):
        log_event(EVENT_GENERATE, goal="Boost sales")
    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload["event"] == "generate"
    assert payload["goal"] == "Boost sales"


# --- success_rate --------------------------------------------------------------


def test_success_rate_is_none_before_any_generation() -> None:
    assert success_rate(Funnel()) is None


def test_success_rate_is_ratio_of_results_to_generations() -> None:
    assert success_rate(Funnel(generations=4, results=3)) == 0.75


def test_success_rate_clamps_when_results_exceed_generations() -> None:
    # Shouldn't happen, but never report over 100%.
    assert success_rate(Funnel(generations=2, results=5)) == 1.0
