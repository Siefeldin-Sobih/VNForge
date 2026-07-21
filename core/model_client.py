"""Provider adapters with structured JSON, validation, and bounded repair."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import requests
from dotenv import load_dotenv
from pydantic import ValidationError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.prompts import build_repair_prompt
from core.schemas import ScenePlan

load_dotenv()

PROVIDER = os.getenv("PROVIDER", "")
WATSONX_REGION = os.getenv("WATSONX_REGION", "us-south")
WATSONX_API_KEY = os.getenv("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_MODEL_ID = os.getenv("WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _build_session() -> requests.Session:
    """Build a provider session with bounded rate-limit and server retries."""
    retry = Retry(
        total=2,
        connect=2,
        read=1,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


SESSION = _build_session()


class CompilationCancelled(RuntimeError):
    """Raised when the creator cancels a pending compilation workflow."""


def _check_cancelled(cancel_event: threading.Event | None) -> None:
    """Stop between network operations when cancellation was requested."""
    if cancel_event and cancel_event.is_set():
        raise CompilationCancelled("Compilation cancelled.")


def _watsonx_base_url(region: str) -> str:
    """Return the public watsonx service URL for a supported region."""
    if region == "ap-south-1":
        return "https://ap-south-1.aws.wxai.ibm.com"
    return f"https://{region}.ml.cloud.ibm.com"


def _get_watsonx_token(api_key: str) -> str:
    """Exchange an IBM API key for a short-lived IAM bearer token."""
    response = SESSION.post(
        IAM_URL,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"IBM IAM authentication failed ({response.status_code}).")
    return response.json()["access_token"]


def fetch_watsonx_models(
    api_key: str,
    region: str = "us-south",
) -> list[str]:
    """Fetch currently available Granite text-generation models by region."""
    token = _get_watsonx_token(api_key)
    response = SESSION.get(
        f"{_watsonx_base_url(region)}/ml/v1/foundation_model_specs",
        params={"version": "2024-05-31", "filters": "function_text_generation"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list watsonx models ({response.status_code}).")
    resources = response.json().get("resources", [])
    model_ids = sorted(
        item["model_id"] for item in resources if item.get("model_id", "").startswith("ibm/granite")
    )
    if not model_ids:
        raise RuntimeError("No Granite generation models are available in this region.")
    return model_ids


def validate_watsonx(
    api_key: str,
    project_id: str,
    region: str = "us-south",
    model_id: str = "ibm/granite-3-3-8b-instruct",
) -> None:
    """Validate IBM credentials, project access, region, and selected model."""
    token = _get_watsonx_token(api_key)
    response = SESSION.post(
        f"{_watsonx_base_url(region)}/ml/v1/text/generation",
        params={"version": "2024-05-31"},
        json={
            "model_id": model_id,
            "input": "Reply with OK",
            "project_id": project_id,
            "parameters": {"max_new_tokens": 2, "decoding_method": "greedy"},
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"watsonx project/model validation failed ({response.status_code}): "
            f"{response.text[:300]}"
        )


def validate_gemini(api_key: str) -> None:
    """Validate a Gemini key without generating creator content."""
    response = SESSION.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": api_key},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini key validation failed ({response.status_code}).")


def fetch_gemini_models(api_key: str) -> list[str]:
    """Return Gemini models that currently advertise content generation."""
    response = SESSION.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": api_key},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list Gemini models ({response.status_code}).")
    models = sorted(
        item.get("name", "").removeprefix("models/")
        for item in response.json().get("models", [])
        if "generateContent" in item.get("supportedGenerationMethods", [])
        and "flash" in item.get("name", "").lower()
    )
    if not models:
        raise RuntimeError("No Gemini Flash generation models are available.")
    return models


def validate_openrouter(api_key: str) -> None:
    """Validate an OpenRouter key against the account endpoint."""
    response = SESSION.get(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter key validation failed ({response.status_code}).")


def fetch_openrouter_models(api_key: str) -> list[str]:
    """Return currently advertised free OpenRouter model identifiers."""
    response = SESSION.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list OpenRouter models ({response.status_code}).")
    models = sorted(
        item["id"]
        for item in response.json().get("data", [])
        if item.get("id", "").endswith(":free")
    )
    if not models:
        raise RuntimeError("No free OpenRouter models are currently advertised.")
    return models


def _call_watsonx(system: str, user: str) -> str:
    """Generate a structured scene plan using IBM watsonx."""
    token = _get_watsonx_token(WATSONX_API_KEY)
    prompt = f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n"
    response = SESSION.post(
        f"{_watsonx_base_url(WATSONX_REGION)}/ml/v1/text/generation",
        params={"version": "2024-05-31"},
        json={
            "model_id": WATSONX_MODEL_ID,
            "input": prompt,
            "project_id": WATSONX_PROJECT_ID,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": 8192,
                "repetition_penalty": 1.05,
            },
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"watsonx generation failed ({response.status_code}): {response.text[:500]}"
        )
    return response.json()["results"][0]["generated_text"]


def _call_gemini(system: str, user: str) -> str:
    """Generate a JSON scene plan using Gemini's JSON response mode."""
    response = SESSION.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Gemini generation failed ({response.status_code}): {response.text[:500]}"
        )
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(system: str, user: str) -> str:
    """Generate a JSON scene plan through OpenRouter."""
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Siefeldin-Sobih/VNForge",
        "X-Title": "VNForge",
    }
    response = SESSION.post(
        OPENROUTER_API_URL,
        json=payload,
        headers=headers,
        timeout=120,
    )
    if response.status_code == 400 and "response_format" in response.text:
        payload.pop("response_format")
        response = SESSION.post(
            OPENROUTER_API_URL,
            json=payload,
            headers=headers,
            timeout=120,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter generation failed ({response.status_code}): {response.text[:500]}"
        )
    return response.json()["choices"][0]["message"]["content"]


