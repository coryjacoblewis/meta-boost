# Structured Flow Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Meta-Boost's single Markdown output with a hybrid structured result whose conversational flow is deeply typed and rendered as an interactive chat thread, degrading gracefully to the existing Markdown path on parse failure.

**Architecture:** `strategist.py` gains Pydantic models and requests Gemini structured output (`response_schema`). `generate_strategy` returns a `StrategyResult` (typed campaigns) or, on parse failure, a `StrategyResult` carrying `fallback_markdown` produced by the retained Markdown prompt. `app.py` renders the flow with `st.chat_message` bubbles and KPIs as `st.metric` tiles; download/copy feed from `result_to_markdown`.

**Tech Stack:** Python 3.11+, Streamlit, google-genai, Pydantic v2, pytest.

## Global Constraints

- Python floor: **3.11** (CI matrix is 3.11 + 3.12; use only stdlib features available in 3.11).
- Provider isolation: all Gemini access stays in `strategist.py`; `app.py` imports only names from `strategist`.
- No secret/raw-SDK leakage in user-facing errors — keep routing through `_friendly_api_error`.
- Tests mock the SDK at the boundary (no network, no API key); the suite must run with `pytest` alone.
- KPI figures remain framed as plausible estimates (existing disclaimer caption stays).
- Dependency addition limited to `pydantic>=2` (already transitively present via `google-genai`).

---

### Task 1: Data models + pydantic dependency

**Files:**
- Modify: `strategist.py` (add models near the top, after imports/constants)
- Modify: `requirements.txt` (add `pydantic>=2`)
- Test: `tests/test_strategist.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Turn`, `Branch`, `Flow`, `Kpis`, `Campaign`, `StrategyResult` (Pydantic v2 `BaseModel`s). `StrategyResult(campaigns: list[Campaign] = [], recommended_next: str = "", fallback_markdown: str | None = None)`.

- [ ] **Step 1: Add the dependency**

Edit `requirements.txt` to:

```
streamlit>=1.40
google-genai>=1.0
python-dotenv>=1.0
pydantic>=2
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_strategist.py`:

```python
def test_strategy_result_models_build_a_full_campaign() -> None:
    campaign = strategist.Campaign(
        title="Bean Quiz",
        brief="A fun quiz.",
        flow=strategist.Flow(
            opener="Hey! Quick question?",
            branches=[
                strategist.Branch(
                    reaction_label="interested",
                    turns=[strategist.Turn(speaker="User", text="Yes!"),
                           strategist.Turn(speaker="Business", text="Great — here's the link.")],
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_strategist.py::test_strategy_result_models_build_a_full_campaign -v`
Expected: FAIL with `AttributeError: module 'strategist' has no attribute 'Campaign'`

- [ ] **Step 4: Add the models**

In `strategist.py`, add the import and models after the existing `CHANNELS/GOALS/TONES` constants (keep the existing `CampaignBrief` dataclass as-is):

```python
from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    speaker: Literal["Business", "User"]
    text: str


class Branch(BaseModel):
    reaction_label: str = Field(description="Short label for the user reaction, e.g. 'interested', 'asks a question', 'not now'.")
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
    ab_tests_md: str = Field(description="Markdown: two A/B tests (opening message + in-flow CTA), each with Variation A/B and a rationale naming the lever.")
    kpis: Kpis
    rationale: str = Field(description="Markdown: PM rationale anchoring each KPI to a rough benchmark.")


class StrategyResult(BaseModel):
    campaigns: list[Campaign] = []
    recommended_next: str = ""
    fallback_markdown: str | None = Field(
        default=None,
        description="Internal use only; always leave null.",
    )
```

