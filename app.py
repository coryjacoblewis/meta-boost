"""Meta-Boost — AI-Powered Micro-Campaign Strategist for SMBs.

Streamlit front end. Collects a business brief, calls the Gemini strategy engine,
and renders actionable conversational micro-campaigns. Includes a mock freemium
"Upgrade to Pro" tier to demonstrate the monetization flow.
"""

from __future__ import annotations

from dotenv import load_dotenv

import streamlit as st

from plans import FREE_LIMIT, FREE_PLAN, PRO_PLAN, at_free_limit, usage_fraction
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

load_dotenv()

st.set_page_config(page_title="Meta-Boost", page_icon="🚀", layout="centered")

# --- Session defaults ----------------------------------------------------------

st.session_state.setdefault("plan", FREE_PLAN)
st.session_state.setdefault("gen_count", 0)
st.session_state.setdefault("result", None)
st.session_state.setdefault("error", None)
st.session_state.setdefault("current_brief", None)


def _run_generation(brief: CampaignBrief) -> None:
    """Generate a strategy and store the result (or error) in session state."""
    with st.spinner("Strategizing your micro-campaigns…"):
        try:
            st.session_state.result = generate_strategy(brief)
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


def render_result(result: StrategyResult) -> None:
    """Render a structured result, or the degraded Markdown view."""
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
        st.toast("Welcome to Pro! (mock upgrade — billing isn't wired up in this MVP)")
        st.rerun()
    st.caption(
        "This is a prototype: the upgrade demonstrates the monetization flow; no payment "
        "is processed."
    )


def attempt_generation(brief: CampaignBrief) -> None:
    """Gate on the free limit, otherwise generate and count the usage."""
    if at_free_limit(st.session_state.plan, st.session_state.gen_count):
        upgrade_dialog()
        return
    _run_generation(brief)
    if st.session_state.error is None:
        st.session_state.gen_count += 1
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
            upgrade_dialog()
        if used > 0:
            if st.button("Reset usage (demo)", use_container_width=True):
                st.session_state.gen_count = 0
                st.rerun()

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
    )
    product_service = st.text_input(
        "Primary product or service",
        placeholder="e.g., Handmade summer dresses",
    )
    target_audience = st.text_area(
        "Target audience",
        placeholder="e.g., Gen Z, trend-conscious, urban, budget-aware",
        height=80,
    )

    st.subheader("2. Your campaign")
    offering = st.text_input(
        "Current offering or promotion",
        placeholder="e.g., 20% off the summer collection this week",
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
            attempt_generation(st.session_state.current_brief)
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
