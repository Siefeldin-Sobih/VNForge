# core/model_client.py
# Handles all communication between VNForge and the active AI provider.
# Called only from compiler.py.
#
# Supported providers (set via PROVIDER in .env):
#   "watsonx"   — IBM watsonx.ai, Granite 3.1 8B Instruct (free on Lite plan)
#   "gemini"    — Google Gemini 2.5 Flash (free tier, no card needed)
#   "openrouter" — OpenRouter.ai, routes to many models (free + paid tiers)

import os
import json
import requests
from json_repair import repair_json
from dotenv import load_dotenv

from core.schemas import VNForgeResult

load_dotenv()

PROVIDER = os.getenv("PROVIDER", "")

# IBM watsonx
WATSONX_API_URL = "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation?version=2023-05-29"
WATSONX_IAM_URL = "https://iam.cloud.ibm.com/identity/token"
WATSONX_API_KEY = os.getenv("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_MODEL_ID = "ibm/granite-3-1-8b-instruct"

# Google Gemini
GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# OpenRouter
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")


# ---------------------------------------------------------------------------
# Validation — called by the setup window to test credentials before saving
# ---------------------------------------------------------------------------

def validate_watsonx(api_key: str, project_id: str) -> None:
    """Test IBM watsonx credentials by exchanging the API key for an IAM token.

    Raises RuntimeError with a human-readable message if validation fails.
    """
    response = requests.post(
        WATSONX_IAM_URL,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Invalid IBM API key (status {response.status_code}).")

    # Project ID can't be validated without a real inference call, so we just
    # check it looks non-empty — the first compile will surface any ID errors.
    if not project_id.strip():
        raise RuntimeError("Project ID cannot be empty.")


def validate_gemini(api_key: str) -> None:
    """Test a Gemini API key with a minimal models list request.

    Raises RuntimeError with a human-readable message if validation fails.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    response = requests.get(url, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"Invalid Gemini API key (status {response.status_code}).")


def validate_openrouter(api_key: str) -> None:
    """Test an OpenRouter API key by fetching the account credits endpoint.

    Raises RuntimeError with a human-readable message if validation fails.
    """
    response = requests.get(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Invalid OpenRouter API key (status {response.status_code}).")


# ---------------------------------------------------------------------------
# Internal callers
# ---------------------------------------------------------------------------

def _get_watsonx_token(api_key: str) -> str:
    """Exchange an IBM API key for a short-lived IAM Bearer token."""
    response = requests.post(
        WATSONX_IAM_URL,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"IBM IAM token error {response.status_code}: {response.text}")
    return response.json()["access_token"]


def _call_watsonx(prompt: str) -> str:
    """Send a prompt to IBM watsonx.ai and return the raw generated text."""
    token = _get_watsonx_token(WATSONX_API_KEY)
    payload = {
        "model_id": WATSONX_MODEL_ID,
        "input": prompt,
        "project_id": WATSONX_PROJECT_ID,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": 2048,
            "temperature": 0,
        },
    }
    response = requests.post(
        WATSONX_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"watsonx.ai error {response.status_code}: {response.text}")
    return response.json()["results"][0]["generated_text"]


def _call_gemini(prompt: str) -> str:
    """Send a prompt to Google Gemini 2.5 Flash and return the raw generated text."""
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
        },
    }
    response = requests.post(url, json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Gemini error {response.status_code}: {response.text}")
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(prompt: str) -> str:
    """Send a prompt to OpenRouter and return the raw generated text."""
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 2048,
    }
    response = requests.post(
        OPENROUTER_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vnforge.app",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text}")
    return response.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(raw_text: str) -> dict:
    """Extract and parse a JSON object from a raw model response string.

    Three-layer approach:
      a) Strip markdown code fences and any surrounding prose, then isolate
         the outermost {...} block.
      b) Try a strict json.loads(); if that fails, try json_repair which
         tolerates minor issues like missing/trailing commas.
      c) If both fail, raise ValueError so call_model can trigger a retry.
    """
    text = raw_text.strip()

    # Layer (a): strip markdown fences —————————————————————————————————————
    # Remove opening fence (```json, ``` etc.) and closing fence.
    if text.startswith("```"):
        # Drop the first line (the fence opener) then strip a trailing fence.
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip().rsplit("```", 1)[0]
    text = text.strip()

    # Isolate the outermost { … } block, skipping any preamble prose.
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in model response.")
    candidate = text[start:end]

    # Layer (b): strict parse, then tolerant repair ————————————————————————
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    repaired = repair_json(candidate, return_objects=True)
    if isinstance(repaired, dict) and repaired:
        return repaired

    raise ValueError(
        f"JSON parse failed after repair attempt. "
        f"First 200 chars of candidate: {candidate[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _raw_call(prompt: str) -> str:
    """Dispatch to the active provider and return the raw text string.

    Separated from call_model so the retry logic can call it a second time
    without duplicating the provider-selection block.
    """
    if PROVIDER == "watsonx":
        if not all([WATSONX_API_KEY, WATSONX_PROJECT_ID]):
            raise RuntimeError("WATSONX_API_KEY and WATSONX_PROJECT_ID must be set in .env")
        return _call_watsonx(prompt)

    if PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY must be set in .env")
        return _call_gemini(prompt)

    if PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY must be set in .env")
        return _call_openrouter(prompt)

    raise RuntimeError(
        f"Unknown or missing PROVIDER '{PROVIDER}' in .env. "
        "Expected: watsonx, gemini, or openrouter."
    )


def call_model(prompt: str) -> VNForgeResult:
    """Route the prompt to the active provider and return a validated VNForgeResult.

    The active provider is read from PROVIDER in .env.
    On a JSON extraction failure the model is called once more before the
    error is surfaced to the caller.
    Raises RuntimeError if the provider is unconfigured or the API call fails.
    """
    raw = _raw_call(prompt)

    # Layer (c): one retry on JSON extraction failure ————————————————————————
    try:
        return VNForgeResult(**_extract_json(raw))
    except (ValueError, TypeError):
        pass

    # Second attempt — ask the model again; new response may be well-formed.
    raw = _raw_call(prompt)
    return VNForgeResult(**_extract_json(raw))
