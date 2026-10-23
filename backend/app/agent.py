"""Agent orchestrator: the LLM talks, code decides.

The LLM chooses which deterministic tool to call and writes short Persian narration.
All cards/facts sent to the UI come from tool output (events), never from LLM text.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime

from app import catalog as C
from app import llm, shop_agent
from app import tools as T

TODAY = "جمعه ۲ آبان ۱۴۰۵ (2026-10-24)"  # overridden at runtime


def _today() -> str:
    now = datetime.now(T.TEHRAN)
    days = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
    return f"{days[now.weekday()]} {now.strftime('%Y-%m-%d %H:%M')} (به وقت تهران)"


SYSTEM = """تو «تربچه» (torob-che) هستی: دستیار فارسی‌زبان برای خرید حضوری از بازارها و پاساژهای تهران با داده‌های ترب.
تخصص عمیق: گوشی موبایل + چهار دستهٔ تخصصی (هدفون/هندزفری، اسپیکر، دوربین مدار بسته، پاوربانک). بقیهٔ ۳۴۰۰+ دسته در «حالت جست‌وجوی عمومی» پشتیبانی می‌شوند.
هدف: سخت‌ترین خرید را برای یک آدم معمولی ساده کنی. کوتاه، گرم و روشن حرف بزن (حداکثر ۳ جملهٔ کوتاه). اصطلاح فنی را ساده کن.

قوانین سخت:
- هیچ مدل، قیمت، مغازه، آدرس، یا مشخصه‌ای از خودت نساز. همهٔ این‌ها از ابزارها می‌آید و رابط کاربری به‌صورت کارت نشان می‌دهد؛ تو فقط جمع‌بندی کوتاه کن و به کارت‌ها اشاره کن. لیست تکراری ننویس.
- قیمت ثبت‌شده ≠ موجودی. همیشه بگو موجودی باید تأیید شود (مرحلهٔ تماس).
- تماس با مغازه‌ها شبیه‌سازی است؛ این را پنهان نکن.
- اگر بودجه از کف بازار کمتر بود، صادقانه بگو و دو راه بده: کمی بودجه بیشتر (با کف بازار) یا گوشی ساده/دکمه‌ای یا کارکرده (allow_used). هرگز گوشی طرح/کپی پیشنهاد نده.
- منطقه شرط سخت است: اگر در منطقهٔ انتخابی چیزی نبود، بدون اجازهٔ کاربر منطقه را گسترش نده؛ فقط تعداد گزینه‌های بیرون منطقه را بگو و بپرس.
- مغازه‌ای که در زمان رفتن بسته است یا بالای بودجه است در برنامهٔ تماس/مسیر نمی‌آید؛ اگر همه این‌طورند، بگو زمان یا بودجه را عوض کند.
- اقساط فیلتر سخت است: اگر کاربر اقساطی خواست، فقط مدل‌ها و مغازه‌هایی نشان داده می‌شوند که در ترب روش پرداخت اقساطی (ترب‌پی، اسنپ‌پی، دیجی‌پی، تارا، ازکی‌وام) ثبت کرده‌اند. اگر نتیجه کم بود، صادقانه بگو و پیشنهاد بده بودجه را تغییر دهد یا شرط اقساط را بردارد.
- اگر کاربر گوشی فعلی‌اش را گفت، lookup_current_phone را صدا بزن و پیشنهادها را با «نسبت به گوشی فعلی» قاب کن. اگر پیدا نشد، تخمینت را صریحاً «تخمینی» بنام.

