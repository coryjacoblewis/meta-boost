"""Meta-Boost — AI-Powered Micro-Campaign Strategist for SMBs.

Streamlit front end. Collects a business brief, calls the Gemini strategy engine,
and renders actionable conversational micro-campaigns. Includes a mock freemium
"Upgrade to Pro" tier to demonstrate the monetization flow.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import streamlit as st
from dotenv import load_dotenv

import analytics
from analytics import Funnel
from plans import (
    FREE_LIMIT,
    FREE_PLAN,
    PRO_PLAN,
    DailyUsage,
    at_free_limit,
    try_consume_daily,
    usage_fraction,
)
from strategist import (
    CHANNELS,
    GOALS,
    TONES,
    Campaign,
    CampaignBrief,
    Flow,
    StrategyResult,
    generate_strategy,
    result_to_markdown,
)

load_dotenv()

st.set_page_config(page_title="Meta-Boost", page_icon="🚀", layout="centered")

# --- Responsive columns --------------------------------------------------------
# Streamlit's st.columns() shrinks rather than stacks on narrow viewports, which
# crushes the 3-up KPI tiles and feature cards on phones. There's no native
# breakpoint API, so make column rows wrap below a phone-ish width: each column
# takes a full line instead of being squeezed. Applies to every st.columns() row.
st.markdown(
    """
    <style>
    @media (max-width: 640px) {
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Session defaults ----------------------------------------------------------

analytics.configure()

st.session_state.setdefault("plan", FREE_PLAN)
st.session_state.setdefault("gen_count", 0)
st.session_state.setdefault("result", None)
st.session_state.setdefault("error", None)
st.session_state.setdefault("current_brief", None)
st.session_state.setdefault("regen_nonce", 0)
st.session_state.setdefault("funnel", Funnel())


# --- Demo cost guards ----------------------------------------------------------
# The public demo runs on a shared API key, so several guards bound its cost:
#   1. a global daily generation cap (below), enforced across every session,
#   2. a per-brief result cache, so repeat briefs cost neither a quota unit nor
#      an API call (regeneration deliberately bypasses the cache, see below), and
#   3. length caps on the free-text brief fields, so a single call's *input*
#      tokens are bounded no matter what a user pastes in.

# Max characters accepted per free-text brief field. Generous enough for a real
# brief, tight enough to keep input tokens (and cost) bounded on every call.
BRIEF_FIELD_MAX_CHARS = 200
BRIEF_TEXTAREA_MAX_CHARS = 400

DAILY_LIMIT_MESSAGE = (
    "The shared demo has hit its daily generation limit — this keeps the public "
    "demo's API costs bounded. Please try again tomorrow, or run Meta-Boost "
    "locally with your own Gemini key (see the README)."
)


@st.cache_resource
def _daily_usage_store() -> DailyUsage:
    """Process-wide daily tally, shared across every session of this app.

    ``st.cache_resource`` returns one instance for the whole server process, so
    all sessions increment the same counter. It resets on cold start — acceptable
    for a demo guard whose only job is to bound worst-case spend.
    """
    return DailyUsage(day="", count=0)


@st.cache_resource
def _daily_usage_lock() -> threading.Lock:
    """Process-wide lock guarding the shared daily tally.

    Streamlit serves sessions on a thread pool, so ``_consume_daily_quota`` is a
    read-modify-write on shared mutable state that can race: two concurrent
    generations could read the same count and both write ``count + 1``, losing an
    increment and letting the demo quietly overspend its daily cap. One cached
    lock (one instance per process, like the store) serializes that section.
    """
    return threading.Lock()


def _consume_daily_quota() -> bool:
    """Consume one unit of the global daily allowance; False if the cap is hit."""
    store = _daily_usage_store()
    with _daily_usage_lock():
        updated, allowed = try_consume_daily(
            DailyUsage(store.day, store.count),
            datetime.now(UTC).date().isoformat(),
        )
        store.day, store.count = updated.day, updated.count
    return allowed


def _brief_cache_key(brief: CampaignBrief) -> str:
    """Stable key over every brief field, so identical briefs share a cache slot."""
    return "|".join(
        [
            brief.business_type,
            brief.product_service,
            brief.target_audience,
            brief.offering,
            brief.marketing_goal,
            brief.channel,
            brief.tone,
        ]
    )


@st.cache_data(show_spinner=False, ttl=3600, max_entries=256)
def _generate_metered(_brief: CampaignBrief, cache_key: str) -> StrategyResult:
    """Cache-miss generation path, with the global daily guard applied.

    Streamlit skips this body entirely on a cache hit, so a repeated brief costs
    neither a daily unit nor an API call — the guard and the model are only
    reached on a genuine miss. ``_brief`` is underscore-prefixed so Streamlit
    doesn't hash the dataclass; ``cache_key`` is the real key (stable per brief
    for Generate, unique per click for Regenerate). Exceptions aren't cached, so a
    daily-cap rejection never sticks.
    """
    if not _consume_daily_quota():
        raise RuntimeError(DAILY_LIMIT_MESSAGE)
    return generate_strategy(_brief)


def _run_generation(brief: CampaignBrief, *, regenerate: bool = False) -> None:
    """Generate a strategy and store the result (or error) in session state.

    A fresh Generate is cache-first (repeat briefs are free); Regenerate busts the
    cache via a per-click nonce so it always yields a new variation and is metered.
    """
    cache_key = _brief_cache_key(brief)
    if regenerate:
        st.session_state.regen_nonce += 1
        cache_key = f"{cache_key}#regen{st.session_state.regen_nonce}"
    with st.spinner("Strategizing your micro-campaigns…"):
        try:
            st.session_state.result = _generate_metered(brief, cache_key)
            st.session_state.error = None
        except RuntimeError as exc:
            st.session_state.result = None
            st.session_state.error = str(exc)


def render_flow(flow: Flow) -> None:
    """Render a conversational flow as a chat thread with branch dividers."""
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


def render_campaign(campaign: Campaign) -> None:
    """Render one campaign: brief, conversational flow, KPI tiles, A/B tests."""
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


def render_result(result: StrategyResult) -> None:
    """Render a structured result, or the degraded Markdown view.

    Multiple campaigns are split into tabs so they can be compared without an
    endless scroll; a single campaign renders inline.
    """
    if result.fallback_markdown is not None:
        st.caption("Showing the basic view for this result.")
        st.markdown(result.fallback_markdown)
        return
    campaigns = result.campaigns
    if len(campaigns) > 1:
        labels = [f"Campaign {i}" for i in range(1, len(campaigns) + 1)]
        for tab, campaign in zip(st.tabs(labels), campaigns, strict=True):
            with tab:
                render_campaign(campaign)
    elif campaigns:
        render_campaign(campaigns[0])
    if result.recommended_next:
        st.divider()
        st.subheader("Recommended next step")
        st.markdown(result.recommended_next)


def render_empty_state() -> None:
    """Preview what a generation produces, shown before the first run."""
    st.divider()
    st.markdown("#### What you'll get")
    st.caption("2–3 tailored micro-campaigns in under a minute — each one includes:")
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        "💬 **Conversational flows**\n\n"
        "Multi-turn, branching chats ready to send on your channel."
    )
    c2.markdown(
        "🧪 **A/B tests**\n\nTwo variations per campaign, each naming the lever it tests."
    )
    c3.markdown(
        "📈 **KPI estimates**\n\nBenchmark-anchored open, click & conversion projections."
    )
    with st.expander("Preview a sample flow"):
        with st.chat_message("Business", avatar="🏪"):
            st.markdown(
                "Hey there! ☕ Quick question — still drinking supermarket blend "
                "while working from home?"
            )
        with st.chat_message("User", avatar="👤"):
            st.markdown("Tell me more about the beans!")
        with st.chat_message("Business", avatar="🏪"):
            st.markdown(
                "We roast single-origin beans weekly. Want to find your perfect match? "
                "**Take the 30-sec quiz — 30% off your first month.**"
            )


