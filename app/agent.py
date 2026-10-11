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
import os

from strands import Agent, tool

from . import data

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.5-flash"),
    "ollama": ("http://localhost:11434/v1", None, "llama3.2"),
}

SYSTEM_PROMPT = """You are SaansSafe, a school safety advisor for India on bad-air and heatwave days.
You help principals, teachers and parents decide what children can safely do outdoors.

Rules:
- ALWAYS call a tool to get real conditions before giving advice. Never invent AQI or temperature numbers.
- If the user names a place, call find_place first if you are unsure of its coordinates, then school_conditions.
- Use the verdicts the tool returns (Go / Go with care / Limit / Move indoors / Stay home); do not override them.
- Be short and practical: bullet points, concrete times, what to do instead.
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


def _model():
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
        model_id=os.getenv("LLM_MODEL", default_model),
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
    d = {k: v for k, v in d.items() if k != "hourly"}
    return json.dumps({"place": report["place"], "forecast_days": [x["date"] for x in report["days"]], **d})


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


def ask(question: str, context: dict | None = None) -> str:
    model = _model()
    if model is None:
        raise RuntimeError("No LLM configured. Set GROQ_API_KEY or GEMINI_API_KEY (both have free tiers).")
    agent = Agent(
        model=model,
        tools=[find_place, school_conditions, parent_circular],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    if context:
        question = (
            f"[The user is looking at: {context.get('place')} (lat {context.get('lat')}, lon {context.get('lon')}), "
            f"sensitive_children={context.get('sensitive', False)}]\n{question}"
        )
    return str(agent(question)).strip()
