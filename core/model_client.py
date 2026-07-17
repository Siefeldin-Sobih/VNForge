# core/model_client.py
# Handles all communication between VNForge and IBM watsonx.ai.
# Called only from compiler.py.

import os
import json
import requests
from dotenv import load_dotenv

from core.schemas import VNForgeResult

load_dotenv()

WATSONX_API_URL = "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation?version=2023-05-29"
WATSONX_API_KEY = os.getenv("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_MODEL_ID = "ibm/granite-3-1-8b-instruct"


def _get_watsonx_token(api_key: str) -> str:
    """Exchange an IBM API key for a short-lived IAM Bearer token."""
    response = requests.post(
        "https://iam.cloud.ibm.com/identity/token",
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


def _extract_json(raw_text: str) -> dict:
    """Extract and parse a JSON object from a raw model response string.

    Handles markdown code fences (```json ... ```) that some models emit.
    Raises ValueError if no valid JSON object can be found.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]

    text = text.strip()

    start = text.find("{")
    end = text.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError("No JSON object found in model response.")

    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}")


def call_model(prompt: str) -> VNForgeResult:
    """Send a prompt to watsonx.ai and return a validated VNForgeResult.

    Raises RuntimeError if the API call or JSON validation fails.
    """
    if not all([WATSONX_API_KEY, WATSONX_PROJECT_ID]):
        raise RuntimeError("WATSONX_API_KEY and WATSONX_PROJECT_ID must be set in .env")

    raw_response = _call_watsonx(prompt)
    data = _extract_json(raw_response)
    return VNForgeResult(**data)
