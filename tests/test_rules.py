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