@st.dialog("⚡ Upgrade to Meta-Boost Pro")
def upgrade_dialog() -> None:
    st.write(
        "You're getting real value from Free. **Pro** unlocks unlimited strategy and "
        "the tools to actually run and measure your campaigns."
    )
    col_free, col_pro = st.columns(2)
    with col_free:
        st.markdown("### Free")
        st.markdown("**$0**")
        st.markdown(
            f"- {FREE_LIMIT} generations / session\n"
            "- Up to 3 strategies per brief\n"
            "- Copy & Markdown export"
        )
    with col_pro:
        st.markdown("### Pro")
        st.markdown("**$19 / mo**")
        st.markdown(
            "- ♾️ Unlimited generations\n"
            "- Up to 6 strategies + tone presets\n"
            "- One-click export to Meta Ads Manager\n"
            "- Live performance tracking dashboard\n"
            "- Saved brand voice & campaign history\n"
            "- Priority model (deeper reasoning)"
        )
    st.divider()
    if st.button("Start Pro — $19/mo", type="primary", use_container_width=True):
        st.session_state.plan = PRO_PLAN
        analytics.log_event(analytics.EVENT_UPGRADE_CONFIRM)
        st.toast("Welcome to Pro! (mock upgrade — billing isn't wired up in this MVP)")
        st.rerun()
    st.caption(
        "This is a prototype: the upgrade demonstrates the monetization flow; no payment "
        "is processed."
    )


