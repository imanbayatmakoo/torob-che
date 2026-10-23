"""Text normalization and spec/title parsers for Torob phone data (pure functions, unit-tested)."""
from __future__ import annotations

import re

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
AR_CHARS = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " ", "ـ": ""})


def norm(s: str | None) -> str:
    """Persian/Arabic digits -> ASCII, Arabic letters -> Persian, ZWNJ -> space, collapse spaces."""
    if s is None:
        return ""
    s = str(s).translate(FA_DIGITS).translate(AR_CHARS)
    return re.sub(r"\s+", " ", s).strip()


def _num(s: str) -> float | None:
    m = re.search(r"(\d+(?:[.,/]\d+)?)", s)
    if not m:
        return None
    return float(m.group(1).replace(",", ".").replace("/", "."))


def parse_storage_gb(v: str | None) -> float | None:
    """'256 گیگابایت' -> 256; '1 ترابایت' -> 1024; '128 مگابایت' -> 0.125."""
    s = norm(v).lower()
    n = _num(s)
    if n is None:
        return None
    if "ترا" in s or "tb" in s:
        return n * 1024
    if "مگ" in s or "mb" in s:
        return round(n / 1024, 4)
    if "کیلو" in s or "kb" in s:
        return round(n / 1024 / 1024, 6)
    return n


def parse_mah(v: str | None) -> int | None:
    s = norm(v)
    m = re.search(r"(\d{3,5})", s.replace(",", ""))
    if not m:
        return None
    n = int(m.group(1))
    return n if 300 <= n <= 20000 else None


def parse_inch(v: str | None) -> float | None:
    s = norm(v)
    m = re.search(r"(\d{1,2}(?:\.\d{1,2})?)\s*(?:اینچ|inch|\"|in\b)", s)
    n = float(m.group(1)) if m else _num(s)
    return n if n and 1.0 <= n <= 12 else None


def parse_mp(v: str | None) -> float | None:
    """Largest megapixel value in a camera string; None for 'ندارد'."""
    s = norm(v)
    if not s or s in {"ندارد", "title"}:
        return None
    unit = r"\s*(?:MP|مگا\s*پیکسل|مگاپیکسل|megapixel)"
    vals = []
    # chains like "64+12+5 مگاپیکسل" or "2 + 8 + 50 مگاپیکسل": every number in the chain counts
    for chain in re.findall(r"((?:\d{1,3}(?:\.\d)?\s*\+\s*)*\d{1,3}(?:\.\d)?)" + unit, s, re.I):
        vals += [float(x) for x in re.findall(r"\d{1,3}(?:\.\d)?", chain)]
    vals = [v for v in vals if 0.3 <= v <= 250]
    return max(vals) if vals else None


def parse_year(v: str | None) -> int | None:
    m = re.search(r"(20[0-3]\d)", norm(v))
    return int(m.group(1)) if m else None


def parse_sim(v: str | None) -> int | None:
    s = norm(v)
    if re.search(r"دو|2|dual", s, re.I):
        return 2
    if re.search(r"یک|تک|1|single", s, re.I):
        return 1
    return None


def parse_os(v: str | None) -> str | None:
    s = norm(v).lower()
    if "ios" in s or "آی او اس" in s:
        return "ios"
    if "android" in s or "اندروید" in s:
        return "android"
    if "harmony" in s:
        return "harmonyos"
    if "بدون" in s or "rtos" in s or "series" in s or "s30" in s:
        return "feature"
    return None


def yes_no(v: str | None) -> bool | None:
    s = norm(v)
    if not s:
        return None
    if re.search(r"ندارد|عدم|فاقد|خیر|no\b", s, re.I):
        return False
    if re.search(r"دارد|بله|yes|✔", s, re.I) or re.search(r"\w", s):
        return True
    return None


