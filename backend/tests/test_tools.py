from app import tools as T


def test_current_phone_lookup_tiers():
    a10 = T.lookup_current_phone("گوشی فعلیم سامسونگ A10 است")
    assert a10["found"] and a10["source"] == "reference" and a10["ratings"]["battery"] is not None
    a56 = T.lookup_current_phone("گلکسی A56")
    assert a56["source"] == "dataset" and a56["model_key"] == "samsung:a56"
    assert T.lookup_current_phone("ردمی نوت ۱۳")["name"].endswith("Redmi Note 13")
    assert not T.lookup_current_phone("یه گوشی چینی قدیمی")["found"]


def test_recommend_roles_and_budget():
    r = T.recommend(70_000_000, priorities=["camera", "battery"])
    roles = [p["role"] for p in r["picks"]]
    assert roles[0] == "best"
    best = r["picks"][0]
    assert best["price_from"] <= 70_000_000
    assert best["n_shops"] >= 3  # prefer models you can actually find in person
    for p in r["picks"]:
        if p["role"] == "cheaper":
            assert p["price_from"] < best["price_from"]
        if p["role"] == "step_up":
            assert p["price_from"] > 70_000_000


def test_guardrail_never_worse_on_pain_point():
    cur = T.lookup_current_phone("سامسونگ A10")
    r = T.recommend(70_000_000, priorities=["camera"], current=cur, pain_points=["battery"])
    for p in r["picks"]:
        assert p["ratings"]["battery"] > cur["ratings"]["battery"]
        assert p["vs_current"]["battery"] > 0


def test_no_lookalikes_and_market_floor():
    r = T.recommend(20_000_000, priorities=["speed"])
    for p in r["picks"]:
        assert "یونیوا" not in p["title"]
    low = T.recommend(5_000_000, priorities=["camera"], os_pref="ios")
    assert not low["picks"] and low["market_floor"] and "شروع" in low["note"]


def test_find_shops_honesty_fields():
    s = T.find_shops("samsung:a17", visit_at="2026-10-24T17:00", budget_max=60_000_000)
    assert s["n"] > 5
    x = s["shops"][0]
    assert x["stock"]["status"] == "unconfirmed"
    assert x["freshness"]["tier"] in {"fresh", "recent", "old", "unknown"}
    assert set(x["score_parts"]) >= {"price", "freshness", "warranty", "registry", "open", "budget"}
    assert [y["score"] for y in s["shops"]] == sorted([y["score"] for y in s["shops"]], reverse=True)
    assert s["route"] and s["route"][0]["step"] == 1


def test_simulated_shop_agent_is_deterministic():
    from app import shop_agent
    s = T.find_shops("samsung:a17")["shops"][0]
    assert shop_agent.decide(s, "samsung:a17", True) == shop_agent.decide(s, "samsung:a17", True)
