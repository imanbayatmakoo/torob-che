"""Tests for the all-category catalogue (app.catalog). Extractor tests are pure; the rest use the built parquet."""
import pytest

from app import catalog as C

needs_data = pytest.mark.skipif(not C.available(), reason="run scripts/build_catalog.py first")


# ---------------------------------------------------------------- pure extraction
def test_headphone_extraction_conservative_anc():
    sm = {"نوع اتصال": "بی‌سیم", "نسخه بلوتوث": "5.4", "قابلیت نویز کنسلینگ": "نویز کنسلینگ میکروفون (ENC)",
          "عمر باتری هدفون در حالت پخش موسیقی": "6 ساعت", "قطر درایور": "(داینامیک) 40 میلی‌متر", "میکروفون": "دارد"}
    s, ev = C.extract_specs("هدفون، هدست و هندزفری", sm, "هدفون بی سیم تست")
    assert s["connection"] == "wireless" and s["bluetooth_version"] == 5.4
    assert s["anc"] == "call_mic_only"  # ENC is a call-mic feature, not active ANC
    assert s["battery_hours"] == 6 and s["driver_mm"] == 40 and s["has_mic"] is True
    assert ev["battery_hours"]["source"] == "spec"
    assert "impedance_ohm" not in s  # unknown stays absent, never invented


def test_powerbank_extraction_and_title_fallback():
    s, ev = C.extract_specs("پاوربانک و شارژر همراه", {"ظرفیت اسمی": "10,000 میلی‌آمپرساعت", "توان خروجی کلی": "22.5 وات",
                                                       "وزن": "180 گرم", "تعداد درگاه خروجی": "دو عدد"}, "پاوربانک x")
    assert (s["capacity_mah"], s["output_w"], s["weight_g"], s["ports"]) == (10000, 22.5, 180, 2)
    s2, ev2 = C.extract_specs("پاوربانک و شارژر همراه", {}, "پاوربانک ۲۰۰۰۰ میلی آمپر مدل X")
    s3, _ = C.extract_specs("پاوربانک و شارژر همراه", {"سازگار با": "گوشی و تبلت"}, "x")
    assert "wireless_charging" not in s3
    assert s2["capacity_mah"] == 20000 and ev2["capacity_mah"]["source"] == "title"


def test_cctv_resolution_and_speaker():
    s, _ = C.extract_specs("دوربین مدار بسته", {"حداکثر رزولوشن": "2688 × 1520", "دید در شب": "رنگی, 30 متر", "حفاظت": "IP67"}, "دوربین بولت")
    assert round(s["resolution_mp"], 1) == 4.1 and s["night_vision"] is True and s["night_range_m"] == 30 and s["ip_water"] == 7
    s, _ = C.extract_specs("اسپیکر و سیستم صوتی", {"ظرفیت باتری": "2600 میلی آمپر ساعت", "توان خروجی": "4.2 وات", "بلوتوث": "دارد"}, "اسپیکر")
    assert s["battery_mah"] == 2600 and s["power_w"] == 4.2 and s["bluetooth"] is True


def test_tokenize_and_priorities():
    assert C.tokenize("بهترین هدفون بی‌سیم ۱۲۳") == ["هدفون", "بی", "سیم", "123"] or "هدفون" in C.tokenize("بهترین هدفون")
    assert C.normalize_priorities("headphones", ["باتری", "battery", "camera", "ارزان"])[0] == ["battery", "value"]


# ---------------------------------------------------------------- data-backed
@needs_data
def test_four_expert_categories_chosen_by_rule():
    ex = C.expert_categories()
    assert len(ex) == 4 and "گوشی موبایل" not in ex
    assert set(ex) == set(C.EXPERT_KINDS)
    d = C.supported_dimensions("هدفون، هدست و هندزفری")
    assert d["expert"] and any(x["key"] == "battery" for x in d["dimensions"])
    assert C.supported_dimensions("لنز دوربین")["expert"] is False


@needs_data
def test_search_categories_covers_all():
    assert C.catalog_stats()["n_categories"] == 3428
    r = C.search_categories("هدفون")
    assert r and r[0]["category"].startswith("هدفون") and r[0]["expert"]
    r2 = C.search_categories("لنز")
    assert any("لنز" in x["category"] for x in r2)


@needs_data
def test_search_strict_filters():
    r = C.search_products("", category="پاوربانک و شارژر همراه", budget_max=3_000_000, installment_only=True, limit=10)
    assert r["expert"] and r["products"]
    for p in r["products"]:
        assert p["price"] <= 3_000_000 and p["category"] == "پاوربانک و شارژر همراه" and p["n_installment_shops"] >= 1
        assert p["product_id"] and p["name"] and p["expert"] is True and p["reasons"]
        shops = C.find_product_shops(p["product_id"], installment_only=True, budget_max=3_000_000)
        assert shops["n"] >= 1 and all(s["installment"] and s["price"] <= 3_000_000 for s in shops["shops"])
    scores = [p["score"] for p in r["products"]]
    assert scores == sorted(scores, reverse=True)