# --- Chipset performance tier (0-10). Ordered: first match wins. ---
CHIP_TIERS: list[tuple[str, float]] = [
    (r"a20\s*pro", 10), (r"a19\s*pro", 10), (r"a20\b", 9.6), (r"a19\b", 9.5), (r"a18\s*pro", 9.6), (r"a18\b", 9.3),
    (r"a17\s*pro", 9.2), (r"a16", 8.8), (r"a15", 8.3), (r"a14", 7.8), (r"a13", 7.3), (r"a12", 6.6), (r"a11", 5.8),
    (r"apple\s*a10", 5.0),
    (r"exynos\s*99[0-9]", 6.4), (r"exynos\s*98[0-9]{2}", 6.0), (r"exynos\s*96[0-9]{2}", 3.6), (r"exynos\s*7[89][0-9]{2}", 2.4),
    (r"snapdragon\s*86[05]", 7.2), (r"snapdragon\s*778", 6.3), (r"kirin\s*8[0-9]{2}", 4.6), (r"kirin\s*7[0-9]{2}", 3.4),
    (r"8\s*elite\s*gen\s*5|8\s*gen\s*5", 10), (r"8\s*elite", 9.7), (r"8\s*gen\s*3", 9.2), (r"8s?\s*gen\s*2", 8.6), (r"8\+?\s*gen\s*1", 8.0),
    (r"8s\s*gen\s*[34]", 8.8), (r"snapdragon\s*8[78]\d", 7.6), (r"7\+\s*gen\s*[23]", 8.0), (r"7s?\s*gen\s*[34]", 6.9),
    (r"7s?\s*gen\s*[12]", 6.3), (r"snapdragon\s*7[0-9]{2}", 5.6), (r"6s?\s*gen\s*[34]", 5.8), (r"6s?\s*gen\s*[12]", 5.2),
    (r"snapdragon\s*6[0-9]{2}", 4.3), (r"4s?\s*gen\s*[1234]", 4.4), (r"snapdragon\s*6s?\s*(?:4g\s*)?gen\s*\d", 5.0), (r"snapdragon\s*4[0-9]{2}", 3.2),
    (r"snapdragon\s*2[0-9]{2}", 1.0),
    (r"dimensity\s*9[45]\d{2}", 9.8), (r"dimensity\s*9[23]\d{2}", 9.0), (r"dimensity\s*9[01]\d{2}", 8.3),
    (r"dimensity\s*8[3-5]\d{2}", 8.0), (r"dimensity\s*8[0-2]\d{2}", 7.2), (r"dimensity\s*7[3-4]\d{2}", 6.5),
    (r"dimensity\s*7[0-2]\d{2}", 5.8), (r"dimensity\s*6\d{3}", 4.6), (r"dimensity", 5.0),
    (r"(?:helio|mtk|mediatek)\s*g1[0-9]{2}", 4.6), (r"(?:helio|mtk|mediatek)\s*g9\d", 4.4),
    (r"(?:helio|mtk|mediatek)\s*g8\d", 3.6), (r"(?:helio|mtk|mediatek)\s*g[3-7]\d", 2.6),
    (r"(?:helio|mtk|mediatek)\s*g[12]\d\b", 1.6), (r"mtk?\s*67[0-9]{2}|mt67[0-9]{2}", 1.0), (r"mtk?\s*6580|mt6580", 0.6),
    (r"helio\s*[pa]\d", 2.4), (r"tensor\s*g[56]", 8.6), (r"tensor\s*g[34]", 7.8), (r"tensor", 7.0),
    (r"exynos\s*2[0-9]{3}", 8.8), (r"exynos\s*1[6-9]\d{2}", 7.0), (r"exynos\s*1[45]\d{2}", 6.3),
    (r"exynos\s*13\d{2}", 5.4), (r"exynos\s*12\d{2}", 4.8), (r"exynos\s*9\d{2}", 4.0), (r"exynos\s*8\d{2}", 3.0),
    (r"kirin\s*9\d{3}", 8.0), (r"unisoc\s*t8\d{2}", 4.6), (r"unisoc\s*t7\d{2}|t7[0-9]{3}", 3.6),
    (r"unisoc\s*t6\d{2}|t6[0-9]{2}\b", 3.0), (r"sc98|9863|t[13]\d{2}\b|t107|t117|t127", 1.0),
    (r"mt626|mt62[0-9]{2}|mtk\s*626|rtos|sc65|6531", 0.2),
]


def chip_tier(chip: str | None) -> float | None:
    s = norm(chip).lower().replace("_", " ")
    if not s or s in {"دارد", "ندارد"}:
        return None
    s = re.sub(r"\bsm\d{4}[-\w]*", " ", s)
    s = s.replace("اسنپدراگون", "snapdragon").replace("کوالکام", "qualcomm").replace("دیمنسیتی", "dimensity")
    s = re.sub(r"snapdragon\s*سری\s*(\d)\s*نسل\s*(\d)", r"snapdragon \1 gen \2", s)
    for pat, tier in CHIP_TIERS:
        if re.search(pat, s):
            return tier
    return None