Add `from typing import Literal` and the pydantic import to the existing import block (top of file) rather than mid-file if that matches the file's style; the models themselves go after the constants.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_strategist.py::test_strategy_result_models_build_a_full_campaign -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add strategist.py requirements.txt tests/test_strategist.py
git commit -m "feat: add pydantic models for structured strategy output"
```

---

### Task 2: `result_to_markdown` reconstruction

**Files:**
- Modify: `strategist.py`
- Test: `tests/test_strategist.py`

**Interfaces:**
- Consumes: `StrategyResult`, `Campaign`, `Flow` from Task 1.
- Produces: `result_to_markdown(result: StrategyResult) -> str`. If `result.fallback_markdown` is set, returns it verbatim; otherwise rebuilds a full Markdown document.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_strategist.py`:

```python
def test_result_to_markdown_includes_titles_kpis_and_next(brief) -> None:
    result = strategist.StrategyResult(
        campaigns=[
            strategist.Campaign(
                title="Bean Quiz",
                brief="A fun quiz.",
                flow=strategist.Flow(
                    opener="Hey! Quick question?",
                    branches=[strategist.Branch(reaction_label="interested",
                              turns=[strategist.Turn(speaker="Business", text="Here's the link.")])],
                    final_cta="Tap to claim.",
                ),
                ab_tests_md="*A/B test*\n- A\n- B",
                kpis=strategist.Kpis(open_rate="75%", click_through_rate="22%", conversion_rate="6%"),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategist.py -k result_to_markdown -v`
Expected: FAIL with `AttributeError: module 'strategist' has no attribute 'result_to_markdown'`

- [ ] **Step 3: Implement `result_to_markdown`**

Add to `strategist.py`:

```python
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
    return "\n".join([
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
    ])


def result_to_markdown(result: StrategyResult) -> str:
    if result.fallback_markdown is not None:
        return result.fallback_markdown
    blocks = [_campaign_to_markdown(c) for c in result.campaigns]
    doc = "\n\n---\n\n".join(blocks)
    if result.recommended_next:
        doc += f"\n\n## Recommended next step\n\n{result.recommended_next}"
    return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategist.py -k result_to_markdown -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add strategist.py tests/test_strategist.py
git commit -m "feat: reconstruct markdown from structured StrategyResult"
```

---

### Task 3: Structured generation + graceful degrade

**Files:**
- Modify: `strategist.py` (prompts + `generate_strategy` + `_generate_markdown`)
- Test: `tests/test_strategist.py` (update `_FakeModels`, rewrite the success test, add degrade test)

**Interfaces:**
- Consumes: `StrategyResult` (Task 1), `result_to_markdown` (Task 2), existing `_friendly_api_error`, `CampaignBrief`, `SYSTEM_INSTRUCTION`, `DEFAULT_MODEL`.
- Produces: `generate_strategy(brief, api_key=None, model=None) -> StrategyResult`; `build_prompt(brief) -> str` (now the *structured* prompt, still contains every brief field); `build_markdown_prompt(brief) -> str` (the legacy prompt); `_generate_markdown(brief, *, client, model=None) -> str`.

- [ ] **Step 1: Update `_FakeModels` and rewrite the affected tests**

Replace the existing `_FakeModels` class and the `test_generate_strategy_returns_stripped_text` test in `tests/test_strategist.py` with:

