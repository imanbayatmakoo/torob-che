# تربچه · torob-che

**Team Transformers — Starcoach Agentic AI Hackathon, Challenge #7 (Torob)**

A Persian, RTL, mobile-first AI assistant that makes the hardest everyday purchase, **a mobile phone**, simple for a normal person who wants to buy **in person** from Tehran's phone passages (Jomhouri / Alaedin / Charsoo, Ferdowsi).

## Beyond phones: 4 expert categories + broad discovery for everything else

| Mode | Categories | What the assistant does |
|---|---|---|
| **Expert** | Phones (flagship), headphones/earbuds, speakers, CCTV cameras, power banks | Category-specific questions and spec-based ranking (ANC, battery, driver; power, Bluetooth; resolution, night vision, IP rating; capacity, fast-charge watts, weight, ports). Compares against the item you own today when known. Unknown specs are shown as "unknown", never as bad. Look-alikes and accessories (e.g. 2M-toman "AirPods Max", cases) are filtered out. |
| **Broad** | All other ~3,400 Torob categories | Real products with real in-person offers, prices, shop ranking, simulated follow-up and route. **No quality scores or "better" claims**: we don't have validated specs there, so we say so. |

The four expert categories were chosen for **decision complexity × usable spec coverage × in-person shop coverage**, not catalogue size. Laptops, TVs and smartwatches scored lower on that selection in this snapshot, so they stay in broad mode.

All modes share the same honesty rules: one offer per seller, closed or over-budget shops are visible but excluded from the plan, area is a hard constraint (the assistant asks before widening it), and installment is a hard filter.

UI: optional dark mode (🌙, saved per device), an area picker next to the installment toggle, and long answers stay at their beginning instead of jumping to the bottom. Product images on every recommendation card. **Tap a shop card to commit to it**: the assistant calls that shop first (simulated) and only falls back to others if it fails. The plan shows an in-app **OpenStreetMap map** (Leaflet) with the shop pin, an optional walking route from your location (OSRM foot routing, only with permission) and one-tap links to OSM, Neshan, Balad and Google Maps. The floor and unit are shown as text, because maps stop at the building entrance.

Branding: the Torob logo is used to show the app is built on Torob's challenge dataset. torob-che is a hackathon entry, not an official Torob product.

## The 4-step journey (from the challenge brief), plus Step 0

| Step | What the user gets |
|---|---|
| 0 · Current phone (optional) | "What do you use now and what bothers you?" Looked up in Torob data, then a curated table of older phones. Recommendations are framed as "vs your phone", with a guardrail: never recommend something worse on a stated pain point. |
| 1 · Right model | Three cards: **best match**, **cheaper**, **step up**. Each has ratings, reasons, price freshness and spec confidence ("based on N of M specs"). Picked from about 200 real models in the dataset. |
| 2 · Shops that have it | Every in-person shop listing the model, with passage, floor and unit parsed from the address. |
| 3 · Compare shops | A transparent score: price, price freshness, warranty, registry, opening hours at *your* visit time, installment and budget. Tap "why?" to see the breakdown. Includes a walking order inside the passages. |
| 4 · Contact shops | A **simulated** shop agent "calls" the top shops to confirm stock, today's price and installments. If a shop doesn't answer or is out of stock, it automatically moves to the next one. The result is a final plan with route and checklist. Clearly labelled as simulation. |

## Principle: the LLM talks, code decides
- Every fact on screen (model, price, shop, address, rating) comes from deterministic tools over the Torob dataset. The LLM only chooses tools and writes short Persian narration.
- **Honesty badges:** listed price ≠ stock ("stock not confirmed"), price freshness tier, spec confidence, and estimates labelled as estimates.
- Look-alike phones (for example "یونیوا 16 Pro Max" filed under Apple) and outlier prices are filtered out.

## Architecture
```
frontend/web       vanilla JS + CSS, RTL mobile web (no build step)
backend/app
  main.py          FastAPI, POST /api/chat → Server-Sent Events (cards + messages)
  agent.py         tool-calling orchestrator (BoxAPI gpt-5.4-mini), session state
  tools.py         deterministic tools: lookup_current_phone, recommend, find_shops, compare
  catalog.py       all-category catalogue: search_categories, search_products (expert/broad), find_product_shops
  shop_agent.py    simulated shop agent (seeded outcomes + LLM-written seller reply)
  data/pq/*.parquet prebuilt data (1.4 MB), loaded into in-memory DuckDB at startup
  data/parsers.py  Persian spec/address parsers (unit tested)
scripts/build_data.py   raw Torob CSV → Parquet (≈4 s)
```

## Run locally
```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env            # set BOXAPI_API_KEY
cd backend && PYTHONPATH=. uvicorn app.main:app --port 8765
# open http://127.0.0.1:8765
pytest                           # 17 tests (parsers, recommender, guardrails, shop scoring)
```
Rebuild the data (needs the raw dataset in `data/torob-dataset/`): `python scripts/build_data.py`

## Live demo
https://torob-che.liara.run

## Deploy (Liara)
`liara deploy` uses the `Dockerfile` and `liara.json`. Set the env vars `BOXAPI_API_KEY` and `BOXAPI_BASE_URL` in the Liara panel.

## Data notes and limitations
- Snapshot: Torob dataset; latest price update 2026-10-13.
- Only about 14 phone shops list installment providers. Installment is a **hard filter**: when enabled, only shops listing an installment provider on Torob are shown or contacted, so results can be few.
- Phone numbers and shop names in the dataset are synthetic; contacting shops is simulated.
- See `docs/ARCHITECTURE.md` and `docs/DATA_NOTES.md`.