# --- Title-level signals ---
def title_storage_ram(title: str) -> tuple[float | None, float | None]:
    t = norm(title)
    st = ram = None
    m = re.search(r"(?:حافظه|ظرفیت)\s*(\d+)\s*(ترابایت|tb|گیگ\S*|مگ\S*|gb|mb)?", t, re.I)
    if m:
        unit = (m.group(2) or "gb").lower()
        st = parse_storage_gb(f"{m.group(1)} {unit}")
        if st and st >= 2048 and not unit.startswith(("ت", "t")):
            st = None
    else:
        m = re.search(r"(\d{2,4})\s*(?:gb|g\b|گیگ)", t, re.I)
        if m:
            st = float(m.group(1))
    m = re.search(r"رم\s*(\d{1,2})\s*(گیگ\S*|gb|مگ\S*|mb)?", t, re.I)
    if m:
        unit = (m.group(2) or "gb").lower()
        ram = float(m.group(1)) / (1024 if unit.startswith(("م", "m")) else 1)
    return st, ram


def condition_from_text(text: str) -> str:
    """new | used | replica | unknown — 'used' = استوک/کارکرده, 'replica' = طرح/های کپی."""
    t = norm(text)
    if re.search(r"(?:^|\s|\()طرح\s|های\s*کپی|کپی\s", t):
        return "replica"
    if re.search(r"استوک|کارکرده|دست\s*دوم|ریفربیش|refurb", t, re.I):
        return "used"
    if re.search(r"آکبند|نو\b|اورجینال|اصلی", t):
        return "new"
    return "unknown"


def registry_from_text(text: str) -> str:
    """registered | not_registered | unknown (Iran IMEI registry)."""
    t = norm(text).lower()
    if re.search(r"بدون\s*(?:رجیستر|ریجستر)|عدم\s*(?:رجیستر|ریجستر)|not\s*register", t):
        return "not_registered"
    if re.search(r"رجیستر|ریجستر|کد\s*فعال|همتا|register", t):
        return "registered"
    return "unknown"


def warranty_kind(provider: str | None, months: int | None, desc: str | None) -> str:
    """official | store_test | none | other | unknown."""
    p, d = norm(provider), norm(desc)
    both = f"{p} {d}"
    if not p and not d:
        return "unknown"
    if "بدون گارانتی" in both:
        return "none"
    if "شرکتی" in both or "هماهنگ" in both or (months and months >= 12):
        return "official"
    if "تست و تحویل" in both:
        return "store_test"
    if re.search(r"گارانتی|ضمانت|خدمات پس از فروش", both):
        return "other"
    return "unknown"


def warranty_months(provider: str | None, months, desc: str | None) -> int | None:
    if months not in (None, "null", ""):
        try:
            return int(float(months))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s*ماه", norm(f"{provider or ''} {desc or ''}"))
    return int(m.group(1)) if m else None


# --- Address → passage / floor / unit ---
FLOOR_WORDS = {"همکف": 0, "زیرزمین": -1, "منفی یک": -1, "منفی دو": -2, "اول": 1, "دوم": 2, "سوم": 3, "چهارم": 4,
               "پنجم": 5, "ششم": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10, "همکف اول": 0}


def parse_address(addr: str | None) -> dict:
    a = norm(addr)
    parts = [p.strip() for p in re.split(r"[،,]", a) if p.strip()]
    passage = None
    for p in parts:
        if re.match(r"^(پاساژ|مجتمع|مرکز خرید|بازار|تیمچه|سرای|سرا|برج|مال)\b", p) or re.search(r"\b(پاساژ|مجتمع تجاری|مرکز خرید)\b", p):
            passage = re.sub(r"^(?:.*?)(پاساژ|مجتمع|مرکز خرید|بازار|تیمچه|سرای|سرا|برج|مال)", r"\1", p).strip()
            break
    floor_label = floor_num = None
    m = re.search(r"طبقه\s*([^\s،,]+(?:\s*(?:یک|دو|اول|همکف))?)", a)
    if m:
        raw = m.group(1).strip()
        floor_label = f"طبقه {raw}"
        if re.fullmatch(r"-?\d+", raw):
            floor_num = int(raw)
        elif raw.startswith("زیر"):
            floor_num, floor_label = -1, "زیر همکف"
        elif raw.startswith("منفی"):
            floor_num = -2 if "دو" in raw else -1
        else:
            floor_num = FLOOR_WORDS.get(raw.split()[0])
    elif re.search(r"همکف", a):
        floor_label, floor_num = "همکف", 0
    unit = None
    m = re.search(r"(?:واحد|پلاک|غرفه|مغازه)\s*([\w/\-]+)", a)
    if m:
        unit = m.group(0).strip()
    return {"passage": passage, "floor_label": floor_label, "floor_num": floor_num, "unit": unit}
