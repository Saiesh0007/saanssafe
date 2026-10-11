"""Free, keyless data sources: Open-Meteo air quality, weather and geocoding."""

from __future__ import annotations

import time
from collections import defaultdict

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
    # Prefer Indian results - this is built for Indian schools first.
    results.sort(key=lambda x: x.get("country_code") != "IN")
    if not results:
        return _nominatim(query)
    return [
        {
            "name": x["name"],
            "admin": ", ".join(p for p in (x.get("admin2"), x.get("admin1"), x.get("country")) if p),
            "lat": x["latitude"],
            "lon": x["longitude"],
        }
        for x in results
    ]


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
            "peak_feels_like": round(peak_heat, 1),
            "heat_category": rules.heat_category(peak_heat),
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
        "generated_at": now_iso or time.strftime("%Y-%m-%dT%H:%M"),
        "days": out_days,
        "source": "Open-Meteo (CAMS air quality + weather forecast); AQI per CPCB breakpoints on hourly PM2.5/PM10",
    }


def parent_notice(report: dict, day_index: int = 0) -> dict:
    """WhatsApp-ready circular in English and Hindi, built from the rules (no LLM needed)."""
    d = report["days"][day_index]
    lines_en = [
        f"*{report['place']} - School safety update for {d['date']}*",
        f"Air: AQI up to {d['peak_aqi']} ({d['aqi_category']}). Heat: feels like {d['peak_feels_like']}°C ({d['heat_category']}).",
        "",
    ]
    lines_hi = [
        f"*{report['place']} - {d['date']} के लिए विद्यालय सुरक्षा सूचना*",
        f"वायु गुणवत्ता: AQI {d['peak_aqi']} तक ({d['aqi_category']})। गर्मी: महसूस तापमान {d['peak_feels_like']}°C।",
        "",
    ]
    for a in d["activities"]:
        lines_en.append(f"• {a['name']}: {a['verdict']} - {a['action']}")
        lines_hi.append(f"• {a['name_hi']}: {a['verdict_hi']} - {a['action_hi']}")
    lines_en += ["", "Parents: please send a water bottle" + (" and an N95 mask." if d["peak_aqi"] > 200 else ".")]
    lines_hi += ["", "अभिभावक कृपया पानी की बोतल" + (" और N95 मास्क भेजें।" if d["peak_aqi"] > 200 else " भेजें।")]
    return {"en": "\n".join(lines_en), "hi": "\n".join(lines_hi)}
