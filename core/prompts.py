# core/prompts.py
# Builds the prompt sent to the AI model.
# The quality of the model's output depends on this prompt.

from typing import Literal

# Maps genre names to a short tone instruction injected into the prompt.
# Falls back to a neutral instruction for unrecognised genres.
GENRE_HINTS = {
    "romance":       "Focus on emotional tension, inner monologue, and meaningful character choices.",
    "mystery":       "Build suspense, plant subtle clues, and keep the reader guessing.",
    "fantasy":       "Use vivid world-building details, magical elements, and high stakes.",
    "horror":        "Create dread through atmosphere, pacing, and unsettling sensory details.",
    "slice_of_life": "Keep it grounded, character-driven, and emotionally honest.",
}

# Maps branching depth to a short instruction about how many choices to produce.
# shallow -> 2 minor choices (low impact).
# medium  -> 3 choices, affects variables (medium impact).
# deep    -> 4+ choices, major route splits (major plot impact).
BRANCHING_DEPTH_HINTS = {
    "shallow": "Provide 2 simple choices with minor consequences.",
    "medium":  "Provide 3 meaningful choices that affect variables or story direction.",
    "deep":    "Provide 4+ choices with significant variable changes and distinct routes.",
}


def build_compile_prompt(
    scene_text: str,
    genre: str,
    branching_depth: Literal["shallow", "medium", "deep"],
) -> str:
    """Assemble the full prompt string sent to the AI model.

    Args:
        scene_text: The raw prose scene pasted in by the user.
        genre: Selected genre matched against GENRE_HINTS.
        branching_depth: One of "shallow", "medium", or "deep".

    Returns:
        A single string — the complete prompt ready to be passed to the model.
    """
    genre_hint = GENRE_HINTS.get(genre.lower(), "Write in a neutral, engaging tone.")
    branching_hint = BRANCHING_DEPTH_HINTS.get(
        branching_depth.lower(),
        BRANCHING_DEPTH_HINTS["medium"],
    )

    return f"""You are VNForge, an expert visual novel script compiler.

Your job is to convert a plain prose scene into a structured visual novel output.

## Scene genre: {genre}
{genre_hint}

## Branching depth: {branching_depth}
{branching_hint}

---

## Input scene:
{scene_text.strip()}

---

## Your task:
Convert the scene above into a structured JSON object. Follow the schema exactly.

Rules:
- Output ONLY valid JSON. No explanation, no markdown, no code fences.
- All string values must be plain text (no Markdown inside JSON strings).
- `renpy_script` must be valid Ren'Py syntax using `label`, `show`, `play music`, and dialogue lines.
- `choices` must reflect meaningful player decisions from the scene.
- `variable_change` uses the format "flag_name = value", e.g. "trust_alex = True".
- `route_label` is a valid Ren'Py label name (snake_case, no spaces).
- `asset_cues` must include backgrounds, character sprites, and music/sound as needed.
- `production_notes` are short developer reminders (animation, pacing, voice acting, etc.).

## Required JSON schema:
{{
  "scene_title": "string",
  "scene_summary": "string (1-2 sentences)",
  "renpy_script": "string (full Ren'Py scene script)",
  "choices": [
    {{
      "choice_text": "string (what the player sees)",
      "variable_change": "string (e.g. trust_alex = True)",
      "route_label": "string (snake_case label)",
      "consequence": "string (brief outcome description)"
    }}
  ],
  "asset_cues": [
    {{
      "cue_type": "background | character | music | sound",
      "name": "string (asset identifier)",
      "description": "string (visual/audio description for the artist)"
    }}
  ],
  "production_notes": ["string", "string"]
}}

Now output the JSON:"""


def build_continue_prompt(
    scene_text: str,
    genre: str,
    branching_depth: Literal["shallow", "medium", "deep"],
    prev_title: str,
    prev_summary: str,
    prev_route_label: str,
    prev_consequence: str,
) -> str:
    """Assemble a continuation prompt that gives the model context from the previous scene.

    Args:
        scene_text: The new prose scene to compile.
        genre: Selected genre matched against GENRE_HINTS.
        branching_depth: One of "shallow", "medium", or "deep".
        prev_title: Title of the previous compiled scene.
        prev_summary: Summary of the previous compiled scene.
        prev_route_label: The route label the writer chose to continue from.
        prev_consequence: The consequence text for that route choice.

    Returns:
        A single prompt string ready to be passed to the model.
    """
    genre_hint = GENRE_HINTS.get(genre.lower(), "Write in a neutral, engaging tone.")
    branching_hint = BRANCHING_DEPTH_HINTS.get(
        branching_depth.lower(),
        BRANCHING_DEPTH_HINTS["medium"],
    )

    return f"""You are VNForge, an expert visual novel script compiler.

Your job is to convert a plain prose scene into a structured visual novel output.
This scene is a direct continuation of a previous scene — maintain story continuity.

## Previous scene context:
- Title: {prev_title}
- Summary: {prev_summary}
- Player chose route: {prev_route_label}
- Consequence of that choice: {prev_consequence}

## Scene genre: {genre}
{genre_hint}

## Branching depth: {branching_depth}
{branching_hint}

---

## New scene input:
{scene_text.strip()}

---

## Your task:
Convert the new scene above into a structured JSON object that continues naturally
from the previous scene and the player's chosen route. Follow the schema exactly.

Rules:
- Output ONLY valid JSON. No explanation, no markdown, no code fences.
- All string values must be plain text (no Markdown inside JSON strings).
- `renpy_script` must be valid Ren'Py syntax using `label`, `show`, `play music`, and dialogue lines.
- `choices` must reflect meaningful player decisions from the scene.
- `variable_change` uses the format "flag_name = value", e.g. "trust_alex = True".
- `route_label` is a valid Ren'Py label name (snake_case, no spaces).
- `asset_cues` must include backgrounds, character sprites, and music/sound as needed.
- `production_notes` are short developer reminders (animation, pacing, voice acting, etc.).

## Required JSON schema:
{{
  "scene_title": "string",
  "scene_summary": "string (1-2 sentences)",
  "renpy_script": "string (full Ren'Py scene script)",
  "choices": [
    {{
      "choice_text": "string (what the player sees)",
      "variable_change": "string (e.g. trust_alex = True)",
      "route_label": "string (snake_case label)",
      "consequence": "string (brief outcome description)"
    }}
  ],
  "asset_cues": [
    {{
      "cue_type": "background | character | music | sound",
      "name": "string (asset identifier)",
      "description": "string (visual/audio description for the artist)"
    }}
  ],
  "production_notes": ["string", "string"]
}}

Now output the JSON:"""
