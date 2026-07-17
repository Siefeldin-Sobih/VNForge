# core/compiler.py
# The desktop app imports and calls only compile_scene().
#
# Pipeline:
#   1. build_compile_prompt()  ->  constructs the prompt string   [prompts.py]
#   2. call_model(prompt)      ->  sends prompt, gets JSON back   [model_client.py]
#   3. JSON parsed + validated ->  VNForgeResult returned

from core.prompts import build_compile_prompt


def compile_scene(
    scene_text: str,
    genre: str,
    branching_depth: str,
) -> "VNForgeResult":
    """Compile a prose scene into a structured VNForgeResult.

    Args:
        scene_text: Raw prose pasted by the user in the desktop app.
        genre: Genre string selected from the UI dropdown (e.g. "romance", "mystery").
        branching_depth: One of "shallow", "medium", or "deep".

    Returns:
        A fully validated VNForgeResult ready for the UI to display.
    """
    # model_client is imported lazily so the module loads even when the .env
    # is not yet configured, avoids a crash on startup before keys are set.
    from core.model_client import call_model

    prompt = build_compile_prompt(scene_text, genre, branching_depth)
    return call_model(prompt)
