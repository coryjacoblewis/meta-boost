"""Behavioral tests for the Streamlit app itself.

The pure logic (``plans``, ``analytics``, ``strategist``) is covered in isolation
elsewhere; these drive ``app.py`` end-to-end through Streamlit's ``AppTest``
harness to lock in the wiring that only exists in the UI layer: the free-plan
paywall gate, the usage/funnel counters, the regenerate cache-bust, and the
error path. The Gemini engine is stubbed at its module boundary, so these run
offline with no API key and never hit the network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import strategist
from plans import FREE_LIMIT

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _isolate_caches() -> Iterator[None]:
    """Clear Streamlit's caches around each test.

    ``_generate_metered`` is ``@st.cache_data`` and ``_daily_usage_store`` is
    ``@st.cache_resource`` — both are process-wide, so without this a result (or a
    daily tally) from one test would bleed into the next.
    """
    st.cache_data.clear()
    st.cache_resource.clear()
    yield
    st.cache_data.clear()
    st.cache_resource.clear()


def _result(title: str = "Bean Quiz") -> strategist.StrategyResult:
    """A minimal but valid structured result the renderer can display."""
    return strategist.StrategyResult(
        campaigns=[
            strategist.Campaign(
                title=title,
                brief="A fun quiz.",
                flow=strategist.Flow(
                    opener="Hey!",
                    branches=[
                        strategist.Branch(
                            reaction_label="interested",
                            turns=[strategist.Turn(speaker="Business", text="Here's the link.")],
                        )
                    ],
                    final_cta="Tap to claim.",
                ),
                ab_tests_md="*A/B test*\n- A\n- B",
                kpis=strategist.Kpis(
                    open_rate="70%", click_through_rate="20%", conversion_rate="5%"
                ),
                rationale="Because reasons.",
            )
        ],
        recommended_next="Run it first.",
    )


def _stub_engine(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[strategist.CampaignBrief],
    *,
    result: strategist.StrategyResult | None = None,
    exc: Exception | None = None,
) -> None:
    """Replace ``strategist.generate_strategy`` with a recording stub.

    ``app.py`` re-imports the name on every rerun, so patching the source module
    is enough for the app to pick up the stub on its next ``run()``.
    """

    def _gen(brief: strategist.CampaignBrief, *args: object, **kwargs: object):
        calls.append(brief)
        if exc is not None:
            raise exc
        return result if result is not None else _result()

    monkeypatch.setattr(strategist, "generate_strategy", _gen)


def _fill_brief(at: AppTest, *, business: str = "Local coffee shop") -> None:
    """Populate the four required brief fields with valid values."""
    at.text_input[0].set_value(business)  # business type
    at.text_input[1].set_value("Single-origin espresso subscriptions")  # product
    at.text_area[0].set_value("Remote workers, 25-40, quality-focused")  # audience
    at.text_input[2].set_value("First month 30% off")  # offering


def _click(at: AppTest, label_contains: str) -> AppTest:
    """Click the first button whose label contains ``label_contains`` and rerun."""
    for button in at.button:
        if label_contains in (button.label or ""):
            button.click()
            break
    return at.run()


# --- initial render ------------------------------------------------------------


def test_app_renders_initial_empty_state() -> None:
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert at.title[0].value == "🚀 Meta-Boost"
    # Free plan, nothing used yet, and the pre-run preview is showing.
    assert any("0/3 generations used" in info.value for info in at.sidebar.info)
    assert at.session_state["result"] is None
    assert any("What you'll get" in md.value for md in at.markdown)


# --- validation ----------------------------------------------------------------


def test_incomplete_brief_warns_and_skips_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls)

    at = AppTest.from_file(APP).run()
    at.text_input[0].set_value("Only the business type")  # leave the rest blank
    _click(at, "Generate campaigns")

    assert not at.exception
    assert calls == []  # never reached the engine
    assert at.session_state["gen_count"] == 0
    assert any("Please fill in" in w.value for w in at.warning)


# --- happy path ----------------------------------------------------------------


def test_full_brief_generates_and_counts_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls)

    at = AppTest.from_file(APP).run()
    _fill_brief(at)
    _click(at, "Generate campaigns")

    assert not at.exception
    # Engine called once, with a brief carrying the submitted fields.
    assert len(calls) == 1
    assert calls[0].business_type == "Local coffee shop"
    assert calls[0].offering == "First month 30% off"
    # Result rendered and usage/funnel advanced.
    assert any(h.value == "Bean Quiz" for h in at.header)
    assert at.session_state["gen_count"] == 1
    funnel = at.session_state["funnel"]
    assert funnel.form_submits == 1
    assert funnel.generations == 1
    assert funnel.results == 1


# --- freemium gate -------------------------------------------------------------


def test_free_limit_gates_generation_without_calling_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls)

    at = AppTest.from_file(APP).run()
    at.session_state["gen_count"] = FREE_LIMIT  # already at the paywall
    _fill_brief(at)
    _click(at, "Generate campaigns")

    assert not at.exception
    assert calls == []  # gated before the engine
    assert at.session_state["gen_count"] == FREE_LIMIT  # not incremented
    # The upgrade intent was recorded on the session funnel.
    assert at.session_state["funnel"].upgrade_clicks == 1


def test_pro_plan_generates_past_free_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls)

    at = AppTest.from_file(APP).run()
    at.session_state["plan"] = "Pro"
    at.session_state["gen_count"] = 99  # far past the free limit
    _fill_brief(at)
    _click(at, "Generate campaigns")

    assert not at.exception
    assert len(calls) == 1  # Pro is never gated
    assert at.session_state["gen_count"] == 100
    assert any("unlimited" in s.value for s in at.sidebar.success)


# --- error path ----------------------------------------------------------------


def test_engine_error_is_shown_and_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls, exc=RuntimeError("Gemini is temporarily unavailable."))

    at = AppTest.from_file(APP).run()
    _fill_brief(at)
    _click(at, "Generate campaigns")

    assert not at.exception  # the app handles it; nothing bubbles up
    assert len(calls) == 1
    assert any("temporarily unavailable" in e.value for e in at.error)
    assert at.session_state["gen_count"] == 0  # a failed attempt doesn't count


# --- regenerate ----------------------------------------------------------------


def test_regenerate_busts_cache_and_calls_engine_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[strategist.CampaignBrief] = []
    _stub_engine(monkeypatch, calls)

    at = AppTest.from_file(APP).run()
    _fill_brief(at)
    _click(at, "Generate campaigns")
    assert len(calls) == 1  # first generation

    _click(at, "Regenerate")
    assert not at.exception
    # Regenerate bypasses the per-brief cache, so the engine runs a second time
    # for the identical brief instead of returning the cached result.
    assert len(calls) == 2
