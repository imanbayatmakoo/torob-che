# همراه خرید ترب · Torob Shopping Companion

**Team Transformers — Starcoach Agentic AI Hackathon, Challenge #7 (Torob)**

A Persian, RTL, mobile-first AI assistant that makes the hardest everyday purchase, **a mobile phone**, simple for a normal person who wants to buy **in person** from Tehran's phone passages (Jomhouri / Alaedin / Charsoo, Ferdowsi).

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
  shop_agent.py    simulated shop agent (seeded outcomes + LLM-written seller reply)
  data/app.duckdb  prebuilt read-only DB (5 MB): phones, models, offers, shops, reference phones
  data/parsers.py  Persian spec/address parsers (unit tested)
scripts/build_data.py   raw Torob CSV → app.duckdb (≈4 s)
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

## Deploy (Liara)
`liara deploy` uses the `Dockerfile` and `liara.json`. Set the env vars `BOXAPI_API_KEY` and `BOXAPI_BASE_URL` in the Liara panel.

## Data notes and limitations
- Snapshot: Torob dataset; latest price update 2026-10-13.
- Only about 14 phone shops list installment providers. Installment is therefore a **soft** preference: listed shops rank higher, and the rest are asked in Step 4.
- Phone numbers and shop names in the dataset are synthetic; contacting shops is simulated.
- See `docs/ARCHITECTURE.md` and `docs/DATA_NOTES.md`.
