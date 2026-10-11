"""SaansSafe API + static frontend."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import agent, data  # noqa: E402  (agent reads env at call time, after .env is loaded)

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SaansSafe", description="Outdoor safety for schools on bad-air and heatwave days")


@app.get("/api/health")
def health():
    return {"ok": True, "agent": agent.provider_name()}


@app.get("/api/places")
def places(q: str = Query(..., min_length=2)):
    try:
        return data.geocode(q)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Geocoding failed: {e}")


class ReportBody(BaseModel):
    lat: float
    lon: float
    place: str = ""
    sensitive: bool = False
    air: dict
    wx: dict


@app.post("/api/report")
def report_from_browser(body: ReportBody):
    try:
        data.seed(body.lat, body.lon, body.air, body.wx)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return report(body.lat, body.lon, body.place, body.sensitive)


@app.get("/api/report")
def report(lat: float, lon: float, place: str = "", sensitive: bool = False):
    try:
        r = data.school_report(lat, lon, place, sensitive)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Forecast service unavailable: {e}")
    if not r["days"]:
        raise HTTPException(404, "No forecast available for this location")
    r["notices"] = [data.parent_notice(r, i) for i in range(len(r["days"]))]
    return r


class AskBody(BaseModel):
    question: str = Field(..., min_length=2, max_length=800)
    place: str | None = None
    lat: float | None = None
    lon: float | None = None
    sensitive: bool = False
    lang: str = "en"


def wants_hindi(question: str, ui_lang: str) -> bool:
    """A question typed in Devanagari gets a Hindi answer whatever the page language;
    otherwise follow the page (so Hinglish on the Hindi page still gets Hindi)."""
    return bool(re.search(r"[ऀ-ॿ]", question)) or ui_lang == "hi"


@app.post("/api/ask")
def ask(body: AskBody):
    if not agent.is_enabled():
        raise HTTPException(503, "The AI advisor is not configured on this server. The dashboard still works.")
    ctx = body.model_dump() if body.lat is not None else None
    try:
        return {"answer": agent.ask(body.question, ctx, hindi=wants_hindi(body.question, body.lang))}
    except agent.AdvisorBusy:
        raise HTTPException(429, "busy")
    except Exception as e:  # surface model/provider errors to the UI instead of a blank 500
        raise HTTPException(502, f"Advisor error: {e}")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.ico", media_type="image/x-icon")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
