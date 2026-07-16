"""Core strategy generation for Meta-Boost, powered by Google Gemini.

Takes a structured campaign brief and returns a full, Markdown-formatted set of
micro-campaign strategies (flows, A/B tests, simulated KPIs with PM-style rationale).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from google import genai
from google.genai import errors, types

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

PROMPT_TEMPLATE = """\
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
    # httpx raises ConnectError/TimeoutException etc. for transport failures.
    if isinstance(exc, (ConnectionError, TimeoutError)) or "timeout" in type(exc).__name__.lower():
        return "Couldn't reach Gemini — check your network connection and try again."
    return "Gemini request failed unexpectedly. Please try regenerating."


def build_prompt(brief: CampaignBrief) -> str:
    return PROMPT_TEMPLATE.format(
        business_type=brief.business_type,
        product_service=brief.product_service,
        target_audience=brief.target_audience,
        offering=brief.offering,
        marketing_goal=brief.marketing_goal,
        channel=brief.channel,
        tone=brief.tone,
    )


def generate_strategy(
    brief: CampaignBrief,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Call Gemini and return the generated campaign plan as Markdown.

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
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the UI
        raise RuntimeError(_friendly_api_error(exc)) from exc

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response. Try regenerating.")
    return text
