"""Core strategy generation for Meta-Boost, powered by Google Gemini.

Takes a structured campaign brief and returns a full, Markdown-formatted set of
micro-campaign strategies (flows, A/B tests, simulated KPIs with PM-style rationale).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Selectable options surfaced by the UI.
CHANNELS = ["WhatsApp Business", "Messenger", "Instagram DMs"]
GOALS = [
    "Increase brand awareness",
    "Drive website traffic",
    "Generate leads",
    "Boost sales",
    "Improve customer retention",
]
TONES = [
    "Friendly & approachable",
    "Professional & informative",
    "Bold & exciting",
    "Warm & personal",
    "Playful & humorous",
]


@dataclass
class CampaignBrief:
    """Structured inputs collected from the SMB user."""

    business_type: str
    product_service: str
    target_audience: str
    offering: str
    marketing_goal: str
    channel: str
    tone: str


# --- Structured output schema --------------------------------------------------
# Only the conversational flow is deeply typed; richer sections (brief, A/B tests,
# rationale) ride along as Markdown strings so the model keeps its formatting
# freedom and the schema stays small.


class Turn(BaseModel):
    speaker: Literal["Business", "User"]
    text: str


class Branch(BaseModel):
    reaction_label: str = Field(
        description="Short label for the user reaction, e.g. 'interested', "
        "'asks a question', 'not now'."
    )
    turns: list[Turn]


class Flow(BaseModel):
    opener: str
    branches: list[Branch]
    final_cta: str


class Kpis(BaseModel):
    open_rate: str
    click_through_rate: str
    conversion_rate: str


class Campaign(BaseModel):
    title: str
    brief: str = Field(description="Markdown: 2-3 sentence concept + primary CTA.")
    flow: Flow
    ab_tests_md: str = Field(
        description="Markdown: two A/B tests (opening message + in-flow CTA), each "
        "with Variation A/B and a rationale naming the lever."
    )
    kpis: Kpis
    rationale: str = Field(
        description="Markdown: PM rationale anchoring each KPI to a rough benchmark."
    )


class StrategyResult(BaseModel):
    campaigns: list[Campaign] = []
    recommended_next: str = ""
    fallback_markdown: str | None = Field(
        default=None,
        description="Internal use only; always leave null.",
    )


SYSTEM_INSTRUCTION = """\
You are an expert conversational-marketing strategist who helps small and medium \
businesses (SMBs) run high-performing micro-campaigns on Meta's messaging platforms \
(WhatsApp Business, Messenger, Instagram DMs).

You think like a growth product manager: you tie every recommendation to a marketing \
goal, you design for experimentation, and you explain the "why" behind your numbers.

Rules:
- Be concrete and channel-specific. Respect the norms of the chosen channel (e.g., \
  WhatsApp broadcasts vs. interactive Messenger quizzes vs. Instagram DM replies).
- Write conversational copy an SMB owner could send as-is. Keep it human, not corporate.
- Simulated KPIs are PLAUSIBLE ESTIMATES for planning, never guarantees. Always frame \
  them that way.
- Output clean Markdown only. No preamble, no closing remarks, no code fences around the \
  whole response.
"""

MARKDOWN_PROMPT_TEMPLATE = """\
Design micro-campaigns for this business.

- **Business type:** {business_type}
- **Primary product/service:** {product_service}
- **Target audience:** {target_audience}
- **Current offering/promotion:** {offering}
- **Primary marketing goal:** {marketing_goal}
- **Preferred Meta channel:** {channel}
- **Desired tone:** {tone}

Produce **2–3 distinct micro-campaign strategies** (aim for 3 when the business supports \
genuinely different angles). Use this exact Markdown structure for each one:

## Campaign N: <catchy title>

**Strategy brief:** 2–3 sentences on the concept and its primary call-to-action.

**Conversational flow**

A step-by-step, multi-turn dialogue for {channel}. For each turn label the speaker \
(**Business** / **User**). Start with the opener, then branch on likely user reactions \
(e.g., *interested*, *asks a question*, *not now*) and give the business's reply for each \
branch. End with a clear final CTA.

**A/B test variations**

