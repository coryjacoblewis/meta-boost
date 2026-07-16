"""Tests for the Gemini strategy engine.

These mock the Gemini client at the SDK boundary, so they run offline and
require no API key. They cover prompt construction and the three outcomes the
UI depends on: success, missing key, and empty/failed responses.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import strategist
from strategist import CampaignBrief, build_prompt, generate_strategy


@pytest.fixture
def brief() -> CampaignBrief:
    return CampaignBrief(
        business_type="Local coffee shop",
        product_service="Single-origin espresso subscriptions",
        target_audience="Remote workers, 25-40, quality-focused",
        offering="First month 30% off",
        marketing_goal="Boost sales",
        channel="WhatsApp Business",
        tone="Friendly & approachable",
    )


class _FakeModels:
    """Stands in for client.models — records the call and returns a canned reply."""

    def __init__(self, text: str, *, raise_exc: Exception | None = None) -> None:
        self._text = text
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_exc is not None:
            raise self._raise_exc
        return SimpleNamespace(text=self._text)


def _patch_client(monkeypatch, models: _FakeModels) -> None:
    """Replace genai.Client so no network call happens."""
    monkeypatch.setattr(
        strategist.genai,
        "Client",
        lambda api_key=None: SimpleNamespace(models=models),
    )


# --- build_prompt --------------------------------------------------------------


def test_build_prompt_includes_every_brief_field(brief: CampaignBrief) -> None:
    prompt = build_prompt(brief)
    for value in (
        brief.business_type,
        brief.product_service,
        brief.target_audience,
        brief.offering,
        brief.marketing_goal,
        brief.channel,
        brief.tone,
    ):
        assert value in prompt


def test_build_prompt_has_no_unfilled_placeholders(brief: CampaignBrief) -> None:
    prompt = build_prompt(brief)
    # A leftover "{field}" would mean a template key went unfilled.
    assert "{" not in prompt and "}" not in prompt


# --- generate_strategy: success ------------------------------------------------


def test_generate_strategy_returns_stripped_text(monkeypatch, brief) -> None:
    models = _FakeModels("  ## Campaign 1\n\nBody  ")
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert result == "## Campaign 1\n\nBody"
    # Prompt and system instruction must reach the model.
    call = models.calls[0]
    assert brief.business_type in call["contents"]
    assert call["config"].system_instruction == strategist.SYSTEM_INSTRUCTION


def test_generate_strategy_uses_key_and_model_overrides(monkeypatch, brief) -> None:
    models = _FakeModels("ok")
    _patch_client(monkeypatch, models)

    generate_strategy(brief, api_key="explicit-key", model="gemini-pro-latest")

    assert models.calls[0]["model"] == "gemini-pro-latest"


def test_generate_strategy_falls_back_to_env_key(monkeypatch, brief) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    models = _FakeModels("ok")
    _patch_client(monkeypatch, models)

    # Should not raise despite no api_key argument.
    assert generate_strategy(brief) == "ok"


# --- generate_strategy: failure modes -----------------------------------------


def test_generate_strategy_missing_key_raises(monkeypatch, brief) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No Gemini API key"):
        generate_strategy(brief)


def test_generate_strategy_empty_response_raises(monkeypatch, brief) -> None:
    _patch_client(monkeypatch, _FakeModels("   "))
    with pytest.raises(RuntimeError, match="empty response"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_none_response_raises(monkeypatch, brief) -> None:
    _patch_client(monkeypatch, _FakeModels(None))
    with pytest.raises(RuntimeError, match="empty response"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_api_error_is_wrapped(monkeypatch, brief) -> None:
    models = _FakeModels("", raise_exc=ValueError("quota exceeded"))
    _patch_client(monkeypatch, models)
    with pytest.raises(RuntimeError, match="Gemini request failed"):
        generate_strategy(brief, api_key="test-key")
