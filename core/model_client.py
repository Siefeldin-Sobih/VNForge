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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "deepseek-v4-flash")

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
OPENCODE_API_URL = "https://opencode.ai/zen/go/v1"
ANTHROPIC_VERSION = "2023-06-01"

# OpenCode Go publishes these families through its Anthropic-compatible
# /messages route. Its other listed models use /chat/completions.
OPENCODE_MESSAGES_PREFIXES = ("minimax-", "qwen")


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


def fetch_openai_models(api_key: str) -> list[str]:
    """Return direct OpenAI text-generation model identifiers."""
    response = SESSION.get(
        f"{OPENAI_API_URL}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list OpenAI models ({response.status_code}).")
    excluded_fragments = (
        "audio",
        "embedding",
        "image",
        "moderation",
        "realtime",
        "search",
        "transcribe",
        "tts",
    )
    models = {
        item.get("id", "")
        for item in response.json().get("data", [])
        if item.get("id", "").startswith(("gpt-", "o1", "o3", "o4"))
        and not any(fragment in item.get("id", "").lower() for fragment in excluded_fragments)
    }
    if not models:
        raise RuntimeError("No OpenAI text-generation models are available to this API key.")
    preferred = ["gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4.1-mini"]
    return [model for model in preferred if model in models] + sorted(models - set(preferred))


def validate_openai(api_key: str) -> None:
    """Validate a direct OpenAI key by listing its available models."""
    fetch_openai_models(api_key)


def fetch_anthropic_models(api_key: str) -> list[str]:
    """Return direct Anthropic Claude model identifiers, newest first."""
    response = SESSION.get(
        f"{ANTHROPIC_API_URL}/models",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        params={"limit": 1000},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list Anthropic models ({response.status_code}).")
    models = [
        item.get("id", "")
        for item in response.json().get("data", [])
        if item.get("id", "").startswith("claude-")
    ]
    if not models:
        raise RuntimeError("No Anthropic Claude models are available to this API key.")
    return models


def validate_anthropic(api_key: str) -> None:
    """Validate a direct Anthropic key by listing its available models."""
    fetch_anthropic_models(api_key)


def fetch_opencode_models(api_key: str) -> list[str]:
    """Return the models currently advertised by OpenCode Go."""
    response = SESSION.get(
        f"{OPENCODE_API_URL}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Could not list OpenCode Go models ({response.status_code}).")
    models = sorted(
        item.get("id", "")
        for item in response.json().get("data", [])
        if item.get("id")
    )
    if not models:
        raise RuntimeError("No OpenCode Go generation models are currently advertised.")
    preferred = ["deepseek-v4-flash", "mimo-v2.5", "kimi-k2.7-code"]
    return [model for model in preferred if model in models] + [
        model for model in models if model not in preferred
    ]


def _opencode_uses_messages(model_id: str) -> bool:
    """Return whether OpenCode Go serves a model through /messages."""
    return model_id.startswith(OPENCODE_MESSAGES_PREFIXES)


def validate_opencode(api_key: str, model_id: str) -> None:
    """Validate an OpenCode Go key and selected model with a minimal request."""
    if _opencode_uses_messages(model_id):
        response = SESSION.post(
            f"{OPENCODE_API_URL}/messages",
            json={
                "model": model_id,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "Reply with a left brace."}],
            },
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    else:
        response = SESSION.post(
            f"{OPENCODE_API_URL}/chat/completions",
            json={
                "model": model_id,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "Reply with a left brace."}],
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenCode Go key/model validation failed ({response.status_code}): "
            f"{response.text[:300]}"
        )


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


def _call_openai(system: str, user: str) -> str:
    """Generate a JSON scene plan through the direct OpenAI API."""
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_output_tokens": 8192,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "vnforge_scene_plan",
                "strict": True,
                "schema": ScenePlan.model_json_schema(),
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    response = SESSION.post(
        f"{OPENAI_API_URL}/responses",
        json=payload,
        headers=headers,
        timeout=120,
    )
    if response.status_code == 400 and any(
        term in response.text.lower() for term in ("format", "json_schema")
    ):
        payload.pop("text")
        response = SESSION.post(
            f"{OPENAI_API_URL}/responses",
            json=payload,
            headers=headers,
            timeout=120,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenAI generation failed ({response.status_code}): {response.text[:500]}"
        )
    body = response.json()
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    return "".join(
        content.get("text", "")
        for output in body.get("output", [])
        for content in output.get("content", [])
        if content.get("type") == "output_text"
    )


def _call_anthropic(system: str, user: str) -> str:
    """Generate a structured scene plan through the direct Anthropic API."""
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 8192,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": ScenePlan.model_json_schema(),
            }
        },
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    response = SESSION.post(
        f"{ANTHROPIC_API_URL}/messages",
        json=payload,
        headers=headers,
        timeout=120,
    )
    if response.status_code == 400 and any(
        term in response.text.lower() for term in ("output_config", "structured output")
    ):
        payload.pop("output_config")
        response = SESSION.post(
            f"{ANTHROPIC_API_URL}/messages",
            json=payload,
            headers=headers,
            timeout=120,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"Anthropic generation failed ({response.status_code}): {response.text[:500]}"
        )
    return "".join(
        block.get("text", "")
        for block in response.json().get("content", [])
        if block.get("type") == "text"
    )


def _call_opencode(system: str, user: str) -> str:
    """Generate a JSON scene plan through the OpenCode Go subscription."""
    if _opencode_uses_messages(OPENCODE_MODEL):
        payload = {
            "model": OPENCODE_MODEL,
            "max_tokens": 8192,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        response = SESSION.post(
            f"{OPENCODE_API_URL}/messages",
            json=payload,
            headers={
                "x-api-key": OPENCODE_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"OpenCode Go generation failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
        return "".join(
            block.get("text", "")
            for block in response.json().get("content", [])
            if block.get("type") == "text"
        )

    payload = {
        "model": OPENCODE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENCODE_API_KEY}",
        "Content-Type": "application/json",
    }
    response = SESSION.post(
        f"{OPENCODE_API_URL}/chat/completions",
        json=payload,
        headers=headers,
        timeout=120,
    )
    if response.status_code == 400 and "response_format" in response.text:
        payload.pop("response_format")
        response = SESSION.post(
            f"{OPENCODE_API_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=120,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenCode Go generation failed ({response.status_code}): {response.text[:500]}"
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
    if PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("OpenAI credentials are not configured.")
        return _call_openai(system, user)
    if PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("Anthropic credentials are not configured.")
        return _call_anthropic(system, user)
    if PROVIDER == "opencode":
        if not OPENCODE_API_KEY:
            raise RuntimeError("OpenCode Go credentials are not configured.")
        return _call_opencode(system, user)
    raise RuntimeError(f"Unknown or missing provider '{PROVIDER}'. Configure VNForge first.")


def _extract_json(raw_text: str | None) -> dict[str, Any]:
    """Extract the first complete JSON object from a provider response."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        value_type = type(raw_text).__name__
        raise ValueError(f"Provider returned an empty or null response body (got '{value_type}').")
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
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(str(error)) from error
            if attempt >= max_repairs:
                raise ValueError(
                    f"Provider returned an invalid scene plan after {attempt + 1} attempts: {error}"
                ) from error
            repair_system, repair_user = build_repair_prompt(raw, str(error))
            raw = _call_provider(repair_system, repair_user)
    raise RuntimeError("Scene-plan validation ended unexpectedly.")
