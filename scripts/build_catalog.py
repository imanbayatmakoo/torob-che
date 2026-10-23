"""Build backend/app/data/catalog/*.parquet (all-category catalogue) from the raw Torob CSVs.

Usage:  .venv/bin/python scripts/build_catalog.py
Output: products.parquet, offers.parquet, categories.parquet, meta.json   (shops are reused from data/pq/shops.parquet)

Expert-category choice (documented rationale, verified here against data/categories.json when present):
  rank non-phone categories by complexity+viability, keeping only those with comparable spec sheets
  (avg_specs >= 14, >=500 products, >=100 shops); ties -> avg_specs, then installment shops.
  Actual result: headphones (181), speakers (180), CCTV cameras (161), power banks (158, ties mic. on 158 but has
  richer specs + more installment shops).  Smartwatches rank 17th (138), laptops 41st, TVs 44th by the same sum, and
  LED panel lights (163) fail the spec-richness guard (avg 9.2 specs) -> not chosen.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import catalog as C  # noqa: E402
from app.data import parsers as P  # noqa: E402

RAW = ROOT / "data" / "torob-dataset"
OUT = ROOT / "backend" / "app" / "data" / "catalog"
PQ = ROOT / "backend" / "app" / "data" / "pq"
PHONE_CAT = "گوشی موبایل"


def nn(v):
    return None if v in (None, "", "null", "None") else v


def choose_expert(cats: list[dict]) -> list[dict]:
    ok = [c for c in cats if c.get("complexity") is not None and c["cat"] != PHONE_CAT and (c["avg_specs"] or 0) >= 14
          and c["n_products"] >= 500 and c["n_shops"] >= 100]
    ok.sort(key=lambda c: (-(c["complexity"] + c["viability"]), -c["avg_specs"], -c["inst_shops"]))
    return ok[:4]


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    opts = "header=true, all_varchar=true, max_line_size=20000000"
    con.execute(f"create view rp as select * from read_csv_auto('{RAW / 'products.csv'}', {opts})")
    con.execute(f"create view ro as select * from read_csv_auto('{RAW / 'offers.csv'}', {opts})")

    cats_json = ROOT / "data" / "categories.json"
    prof = json.loads(cats_json.read_text()) if cats_json.exists() else []
    if prof:
        chosen = [c["cat"] for c in choose_expert(prof)]
        assert set(chosen) == set(C.EXPERT_KINDS), f"expert set drifted: {chosen}"
        print("expert categories (by rank):", chosen)
    prof_by = {c["cat"]: c for c in prof}

    # ---------------- products ----------------
    cur = con.execute("select product_id, persian_title, brand_name, category_name, model, image_urls, specs from rp")
    rows = []
    while True:
        chunk = cur.fetchmany(20000)
        if not chunk:
            break
        for pid, title, brand, cat, model, imgs, specs in chunk:
            try:
                items = json.loads(specs) if nn(specs) else []
            except json.JSONDecodeError:
                items = []
            pairs, sm = [], {}
            for it in items or []:
                k, v = P.norm(it.get("key")), P.norm(it.get("value"))
                if k and v and v.lower() not in ("null", "-"):
                    pairs.append([k, v])
                    sm.setdefault(k, v)
            try:
                img = (json.loads(imgs) or [None])[0] if nn(imgs) else None
            except json.JSONDecodeError:
                img = None
            name = P.norm(title)
            brand = P.norm(brand) if nn(brand) else None
            model = P.norm(model) if nn(model) else None
            cat = P.norm(cat)
            exp_specs = exp_ev = None
            if cat in C.EXPERT_KINDS:
                s, ev = C.extract_specs(cat, sm, name)
                exp_specs, exp_ev = json.dumps(s, ensure_ascii=False), json.dumps(ev, ensure_ascii=False)
            else:
                hi = [(k, v) for k, v in pairs if len(v) <= 80 and k not in ("نام محصول", "سایر مشخصات")][:6]
                exp_specs = json.dumps({k: v for k, v in hi}, ensure_ascii=False)
                exp_ev = json.dumps({k: {"source": "spec", "key": k, "raw": v} for k, v in hi}, ensure_ascii=False)
            rows.append((pid, name, brand, cat, model, img, json.dumps(pairs, ensure_ascii=False), exp_specs, exp_ev,
                         len(pairs), " ".join(x for x in (name, brand, model, cat) if x).lower()))
    pdf = pd.DataFrame(rows, columns=["product_id", "name", "brand", "category", "model", "image", "raw_specs_json",
                                      "specs_json", "evidence_json", "n_specs", "search_text"])
    del rows
    print(f"products {len(pdf)} in {time.time()-t0:.0f}s")

    # ---------------- offers ----------------
    ocur = con.execute("""select offer_id, product_id, shop_id, seller_title, description,
        try_cast(nullif(price_toman,'null') as bigint), try_cast(nullif(last_price_changed_at,'null') as timestamptz),
        nullif(warranty,'null') from ro""")
    wcache: dict = {}
    orows = []
    for oid, pid, sid, st, desc, price, ts, wj in ocur.fetchall():
        if wj not in wcache:
            w = json.loads(wj) if wj else {}
            prov, months, wdesc = w.get("provider"), w.get("period_months"), w.get("description")
            wm = P.warranty_months(prov, months, wdesc)
            wcache[wj] = (P.warranty_kind(prov, months, wdesc), wm,
                          " · ".join(x for x in [P.norm(prov), f"{wm} ماه" if wm else "", P.norm(wdesc)] if x) or None, P.norm(wdesc))
        wk, wm, wt, wd = wcache[wj]
        cond = P.condition_from_text(f"{st or ''} {desc or ''} {wd}")
        orows.append((oid, pid, sid, price, ts, wk, wm, wt, "used" if cond == "used" else "new_or_unknown", P.norm(st)))
    odf = pd.DataFrame(orows, columns=["offer_id", "product_id", "shop_id", "price", "price_changed_at", "warranty_kind",
                                       "warranty_months", "warranty_text", "condition", "seller_title"])
    del orows
    for d in (pdf, odf):
        for c in d.columns:
            if str(d[c].dtype) in ("str", "string"):
                d[c] = d[c].astype(object)
    con.register("pdf", pdf)
    con.register("odf", odf)
    # outlier: >3x or <1/3 of the product's median price, only when >=3 priced offers (never drop a lone offer)
    con.execute("""create table offers as
        with m as (select product_id, median(price) med, count(price) n from odf group by 1)
        select o.offer_id, o.product_id, p.category, o.shop_id, cast(o.price as bigint) price, o.price_changed_at, o.warranty_kind,
               o.warranty_months, o.warranty_text, o.condition, o.seller_title,
               (o.price is not null and m.n >= 3 and (o.price > 3*m.med or o.price < m.med/3)) as price_outlier
        from odf o join pdf p using(product_id) join m using(product_id)""")
    # (offers are written after products, once we know which products have a usable price)
    shops_pq = (PQ / "shops.parquet").as_posix()
    con.execute(f"""create table agg as
        select o.product_id, count(*) n_offers, count(distinct o.shop_id) n_shops, min(o.price) price_min,
               median(o.price) price_med, max(o.price) price_max,
               count(distinct o.shop_id) filter (where s.has_installment) n_installment_shops
        from offers o join read_parquet('{shops_pq}') s using(shop_id)
        where o.price is not null and not o.price_outlier group by 1""")
    con.execute("""create table prod as select p.*, a.n_offers, a.n_shops, a.price_min, a.price_med, a.price_max,
        a.n_installment_shops, coalesce(a.n_offers,0) > 0 as has_price from pdf p left join agg a using(product_id)""")
    # Deploy size: ship only products with a usable in-person offer; full raw specs/evidence only for expert
    # categories (broad mode uses the compact specs summary). Seller titles are not needed at runtime.
    from app.catalog import EXPERT_KINDS  # noqa: E402
    exl = ",".join("'" + c.replace("'", "''") + "'" for c in EXPERT_KINDS)
    con.execute(f"""copy (select * replace(case when category in ({exl}) then raw_specs_json else '[]' end as raw_specs_json,
                                     case when category in ({exl}) then evidence_json else '{{}}' end as evidence_json)
                from prod where has_price order by category, product_id) to '{OUT/'products.parquet'}'
                (format parquet, compression zstd, compression_level 19, row_group_size 20000)""")
    con.execute(f"""copy (select * exclude(seller_title) from offers where product_id in (select product_id from prod where has_price)
                order by category, product_id) to '{OUT/'offers.parquet'}'
                (format parquet, compression zstd, compression_level 19, row_group_size 20000)""")

    # ---------------- categories ----------------
    cdf = con.execute("""select category, count(*) n_products, count(*) filter (where has_price) n_priced_products,
        coalesce(sum(n_offers),0) n_offers, median(price_min) median_price, avg(n_specs) avg_specs,
        coalesce(sum(n_installment_shops),0)>0 has_installment,
        mode(brand) top_brand from prod group by 1""").fetchdf()
    cdf["complexity"] = cdf.category.map(lambda c: prof_by.get(c, {}).get("complexity"))
    cdf["viability"] = cdf.category.map(lambda c: prof_by.get(c, {}).get("viability"))
    cdf["kind"] = cdf.category.map(lambda c: C.EXPERT_KINDS.get(c))
    cdf["expert"] = cdf.kind.notna()
    cov = {}
    for cat in C.EXPERT_KINDS:
        sp = con.execute("select specs_json from prod where category=?", [cat]).fetchall()
        n = len(sp)
        cnt: dict = {}
        for (s,) in sp:
            for k in json.loads(s):
                cnt[k] = cnt.get(k, 0) + 1
        cov[cat] = {k: round(v / n, 3) for k, v in sorted(cnt.items())}
    cdf["coverage_json"] = cdf.category.map(lambda c: json.dumps(cov[c]) if c in cov else None)
    cdf["rationale"] = cdf.category.map(lambda c: C.RATIONALE.get(c))
    cdf["search_text"] = cdf.category.str.lower()
    cdf = cdf.sort_values("category")
    cdf.to_parquet(OUT / "categories.parquet", compression="zstd", index=False) if _has_pyarrow() else \
        _copy_df(con, cdf, OUT / "categories.parquet")
    snap = con.execute(f"select snapshot_at from read_parquet('{(PQ/'meta.parquet').as_posix()}')").fetchone()[0]
    (OUT / "meta.json").write_text(json.dumps({"snapshot_at": snap.isoformat(), "n_products": len(pdf), "n_offers": len(odf),
                                               "n_categories": len(cdf), "expert": C.EXPERT_KINDS}, ensure_ascii=False))
    print("coverage:", {c: {k: v for k, v in d.items()} for c, d in cov.items()})
    print(f"done in {time.time()-t0:.0f}s; products={len(pdf)} offers={len(odf)} categories={len(cdf)}")


def _has_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def _copy_df(con, df, path):
    for c in df.columns:
        if str(df[c].dtype) in ("str", "string"):
            df[c] = df[c].astype(object)
    con.register("tmp_df", df)
    con.execute(f"copy (select * from tmp_df) to '{path}' (format parquet, compression zstd)")


if __name__ == "__main__":
    main()