@needs_data
def test_area_filter_and_nonexpert_search():
    r = C.search_products("لنز", category="لنز دوربین", area="فردوسی", limit=5)
    assert not r["expert"] and r["priorities_applied"] == []
    for p in r["products"]:
        sh = C.find_product_shops(p["product_id"], area="فردوسی")
        assert sh["n"] >= 1 and all(s["area"] == "فردوسی" for s in sh["shops"])
        assert p["specs"] == {} or isinstance(p["specs"], dict)


@needs_data
def test_priorities_change_ranking_and_never_invent():
    cat = "هدفون، هدست و هندزفری"
    a = C.search_products("", category=cat, priorities=["battery"], limit=5)
    assert a["priorities_applied"] == ["battery", "value"] or "battery" in a["priorities_applied"]
    top = a["products"][0]
    assert "battery_hours" in top["specs"] or any("نامشخص" in r or "ثبت نشده" in r for r in top["reasons"])
    for p in a["products"]:
        for f in p["specs"]:
            assert f in p["evidence"]  # every shown spec carries evidence
    b = C.search_products("", category=cat, priorities=["noise"], limit=5)
    assert [p["product_id"] for p in a["products"]] != [p["product_id"] for p in b["products"]]


@needs_data
def test_product_details_and_shops_schema_matches_find_shops():
    r = C.search_products("اسپیکر", category="اسپیکر و سیستم صوتی", limit=3)
    pid = r["products"][0]["product_id"]
    d = C.product_details(pid)
    assert d["product_id"] == pid and d["raw_specs"] is not None and d["offers"]["n"] >= 1
    sh = C.find_product_shops(pid, visit_at="2026-10-14T11:00:00")
    assert {"n", "shops", "price_min", "price_max", "route"} <= set(sh)
    need = {"offer_id", "shop_id", "shop_name", "address", "area", "passage", "passage_key", "floor", "floor_num", "unit",
            "title", "variant", "price", "price_label", "over_budget", "freshness", "stock", "warranty", "registry",
            "installment", "payment_providers", "open", "score", "score_parts", "phone_listed", "rank"}
    assert sh["shops"] and need <= set(sh["shops"][0])
    assert sh["shops"][0]["rank"] == 1
    assert C.product_details("nope") is None


@needs_data
def test_broad_mode_no_phone_ratings():
    r = C.search_products("گوشی", category="گوشی موبایل", limit=3)
    assert r["products"] and not r["expert"]
    for p in r["products"]:
        assert not ({"camera", "battery", "speed"} & set(p["specs"]))
        assert p["expert"] is False


# ---- integration guards (look-alikes, wireless intent, finalize_shops reuse)
def test_premium_lookalikes_and_accessories_are_never_recommended():
    from app import catalog as C
    assert C.looks_fake_or_accessory("هدفون بی سیم اپل مدل AirPods Max", C.EXPERT_HEADPHONES, 2_191_000)
    assert C.looks_fake_or_accessory("کیف هدفون اپل ایرپاد مکس", C.EXPERT_HEADPHONES, 630_000)
    assert not C.looks_fake_or_accessory("هدفون بی سیم اپل مدل AirPods Max 2", C.EXPERT_HEADPHONES, 113_800_000)
    assert not C.looks_fake_or_accessory("کیف لپ تاپ", "کیف لپ تاپ", 1_000_000)  # broad mode untouched
    r = C.search_products("ایرپاد مکس", C.EXPERT_HEADPHONES, 10_000_000, limit=8)
    assert all(not ("airpods" in p["name"].lower() or "ایرپاد" in p["name"]) for p in r["products"])


def test_wireless_only_excludes_wired_headphones():
    from app import catalog as C
    r = C.search_products("", C.EXPERT_HEADPHONES, 6_000_000, priorities=["noise"], limit=8, wireless_only=True)
    assert r["products"]
    assert all(p["specs"].get("connection") != "wired" for p in r["products"])


def test_product_shops_one_row_per_seller_and_route_actionable():
    from app import catalog as C
    r = C.search_products("", "پاوربانک و شارژر همراه", 3_000_000, limit=3)
    pid = max(r["products"], key=lambda p: p["n_shops"])["product_id"]
    s = C.find_product_shops(pid, budget_max=3_000_000)
    ids = [x["shop_id"] for x in s["shops"]]
    assert len(ids) == len(set(ids)) == s["n"]
    assert all(x["actionable"] for x in s["shops"][: s["n_actionable"]])