def _open_upgrade_dialog(source: str) -> None:
    """Record the upgrade-intent event, then show the dialog."""
    st.session_state.funnel.upgrade_clicks += 1
    analytics.log_event(analytics.EVENT_UPGRADE_CLICK, source=source)
    upgrade_dialog()


def attempt_generation(brief: CampaignBrief, *, regenerate: bool = False) -> None:
    """Gate on the free limit, otherwise generate and count the usage."""
    if at_free_limit(st.session_state.plan, st.session_state.gen_count):
        _open_upgrade_dialog("paywall")
        return
    st.session_state.funnel.generations += 1
    analytics.log_event(
        analytics.EVENT_GENERATE,
        regenerate=regenerate,
        goal=brief.marketing_goal,
        channel=brief.channel,
        tone=brief.tone,
    )
    _run_generation(brief, regenerate=regenerate)
    if st.session_state.error is None:
        st.session_state.gen_count += 1
        st.session_state.funnel.results += 1
        result = st.session_state.result
        analytics.log_event(
            analytics.EVENT_RESULT_SHOWN,
            campaigns=len(result.campaigns) if result else 0,
            degraded=bool(result and result.fallback_markdown is not None),
        )
    # Rerun so the sidebar counter/meter reflect the new count immediately
    # (the sidebar renders earlier in the script, before this increment).
    st.rerun()


# --- Sidebar: plan & usage -----------------------------------------------------

with st.sidebar:
    st.markdown("### Your plan")
    if st.session_state.plan == PRO_PLAN:
        st.success("**Pro** — unlimited ♾️")
        if st.button("Manage plan", use_container_width=True):
            st.session_state.plan = FREE_PLAN
            st.session_state.gen_count = 0
            st.rerun()
    else:
        used = st.session_state.gen_count
        st.info(f"**Free** — {used}/{FREE_LIMIT} generations used")
        st.progress(usage_fraction(used))
        if st.button("⚡ Upgrade to Pro", type="primary", use_container_width=True):
            _open_upgrade_dialog("sidebar")
        if used > 0:
            if st.button("Reset usage (demo)", use_container_width=True):
                st.session_state.gen_count = 0
                st.rerun()

    # --- Session funnel ---------------------------------------------------------
    # A tiny live view of this session's funnel. The same events are emitted as
    # structured logs (see analytics.py) for offline/aggregate analysis.
    funnel = st.session_state.funnel
    if funnel.form_submits or funnel.generations:
        st.divider()
        st.markdown("### This session")
        fc1, fc2 = st.columns(2)
        fc1.metric("Briefs", funnel.form_submits)
        fc2.metric("Generations", funnel.generations)
        fc3, fc4 = st.columns(2)
        fc3.metric("Results", funnel.results)
        fc4.metric("Upgrade clicks", funnel.upgrade_clicks)
        rate = analytics.success_rate(funnel)
        if rate is not None:
            st.caption(f"Generation success rate: {rate:.0%}")
        st.caption("These events are also emitted as structured logs.")

