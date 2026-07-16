# Meta-Boost: AI-Powered Micro-Campaign Strategist for SMBs

**Tagline:** Unlock personalized conversational marketing on Meta platforms, instantly.

## Core Concept

Meta-Boost is a web-based prototype that acts as an AI-powered strategic co-pilot for
Small and Medium Businesses (SMBs). It helps SMBs — who typically lack marketing teams,
time, and budget — rapidly generate personalized, actionable micro-campaigns for Meta's
messaging platforms (WhatsApp Business, Messenger, Instagram DMs).

It abstracts marketing strategy and conversational design into an intuitive AI
interaction, guiding SMBs from a basic idea to a full, actionable conversational campaign
plan — complete with A/B test suggestions and simulated performance insights — in minutes.

Purpose: a portfolio/weekend build demonstrating skills for a **Meta Business Agents
Growth PM** role.

## Target Users (SMBs)

Owners and marketing managers of SMBs with limited budgets who act as their own marketing
department:
- **E-commerce stores** — drive sales, promote products, recover abandoned carts via DMs.
- **Local businesses** (restaurants, salons, boutiques) — foot traffic, specials, bookings.
- **Service providers** (consultants, coaches, freelancers) — lead gen, nurture prospects.

## Problem Solved

- **Lack of expertise** — SMBs don't know what campaigns to run or how to design flows.
- **Time & resource constraints** — no budget for agencies or specialists.
- **Complexity of Meta's business tools** — overwhelming to navigate for strategy.
- **Generality of existing AI tools** — produce generic copy, not tactical, channel-specific,
  multi-step strategic plans with performance rationale.

Meta-Boost delivers "expertise on demand."

## Key Features (MVP — scoped for a 16–24h weekend build)

### 1. Intuitive Onboarding & Input Flow (Streamlit UI)
Clean, multi-step UI capturing structured inputs. Session-based only — no auth, no DB.

Inputs captured:
- **Business Profile:** Business Type, Primary Product/Service, Target Audience
  (demographics/psychographics).
- **Current Offering/Promotion:** e.g., "20% off summer collection."
- **Marketing Goal:** awareness / traffic / leads / sales / retention.
- **Preferred Meta Channel:** WhatsApp Business / Messenger / Instagram DMs.
- **Desired Tone:** friendly / professional / bold / etc.

### 2. AI-Powered Strategic Generation (Gemini core)
Uses the Google Gemini API (via the `google-genai` SDK) to generate:
- **2–3 distinct micro-campaign strategies** — each with a catchy title, strategy brief,
  and clear primary CTA.
- **Detailed conversational flows** — step-by-step multi-turn scripts with an initial
  message, conditional responses (interested / question / not now), and integrated CTAs.
- **A/B test variations** — 1–2 alternative phrasings/CTAs for key messages, each with a
  rationale for why it might perform differently.
- **Simulated KPI predictions & rationale** — plausible Open Rate, CTR, Conversion Rate
  estimates with a "PM-style" justification of *why* those metrics are predicted and how
  the strategy optimizes for the stated goal. (Clearly framed as plausible estimates, not
  real-time predictions.)

Output format: structured Markdown (headings, nested lists) for clean rendering.

### 3. Iterative Review & Refinement
"Regenerate" / "Adjust Parameters" — re-run generation with updated inputs.

### 4. Export
Copy-to-clipboard and download as text/Markdown.

## Technical Stack (weekend-feasible)

- **Frontend & app logic:** Python + Streamlit.
- **AI backend:** Python + Google Gemini API (`google-genai` SDK).
- **No database** — session-based inputs.
- **Deployment (demo):** Streamlit Cloud or Render.com; optional Docker Compose.

## Known Challenges

- **Prompt engineering nuance** — consistent, well-structured, multi-component output with
  thoughtful PM-style KPI rationale is the main time sink.
- **API rate limits** — need friendly error handling for rapid regenerations.
- **Streamlit state management** — clear plan for iterative input adjustments.
- **Managing "simulated" KPI expectations** — clearly label estimates vs. predictions.

## Skills Demonstrated (Meta Business Agents Growth PM)

Product-Led Growth (SMBs) · AI Integration & Prompt Engineering · Growth Strategy & Funnel
Optimization · Onboarding & Activation · Monetization (conceptual: freemium/tiered, Meta
Ads integration, Agent-as-a-Service) · Experimentation (A/B tests) · 0→1 Mindset ·
Conversational AI / Business Agents · Data-Driven Approach.

## Suggested Enhancements (from review, optional)

- Strict JSON schema for a component (e.g., flow steps) parsed into interactive UI.
- Mock "Upgrade to Pro" monetization modal.
- Targeted section regeneration (prompt chaining) instead of full regenerate.
- Visual flowchart of a conversational flow.
- Small KPI comparison "dashboard" (st.dataframe).