```python
class _FakeModels:
    """Stands in for client.models. Returns structured vs markdown replies by
    inspecting whether the call requested a response_schema."""

    def __init__(self, *, parsed=None, text="", markdown_text="## Campaign 1\n\nMD body",
                 raise_exc: Exception | None = None) -> None:
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


def _valid_result() -> "strategist.StrategyResult":
    return strategist.StrategyResult(
        campaigns=[
            strategist.Campaign(
                title="Bean Quiz",
                brief="A fun quiz.",
                flow=strategist.Flow(
                    opener="Hey!",
                    branches=[strategist.Branch(reaction_label="interested",
                              turns=[strategist.Turn(speaker="Business", text="Link.")])],
                    final_cta="Tap.",
                ),
                ab_tests_md="*A/B*\n- A\n- B",
                kpis=strategist.Kpis(open_rate="75%", click_through_rate="22%", conversion_rate="6%"),
                rationale="Reasons.",
            )
        ],
        recommended_next="Run it.",
    )


def test_generate_strategy_returns_parsed_structured_result(monkeypatch, brief) -> None:
    models = _FakeModels(parsed=_valid_result())
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert isinstance(result, strategist.StrategyResult)
    assert result.campaigns[0].title == "Bean Quiz"
    assert result.fallback_markdown is None
    # Structured request carried a response_schema and the brief content.
    call = models.calls[0]
    assert brief.business_type in call["contents"]
    assert getattr(call["config"], "response_schema", None) is strategist.StrategyResult


def test_generate_strategy_degrades_to_markdown_on_parse_failure(monkeypatch, brief) -> None:
    # parsed None + non-JSON text => degrade; second (markdown) call supplies the body.
    models = _FakeModels(parsed=None, text="not json at all",
                         markdown_text="## Campaign 1\n\nDegraded body")
    _patch_client(monkeypatch, models)

    result = generate_strategy(brief, api_key="test-key")

    assert result.fallback_markdown == "## Campaign 1\n\nDegraded body"
    assert result.campaigns == []
    assert len(models.calls) == 2  # structured attempt + markdown fallback
```

Also update the two existing tests that assumed a string return:
- `test_generate_strategy_uses_key_and_model_overrides`: change `_FakeModels("ok")` to `_FakeModels(parsed=_valid_result())`.
- `test_generate_strategy_falls_back_to_env_key`: change `_FakeModels("ok")` to `_FakeModels(parsed=_valid_result())` and assert `generate_strategy(brief).campaigns[0].title == "Bean Quiz"`.

The empty/none/error tests use `raise_exc` or empty text and still pass unchanged, but update their constructor calls to keyword form: `_FakeModels(parsed=None, text="   ")` for empty, `_FakeModels(parsed=None, text=None)` for none, `_FakeModels(raise_exc=...)` for errors.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategist.py -v`
Expected: FAIL — new structured/degrade tests fail (return type mismatch / no response_schema on the call).

- [ ] **Step 3: Split the prompt and rewire generation**

In `strategist.py`, rename the current `PROMPT_TEMPLATE` to `MARKDOWN_PROMPT_TEMPLATE` (unchanged text), and add a structured template plus the new functions. Add a structured prompt template:

```python
STRUCTURED_PROMPT_TEMPLATE = """\
Design micro-campaigns for this business and return them as structured data.

- **Business type:** {business_type}
- **Primary product/service:** {product_service}
- **Target audience:** {target_audience}
- **Current offering/promotion:** {offering}
- **Primary marketing goal:** {marketing_goal}
- **Preferred Meta channel:** {channel}
- **Desired tone:** {tone}

Produce 2-3 distinct campaigns. For each campaign fill every field:
- `title`: catchy title.
- `brief`: 2-3 sentence concept + primary CTA (Markdown).
- `flow`: an `opener` message from the business, then `branches` — one per likely
  user reaction (e.g. interested / asks a question / not now). Each branch has a
  `reaction_label` and a short `turns` list alternating speaker "Business"/"User".
  End with a single `final_cta`. Write copy specific to {channel} that an SMB could
  send as-is.
- `ab_tests_md` (Markdown): TWO A/B tests — one for the opening message, one for a
  key in-flow CTA — each with **Variation A**, **Variation B**, and a **Rationale**
  naming the lever (urgency, social proof, personalization, clarity, etc.).
- `kpis`: open_rate, click_through_rate, conversion_rate as percent strings (e.g. "72%").
  Keep them realistic and varied across campaigns, not uniformly rosy.
- `rationale` (Markdown): explain why the KPIs are plausible, anchoring each to a
  rough industry benchmark, and connect the campaign to the goal of "{marketing_goal}".

Also set `recommended_next` (Markdown): which campaign to run first and why.
Leave `fallback_markdown` null.
"""
```

Replace `build_prompt` and `generate_strategy`, and add helpers:

```python
def build_prompt(brief: CampaignBrief) -> str:
    return STRUCTURED_PROMPT_TEMPLATE.format(**_brief_fields(brief))


