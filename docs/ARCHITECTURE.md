# Torob In-Person Shopping Assistant — Product & Architecture

**Team:** Transformers · **Challenge:** Starcoach Agentic AI Hackathon — Torob challenge (#7)
**Deadline:** 1 Aban 1405, 23:50 (Oct 23, 2026) · **Submission:** public demo video (~5 min, required) + GitHub repo · one submission only
**Status:** design approved, implementation not started

---

## 1. Challenge summary

Build an agentic assistant that helps people shop **in person** at Tehran shops, passages and malls, using Torob's dataset.

**The four steps (from the mandatory challenge video):**
1. Help the user figure out **which product/model** they need: compare products, prices and features.
2. Find **shops that have it**, near the user's location.
3. **Compare shops** on price, distance and opening hours.
4. **Contact the shops** (the agent asks about hours, current price and stock, because many shops don't update them) and report accurate info back.

**Pain points named in the video:**
- The user doesn't know the right model.
- Listed prices are stale; suggests "Let Google Call"-style AI contact with shops.
- The seller doesn't answer, or the shop is closed on arrival → suggest **alternatives immediately**.
- You find the passage but can't find the shop inside it → give a **precise in-passage location**.
- Some users only want shops offering **installment / credit purchase** → a filter for that.

**Judging (300 points):**

| Criterion | Points |
|---|---:|
| Product (solves in-person shopping, covers all requested steps) | 75 |
| UX / UI | 75 |
| Intelligence (follow-up with sellers, alternatives, visit conditions) | 50 |
| Deployment (stability, running in production) | 40 |
| Technical implementation | 40 |
| Dataset usage and transparent display | 20 |

The video stresses that **UX quality is very important** and recommends deploying on **Liara** (sponsor).

---

## 2. Dataset facts (measured)

| Table | Rows | Notes |
|---|---:|---|
| shops | 6,476 | All have coordinates (Tehran only). Phone numbers are all fake; 6,364 names are fake (the 112 with Instagram/website are real). |
| products | 225,903 | 3,428 categories, 2,250 brands |
| offers | 331,506 | One per (shop, product). 3,792 shops have offers; **2,684 shops have none** (category only). |

- Shops cluster in Ferdowsi (3,282), Sheikh Hadi (1,587), Baharestan (616).
- Addresses: 3,671 mention a passage/mall, 4,224 a floor, 6,014 a unit/plaque number.
- Opening hours missing for ~2,000 shops. Payment options on only 266 shops (Torob Pay, Snapp Pay, Digipay, Tara, Azki Vam), with channel `in_person` or `unknown`.
- 15,083 offers have no price; price dates range from 2020 to Oct 2026.
- Listed price ≠ confirmed stock. A shop's category alone ≠ the shop having a product.

Full notes: `docs/DATA_NOTES.md`.

---

## 3. Product decisions

### Demo category: mobile phones
Chosen because it is the **most complex purchase decision** for an everyday consumer. Goal: **make the hardest purchase easy.**

| | Mobile phones | Headphones (runner-up) |
|---|---|---|
| Products | 814 | 1,339 |
| Brand known | 97% | 75% |
| Price range (p10–p90) | 2.7M → 359M toman (130×) | 1.3M → 29.9M (23×) |
| Median price | 70.8M | 4.3M |
| Products with 2+ sellers | 343 | 370 |
| Shops | 134 | 251 |
| Price updated in October | 80% | 55% |
| Warranty listed | 72% | 51% |
| Shops with installments | 14 | 43 |

Only 14 phone shops offer installments, so the assistant warns early that this filter shrinks the options.

### Core idea
The user never needs to read a spec sheet. The assistant turns everyday needs ("good photos of my kids", "battery that lasts a day", "about 25 million") into recommendations, and specs into plain-language trade-offs. **Chat is only the input method**; cards, chips, filters and buttons drive the flow.

### The flow

**Step 0 — Your current phone (optional, one tap to skip)**
- "What phone do you use now?" Typed (Persian, English or Finglish, e.g. "ردمی نوت ۱۰", "a51") or picked from popular-model chips.
- "What bothers you about it?" Chips: slow, battery dies, poor photos, out of storage, broken screen, too big / too small.
- "What do you want to keep?" iOS/Android, size, brand.
- Pain points become weighted priorities automatically.
- Current-phone lookup, source always shown:
  1. In the dataset → "from Torob data".
  2. Curated reference table of ~70 popular phones in Iran (2019–2024) → "from public specs". Needed because common models like Galaxy A14/A51/A54/S21 and Poco X3 are **not** in the dataset.
  3. Otherwise an LLM estimate, labeled "approximate", confirmed by the user before use.

**Step 1 — Find the right phone**
- At most 2–3 questions: main use, budget, brand, must-haves.
- Three recommendations: **best match / cheaper / step up**, each fixing at least one stated pain point.
- Cards show 4 everyday ratings (camera, battery, speed, storage), the reason ("because you take lots of photos and your budget is 25M"), and **"vs your phone"** differences, e.g. "battery +40% vs your A14".
- Plain-language model comparison; raw specs behind a "technical details" expander.
- Missing specs are shown as "not listed", never guessed; ratings show confidence ("based on 6 of 9 key specs").
- Guardrail: never recommend a phone worse on the user's stated pain point.

**Step 2 — Find shops that have it**
- Based on GPS or a chosen area (e.g. Jomhouri, Tajrish).
- 🟢 **Listed**: the shop lists this model. 🟡 **Possible**: category matches but the model isn't listed.

**Step 3 — Compare shops**
- Cards + map, sortable by price, distance, open at visit time, warranty type, price freshness.
- Filters: **installments only**, **open when I arrive**.
- **In-passage locator:** passage, floor, unit parsed from the address, e.g. "Alaeddin 2, floor 6, unit 622".

**Step 4 — Agent contacts shops (simulated)**
- One tap sends the shortlist to the **simulated shop agent**; a live thread shows it asking each shop about stock, current price, warranty, today's hours, and trade-in of the user's old phone.
- Answers update cards: "✅ confirmed by shop just now (simulated)".
- Fallbacks: no answer / sold out / closed → next-best shop (same passage preferred) → other variant → step-down model. Over budget → cheaper model.
- Output: a **visit plan** — shop order, "open until" times, in-passage location, a call script to re-check before leaving.

### Transparency (always visible)
- Listed price, price-change date and confirmed stock are always separate.
- Price freshness: within 7 days / within a month / older (warning).
- Unknown data is shown as unknown: hours not declared, payment channel unknown, price not listed.
- Phone-specific: warranty type (official / store / none); "check registry status before paying" when unknown.
- Simulated seller replies are labeled **"Simulated seller response — demo"** everywhere (all phone numbers in the dataset are fake, so real calls are impossible).

### Demo story (~5 min video)
> Maryam has a Galaxy A14 whose battery dies by afternoon and whose photos are poor. She wants a phone around 20M, will go to Jomhouri tomorrow at 5 pm, and wants installments.

Covers: current phone → pain points → 3 recommendations with "vs your phone" → shops → comparison with installment filter and in-passage location → simulated outreach with one shop not answering → automatic fallback → visit plan.

### Scope
- **Must:** steps 0–4, status badges, opening-hours check, mobile RTL UI, deploy on Liara.
- **Should:** in-passage locator, alternatives, installment/payment filters.
- **Simplified:** visit order is a simple ordered list (no route optimization).
- **Cut:** accounts, real calls/messaging, purchase history, categories other than phones (data model kept category-neutral for the pitch).

---

## 4. LLM provider: BoxAPI (provided by organizers)

- Base URL: `https://ai.boxapi.ir/ai/v1` — OpenAI-compatible `/chat/completions` and `/embeddings`.
- **API key: shared privately with the team; never commit it.** Locally it lives in `.env` (git-ignored); in production it is a Liara environment variable.

Tested Oct 22, 2026 with real requests:

| Model | Tool calling | Latency | Notes |
|---|---|---|---|
| `gpt-5.4-mini` | ✅ | 2.4 s | Correct, concise arguments. **Main agent + seller persona** |
| `gpt-5-mini` | ✅ | 3.1 s | Spends many tokens reasoning on trivial calls |
| `gpt-5.6-terra` | ✅ | 2.4 s | **Fallback model** |
| `gpt-6-luna`, `gpt-6-sol` | ✅ only with `reasoning_effort: "none"` | 2.3–2.6 s | Return 400 otherwise |
| `gpt-6.1-sol`, `gpt-6-astra` | ❌ via `/chat/completions` | — | Need reasoning; tools only via `/responses` (not supported here) |
| `text-embedding-3-small` | ✅ | 2.1 s | 1536 dimensions, Persian + English |

---

## 5. Architecture

### 5.1 Overview
```text
Mobile web (React, RTL Persian)
   │  REST + SSE streaming
   ▼
FastAPI backend ───────────────► BoxAPI (LLM + embeddings)
   ├─ Agent orchestrator (tool calling)
   ├─ Deterministic tools: catalog search, scoring, shops, hours, distance
   ├─ Simulated shop agent (separate LLM persona)
   └─ Session state (in memory + SQLite)
   │
   ▼
Prebuilt data file (DuckDB): phones, offers, shops, derived scores, search index
```
One container on Liara. No external database or queue.

### 5.2 Core principle: the LLM talks, code decides
- **LLM:** understands user text, chooses tools, asks clarifying questions, writes short friendly Persian explanations.
- **Deterministic code:** all facts and ranking — prices, scores, distances, opening hours, filters, status badges.
- The LLM never invents a price, stock level, spec or address. Every card is rendered from tool output, not model text.

### 5.3 Offline data pipeline
`scripts/build_data.py` reads the raw CSVs and writes `app.duckdb` (~20–40 MB, shipped in the image):
1. **Phones:** filter the phone category (814); parse specs into typed columns — battery mAh, storage, RAM, screen size, main/selfie camera MP, chipset, release year, SIM count, network.
2. **Normalized models:** brand, model family, variant (e.g. Galaxy A35 128/8) to group listings of one model.
3. **Everyday ratings (0–10):** camera, battery, speed, storage, value — relative to all phones, each storing how many inputs it used. No guessing.
4. **Offers:** price, change date, freshness tier, warranty type, "price not listed".
5. **Shops (all 6,476):** parsed weekly hours; payment methods (in-person / unknown channel / installment providers); address → passage, floor, unit; coordinates; listed vs possible.
6. **Reference phones:** ~70 popular older phones (`scripts/reference_phones.csv`), labeled "public specs".
7. **Search index:** Persian/English/Finglish aliases + embeddings of model names.

### 5.4 Backend modules (Python, FastAPI)
| Module | Responsibility |
|---|---|
| `catalog` | Search/filter phones, group variants, model cards with price range and shop count |
| `profile` | Resolve current phone (dataset → reference → labeled estimate); pain points → weighted priorities |
| `recommender` | Score candidates vs needs and budget; pick best match / cheaper / step up; guardrails; "why" reasons and "vs your phone" diffs |
| `shops` | Listed and possible shops, distance, open-at-visit-time, installment filter, in-passage location |
| `compare` | Model-vs-model and shop-vs-shop comparisons in plain language |
| `outreach` | Simulated shop conversations, outcomes, fallbacks |
| `agent` | Orchestration, tool definitions, state machine, streaming |

### 5.5 Agent design
A guided state machine wrapping an LLM tool-calling loop:
```text
0 Current phone ─► 1 Needs & model ─► 2 Find shops ─► 3 Compare shops ─► 4 Contact shops ─► Visit plan
                        ▲                                                       │
                        └──────────── fallback: other model / other shop ◄──────┘
```
- **Session state (JSON):** current phone, pain points, things to keep, budget, uses, location, visit time, installment requirement, shortlist, shop outcomes.
- **Every reply = short text + UI blocks** (model cards, comparison table, shop cards, map, chips, outreach thread, visit plan).
- **Chips/buttons update state directly** without an LLM call, so filters are instant.
- **Tools:** `resolve_current_phone`, `set_preferences`, `recommend_models`, `compare_models`, `find_shops`, `compare_shops`, `contact_shops`, `build_visit_plan`, `suggest_alternatives`.
- **Models:** `gpt-5.4-mini` main agent and seller persona; `text-embedding-3-small` for name matching (build time + cached); `gpt-5.6-terra` fallback on error/timeout.

### 5.6 Simulated shop agent
- Each shop gets a **hidden, reproducible scenario** (seeded per shop + model): in stock at listed price / price changed ±x% / only another variant / sold out / no answer / closing early.
- Probabilities follow the real data: older price → more likely changed; hours not declared → more "no answer".
- **The scenario decides the facts; the LLM only voices the seller** in natural Persian. The structured outcome is validated against the scenario.
- Fallbacks: next-best listed shop (same passage preferred) → another variant → step-down model.
- Labeled everywhere as simulated. A **demo mode** fixes scenarios so the video hits every story beat.

### 5.7 Frontend
- React + Vite + TypeScript, `dir="rtl"`, Vazirmatn font, mobile-first (390 px).
- Chat thread with rich cards, sticky step chip bar, bottom-sheet filters (budget, area, visit time, installments).
- Map: Leaflet + OpenStreetMap tiles (no key). If tiles are slow/blocked in Iran → Neshan key or list view with distances.
- Components: `PhoneCard`, `VsMyPhone`, `ModelCompare`, `ShopCard` (status badges), `PassageLocator`, `OutreachThread`, `VisitPlan`, `ConfidenceBadge`.

### 5.8 Deployment (Liara)
- One Docker image: FastAPI serves the Vite build as static files, plus API, `app.duckdb` and reference data.
- Secrets `BOXAPI_API_KEY`, `BOXAPI_BASE_URL` as Liara environment variables, never in git.
- `/health` endpoint; logging of every tool call and LLM latency.
- To verify at deploy time: Liara Docker-app flow and environment variables (per the Liara credit guide).

### 5.9 Repository layout
```text
torob-che/
  backend/app/{main.py, agent/, tools/, data/, llm.py}
  frontend/src/{components/, pages/, api.ts}
  scripts/{build_data.py, reference_phones.csv}
  docs/{ARCHITECTURE.md, DATA_NOTES.md}
  Dockerfile
  README.md   (Persian + English, demo GIF, links)
```
Raw data (`data/`), `.env` and the challenge video are git-ignored.

### 5.10 Risks
| Risk | Mitigation |
|---|---|
| BoxAPI slow/unavailable during judging | Timeouts + fallback model; core flow works via chips without the LLM; cached demo responses |
| Phone specs only ~56% covered | Ratings show confidence; missing data shown as "not listed" |
| Popular older phones missing | Curated reference table + labeled estimate |
| Map tiles blocked | Neshan fallback or list view |
| Time | Phased execution; working end-to-end slice first |

---

## 6. Execution plan

| Phase | Work | Estimate |
|---|---|---:|
| 1 | Data pipeline + reference phone table | ~3 h |
| 2 | Backend tools + recommender, with tests | ~5 h |
| 3 | Agent + simulated shops | ~4 h |
| 4 | Frontend | ~7 h |
| 5 | Deploy on Liara | ~2 h |
| 6 | Demo script, README, video support | ~3 h |

~5 h buffer. The demo video is recorded by the team; the final submission (single attempt) is pressed by Iman.
