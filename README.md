# SaansSafe: can the kids go outside today?

**Outdoor safety for Indian schools on bad-air and heatwave days.**
Type a school's location and SaansSafe turns live air-quality and heat forecasts into a clear verdict for each part of the school day (morning assembly, recess, PE and dismissal), plus a WhatsApp-ready notice for parents in English and Hindi.

**Live demo: https://saanssafe.onrender.com** (free tier, so the first load can take ~30 s while it wakes up)

> Tracks: **Air** (school safety on bad days, pollution exposure) · **Heat and Water** (heatwaves)
> AWS: the advisor agent is built on the **AWS open-source [Strands Agents SDK](https://github.com/strands-agents/sdk-python)**.

---

## The problem

Every winter, Delhi-NCR and the Indo-Gangetic plain see AQI above 300 for weeks. Every summer, the same schools face heat that "feels like" 45°C or more. Children breathe faster than adults and spend recess and PE outdoors, so they take the worst of it.

Today the decision ("do we hold assembly outside? cancel PE? let the asthmatic kids play?") is made by a principal looking at a single AQI number on a news app, often on the US scale, often for a station 10 km away, with no link to *when* the school is actually outdoors. Heat and air are checked separately, if at all. Parents get no clear message.

## What SaansSafe does

| Feature | What it does |
|---|---|
| **Any school in India** | Search a school, locality or city (OpenStreetMap), or use GPS. |
| **Indian standards** | AQI on India's **CPCB National AQI** scale (hourly PM2.5 / PM10), so numbers match Indian news, SAMEER and SAFAR. Heat alerts use the **IMD colour code** (Green / Yellow / Orange / Red). |
| **Judged on school hours** | Each activity is checked against its own time window (assembly 7-9, recess 10-12, PE 9-14, dismissal 13-15). |
| **Air + heat together** | The verdict is the worse of air risk and heat-stress risk ("feels like" temperature), and each card says which one is driving it. |
| **Five plain verdicts** | Go · Go with care · Limit · Move indoors · Stay home, each with a concrete instruction. |
| **Asthma mode** | Stricter thresholds for sensitive children. Strenuous PE always steps up one level. |
| **4-day outlook** | Plan sports day or a field trip ahead of time. |
| **Parent circular** | A ready-to-forward message for the parents' WhatsApp group in English or Hindi: what the conditions are, what the school will do, what to send with the child (water, cap, N95 mask, inhaler) and when to keep them home. Dated DD-MM-YYYY and signed with the school's name. |
| **Ask the advisor** | A Strands agent answers free-form questions ("Can we hold the football match tomorrow at 11?") in English or Hindi, after calling tools for live data. |
| **Bilingual UI** | Full English / हिंदी toggle. Works on a basic phone browser; no login, no install. |

The dashboard is **fully deterministic and works without any AI key**. The agent is an extra layer on top that never invents numbers.

## Architecture

```
 Browser (vanilla HTML/CSS/JS, mobile-first, EN/HI)
    │  /api/places   /api/report   /api/ask
    ▼
 FastAPI (app/main.py)
    ├── app/data.py   ─ Open-Meteo air quality (Copernicus CAMS) + weather forecast,
    │                   Open-Meteo / OpenStreetMap Nominatim geocoding, 15-min cache
    ├── app/rules.py  ─ CPCB AQI · IMD-colour heat alerts · per-activity decisions
    └── app/agent.py  ─ Strands Agents SDK agent
                         tools: find_place · school_conditions · parent_circular
                         model: any OpenAI-compatible LLM (Groq / Gemini free tiers,
                                local Ollama) or Amazon Bedrock
```

### How AWS is used
- **Strands Agents SDK (AWS open source):** `app/agent.py` defines three `@tool` functions and an `Agent` with a safety-first system prompt. The agent loop decides when to geocode, fetch conditions for a given day, or draft a parent circular, then explains the result. Because Strands is model-agnostic, the project runs **completely free** (Groq / Gemini free tier or local Ollama). Switching to **Amazon Bedrock** is one env var (`LLM_PROVIDER=bedrock`).
- Hosting: deployed free on Render from the `render.yaml` blueprint. Forecasts are fetched in the visitor's browser and posted to the API, because free hosts share outbound IPs that the free data APIs rate-limit.
- The app is a single Docker image (`Dockerfile`), so it can go to **AWS App Runner / ECS Fargate / Lightsail** unchanged when credits are available.

### The decision rules (`app/rules.py`)
- **AQI:** CPCB sub-index for PM2.5 and PM10, AQI = max. Bands: Good ≤50, Satisfactory ≤100, Moderate ≤200, Poor ≤300, Very Poor ≤400, Severe >400.
- **Air → level:** ≤100 Go · ≤200 Go with care (Limit in asthma mode) · ≤300 Limit (Move indoors in asthma mode) · ≤400 Move indoors · >400 Stay home.
- **Heat ("feels like" °C) → level:** <32 Go · <41 Go with care · <47 Limit · <54 Move indoors · ≥54 Stay home (stricter in asthma mode).
- **Heat alert label (IMD colour code):** <32 Green · 32-41 Yellow (be aware) · 41-47 Orange (be prepared) · ≥47 Red (take action). "Feels like" is used so humid coastal heat counts too.
- **Strenuous activities** (PE) step up one level, capped at "Move indoors"; only conditions themselves trigger "Stay home".
- Each activity uses the **worst hour inside its own window**.

All rules are unit-tested (`tests/test_rules.py`).

## Run it locally (free, about 2 minutes)

```bash
git clone <this repo> && cd saanssafe
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add a free GROQ_API_KEY or GEMINI_API_KEY for the advisor
uvicorn app.main:app --reload
# open http://localhost:8000
```

Tests: `pip install pytest && pytest -q`

Docker: `docker build -t saanssafe . && docker run -p 7860:7860 --env-file .env saanssafe`

### Free LLM options for the advisor
| Provider | Env | Cost |
|---|---|---|
| Groq | `GROQ_API_KEY` (console.groq.com) | free tier |
| Google Gemini | `GEMINI_API_KEY` (aistudio.google.com) | free tier |
| Ollama (local) | `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.2` | free |
| Amazon Bedrock | `LLM_PROVIDER=bedrock` + AWS credentials | pay-as-you-go |

## Data sources
- **Open-Meteo Air Quality API** (Copernicus CAMS global and European forecasts): hourly PM2.5 / PM10, 4-day forecast. Free, no key.
- **Open-Meteo Forecast API**: temperature, humidity, apparent temperature, UV.
- **Open-Meteo Geocoding** and **OpenStreetMap Nominatim** for place search.

## Limitations and next steps
- CAMS is a modelled forecast (~10-40 km grid), not a ground monitor. Next: blend in CPCB station readings from data.gov.in where a station is close.
- Hourly concentrations are used for school-hour decisions; the official CPCB AQI uses 24-hour averages, so a single hour can read higher than the daily bulletin.
- Next: SMS / WhatsApp Business alerts at 6 am for subscribed schools (Amazon SNS + EventBridge), school-specific timetables, and regional languages beyond Hindi.

**SaansSafe is a guidance tool, not a medical or government order. Always follow your state's DoE / GRAP circulars.**

## License
MIT
