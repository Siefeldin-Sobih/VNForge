# VNForge Testing Notes

Tester log — verified behaviour, open defects, and how automated checks relate to them.

**Date:** 2026-07-22

---

## Summary

Core product path is confirmed: prose in → playable Ren'Py project out. Lint (v8.5.3), playable export, scene chaining, and Story Map all work in manual verification.

The implementation review fixed **BUG-01** through **BUG-06** and added offline regression coverage. **BUG-07** now has explicit rollback configuration and needs one final manual Ren'Py playtest. The complete offline suite passes with 38 tests.

Earlier the same day on branch `fix/model-and-parsing`: Gemini model configurability and defaults, hardened JSON parsing/repair, schema defaults for missing optional fields, and clearer error UX (readable messages; app returns to ready state without restart).

---

## Verified Working

*Verified 2026-07-22.*

| Area | Result |
|------|--------|
| **Ren'Py lint (v8.5.3)** | Passes on VNForge-exported `.rpy`: zero syntax, label, or structural errors. Only missing-asset warnings (expected — VNForge emits asset cues, not assets). Lint stats: 10 dialogue blocks, 129 words, 1 menu, 6 image references. |
| **Playable Project export** | Complete runnable project (`script.rpy`, `options.rpy`, `audio/`, `images/`), includes `label start:`, ships placeholder assets, launches and plays in Ren'Py with no manual wiring. Core claim confirmed: prose in → playable VN out. |
| **Scene chaining** | "Continue from" correctly links scene 2 to a named route of scene 1; generated scene 2 retained context (background continuity, caretaker sprite state carried over). |
| **Story Map** | Renders the scene tree with routes and branch targets. |

---

## Defects Reviewed

### BUG-01 — Boolean flags default to True

**Status:** Fixed. Generated state variables now receive neutral defaults; boolean action flags start `False` while the selected choice still assigns `True`.

**Severity:** High — breaks branch logic.

Every generated `default <flag>` statement initializes `True` (observed: `asked_teacup`, `examined_latch`, `know_debtor`, `latch_examined` — 4/4). Flags meaning "the player has done X" must default `False`, or every conditional gated on player action passes before the player acts.

**Reproduced by pytest.**

---

### BUG-02 — Validator false positive on valid chain links

**Status:** Fixed. Per-scene validation now receives all known project scene labels.

**Severity:** High — headline feature.

Scene 3's Notes & Validation showed:

```text
[ERROR] Jump target 'scene_scene04_room306_convo' is not defined.
```

Scene 4 exists and is chained from `scene03` / `ask_teacup`. Per the codebase, compile-time checks are per-scene "with awareness of other scene labels for jumps" — that awareness is not resolving.

---

### BUG-03 — Cross-scene flag rename not detected

**Status:** Fixed. Project analysis reports `variable_name_drift` for reordered and common suffix variants across scenes.

**Severity:** High — false negative.

`scene03` declared `examined_latch`; `scene04` declared `latch_examined` — same concept, renamed. Story Map reported "No cross-scene continuity problems detected." This is exactly the bug class the checker exists to catch. Project-wide analysis lives in `analyze_project`.

---

### BUG-04 — Empty/None model response crashes compile

**Status:** Fixed. Empty and null provider bodies now raise a handled `ValueError` without attempting an impossible repair request.

**Severity:** High (crash).

Empty/None model response crashes compile with:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

at `core/model_client.py:306` in `_extract_json` (`text = raw_text.strip()`). Triggered live by `cohere/north-mini-code:free` returning empty. Should raise a clean `ValueError`.

**Reproduced by pytest.**

---

### BUG-05 — Unstable scene IDs/labels across compiles

**Status:** Fixed. Recompilation preserves the stored scene ID, and Scene Plan edits cannot rename an existing scene behind inbound links.

Scene IDs/labels are model-generated and not stable across compiles of identical input (e.g. `scene03_room306` → `the_third_floor_hallway`). Risk for chained projects where scene 2 jumps to scene 1's label.

---

### BUG-06 — Long compile latency with no progress feedback

**Status:** Fixed. The workspace displays elapsed provider wait time and the estimated input-token count during compilation.

UI gives no indication work is in progress during long compiles. Demo risk: a long silent wait reads as a crash.

---

## BUG-07 — No rollback / choice re-selection in exported Playable Project

**Status:** Code safeguard added; manual Ren'Py retest required. Export now sets `config.rollback_enabled = True`, and BUG-01 no longer pre-initializes action flags to their selected value.

**Severity:** Medium
**Found:** 2026-07-22, Playable Project export running in Ren'Py 8.5.3

**Observed:** After reaching the choice menu and selecting an option, there is
no way to go back and pick the other branch. The player must restart the game
to see the alternate route.

**Expected:** Ren'Py supports rollback by default — scroll wheel up over the
text, or right-click → History — allowing a player to rewind and re-choose.
This is standard visual-novel behaviour that players expect.

**Likely causes to investigate:**
- `options.rpy` in the generated project may have rollback disabled
- Generated `$ flag = True` statements may block rollback; Ren'Py can only
  reliably roll back variable changes declared via `default`

**Impact:** Beyond player expectation, this is a demo problem — showing both
branches requires a full restart rather than a quick rewind.

**Owner:** Person 1 (exporter / renderer)

---

## NOT A BUG — Missing images and audio in exported project

**Observed:** Exported projects show placeholder rectangles instead of
backgrounds and sprites; Ren'Py lint reports files such as
`images/char_asha.svg` and `audio/music_tense_low.wav` as not loadable.

**Status:** Working as designed. VNForge generates asset *cues* — a production
shopping list describing what an artist needs to create — not the assets
themselves. Ren'Py's placeholder rendering is the expected result.

**SUGGESTION (demo quality):** Ship 3–4 generic placeholder assets with the
Playable Project export (a silhouette character sprite, a neutral room
background, a short ambient audio loop). Exported demos currently render as
empty coloured rectangles, which undersells the output in a video or live
walkthrough. Low effort, high visual payoff.

## Test Infrastructure

| Item | Detail |
|------|--------|
| Suite | `pytest` under `tests/` |
| Live models | None — fake provider / fixtures only |
| Runtime | ~1s |
| Current state | 38 passing; BUG-01 through BUG-06 have regression coverage |

**Known gaps** (cannot be tested this way):

- Live-model behaviour
- UI / tab rendering
- Story quality
- Ren'Py SDK lint (requires local install)

---

## Environment Notes

- **Gemini free tier:** 20 requests/day — real-model testing is quota-bound; use the fake provider for UI and structural work.
- **OpenRouter free model IDs rot** (e.g. `meta-llama/llama-3.2-3b-instruct:free` went paid); `openrouter/free` is a router alias that self-heals.
- **Ren'Py 8.5.3** installed locally for lint and playtest verification.