def build_markdown_prompt(brief: CampaignBrief) -> str:
    return MARKDOWN_PROMPT_TEMPLATE.format(**_brief_fields(brief))


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


def _generate_markdown(brief: CampaignBrief, *, client, model: str | None = None) -> str:
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

    result = response.parsed
    if result is None:
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response. Try regenerating.")
        try:
            result = StrategyResult.model_validate_json(text)
        except Exception:  # noqa: BLE001 - fall through to degrade
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
```

- [ ] **Step 4: Run the full engine test suite**

Run: `pytest tests/test_strategist.py -v`
Expected: PASS (all — structured success, degrade, overrides, env fallback, missing key, empty, none, error mapping, no-leak, result_to_markdown, models).

- [ ] **Step 5: Commit**

```bash
git add strategist.py tests/test_strategist.py
git commit -m "feat: request Gemini structured output with markdown degrade"
```

---

### Task 4: Interactive rendering in the UI

**Files:**
- Modify: `app.py` (imports, `_run_generation` result handling, results section)
- Manual verification (Streamlit UI is not unit-tested)

**Interfaces:**
- Consumes: `generate_strategy` (returns `StrategyResult`), `result_to_markdown`, and the model types from `strategist`.
- Produces: `render_result(result)` and `render_flow(flow)` in `app.py`; `st.session_state.result` now holds a `StrategyResult`.

- [ ] **Step 1: Update imports**

In `app.py`, extend the `from strategist import (...)` block to also import `StrategyResult`, `Flow`, and `result_to_markdown`:

```python
from strategist import (
    CHANNELS,
    GOALS,
    TONES,
    CampaignBrief,
    Flow,
    StrategyResult,
    generate_strategy,
    result_to_markdown,
)
```

- [ ] **Step 2: Add the render functions**

Add near the top of `app.py` (after `_run_generation`):

```python
def render_flow(flow: Flow) -> None:
    with st.chat_message("Business", avatar="🏪"):
        st.markdown(flow.opener)
    for branch in flow.branches:
        st.markdown(f"**↳ If the user is _{branch.reaction_label}_:**")
        for turn in branch.turns:
            avatar = "🏪" if turn.speaker == "Business" else "👤"
            with st.chat_message(turn.speaker, avatar=avatar):
                st.markdown(turn.text)
    with st.chat_message("Business", avatar="🏪"):
        st.markdown(f"**Final CTA:** {flow.final_cta}")


def render_result(result: StrategyResult) -> None:
    if result.fallback_markdown is not None:
        st.caption("Showing the basic view for this result.")
        st.markdown(result.fallback_markdown)
        return
    for campaign in result.campaigns:
        st.header(campaign.title)
        st.markdown(campaign.brief)
        st.markdown("**Conversational flow**")
        render_flow(campaign.flow)
        st.markdown("**Simulated KPI predictions** *(plausible estimates, not guarantees)*")
        c1, c2, c3 = st.columns(3)
        c1.metric("Open rate", campaign.kpis.open_rate)
        c2.metric("Click-through", campaign.kpis.click_through_rate)
        c3.metric("Conversion", campaign.kpis.conversion_rate)
        st.markdown(campaign.ab_tests_md)
        st.markdown(f"**PM rationale:** {campaign.rationale}")
        st.divider()
    if result.recommended_next:
        st.subheader("Recommended next step")
        st.markdown(result.recommended_next)
