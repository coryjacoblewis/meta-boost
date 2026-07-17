# Meta-Boost — Design Notes

Planning notes behind the build. For the product overview, features, setup, and
monetization framing, see the [README](README.md); this doc only captures detail
that doesn't live there — who it's for, the exact I/O contract, and the known
build risks.

## Target Users (SMBs)

Owners and marketing managers of SMBs with limited budgets who act as their own marketing
department:

- **E-commerce stores** — drive sales, promote products, recover abandoned carts via DMs.
- **Local businesses** (restaurants, salons, boutiques) — foot traffic, specials, bookings.
- **Service providers** (consultants, coaches, freelancers) — lead gen, nurture prospects.

## Input / output contract

**Inputs captured** (structured brief, session-only — no auth, no DB):

- **Business Profile:** Business Type, Primary Product/Service, Target Audience
  (demographics/psychographics).
- **Current Offering/Promotion:** e.g., "20% off summer collection."
- **Marketing Goal:** awareness / traffic / leads / sales / retention.
- **Preferred Meta Channel:** WhatsApp Business / Messenger / Instagram DMs.
- **Desired Tone:** friendly / professional / bold / etc.

**Generated output** (structured Markdown — headings + nested lists for clean rendering):

- **2–3 distinct micro-campaign strategies** — each with a title, strategy brief, and
  primary CTA.
- **Conversational flows** — multi-turn scripts with an initial message, conditional
  branches (interested / question / not now), and integrated CTAs.
- **A/B test variations** — 1–2 alternative phrasings/CTAs per key message, each with a
  rationale for why it might perform differently.
- **Simulated KPI predictions** — plausible Open Rate, CTR, and Conversion Rate estimates
  with a PM-style justification of *why* each figure is predicted and how the strategy
  optimizes for the stated goal. (Framed as planning estimates, not real-time predictions.)

## Known challenges

- **Prompt engineering nuance** — consistent, well-structured, multi-component output with
  thoughtful PM-style KPI rationale is the main time sink.
- **API rate limits** — friendly error handling for rapid regenerations.
- **Streamlit state management** — a clear plan for iterative input adjustments.
- **Managing "simulated" KPI expectations** — clearly label estimates vs. predictions.
