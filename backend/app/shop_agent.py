"""Simulated shop agent (step 4). Clearly labeled as a simulation in every output.

Outcomes (answered / in stock / installment) are decided by deterministic code seeded by shop+model,
so the demo is reproducible; the LLM only writes the seller's Persian reply, grounded in the offer row.
"""
from __future__ import annotations

import asyncio
import hashlib

from app import llm

SIM_NOTE = "شبیه‌سازی: این پاسخ را یک عامل هوش مصنوعی به‌جای فروشنده داده است، نه خود فروشگاه."


def _roll(*parts: str) -> float:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def decide(shop: dict, model_key: str, want_installment: bool) -> dict:
    sid = shop["shop_id"]
    answered = _roll(sid, model_key, "answer") > 0.22
    fresh = shop["freshness"]["tier"]
    p_stock = {"fresh": 0.85, "recent": 0.65, "old": 0.35, "unknown": 0.5}[fresh]
    in_stock = answered and _roll(sid, model_key, "stock") < p_stock
    price = shop.get("price")
    drift = 0
    if in_stock and price:
        r = _roll(sid, model_key, "price")
        drift = 0 if r < 0.55 else (1 if r < 0.85 else -1)
    new_price = None
    if price:
        step = max(500_000, round(price * 0.02 / 100_000) * 100_000)
        new_price = price + drift * step
    inst = None
    if want_installment and answered:
        # Only shops whose Torob listing includes an installment provider can be simulated as offering installments.
        inst = bool(shop.get("installment")) and _roll(sid, model_key, "inst") < 0.9
    return {"answered": answered, "in_stock": in_stock, "price": new_price, "price_changed": drift != 0,
            "installment": inst}


async def _reply(shop: dict, phone_name: str, d: dict, question: str) -> str:
    if not d["answered"]:
        return ""
    sto = (shop.get("variant") or {}).get("storage_gb")
    facts = [f"کالا: {phone_name}" + (f" ({sto:g} گیگ)" if sto else ""),
             f"موجود: {'بله' if d['in_stock'] else 'خیر، تمام شده'}"]
    if d["in_stock"] and d["price"]:
        facts.append(f"قیمت امروز: {d['price']:,} تومان" + (" (با قیمت ثبت‌شده فرق دارد)" if d["price_changed"] else ""))
    if d["installment"] is not None:
        facts.append(f"اقساط: {'دارد؛ روش ثبت‌شده در ترب: ' + '، '.join(shop.get('payment_providers') or ['نامشخص']) if d['installment'] else 'ندارد، فقط نقد'}")
    w = shop.get("warranty") or {}
    if w.get("text"):
        facts.append(f"گارانتی: {w['text']}")
    msgs = [
        {"role": "system", "content": "تو فروشندهٔ یک مغازه در بازار/پاساژهای تهران هستی. فقط بر اساس «واقعیت‌ها» جواب بده، "
                                      "هیچ عدد یا ادعای دیگری نساز. محاوره‌ای، مودب و کوتاه (حداکثر دو جمله)."},
        {"role": "user", "content": f"واقعیت‌ها:\n- " + "\n- ".join(facts) + f"\n\nپیام مشتری: {question}"},
    ]
    try:
        m = await asyncio.wait_for(llm.chat(msgs, model=llm.SHOP_MODEL, max_tokens=200), timeout=25)
        return (m.get("content") or "").strip()
    except Exception:
        # deterministic fallback text if the LLM is slow/unavailable
        if not d["in_stock"]:
            return "سلام، متأسفانه این مدل فعلاً تموم شده."
        return f"سلام، بله موجوده. قیمت امروز {d['price']:,} تومان." if d["price"] else "سلام، بله موجوده. برای قیمت تشریف بیارید."


async def contact(shops: list[dict], phone_name: str, model_key: str, want_installment: bool, visit_label: str | None) -> list[dict]:
    q = f"سلام، {phone_name} موجود دارید؟ قیمتش چنده؟"
    if want_installment:
        q += " قسطی هم می‌فروشید؟"
    if visit_label:
        q += f" {visit_label} میام مغازه."
    decisions = [decide(s, model_key, want_installment) for s in shops]
    replies = await asyncio.gather(*[_reply(s, phone_name, d, q) for s, d in zip(shops, decisions)])
    out = []
    for s, d, rep in zip(shops, decisions, replies):
        if not d["answered"]:
            status, label = "no_answer", "پاسخ نداد"
        elif not d["in_stock"]:
            status, label = "out_of_stock", "ناموجود"
        elif want_installment and not d["installment"]:
            status, label = "no_installment", "موجود، ولی اقساط ندارد"
        else:
            status, label = "confirmed", "موجودی تأیید شد"
        out.append({"shop_id": s["shop_id"], "shop_name": s["shop_name"], "question": q, "reply": rep,
                    "status": status, "status_label": label, "confirmed_price": d["price"] if d["in_stock"] else None,
                    "listed_price": s.get("price"), "price_changed": d["price_changed"] and d["in_stock"],
                    "installment": d["installment"], "simulated": True, "sim_note": SIM_NOTE,
                    "passage": s.get("passage"), "floor": s.get("floor"), "unit": s.get("unit")})
    return out
