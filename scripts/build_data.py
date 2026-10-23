"""Build backend/app/data/pq/*.parquet from the raw Torob CSVs.

Usage:  .venv/bin/python scripts/build_data.py
Output: backend/app/data/pq/*.parquet  (phones, phone_offers, shops, reference_phones, meta)
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.data import parsers as P  # noqa: E402

RAW = ROOT / "data" / "torob-dataset"
PQ = ROOT / "backend" / "app" / "data" / "pq"
PHONE_CAT = "گوشی موبایل"

BRAND_EN = {
    "اپل": "apple", "سامسونگ": "samsung", "شیائومی": "xiaomi", "نوکیا": "nokia", "آنر": "honor", "گوگل": "google",
    "ناتینگ": "nothing", "موتورولا": "motorola", "ریلمی": "realme", "وان پلاس": "oneplus", "ویوو": "vivo",
    "هوآوی": "huawei", "اوپو": "oppo", "سونی": "sony", "هانوفر": "hanofer", "جی ال ایکس": "glx",
}

SPEC_KEYS = {
    "storage": ["حافظه داخلی", "ظرفیت حافظه داخلی", "ظرفیت حافظه", "حافظه"],
    "battery": ["ظرفیت باتری", "باتری", "مشخصات باتری", "محدوده ظرفیت باتری"],
    "ram": ["مقدار RAM", "رم اجرایی", "حافظه رم", "رم", "حافظه RAM", "حافظه رم (Ram)", "حافظه رم RAM", "مقدار رم",
            "ظرفیت حافظه رم", "حافظه اجرایی (RAM)", "رم (RAM)"],
    "screen": ["اندازه صفحه نمایش", "سایز صفحه نمایش", "اندازه", "اندازه نمایشگر", "صفحه نمایش", "بازه ی اندازه صفحه نمایش"],
    "os": ["سیستم عامل", "نوع سیستم عامل", "سیستم عامل در زمان عرضه", "نسخه سیستم عامل"],
    "sim": ["تعداد سیم کارت", "سیم کارت", "نوع سیم کارت", "توضیحات سیم کارت"],
    "chip": ["تراشه", "مدل تراشه", "تراشه (SOC)", "نوع تراشه", "تراشه پردازنده", "پردازنده مرکزی", "نوع پردازنده",
             "پردازنده", "پردازنده CPU", "تراشه(cpu)", "نوع پردازنده - CPU", "پردازنده ی مرکزی", "پردازنده مرکزی (CPU)"],
    "main_cam": ["رزولوشن دوربین اصلی", "دوربین اصلی - واید/استاندارد", "دوربین اصلی", "کیفیت دوربین اصلی",
                 "دقت عکاسی دوربین اصلی", "مشخصات دوربین اصلی", "پیکربندی دوربین پشت", "کیفیت دوربین", "دوربین پشت",
                 "دوربین واید", "مشخصات دوربین واید", "دوربین"],
    "selfie": ["دوربین سلفی", "دوربین سلفی اصلی", "رزولوشن دوربین سلفی", "کیفیت دوربین سلفی", "دوربین جلو", "پیکربندی دوربین سلفی"],
    "year": ["تاریخ معرفی", "زمان معرفی", "تاریخ عرضه", "سال عرضه"],
    "nfc": ["NFC", "فناوری NFC"], "weight": ["وزن", "وزن (گرم)"],
    "network": ["شبکه های ارتباطی", "شبکه های مخابراتی", "نسل شبکه مخابراتی", "شبکه"],
    "memcard": ["پشتیبانی از کارت حافظه", "پشتیبانی از کارت حافظه جانبی", "درگاه کارت حافظه"],
    "display_type": ["نوع صفحه نمایش", "فناوری صفحه نمایش", "مدل صفحه نمایش"],
    "persian": ["پشتیبانی از زبان فارسی"],
}
CHIP_HINT = re.compile(r"snapdragon|dimensity|helio|exynos|apple\s*a\d|bionic|tensor|unisoc|kirin|mt6\d{3}|اسنپدراگون", re.I)


def load_csv(con, name):
    con.execute(f"""create or replace table raw_{name} as select * from read_csv_auto('{RAW / (name + ".csv")}',
        header=true, all_varchar=true, max_line_size=20000000)""")


def nn(v):
    return None if v in (None, "", "null", "None") else v


def spec_map(specs_json: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        items = json.loads(specs_json) if nn(specs_json) else []
    except json.JSONDecodeError:
        items = []
    for it in items:
        k, v = P.norm(it.get("key")), P.norm(it.get("value"))
        if k and v and k not in out:
            out[k] = v
    return out


def pick(sm: dict, field: str, parser=None):
    """First key (priority order) whose value parses; returns raw string, or parsed value when parser given."""
    for k in SPEC_KEYS[field]:
        if k in sm:
            if parser is None:
                return sm[k]
            v = parser(sm[k])
            if v is not None:
                return v
    return None


def find_chip(sm: dict) -> str | None:
    c = pick(sm, "chip", lambda v: v if P.chip_tier(v) is not None else None)
    if c:
        return c
    for v in sm.values():
        if CHIP_HINT.search(v) and P.chip_tier(v) is not None:
            return v
    return pick(sm, "chip")


def model_key(brand_en: str, model: str | None, title: str) -> tuple[str, str]:
    """Return (model_key, display_model). Variant (storage/RAM) is NOT part of the key."""
    m = P.norm(model).lower() if nn(model) else ""
    if not m:
        t = P.norm(title)
        t = re.split(r"\||حافظه|ظرفیت|رم\s", t)[0]
        t = re.sub(r"گوشی(?:\s*موبایل)?|مدل|طرح|\(.*?\)|دو سیم ?کارت|تک سیم ?کارت|4G|5G", " ", t, flags=re.I)
        for fa in BRAND_EN:
            t = t.replace(fa, " ")
        m = re.sub(r"\s+", " ", t).strip().lower()
    m = re.sub(r"\b(5g|4g|lte|dual sim|ch|zaa|za/a|ll/a)\b", " ", m)
    m = re.sub(r"(?<=[a-z])\s+(?=\d)", "", m)  # 'a 56' -> 'a56', 's 26 ultra' -> 's26 ultra'
    m = re.sub(r"(?<=\d)\s+(?=[a-z]\b)", "", m)  # 'x 6 c' -> 'x6c'
    m = re.sub(r"\s+", " ", m).strip()
    disp = m
    key = f"{brand_en}:{m.replace(' ', '')}"
    return key, disp


def pct_rank(values: list[float], v: float | None) -> float | None:
    if v is None or not values:
        return None
    below = sum(1 for x in values if x < v)
    eq = sum(1 for x in values if x == v)
    return (below + 0.5 * eq) / len(values)


def main():
    t0 = time.time()
    PQ.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()  # build in memory, then copy only final tables to disk
    for n in ("products", "offers", "shops"):
        load_csv(con, n)
    print(f"loaded raw in {time.time()-t0:.1f}s")

    # ---------------- phones ----------------
    prods = con.execute(f"select product_id, persian_title, brand_name, model, image_urls, specs from raw_products where category_name=?",
                        [PHONE_CAT]).fetchall()
    phones = []
    for pid, title, brand, model, imgs, specs in prods:
        sm = spec_map(specs)
        brand_fa = nn(brand)
        brand_en = BRAND_EN.get(brand_fa or "", (brand_fa or "other"))
        mk, mdisp = model_key(brand_en, model, title)
        cond = P.condition_from_text(title)
        if cond == "replica":
            mk = "replica:" + mk
        st_t, ram_t = P.title_storage_ram(title)
        storage = pick(sm, "storage", P.parse_storage_gb) or st_t
        ram = pick(sm, "ram", P.parse_storage_gb) or ram_t
        os_ = pick(sm, "os", P.parse_os)
        if os_ is None:
            if brand_en == "apple" and "iphone" in P.norm(title).lower() + mdisp:
                os_ = "ios"
            elif storage is not None and storage < 1:
                os_ = "feature"
        screen = pick(sm, "screen", P.parse_inch)
        segment = "feature" if (os_ == "feature" or (storage is not None and storage < 1) or (screen and screen < 3.5)) else "smartphone"
        chip = find_chip(sm)
        try:
            images = json.loads(imgs) if nn(imgs) else []
        except json.JSONDecodeError:
            images = []
        phones.append(dict(
            product_id=pid, title=P.norm(title), brand_fa=brand_fa, brand_en=brand_en, model_key=mk, model=mdisp,
            storage_gb=storage, ram_gb=ram, battery_mah=pick(sm, "battery", P.parse_mah), screen_in=screen,
            main_mp=pick(sm, "main_cam", P.parse_mp), selfie_mp=pick(sm, "selfie", P.parse_mp),
            chipset=chip, chip_tier=P.chip_tier(chip), os=os_, sim=P.parse_sim(pick(sm, "sim")),
            year=pick(sm, "year", P.parse_year), nfc=P.yes_no(pick(sm, "nfc")),
            display_type=pick(sm, "display_type"), segment=segment,
            condition=cond, registry=P.registry_from_text(title),
            image=images[0] if images else None, n_specs=len(sm), specs_json=json.dumps(sm, ensure_ascii=False),
        ))

    # Variants of one model share hardware: fill missing model-level specs from siblings (provenance kept).
    shared = ["battery_mah", "screen_in", "main_mp", "selfie_mp", "chipset", "chip_tier", "os", "year", "nfc", "display_type"]
    by_model: dict[str, list[dict]] = {}
    for p in phones:
        by_model.setdefault(p["model_key"], []).append(p)
    for group in by_model.values():
        for f in shared:
            vals = [p[f] for p in group if p[f] is not None]
            if not vals:
                continue
            best = max(set(map(str, vals)), key=lambda v: [str(x) for x in vals].count(v))
            fill = next(v for v in vals if str(v) == best)
            for p in group:
                if p[f] is None:
                    p[f] = fill
                    p.setdefault("filled_from_variant", []).append(f)
    for p in phones:
        p["filled_fields"] = ",".join(p.pop("filled_from_variant", [])) or None
        if p["segment"] == "smartphone" and (p["os"] == "feature"):
            p["segment"] = "feature"

    # Ratings: relative to smartphones only; each rating keeps its input count.
    smart = [p for p in phones if p["segment"] == "smartphone"]
    bat = [p["battery_mah"] for p in smart if p["battery_mah"]]
    stor = [math.log2(p["storage_gb"]) for p in smart if p["storage_gb"]]
    cam = [p["main_mp"] for p in smart if p["main_mp"]]
    for p in phones:
        r_bat = pct_rank(bat, p["battery_mah"])
        r_sto = pct_rank(stor, math.log2(p["storage_gb"])) if p["storage_gb"] else None
        speed = p["chip_tier"]
        speed_basis = "chipset" if speed is not None else None
        if speed is None and p["ram_gb"]:
            speed = min(5.0, 0.6 * p["ram_gb"]) if p["ram_gb"] >= 1 else 0.3
            speed_basis = "ram_estimate"
        cam_parts = []
        if p["main_mp"]:
            cam_parts.append(10 * (pct_rank(cam, p["main_mp"]) or 0))
        if p["chip_tier"] is not None:
            cam_parts.append(p["chip_tier"])  # image processing tracks SoC tier
        r_cam = sum(cam_parts) / len(cam_parts) if cam_parts else None
        p["rating_battery"] = round(10 * r_bat, 1) if r_bat is not None else None
        p["rating_storage"] = round(10 * r_sto, 1) if r_sto is not None else None
        p["rating_speed"] = round(speed, 1) if speed is not None else None
        p["speed_basis"] = speed_basis
        p["rating_camera"] = round(r_cam, 1) if r_cam is not None else None
        p["camera_inputs"] = len(cam_parts)
        if p["segment"] == "feature":  # ratings are not meaningful vs smartphones
            p["rating_camera"] = min(p["rating_camera"] or 0, 1.0) if p["main_mp"] else None
            p["rating_speed"] = 0.3
        keys = ["battery_mah", "storage_gb", "ram_gb", "main_mp", "chip_tier", "screen_in", "os", "sim", "year"]
        p["key_specs_known"] = sum(1 for k in keys if p[k] is not None)
        p["key_specs_total"] = len(keys)

    con.execute("""create table phones (product_id varchar primary key, title varchar, brand_fa varchar, brand_en varchar,
        model_key varchar, model varchar, storage_gb double, ram_gb double, battery_mah integer, screen_in double, main_mp double,
        selfie_mp double, chipset varchar, chip_tier double, os varchar, sim integer, year integer, nfc boolean, display_type varchar,
        segment varchar, condition varchar, registry varchar, image varchar, n_specs integer, specs_json varchar,
        rating_battery double, rating_storage double, rating_speed double, speed_basis varchar, rating_camera double,
        camera_inputs integer, key_specs_known integer, key_specs_total integer, filled_fields varchar)""")
    cols = [r[0] for r in con.execute("describe phones").fetchall()]
    con.executemany(f"insert into phones values ({','.join('?' * len(cols))})", [[p[c] for c in cols] for p in phones])

    # ---------------- offers (phones only) ----------------
    con.execute("""create table phone_offers as
        select o.offer_id, o.product_id, o.shop_id, o.seller_title, nullif(o.description,'') description,
               try_cast(nullif(o.price_toman,'null') as bigint) price_toman,
               try_cast(nullif(o.last_price_changed_at,'null') as timestamptz) price_changed_at,
               nullif(o.warranty,'null') warranty_json
        from raw_offers o join phones p using(product_id)""")
    con.execute("alter table phone_offers add column warranty_kind varchar")
    con.execute("alter table phone_offers add column warranty_months integer")
    con.execute("alter table phone_offers add column warranty_text varchar")
    con.execute("alter table phone_offers add column condition varchar")
    con.execute("alter table phone_offers add column registry varchar")
    rows = con.execute("select offer_id, warranty_json, seller_title, description from phone_offers").fetchall()
    upd = []
    for oid, wj, st, desc in rows:
        w = json.loads(wj) if wj else {}
        prov, months, wdesc = w.get("provider"), w.get("period_months"), w.get("description")
        kind = P.warranty_kind(prov, months, wdesc)
        wm = P.warranty_months(prov, months, wdesc)
        wtext = " · ".join(x for x in [P.norm(prov), f"{wm} ماه" if wm else "", P.norm(wdesc)] if x) or None
        text = f"{st or ''} {desc or ''} {wdesc or ''}"
        upd.append((kind, wm, wtext, P.condition_from_text(text), P.registry_from_text(text), oid))
    con.executemany("""update phone_offers set warranty_kind=?, warranty_months=?, warranty_text=?, condition=?, registry=?
                       where offer_id=?""", upd)

    con.execute("""create or replace table phone_offers as
        with m as (select p.model_key, median(o.price_toman) med from phone_offers o join phones p using(product_id) group by 1)
        select o.*, (o.price_toman is not null and m.med is not null and (o.price_toman > 3*m.med or o.price_toman < m.med/3)) price_outlier
        from phone_offers o join phones p using(product_id) join m using(model_key)""")

    # ---------------- shops (all) ----------------
    shops = con.execute("""select shop_id, name, address, location_label, try_cast(lat as double), try_cast(lon as double),
        category_names, contacts, instagram, website_url, payment_options, supports_fast_delivery, weekly_hours from raw_shops""").fetchall()
    phone_shop_ids = {r[0] for r in con.execute("select distinct shop_id from phone_offers").fetchall()}
    srows = []
    for (sid, name, addr, label, lat, lon, cats, contacts, ig, web, pay, fast, hours) in shops:
        try:
            catl = json.loads(cats) if nn(cats) else []
        except json.JSONDecodeError:
            catl = []
        try:
            payl = json.loads(pay) if nn(pay) else []
        except json.JSONDecodeError:
            payl = []
        providers = [{"provider": P.norm(x.get("provider_name")), "channel": x.get("channel") or "unknown"} for x in payl]
        try:
            hj = json.loads(hours) if nn(hours) else {}
        except json.JSONDecodeError:
            hj = {}
        days = {}
        for d, info in (hj or {}).items():
            st = (info or {}).get("status")
            shifts = [[s.get("start_time", "")[:5], s.get("end_time", "")[:5]] for s in (info or {}).get("shifts") or []]
            days[d] = {"status": st, "shifts": shifts if st == "declared" else []}
        hours_known = any(v["status"] in ("declared", "closed") for v in days.values())
        a = P.parse_address(addr)
        srows.append((sid, P.norm(name), P.norm(addr), P.norm(label), lat, lon, json.dumps(catl, ensure_ascii=False),
                      contacts, nn(ig), nn(web), json.dumps(providers, ensure_ascii=False), len(providers) > 0,
                      any(p["channel"] == "in_person" for p in providers),
                      None if fast in (None, "null") else fast == "true",
                      json.dumps(days), hours_known, a["passage"], a["floor_label"], a["floor_num"], a["unit"],
                      sid in phone_shop_ids, PHONE_CAT in catl, bool(nn(ig) or nn(web))))
    con.execute("""create table shops (shop_id varchar primary key, name varchar, address varchar, area varchar, lat double, lon double,
        categories_json varchar, contacts_json varchar, instagram varchar, website varchar, payment_json varchar, has_installment boolean,
        installment_in_person boolean, fast_delivery boolean, hours_json varchar, hours_known boolean, passage varchar,
        floor_label varchar, floor_num integer, unit varchar, lists_phones boolean, phone_category boolean, real_name boolean)""")
    con.executemany(f"insert into shops values ({','.join('?' * 23)})", srows)

    # ---------------- reference phones ----------------
    con.execute(f"""create table reference_phones as select * from read_csv_auto('{ROOT / "scripts" / "reference_phones.csv"}', header=true)""")
    con.execute("alter table reference_phones add column chip_tier double")
    for (m, chip) in con.execute("select model, chipset from reference_phones").fetchall():
        con.execute("update reference_phones set chip_tier=? where model=?", [P.chip_tier(chip), m])

    # ---------------- model-level aggregate ----------------
    con.execute("""create table models as
        select p.model_key, any_value(p.brand_en) brand_en, any_value(p.brand_fa) brand_fa, any_value(p.model) model,
            any_value(p.segment) segment, count(distinct p.product_id) n_variants,
            count(o.offer_id) n_offers, count(distinct o.shop_id) n_shops,
            min(o.price_toman) filter (where not o.price_outlier) min_price,
            max(o.price_toman) filter (where not o.price_outlier) max_price,
            median(o.price_toman) filter (where not o.price_outlier) median_price,
            max(o.price_changed_at) last_price_change
        from phones p left join phone_offers o using(product_id) group by 1""")

    con.execute("create table meta as select (select max(price_changed_at) from phone_offers) snapshot_at, ? phone_category, current_timestamp built_at", [PHONE_CAT])
    # ship as Parquet: portable across DuckDB versions and CPUs (Liara hosts lack AVX2)
    PQ.mkdir(parents=True, exist_ok=True)
    for t in ("phones", "phone_offers", "shops", "reference_phones", "models", "meta"):
        con.execute(f"copy {t} to '{PQ / (t + '.parquet')}' (format parquet, compression zstd)")
    con.close()
    size = sum(f.stat().st_size for f in PQ.glob("*.parquet")) / 1e6
    print(f"built {PQ} ({size:.1f} MB) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