Provide TWO separate tests, each clearly sub-labelled. Do not skip either.

*A/B test — Opening message*
- **Variation A:** <text>
- **Variation B:** <text>
- **Rationale:** why B might out- or under-perform A (name the specific lever — urgency, \
  social proof, personalization, clarity, etc.).

*A/B test — Key in-flow CTA*
- **Variation A:** <text of a call-to-action used inside the flow>
- **Variation B:** <text>
- **Rationale:** same — name the lever being tested.

**Simulated KPI predictions** *(plausible planning estimates, not guarantees)*

| Metric | Estimate |
| --- | --- |
| Open rate | <x%> |
| Click-through rate | <x%> |
| Conversion rate | <x%> |

**PM rationale:** Explain *why* these numbers are plausible — briefly anchor each estimate \
to a rough industry benchmark (e.g. "vs. ~20% open rate for marketing email") so they don't \
read as arbitrary, name the factors that drive them, and connect the campaign to the goal \
of "{marketing_goal}". Keep estimates realistic and varied across campaigns, not uniformly \
rosy.

---

After the campaigns, add a short **## Recommended next step** section telling the SMB which \
campaign to run first and why.
"""

STRUCTURED_PROMPT_TEMPLATE = """\
Design micro-campaigns for this business and return them as structured data.

- **Business type:** {business_type}
- **Primary product/service:** {product_service}
- **Target audience:** {target_audience}
- **Current offering/promotion:** {offering}
- **Primary marketing goal:** {marketing_goal}
- **Preferred Meta channel:** {channel}
- **Desired tone:** {tone}

Produce 2–3 distinct campaigns. For each campaign fill every field:
- `title`: catchy title.
- `brief`: 2–3 sentence concept + primary CTA (Markdown).
- `flow`: an `opener` message from the business, then `branches` — one per likely \
user reaction. Each branch has a `reaction_label` (a short human-readable phrase in \
plain words, e.g. "interested", "asks a question", "not now" — never snake_case) and \
a short `turns` list alternating speaker "Business"/"User". End with a single \
`final_cta`. Write copy specific to {channel} that an SMB could send as-is.
- `ab_tests_md` (Markdown): TWO A/B tests — one for the opening message, one for a \
key in-flow CTA. Format as plain Markdown with real line breaks; do NOT use HTML \
(no `<br>`) and do NOT use `#` headings. Use exactly this shape:

  *A/B test — Opening message*
  - **Variation A:** …
  - **Variation B:** …
  - **Rationale:** name the lever (urgency, social proof, personalization, clarity, …).

  *A/B test — Key in-flow CTA*
  - **Variation A:** …
  - **Variation B:** …
  - **Rationale:** name the lever.
- `kpis`: open_rate, click_through_rate, conversion_rate as percent strings \
(e.g. "72%"). Keep them realistic and varied across campaigns, not uniformly rosy.
- `rationale` (Markdown): explain why the KPIs are plausible, anchoring each to a \
rough industry benchmark, and connect the campaign to the goal of "{marketing_goal}".