مسیر گوشی: (۰) گوشی فعلی و مشکلاتش (اختیاری) → (۱) پیدا کردن مدل درست → (۲) مغازه‌هایی که دارند → (۳) مقایسهٔ مغازه‌ها → (۴) تماس با مغازه‌ها و برنامهٔ رفتن.
در شروع، اگر بودجه معلوم نیست فقط یک سؤال بپرس (بودجه + برای چه کسی/چه کاری + گوشی فعلی). حداکثر دو سؤال پشت سر هم؛ وقتی بودجه را داری، recommend_phones را صدا بزن.
هر وقت اطلاعات تازه‌ای گرفتی (بودجه، اولویت، اقساط، زمان رفتن، گوشی فعلی، مشکلات) اول update_profile را صدا بزن.
اولویت‌ها و مشکلات گوشی فقط از این‌ها: camera, battery, speed, storage. «عکاسی/دوربین»→camera، «شارژ/باتری»→battery، «کندی/هنگ/بازی»→speed، «پر شدن حافظه»→storage.
مبلغ‌ها را به تومان کامل بفرست (۲۰ میلیون = 20000000). اگر کاربر «تومن» یا «میلیون» گفت همین را تبدیل کن.
زمان رفتن را به فرمت ISO محلی تهران بفرست (مثلاً 2026-10-24T17:00). امروز: {today}.
اگر بعد از نمایش پیشنهادها بودجه/اولویت/اقساط/منطقه عوض شد، بعد از update_profile دوباره ابزار پیشنهاد همان دسته را صدا بزن تا کارت‌ها به‌روز شوند.
وقتی کاربر یک گوشی انتخاب کرد find_shops را صدا بزن؛ وقتی خواست مطمئن شود/تماس بگیری، contact_shops را صدا بزن.

مسیر کالاهای غیرگوشی:
- اگر کاربر چیزی غیر از گوشی خواست، search_products را با category (اگر مطمئن نیستی اول search_categories) و budget_max همان کالا صدا بزن. بودجهٔ گوشی را برای کالای دیگر استفاده نکن.
- دسته‌های تخصصی و سؤال‌های کلیدی (حداکثر یک سؤال کوتاه قبل از جست‌وجو، اگر بودجه/کاربری مبهم بود):
  • «هدفون، هدست و هندزفری»: بی‌سیم/باسیم، حذف نویز، مکالمه، ورزش/سبکی، عمر باتری → priorities از battery, noise, sound, mic, light, value
  • «اسپیکر و سیستم صوتی»: قابل حمل یا خانگی، بلندی صدا، باتری → battery, power, bluetooth, portable, value
  • «دوربین مدار بسته»: داخل یا بیرون ساختمان، دید در شب، کیفیت تصویر، صدا → resolution, night, weather, audio, value
  • «پاوربانک و شارژر همراه»: چند بار شارژ گوشی، شارژ سریع، وزن، تعداد پورت → capacity, speed, portable, ports, value