```

- [ ] **Step 3: Rewire the results section**

In the results block at the bottom of `app.py`, the download button and copy expander must feed from `result_to_markdown(...)`, and the body must call `render_result(...)`. Replace the current `st.markdown(st.session_state.result)` usage:

```python
if st.session_state.get("result"):
    result = st.session_state.result
    markdown_doc = result_to_markdown(result)
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Regenerate", use_container_width=True):
            attempt_generation(st.session_state.current_brief)
    with col_b:
        st.download_button(
            "⬇️ Download as Markdown",
            data=markdown_doc,
            file_name="meta-boost-campaigns.md",
            mime="text/markdown",
            use_container_width=True,
        )

    if _at_free_limit():
        st.info(
            f"You've used all {FREE_LIMIT} free generations this session. "
            "Upgrade to Pro for unlimited campaigns."
        )

    render_result(result)

    with st.expander("Copy raw Markdown"):
        st.code(markdown_doc, language="markdown")

    st.caption(
        "⚠️ KPI figures are AI-generated plausible planning estimates, not guarantees "
        "or real-time predictions."
    )
```

(The `error` handling block above it is unchanged.)

- [ ] **Step 4: Manual verification**

Run: `streamlit run app.py` (with a real `GEMINI_API_KEY` in `.env`).
Fill the sample brief (coffee shop) and generate. Confirm:
- flow renders as chat bubbles with 🏪/👤 avatars and branch dividers;
- three KPI metric tiles appear in a row;
- A/B tests + rationale render;
- Download and "Copy raw Markdown" produce a full document.

Then temporarily force the degrade path to confirm fallback: in `generate_strategy`, comment out the `response_schema=StrategyResult` line so `response.parsed` is None and the text is prose → confirm the basic Markdown view renders. Restore the line afterward.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: render structured flow as chat thread with KPI tiles"
```

---

### Task 5: Verify, ship, redeploy, refresh docs

**Files:**
- Modify: `README.md` (only if the structure/feature description needs a touch-up), `docs/*.jpg` (screenshots)

- [ ] **Step 1: Full suite + compile check**

Run: `python -m py_compile app.py strategist.py && pytest -q`
Expected: compile OK; all tests pass.

- [ ] **Step 2: Push and confirm CI**

```bash
git push origin main
```
Then check `https://github.com/coryjacoblewis/meta-boost/actions` is green.

- [ ] **Step 3: Redeploy + smoke-test**

Streamlit Cloud auto-redeploys from `main`. Open the live URL, run one generation, confirm the interactive flow renders and there are no console errors.

- [ ] **Step 4: Refresh screenshots**

Recapture `docs/02-campaign.jpg` (and others if changed) from the new interactive view. Commit:

```bash
git add docs/ README.md
git commit -m "docs: refresh screenshots for interactive flow view"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- Hybrid flow-only structuring → Tasks 1 (models) + 3 (structured prompt/generation). ✓
- Graceful degrade to Markdown path → Task 3 (`_generate_markdown` + degrade branch) + Task 4 (`render_result` fallback). ✓
- One reaction-level branching → `Flow`/`Branch` models (Task 1). ✓
- Interactive chat rendering + KPI metric tiles → Task 4. ✓
- Download/copy from reconstructed Markdown → Task 2 (`result_to_markdown`) + Task 4 wiring. ✓
- Error contracts unchanged (missing key, empty, `_friendly_api_error`, no raw leak) → Task 3 tests. ✓
- `pydantic>=2` dependency → Task 1. ✓
- Verify/deploy/screenshots → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `StrategyResult`, `Campaign`, `Flow`, `Branch`, `Turn`, `Kpis`, `generate_strategy -> StrategyResult`, `result_to_markdown(result)`, `render_flow(flow)`, `render_result(result)`, `build_prompt`/`build_markdown_prompt`/`_generate_markdown` are named identically across all tasks. KPI fields `open_rate`/`click_through_rate`/`conversion_rate` are consistent between model, prompt, `result_to_markdown`, and `render_result`. ✓
