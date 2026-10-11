"""Free, keyless data sources: Open-Meteo air quality, weather and geocoding."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date

import httpx

from . import rules

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

SCHOOL_HOURS = range(7, 16)  # 07:00-15:00 local
_cache: dict[tuple, tuple[float, dict]] = {}
CACHE_SECONDS = 30 * 60


def seed(lat: float, lon: float, air: dict, wx: dict) -> None:
    """Store forecasts the browser fetched itself, so the report and the agent reuse them.

    Free hosts share outbound IPs, and Open-Meteo rate-limits busy IPs; letting each
    visitor's browser fetch keeps the app working for everyone.
    """
    if not (air.get("hourly", {}).get("pm2_5") and wx.get("hourly", {}).get("apparent_temperature")):
        raise ValueError("Incomplete forecast data")
    _cache[(round(lat, 2), round(lon, 2))] = (time.time(), {"air": air, "wx": wx})


def geocode(query: str) -> list[dict]:
    r = httpx.get(GEOCODE_URL, params={"name": query, "count": 6, "language": "en"}, timeout=15)
    r.raise_for_status()
    results = r.json().get("results") or []
    # Indian places first, then by population, so "Kolhapur" means the city, not a same-named village.
    results.sort(key=lambda x: (x.get("country_code") != "IN", -(x.get("population") or 0)))
    if not results:
        return _nominatim(query)
    return _dedupe([
        {
            "name": x["name"],
            "admin": ", ".join(p for p in (x.get("admin2"), x.get("admin1"), x.get("country")) if p),
            "lat": x["latitude"],
            "lon": x["longitude"],
        }
        for x in results
    ])


def _dedupe(places: list[dict]) -> list[dict]:
    seen, out = set(), []
    for p in places:
        key = (p["name"].lower(), p["admin"].lower())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _nominatim(query: str) -> list[dict]:
    """OpenStreetMap fallback for localities and school names the city geocoder misses."""
    r = httpx.get(
        NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": 6, "countrycodes": "in"},
        headers={"User-Agent": "SaansSafe/1.0 (school air & heat safety, hackathon project)"},
        timeout=15,
    )
    r.raise_for_status()
    return [
        {
            "name": x["display_name"].split(",")[0],
            "admin": ", ".join(p.strip() for p in x["display_name"].split(",")[1:4]),
            "lat": float(x["lat"]),
            "lon": float(x["lon"]),
        }
        for x in r.json()
    ]


def _fetch(lat: float, lon: float) -> tuple[dict, dict]:
    common = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 4}
    with httpx.Client(timeout=20) as c:
        air = c.get(AIR_URL, params={**common, "hourly": "pm2_5,pm10"})
        wx = c.get(
            WEATHER_URL,
            params={**common, "hourly": "temperature_2m,relative_humidity_2m,apparent_temperature,uv_index"},
        )
    air.raise_for_status()
    wx.raise_for_status()
    return air.json(), wx.json()


def school_report(lat: float, lon: float, place: str = "", sensitive: bool = False) -> dict:
    """Day-by-day school safety report for the next 4 days."""
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        air, wx = hit[1]["air"], hit[1]["wx"]
    else:
        air, wx = _fetch(lat, lon)
        _cache[key] = (time.time(), {"air": air, "wx": wx})

    ah, wh = air["hourly"], wx["hourly"]
    weather_by_time = {
        t: (wh["temperature_2m"][i], wh["relative_humidity_2m"][i], wh["apparent_temperature"][i], wh["uv_index"][i])
        for i, t in enumerate(wh["time"])
    }

    days: dict[str, list[dict]] = defaultdict(list)
    for i, t in enumerate(ah["time"]):
        pm25, pm10 = ah["pm2_5"][i], ah["pm10"][i]
        w = weather_by_time.get(t)
        if w is None or (pm25 is None and pm10 is None) or w[2] is None:
            continue
        a = rules.indian_aqi(pm25, pm10)
        days[t[:10]].append({
            "time": t,
            "hour": int(t[11:13]),
            "pm25": pm25,
            "pm10": pm10,
            "aqi": a["aqi"],
            "dominant": a["dominant"],
            "temp": w[0],
            "rh": w[1],
            "feels_like": w[2],
            "uv": w[3],
        })

    now_iso = wx.get("current", {}).get("time")
    out_days = []
    for date in sorted(days)[:4]:
        hours = days[date]
        school = [h for h in hours if h["hour"] in SCHOOL_HOURS] or hours
        peak_aqi = max(h["aqi"] for h in school)
        peak_heat = max(h["feels_like"] for h in school)
        acts = rules.decide(school, sensitive)
        overall = max(a["level"] for a in acts) if acts else 0
        out_days.append({
            "date": date,
            "peak_aqi": peak_aqi,
            "aqi_category": rules.aqi_category(peak_aqi),
            "aqi_category_hi": rules.AQI_CATEGORY_HI[rules.aqi_category(peak_aqi)],
            "peak_feels_like": round(peak_heat, 1),
            "heat_category": rules.heat_category(peak_heat),
            "heat_category_hi": rules.heat_category(peak_heat, hindi=True),
            "max_uv": max((h["uv"] or 0) for h in school),
            "overall_level": overall,
            "overall": rules.LEVELS[overall],
            "overall_hi": rules.LEVELS_HI[overall],
            "activities": acts,
            "tips": rules.tips(peak_aqi, peak_heat),
            "hourly": [
                {"hour": h["hour"], "aqi": h["aqi"], "feels_like": round(h["feels_like"], 1)} for h in hours
            ],
        })

    return {
        "place": place or f"{lat:.3f}, {lon:.3f}",
        "lat": lat,
        "lon": lon,
        "timezone": air.get("timezone"),
        "sensitive": sensitive,
        "generated_at": now_iso or time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() + wx.get("utc_offset_seconds", 0))),
        "days": out_days,
        "source": "Copernicus CAMS forecast via Open-Meteo (~40 km grid). AQI uses CPCB National AQI breakpoints on hourly PM2.5/PM10; heat alerts follow the IMD colour code.",
    }


WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_HI = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]

# What the school will do, in words a parent understands: (activity id, level) -> (en, hi)
SCHOOL_PLAN = {
    ("assembly", 1): ("keep the morning assembly short", "प्रार्थना सभा छोटी रखेगा"),
    ("assembly", 2): ("keep the morning assembly short and in the shade", "प्रार्थना सभा छोटी और छाँव में करेगा"),
    ("assembly", 3): ("hold the morning assembly inside the classrooms", "प्रार्थना सभा कक्षाओं के अंदर करेगा"),
    ("recess", 1): ("give children regular water breaks during recess", "मध्यावकाश में बच्चों को बार-बार पानी पिलाएगा"),
    ("recess", 2): ("keep outdoor play at recess short and in the shade", "मध्यावकाश में बाहर का खेल कम और छाँव में रखेगा"),
    ("recess", 3): ("keep children indoors during recess", "मध्यावकाश में बच्चों को कक्षा के अंदर रखेगा"),
    ("pe", 1): ("hold PE with extra water breaks", "पीटी के दौरान अतिरिक्त पानी का ब्रेक देगा"),
    ("pe", 2): ("keep PE light and short, with no running", "पीटी हल्की और छोटी रखेगा, दौड़ नहीं होगी"),
    ("pe", 3): ("hold PE indoors, with no outdoor games", "पीटी अंदर कराएगा, बाहर कोई खेल नहीं होगा"),
}
# When polluted air (not heat) is the reason, shade does not help - say what does.
SCHOOL_PLAN_AIR = {
    ("assembly", 1): ("keep the morning assembly short", "प्रार्थना सभा छोटी रखेगा"),
    ("assembly", 2): ("keep the morning assembly very short", "प्रार्थना सभा बहुत छोटी रखेगा"),
    ("recess", 1): ("keep an eye on children who cough or tire easily during recess", "मध्यावकाश में खाँसने या जल्दी थकने वाले बच्चों पर ध्यान रखेगा"),
    ("recess", 2): ("keep outdoor play at recess short and calm", "मध्यावकाश में बाहर का खेल कम और हल्का रखेगा"),
    ("pe", 1): ("keep PE light, with rest breaks", "पीटी हल्की रखेगा और बीच-बीच में आराम देगा"),
}


def fmt_date(iso: str) -> tuple[str, str, str]:
    """'2026-10-13' -> ('13-10-2026', 'Tuesday', 'मंगलवार')"""
    y, m, d = (int(x) for x in iso[:10].split("-"))
    wd = date(y, m, d).weekday()
    return f"{d:02d}-{m:02d}-{y}", WEEKDAYS_EN[wd], WEEKDAYS_HI[wd]


def parent_notice(report: dict, day_index: int = 0) -> dict:
    """A circular the school can forward to the parents' WhatsApp group, in English and Hindi.

    Built from the same rules as the dashboard (no LLM), worded for parents rather than staff.
    """
    d = report["days"][day_index]
    dmy, wd_en, wd_hi = fmt_date(d["date"])
    when_en = ["Today", "Tomorrow"][day_index] if day_index < 2 else f"On {wd_en}"
    when_hi = ["आज", "कल"][day_index] if day_index < 2 else f"{wd_hi} को"
    place = report["place"]
    aqi, feels = d["peak_aqi"], round(d["peak_feels_like"])
    levels = {a["id"]: a["level"] for a in d["activities"]}
    drivers = {a["id"]: a["driver"] for a in d["activities"]}
    overall = d["overall_level"]
    hot, bad_air = feels >= 32, aqi > 100

    # 1. Conditions, in one plain sentence
    air_en = f"the air quality in {place} is expected to be {d['aqi_category'].lower()} (AQI up to {aqi})"
    air_hi = f"{place} में हवा की गुणवत्ता {d['aqi_category_hi']} (AQI {aqi} तक) रहने की संभावना है"
    if feels >= 38:
        cond_en = f"{when_en}, {air_en}, and it will feel very hot, around {feels}°C, during school hours."
        cond_hi = f"{when_hi} {air_hi}, और स्कूल के समय काफ़ी गर्मी रहेगी (लगभग {feels}°C जैसा महसूस होगा)।"
    elif hot:
        cond_en = f"{when_en}, {air_en}, and it will be warm, feeling like {feels}°C, during school hours."
        cond_hi = f"{when_hi} {air_hi}, और स्कूल के समय गर्मी रहेगी (लगभग {feels}°C जैसा महसूस होगा)।"
    else:
        cond_en = f"{when_en}, {air_en}, and the weather will be pleasant."
        cond_hi = f"{when_hi} {air_hi}, और मौसम सुहावना रहेगा।"

    en = [f"*School update for {wd_en}, {dmy}*", "", "Dear Parents,", "", cond_en, ""]
    hi = [f"*विद्यालय सूचना - {wd_hi}, {dmy}*", "", "प्रिय अभिभावकगण,", "", cond_hi, ""]

    # 2. What the school will do
    if overall >= 4:
        en += ["Because conditions are expected to be severe, the school may hold classes online or stay closed. "
               "We will confirm this in a separate message. Please keep your child indoors as far as possible.", ""]
        hi += ["स्थिति गंभीर रहने की संभावना है, इसलिए विद्यालय ऑनलाइन कक्षाएँ चला सकता है या बंद रह सकता है। "
               "इसकी पुष्टि अलग संदेश से की जाएगी। कृपया बच्चों को यथासंभव घर के अंदर रखें।", ""]
    else:
        plan = [
            (SCHOOL_PLAN_AIR if drivers[k] == "air" and (k, v) in SCHOOL_PLAN_AIR else SCHOOL_PLAN)[(k, v)]
            for k, v in levels.items()
            if (k, v) in SCHOOL_PLAN
        ]
        if plan:
            en.append("To keep the children safe, the school will:")
            hi.append("बच्चों की सुरक्षा के लिए विद्यालय:")
            en += [f"• {x[0]}" for x in plan] + [""]
            hi += [f"• {x[1]}" for x in plan] + [""]
        else:
            en += ["All school activities, including outdoor play and PE, will go ahead as usual.", ""]
            hi += ["खेल और पीटी सहित विद्यालय की सभी गतिविधियाँ सामान्य रूप से होंगी।", ""]

    # 3. What parents can do
    ask_en, ask_hi = [], []
    if hot or overall >= 1:
        ask_en.append("a full water bottle" + (" (an extra one if possible)" if feels >= 38 else ""))
        ask_hi.append("पानी की भरी बोतल" + (" (हो सके तो एक अतिरिक्त)" if feels >= 38 else ""))
    if feels >= 36:
        ask_en.append("a cap and light cotton clothes")
        ask_hi.append("टोपी और हल्के सूती कपड़े")
    if aqi > 200:
        ask_en.append("an N95 mask for the journey to and from school")
        ask_hi.append("आने-जाने के लिए N95 मास्क")
    if bad_air or report.get("sensitive"):
        ask_en.append("their inhaler or medicines, if your child has asthma")
        ask_hi.append("अस्थमा हो तो बच्चे का इनहेलर या दवाइयाँ")
    if ask_en:
        en += ["Please send your child with:"] + [f"• {x}" for x in ask_en] + [""]
        hi += ["कृपया बच्चे के साथ भेजें:"] + [f"• {x}" for x in ask_hi] + [""]
    if overall >= 2:
        en += ["If your child has a fever, cough or difficulty breathing, please keep them at home and inform the class teacher.", ""]
        hi += ["यदि बच्चे को बुखार, खाँसी या साँस लेने में तकलीफ़ हो, तो कृपया उसे घर पर रखें और कक्षा अध्यापक को सूचित करें।", ""]
    if levels.get("dismissal", 0) >= 2:
        en += ["At dismissal, please pick your child up on time so they do not have to wait outside.", ""]
        hi += ["छुट्टी के समय कृपया बच्चे को समय पर लेने आएँ, ताकि उसे बाहर इंतज़ार न करना पड़े।", ""]

    en += ["Thank you for your cooperation.", "", "Principal"]
    hi += ["आपके सहयोग के लिए धन्यवाद।", "", "प्रधानाचार्य"]
    return {"en": "\n".join(en), "hi": "\n".join(hi)}