- اگر کاربر وسیلهٔ فعلی‌اش را گفت (مثلاً «پاوربانک فعلیم ۱۰ هزاره»)، current_item_query را بفرست تا کارت‌ها «نسبت به وسیلهٔ فعلی» مقایسه شوند.
- برای بقیهٔ دسته‌ها حالت عمومی است: محصول واقعی، قیمت و مغازه‌ها و مشخصات خام نشان داده می‌شود، اما امتیاز کیفیت نداریم؛ این را صادقانه بگو و ادعای «بهتر بودن» نکن.
- وقتی کاربر یک کالا را انتخاب کرد find_product_shops، و بعد برای تأیید موجودی contact_shops را صدا بزن.
"""

TOOLS = [
    {"type": "function", "function": {
        "name": "update_profile", "description": "ذخیرهٔ نیازهای کاربر. فقط فیلدهای تازه را بفرست.",
        "parameters": {"type": "object", "properties": {
            "budget_max": {"type": "integer", "description": "سقف بودجه به تومان"},
            "budget_min": {"type": "integer"},
            "priorities": {"type": "array", "items": {"type": "string", "enum": T.DIMS}, "description": "به ترتیب اهمیت"},
            "pain_points": {"type": "array", "items": {"type": "string", "enum": T.DIMS}, "description": "مشکلات گوشی فعلی"},
            "installment_only": {"type": "boolean"}, "allow_used": {"type": "boolean"},
            "os_pref": {"type": "string", "enum": ["ios", "android", "any"]},
            "visit_at": {"type": "string", "description": "ISO local time, e.g. 2026-10-24T17:00"},
            "area": {"type": "string", "description": "منطقهٔ ثبت‌شده در ترب، مثل «شیخ هادی» (= جمهوری/علاالدین/چارسو)، «فردوسی»، «بهارستان»، «تجریش». برای حذف: «همه»"},
            "for_whom": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "lookup_current_phone", "description": "پیدا کردن مشخصات گوشی فعلی کاربر (دیتاست ترب ← جدول مرجع).",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "recommend_phones", "description": "سه پیشنهاد (بهترین، ارزان‌تر، یک پله بالاتر) بر اساس پروفایل. کارت‌ها خودکار نمایش داده می‌شوند.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "compare_models", "description": "مقایسهٔ ۲ یا ۳ مدل",
        "parameters": {"type": "object", "properties": {"model_keys": {"type": "array", "items": {"type": "string"}}}, "required": ["model_keys"]}}},
    {"type": "function", "function": {
        "name": "find_shops", "description": "مغازه‌های حضوری که این مدل را دارند، رتبه‌بندی‌شده با مسیر پیشنهادی.",
        "parameters": {"type": "object", "properties": {"model_key": {"type": "string"}, "storage_gb": {"type": "number"}}, "required": ["model_key"]}}},
    {"type": "function", "function": {
        "name": "search_categories", "description": "پیدا کردن دستهٔ درست ترب برای یک کالای غیرگوشی (از بین ۳۴۰۰+ دسته).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_products", "description": "پیشنهاد کالاهای غیرگوشی با پیشنهادهای واقعی مغازه‌های حضوری. در دسته‌های تخصصی رتبه‌بندی بر اساس مشخصات؛ در بقیه حالت عمومی. کارت‌ها خودکار نمایش داده می‌شوند.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "کلمات کلیدی مدل/برند/نوع، اختیاری"},
            "category": {"type": "string", "description": "نام دقیق دستهٔ ترب"},
            "budget_max": {"type": "integer", "description": "سقف بودجهٔ همین کالا به تومان"},
            "budget_min": {"type": "integer", "description": "کف قیمت به تومان، اختیاری"},
            "priorities": {"type": "array", "items": {"type": "string"}, "description": "کلیدهای اولویت همان دسته"},
            "current_item_query": {"type": "string", "description": "وسیلهٔ فعلی کاربر در همین دسته، اختیاری"}}}}},
    {"type": "function", "function": {
        "name": "find_product_shops", "description": "مغازه‌های حضوری که این کالای غیرگوشی را دارند، رتبه‌بندی‌شده با مسیر.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]}}},
    {"type": "function", "function": {
        "name": "contact_shops", "description": "تماس شبیه‌سازی‌شده با بهترین مغازه‌ها برای تأیید موجودی/قیمت/اقساط؛ اگر جواب ندهند خودکار سراغ بعدی می‌رود.",
        "parameters": {"type": "object", "properties": {
            "chosen_shop_id": {"type": "string", "description": "اگر کاربر یک مغازهٔ مشخص را انتخاب کرد؛ اول فقط همان تماس گرفته می‌شود و اگر نشد سراغ بعدی می‌رود"},
            "shop_ids": {"type": "array", "items": {"type": "string"}, "description": "اختیاری"}}}}},
]


class Session:
    def __init__(self, sid: str):
        self.id = sid
        self.messages: list[dict] = []
        self.profile: dict = {}
        self.current: dict | None = None
        self.last_picks: list[dict] = []
        self.model: dict | None = None  # {"model_key","name","storage_gb"}
        self.shops: list[dict] = []
        self.products: list[dict] = []
        self.product_ctx: dict = {}
        self.contacts: list[dict] = []
        self.chosen_shop_id: str | None = None
        self.stage = 0
        self.updated = time.time()


SESSIONS: dict[str, Session] = {}


def get_session(sid: str | None) -> Session:
    if sid and sid in SESSIONS:
        return SESSIONS[sid]
    s = Session(sid or uuid.uuid4().hex[:12])
    SESSIONS[s.id] = s
    if len(SESSIONS) > 500:
        for k in sorted(SESSIONS, key=lambda k: SESSIONS[k].updated)[:100]:
            SESSIONS.pop(k, None)
    return s


def _visit_label(p: dict) -> str | None:
    v = p.get("visit_at")
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    day = T.DAY_FA[T.DAY_KEYS[dt.weekday()]]
    return f"{day} ساعت {dt.strftime('%H:%M')}"


# ---------------------------------------------------------------- tool execution
async def run_tool(s: Session, name: str, args: dict, emit) -> dict:
    """Execute a tool; emit UI events; return a COMPACT summary for the LLM."""
    p = s.profile
    if name == "update_profile":
        for k, v in args.items():
            if v not in (None, "", []):
                if k == "os_pref" and v == "any":
                    p.pop("os_pref", None)
                    continue
                if k == "area" and v in ("همه", "همه مناطق", "all"):
                    p.pop("area", None)
                    continue
                p[k] = v
        emit({"type": "profile", "profile": p, "visit_label": _visit_label(p), "current": s.current})
        return {"ok": True, "profile": p}

    if name == "lookup_current_phone":
        r = T.lookup_current_phone(args.get("text", ""))
        if r["found"]:
            s.current = r
            p["current_phone"] = r["name"]
        emit({"type": "current_phone", "data": r})
        if s.stage < 1:
            s.stage = 0
        return {k: r.get(k) for k in ["found", "source", "name", "ratings", "note"]}

    if name == "recommend_phones":
        if not p.get("budget_max"):
            return {"error": "budget_max unknown — ask the user for a budget first"}
        r = T.recommend(p["budget_max"], p.get("budget_min"), p.get("priorities"), s.current, p.get("pain_points"),
                        p.get("installment_only", False), p.get("allow_used", False), p.get("os_pref"),
                        None, None, p.get("area"))
        s.last_picks = r["picks"]
        s.stage = 1
        s.products = []
        r["price_range"] = T.phone_price_range()
        r["filters"] = {"budget_min": p.get("budget_min"), "budget_max": p.get("budget_max")}
        emit({"type": "recommendations", "data": r, "current": s.current})
        return {"picks": [{"role": c["role"], "model_key": c["model_key"], "name": c["name"], "price_from": c["price_from"],
                           "n_shops": c["n_shops"], "n_shops_listing_installment": c["n_inst_shops"], "ratings": c["ratings"], "vs_current": c["vs_current"]} for c in r["picks"]],
                "relaxed": r["relaxed"], "guardrail_removed": r["guardrail_removed"], "note": r["note"],
                "market_floor_toman": r["market_floor"]}

    if name == "compare_models":
        r = T.compare_models(args.get("model_keys") or [c["model_key"] for c in s.last_picks])
        emit({"type": "compare", "data": r, "current": s.current})
        return {"models": [{k: m[k] for k in ["model_key", "name", "min_price", "camera", "battery", "speed"]} for m in r]}

    if name == "find_shops":
        mk = args["model_key"]
        sto = args.get("storage_gb")
        pick = next((c for c in s.last_picks if c["model_key"] == mk), None)
        if sto is None and pick:
            sto = pick["variant"]["storage_gb"]
        r = T.find_shops(mk, sto, p.get("installment_only", False), p.get("allow_used", False), p.get("area"),
                         p.get("visit_at"), p.get("budget_max"))
        fell_back = None
        outside_area = None
        if r["n"] == 0 and p.get("area"):
            # Never silently relax a requested area: show only a count and ask before expanding.
            other = T.find_shops(mk, sto, p.get("installment_only", False), p.get("allow_used", False), None, p.get("visit_at"), p.get("budget_max"))
            outside_area = {"n": other["n"], "n_actionable": other["n_actionable"]}
            fell_back = "area_empty_ask"
        name_ = pick["name"] if pick else (T.compare_models([mk])[0]["name"] if T.compare_models([mk]) else mk)
        s.model = {"model_key": mk, "name": name_, "storage_gb": sto}
        s.shops = r["shops"]
        s.stage = 2
        emit({"type": "shops", "data": r, "model": s.model, "fell_back": fell_back, "outside_area": outside_area,
              "visit_label": _visit_label(p)})
        top = r["shops"][:5]
        return {"n_shops": r["n"], "n_actionable": r["n_actionable"], "price_min": r["price_min"], "price_max": r["price_max"],
                "fell_back": fell_back, "outside_area": outside_area,
                "top": [{"shop_id": x["shop_id"], "name": x["shop_name"], "passage": x["passage"], "price": x["price"],
                         "fresh": x["freshness"]["tier"], "warranty": x["warranty"]["kind"], "open": x["open"]["status"],
                         "installment": x["installment"], "actionable": x["actionable"], "blocked_reason": x["blocked_reason"]} for x in top]}

    if name == "search_categories":
        r = C.search_categories(args.get("query", ""), 6)
        return {"categories": [{k: c[k] for k in ["category", "n_priced_products", "median_price", "expert"]} for c in r]}

    if name == "search_products":
        cat = args.get("category")
        if cat and C.EXPERT_KINDS.get(cat) is None:
            cat = _prefer_expert(args.get("query", "") + " " + cat, cat)
        if not cat and args.get("query"):
            cat = _prefer_expert(args["query"], None)
        if not cat and args.get("query"):
            # broad query without a category: pin the category only when every query word is in its name
            top = C.search_categories(args["query"], 1)
            if top and all(w in top[0]["category"].replace(" ", "") or w in top[0]["category"] for w in C.tokenize(args["query"])):
                cat = top[0]["category"]
        budget = args.get("budget_max") or s.product_ctx.get("budget_max")
        bmin = args.get("budget_min") if "budget_min" in args else s.product_ctx.get("budget_min")
        if cat and s.product_ctx.get("category") and cat != s.product_ctx.get("category"):
            bmin = args.get("budget_min")
            if not args.get("budget_max"):
                budget = None  # never carry one category's budget into another
        pri = args.get("priorities") or (s.product_ctx.get("priorities") if cat == s.product_ctx.get("category") else None)
        last_user = next((m["content"] for m in reversed(s.messages) if m.get("role") == "user" and m.get("content")), "")
        wl_text = f"{args.get('query', '')} {last_user if cat == C.EXPERT_HEADPHONES else ''}"
        wireless = cat == C.EXPERT_HEADPHONES and bool(re.search(r"بی ?‌?سیم|بلوتوث|wireless|ایرپاد|ایربادز", wl_text, re.I)) \
            and not re.search(r"با ?‌?سیم می|سیمی می", wl_text)
        r = C.search_products(args.get("query", ""), cat, budget, p.get("installment_only", False), p.get("area"), pri, 3,
                              wireless_only=wireless, budget_min=bmin)
        if wireless:
            r["note"] = (r.get("note") or "") + " فقط مدل‌های بی‌سیم/بلوتوث نشان داده شد."
        cur = None
        cq = args.get("current_item_query") or (s.product_ctx.get("current_query") if cat == s.product_ctx.get("category") else None)
        if cq and r["category"]:
            cur = C.lookup_current_item(cq, r["category"])
        C.annotate_vs_current(r, cur)
        s.products = r["products"]
        s.product_ctx = {"category": r["category"] or cat, "budget_max": budget, "budget_min": bmin, "priorities": pri,
                         "current_query": cq, "query": args.get("query", "")}
        s.stage = 1
        emit({"type": "products", "data": r, "current": cur})
        return {"mode": r["mode"], "category": r["category"], "n_candidates": r["n_candidates"], "note": r["note"],
                "priorities_applied": r["priorities_applied"], "priorities_ignored": r["priorities_ignored"],
                "current_item": cur and {"name": cur["name"], "specs": cur["specs"]},
                "products": [{"product_id": x["product_id"], "name": x["name"], "price": x["price"], "n_shops": x["n_shops"],
                              "reasons": x["reasons"], "vs_current": x.get("vs_current")} for x in r["products"]]}

    if name == "find_product_shops":
        pid = args["product_id"]
        prod = next((x for x in s.products if x["product_id"] == pid), None) or C.product_details(pid)
        if not prod:
            return {"error": "unknown product_id"}
        r = C.find_product_shops(pid, p.get("installment_only", False), p.get("area"), s.product_ctx.get("budget_max"), p.get("visit_at"))
        outside_area = None
        if r["n"] == 0 and p.get("area"):
            other = C.find_product_shops(pid, p.get("installment_only", False), None, s.product_ctx.get("budget_max"), p.get("visit_at"))
            outside_area = {"n": other["n"], "n_actionable": other["n_actionable"]}
        s.model = {"model_key": pid, "name": prod["name"], "storage_gb": None, "kind": "product"}
        s.shops = r["shops"]
        s.stage = 2
        emit({"type": "shops", "data": r, "model": s.model, "fell_back": "area_empty_ask" if outside_area else None,
              "outside_area": outside_area, "visit_label": _visit_label(p)})
        return {"n_shops": r["n"], "n_actionable": r["n_actionable"], "price_min": r["price_min"], "outside_area": outside_area,
                "top": [{"shop_id": x["shop_id"], "name": x["shop_name"], "passage": x["passage"], "price": x["price"],
                         "open": x["open"]["status"], "actionable": x["actionable"], "blocked_reason": x["blocked_reason"]}
                        for x in r["shops"][:5]]}

    if name == "contact_shops":
        if not s.shops or not s.model:
            return {"error": "no model/shops selected yet — call find_shops first"}
        chosen = args.get("chosen_shop_id")
        ids = ([chosen] if chosen else []) + [i for i in (args.get("shop_ids") or []) if i != chosen]
        pool, seen = [], set()
        for x in [x for x in s.shops if x["shop_id"] in ids] + [x for x in s.shops if x["shop_id"] not in ids]:
            if x["shop_id"] not in seen and x.get("actionable", True):
                seen.add(x["shop_id"])
                pool.append(x)
        if not pool:
            return {"error": "no actionable shops: all are closed at the chosen time or above budget; ask user to change time/budget"}
        want_inst = bool(p.get("installment_only"))
        results, confirmed, tried = [], 0, 0
        emit({"type": "contact_start", "model": s.model, "simulated": True, "note": shop_agent.SIM_NOTE})
        # contact in waves of 3 until 2 confirmed (automatic fallback), max 9 shops
        i = 0
        need = 1 if chosen else 2
        while confirmed < need and i < len(pool) and tried < 9:
            step = 1 if (chosen and i == 0) else 3  # user's chosen shop alone first; fallback waves only if it fails
            wave = pool[i:i + step]
            i += step
            tried += len(wave)
            res = await shop_agent.contact(wave, s.model["name"], s.model["model_key"], want_inst, _visit_label(p))
            for r_ in res:
                results.append(r_)
                emit({"type": "contact_result", "data": r_})
            confirmed = len({r_["shop_id"] for r_ in results if r_["status"] == "confirmed"})
        s.contacts = results
        s.chosen_shop_id = chosen
        s.stage = 4
        plan = build_plan(s)
        emit({"type": "plan", "data": plan})
        return {"contacted": len(results), "confirmed": confirmed,
                "results": [{"name": r_["shop_name"], "status": r_["status"], "price": r_["confirmed_price"],
                             "installment_confirmed": r_["installment"]} for r_ in results],
                "best_confirmed_price": min([r_["confirmed_price"] for r_ in results if r_["status"] == "confirmed" and r_["confirmed_price"]], default=None),
                "plan_steps": len(plan["stops"])}

    return {"error": f"unknown tool {name}"}


def build_plan(s: Session) -> dict:
    ok = [c for c in s.contacts if c["status"] == "confirmed"]
    backup = [c for c in s.contacts if c["status"] == "no_installment"]
    by_id = {x["shop_id"]: x for x in s.shops}
    chosen = getattr(s, "chosen_shop_id", None)
    stops = sorted(ok, key=lambda c: (c["shop_id"] != chosen, c["confirmed_price"] or 1e15))
    route = T.walking_route([by_id[c["shop_id"]] for c in stops])
    cmap = {c["shop_id"]: c for c in stops}
    out = []
    for r in route:
        c = cmap[r["shop_id"]]
        out.append({**r, "confirmed_price": c["confirmed_price"], "price_changed": c["price_changed"],
                    "installment": c["installment"], "address": by_id[r["shop_id"]]["address"],
                    "chosen": r["shop_id"] == chosen})
    if chosen:
        out.sort(key=lambda x: not x["chosen"])
    chosen_failed = None
    if chosen and not any(x["chosen"] for x in out):
        cf = next((c for c in s.contacts if c["shop_id"] == chosen), None)
        chosen_failed = cf and {"shop_name": cf["shop_name"], "status_label": cf["status_label"]}
    return {"model": s.model, "visit_label": _visit_label(s.profile), "stops": out, "chosen_failed": chosen_failed,
            "backup": [{"shop_name": b["shop_name"], "status_label": b["status_label"]} for b in backup],
            "checklist": (["سلامت جعبه و پلمپ را چک کنید", "کارت گارانتی و نام شرکت گارانتی را ببینید",
                           "کالا را جلوی فروشنده روشن و تست کنید", "فاکتور با نام مدل و سریال بگیرید"]
                          if (s.model or {}).get("kind") == "product" else
                          ["سلامت جعبه و پلمپ را چک کنید", "کد رجیستری (همتا) را قبل از پرداخت بررسی کنید",
                           "کارت گارانتی و نام شرکت گارانتی را ببینید", "فاکتور با IMEI بگیرید"]),
            "simulated": True}


# ---------------------------------------------------------------- main loop
async def handle(s: Session, user_text: str | None, action: dict | None, emit) -> None:
    s.updated = time.time()
    if not s.messages:
        s.messages.append({"role": "system", "content": SYSTEM.format(today=_today())})

    if action:
        # UI button → deterministic tool call, recorded in history as if the agent called it
        name, args, text = _action_to_tool(s, action)
        s.messages.append({"role": "user", "content": text})
        emit({"type": "user_echo", "text": text})
        tcid = "call_" + uuid.uuid4().hex[:10]
        s.messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]})
        emit({"type": "status", "text": _status_text(name)})
        res = await run_tool(s, name, args, emit)
        s.messages.append({"role": "tool", "tool_call_id": tcid, "content": json.dumps(res, ensure_ascii=False, default=str)})
    else:
        s.messages.append({"role": "user", "content": user_text or ""})

    for _ in range(6):
        emit({"type": "status", "text": "در حال فکر کردن…"})
        try:
            msg = await llm.chat(s.messages, TOOLS)
        except Exception as e:  # noqa: BLE001
            emit({"type": "message", "text": "ارتباط با مدل زبانی برقرار نشد؛ لطفاً دوباره تلاش کنید.", "error": str(e)[:200]})
            break
        tcs = msg.get("tool_calls") or []
        s.messages.append({"role": "assistant", "content": msg.get("content"), **({"tool_calls": tcs} if tcs else {})})
        if not tcs:
            emit({"type": "message", "text": (msg.get("content") or "").strip()})
            break
        if msg.get("content"):
            emit({"type": "message", "text": msg["content"].strip()})
        for tc in tcs:
            name = tc["function"]["name"]
            emit({"type": "status", "text": _status_text(name)})
            try:
                res = await run_tool(s, name, llm.parse_args(tc), emit)
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)[:300]}
            s.messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, ensure_ascii=False, default=str)})
    emit({"type": "chips", "chips": suggest_chips(s)})
    emit({"type": "stage", "stage": s.stage, "profile": s.profile, "visit_label": _visit_label(s.profile)})


def _status_text(name: str) -> str:
    return {"update_profile": "ذخیرهٔ نیازهای شما…", "lookup_current_phone": "بررسی گوشی فعلی شما…",
            "recommend_phones": "مقایسهٔ گوشی‌های موجود در بازار…", "compare_models": "مقایسهٔ مدل‌ها…",
            "find_shops": "پیدا کردن مغازه‌هایی که این گوشی را دارند…", "search_categories": "پیدا کردن دستهٔ کالا…",
            "search_products": "مقایسهٔ کالاهای موجود در بازار…", "find_product_shops": "پیدا کردن مغازه‌هایی که این کالا را دارند…",
            "contact_shops": "تماس (شبیه‌سازی‌شده) با مغازه‌ها…"}.get(name, "…")


_EXPERT_HINTS = {
    "هدفون، هدست و هندزفری": r"هدفون|هدست|هندزفری|ایرپاد|ایربادز|earbud|headphone|airpods",
    "اسپیکر و سیستم صوتی": r"اسپیکر|بلندگو|speaker",
    "دوربین مدار بسته": r"مدار ?‌?بسته|دوربین (?:امنیتی|نظارتی|حیاط|wifi|وای ?فای)|cctv",
    "پاوربانک و شارژر همراه": r"پاور ?‌?بانک|شارژر همراه|power ?bank",
}
_ACCESSORY_INTENT = r"کیف|کاور|قاب|کابل|ایرتیپ|سری|بند|استند|پایه|لوازم جانبی|قطعات"


def _prefer_expert(text: str, fallback):
    """Route product words to the expert category unless the user explicitly wants an accessory."""
    if re.search(_ACCESSORY_INTENT, text or ""):
        return fallback
    for cat, rx in _EXPERT_HINTS.items():
        if re.search(rx, text or "", re.I):
            return cat
    return fallback


def _action_to_tool(s: Session, a: dict) -> tuple[str, dict, str]:
    t = a.get("type")
    if t == "select_product":
        return "find_product_shops", {"product_id": a["product_id"]}, f"{a.get('name') or 'این کالا'} را انتخاب کردم؛ کدام مغازه‌ها دارند؟"
    if t == "select_model":
        nm = a.get("name") or a["model_key"]
        return "find_shops", {"model_key": a["model_key"], "storage_gb": a.get("storage_gb")}, f"{nm} را انتخاب کردم؛ کدام مغازه‌ها دارند؟"
    if t == "set_price":
        lo, hi = int(a["min"]), int(a["max"])
        txt = f"بازهٔ قیمت را {lo // 100000 / 10:g} تا {hi // 100000 / 10:g} میلیون تومان گذاشتم؛ پیشنهادها را به‌روز کن."
        if a.get("kind") == "phone":
            s.profile["budget_min"], s.profile["budget_max"] = lo, hi
            return "recommend_phones", {}, txt
        ctx = s.product_ctx
        return "search_products", {"query": ctx.get("query", ""), "category": ctx.get("category"), "budget_min": lo,
                                   "budget_max": hi, "priorities": ctx.get("priorities"),
                                   "current_item_query": ctx.get("current_query")}, txt
    if t == "choose_shop":
        nm = a.get("name") or "این مغازه"
        return "contact_shops", {"chosen_shop_id": a["shop_id"], "shop_ids": []}, \
            f"از {nm} می‌خرم؛ قبل از رفتن موجودی را چک کن و مسیرش را نشان بده."
    if t == "contact":
        ids = a.get("shop_ids") or []
        return "contact_shops", {"shop_ids": ids}, "با مغازه‌ها تماس بگیر و موجودی و قیمت را چک کن."
    if t == "compare":
        return "compare_models", {"model_keys": a.get("model_keys") or [c["model_key"] for c in s.last_picks]}, "این‌ها را کنار هم مقایسه کن."
    if t == "set_area":
        v = a.get("value") or "همه"
        return "update_profile", {"area": v}, ("همهٔ مناطق" if v == "همه" else f"فقط مغازه‌های {v}") + " — نتیجه‌ها را با این منطقه به‌روز کن."
    if t == "toggle_installment":
        v = bool(a.get("value"))
        return "update_profile", {"installment_only": v}, "فقط مغازه‌های اقساطی" if v else "اقساط مهم نیست"
    raise ValueError(f"unknown action {t}")


def suggest_chips(s: Session) -> list[str]:
    p = s.profile
    if s.stage == 1 and s.products:
        return ["چرا اولی؟", "ارزون‌تر هم هست؟", "قسطی می‌خوام", "فقط مغازه‌های جمهوری"]
    if s.stage == 0:
        if not p.get("budget_max"):
            return ["تا ۷۰ میلیون، دوربین خوب", "هدفون بی‌سیم با حذف نویز تا ۵ میلیون", "پاوربانک سبک تا ۲ میلیون", "دوربین مدار بسته برای حیاط"]
        return ["دوربین برام مهمه", "شارژ زیاد بمونه", "گوشی فعلیم سامسونگ A10 است"]
    if s.stage == 1:
        return ["چرا اولی؟", "مقایسه‌شون کن", "قسطی می‌خوام", "ارزون‌تر هم هست؟"]
    if s.stage == 2:
        return ["با مغازه‌ها تماس بگیر", "فقط اقساطی‌ها", "فردا ساعت ۵ می‌رم", "یه مدل دیگه"]
    return ["مسیرم رو خلاصه کن", "اگه رفتم و نبود چی؟", "یه مدل دیگه ببینم"]
