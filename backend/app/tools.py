"""Deterministic tools: "the LLM talks, code decides".

Every fact shown to the user comes from these functions, never from LLM text.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.data import parsers as P
from app.db import one, rows

TEHRAN = timezone(timedelta(hours=3, minutes=30))
KNOWN_BRANDS = {"apple", "samsung", "xiaomi", "honor", "google", "nothing", "motorola", "realme", "oneplus",
                "huawei", "vivo", "oppo", "sony", "nokia"}
DIMS = ["camera", "battery", "speed", "storage"]
DIM_FA = {"camera": "دوربین", "battery": "باتری", "speed": "سرعت", "storage": "حافظه"}
FA_TRANSLIT = {"ردمی": "redmi", "نوت": "note", "پرو مکس": "pro max", "پرو": "pro", "مکس": "max", "آیفون": "iphone",
               "ایفون": "iphone", "پوکو": "poco", "گلکسی": "galaxy ", "گالکسی": "galaxy ", "اولترا": "ultra", "الترا": "ultra",
               "پلاس": "plus", "لایت": "lite", "آنر": "honor", "نوکیا": "nokia", "هواوی": "huawei", "هوآوی": "huawei"}
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # python weekday() order
DAY_FA = {"sat": "شنبه", "sun": "یکشنبه", "mon": "دوشنبه", "tue": "سه‌شنبه", "wed": "چهارشنبه", "thu": "پنجشنبه", "fri": "جمعه"}


# ---------------------------------------------------------------- helpers
@lru_cache(maxsize=1)
def snapshot() -> datetime:
    return one("select snapshot_at from meta")["snapshot_at"]


@lru_cache(maxsize=1)
def distributions() -> dict:
    """Smartphone distributions used to rate phones that are not in the dataset (reference phones)."""
    r = rows("select battery_mah, main_mp from phones where segment='smartphone' and condition<>'replica'")
    return {"battery": sorted(x["battery_mah"] for x in r if x["battery_mah"]),
            "mp": sorted(x["main_mp"] for x in r if x["main_mp"])}


def _pct(values: list, v) -> float | None:
    if v is None or not values:
        return None
    below = sum(1 for x in values if x < v)
    eq = sum(1 for x in values if x == v)
    return (below + 0.5 * eq) / len(values)


def freshness(ts: datetime | None) -> dict:
    if ts is None:
        return {"tier": "unknown", "label": "تاریخ قیمت نامشخص", "days": None}
    days = (snapshot() - ts).days
    if days <= 7:
        tier, label = "fresh", "قیمت به‌روز"
    elif days <= 30:
        tier, label = "recent", f"قیمت {days} روز پیش"
    else:
        tier, label = "old", f"قیمت قدیمی ({days} روز)"
    return {"tier": tier, "label": label, "days": days}


def norm_passage(p: str | None) -> str | None:
    if not p:
        return None
    s = P.norm(p)
    s = re.sub(r"علاءالدین|علائدین|علاالدین", "علاالدین", s)
    s = re.sub(r"^(?:پاساژ|بازار موبایل|مجتمع تجاری|مجتمع)\s*", "", s)
    s = s.replace("چهارسو", "چارسو")
    return re.sub(r"\s+\d+$", "", s).strip()


def fmt_toman(n: int | float | None) -> str:
    if n is None:
        return "قیمت ثبت نشده"
    m = n / 1_000_000
    return f"{m:,.1f} میلیون تومان".replace(".0 ", " ")


def display_name(title: str, brand_en: str, model: str | None) -> str:
    t = P.norm(title).split("|")[0]
    t = re.sub(r"گوشی(?:\s*موبایل)?|مدل|\(.*?\)|دو سیم ?کارت|تک سیم ?کارت|ظرفیت.*|حافظه.*", " ", t)
    latin = " ".join(re.findall(r"[A-Za-z0-9+]+", t))
    if latin:
        return f"{brand_en.title()} {latin}".replace("Apple iPhone", "iPhone").replace("Apple Iphone", "iPhone")
    return re.sub(r"\s+", " ", t).strip() or f"{brand_en.title()} {model}"


BRAND_WORDS = {"apple": ["اپل", "آیفون", "ایفون", "iphone", "apple"], "samsung": ["سامسونگ", "samsung", "galaxy", "گلکسی"],
               "xiaomi": ["شیائومی", "xiaomi", "redmi", "poco", "ردمی", "پوکو"], "nokia": ["نوکیا", "nokia"],
               "huawei": ["هوآوی", "هواوی", "huawei"], "honor": ["آنر", "honor"]}
MIN_GENUINE_SMARTPHONE = 25_000_000  # Oct 2026 Tehran market: cheaper "brand" smartphones are look-alikes or mislisted


def genuine(c: dict) -> bool:
    """Drop look-alikes filed under a big brand (e.g. 'یونیوا 16Pro Max' under Apple) and implausible prices."""
    t = P.norm(c["title"]).lower()
    words = BRAND_WORDS.get(c["brand_en"])
    if words and not any(w in t for w in words):
        return False
    if c["brand_en"] != "nokia" and c["price"] < MIN_GENUINE_SMARTPHONE:
        return False
    return True


# ---------------------------------------------------------------- step 0: current phone
def _ref_ratings(r: dict) -> dict:
    d = distributions()
    pb = _pct(d["battery"], r.get("battery_mah"))
    pm = _pct(d["mp"], r.get("main_mp"))
    chip = r.get("chip_tier")
    cam_parts = [x for x in [10 * pm if pm is not None else None, chip] if x is not None]
    sto = r.get("storage_gb")
    return {
        "battery": round(10 * pb, 1) if pb is not None else None,
        "camera": round(sum(cam_parts) / len(cam_parts), 1) if cam_parts else None,
        "speed": chip,
        "storage": None if not sto else round(min(10, 10 * (sto / 512) ** 0.5), 1),
    }


def lookup_current_phone(text: str) -> dict:
    """Three-step lookup: dataset model -> curated reference table -> unknown (agent may estimate, labeled)."""
    q = P.norm(text).lower()
    for fa, en in FA_TRANSLIT.items():
        q = q.replace(fa, en)
    q_compact = re.sub(r"[\s\-]", "", q)
    # 1) curated reference (older phones, aliases in fa/en)
    best = None
    for r in rows("select * from reference_phones"):
        for a in [r["model"].lower()] + (r["aliases"] or "").split("|"):
            a = P.norm(a).lower().strip()
            ac = re.sub(r"[\s\-]", "", a)
            if ac and (ac in q_compact) and (best is None or len(ac) > best[0]):
                best = (len(ac), r)
    # 2) dataset models (current phones)
    dbest = None
    for m in rows("select model_key, brand_en, model from models where segment='smartphone' and model_key not like 'replica%'"):
        mc = re.sub(r"[\s\-]", "", (m["model"] or "").lower())
        if len(mc) >= 3 and mc in q_compact and (dbest is None or len(mc) > dbest[0]):
            dbest = (len(mc), m)
    if dbest and (best is None or dbest[0] > best[0]):
        mk = dbest[1]["model_key"]
        p = one("""select model_key, brand_en, model, avg(battery_mah) battery_mah, max(main_mp) main_mp, max(chip_tier) chip_tier,
                   min(storage_gb) storage_gb, min(ram_gb) ram_gb, any_value(chipset) chipset, round(avg(rating_camera),1) camera,
                   round(avg(rating_battery),1) battery, round(avg(rating_speed),1) speed, round(min(rating_storage),1) "storage",
                   any_value(image) image
                   from phones where model_key=? group by all""", [mk])
        return {"found": True, "source": "dataset", "source_label": "از داده‌های ترب",
                "name": f"{p['brand_en'].title()} {p['model']}", "model_key": mk,
                "specs": {k: p[k] for k in ["battery_mah", "main_mp", "chip_tier", "storage_gb", "ram_gb", "chipset"]},
                "ratings": {k: p[k] for k in DIMS}, "image": p["image"]}
    if best:
        r = best[1]
        return {"found": True, "source": "reference", "source_label": "از جدول مرجع گوشی‌های قدیمی",
                "name": f"{r['brand'].title()} {r['model']}", "year": r["year"],
                "specs": {k: r[k] for k in ["battery_mah", "main_mp", "chip_tier", "storage_gb", "ram_gb", "chipset"]},
                "ratings": _ref_ratings(r)}
    return {"found": False, "source": None,
            "note": "این گوشی در داده‌ها و جدول مرجع نیست؛ اگر دستیار تخمین بزند، باید با برچسب «تخمینی» نشان داده شود."}


# ---------------------------------------------------------------- step 1: recommend models
def _offer_filter_sql(installment_only: bool, allow_used: bool, area: str | None) -> tuple[str, list]:
    w = ["not o.price_outlier", "o.price_toman is not null", "s.lists_phones"]
    params: list = []
    if installment_only:
        w.append("s.has_installment")
    if not allow_used:
        w.append("coalesce(o.condition,'unknown') <> 'used' and p.condition <> 'used'")
    if area:
        w.append("s.area = ?")
        params.append(area)
    return " and ".join(w), params


def recommend(budget_max: int, budget_min: int | None = None, priorities: list[str] | None = None,
              current: dict | None = None, pain_points: list[str] | None = None, installment_only: bool = False,
              allow_used: bool = False, os_pref: str | None = None, brands: list[str] | None = None,
              min_storage_gb: int | None = None, area: str | None = None) -> dict:
    """Return three picks (best match, cheaper, step up) with deterministic reasons."""
    priorities = [p for p in (priorities or []) if p in DIMS]
    pain_points = [p for p in (pain_points or []) if p in DIMS]
    weights = {d: 1.0 for d in DIMS}
    for i, p in enumerate(priorities):
        weights[p] += 3.0 - i * 0.8
    for p in pain_points:
        weights[p] += 1.5
    weights["storage"] *= 0.6

    w, params = _offer_filter_sql(installment_only, allow_used, area)
    cand = rows(f"""
        select p.product_id, p.model_key, p.brand_en, p.brand_fa, p.model, p.title, p.storage_gb, p.ram_gb, p.battery_mah,
               p.main_mp, p.chipset, p.chip_tier, p.os, p.image, p.rating_camera camera, p.rating_battery battery,
               p.rating_speed speed, p.rating_storage "storage", p.speed_basis, p.key_specs_known, p.key_specs_total,
               p.filled_fields, p.year,
               min(o.price_toman) price, count(distinct o.shop_id) n_shops, max(o.price_changed_at) last_change,
               count(distinct o.shop_id) filter (where s.has_installment) n_inst_shops
        from phones p join phone_offers o using(product_id) join shops s using(shop_id)
        where p.segment='smartphone' and p.condition <> 'replica' and {w}
        group by all""", params)
    cand = [c for c in cand if c["brand_en"] in KNOWN_BRANDS and genuine(c)]
    if os_pref in ("ios", "android"):
        cand = [c for c in cand if (c["brand_en"] == "apple") == (os_pref == "ios")]
    if brands:
        cand = [c for c in cand if c["brand_en"] in brands]
    if min_storage_gb:
        cand = [c for c in cand if (c["storage_gb"] or 0) >= min_storage_gb]

    cur = (current or {}).get("ratings") or {}

    def score(c):
        tot = wsum = 0.0
        for d in DIMS:
            v = c[d] if c[d] is not None else 3.5  # unknown spec: pessimistic neutral
            tot += weights[d] * v
            wsum += weights[d]
        s = tot / wsum
        s += 0.6 * min(c["n_shops"], 8) / 8  # in-person availability matters: more shops = more choice + fallback
        return round(s, 3)

    def ok_vs_current(c):
        """Guardrail: never recommend something worse on a stated pain point."""
        for p in pain_points:
            if cur.get(p) is not None and (c[p] is None or c[p] <= cur[p]):
                return False
        return True

    # one row per model: the best-scoring variant (ties -> cheaper), chosen separately inside/outside the budget
    lo = budget_min or 0

    def dedupe(rows_):
        by: dict[str, dict] = {}
        for c in rows_:
            k = c["model_key"]
            if k not in by or (c["score"], -c["price"]) > (by[k]["score"], -by[k]["price"]):
                by[k] = c
        return by

    for c in cand:
        c["score"] = score(c)
    by_model = dedupe(cand)
    models = [m for m in by_model.values() if ok_vs_current(m)]
    guard_removed = len(by_model) - len(models)
    within = [m for m in dedupe([c for c in cand if lo <= c["price"] <= budget_max]).values() if ok_vs_current(m)]
    in_budget = sorted(within, key=lambda m: -m["score"])
    picks = []
    relaxed = None
    if not in_budget:
        # fallback: widen budget by 15%, then show nearest
        in_budget = sorted([m for m in models if m["price"] <= budget_max * 1.15], key=lambda m: -m["score"])
        relaxed = "budget_+15%" if in_budget else None
    if in_budget:
        # prefer a model you can actually find in several shops if it is nearly as good
        best = next((m for m in in_budget if m["n_shops"] >= 3 and m["score"] >= in_budget[0]["score"] - 0.4), in_budget[0])
        picks.append(("best", best))
        cheaper = [m for m in in_budget if m is not best and best["price"] * 0.45 <= m["price"] <= best["price"] * 0.85]
        if cheaper:
            picks.append(("cheaper", max(cheaper, key=lambda m: m["score"] - 0.000000002 * m["price"])))
        inb = {m["model_key"] for m in in_budget}
        up = sorted([m for m in models if m["model_key"] not in inb and budget_max < m["price"] <= budget_max * 1.3 and m["score"] > best["score"] + 0.25],
                    key=lambda m: -(m["score"] - best["score"]) / max(1, (m["price"] - best["price"]) / 1e7))
        if up:
            picks.append(("step_up", up[0]))
        elif len(in_budget) > 1:
            alt = next((m for m in in_budget[1:] if m["model_key"] not in {p[1]["model_key"] for p in picks}), None)
            if alt:
                picks.append(("alternative", alt))

    label = {"best": "بهترین انتخاب برای شما", "cheaper": "ارزان‌تر، با کمی مصالحه",
             "step_up": "کمی بیشتر بدهید، خیلی بهتر بگیرید", "alternative": "گزینهٔ دیگر در همین بودجه"}
    out = []
    for role, m in picks:
        out.append(_card(m, role, label[role], cur, priorities, pain_points))
    floor = min((m["price"] for m in models), default=None)
    note = None
    if not out:
        note = "در این بودجه و با این فیلترها گوشی مناسبی پیدا نشد."
        if floor and budget_max < floor:
            note = (f"ارزان‌ترین گوشی هوشمند اصل از برندهای شناخته‌شده در بازار حضوری الان از {fmt_toman(floor)} شروع می‌شود. "
                    "زیر این قیمت معمولاً طرح/کپی است.")
    return {"picks": out, "considered_models": len(by_model), "guardrail_removed": guard_removed,
            "relaxed": relaxed, "weights": weights, "market_floor": floor, "note": note}


def _card(m: dict, role: str, label: str, cur: dict, priorities: list[str], pain_points: list[str]) -> dict:
    vs = {}
    for d in DIMS:
        if cur.get(d) is not None and m[d] is not None:
            vs[d] = round(m[d] - cur[d], 1)
    reasons = []
    for d in pain_points:
        if vs.get(d) is not None and vs[d] > 0:
            reasons.append(f"{DIM_FA[d]} خیلی بهتر از گوشی فعلی (+{vs[d]})")
    if m["battery_mah"]:
        reasons.append(f"باتری {m['battery_mah']:,} میلی‌آمپر")
    if m["main_mp"]:
        reasons.append(f"دوربین اصلی {m['main_mp']:g} مگاپیکسل")
    if m["chipset"] and m["chip_tier"] is not None:
        reasons.append(f"تراشه {P.norm(m['chipset'])[:40]}")
    return {
        "role": role, "role_label": label, "model_key": m["model_key"], "product_id": m["product_id"],
        "name": display_name(m["title"], m["brand_en"], m["model"]), "title": m["title"], "image": m["image"],
        "variant": {"storage_gb": m["storage_gb"], "ram_gb": m["ram_gb"]},
        "price_from": m["price"], "price_label": f"از {fmt_toman(m['price'])}", "n_shops": m["n_shops"],
        "n_inst_shops": m["n_inst_shops"],
        "freshness": freshness(m["last_change"]),
        "ratings": {d: m[d] for d in DIMS}, "speed_basis": m["speed_basis"],
        "vs_current": vs, "reasons": reasons[:5], "score": m["score"],
        "confidence": {"known": m["key_specs_known"], "total": m["key_specs_total"],
                       "label": f"بر اساس {m['key_specs_known']} از {m['key_specs_total']} مشخصه",
                       "filled_from_variant": m["filled_fields"]},
    }


# ---------------------------------------------------------------- step 2/3: shops for a model
def _open_status(hours_json: str | None, when: datetime | None) -> dict:
    if not hours_json:
        return {"status": "unknown", "label": "ساعت کاری نامشخص"}
    if when is None:
        return {"status": "listed", "label": "ساعت کاری ثبت شده"}
    h = json.loads(hours_json)
    day = DAY_KEYS[when.weekday()]
    d = h.get(day) or {}
    shifts = [s for s in d.get("shifts", []) if s and s != ["00:00", "00:00"]]
    if d.get("status") == "closed" or not shifts:
        return {"status": "closed", "label": f"{DAY_FA[day]} تعطیل"}
    t = when.strftime("%H:%M")
    for a, b in shifts:
        if a <= t < b:
            return {"status": "open", "label": f"باز ({a}–{b})"}
    return {"status": "closed_then", "label": f"در آن ساعت بسته ({', '.join(f'{a}–{b}' for a, b in shifts)})"}


def find_shops(model_key: str, storage_gb: float | None = None, installment_only: bool = False,
               allow_used: bool = False, area: str | None = None, visit_at: str | None = None,
               budget_max: int | None = None) -> dict:
    """All in-person offers for a model, scored and ordered into a walking route."""
    w, params = _offer_filter_sql(installment_only, allow_used, area)
    w = w.replace("o.price_toman is not null", "true")  # keep 'price not listed' shops (call to ask)
    sql = f"""select o.offer_id, o.price_toman, o.price_changed_at, o.warranty_kind, o.warranty_months, o.warranty_text,
               o.registry, o.condition, p.storage_gb, p.ram_gb, p.title, p.product_id,
               s.shop_id, s.name, s.address, s.area, s.passage, s.floor_label, s.floor_num, s.unit, s.has_installment,
               s.payment_json, s.hours_json, s.contacts_json, s.real_name, s.fast_delivery
        from phone_offers o join phones p using(product_id) join shops s using(shop_id)
        where p.model_key = ? and {w}"""
    r = rows(sql, [model_key] + params)
    if storage_gb:
        same = [x for x in r if x["storage_gb"] == storage_gb]
        r = same or r
    when = datetime.fromisoformat(visit_at) if visit_at else None
    prices = [x["price_toman"] for x in r if x["price_toman"]]
    pmin = min(prices) if prices else None
    out = []
    for x in r:
        fr = freshness(x["price_changed_at"])
        op = _open_status(x["hours_json"], when)
        pay = [p["provider"] for p in json.loads(x["payment_json"] or "[]")]
        # deterministic shop score (0-10) with visible breakdown
        parts = {}
        parts["price"] = 4.0 * (pmin / x["price_toman"]) if x["price_toman"] and pmin else 1.0
        parts["freshness"] = {"fresh": 2.0, "recent": 1.2, "old": 0.3, "unknown": 0}[fr["tier"]]
        parts["warranty"] = {"official": 2.0, "store_test": 0.8, "other": 0.8, "none": 0, "unknown": 0.4}[x["warranty_kind"] or "unknown"]
        parts["registry"] = {"registered": 1.0, "unknown": 0.4, "not_registered": 0}[x["registry"] or "unknown"]
        parts["open"] = {"open": 1.0, "listed": 0.6, "unknown": 0.3, "closed": 0, "closed_then": 0}[op["status"]]
        if budget_max and x["price_toman"]:
            parts["budget"] = 1.0 if x["price_toman"] <= budget_max else max(0.0, 1 - 10 * (x["price_toman"] / budget_max - 1))
        score = round(sum(parts.values()), 2)
        out.append({
            "offer_id": x["offer_id"], "shop_id": x["shop_id"], "shop_name": x["name"], "address": x["address"],
            "area": x["area"], "passage": x["passage"], "passage_key": norm_passage(x["passage"]),
            "floor": x["floor_label"], "floor_num": x["floor_num"], "unit": x["unit"],
            "title": x["title"], "variant": {"storage_gb": x["storage_gb"], "ram_gb": x["ram_gb"]},
            "price": x["price_toman"], "price_label": fmt_toman(x["price_toman"]),
            "over_budget": bool(budget_max and x["price_toman"] and x["price_toman"] > budget_max),
            "freshness": fr, "stock": {"status": "unconfirmed", "label": "موجودی تأیید نشده"},
            "warranty": {"kind": x["warranty_kind"], "months": x["warranty_months"], "text": x["warranty_text"]},
            "registry": x["registry"], "installment": x["has_installment"], "payment_providers": pay,
            "open": op, "score": score, "score_parts": {k: round(v, 2) for k, v in parts.items()},
            "phone_listed": bool(json.loads(x["contacts_json"] or "[]")),
        })
    return finalize_shops(model_key, out, pmin, prices)


def finalize_shops(key: str, out: list[dict], pmin, prices: list) -> dict:
    """One row per seller (best eligible offer), mark actionable rows, rank, and build the route from actionable only."""
    # Repeated offer rows of the same shop must not look like extra fallback shops.
    best_by_shop: dict[str, dict] = {}
    for o in out:
        cur = best_by_shop.get(o["shop_id"])
        if cur is None or (o["score"], -(o["price"] or 10**15)) > (cur["score"], -(cur["price"] or 10**15)):
            best_by_shop[o["shop_id"]] = o
    out = list(best_by_shop.values())
    for o in out:
        closed = o["open"]["status"] in ("closed", "closed_then")
        o["actionable"] = not o["over_budget"] and not closed
        o["blocked_reason"] = "بالاتر از بودجه" if o["over_budget"] else ("در زمان انتخابی بسته است" if closed else None)
    out.sort(key=lambda s: (not s["actionable"], -s["score"], s["shop_id"]))
    for i, s in enumerate(out):
        s["rank"] = i + 1
    actionable = [x for x in out if x["actionable"]]
    return {"model_key": key, "n": len(out), "n_actionable": len(actionable), "shops": out, "price_min": pmin,
            "price_max": max(prices) if prices else None, "route": walking_route(actionable[:6])}


def walking_route(shops: list[dict]) -> list[dict]:
    """Simple in-person route: group by passage, then floor ascending. (No map routing in the MVP.)"""
    groups: dict[str, list[dict]] = {}
    for s in shops:
        groups.setdefault(s["passage_key"] or s["address"] or "؟", []).append(s)
    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    route = []
    for key, g in order:
        g.sort(key=lambda s: (s["floor_num"] if s["floor_num"] is not None else 99))
        for s in g:
            route.append({"step": len(route) + 1, "shop_id": s["shop_id"], "shop_name": s["shop_name"],
                          "passage": s["passage"], "floor": s["floor"], "unit": s["unit"], "price_label": s["price_label"]})
    return route


def shop_detail(shop_id: str) -> dict | None:
    return one("select shop_id, name, address, area, passage, floor_label, unit, has_installment, payment_json, hours_json from shops where shop_id=?", [shop_id])


def model_specs(model_key: str) -> list[dict]:
    return rows("""select product_id, title, storage_gb, ram_gb, battery_mah, main_mp, selfie_mp, chipset, screen_in, os, year,
                   rating_camera camera, rating_battery battery, rating_speed speed, rating_storage "storage", image
                   from phones where model_key=? order by storage_gb""", [model_key])


def compare_models(model_keys: list[str]) -> list[dict]:
    out = []
    for mk in model_keys[:3]:
        r = one("""select m.model_key, m.brand_en, m.model, m.min_price, m.n_shops, max(p.battery_mah) battery_mah, max(p.main_mp) main_mp,
                   any_value(p.chipset) chipset, max(p.screen_in) screen_in, round(max(p.rating_camera),1) camera,
                   round(max(p.rating_battery),1) battery, round(max(p.rating_speed),1) speed, any_value(p.image) image
                   from models m join phones p using(model_key) where m.model_key=? group by all""", [mk])
        if r:
            t = one("select title from phones where model_key=? limit 1", [mk])["title"]
            r["name"] = display_name(t, r["brand_en"], r["model"])
            out.append(r)
    return out
