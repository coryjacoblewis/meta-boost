# Structured Flow Output — Design

**Date:** 2026-07-16
**Status:** Approved (design)
**Scope:** Meta-Boost — replace the single Markdown output blob with a hybrid
structured result whose conversational flow is deeply typed and rendered as an
interactive chat thread. Everything else stays Markdown.

## Goal

Turn the flat Markdown campaign output into an interactive, chat-style rendering
of the conversational flow — the single highest-"wow" upgrade for a live portfolio
demo — without materially increasing generation brittleness.

Non-goals (explicitly deferred): clickable/simulatable flows, full-JSON for every
section, targeted per-section regeneration. These are v3 roadmap items.

## Key decisions

1. **Hybrid, flow-only structuring.** Only the conversational flow becomes deeply
   typed. Brief, A/B tests, and PM rationale ride along as Markdown strings inside
   the structured envelope. KPIs are typed (three numbers) so they can render as
   metric tiles. Rationale for the split: the flow is what benefits from interactive
   rendering; the other sections already render well as Markdown, and typing them
   would add schema surface and failure modes for little visible gain.

2. **Graceful degrade to the existing Markdown path.** If structured generation
   fails to parse/validate, fall back to the current Markdown prompt and render with
   `st.markdown` — i.e. exactly today's behavior. Worst case equals today; best case
   is the rich view. Nothing hard-fails in front of a user.

3. **One reaction-level of branching.** Flow shape is `opener → branches[] → final_cta`,
   where each branch is a labeled reaction (e.g. "interested", "asks a question",
   "not now") containing a short turn chain. Accepted tradeoff: today's occasional
   sub-branches ("branch 1a") flatten into the reply chain. This covers the large
   majority of flows, avoids schema recursion (which Gemini structured output handles
   poorly), and renders cleanly.

## Data model

Pydantic v2 models (google-genai accepts a Pydantic model as `response_schema` and
returns the parsed instance on `response.parsed`).

```python
class Turn(BaseModel):
    speaker: Literal["Business", "User"]
    text: str

class Branch(BaseModel):
    reaction_label: str          # e.g. "interested", "asks a question", "not now"
    turns: list[Turn]

class Flow(BaseModel):
    opener: str
    branches: list[Branch]
    final_cta: str

class Kpis(BaseModel):
    open_rate: str               # e.g. "75%" — kept as display strings
    click_through_rate: str
    conversion_rate: str

class Campaign(BaseModel):
    title: str
    brief: str                   # Markdown
    flow: Flow
    ab_tests_md: str             # Markdown (both A/B tests, unchanged format)
    kpis: Kpis
    rationale: str               # Markdown

class StrategyResult(BaseModel):
    campaigns: list[Campaign] = []
    recommended_next: str = ""   # Markdown
    fallback_markdown: str | None = None   # set ONLY on degrade; when present,
                                           # render this and ignore campaigns
```

## Component design

### `strategist.py`

- **`generate_strategy(brief, api_key=None, model=None) -> StrategyResult`**
  (return type changes from `str`). Calls Gemini with
  `response_mime_type="application/json"` and `response_schema=StrategyResult`,
  keeping `system_instruction` and `temperature=0.8`.
  - Success: return `response.parsed` (a `StrategyResult`). If `.parsed` is `None`,
    try `StrategyResult.model_validate_json(response.text)`.
  - Empty text → `RuntimeError("empty response")` (unchanged contract).
  - API/transport errors → `_friendly_api_error(...)` (unchanged).
  - **Structured-parse failure** (validation error / unusable JSON): call the
    internal `_generate_markdown(brief, ...)` fallback and return
    `StrategyResult(fallback_markdown=<md>)`. Only a *parse* failure triggers
    fallback; a missing key or 429 still raises as today.
- **`_generate_markdown(brief, ...) -> str`**: the current prompt/behavior, extracted
  so it serves as the degrade path.
- **`result_to_markdown(result: StrategyResult) -> str`**: reconstruct a full Markdown
  document from the typed object (used by the download button and copy expander). If
  `fallback_markdown` is set, return it verbatim.
- Two prompts: a **structured prompt** (instructs the model to fill the typed schema,
  putting Markdown in the string fields) and the retained **Markdown prompt**
  (current `PROMPT_TEMPLATE`) for the fallback.

### `app.py`

- `_run_generation` stores a `StrategyResult` in `st.session_state.result`.
- New `render_result(result)`:
  - If `result.fallback_markdown`: `st.markdown(result.fallback_markdown)` (today's view)
    plus a small caption noting the basic view.
  - Else, per campaign: `st.header(title)` → `st.markdown(brief)` →
    `render_flow(flow)` → three `st.metric` KPI tiles in `st.columns(3)` →
    `st.markdown(ab_tests_md)` → `st.markdown(rationale)`; then
    `st.markdown(recommended_next)`.
- `render_flow(flow)`:
  - opener as a `st.chat_message("Business", avatar="🏪")` bubble;
  - each branch: a divider line `**↳ If the user is _{reaction_label}_:**`, then its
    turns as `st.chat_message` bubbles (🏪 Business / 👤 User);
  - final CTA as a highlighted Business bubble.
- Download button + "Copy raw Markdown" expander feed from `result_to_markdown(result)`.
- The free-limit gating, upgrade dialog, sidebar, and disclaimers are unchanged.

## Error handling

| Condition | Behavior |
| --- | --- |
| Missing API key | `RuntimeError` friendly message (unchanged) |
| Empty model response | `RuntimeError("empty response")` (unchanged) |
| 401/403, 429, 5xx, network | `_friendly_api_error` mapping (unchanged) |
| Structured JSON invalid/unparseable | Degrade to Markdown prompt; render as today |
| A branch/turn list empty | Render what exists; never crash the page |

## Testing

Mock the SDK at the boundary (as today). `_FakeModels` gains a `parsed` attribute
alongside `text`.

- `generate_strategy` returns a populated `StrategyResult` when `.parsed` is a valid
  object; campaigns/flow/kpis are carried through.
- `.parsed is None` but valid JSON in `.text` → validated into `StrategyResult`.
- Invalid structured output → `fallback_markdown` is populated (degrade path taken),
  no exception raised.
- Existing contracts preserved: missing key, empty response, error mapping
  (bad key / 429 / 5xx / no raw-detail leak).
- `result_to_markdown` round-trip: every campaign title, KPI value, and the
  recommended-next text appear in the output; fallback mode returns the blob verbatim.
- `build_prompt` (structured prompt) still includes every brief field and has no
  unfilled placeholders.

App rendering (`render_flow`, `render_result`) is not unit-tested (Streamlit UI);
it is verified manually via the live app after deploy.

## Dependencies

- Add `pydantic>=2` explicitly to `requirements.txt` (already transitively present
  via `google-genai`; pinning it makes the dependency intentional).

## Rollout / verification

1. Unit tests green (`pytest`).
2. Run locally, generate for a sample brief, confirm chat-bubble flow + metric tiles.
3. Force a parse failure (temporarily) to confirm the Markdown degrade renders.
4. Push → CI green → redeploy on Streamlit Cloud → smoke-test the live link.
5. Refresh `docs/` screenshots if the UI has changed.
