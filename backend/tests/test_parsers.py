from app.data import parsers as P


def test_norm_digits_and_letters():
    assert P.norm("۲۵۶ گیگابايت") == "256 گیگابایت"
    assert P.norm("  a\u200cb  ") == "a b"


def test_storage():
    assert P.parse_storage_gb("256 گیگابایت") == 256
    assert P.parse_storage_gb("۱ ترابایت") == 1024
    assert P.parse_storage_gb("128 مگابایت") == 0.125
    assert P.parse_storage_gb(None) is None


def test_battery():
    assert P.parse_mah("۵۰۰۰ میلی‌آمپرساعت") == 5000
    assert P.parse_mah("5,000 mAh") == 5000
    assert P.parse_mah("دارد") is None


def test_camera_and_screen():
    assert P.parse_mp("50MP Wide Camera, ,") == 50
    assert P.parse_mp("48 MP, f/1.5 + 12 MP") == 48
    assert P.parse_mp("ندارد") is None
    assert P.parse_inch("6.67 اینچ") == 6.67
    assert P.parse_inch("2.4 اینچ") == 2.4


def test_chip_tier():
    assert P.chip_tier("Apple A19 Pro (3 nm)") == 10
    assert P.chip_tier("Qualcomm SM7635 Snapdragon 7s Gen 3 (4 nm)") == 6.9
    assert P.chip_tier("Exynos 1380, ,") == 5.4
    assert P.chip_tier("Mediatek Helio G99 Ultra") == 4.4
    assert P.chip_tier("MTK G99") == 4.4
    assert P.chip_tier("MT6261D") == 0.2
    assert P.chip_tier("اسنپدراگون سری 8 نسل 3 مدل کوالکام SM8650-AC (4 نانومتری)") == 9.2
    assert P.chip_tier("Qualcomm Snapdragon 8 Gen 5") == 10
    assert P.chip_tier("دارد") is None
    # ordering matters: higher tiers must not be shadowed
    assert P.chip_tier("Snapdragon 8 Elite Gen 5") > P.chip_tier("Snapdragon 8 Elite")
    assert P.chip_tier("Exynos 2400") > P.chip_tier("Exynos 1480")


def test_title_storage_ram():
    assert P.title_storage_ram("گوشی شیائومی Redmi Note 14 Pro 4G | حافظه 256 رم 8 گیگابایت") == (256, 8)
    assert P.title_storage_ram("گوشی هانوفر 6700 | حافظه 32 مگابایت")[0] == round(32 / 1024, 4)


def test_condition_registry():
    assert P.condition_from_text("گوشی سامسونگ (استوک) A26 5G") == "used"
    assert P.condition_from_text("گوشی طرح نوکیا Bm10") == "replica"
    assert P.registry_from_text("iPhone 17 CH بدون ریجستر") == "not_registered"
    assert P.registry_from_text("ریجستر شرکتی") == "registered"
    assert P.registry_from_text("دارای کد فعال سازی همتا") == "registered"
    assert P.registry_from_text("گوشی سامسونگ A56") == "unknown"


def test_warranty():
    assert P.warranty_kind("شرکتی", 18, None) == "official"
    assert P.warranty_kind("بدون گارانتی", None, None) == "none"
    assert P.warranty_kind("تست و تحویل در حضور مشتری", None, None) == "store_test"
    assert P.warranty_kind(None, None, "ضمانت اصالت کالا") == "other"
    assert P.warranty_kind(None, None, None) == "unknown"
    assert P.warranty_months(None, None, "گارانتی ۱۸ ماهه شرکتی") == 18


def test_address():
    a = P.parse_address("خیابان جمهوری، نبش شیخ هادی، پاساژ علالدین 2، طبقه 6، واحد 622")
    assert a == {"passage": "پاساژ علالدین 2", "floor_label": "طبقه 6", "floor_num": 6, "unit": "واحد 622"}
    b = P.parse_address("پاساژ چارسو، طبقه زیر همکف، پلاک A57")
    assert b["floor_num"] == -1 and b["unit"] == "پلاک A57"
    c = P.parse_address("خیابان لاله زارنو، پاساژ درافشان، طبقه پنجم، پلاک 6/27")
    assert c["floor_num"] == 5 and c["unit"] == "پلاک 6/27"
    d = P.parse_address("میدان فردوسی، پاساژ تجارت جهانی فردوسی، طبقه منفی یک")
    assert d["floor_num"] == -1


def test_camera_chains():
    assert P.parse_mp("سه گانه 64+12+5 مگاپیکسل (OIS)") == 64
    assert P.parse_mp("2 + 8 + 50 مگاپیکسل") == 50
    assert P.parse_mp("50 مگاپیکسل، f/1.8، 1/1.56 اینچ") == 50


def test_low_end_chips():
    assert P.chip_tier("MediaTek MT6762G Helio G25 (12 nm)") == 1.6
    assert P.chip_tier("MTK6739") == 1.0
    assert P.chip_tier("چهار هسته ای MTK 6580M") == 0.6
    assert P.chip_tier("Qualcomm Snapdragon 6s 4G Gen 1") == 5.0
    assert P.chip_tier("چهار هسته ای") is None
