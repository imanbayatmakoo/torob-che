# Dataset profile (verified 2026-10-22, DuckDB over raw CSVs)

| Table | Rows | Notes |
|---|---:|---|
| shops | 6,476 | all have lat/lon (Tehran bbox 35.64–35.81, 51.31–51.51), all have phone only (fake numbers) |
| products | 225,903 | 3,428 categories, 2,250 brands; images 99%, specs 64%, brand 26% |
| offers | 331,506 | 1 per (shop, product); 3,792 shops have offers; **2,684 shops have zero offers** (category only) |

## Shops
- Clustered: فردوسی 3,282 · شیخ هادی 1,587 · بهارستان 616 · then long tail (Tajrish, Asman, Bagh-Feyz…).
- Address parseable: 3,671 mention پاساژ/مجتمع/مرکز خرید, 4,224 mention floor (طبقه), 6,014 unit/plaque.
- weekly_hours: Saturday status declared 4,305 / closed 162 / unsupported 6 / missing ~2,000. Per-day shifts with start/end.
- payment_options: only 266 shops. Providers: Torob Pay, Snapp Pay, Digipay, Tara, Azki Vam. channel = `in_person` vs `unknown` → must display "declared in-person" vs "declared, channel unknown".
- supports_fast_delivery: true 1,168 / false 433 / null 4,875.
- instagram 22, website 90 (the only real shop names). Kalabarg (کالابرگ) field: not found yet as a column.

## Offers
- price_toman null: 15,083 (show "price not listed — call").
- last_price_changed_at: null 769; 2026-10: 129k, 2026-09: 88k, older tail back to 2020 → freshness badge needed.
- warranty JSON on 59k offers (provider, period_months, description).
- 187k products have exactly one seller; comparison only meaningful for ~39k multi-seller products (max 105).

## Product implications
- Listed price ≠ confirmed stock. Freshness + "call to confirm" step is core.
- Category-only shops = "may carry, unconfirmed" tier, never shown as having the product.
- Mall/floor/unit parsing enables an in-mall visit route (e.g. Alaeddin, Charsou).
