"""Tests for the Gemini strategy engine.

These mock the Gemini client at the SDK boundary, so they run offline and
require no API key. They cover prompt construction and the three outcomes the
UI depends on: success, missing key, and empty/failed responses.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
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
    """Stands in for client.models. Returns structured vs. markdown replies by
    inspecting whether the call requested a response_schema."""

    def __init__(
        self,
        *,
        parsed=None,
        text: str | None = "",
        markdown_text: str = "## Campaign 1\n\nMD body",
        raise_exc: Exception | None = None,
    ) -> None:
        self.parsed = parsed
        self.text = text
        self.markdown_text = markdown_text
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_exc is not None:
            raise self._raise_exc
        cfg = kwargs.get("config")
        is_structured = getattr(cfg, "response_schema", None) is not None
        if is_structured:
            return SimpleNamespace(parsed=self.parsed, text=self.text)
        return SimpleNamespace(parsed=None, text=self.markdown_text)


def _valid_result() -> strategist.StrategyResult:
    return strategist.StrategyResult(
        campaigns=[
            strategist.Campaign(
                title="Bean Quiz",
                brief="A fun quiz.",
                flow=strategist.Flow(
                    opener="Hey!",
                    branches=[
                        strategist.Branch(
                            reaction_label="interested",
                            turns=[strategist.Turn(speaker="Business", text="Link.")],
                        )
                    ],
                    final_cta="Tap.",
                ),
                ab_tests_md="*A/B*\n- A\n- B",
                kpis=strategist.Kpis(
                    open_rate="75%", click_through_rate="22%", conversion_rate="6%"
                ),
                rationale="Reasons.",
            )
        ],
        recommended_next="Run it.",
    )


def _patch_client(
    monkeypatch, models: object, captured: dict | None = None
) -> None:
    """Replace genai.Client so no network call happens.

    Passing ``captured`` records the kwargs the client was built with (e.g.
    ``http_options``), so tests can assert on client configuration.
    """

    def _factory(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return SimpleNamespace(models=models)

    monkeypatch.setattr(strategist.genai, "Client", _factory)


# --- models --------------------------------------------------------------------


def test_strategy_result_models_build_a_full_campaign() -> None:
    campaign = strategist.Campaign(
        title="Bean Quiz",
        brief="A fun quiz.",
        flow=strategist.Flow(
            opener="Hey! Quick question?",
            branches=[
                strategist.Branch(
                    reaction_label="interested",
                    turns=[
                        strategist.Turn(speaker="User", text="Yes!"),
                        strategist.Turn(speaker="Business", text="Great — here's the link."),
                    ],
                )
            ],
            final_cta="Tap to claim.",
        ),
        ab_tests_md="*A/B test*\n- A\n- B",
        kpis=strategist.Kpis(open_rate="75%", click_through_rate="22%", conversion_rate="6%"),
        rationale="Because reasons.",
    )
    result = strategist.StrategyResult(campaigns=[campaign], recommended_next="Run it.")
    assert result.campaigns[0].flow.branches[0].turns[1].speaker == "Business"
    assert result.campaigns[0].kpis.open_rate == "75%"
    assert result.fallback_markdown is None


# --- result_to_markdown --------------------------------------------------------


def test_result_to_markdown_includes_titles_kpis_and_next() -> None:
    result = strategist.StrategyResult(
        campaigns=[
            strategist.Campaign(
                title="Bean Quiz",
                brief="A fun quiz.",
                flow=strategist.Flow(
                    opener="Hey! Quick question?",
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
                    open_rate="75%", click_through_rate="22%", conversion_rate="6%"
                ),
                rationale="Because reasons.",
            )
        ],
        recommended_next="Run the quiz first.",
    )
    md = strategist.result_to_markdown(result)
    assert "Bean Quiz" in md
    assert "75%" in md and "22%" in md and "6%" in md
    assert "Hey! Quick question?" in md
    assert "Run the quiz first" in md
    assert "Recommended next step" in md


def test_result_to_markdown_returns_fallback_verbatim() -> None:
    result = strategist.StrategyResult(fallback_markdown="## Campaign 1\n\nRaw body")
    assert strategist.result_to_markdown(result) == "## Campaign 1\n\nRaw body"


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


def test_generate_strategy_returns_parsed_structured_result(monkeypatch, brief) -> None:
    models = _FakeModels(parsed=_valid_result())
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert isinstance(result, strategist.StrategyResult)
    assert result.campaigns[0].title == "Bean Quiz"
    assert result.fallback_markdown is None
    # Structured request carried a response_schema, the brief, and the system prompt.
    call = models.calls[0]
    assert brief.business_type in call["contents"]
    assert call["config"].system_instruction == strategist.SYSTEM_INSTRUCTION
    assert getattr(call["config"], "response_schema", None) is strategist.StrategyResult


def test_generate_strategy_degrades_to_markdown_on_parse_failure(monkeypatch, brief) -> None:
    # parsed None + non-JSON text => degrade; the markdown (second) call supplies the body.
    models = _FakeModels(
        parsed=None,
        text="not json at all",
        markdown_text="## Campaign 1\n\nDegraded body",
    )
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert result.fallback_markdown == "## Campaign 1\n\nDegraded body"
    assert result.campaigns == []
    assert len(models.calls) == 2  # structured attempt + markdown fallback


def test_generate_strategy_uses_key_and_model_overrides(monkeypatch, brief) -> None:
    models = _FakeModels(parsed=_valid_result())
    _patch_client(monkeypatch, models)

    generate_strategy(brief, api_key="explicit-key", model="gemini-pro-latest")

    assert models.calls[0]["model"] == "gemini-pro-latest"


def test_generate_strategy_falls_back_to_env_key(monkeypatch, brief) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    models = _FakeModels(parsed=_valid_result())
    _patch_client(monkeypatch, models)

    # Should not raise despite no api_key argument.
    assert generate_strategy(brief).campaigns[0].title == "Bean Quiz"


# --- generate_strategy: failure modes -----------------------------------------


def test_generate_strategy_missing_key_raises(monkeypatch, brief) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No Gemini API key"):
        generate_strategy(brief)


def test_generate_strategy_empty_response_raises(monkeypatch, brief) -> None:
    _patch_client(monkeypatch, _FakeModels(parsed=None, text="   "))
    with pytest.raises(RuntimeError, match="empty response"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_none_response_raises(monkeypatch, brief) -> None:
    _patch_client(monkeypatch, _FakeModels(parsed=None, text=None))
    with pytest.raises(RuntimeError, match="empty response"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_api_error_is_wrapped(monkeypatch, brief) -> None:
    models = _FakeModels(raise_exc=ValueError("quota exceeded"))
    _patch_client(monkeypatch, models)
    with pytest.raises(RuntimeError, match="Gemini request failed"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_maps_auth_error(monkeypatch, brief) -> None:
    exc = strategist.errors.ClientError(403, {"error": {"message": "permission denied"}})
    _patch_client(monkeypatch, _FakeModels(raise_exc=exc))
    with pytest.raises(RuntimeError, match="rejected the API key"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_maps_rate_limit(monkeypatch, brief) -> None:
    exc = strategist.errors.ClientError(429, {"error": {"message": "quota"}})
    _patch_client(monkeypatch, _FakeModels(raise_exc=exc))
    with pytest.raises(RuntimeError, match="rate limit or quota"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_maps_server_error(monkeypatch, brief) -> None:
    exc = strategist.errors.ServerError(503, {"error": {"message": "backend down"}})
    _patch_client(monkeypatch, _FakeModels(raise_exc=exc))
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        generate_strategy(brief, api_key="test-key")


def test_generate_strategy_error_does_not_leak_raw_detail(monkeypatch, brief) -> None:
    # A secret-ish string in the raw exception must never reach the user message.
    exc = strategist.errors.ClientError(429, {"error": {"message": "SECRET-quota-token-abc123"}})
    _patch_client(monkeypatch, _FakeModels(raise_exc=exc))
    with pytest.raises(RuntimeError) as info:
        generate_strategy(brief, api_key="test-key")
    assert "SECRET-quota-token-abc123" not in str(info.value)


# --- timeout & retry -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch) -> None:
    """Make retry backoff instant so the suite stays fast."""
    monkeypatch.setattr(strategist.time, "sleep", lambda _s: None)


class _SequencedModels:
    """Raises each queued exception in turn, then returns a structured success."""

    def __init__(self, *, failures: list[Exception], parsed) -> None:
        self._failures = list(failures)
        self._parsed = parsed
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._failures:
            raise self._failures.pop(0)
        return SimpleNamespace(parsed=self._parsed, text="")


def test_generate_strategy_retries_transient_then_succeeds(monkeypatch, brief) -> None:
    # One transient 5xx, then success — the caller should never see the blip.
    server_err = strategist.errors.ServerError(503, {"error": {"message": "backend down"}})
    models = _SequencedModels(failures=[server_err], parsed=_valid_result())
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert result.campaigns[0].title == "Bean Quiz"
    assert len(models.calls) == 2  # first attempt failed, retry succeeded


def test_generate_strategy_gives_up_after_max_retries(monkeypatch, brief) -> None:
    server_err = strategist.errors.ServerError(503, {"error": {"message": "still down"}})
    models = _FakeModels(raise_exc=server_err)
    _patch_client(monkeypatch, models)

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        generate_strategy(brief, api_key="test-key")
    # Initial attempt + MAX_RETRIES extra attempts, all exhausted.
    assert len(models.calls) == strategist.MAX_RETRIES + 1


def test_generate_strategy_does_not_retry_rate_limit(monkeypatch, brief) -> None:
    # 429 must NOT be retried — retrying quota errors just burns more quota.
    rate_err = strategist.errors.ClientError(429, {"error": {"message": "quota"}})
    models = _FakeModels(raise_exc=rate_err)
    _patch_client(monkeypatch, models)

    with pytest.raises(RuntimeError, match="rate limit or quota"):
        generate_strategy(brief, api_key="test-key")
    assert len(models.calls) == 1  # tried once, no retries


def test_generate_strategy_retries_network_faults(monkeypatch, brief) -> None:
    # A transport-level timeout is transient and should be retried.
    timeout = httpx.ConnectTimeout("timed out")
    models = _SequencedModels(failures=[timeout], parsed=_valid_result())
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert result.campaigns[0].title == "Bean Quiz"
    assert len(models.calls) == 2


def test_generate_strategy_sets_request_timeout(monkeypatch, brief) -> None:
    captured: dict = {}
    _patch_client(monkeypatch, _FakeModels(parsed=_valid_result()), captured)

    generate_strategy(brief, api_key="test-key")

    http_options = captured.get("http_options")
    assert http_options is not None
    assert http_options.timeout == strategist.REQUEST_TIMEOUT_MS


# --- output cost cap -----------------------------------------------------------


def test_generate_strategy_caps_output_tokens(monkeypatch, brief) -> None:
    # The structured call must bound output tokens, so no single call can run away.
    models = _FakeModels(parsed=_valid_result())
    _patch_client(monkeypatch, models)

    generate_strategy(brief, api_key="test-key")

    assert models.calls[0]["config"].max_output_tokens == strategist.MAX_OUTPUT_TOKENS


def test_markdown_fallback_also_caps_output_tokens(monkeypatch, brief) -> None:
    # The degrade path makes a second full API call — it must be capped too.
    models = _FakeModels(
        parsed=None,
        text="not json at all",
        markdown_text="## Campaign 1\n\nDegraded body",
    )
    _patch_client(monkeypatch, models)

    generate_strategy(brief, api_key="test-key")

    assert len(models.calls) == 2  # structured attempt + markdown fallback
    assert models.calls[1]["config"].max_output_tokens == strategist.MAX_OUTPUT_TOKENS
