"""Safety rules: CPCB Indian AQI, heat-stress bands and school activity decisions.

Everything here is deterministic so the app gives the same, explainable answer
with or without an LLM.
"""

from __future__ import annotations

# CPCB National AQI breakpoints: (conc_lo, conc_hi, aqi_lo, aqi_hi)
PM25_BREAKPOINTS = [
    (0, 30, 0, 50),
    (30, 60, 51, 100),
    (60, 90, 101, 200),
    (90, 120, 201, 300),
    (120, 250, 301, 400),
    (250, 500, 401, 500),
]
PM10_BREAKPOINTS = [
    (0, 50, 0, 50),
    (50, 100, 51, 100),
    (100, 250, 101, 200),
    (250, 350, 201, 300),
    (350, 430, 301, 400),
    (430, 600, 401, 500),
]

AQI_BANDS = [
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (10_000, "Severe"),
]

# Heat-stress bands on "feels like" temperature (deg C), adapted from the
# NWS heat-index bands used in many Indian heat action plans.
HEAT_BANDS = [
    (27, "Comfortable"),
    (32, "Warm"),
    (41, "Caution"),
    (47, "Extreme caution"),
    (54, "Danger"),
    (10_000, "Extreme danger"),
]

# Severity levels shared by air and heat, 0 (fine) .. 4 (stop)
LEVELS = ["Go", "Go with care", "Limit", "Move indoors", "Stay home"]
LEVELS_HI = ["ठीक है", "सावधानी से", "सीमित करें", "अंदर ही रखें", "घर पर रहें"]


def _sub_index(conc: float | None, table) -> int | None:
    if conc is None:
        return None
    for c_lo, c_hi, i_lo, i_hi in table:
        if conc <= c_hi:
            return round(i_lo + (i_hi - i_lo) * (max(conc, c_lo) - c_lo) / (c_hi - c_lo))
    return 500


def indian_aqi(pm25: float | None, pm10: float | None) -> dict:
    """CPCB AQI = max of pollutant sub-indices."""
    subs = {"PM2.5": _sub_index(pm25, PM25_BREAKPOINTS), "PM10": _sub_index(pm10, PM10_BREAKPOINTS)}
    subs = {k: v for k, v in subs.items() if v is not None}
    if not subs:
        return {"aqi": None, "category": "Unknown", "dominant": None}
    dominant = max(subs, key=subs.get)
    aqi = subs[dominant]
    return {"aqi": aqi, "category": aqi_category(aqi), "dominant": dominant}


def aqi_category(aqi: int) -> str:
    return next(name for limit, name in AQI_BANDS if aqi <= limit)


def heat_category(feels_like: float) -> str:
    return next(name for limit, name in HEAT_BANDS if feels_like < limit)


def air_level(aqi: int, sensitive: bool) -> int:
    if aqi <= 100:
        return 0
    if aqi <= 200:
        return 2 if sensitive else 1
    if aqi <= 300:
        return 3 if sensitive else 2
    if aqi <= 400:
        return 3
    return 4


def heat_level(feels_like: float, sensitive: bool) -> int:
    if feels_like < 32:
        return 0
    if feels_like < 41:
        return 2 if sensitive else 1
    if feels_like < 47:
        return 3 if sensitive else 2
    if feels_like < 54:
        return 3
    return 4


# Activities a school actually has to decide on, with typical local hours and
# how strenuous they are (strenuous activities step up one level when air/heat is bad).
ACTIVITIES = [
    {"id": "assembly", "name": "Morning assembly", "name_hi": "प्रार्थना सभा", "hours": (7, 9), "strenuous": False},
    {"id": "recess", "name": "Recess / outdoor play", "name_hi": "मध्यावकाश / खेल", "hours": (10, 12), "strenuous": False},
    {"id": "pe", "name": "PE & sports practice", "name_hi": "शारीरिक शिक्षा / खेल अभ्यास", "hours": (9, 14), "strenuous": True},
    {"id": "dismissal", "name": "Dismissal & commute", "name_hi": "छुट्टी और घर वापसी", "hours": (13, 15), "strenuous": False},
]

ACTION_TEXT = {
    0: "Normal schedule.",
    1: "Go ahead. Water breaks every 20 min; watch children who cough or tire easily.",
    2: "Keep it short (under 20 min), in shade, no running drills. Inhalers on hand.",
    3: "Move indoors. No outdoor exertion today.",
    4: "Cancel outdoor activity. Consider online/hybrid classes.",
}
ACTION_TEXT_HI = {
    0: "सामान्य कार्यक्रम।",
    1: "जारी रखें। हर 20 मिनट पानी पिलाएँ; खाँसने या जल्दी थकने वाले बच्चों पर ध्यान दें।",
    2: "छोटा रखें (20 मिनट से कम), छाँव में, दौड़ नहीं। इनहेलर पास रखें।",
    3: "कक्षा के अंदर करें। आज बाहर कोई मेहनत वाली गतिविधि नहीं।",
    4: "बाहरी गतिविधि रद्द करें। ऑनलाइन/हाइब्रिड कक्षाओं पर विचार करें।",
}


def decide(hours: list[dict], sensitive: bool) -> list[dict]:
    """hours: [{hour, aqi, feels_like}] for one school day."""
    out = []
    for act in ACTIVITIES:
        lo, hi = act["hours"]
        window = [h for h in hours if lo <= h["hour"] <= hi]
        if not window:
            continue
        worst_aqi = max(h["aqi"] for h in window)
        worst_heat = max(h["feels_like"] for h in window)
        a = air_level(worst_aqi, sensitive)
        t = heat_level(worst_heat, sensitive)
        if act["strenuous"]:
            # Exertion steps a bad day up one level, but only conditions themselves close the school.
            a = a if a in (0, 4) else min(3, a + 1)
            t = t if t in (0, 4) else min(3, t + 1)
        level = max(a, t)
        reason = "air" if a >= t and a > 0 else ("heat" if t > 0 else None)
        out.append({
            "id": act["id"],
            "name": act["name"],
            "name_hi": act["name_hi"],
            "window": f"{lo:02d}:00-{hi:02d}:00",
            "level": level,
            "verdict": LEVELS[level],
            "verdict_hi": LEVELS_HI[level],
            "action": ACTION_TEXT[level],
            "action_hi": ACTION_TEXT_HI[level],
            "driver": reason,
            "peak_aqi": worst_aqi,
            "peak_feels_like": round(worst_heat, 1),
        })
    return out


def tips(aqi: int, feels_like: float) -> list[str]:
    t = []
    if aqi > 200:
        t.append("Keep windows shut during peak traffic hours (8-10 am, 5-8 pm); ventilate around midday.")
        t.append("N95/FFP2 masks for the commute, not cloth masks.")
    if aqi > 300:
        t.append("Under GRAP Stage III/IV, Delhi-NCR schools may be ordered into hybrid mode; check DoE circulars.")
    if aqi > 100:
        t.append("Children with asthma: carry reliever inhaler, skip strenuous play.")
    if feels_like >= 32:
        t.append("Water bell every 30-40 minutes; ORS available in the sick room.")
    if feels_like >= 41:
        t.append("Hold assembly before 8 am or indoors; light cotton uniforms, caps allowed.")
        t.append("Know heatstroke signs: hot dry skin, confusion, vomiting - cool and call 108.")
    if not t:
        t.append("Good conditions - a great day for outdoor learning.")
    return t
