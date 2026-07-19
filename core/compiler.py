# core/compiler.py
# The desktop app imports and calls compile_scene() and continue_scene().
#
# Pipeline:
#   1. build_*_prompt()   ->  constructs the prompt string   [prompts.py]
#   2. call_model(prompt) ->  sends prompt, gets JSON back   [model_client.py]
#   3. JSON parsed + validated ->  VNForgeResult returned

from core.prompts import build_compile_prompt, build_continue_prompt


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
    from core.model_client import call_model

    prompt = build_compile_prompt(scene_text, genre, branching_depth)
    return call_model(prompt)


def continue_scene(
    scene_text: str,
    genre: str,
    branching_depth: str,
    prev_title: str,
    prev_summary: str,
    prev_route_label: str,
    prev_consequence: str,
) -> "VNForgeResult":
    """Compile a scene as a continuation of a previously compiled scene.

    Args:
        scene_text: New prose pasted by the user.
        genre: Genre string selected from the UI dropdown.
        branching_depth: One of "shallow", "medium", or "deep".
        prev_title: Title of the previous compiled scene.
        prev_summary: Summary of the previous compiled scene.
        prev_route_label: The route label the writer is continuing from.
        prev_consequence: The consequence text for that route.

    Returns:
        A fully validated VNForgeResult ready for the UI to display.
    """
    from core.model_client import call_model

    prompt = build_continue_prompt(
        scene_text, genre, branching_depth,
        prev_title, prev_summary, prev_route_label, prev_consequence,
    )
    return call_model(prompt)
