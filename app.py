# app.py
# Main desktop window. Owns the layout, user input, and output display.
# Calls compile_scene() from core/compiler.py and exporters from core/exporters.py.
#
# Also contains SetupWindow, shown on first launch when .env is missing or incomplete.
# SetupWindow writes .env on successful credential validation, then opens VNForgeApp.

import sys
import os
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk
from core.compiler import compile_scene, continue_scene
from core.exporters import export_rpy, export_asset_list, export_markdown_report

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

GENRES = ["Romance", "Mystery", "Thriller", "Fantasy", "Sci-Fi", "Slice of Life"]
BRANCHING_DEPTHS = ["Shallow (2 choices)", "Medium (3–4 choices)", "Deep (5+ choices)"]

_GENRE_MAP = {g: g.lower().replace("-", "_").replace(" ", "_") for g in GENRES}
_DEPTH_MAP = {
    "Shallow (2 choices)":  "shallow",
    "Medium (3–4 choices)": "medium",
    "Deep (5+ choices)":    "deep",
}

_ENV_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_LOG_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vnforge_errors.log")

logging.basicConfig(
    filename=_LOG_PATH,
    level=logging.ERROR,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("vnforge")


def _classify_error(raw: str) -> str:
    """Map a raw RuntimeError message to a short, user-friendly string.

    The full error is logged to vnforge_errors.log by the caller.
    """
    low = raw.lower()
    if "429" in raw:
        return (
            "Rate limit reached. Wait a minute or switch provider "
            "(Change Provider button)."
        )
    if any(k in low for k in ("401", "403", "invalid", "api key", "key rejected",
                               "api_key", "permission denied")):
        return "API key rejected. Check your provider settings."
    if any(k in low for k in ("timeout", "timed out", "connection", "network")):
        return "Network error. Check your internet connection and try again."
    if "no json" in low or "json parse" in low:
        return "Model returned an unexpected response. Try compiling again."
    # Unknown — show a trimmed first line so the status bar stays readable.
    first_line = raw.splitlines()[0]
    return first_line[:120] + ("…" if len(first_line) > 120 else "")

# Provider metadata shown in the picker screen.
_PROVIDERS = [
    {
        "key":         "watsonx",
        "label":       "IBM watsonx.ai",
        "description": "Free on IBM Cloud Lite plan.\nRequires API Key + Project ID.",
        "link":        "https://cloud.ibm.com",
        "fields":      ["API Key", "Project ID"],
        "secret":      [True, False],
    },
    {
        "key":         "gemini",
        "label":       "Google Gemini",
        "description": "Free tier — no card needed.\n1 500 requests/day.",
        "link":        "https://aistudio.google.com/app/apikey",
        "fields":      ["API Key"],
        "secret":      [True],
    },
    {
        "key":         "openrouter",
        "label":       "OpenRouter",
        "description": "Access to many models.\nFree and paid tiers available.",
        "link":        "https://openrouter.ai/keys",
        "fields":      ["API Key"],
        "secret":      [True],
    },
]


# ---------------------------------------------------------------------------
# Setup window — shown on first launch
# ---------------------------------------------------------------------------

class SetupWindow(ctk.CTk):
    """First-run setup: lets the user pick a provider, enter credentials,
    validate them live, then writes .env and opens the main app."""

    def __init__(self):
        super().__init__()
        self.title("VNForge — Setup")
        self.geometry("520x460")
        self.resizable(False, False)
        self._provider = None
        self._show_picker()

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def _show_picker(self):
        """Screen 1 — choose a provider."""
        self._clear()
        self.geometry("520x460")

        ctk.CTkLabel(self, text="VNForge",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color="#7c5cd8").pack(pady=(28, 4))
        ctk.CTkLabel(self, text="Choose your AI provider to get started.",
                     font=ctk.CTkFont(size=13),
                     text_color="#8b8fa8").pack(pady=(0, 20))

        for p in _PROVIDERS:
            card = ctk.CTkFrame(self, corner_radius=10, cursor="hand2")
            card.pack(fill="x", padx=32, pady=6)

            ctk.CTkLabel(card, text=p["label"],
                         font=ctk.CTkFont(size=14, weight="bold"),
                         anchor="w").pack(fill="x", padx=14, pady=(10, 2))
            ctk.CTkLabel(card, text=p["description"],
                         font=ctk.CTkFont(size=11),
                         text_color="#8b8fa8",
                         justify="left",
                         anchor="w").pack(fill="x", padx=14, pady=(0, 10))

            provider_key = p["key"]
            card.bind("<Button-1>", lambda _e, k=provider_key: self._show_credentials(k))
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda _e, k=provider_key: self._show_credentials(k))

    # Fallback free models shown if the live fetch fails.
    _OPENROUTER_FALLBACK_MODELS = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "qwen/qwen3-coder:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
    ]

    def _show_credentials(self, provider_key: str):
        """Screen 2 — enter and validate credentials for the chosen provider."""
        self._clear()
        self._provider = next(p for p in _PROVIDERS if p["key"] == provider_key)
        self._model_var = None
        self._model_menu = None

        # OpenRouter gets an extra model row, so it needs a taller window.
        self.geometry("520x480" if provider_key == "openrouter" else "520x380")

        ctk.CTkLabel(self, text=self._provider["label"],
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#7c5cd8").pack(pady=(24, 4))

        link = ctk.CTkLabel(self,
                            text=f"Get your key at: {self._provider['link']}",
                            font=ctk.CTkFont(size=11),
                            text_color="#3b82d4",
                            cursor="hand2")
        link.pack(pady=(0, 16))
        link.bind("<Button-1>", lambda _e: self._open_link(self._provider["link"]))

        self._entries = []
        for i, field_label in enumerate(self._provider["fields"]):
            ctk.CTkLabel(self, text=field_label,
                         font=ctk.CTkFont(size=12),
                         anchor="w").pack(fill="x", padx=40, pady=(4, 0))
            show = "" if not self._provider["secret"][i] else "*"
            entry = ctk.CTkEntry(self, show=show, width=440, height=36)
            entry.pack(padx=40, pady=(2, 6))
            self._entries.append(entry)

        if provider_key == "openrouter":
            self._build_model_row()

        self._status = ctk.CTkLabel(self, text="",
                                    font=ctk.CTkFont(size=11),
                                    text_color="#8b8fa8")
        self._status.pack(pady=(4, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(10, 0))

        ctk.CTkButton(btn_row, text="← Back",
                      width=100,
                      fg_color="transparent",
                      border_width=1,
                      text_color="#8b8fa8",
                      hover_color="#2a2b3d",
                      command=self._show_picker).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_row, text="Validate & Save",
                      width=160,
                      fg_color="#7c5cd8",
                      hover_color="#5a3fb5",
                      command=self._on_validate).pack(side="left")

    def _build_model_row(self):
        """Build the model label, dropdown, and refresh button for OpenRouter."""
        model_label_row = ctk.CTkFrame(self, fg_color="transparent")
        model_label_row.pack(fill="x", padx=40, pady=(8, 0))
        model_label_row.columnconfigure(0, weight=1)

        ctk.CTkLabel(model_label_row, text="Model",
                     font=ctk.CTkFont(size=12),
                     anchor="w").pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            model_label_row, text="↻ Load live models",
            width=130, height=22,
            fg_color="transparent",
            border_width=1,
            border_color="#3b3d52",
            text_color="#8b8fa8",
            hover_color="#2a2b3d",
            font=ctk.CTkFont(size=11),
            command=self._fetch_openrouter_models,
        )
        self._refresh_btn.pack(side="right")

        self._model_var = ctk.StringVar(value=self._OPENROUTER_FALLBACK_MODELS[0])
        self._model_menu = ctk.CTkOptionMenu(
            self,
            values=self._OPENROUTER_FALLBACK_MODELS,
            variable=self._model_var,
            width=440,
        )
        self._model_menu.pack(padx=40, pady=(4, 0))

    def _fetch_openrouter_models(self):
        """Fetch live free models from OpenRouter using the key the user entered."""
        api_key = self._entries[0].get().strip() if self._entries else ""
        if not api_key:
            self._set_status("Enter your API key first, then load models.", "#e3a008")
            return

        self._refresh_btn.configure(state="disabled", text="Loading…")
        self._set_status("", "#8b8fa8")

        def fetch():
            try:
                import requests as req
                r = req.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=15,
                )
                r.raise_for_status()
                models = sorted(
                    m["id"] for m in r.json().get("data", [])
                    if ":free" in m["id"]
                )
                if not models:
                    raise ValueError("No free models returned.")
                self.after(0, lambda: self._update_model_menu(models))
            except Exception as ex:
                msg = str(ex)
                self.after(0, lambda: self._on_fetch_error(msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _update_model_menu(self, models: list):
        """Populate the model dropdown with freshly fetched models."""
        self._model_var.set(models[0])
        self._model_menu.configure(values=models)
        self._refresh_btn.configure(state="normal", text="↻ Load live models")
        self._set_status(f"✓ {len(models)} free models loaded.", "#22c55e")

    def _on_fetch_error(self, message: str):
        self._refresh_btn.configure(state="normal", text="↻ Load live models")
        self._set_status(f"Could not load models — using defaults. ({message})", "#e3a008")

    def _on_validate(self):
        """Read entries, run validation in a thread, write .env on success."""
        values = [e.get().strip() for e in self._entries]

        if not all(values):
            self._set_status("All fields are required.", "#e3a008")
            return

        self._set_status("Validating…", "#8b8fa8")

        def run():
            try:
                self._validate(values)
                self.after(0, lambda: self._on_success(values))
            except Exception as ex:
                msg = str(ex)
                self.after(0, lambda: self._set_status(msg, "#ef4444"))

        threading.Thread(target=run, daemon=True).start()

    def _validate(self, values: list):
        """Call the appropriate validate_* function from model_client."""
        from core.model_client import validate_watsonx, validate_gemini, validate_openrouter

        key = self._provider["key"]
        if key == "watsonx":
            validate_watsonx(values[0], values[1])
        elif key == "gemini":
            validate_gemini(values[0])
        elif key == "openrouter":
            validate_openrouter(values[0])

    def _on_success(self, values: list):
        self._set_status("✓ Connected! Saving…", "#22c55e")
        self._write_env(values)
        self.after(800, self._launch_app)

    def _write_env(self, values: list):
        """Write .env with the validated credentials and selected provider."""
        key = self._provider["key"]
        lines = [f"PROVIDER={key}"]

        if key == "watsonx":
            lines += [f"WATSONX_API_KEY={values[0]}", f"WATSONX_PROJECT_ID={values[1]}"]
        elif key == "gemini":
            lines.append(f"GEMINI_API_KEY={values[0]}")
        elif key == "openrouter":
            lines.append(f"OPENROUTER_API_KEY={values[0]}")
            model = self._model_var.get() if self._model_var else "meta-llama/llama-3.3-70b-instruct:free"
            lines.append(f"OPENROUTER_MODEL={model}")

        with open(_ENV_PATH, "w") as f:
            f.write("\n".join(lines) + "\n")

    def _launch_app(self):
        self.destroy()
        # Reload env so the freshly written keys are visible to model_client.
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=True)

        # Re-import model_client so module-level os.getenv() calls pick up new values.
        import importlib
        import core.model_client as mc
        importlib.reload(mc)

        app = VNForgeApp()
        app.mainloop()

    def _set_status(self, msg: str, color: str):
        self._status.configure(text=msg, text_color=color)

    @staticmethod
    def _open_link(url: str):
        import webbrowser
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main app window
# ---------------------------------------------------------------------------

class VNForgeApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("VNForge Desktop")
        self.geometry("1200x760")
        self.minsize(900, 600)
        self._compiled_scene = None
        self._build_layout()

    def _build_layout(self):
        top = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color="#1a1b2e")
        top.pack(fill="x", side="top")
        top.pack_propagate(False)
        ctk.CTkLabel(top, text="VNForge",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#7c5cd8").pack(side="left", padx=16, pady=8)
        ctk.CTkLabel(top, text="Visual Novel Compiler",
                     font=ctk.CTkFont(size=13),
                     text_color="#8b8fa8").pack(side="left", pady=8)
        ctk.CTkButton(top, text="Change Provider",
                      width=130,
                      height=28,
                      fg_color="transparent",
                      border_width=1,
                      border_color="#3b3d52",
                      text_color="#8b8fa8",
                      hover_color="#2a2b3d",
                      font=ctk.CTkFont(size=11),
                      command=self._change_provider).pack(side="right", padx=16, pady=10)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        self._build_left_panel(body)
        self._build_right_panel(body)

    def _build_left_panel(self, parent):
        left = ctk.CTkFrame(parent, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Scene Input",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        self.prose_box = ctk.CTkTextbox(left, wrap="word",
                                        font=ctk.CTkFont(size=13),
                                        corner_radius=8)
        self.prose_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        self._set_placeholder()

        genre_row = ctk.CTkFrame(left, fg_color="transparent")
        genre_row.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        genre_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(genre_row, text="Genre", width=90,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.genre_var = ctk.StringVar(value=GENRES[0])
        ctk.CTkOptionMenu(genre_row, values=GENRES,
                          variable=self.genre_var,
                          width=200).grid(row=0, column=1, sticky="ew")

        depth_row = ctk.CTkFrame(left, fg_color="transparent")
        depth_row.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        depth_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(depth_row, text="Branching", width=90,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.depth_var = ctk.StringVar(value=BRANCHING_DEPTHS[0])
        ctk.CTkOptionMenu(depth_row, values=BRANCHING_DEPTHS,
                          variable=self.depth_var,
                          width=200).grid(row=0, column=1, sticky="ew")

        self.compile_btn = ctk.CTkButton(
            left, text="⚙  Compile Scene",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            fg_color="#7c5cd8", hover_color="#5a3fb5",
            command=self._on_compile)
        self.compile_btn.grid(row=4, column=0, sticky="ew", padx=10, pady=(8, 4))

        # Continue row — hidden until a scene has been compiled.
        self._continue_frame = ctk.CTkFrame(left, fg_color="transparent")
        self._continue_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 4))
        self._continue_frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(self._continue_frame, text="Continue from route:",
                     font=ctk.CTkFont(size=11),
                     text_color="#8b8fa8").grid(row=0, column=0, sticky="w", pady=(2, 0))

        self._route_var = ctk.StringVar(value="")
        self._route_menu = ctk.CTkOptionMenu(
            self._continue_frame, values=["—"],
            variable=self._route_var, width=200,
        )
        self._route_menu.grid(row=1, column=0, sticky="ew", pady=(2, 4))

        self._continue_btn = ctk.CTkButton(
            self._continue_frame, text="↪  Continue Scene",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color="#2a6496", hover_color="#1d4f75",
            command=self._on_continue,
        )
        self._continue_btn.grid(row=2, column=0, sticky="ew")
        self._continue_frame.grid_remove()  # hidden until first compile

        # Status row: a frame so the status label and optional Details button
        # can sit side-by-side using pack inside a single grid cell.
        self._status_frame = ctk.CTkFrame(left, fg_color="transparent")
        self._status_frame.grid(row=6, column=0, padx=12, pady=(4, 10))

        self.status_label = ctk.CTkLabel(self._status_frame, text="Ready.",
                                         font=ctk.CTkFont(size=11),
                                         text_color="#8b8fa8")
        self.status_label.pack(side="left")

        self.prose_box.bind("<FocusIn>", self._clear_placeholder)
        self.prose_box.bind("<FocusOut>", self._restore_placeholder)

    def _build_right_panel(self, parent):
        right = ctk.CTkFrame(parent, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Compiled Output",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        self.tab_view = ctk.CTkTabview(right, corner_radius=8)
        self.tab_view.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        tabs = ["Ren'Py Script", "Choices", "Asset Cues", "Production Notes"]
        self._tab_boxes = {}
        for tab in tabs:
            self.tab_view.add(tab)
            box = ctk.CTkTextbox(self.tab_view.tab(tab),
                                 wrap="word",
                                 font=ctk.CTkFont(family="Courier New", size=12),
                                 state="disabled",
                                 corner_radius=6)
            box.pack(fill="both", expand=True, padx=4, pady=4)
            self._tab_boxes[tab] = box

        export_row = ctk.CTkFrame(right, fg_color="transparent")
        export_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        export_row.columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(export_row, text="Export .rpy",
                      fg_color="#3b82d4", hover_color="#2563a8",
                      command=self._export_rpy).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(export_row, text="Export Asset List",
                      fg_color="#3b82d4", hover_color="#2563a8",
                      command=self._export_assets).grid(
            row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(export_row, text="Export Report (md)",
                      fg_color="#3b82d4", hover_color="#2563a8",
                      command=self._export_report).grid(
            row=0, column=2, sticky="ew", padx=(4, 0))

    def _set_placeholder(self):
        self.prose_box.insert("1.0", (
            "Paste your prose scene here…\n\n"
            "Example:\n"
            "The train platform was empty. Steam curled around the iron pillars. "
            "Ren stood at the far end, staring at the tracks."
        ))
        self.prose_box.configure(text_color="#555769")
        self._placeholder_active = True

    def _clear_placeholder(self, _event=None):
        if getattr(self, "_placeholder_active", False):
            self.prose_box.delete("1.0", "end")
            self.prose_box.configure(text_color="#dce1f0")
            self._placeholder_active = False

    def _restore_placeholder(self, _event=None):
        if not self.prose_box.get("1.0", "end").strip():
            self._set_placeholder()

    def _get_prose(self) -> str:
        if getattr(self, "_placeholder_active", False):
            return ""
        return self.prose_box.get("1.0", "end").strip()

    def _on_compile(self):
        prose = self._get_prose()
        if not prose:
            self._set_status("⚠  Paste a scene before compiling.", "#e3a008")
            return

        genre = _GENRE_MAP.get(self.genre_var.get(), "romance")
        depth = _DEPTH_MAP.get(self.depth_var.get(), "shallow")

        self.compile_btn.configure(state="disabled", text="Compiling…")
        self._set_status("Sending to compiler…", "#8b8fa8")

        def run():
            try:
                scene = compile_scene(prose, genre, depth)
                self.after(0, lambda: self._display_output(scene))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._on_compile_error(msg))

        threading.Thread(target=run, daemon=True).start()

    def _on_compile_error(self, raw: str):
        _log.error(raw)
        short = _classify_error(raw)
        self.compile_btn.configure(state="normal", text="⚙  Compile Scene")
        self._set_status(f"✗ {short}", "#ef4444")
        # Replace any previous Details button; pack it right of the status label.
        if hasattr(self, "_detail_btn") and self._detail_btn.winfo_exists():
            self._detail_btn.destroy()
        self._detail_raw = raw
        self._detail_btn = ctk.CTkButton(
            self._status_frame,
            text="Details…",
            width=70,
            height=24,
            fg_color="#3b3b4f",
            hover_color="#52526e",
            text_color="#c0c0d0",
            font=ctk.CTkFont(size=12),
            command=self._show_error_detail,
        )
        self._detail_btn.pack(side="left", padx=(6, 0))

    def _show_error_detail(self):
        """Open a small modal with the full error text and a log-file note."""
        win = ctk.CTkToplevel(self)
        win.title("Error detail")
        win.geometry("660x360")
        win.resizable(True, True)
        win.grab_set()

        box = ctk.CTkTextbox(win, wrap="word", font=ctk.CTkFont(family="Courier", size=12))
        box.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        detail = getattr(self, "_detail_raw", "")
        box.insert("1.0", detail)
        box.configure(state="disabled")

        note = ctk.CTkLabel(
            win,
            text=f"Full log: {_LOG_PATH}",
            font=ctk.CTkFont(size=11),
            text_color="#57606a",
        )
        note.pack(pady=(0, 8))

        ctk.CTkButton(win, text="Close", width=80, command=win.destroy).pack(pady=(0, 10))

    def _display_output(self, scene):
        # Clear any error Details button left from a previous failed compile.
        if hasattr(self, "_detail_btn") and self._detail_btn.winfo_exists():
            self._detail_btn.destroy()
        self._compiled_scene = scene

        self._write_tab("Ren'Py Script", scene.renpy_script)

        choice_lines = []
        for c in scene.choices:
            choice_lines.append(f"[{c.route_label}]  {c.choice_text}")
            if c.consequence:
                choice_lines.append(f"  → {c.consequence}")
            choice_lines.append("")
        self._write_tab("Choices", "\n".join(choice_lines))

        asset_lines = []
        for a in scene.asset_cues:
            asset_lines.append(f"[{a.cue_type.upper()}]  {a.name}")
            asset_lines.append(f"  {a.description}")
            asset_lines.append("")
        self._write_tab("Asset Cues", "\n".join(asset_lines))

        self._write_tab("Production Notes", "\n".join(
            f"• {note}" for note in scene.production_notes
        ))

        self.compile_btn.configure(state="normal", text="⚙  Compile Scene")
        self._set_status("✓ Compiled successfully.", "#22c55e")
        self.tab_view.set("Ren'Py Script")

        # Reveal the continue row and populate it with routes from this scene.
        route_labels = [c.route_label for c in scene.choices]
        if route_labels:
            self._route_menu.configure(values=route_labels)
            self._route_var.set(route_labels[0])
            self._continue_frame.grid()

    def _on_continue(self):
        prose = self._get_prose()
        if not prose:
            self._set_status("⚠  Paste the next scene before continuing.", "#e3a008")
            return

        scene = self._compiled_scene
        route_label = self._route_var.get()
        consequence = next(
            (c.consequence for c in scene.choices if c.route_label == route_label), ""
        )

        genre = _GENRE_MAP.get(self.genre_var.get(), "romance")
        depth = _DEPTH_MAP.get(self.depth_var.get(), "shallow")

        self._continue_btn.configure(state="disabled", text="Continuing…")
        self.compile_btn.configure(state="disabled")
        self._set_status("Continuing scene…", "#8b8fa8")

        def run():
            try:
                result = continue_scene(
                    prose, genre, depth,
                    scene.scene_title, scene.scene_summary,
                    route_label, consequence,
                )
                self.after(0, lambda: self._display_output(result))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._on_compile_error(msg))
            finally:
                self.after(0, lambda: self._continue_btn.configure(
                    state="normal", text="↪  Continue Scene"
                ))

        threading.Thread(target=run, daemon=True).start()

    def _write_tab(self, tab_name: str, content: str):
        box = self._tab_boxes[tab_name]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", content)
        box.configure(state="disabled")

    def _set_status(self, msg: str, color: str = "#8b8fa8"):
        self.status_label.configure(text=msg, text_color=color)

    def _require_scene(self) -> bool:
        if self._compiled_scene is None:
            self._set_status("⚠  Compile a scene first.", "#e3a008")
            return False
        return True

    def _export_rpy(self):
        if not self._require_scene():
            return
        path = export_rpy(self._compiled_scene)
        self._set_status(f"✓ Saved: {os.path.basename(path)}", "#22c55e")

    def _export_assets(self):
        if not self._require_scene():
            return
        path = export_asset_list(self._compiled_scene)
        self._set_status(f"✓ Saved: {os.path.basename(path)}", "#22c55e")

    def _export_report(self):
        if not self._require_scene():
            return
        path = export_markdown_report(self._compiled_scene)
        self._set_status(f"✓ Saved: {os.path.basename(path)}", "#22c55e")

    def _change_provider(self):
        """Close the main app and reopen the setup picker."""
        self.destroy()
        setup = SetupWindow()
        setup.mainloop()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _env_is_configured() -> bool:
    """Return True if .env exists and has both PROVIDER and at least one key set."""
    if not os.path.exists(_ENV_PATH):
        return False
    from dotenv import dotenv_values
    env = dotenv_values(_ENV_PATH)
    provider = env.get("PROVIDER", "").strip()
    if provider == "watsonx":
        return bool(env.get("WATSONX_API_KEY", "").strip() and
                    env.get("WATSONX_PROJECT_ID", "").strip())
    if provider == "gemini":
        return bool(env.get("GEMINI_API_KEY", "").strip())
    if provider == "openrouter":
        return bool(env.get("OPENROUTER_API_KEY", "").strip())
    return False


def run():
    if _env_is_configured():
        app = VNForgeApp()
    else:
        app = SetupWindow()
    app.mainloop()


if __name__ == "__main__":
    run()
