"""SaansSafe advisor agent, built on the AWS open-source Strands Agents SDK.

The agent never guesses numbers: it calls tools that run the same CPCB/heat
rules as the dashboard, then explains them in plain English or Hindi.

Any OpenAI-compatible endpoint works, so it can run for free:
  - Groq free tier:   LLM_PROVIDER=groq   GROQ_API_KEY=...
  - Gemini free tier: LLM_PROVIDER=gemini GEMINI_API_KEY=...
  - Local Ollama:     LLM_PROVIDER=ollama (no key)
  - Amazon Bedrock:   LLM_PROVIDER=bedrock (uses your AWS credentials)
"""

from __future__ import annotations

import json
import logging
import os

from strands import Agent, tool
from strands.event_loop._retry import ModelRetryStrategy
from strands.types.exceptions import ModelThrottledException

from . import data

# gpt-oss returns reasoning blocks; Strands drops them between turns and warns each time.
logging.getLogger("strands.models.openai").setLevel(logging.ERROR)

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "ollama": ("http://localhost:11434/v1", None, "llama3.2"),
}

SYSTEM_PROMPT = """You are SaansSafe, a school safety advisor for India on bad-air and heatwave days.
You help principals, teachers and parents decide what children can safely do outdoors.

Rules:
- ALWAYS call a tool to get real conditions before giving advice. Never invent AQI or temperature numbers.
- If the user names a place, call find_place first if you are unsure of its coordinates, then school_conditions.
- Use the verdicts the tool returns (Go / Go with care / Limit / Move indoors / Stay home); do not override them.
- Be short and practical: at most 8 plain bullet points ("- "), concrete times, what to do instead.
- Plain text only: no tables, no headings, no bold or other markdown.
- Mention children with asthma or other sensitivities when air is Moderate or worse.
- Reply in the user's language. If they write in Hindi or Hinglish, reply in simple Hindi.
- You are not a doctor; for symptoms like breathlessness or heatstroke tell them to seek medical help (108).
"""


def provider_name() -> str | None:
    p = os.getenv("LLM_PROVIDER", "").lower()
    if p:
        return p
    for name, (_, key_env, _) in PRESETS.items():
        if key_env and os.getenv(key_env):
            return name
    return None


# Groq's free tier allows 8k tokens/minute *per model*; when the main model is throttled we
# switch to a second one with its own quota instead of sitting through long retries.
FALLBACK_MODELS = {"groq": "openai/gpt-oss-20b"}

# Strands' default retries throttled calls up to 6 times (4s, 8s, ... 64s): minutes of a frozen page.
QUICK_RETRY = dict(max_attempts=2, initial_delay=2, max_delay=4)


def _model(model_id: str | None = None):
    provider = provider_name()
    if provider is None:
        return None
    if provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(model_id=os.getenv("LLM_MODEL", "us.amazon.nova-lite-v1:0"))

    from strands.models.openai import OpenAIModel

    base_url, key_env, default_model = PRESETS.get(provider, (os.getenv("LLM_BASE_URL"), "LLM_API_KEY", None))
    api_key = os.getenv(key_env) if key_env else "ollama"
    return OpenAIModel(
        client_args={"api_key": api_key or os.getenv("LLM_API_KEY"), "base_url": os.getenv("LLM_BASE_URL", base_url)},
        model_id=model_id or os.getenv("LLM_MODEL", default_model),
        params={"temperature": 0.3, "max_tokens": 700},
    )


@tool
def find_place(query: str) -> str:
    """Find coordinates for a school, locality or city in India.

    Args:
        query: Place name, e.g. "DPS R.K. Puram" or "Anand Vihar, Delhi".
    """
    return json.dumps(data.geocode(query)[:3])


@tool
def school_conditions(lat: float, lon: float, place: str = "", sensitive_children: bool = False, day: int = 0) -> str:
    """Get air quality (Indian AQI), heat stress and activity verdicts for school hours.

    Args:
        lat: Latitude of the school.
        lon: Longitude of the school.
        place: Human-readable name of the place.
        sensitive_children: True when advising for children with asthma or other sensitivities.
        day: 0 = today, 1 = tomorrow, up to 3.
    """
    report = data.school_report(lat, lon, place, sensitive_children)
    d = report["days"][max(0, min(day, len(report["days"]) - 1))]
    # Compact on purpose: the free LLM tier is metered in tokens per minute.
    return json.dumps({
        "place": report["place"],
        "date": data.fmt_date(d["date"])[0],
        "school_hours_peak_aqi": d["peak_aqi"],
        "aqi_category": d["aqi_category"],
        "peak_feels_like_c": d["peak_feels_like"],
        "heat_alert": d["heat_category"],
        "overall": d["overall"],
        "activities": [
            {"name": a["name"], "hours": a["window"], "verdict": a["verdict"], "do": a["action"], "because_of": a["driver"]}
            for a in d["activities"]
        ],
        "tips": [t["en"] for t in d["tips"]],
    })


@tool
def parent_circular(lat: float, lon: float, place: str, day: int = 0) -> str:
    """Draft a WhatsApp-ready notice for parents in English and Hindi.

    Args:
        lat: Latitude of the school.
        lon: Longitude of the school.
        place: School or locality name to show in the notice.
        day: 0 = today, 1 = tomorrow, up to 3.
    """
    return json.dumps(data.parent_notice(data.school_report(lat, lon, place), day), ensure_ascii=False)


def is_enabled() -> bool:
    return provider_name() is not None


HINDI_RULE = """
LANGUAGE: Write your entire final answer in simple Hindi, in Devanagari script (हिंदी), even though the
tool results are in English. Translate verdicts too: Go = ठीक है, Go with care = सावधानी से,
Limit = सीमित करें, Move indoors = अंदर ही रखें, Stay home = घर पर रहें. Keep numbers, AQI and °C as they are.
"""


ENGLISH_RULE = "\nLANGUAGE: Write your final answer in English.\n"


def ask(question: str, context: dict | None = None, hindi: bool = False) -> str:
    if _model() is None:
        raise RuntimeError("No LLM configured. Set GROQ_API_KEY or GEMINI_API_KEY (both have free tiers).")
    if context:
        question = (
            f"[The user is looking at: {context.get('place')} (lat {context.get('lat')}, lon {context.get('lon')}), "
            f"sensitive_children={context.get('sensitive', False)}. Use these coordinates; no need to call find_place.]\n{question}"
        )
    fallback = FALLBACK_MODELS.get(provider_name() or "")
    for model_id in [None, fallback] if fallback else [None]:
        agent = Agent(
            model=_model(model_id),
            tools=[find_place, school_conditions, parent_circular],
            system_prompt=SYSTEM_PROMPT + (HINDI_RULE if hindi else ENGLISH_RULE),
            callback_handler=None,
            retry_strategy=ModelRetryStrategy(**QUICK_RETRY),
        )
        try:
            return str(agent(question)).strip()
        except ModelThrottledException:
            continue
    raise AdvisorBusy()


class AdvisorBusy(Exception):
    """Every model's free-tier quota is used up for this minute."""
