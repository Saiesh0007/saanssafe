from app import rules


def test_cpcb_aqi_breakpoints():
    assert rules.indian_aqi(30, 0)["aqi"] == 50
    assert rules.indian_aqi(60, 0)["aqi"] == 100
    assert rules.indian_aqi(75, 0)["category"] == "Moderate"
    assert rules.indian_aqi(100, 400)["category"] == "Very Poor"
    assert rules.indian_aqi(10, 300)["dominant"] == "PM10"
    assert rules.indian_aqi(None, None)["aqi"] is None


def hours(aqi, heat):
    return [{"hour": h, "aqi": aqi, "feels_like": heat} for h in range(7, 16)]


def verdicts(aqi, heat, sensitive=False):
    return {a["id"]: a["verdict"] for a in rules.decide(hours(aqi, heat), sensitive)}


def test_clean_cool_day_is_all_go():
    assert set(verdicts(40, 25).values()) == {"Go"}


def test_poor_air_moves_pe_indoors_but_not_closure():
    v = verdicts(250, 25)
    assert v["recess"] == "Limit"
    assert v["pe"] == "Move indoors"


def test_asthma_mode_is_stricter():
    assert verdicts(150, 25)["recess"] == "Go with care"
    assert verdicts(150, 25, sensitive=True)["recess"] == "Limit"


def test_severe_air_or_extreme_heat_says_stay_home():
    assert set(verdicts(450, 25).values()) == {"Stay home"}
    assert set(verdicts(40, 56).values()) == {"Stay home"}


def test_heat_alone_drives_decision():
    a = {x["id"]: x for x in rules.decide(hours(40, 44), False)}
    assert a["pe"]["driver"] == "heat"
    assert a["pe"]["verdict"] == "Move indoors"


def fake_report(aqi, heat, date="2026-10-13"):
    acts = rules.decide(hours(aqi, heat), False)
    day = {
        "date": date, "peak_aqi": aqi, "peak_feels_like": heat,
        "aqi_category": rules.aqi_category(aqi), "aqi_category_hi": rules.AQI_CATEGORY_HI[rules.aqi_category(aqi)],
        "overall_level": max(a["level"] for a in acts), "activities": acts,
    }
    return {"place": "Bhayandar", "sensitive": False, "days": [day]}


def test_parent_circular_is_dated_ddmmyyyy_and_addressed_to_parents():
    from app.data import parent_notice
    n = parent_notice(fake_report(100, 38))
    assert "Tuesday, 13-10-2026" in n["en"] and "2026-10-13" not in n["en"]
    assert "Dear Parents," in n["en"] and n["en"].endswith("Principal")
    assert "मंगलवार, 13-10-2026" in n["hi"] and "प्रिय अभिभावकगण" in n["hi"]
    assert "water bottle" in n["en"]


def test_circular_uses_air_wording_on_smoggy_days():
    from app.data import parent_notice
    n = parent_notice(fake_report(250, 25))["en"]
    assert "shade" not in n
    assert "N95" in n


def test_heat_alerts_use_imd_colours():
    assert rules.heat_category(30).startswith("Green")
    assert rules.heat_category(38).startswith("Yellow")
    assert rules.heat_category(44).startswith("Orange")
    assert rules.heat_category(50, hindi=True).startswith("लाल")