# --- Header --------------------------------------------------------------------

st.title("🚀 Meta-Boost")
st.caption(
    "Unlock personalized conversational marketing on Meta platforms, instantly. "
    "Describe your business and goal — get ready-to-send micro-campaigns."
)

with st.form("brief"):
    st.subheader("1. Your business")
    business_type = st.text_input(
        "Business type",
        placeholder="e.g., Online fashion boutique, Local coffee shop, B2B SaaS startup",
        max_chars=BRIEF_FIELD_MAX_CHARS,
    )
    product_service = st.text_input(
        "Primary product or service",
        placeholder="e.g., Handmade summer dresses",
        max_chars=BRIEF_FIELD_MAX_CHARS,
    )
    target_audience = st.text_area(
        "Target audience",
        placeholder="e.g., Gen Z, trend-conscious, urban, budget-aware",
        height=80,
        max_chars=BRIEF_TEXTAREA_MAX_CHARS,
    )

    st.subheader("2. Your campaign")
    offering = st.text_input(
        "Current offering or promotion",
        placeholder="e.g., 20% off the summer collection this week",
        max_chars=BRIEF_FIELD_MAX_CHARS,
    )
    marketing_goal = st.selectbox("Primary marketing goal", GOALS)
    channel = st.radio("Preferred Meta channel", CHANNELS, horizontal=True)
    tone = st.selectbox("Desired tone", TONES)

    submitted = st.form_submit_button("Generate campaigns", type="primary")

if submitted:
    required = {
        "Business type": business_type,
        "Primary product or service": product_service,
        "Target audience": target_audience,
        "Current offering or promotion": offering,
    }
    missing = [label for label, value in required.items() if not value.strip()]
    if missing:
        st.warning("Please fill in: " + ", ".join(missing))
    else:
        st.session_state.current_brief = CampaignBrief(
            business_type=business_type.strip(),
            product_service=product_service.strip(),
            target_audience=target_audience.strip(),
            offering=offering.strip(),
            marketing_goal=marketing_goal,
            channel=channel,
            tone=tone,
        )
        st.session_state.funnel.form_submits += 1
        # Log only categorical selections — never the free-text business fields.
        analytics.log_event(
            analytics.EVENT_FORM_SUBMIT,
            goal=marketing_goal,
            channel=channel,
            tone=tone,
        )
        attempt_generation(st.session_state.current_brief)

# --- Results -------------------------------------------------------------------

if st.session_state.get("error"):
    st.error(st.session_state.error)

if st.session_state.get("result"):
    result = st.session_state.result
    markdown_doc = result_to_markdown(result)
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Regenerate", use_container_width=True):
            attempt_generation(st.session_state.current_brief, regenerate=True)
    with col_b:
        st.download_button(
            "⬇️ Download as Markdown",
            data=markdown_doc,
            file_name="meta-boost-campaigns.md",
            mime="text/markdown",
            use_container_width=True,
        )

    if at_free_limit(st.session_state.plan, st.session_state.gen_count):
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

# Before the first generation, preview what the tool produces.
if not st.session_state.get("result") and not st.session_state.get("error"):
    render_empty_state()
