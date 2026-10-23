"""All-category catalogue + deterministic category-expert tools ("the LLM talks, code decides").

Data: backend/app/data/catalog/{products,offers,categories}.parquet (built by scripts/build_catalog.py) and the
existing normalized shops in data/pq/shops.parquet.  Own read-only DuckDB connection with lazy parquet views
(nothing is loaded into memory up front).

Public API
    search_categories(query, limit)                       -> [category dict]
    supported_dimensions(category)                        -> expert dimensions / filters for a category
    search_products(query, category, budget_max, installment_only, area, priorities, limit)
    product_details(product_id)
    find_product_shops(product_id, installment_only, area, budget_max, visit_at)   (same schema as tools.find_shops)

Honesty rules: a spec exists only if it was parsed from the product's own spec sheet (or its title, marked
source="title"); unknown stays unknown and is scored below any known-good value, never as a quality claim.
Expert ranking is relative to the same category (percentiles); broad mode (non-expert categories, incl. phones)
never applies phone ratings or priorities.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import duckdb

from app.data import parsers as P
from app.db import PQ_DIR
from app.tools import _open_status, finalize_shops, fmt_toman, norm_passage, walking_route  # noqa: F401

CAT_DIR = Path(os.environ.get("APP_CATALOG", Path(__file__).parent / "data" / "catalog"))

EXPERT_KINDS = {
    "هدفون، هدست و هندزفری": "headphones",
    "اسپیکر و سیستم صوتی": "speaker",
    "دوربین مدار بسته": "cctv",
    "پاوربانک و شارژر همراه": "powerbank",
}
EXPERT_HEADPHONES = "هدفون، هدست و هندزفری"
RATIONALE = {
    "هدفون، هدست و هندزفری": "complexity 81 + viability 100 (rank 1 non-phone); rich comparable specs (battery, ANC, driver, BT)",
    "اسپیکر و سیستم صوتی": "complexity 81 + viability 99 (rank 2); battery/power/BT specs; 220 shops",
    "دوربین مدار بسته": "complexity 61 + viability 100; resolution/night-vision/IP specs; 259 shops",
    "پاوربانک و شارژر همراه": "complexity 72 + viability 86; capacity/output/ports specs; 37 installment shops. "
                             "Chosen over microphones (tie 158, fewer specs) and LED panels (avg 9.2 specs)",
}
_STOP = {"بهترین", "خوب", "یک", "برای", "با", "و", "از", "در", "به", "مدل", "قیمت", "خرید", "میخوام", "می", "خواهم", "یه"}
_SYN = {"لپتاپ": "لپ تاپ", "تلوزیون": "تلویزیون", "هندزفري": "هندزفری", "ساعت هوشمند": "ساعت هوشمند",
        "پاور بانک": "پاوربانک", "ایرپاد": "هدفون", "هدست": "هدفون", "اسپيکر": "اسپیکر", "سیسیتیوی": "دوربین مدار بسته",
        "بیسیم": "بی سیم", "بلوتوثی": "بلوتوث"}


# ================================================================ text helpers
def _qnorm(q: str | None) -> str:
    s = P.norm(q).lower()
    for a, b in _SYN.items():
        s = s.replace(a, b)
    return s


def tokenize(q: str | None) -> list[str]:
    toks = re.findall(r"[0-9a-z\u0600-\u06ff]+", _qnorm(q))
    return [t for t in toks if t not in _STOP]


def _num(s: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", re.sub(r"(?<=\d),(?=\d{3})", "", s).replace("/", "."))
    return float(m.group(1)) if m else None


# ================================================================ spec extraction (pure)
class _X:
    """Collects extracted specs + evidence for one product."""

    def __init__(self, sm: dict[str, str], title: str):
        self.sm, self.title, self.specs, self.ev = {P.norm(k): P.norm(v) for k, v in sm.items()}, P.norm(title), {}, {}

    def get(self, keys, sub: str | None = None):
        for k in keys:
            if k in self.sm:
                yield k, self.sm[k]
        if sub:
            for k, v in self.sm.items():
                if sub in k and k not in keys:
                    yield k, v

    def put(self, field, value, source, key=None, raw=None):
        if value is None or field in self.specs:
            return False
        self.specs[field] = value
        self.ev[field] = {"source": source, "key": key, "raw": raw}
        return True

    def num(self, field, keys, rx, scale=1.0, title_rx=None, sub=None, lo=None, hi=None):
        for k, v in self.get(keys, sub):
            m = re.search(rx, re.sub(r"(?<=\d),(?=\d{3})", "", v), re.I)
            if m:
                x = float(m.group(1)) * (scale(m) if callable(scale) else scale)
                if (lo is None or x >= lo) and (hi is None or x <= hi) and self.put(field, round(x, 3), "spec", k, v):
                    return
        if title_rx:
            m = re.search(title_rx, re.sub(r"(?<=\d),(?=\d{3})", "", self.title), re.I)
            if m:
                x = float(m.group(1))
                if (lo is None or x >= lo) and (hi is None or x <= hi):
                    self.put(field, round(x, 3), "title", "title", m.group(0))

    def flag(self, field, keys, sub=None):
        for k, v in self.get(keys, sub):
            r = P.yes_no(v)
            if r is not None:
                self.put(field, r, "spec", k, v)
                return

    def weight(self):
        self.num("weight_g", ["وزن", "وزن (گرم)"], r"(\d+(?:\.\d+)?)\s*(کیلو ?گرم?|kg|گرم|g)\b",
                 lambda m: 1000.0 if m.group(2).lower().startswith(("کیلو", "kg")) else 1.0, lo=1, hi=50000)


def _extract_headphones(x: _X):
    for k, v in x.get(["نوع اتصال"], "نوع اتصال"):
        wl, wd = bool(re.search(r"بی ?سیم|بلوتوث|wireless", v, re.I)), bool(re.search(r"با ?سیم|کابل|jack|wired", v, re.I))
        if wl or wd:
            x.put("connection", "both" if wl and wd else "wireless" if wl else "wired", "spec", k, v)
            break
    for k, v in x.get(["نسخه بلوتوث", "بلوتوث"]):
        n = _num(v)
        if n and 1 <= n <= 6.5 and x.put("bluetooth_version", n, "spec", k, v):
            break
    if "bluetooth_version" in x.specs and "connection" not in x.specs:
        x.specs["connection"] = "wireless"
        x.ev["connection"] = dict(x.ev["bluetooth_version"])
    # active noise cancelling: conservative three-state
    for k, v in x.get(["قابلیت نویز کنسلینگ", "نویز کنسلینگ", "حذف نویز", "کنسل کننده نویز", "قابلیت حذف نویز"]):
        if re.search(r"ندارد|فاقد|بدون", v):
            x.put("anc", "none", "spec", k, v)
        elif re.search(r"anc|active|اکتیو|فعال|هیبرید|hybrid", v, re.I) or not re.search(r"enc|میکروفون|مکالمه|تماس", v, re.I):
            x.put("anc", "active", "spec", k, v)
        else:
            x.put("anc", "call_mic_only", "spec", k, v)
        break
    if "anc" not in x.specs and re.search(r"\banc\b|نویز ?کنسل|حذف نویز|noise ?cancel", x.title, re.I):
        x.put("anc", "active", "title", "title", "claimed in title")
    x.num("battery_hours", ["عمر باتری هدفون در حالت پخش موسیقی", "عمر باتری", "مدت زمان پخش موسیقی", "زمان پخش موسیقی",
                            "مدت زمان کار با باتری", "زمان کارکرد"], r"(\d+(?:\.\d+)?)\s*(ساعت|دقیقه|hr?s?|min)",
          lambda m: 1 / 60 if m.group(2).startswith(("دقیقه", "min")) else 1.0, lo=0.2, hi=200)
    x.num("driver_mm", ["قطر درایور", "اندازه درایور", "درایور"], r"(\d+(?:\.\d+)?)\s*(?:میلی|mm)", lo=3, hi=100)
    x.num("impedance_ohm", ["امپدانس"], r"(\d+(?:\.\d+)?)\s*(کیلو ?)?\s*(?:اهم|ohm|Ω)",
          lambda m: 1000.0 if m.group(2) else 1.0, lo=1, hi=1000000)
    x.num("battery_mah", ["ظرفیت باتری"], r"(\d+(?:\.\d+)?)\s*(?:میلی ?آمپر|mah)", lo=20, hi=20000)
    x.flag("has_mic", ["میکروفون"])
    x.weight()
    for k, v in x.get(["نوع هدفون، هدست و هندزفری", "نوع هدفون", "نوع"], "نوع هدفون"):
        form = ("on_ear" if re.search(r"روی گوش|on-?ear", v, re.I) else
                "over_ear" if re.search(r"دور گوش|over-?ear|روی سر|اطراف گوش", v, re.I) else
                "neckband" if re.search(r"گردنی|neckband", v, re.I) else
                "in_ear" if re.search(r"تو گوشی|داخل گوش|earbud|earphone|in-?ear|ایرپاد|ایربادز", v, re.I) else None)
        if form and x.put("form", form, "spec", k, v):
            break


def _extract_speaker(x: _X):
    x.num("battery_mah", ["ظرفیت باتری"], r"(\d+(?:\.\d+)?)\s*(?:میلی ?آمپر|mah)", lo=100, hi=100000)
    x.num("power_w", ["توان خروجی", "توان", "توان خروجی RMS", "توان RMS", "حداکثر توان"], r"(\d+(?:\.\d+)?)\s*(?:وات|w\b)",
          title_rx=r"(\d+(?:\.\d+)?)\s*وات", lo=0.5, hi=50000)
    for k, v in x.get(["نسخه بلوتوث"]):
        n = _num(v)
        if n and 1 <= n <= 6.5 and x.put("bluetooth_version", n, "spec", k, v):
            x.put("bluetooth", True, "spec", k, v)
            break
    x.flag("bluetooth", ["بلوتوث"])
    x.flag("has_mic_input", ["ورودی میکروفون"])
    x.flag("remote", ["ریموت کنترل"])
    x.weight()
    for k, v in x.get(["نوع اسپیکر"]):
        x.put("portable", bool(re.search(r"قابل حمل|پرتابل|portable", v, re.I)), "spec", k, v)
        break


def _extract_cctv(x: _X):
    for k, v in x.get(["حداکثر رزولوشن", "رزولوشن", "رزولوشن تصویر", "کیفیت تصویر", "سنسور تصویر", "رزولوشن ویدیو"]):
        m = re.search(r"(\d{3,4})\s*(?:[x×*]|در)\s*(\d{3,4})", v, re.I)
        if m and x.put("resolution_mp", round(int(m.group(1)) * int(m.group(2)) / 1e6, 2), "spec", k, v):
            break
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:مگا ?پیکسل|mp\b)", v, re.I)
        if m and 0.3 <= float(m.group(1)) <= 60 and x.put("resolution_mp", float(m.group(1)), "spec", k, v):
            break
    x.num("resolution_mp", [], r"", title_rx=r"(\d+(?:\.\d+)?)\s*(?:مگا ?پیکسل|mp\b)", lo=0.3, hi=60)
    for k, v in x.get(["دید در شب", "برد دید در شب", "نوع دید در شب", "فاصله دید در شب"]):
        if re.search(r"ندارد|فاقد", v):
            x.put("night_vision", False, "spec", k, v)
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:متر|m\b)", v, re.I)
        x.put("night_vision", True, "spec", k, v)
        if m:
            x.put("night_range_m", float(m.group(1)), "spec", k, v)
    for k, v in x.get(["حفاظت", "درجه حفاظت", "استاندارد IP", "مقاومت در برابر آب", "گواهی"]):
        m = re.search(r"ip\s*(\d)(\d)", v, re.I)
        if m and x.put("ip_water", int(m.group(2)), "spec", k, v):
            x.put("ip_dust", int(m.group(1)), "spec", k, v)
            break
    if "ip_water" not in x.specs:
        m = re.search(r"\bip\s*(\d)(\d)\b", x.title, re.I)
        if m:
            x.put("ip_water", int(m.group(2)), "title", "title", m.group(0))
    x.flag("has_mic", ["میکروفون داخلی", "میکروفون"])
    for k, v in x.get(["نوع اتصال"]):
        if re.search(r"wi-?fi|وای ?فای|بی ?سیم", v, re.I):
            x.put("connection", "wifi", "spec", k, v)
        elif re.search(r"با ?سیم", v):
            x.put("connection", "wired", "spec", k, v)
    x.weight()


def _extract_powerbank(x: _X):
    x.num("capacity_mah", ["ظرفیت اسمی", "ظرفیت", "ظرفیت باتری", "ظرفیت واقعی"], r"(\d+(?:\.\d+)?)\s*(?:میلی ?آمپر|mah)",
          title_rx=r"(\d+(?:\.\d+)?)\s*(?:میلی ?آمپر|mah)", lo=500, hi=200000)
    x.num("output_w", ["توان خروجی کلی", "توان خروجی", "حداکثر توان خروجی"], r"(\d+(?:\.\d+)?)\s*(?:وات|w\b)",
          title_rx=r"(\d+(?:\.\d+)?)\s*(?:وات|w\b)", lo=1, hi=500)
    words = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5}
    for k, v in x.get(["تعداد درگاه خروجی", "تعداد پورت خروجی", "تعداد پورت"]):
        m = re.match(r"\s*(\d+)", v)
        n = int(m.group(1)) if m else next((n for w, n in words.items() if v.strip().startswith(w)), None)
        if n and x.put("ports", n, "spec", k, v):
            break
    x.num("output_a", ["شدت جریان خروجی"], r"(\d+(?:\.\d+)?)\s*(?:آمپر|a\b)", lo=0.1, hi=20)
    for k, v in x.get(["سازگار با"]):
        if re.search(r"magsafe|بی ?سیم|wireless", v, re.I):  # positive evidence only; absence is not "no"
            x.put("wireless_charging", True, "spec", k, v)
            break
    x.weight()


_EXTRACTORS = {"headphones": _extract_headphones, "speaker": _extract_speaker, "cctv": _extract_cctv, "powerbank": _extract_powerbank}


def extract_specs(category: str, sm: dict[str, str], title: str = "") -> tuple[dict, dict]:
    """(specs, evidence) for an expert category; both empty for others."""
    kind = EXPERT_KINDS.get(category, category)
    fn = _EXTRACTORS.get(kind)
    if not fn:
        return {}, {}
    x = _X(sm, title)
    fn(x)
    return x.specs, x.ev


# ================================================================ expert dimensions
# dim -> (field, mode, Persian label, aliases)
_ANC = {"active": 1.0, "call_mic_only": 0.3, "none": 0.0}
DIMS = {
    "headphones": {
        "battery": ("battery_hours", "hi", "عمر باتری", ["باتری", "شارژدهی", "battery", "عمر باتری"]),
        "noise": ("anc", "enum", "حذف نویز فعال", ["نویز", "anc", "noise", "نویز کنسلینگ", "حذف نویز"]),
        "sound": ("driver_mm", "hi", "قطر درایور (نشانگر محدود کیفیت صدا)", ["صدا", "کیفیت صدا", "sound", "درایور", "باس"]),
        "mic": ("has_mic", "bool", "میکروفون", ["میکروفون", "مکالمه", "mic", "تماس"]),
        "light": ("weight_g", "lo", "سبکی", ["سبک", "وزن", "light"]),
    },
    "speaker": {
        "battery": ("battery_mah", "hi", "ظرفیت باتری", ["باتری", "شارژدهی", "battery"]),
        "power": ("power_w", "hi", "توان خروجی", ["توان", "قدرت", "صدا", "بلند", "power", "volume"]),
        "bluetooth": ("bluetooth", "bool", "بلوتوث", ["بلوتوث", "بی سیم", "bluetooth", "wireless"]),
        "portable": ("weight_g", "lo", "سبکی/حمل آسان", ["سبک", "حمل", "پرتابل", "portable", "وزن"]),
    },
    "cctv": {
        "resolution": ("resolution_mp", "hi", "رزولوشن", ["رزولوشن", "کیفیت", "وضوح", "resolution", "کیفیت تصویر"]),
        "night": ("night_range_m", "hi", "برد دید در شب", ["شب", "دید در شب", "night"]),
        "weather": ("ip_water", "ip", "مقاومت در برابر آب", ["بیرون", "فضای باز", "ضد آب", "آب", "ip", "weather", "outdoor"]),
        "audio": ("has_mic", "bool", "میکروفون داخلی", ["صدا", "میکروفون", "audio", "mic"]),
    },
    "powerbank": {
        "capacity": ("capacity_mah", "hi", "ظرفیت", ["ظرفیت", "شارژ", "capacity", "mah", "باتری"]),
        "speed": ("output_w", "hi", "توان شارژ سریع", ["سرعت", "فست", "سریع", "توان", "وات", "fast", "speed"]),
        "portable": ("weight_g", "lo", "سبکی", ["سبک", "وزن", "حمل", "portable", "light"]),
        "ports": ("ports", "hi", "تعداد درگاه خروجی", ["پورت", "درگاه", "ports"]),
    },
}
for _k in DIMS.values():
    _k["value"] = (None, "value", "صرفه اقتصادی (قیمت نسبت به همان دسته)", ["ارزان", "قیمت", "اقتصادی", "بودجه", "value", "cheap", "ارزان تر"])
    _k["availability"] = (None, "availability", "تعداد فروشگاه‌های دارای کالا", ["موجودی", "دسترسی", "فروشگاه", "availability"])

_FIELD_FA = {
    "battery_hours": "عمر باتری {:g} ساعت", "driver_mm": "درایور {:g} میلی‌متر", "battery_mah": "باتری {:g} میلی‌آمپرساعت",
    "power_w": "توان {:g} وات", "resolution_mp": "رزولوشن {:g} مگاپیکسل", "night_range_m": "دید در شب {:g} متر",
    "ip_water": "مقاومت در برابر آب IPx{:g}", "capacity_mah": "ظرفیت {:g} میلی‌آمپرساعت", "output_w": "توان خروجی {:g} وات",
    "ports": "{:g} درگاه خروجی", "weight_g": "وزن {:g} گرم",
}


def _kind(category: str | None) -> str | None:
    return EXPERT_KINDS.get(category or "") or (category if category in DIMS else None)


def normalize_priorities(category_or_kind: str | None, priorities: list[str] | None) -> tuple[list[str], list[str]]:
    """Map free-text priorities to supported dimension keys -> (applied, ignored). Non-expert: nothing applies."""
    kind = _kind(category_or_kind)
    if not priorities:
        return [], []
    if not kind:
        return [], list(priorities)
    dims = DIMS[kind]
    applied, ignored = [], []
    for p in priorities:
        s = _qnorm(p)
        hit = s if s in dims else next((d for d, (_, _, _, al) in dims.items() if s in [_qnorm(a) for a in al]), None)
        if hit is None:
            hit = next((d for d, (_, _, _, al) in dims.items() if any(len(a) > 2 and _qnorm(a) in s for a in al)), None)
        if hit and hit not in applied:
            applied.append(hit)
        elif not hit:
            ignored.append(p)
    return applied, ignored


# ================================================================ data access
_lock = threading.Lock()
_root: duckdb.DuckDBPyConnection | None = None
_local = threading.local()


def available() -> bool:
    return all((CAT_DIR / f"{n}.parquet").exists() for n in ("products", "offers", "categories")) and (PQ_DIR / "shops.parquet").exists()


def _con() -> duckdb.DuckDBPyConnection:
    global _root
    if _root is None:
        with _lock:
            if _root is None:
                c = duckdb.connect(":memory:")
                c.execute("set threads=4")
                c.execute("set memory_limit='400MB'")
                for n in ("products", "offers", "categories"):
                    c.execute(f"create view {n} as select * from read_parquet('{(CAT_DIR / (n + '.parquet')).as_posix()}')")
                c.execute(f"create view shops as select * from read_parquet('{(PQ_DIR / 'shops.parquet').as_posix()}')")
                _root = c
    cur = getattr(_local, "cur", None)
    if cur is None:
        cur = _local.cur = _root.cursor()
    return cur


def _rows(sql: str, params: list | None = None) -> list[dict]:
    cur = _con().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@lru_cache(maxsize=1)
def _meta() -> dict:
    return json.loads((CAT_DIR / "meta.json").read_text())


@lru_cache(maxsize=1)
def snapshot() -> datetime:
    return datetime.fromisoformat(_meta()["snapshot_at"])


def freshness(ts: datetime | None) -> dict:
    if ts is None:
        return {"tier": "unknown", "label": "تاریخ قیمت نامشخص", "days": None}
    days = (snapshot() - ts).days
    if days <= 7:
        return {"tier": "fresh", "label": "قیمت به‌روز", "days": days}
    if days <= 30:
        return {"tier": "recent", "label": f"قیمت {days} روز پیش", "days": days}
    return {"tier": "old", "label": f"قیمت قدیمی ({days} روز)", "days": days}


@lru_cache(maxsize=1)
def _categories() -> list[dict]:
    return _rows("select * from categories order by n_products desc")


def catalog_stats() -> dict:
    m = _meta()
    return {"n_categories": len(_categories()), "n_products": m["n_products"], "n_offers": m["n_offers"],
            "expert_categories": list(EXPERT_KINDS), "snapshot_at": m["snapshot_at"]}


def expert_categories() -> dict[str, str]:
    return dict(EXPERT_KINDS)


def _cat_public(c: dict) -> dict:
    return {"category": c["category"], "n_products": c["n_products"], "n_priced_products": c["n_priced_products"],
            "n_offers": c["n_offers"], "median_price": c["median_price"], "expert": bool(c["expert"]), "kind": c["kind"],
            "has_installment": bool(c["has_installment"]), "top_brand": c["top_brand"]}


def search_categories(query: str = "", limit: int = 8) -> list[dict]:
    toks = tokenize(query)
    cats = _categories()
    if not toks:
        return [_cat_public(c) for c in cats[:limit]]
    q_compact = "".join(toks)
    scored = []
    for c in cats:
        name = c["search_text"]
        compact = name.replace(" ", "")
        hit = sum(1 for t in toks if t in name or t in compact)
        if hit == 0 and q_compact not in compact:
            continue
        exact = 1 if q_compact == compact else 0
        phrase = 1 if _qnorm(query) in name else 0
        scored.append((-(hit / len(toks)), -exact, -phrase, -int(bool(c["expert"])), -c["n_products"], c))
    scored.sort(key=lambda t: t[:5])
    return [_cat_public(t[5]) for t in scored[:limit]]


def _resolve_category(category: str | None) -> str | None:
    if not category:
        return None
    cn = P.norm(category)
    for c in _categories():
        if c["category"] == cn:
            return cn
    r = search_categories(cn, 1)
    return r[0]["category"] if r else None


def supported_dimensions(category: str) -> dict:
    cat = _resolve_category(category) or category
    kind = EXPERT_KINDS.get(cat)
    if not kind:
        return {"category": cat, "expert": False, "dimensions": [], "note": "broad mode: text/budget/area/installment only; no spec ranking"}
    row = next((c for c in _categories() if c["category"] == cat), None)
    cov = json.loads(row["coverage_json"]) if row and row["coverage_json"] else {}
    dims = []
    for d, (field, mode, label, aliases) in DIMS[kind].items():
        dims.append({"key": d, "label": label, "field": field, "mode": mode, "aliases": aliases,
                     "coverage": cov.get(field) if field else None})
    return {"category": cat, "expert": True, "kind": kind, "dimensions": dims, "spec_coverage": cov,
            "rationale": RATIONALE[cat], "filters": ["budget_max", "installment_only", "area"]}


# ================================================================ ranking
@lru_cache(maxsize=16)
def _dist(category: str) -> dict:
    """Sorted value lists per spec field + price list for priced products of an expert category."""
    rs = _con().execute("select specs_json, price_min from products where category=? and price_min is not null", [category]).fetchall()
    d: dict[str, list] = {"__price": sorted(r[1] for r in rs)}
    for s, _ in rs:
        for k, v in json.loads(s).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                d.setdefault(k, []).append(v)
    for k in d:
        d[k].sort()
    return d


def _pct(vals: list, v) -> float | None:
    if v is None or not vals:
        return None
    from bisect import bisect_left, bisect_right
    return (bisect_left(vals, v) + 0.5 * (bisect_right(vals, v) - bisect_left(vals, v))) / len(vals)


def _dim_score(kind: str, dim: str, specs: dict, dist: dict, price: int, n_shops: int):
    field, mode, label, _ = DIMS[kind][dim]
    if mode == "value":
        p = _pct(dist["__price"], price)
        return (None if p is None else 1 - p), f"قیمت از {100 - round(p * 100) if p is not None else '؟'}٪ محصولات همین دسته ارزان‌تر است" if p is not None else None
    if mode == "availability":
        s = min(n_shops, 5) / 5
        return s, f"موجود در {n_shops} فروشگاه"
    v = specs.get(field)
    if v is None:
        return None, f"{label}: در مشخصات ثبت نشده / نامشخص"
    if mode in ("hi", "lo"):
        p = _pct(dist.get(field, []), v)
        if p is None:
            return None, f"{label}: نامشخص"
        s = p if mode == "hi" else 1 - p
        return s, _FIELD_FA.get(field, "{}").format(v) + f" (بالاتر از {round(p * 100)}٪ دسته)" if mode == "hi" else \
            _FIELD_FA.get(field, "{}").format(v) + f" (سبک‌تر از {round((1 - p) * 100)}٪ دسته)"
    if mode == "enum":
        s = _ANC.get(v)
        txt = {"active": "حذف نویز فعال ثبت شده", "call_mic_only": "فقط حذف نویز میکروفون مکالمه (ENC) ثبت شده، نه ANC کامل",
               "none": "حذف نویز ندارد"}[v]
        return s, txt
    if mode == "bool":
        return (1.0 if v else 0.0), f"{label}: {'دارد' if v else 'ندارد'}"
    if mode == "ip":
        return min(v, 8) / 8, f"مقاومت در برابر آب IPx{v}" if v else "بدون مقاومت در برابر آب"
    return None, None


def _rank_expert(kind: str, cat: str, row: dict, applied: list[str], rel: float, has_query: bool) -> dict:
    specs = json.loads(row["specs_json"])
    dist = _dist(cat)
    weights, parts, reasons, unknowns = [], {}, [], []
    plan = [(d, 3.0) for d in applied] + [("value", 1.0 if "value" not in applied else 0.0), ("availability", 1.0 if "availability" not in applied else 0.0)]
    if not applied:  # default: balanced over all spec dims, light
        plan = [(d, 1.0) for d in DIMS[kind] if d not in ("value", "availability")] + [("value", 1.5), ("availability", 1.0)]
    for dim, w in plan:
        if w <= 0:
            continue
        s, txt = _dim_score(kind, dim, specs, dist, row["price"], row["n_shops"])
        if s is None:  # unknown: below-median neutral, flagged, no quality claim
            s = 0.3
            if txt:
                unknowns.append(txt)
        elif txt and (dim in applied or s >= 0.6):
            reasons.append(txt)
        parts[dim] = round(s, 3)
        weights.append((s, w))
    if has_query:
        weights.append((rel, 1.5))
        parts["query_match"] = round(rel, 3)
    comp = sum(1 for f in {DIMS[kind][d][0] for d in DIMS[kind] if DIMS[kind][d][0]} if f in specs) / max(
        1, len({DIMS[kind][d][0] for d in DIMS[kind] if DIMS[kind][d][0]}))
    weights.append((comp, 0.5))
    parts["spec_completeness"] = round(comp, 3)
    score = round(100 * sum(s * w for s, w in weights) / sum(w for _, w in weights), 1)
    return {"score": score, "score_parts": parts, "reasons": reasons[:5] + unknowns[:3], "unknowns": unknowns, "specs": specs}


# ================================================================ product search
def _product_row(p: dict, specs: dict, ev: dict, expert: bool, score: float, parts: dict, reasons: list, unknowns: list) -> dict:
    return {"product_id": p["product_id"], "name": p["name"], "category": p["category"], "brand": p["brand"], "image": p["image"],
            "price": p["price"], "price_label": fmt_toman(p["price"]), "price_max": p["price_max"], "n_shops": p["n_shops"],
            "n_installment_shops": p["n_inst"], "specs": specs, "evidence": {k: ev[k] for k in specs if k in ev},
            "reasons": reasons, "unknowns": unknowns, "expert": expert, "score": score, "score_parts": parts}


def search_products(query: str = "", category: str | None = None, budget_max: int | None = None,
                    installment_only: bool = False, area: str | None = None, priorities: list[str] | None = None,
                    limit: int = 8, wireless_only: bool = False) -> dict:
    cat = _resolve_category(category) if category else None
    if category and not cat:
        return {"query": query, "category": None, "expert": False, "n_candidates": 0, "products": [], "priorities_applied": [],
                "priorities_ignored": list(priorities or []), "note": "دسته‌بندی پیدا نشد"}
    toks = tokenize(query)
    cat_toks = set(tokenize(cat)) if cat else set()
    qtoks = [t for t in toks if t not in cat_toks] if cat else toks  # words already implied by the category don't filter
    where, params = ["o.price is not null", "not o.price_outlier", "o.condition <> 'used'"], []
    if cat:
        where.append("o.category = ?"); params.append(cat)
    if budget_max:
        where.append("o.price <= ?"); params.append(int(budget_max))
    if installment_only:
        where.append("s.has_installment")
    if area:
        where.append("s.area = ?"); params.append(P.norm(area))

    def run(mode_and: bool):
        tw, tp = "", []
        if qtoks:
            tw = " and (" + (" and " if mode_and else " or ").join("p.search_text like ?" for _ in qtoks) + ")"
            tp = [f"%{t}%" for t in qtoks]
        sql = f"""with f as (select o.product_id, o.shop_id, o.price, s.has_installment inst from offers o join shops s using(shop_id)
                  where {' and '.join(where)}),
             a as (select product_id, min(price) price, max(price) price_max, count(distinct shop_id) n_shops,
                   count(distinct shop_id) filter (where inst) n_inst from f group by 1)
             select p.product_id, p.name, p.brand, p.category, p.image, p.specs_json, p.evidence_json, p.n_specs,
                    a.price, a.price_max, a.n_shops, a.n_inst
             from a join products p on p.product_id = a.product_id where true{tw}
             order by a.n_shops desc, p.n_specs desc, p.product_id limit 3000"""
        return _rows(sql, params + tp)

    cands = run(True)
    if not cands and len(qtoks) > 1:
        cands = run(False)
    cands = [p for p in cands if not looks_fake_or_accessory(p["name"], p["category"], p["price"])]
    if wireless_only:
        cands = [p for p in cands if not _is_wired(p)]
    kind = EXPERT_KINDS.get(cat) if cat else None
    applied, ignored = normalize_priorities(kind, priorities)
    out = []
    for p in cands:
        pkind = EXPERT_KINDS.get(p["category"])
        name_l = p["name"].lower()
        rel = (sum(1 for t in qtoks if t in name_l) / len(qtoks)) if qtoks else 0.5
        if pkind:
            p_applied = applied if pkind == kind else []
            r = _rank_expert(pkind, p["category"], p, p_applied, rel, bool(qtoks))
            out.append(_product_row(p, r["specs"], json.loads(p["evidence_json"]), True, r["score"], r["score_parts"], r["reasons"], r["unknowns"]))
        else:
            avail, comp = min(p["n_shops"], 5) / 5, min(p["n_specs"], 15) / 15
            score = round(100 * (0.45 * rel + 0.30 * avail + 0.25 * comp), 1)
            specs = json.loads(p["specs_json"])
            reasons = [f"قیمت از {fmt_toman(p['price'])}", f"موجود در {p['n_shops']} فروشگاه"]
            if p["n_specs"]:
                reasons.append(f"{p['n_specs']} مشخصه ثبت‌شده")
            out.append(_product_row(p, specs, json.loads(p["evidence_json"]), False, score,
                                    {"query_match": round(rel, 3), "availability": avail, "spec_completeness": round(comp, 3)}, reasons, []))
    out.sort(key=lambda r: (-r["score"], r["price"], r["product_id"]))
    return {"query": query, "category": cat, "expert": bool(kind), "n_candidates": len(out), "products": out[:limit],
            "priorities_applied": applied, "priorities_ignored": ignored,
            "filters": {"budget_max": budget_max, "installment_only": installment_only, "area": area},
            "mode": "expert" if kind else "broad",
            "note": None if kind or not priorities else "اولویت‌ها فقط برای دسته‌های تخصصی اعمال می‌شود؛ در حالت عمومی نادیده گرفته شد"}


# ---------------------------------------------------------------- honesty guards
# Torob lists many look-alikes ("AirPods Max" for 2M toman) and accessories (cases, ear tips) inside expert categories.
# A premium model name priced far below the genuine market floor is treated as a look-alike and never recommended.
_FAKE_WORDS = re.compile(r"کپی|طرح|های ?کپی|فیک|replica|مشابه|شبیه|اورجینال ?طرح|\bmaster ?copy\b", re.I)
_ACCESSORY = re.compile(r"^\s*(کیف|کاور|قاب|محافظ|بند|کابل|پد|ایرتیپ|سری|استند|پایه|کیس)\b|\bcase\b|کاور ", re.I)
_PREMIUM_FLOORS = [  # (pattern, minimum plausible new price in toman, snapshot Oct 2026)
    (re.compile(r"airpods ?max|ایرپاد ?مکس", re.I), 60_000_000),
    (re.compile(r"airpods ?pro|ایرپاد ?پرو", re.I), 12_000_000),
    (re.compile(r"airpods|ایرپاد|ایرپادز", re.I), 7_000_000),
    (re.compile(r"galaxy ?buds|گلکسی ?بادز|بادز ?(?:پرو|۳|3|fe)", re.I), 4_000_000),
    (re.compile(r"bose|بوز", re.I), 15_000_000),
    (re.compile(r"wh-?1000|سونی ?wh", re.I), 20_000_000),
]


def looks_fake_or_accessory(name: str, category: str, price) -> bool:
    if category not in EXPERT_KINDS:
        return False
    n = name or ""
    if _FAKE_WORDS.search(n) or _ACCESSORY.search(n):
        return True
    if price:
        for rx, floor in _PREMIUM_FLOORS:
            if rx.search(n):
                return price < floor
    return False


def _is_wired(p: dict) -> bool:
    sp = json.loads(p.get("specs_json") or "{}")
    if sp.get("connection") == "wired":
        return True
    return bool(re.search(r"با ?سیم|سیمی", p["name"] or "")) and not re.search(r"بی ?سیم|بلوتوث", p["name"] or "")


# ================================================================ product details / shops
def product_details(product_id: str) -> dict | None:
    r = _rows("select * from products where product_id=?", [product_id])
    if not r:
        return None
    p = r[0]
    offers = _rows("""select min(price) price_min, median(price) price_med, max(price) price_max, count(*) n,
                      count(distinct o.shop_id) n_shops, count(distinct o.shop_id) filter (where s.has_installment) n_installment_shops
                      from offers o join shops s using(shop_id)
                      where o.product_id=? and o.price is not null and not o.price_outlier and o.condition <> 'used'""", [product_id])[0]
    expert = p["category"] in EXPERT_KINDS
    return {"product_id": p["product_id"], "name": p["name"], "category": p["category"], "brand": p["brand"], "model": p["model"],
            "image": p["image"], "expert": expert, "specs": json.loads(p["specs_json"]), "evidence": json.loads(p["evidence_json"]),
            "raw_specs": json.loads(p["raw_specs_json"]), "offers": offers,
            "kind": EXPERT_KINDS.get(p["category"]), "unknown_fields": [] if not expert else [
                d for d, (f, m, *_r) in DIMS[EXPERT_KINDS[p["category"]]].items() if f and f not in json.loads(p["specs_json"])]}


def find_product_shops(product_id: str, installment_only: bool = False, area: str | None = None, budget_max: int | None = None,
                       visit_at: str | None = None) -> dict:
    """Same output schema as tools.find_shops (so the contact simulator / route UI can be reused)."""
    where, params = ["o.product_id = ?", "not o.price_outlier", "o.condition <> 'used'"], [product_id]
    if installment_only:
        where.append("s.has_installment")
    if area:
        where.append("s.area = ?"); params.append(P.norm(area))
    if budget_max:
        where.append("o.price is not null and o.price <= ?"); params.append(int(budget_max))
    r = _rows(f"""select o.offer_id, o.price price_toman, o.price_changed_at, o.warranty_kind, o.warranty_months, o.warranty_text,
               s.shop_id, s.name, s.address, s.area, s.passage, s.floor_label, s.floor_num, s.unit, s.has_installment,
               s.payment_json, s.hours_json, s.contacts_json, p.name title
        from offers o join shops s using(shop_id) join products p using(product_id) where {' and '.join(where)}""", params)
    when = datetime.fromisoformat(visit_at) if visit_at else None
    prices = [x["price_toman"] for x in r if x["price_toman"]]
    pmin = min(prices) if prices else None
    out = []
    for x in r:
        fr = freshness(x["price_changed_at"])
        op = _open_status(x["hours_json"], when)
        pay = [p["provider"] for p in json.loads(x["payment_json"] or "[]")]
        parts = {"price": 4.0 * (pmin / x["price_toman"]) if x["price_toman"] and pmin else 1.0,
                 "freshness": {"fresh": 2.0, "recent": 1.2, "old": 0.3, "unknown": 0}[fr["tier"]],
                 "warranty": {"official": 2.0, "store_test": 0.8, "other": 0.8, "none": 0, "unknown": 0.4}[x["warranty_kind"] or "unknown"],
                 "registry": 0.4,
                 "open": {"open": 1.0, "listed": 0.6, "unknown": 0.3, "closed": 0, "closed_then": 0}[op["status"]]}
        if budget_max and x["price_toman"]:
            parts["budget"] = 1.0 if x["price_toman"] <= budget_max else max(0.0, 1 - 10 * (x["price_toman"] / budget_max - 1))
        out.append({
            "offer_id": x["offer_id"], "shop_id": x["shop_id"], "shop_name": x["name"], "address": x["address"],
            "area": x["area"], "passage": x["passage"], "passage_key": norm_passage(x["passage"]),
            "floor": x["floor_label"], "floor_num": x["floor_num"], "unit": x["unit"], "title": x["title"],
            "variant": {"storage_gb": None, "ram_gb": None}, "price": x["price_toman"], "price_label": fmt_toman(x["price_toman"]),
            "over_budget": bool(budget_max and x["price_toman"] and x["price_toman"] > budget_max),
            "freshness": fr, "stock": {"status": "unconfirmed", "label": "موجودی تأیید نشده"},
            "warranty": {"kind": x["warranty_kind"], "months": x["warranty_months"], "text": x["warranty_text"]},
            "registry": "unknown", "installment": x["has_installment"], "payment_providers": pay,
            "open": op, "score": round(sum(parts.values()), 2), "score_parts": {k: round(v, 2) for k, v in parts.items()},
            "phone_listed": bool(json.loads(x["contacts_json"] or "[]")),
        })
    r = finalize_shops(product_id, out, pmin, prices)
    r["product_id"] = product_id
    return r


# ================================================================ current item (expert categories)
def _parse_capacity_hint(q: str) -> float | None:
    s = _qnorm(q)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(هزار|k)\b", s)
    if m:
        return float(m.group(1)) * 1000
    m = re.search(r"(\d{4,5})", s)
    return float(m.group(1)) if m else None


def lookup_current_item(query: str, category: str) -> dict | None:
    """Starting point for an expert category: dataset product by name match, else (powerbank) a stated capacity.
    Returns None when nothing is known — never invents specs."""
    cat = _resolve_category(category) or category
    kind = EXPERT_KINDS.get(cat)
    if not kind or not query:
        return None
    toks = [t for t in tokenize(query) if t not in set(tokenize(cat)) and not t.isdigit()]
    toks = [t for t in toks if len(t) >= 2]
    if toks:
        rows = _rows(f"""select product_id, name, specs_json from products where category = ? and
                          ({' and '.join('search_text like ?' for _ in toks)}) order by n_specs desc limit 1""",
                     [cat] + [f"%{t}%" for t in toks])
        if rows and json.loads(rows[0]["specs_json"]):
            return {"found": True, "source": "dataset", "name": rows[0]["name"], "product_id": rows[0]["product_id"],
                    "specs": json.loads(rows[0]["specs_json"]), "source_label": "از داده‌های ترب"}
    if kind == "powerbank":
        cap = _parse_capacity_hint(query)
        if cap and 1000 <= cap <= 60000:
            return {"found": True, "source": "user", "name": f"پاوربانک فعلی ({cap:g} میلی‌آمپرساعت)",
                    "specs": {"capacity_mah": cap}, "source_label": "گفتهٔ خود شما"}
    return None


def annotate_vs_current(result: dict, current: dict | None) -> None:
    """Add a per-spec comparison against the user's current item (only for specs known on both sides)."""
    kind = EXPERT_KINDS.get(result.get("category") or "")
    if not kind or not current:
        return
    modes = {f: (m, label) for d, (f, m, label, _a) in DIMS[kind].items() if f and m in ("hi", "lo")}
    cs = current.get("specs") or {}
    for p in result["products"]:
        vs, better = {}, []
        for f, (mode, label) in modes.items():
            a, b = cs.get(f), p["specs"].get(f)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a:
                diff = (b - a) / a
                good = diff > 0.05 if mode == "hi" else diff < -0.05
                vs[f] = {"label": label, "current": a, "new": b, "pct": round(100 * diff), "better": good}
                if good:
                    better.append(f"{label}: {abs(round(100 * diff))}٪ {'بیشتر' if mode == 'hi' else 'کمتر'} از وسیلهٔ فعلی")
        p["vs_current"] = vs
        p["reasons"] = better[:2] + [r for r in p["reasons"] if r not in better]