def _call_provider(system: str, user: str) -> str:
    """Route one request to the configured provider."""
    if PROVIDER == "watsonx":
        if not WATSONX_API_KEY or not WATSONX_PROJECT_ID:
            raise RuntimeError("watsonx credentials are not configured.")
        return _call_watsonx(system, user)
    if PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("Gemini credentials are not configured.")
        return _call_gemini(system, user)
    if PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OpenRouter credentials are not configured.")
        return _call_openrouter(system, user)
    raise RuntimeError(f"Unknown or missing provider '{PROVIDER}'. Configure VNForge first.")


def _extract_json(raw_text: str) -> dict[str, Any]:
    """Extract the first complete JSON object from a provider response."""
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline >= 0 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    if start < 0:
        raise ValueError("Provider response contained no JSON object.")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON parsing failed: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("Provider response must be a JSON object.")
    return value


def call_model(
    system: str,
    user: str | None = None,
    cancel_event: threading.Event | None = None,
    max_repairs: int = 2,
) -> ScenePlan:
    """Return a validated scene plan, repairing malformed output when needed.

    ``user`` is optional for compatibility with earlier single-prompt callers.
    """
    if user is None:
        user = system
        system = "Return only a VNForge ScenePlan JSON object."
    _check_cancelled(cancel_event)
    raw = _call_provider(system, user)
    for attempt in range(max_repairs + 1):
        _check_cancelled(cancel_event)
        try:
            return ScenePlan.model_validate(_extract_json(raw))
        except (ValueError, ValidationError) as error:
            if attempt >= max_repairs:
                raise ValueError(
                    f"Provider returned an invalid scene plan after {attempt + 1} attempts: {error}"
                ) from error
            repair_system, repair_user = build_repair_prompt(raw, str(error))
            raw = _call_provider(repair_system, repair_user)
    raise RuntimeError("Scene-plan validation ended unexpectedly.")