Also set `recommended_next` (Markdown): which campaign to run first and why.
Leave `fallback_markdown` null.
"""


def _friendly_api_error(exc: Exception) -> str:
    """Translate an SDK/transport error into a message safe to show a user.

    Maps the common failure modes to actionable guidance and deliberately avoids
    echoing raw SDK internals (stack-ish detail, request IDs) into the UI.
    """
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return (
                "Gemini rejected the API key. Check that GEMINI_API_KEY is valid "
                "and has access to the selected model."
            )
        if code == 429:
            return (
                "Gemini rate limit or quota reached. Wait a moment before "
                "regenerating, or check your plan's quota."
            )
        if isinstance(exc, errors.ServerError):
            return "Gemini is temporarily unavailable. Please try again shortly."
        return "Gemini couldn't process this request. Try adjusting your brief and regenerating."
    # httpx.TransportError is the base for connect/read timeouts and connection errors.
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError)):
        return "Couldn't reach Gemini — check your network connection and try again."
    return "Gemini request failed unexpectedly. Please try regenerating."


def _flow_to_markdown(flow: Flow) -> str:
    lines = ["**Conversational flow**", "", f"**Business:** {flow.opener}", ""]
    for branch in flow.branches:
        lines.append(f"*If the user is {branch.reaction_label}:*")
        for turn in branch.turns:
            lines.append(f"- **{turn.speaker}:** {turn.text}")
        lines.append("")
    lines.append(f"**Final CTA — Business:** {flow.final_cta}")
    return "\n".join(lines)


def _campaign_to_markdown(campaign: Campaign) -> str:
    kpis = campaign.kpis
    return "\n".join(
        [
            f"## {campaign.title}",
            "",
            f"**Strategy brief:** {campaign.brief}",
            "",
            _flow_to_markdown(campaign.flow),
            "",
            campaign.ab_tests_md,
            "",
            "**Simulated KPI predictions** *(plausible planning estimates, not guarantees)*",
            "",
            "| Metric | Estimate |",
            "| --- | --- |",
            f"| Open rate | {kpis.open_rate} |",
            f"| Click-through rate | {kpis.click_through_rate} |",
            f"| Conversion rate | {kpis.conversion_rate} |",
            "",
            f"**PM rationale:** {campaign.rationale}",
        ]
    )


def result_to_markdown(result: StrategyResult) -> str:
    """Rebuild a full Markdown document from a structured result.

    In degraded mode (``fallback_markdown`` set) the raw blob is returned verbatim.
    """
    if result.fallback_markdown is not None:
        return result.fallback_markdown
    blocks = [_campaign_to_markdown(c) for c in result.campaigns]
    doc = "\n\n---\n\n".join(blocks)
    if result.recommended_next:
        doc += f"\n\n## Recommended next step\n\n{result.recommended_next}"
    return doc


def _brief_fields(brief: CampaignBrief) -> dict[str, str]:
    return {
        "business_type": brief.business_type,
        "product_service": brief.product_service,
        "target_audience": brief.target_audience,
        "offering": brief.offering,
        "marketing_goal": brief.marketing_goal,
        "channel": brief.channel,
        "tone": brief.tone,
    }


def build_prompt(brief: CampaignBrief) -> str:
    """The structured prompt (asks the model to fill the StrategyResult schema)."""
    return STRUCTURED_PROMPT_TEMPLATE.format(**_brief_fields(brief))


def build_markdown_prompt(brief: CampaignBrief) -> str:
    """The legacy Markdown prompt, retained for the graceful-degrade path."""
    return MARKDOWN_PROMPT_TEMPLATE.format(**_brief_fields(brief))


def _generate_markdown(
    brief: CampaignBrief, *, client, model: str | None = None
) -> str:
    """Fallback generation: the proven Markdown path, returned as a raw string."""
    response = client.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=build_markdown_prompt(brief),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.8,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response. Try regenerating.")
    return text


def generate_strategy(
    brief: CampaignBrief,
    api_key: str | None = None,
    model: str | None = None,
) -> StrategyResult:
    """Call Gemini for structured campaigns; degrade to Markdown on parse failure.

    Raises RuntimeError with a friendly message on missing key or API failure.
    """

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "No Gemini API key found. Set GEMINI_API_KEY in your .env file."
        )

    client = genai.Client(api_key=key)

    try:
        response = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=build_prompt(brief),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.8,
                response_mime_type="application/json",
                response_schema=StrategyResult,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the UI
        raise RuntimeError(_friendly_api_error(exc)) from exc

    # response.parsed is typed broadly by the SDK (BaseModel | dict | Enum | None);
    # narrow it to our schema and only trust an actual StrategyResult.
    parsed = response.parsed
    result: StrategyResult | None = parsed if isinstance(parsed, StrategyResult) else None
    if result is None:
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response. Try regenerating.")
        try:
            result = StrategyResult.model_validate_json(text)
        except Exception:  # noqa: BLE001 - fall through to the Markdown degrade path
            result = None

    if result is not None and result.campaigns:
        result.fallback_markdown = None
        return result

    # Degrade: re-request in the proven Markdown mode.
    try:
        markdown = _generate_markdown(brief, client=client, model=model)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(_friendly_api_error(exc)) from exc
    return StrategyResult(fallback_markdown=markdown)
