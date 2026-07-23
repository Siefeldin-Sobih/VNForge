"""VNForge desktop interface for project-based visual-novel production."""

from __future__ import annotations

import difflib
import importlib
import json
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
from pydantic import ValidationError

from core.compiler import compile_scene, estimate_input_tokens
from core.exporters import (
    export_asset_csv,
    export_asset_list,
    export_markdown_report,
    export_playable_project,
    export_rpy,
)
from core.importers import import_document
from core.project import (
    ProjectHistory,
    load_project,
    new_project,
    rebuild_asset_registry,
    save_project,
    upsert_scene,
)
from core.renderer import render_scene
from core.schemas import CharacterProfile, ScenePlan, VNForgeResult, VNProject
from core.settings import apply_provider_settings, load_provider_settings, save_provider_settings
from core.validation import analyze_project, validate_renpy_source, validate_scene

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ROOT_DIR = Path(__file__).resolve().parent
ENV_PATH = ROOT_DIR / ".env"
GENRES = ["Romance", "Mystery", "Thriller", "Fantasy", "Sci-Fi", "Horror", "Slice of Life"]
GENRE_MAP = {value: value.lower().replace("-", "_").replace(" ", "_") for value in GENRES}
DEPTHS = [
    "Linear (no choices)",
    "Shallow (2 choices)",
    "Medium (3–4 choices)",
    "Deep (5–8 choices)",
]
DEPTH_MAP = {
    "Linear (no choices)": "linear",
    "Shallow (2 choices)": "shallow",
    "Medium (3–4 choices)": "medium",
    "Deep (5–8 choices)": "deep",
}
MODES = ["Preserve", "Balanced", "Adapt"]
MODE_MAP = {value: value.lower() for value in MODES}
LOCK_SECTIONS = ["beats", "choices", "asset_cues", "production_notes"]
WATSONX_REGIONS = ["us-south", "eu-de", "eu-gb", "jp-tok", "au-syd", "ca-tor", "ap-south-1"]


def _replace_text(box: ctk.CTkTextbox, content: str, read_only: bool = False) -> None:
    """Replace textbox content while respecting its final editable state."""
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", content)
    if read_only:
        box.configure(state="disabled")


class SetupWindow(ctk.CTk):
    """First-run provider selection with live model and credential checks."""

    def __init__(self) -> None:
        super().__init__()
        self.title("VNForge — Provider Setup")
        self.geometry("760x590")
        self.resizable(False, False)
        self.provider_var = ctk.StringVar(value="watsonx")
        self.status_var = ctk.StringVar(value="Choose a provider and validate it.")
        self._build()

    def _build(self) -> None:
        """Build provider fields once and toggle them by selection."""
        ctk.CTkLabel(
            self,
            text="VNForge",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#8b6de8",
        ).pack(pady=(24, 2))
        ctk.CTkLabel(
            self,
            text="Connect a model provider. IBM watsonx is the recommended path.",
            text_color="#9ca3b8",
        ).pack(pady=(0, 16))
        provider_row = ctk.CTkSegmentedButton(
            self,
            values=["watsonx", "gemini", "openrouter", "openai", "anthropic", "opencode"],
            variable=self.provider_var,
            command=lambda _value: self._show_provider(),
        )
        provider_row.pack(fill="x", padx=40)

        self.form = ctk.CTkFrame(self)
        self.form.pack(fill="both", expand=True, padx=40, pady=16)
        self.api_key = self._entry("API Key", secret=True)
        self.project_id = self._entry("IBM Project ID")
        self.region_var = ctk.StringVar(value="us-south")
        self.region_label = ctk.CTkLabel(self.form, text="IBM Region", anchor="w")
        self.region_menu = ctk.CTkOptionMenu(
            self.form, values=WATSONX_REGIONS, variable=self.region_var
        )
        self.model_var = ctk.StringVar(value="ibm/granite-3-3-8b-instruct")
        self.model_label = ctk.CTkLabel(self.form, text="Model", anchor="w")
        self.model_menu = ctk.CTkOptionMenu(
            self.form,
            values=[self.model_var.get()],
            variable=self.model_var,
            dynamic_resizing=False,
        )
        self.load_models_button = ctk.CTkButton(
            self.form,
            text="Load Current Models",
            command=self._load_models,
            fg_color="#374151",
        )
        self._show_provider()

        ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            wraplength=520,
            text_color="#b6bdd1",
        ).pack(pady=(0, 8))
        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 22))
        ctk.CTkButton(
            button_row,
            text="Provider Help",
            width=120,
            fg_color="#374151",
            command=self._open_help,
        ).pack(side="left", padx=6)
        self.validate_button = ctk.CTkButton(
            button_row,
            text="Validate & Save",
            width=170,
            fg_color="#7654d8",
            command=self._validate,
        )
        self.validate_button.pack(side="left", padx=6)

    def _entry(self, label: str, secret: bool = False) -> ctk.CTkEntry:
        """Create a consistently styled labeled setup entry."""
        widget_label = ctk.CTkLabel(self.form, text=label, anchor="w")
        widget_label.pack(fill="x", padx=18, pady=(10, 2))
        entry = ctk.CTkEntry(self.form, show="*" if secret else "")
        entry.pack(fill="x", padx=18)
        entry._vnforge_label = widget_label  # type: ignore[attr-defined]
        return entry

    def _show_provider(self) -> None:
        """Show fields relevant to the selected provider."""
        for widget in (
            self.project_id._vnforge_label,  # type: ignore[attr-defined]
            self.project_id,
            self.region_label,
            self.region_menu,
            self.model_label,
            self.model_menu,
            self.load_models_button,
        ):
            widget.pack_forget()
        provider = self.provider_var.get()
        if provider == "watsonx":
            self.project_id._vnforge_label.pack(fill="x", padx=18, pady=(10, 2))  # type: ignore[attr-defined]
            self.project_id.pack(fill="x", padx=18)
            self.region_label.pack(fill="x", padx=18, pady=(10, 2))
            self.region_menu.pack(fill="x", padx=18)
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)
        elif provider == "openrouter":
            self.model_var.set("meta-llama/llama-3.3-70b-instruct:free")
            self.model_menu.configure(values=[self.model_var.get()])
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)
        elif provider == "gemini":
            self.model_var.set("gemini-2.0-flash")
            self.model_menu.configure(values=[self.model_var.get()])
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)
        elif provider == "openai":
            self.model_var.set("gpt-5.1")
            self.model_menu.configure(values=[self.model_var.get()])
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)
        elif provider == "anthropic":
            self.model_var.set("claude-sonnet-5")
            self.model_menu.configure(values=[self.model_var.get()])
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)
        elif provider == "opencode":
            self.model_var.set("deepseek-v4-flash")
            self.model_menu.configure(values=[self.model_var.get()])
            self.model_label.pack(fill="x", padx=18, pady=(10, 2))
            self.model_menu.pack(fill="x", padx=18)
            self.load_models_button.pack(fill="x", padx=18, pady=10)

    def _load_models(self) -> None:
        """Load live models in a worker so setup remains responsive."""
        key = self.api_key.get().strip()
        if not key:
            self.status_var.set("Enter an API key before loading models.")
            return
        self.load_models_button.configure(state="disabled", text="Loading…")
        provider = self.provider_var.get()
        region = self.region_var.get()

        def worker() -> None:
            try:
                if provider == "watsonx":
                    from core.model_client import fetch_watsonx_models

                    models = fetch_watsonx_models(key, region)
                elif provider == "openrouter":
                    from core.model_client import fetch_openrouter_models

                    models = fetch_openrouter_models(key)
                elif provider == "gemini":
                    from core.model_client import fetch_gemini_models

                    models = fetch_gemini_models(key)
                elif provider == "openai":
                    from core.model_client import fetch_openai_models

                    models = fetch_openai_models(key)
                elif provider == "anthropic":
                    from core.model_client import fetch_anthropic_models

                    models = fetch_anthropic_models(key)
                else:
                    from core.model_client import fetch_opencode_models

                    models = fetch_opencode_models(key)
                self.after(0, lambda: self._models_loaded(models))
            except Exception as error:
                message = str(error)
                self.after(0, lambda value=message: self._setup_error(value))

        threading.Thread(target=worker, daemon=True).start()

    def _models_loaded(self, models: list[str]) -> None:
        """Populate model choices after a successful live fetch."""
        self.model_menu.configure(values=models)
        self.model_var.set(models[0])
        self.load_models_button.configure(state="normal", text="Load Current Models")
        self.status_var.set(f"Loaded {len(models)} currently available models.")

    def _setup_error(self, message: str) -> None:
        """Restore setup controls after a provider error."""
        self.load_models_button.configure(state="normal", text="Load Current Models")
        self.validate_button.configure(state="normal", text="Validate & Save")
        self.status_var.set(message)

    def _validate(self) -> None:
        """Validate the complete provider configuration before saving."""
        provider = self.provider_var.get()
        key = self.api_key.get().strip()
        project_id = self.project_id.get().strip()
        region = self.region_var.get()
        selected_model = self.model_var.get()
        if not key or (provider == "watsonx" and not project_id):
            self.status_var.set("Complete all required fields.")
            return
        self.validate_button.configure(state="disabled", text="Validating…")

        def worker() -> None:
            try:
                from core.model_client import (
                    fetch_anthropic_models,
                    fetch_gemini_models,
                    fetch_openai_models,
                    fetch_opencode_models,
                    fetch_openrouter_models,
                    validate_anthropic,
                    validate_gemini,
                    validate_openai,
                    validate_opencode,
                    validate_openrouter,
                    validate_watsonx,
                )

                values: dict[str, str] = {}
                if provider == "watsonx":
                    validate_watsonx(
                        key,
                        project_id,
                        region,
                        selected_model,
                    )
                    values = {
                        "WATSONX_API_KEY": key,
                        "WATSONX_PROJECT_ID": project_id,
                        "WATSONX_REGION": region,
                        "WATSONX_MODEL_ID": selected_model,
                    }
                elif provider == "gemini":
                    validate_gemini(key)
                    models = fetch_gemini_models(key)
                    model = selected_model if selected_model in models else models[0]
                    values = {"GEMINI_API_KEY": key, "GEMINI_MODEL": model}
                elif provider == "openrouter":
                    validate_openrouter(key)
                    models = fetch_openrouter_models(key)
                    model = selected_model if selected_model in models else models[0]
                    values = {
                        "OPENROUTER_API_KEY": key,
                        "OPENROUTER_MODEL": model,
                    }
                elif provider == "openai":
                    validate_openai(key)
                    models = fetch_openai_models(key)
                    model = selected_model if selected_model in models else models[0]
                    values = {
                        "OPENAI_API_KEY": key,
                        "OPENAI_MODEL": model,
                    }
                elif provider == "anthropic":
                    validate_anthropic(key)
                    models = fetch_anthropic_models(key)
                    model = selected_model if selected_model in models else models[0]
                    values = {
                        "ANTHROPIC_API_KEY": key,
                        "ANTHROPIC_MODEL": model,
                    }
                else:
                    models = fetch_opencode_models(key)
                    model = selected_model if selected_model in models else models[0]
                    validate_opencode(key, model)
                    values = {
                        "OPENCODE_API_KEY": key,
                        "OPENCODE_MODEL": model,
                    }
                save_provider_settings(str(ENV_PATH), provider, values)
                self.after(0, self._launch_main)
            except Exception as error:
                message = str(error)
                self.after(0, lambda value=message: self._setup_error(value))

        threading.Thread(target=worker, daemon=True).start()

    def _launch_main(self) -> None:
        """Apply fresh settings and replace setup with the main window."""
        apply_provider_settings(str(ENV_PATH))
        import core.model_client as model_client

        importlib.reload(model_client)
        self.destroy()
        VNForgeApp().mainloop()

    def _open_help(self) -> None:
        """Open the selected provider's official key page."""
        urls = {
            "watsonx": "https://cloud.ibm.com/catalog/services/watsonxai-runtime",
            "gemini": "https://aistudio.google.com/app/apikey",
            "openrouter": "https://openrouter.ai/keys",
            "openai": "https://platform.openai.com/api-keys",
            "anthropic": "https://console.anthropic.com/settings/keys",
            "opencode": "https://opencode.ai/auth",
        }
        webbrowser.open(urls[self.provider_var.get()])


class AssetBoardWindow(ctk.CTkToplevel):
    """Editable project asset-production board."""

    def __init__(self, parent: VNForgeApp) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.title("VNForge — Asset Production Board")
        self.geometry("1040x620")
        self.transient(parent)
        self.rows: list[tuple[object, ctk.StringVar, ctk.CTkEntry]] = []
        self._build()

    def _build(self) -> None:
        """Build one editable row per deduplicated project asset."""
        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=12, pady=(12, 4))
        for text, width in (
            ("Type / ID", 180),
            ("Description & usage", 420),
            ("Status", 130),
            ("Source file", 250),
        ):
            ctk.CTkLabel(header, text=text, width=width, anchor="w").pack(side="left", padx=4)
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=12, pady=4)
        for asset in self.parent_app.project.asset_registry:
            row = ctk.CTkFrame(scroll)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(
                row,
                text=f"{asset.cue_type.upper()}\n{asset.name}",
                width=180,
                anchor="w",
            ).pack(side="left", padx=4)
            ctk.CTkLabel(
                row,
                text=f"{asset.description}\nUsed: {', '.join(asset.used_in_scenes)}",
                width=420,
                anchor="w",
                justify="left",
                wraplength=400,
            ).pack(side="left", padx=4)
            status = ctk.StringVar(value=asset.status)
            ctk.CTkOptionMenu(
                row,
                values=["planned", "in_progress", "ready", "approved"],
                variable=status,
                width=130,
            ).pack(side="left", padx=4)
            path_entry = ctk.CTkEntry(row, width=250)
            path_entry.insert(0, asset.file_path)
            path_entry.pack(side="left", padx=4)
            self.rows.append((asset, status, path_entry))
        ctk.CTkButton(self, text="Save Production Updates", command=self._save).pack(pady=12)

    def _save(self) -> None:
        """Persist status and source-file changes into the project registry."""
        self.parent_app.history.checkpoint()
        for asset, status, entry in self.rows:
            asset.status = status.get()
            asset.file_path = entry.get().strip()
            for scene in self.parent_app.project.scenes:
                for cue in scene.plan.asset_cues:
                    if cue.name == asset.name:
                        cue.status = asset.status
                        cue.file_path = asset.file_path
        self.parent_app._mark_dirty()
        self.parent_app._refresh_all()
        self.destroy()


class CanonWindow(ctk.CTkToplevel):
    """Project metadata and structured story-bible editor."""

    def __init__(self, parent: VNForgeApp) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.title("VNForge — Project & Story Bible")
        self.geometry("760x720")
        self.transient(parent)
        self._build()

    def _build(self) -> None:
        """Build metadata fields plus JSON character profiles."""
        project = self.parent_app.project
        self.title_entry = self._entry("Project title", project.title)
        self.author_entry = self._entry("Author", project.author)
        ctk.CTkLabel(self, text="Synopsis", anchor="w").pack(fill="x", padx=24, pady=(10, 2))
        self.synopsis = ctk.CTkTextbox(self, height=90)
        self.synopsis.pack(fill="x", padx=24)
        self.synopsis.insert("1.0", project.synopsis)
        ctk.CTkLabel(self, text="World rules — one per line", anchor="w").pack(
            fill="x", padx=24, pady=(10, 2)
        )
        self.rules = ctk.CTkTextbox(self, height=90)
        self.rules.pack(fill="x", padx=24)
        self.rules.insert("1.0", "\n".join(project.world_rules))
        ctk.CTkLabel(
            self,
            text="Characters — JSON array (IDs, display names, pronouns, appearance, relationships)",
            anchor="w",
        ).pack(fill="x", padx=24, pady=(10, 2))
        self.characters = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier New", size=12))
        self.characters.pack(fill="both", expand=True, padx=24)
        self.characters.insert(
            "1.0",
            json.dumps([item.model_dump() for item in project.characters], indent=2),
        )
        ctk.CTkButton(self, text="Apply Canon", command=self._save).pack(pady=14)

    def _entry(self, label: str, value: str) -> ctk.CTkEntry:
        """Create a labeled project metadata field."""
        ctk.CTkLabel(self, text=label, anchor="w").pack(fill="x", padx=24, pady=(10, 2))
        entry = ctk.CTkEntry(self)
        entry.pack(fill="x", padx=24)
        entry.insert(0, value)
        return entry

    def _save(self) -> None:
        """Validate and apply story-bible edits."""
        try:
            character_data = json.loads(self.characters.get("1.0", "end"))
            characters = [CharacterProfile.model_validate(item) for item in character_data]
            title = self.title_entry.get().strip()
            if not title:
                raise ValueError("Project title cannot be empty.")
        except (ValueError, ValidationError, json.JSONDecodeError) as error:
            messagebox.showerror("Invalid canon", str(error), parent=self)
            return
        self.parent_app.history.checkpoint()
        project = self.parent_app.project
        project.title = title
        project.author = self.author_entry.get().strip()
        project.synopsis = self.synopsis.get("1.0", "end").strip()
        project.world_rules = [
            value.strip() for value in self.rules.get("1.0", "end").splitlines() if value.strip()
        ]
        project.characters = characters
        self.parent_app._mark_dirty()
        self.parent_app._refresh_all()
        self.destroy()


class VNForgeApp(ctk.CTk):
    """Project workspace for compiling, reviewing, and exporting scenes."""

    def __init__(self) -> None:
        super().__init__()
        self.title("VNForge — Visual Novel Production Workspace")
        self.geometry("1440x880")
        self.minsize(1080, 700)
        self.history = ProjectHistory(new_project())
        self.project_path = ""
        self.current_scene_id = ""
        self.current_result: VNForgeResult | None = None
        self.dirty = False
        self.cancel_event: threading.Event | None = None
        self.compile_active = False
        self.compile_started_at = 0.0
        self.compile_token_estimate = 0
        self.compile_phase = "Waiting for provider"
        self.compile_run_id = 0
        self._build_layout()
        self._refresh_all()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @property
    def project(self) -> VNProject:
        """Return the mutable project owned by the history manager."""
        return self.history.project

    def _build_layout(self) -> None:
        """Build toolbar, scene controls, output tabs, and export actions."""
        toolbar = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color="#171827")
        toolbar.pack(fill="x")
        ctk.CTkLabel(
            toolbar,
            text="VNForge",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#8b6de8",
        ).pack(side="left", padx=(14, 8))
        for text, command in (
            ("New", self._new_project),
            ("Open", self._open_project),
            ("Import", self._import_document),
            ("Save", self._save_project),
            ("Save As", self._save_project_as),
            ("Undo", self._undo),
            ("Redo", self._redo),
            ("Project & Canon", lambda: CanonWindow(self)),
            ("Asset Board", lambda: AssetBoardWindow(self)),
        ):
            ctk.CTkButton(
                toolbar,
                text=text,
                width=88 if len(text) < 10 else 116,
                height=30,
                fg_color="#303247",
                command=command,
            ).pack(side="left", padx=3, pady=9)
        ctk.CTkButton(
            toolbar,
            text="Provider",
            width=90,
            height=30,
            fg_color="#303247",
            command=self._change_provider,
        ).pack(side="right", padx=12)
        self.project_label = ctk.CTkLabel(toolbar, text="", text_color="#aeb5ca")
        self.project_label.pack(side="right", padx=8)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=10)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)
        self._build_input_panel(body)
        self._build_output_panel(body)

    def _build_input_panel(self, parent: ctk.CTkFrame) -> None:
        """Build project-scene selection and generation controls."""
        panel = ctk.CTkFrame(parent)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)
        ctk.CTkLabel(panel, text="Project Scene", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 3)
        )
        scene_row = ctk.CTkFrame(panel, fg_color="transparent")
        scene_row.grid(row=1, column=0, sticky="ew", padx=10)
        scene_row.columnconfigure(0, weight=1)
        self.scene_var = ctk.StringVar(value="New scene")
        self.scene_menu = ctk.CTkOptionMenu(
            scene_row,
            values=["New scene"],
            variable=self.scene_var,
            command=self._select_scene,
        )
        self.scene_menu.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(scene_row, text="+", width=36, command=self._new_scene).grid(row=0, column=1)
        continuation_row = ctk.CTkFrame(panel, fg_color="transparent")
        continuation_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        continuation_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(continuation_row, text="Continue from", width=90, anchor="w").grid(
            row=0, column=0
        )
        self.continuation_var = ctk.StringVar(value="Independent scene")
        self.continuation_menu = ctk.CTkOptionMenu(
            continuation_row,
            values=["Independent scene"],
            variable=self.continuation_var,
        )
        self.continuation_menu.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(panel, text="Creator prose", anchor="w").grid(
            row=3, column=0, sticky="w", padx=12, pady=(8, 3)
        )
        self.prose_box = ctk.CTkTextbox(panel, wrap="word", font=ctk.CTkFont(size=13))
        self.prose_box.grid(row=4, column=0, sticky="nsew", padx=10)

        options = ctk.CTkFrame(panel, fg_color="transparent")
        options.grid(row=5, column=0, sticky="ew", padx=10, pady=7)
        options.columnconfigure(1, weight=1)
        self.genre_var = ctk.StringVar(value="Romance")
        self.depth_var = ctk.StringVar(value=DEPTHS[1])
        self.mode_var = ctk.StringVar(value="Balanced")
        for row, (label, values, variable) in enumerate(
            (
                ("Genre", GENRES, self.genre_var),
                ("Branching", DEPTHS, self.depth_var),
                ("Adaptation", MODES, self.mode_var),
            )
        ):
            ctk.CTkLabel(options, text=label, width=80, anchor="w").grid(
                row=row, column=0, sticky="w", pady=2
            )
            ctk.CTkOptionMenu(options, values=values, variable=variable).grid(
                row=row, column=1, sticky="ew", pady=2
            )

        lock_frame = ctk.CTkFrame(panel)
        lock_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 7))
        ctk.CTkLabel(lock_frame, text="Lock approved sections", text_color="#adb4c8").pack(
            anchor="w", padx=8, pady=(5, 1)
        )
        self.lock_vars: dict[str, ctk.BooleanVar] = {}
        lock_row = ctk.CTkFrame(lock_frame, fg_color="transparent")
        lock_row.pack(fill="x", padx=4, pady=(0, 4))
        for section, label in (
            ("beats", "Script beats"),
            ("choices", "Choices"),
            ("asset_cues", "Assets"),
            ("production_notes", "Notes"),
        ):
            variable = ctk.BooleanVar(value=False)
            self.lock_vars[section] = variable
            ctk.CTkCheckBox(
                lock_row,
                text=label,
                variable=variable,
                width=80,
                command=self._sync_current_scene_inputs,
            ).pack(side="left", padx=3)

        action_row = ctk.CTkFrame(panel, fg_color="transparent")
        action_row.grid(row=7, column=0, sticky="ew", padx=10)
        action_row.columnconfigure((0, 1), weight=1)
        self.compile_button = ctk.CTkButton(
            action_row,
            text="Compile Scene",
            height=42,
            fg_color="#7654d8",
            command=self._compile,
        )
        self.compile_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.cancel_button = ctk.CTkButton(
            action_row,
            text="Cancel",
            height=42,
            fg_color="#7f3446",
            state="disabled",
            command=self._cancel_compile,
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.status_label = ctk.CTkLabel(panel, text="Ready.", wraplength=420, text_color="#aeb5ca")
        self.status_label.grid(row=8, column=0, padx=10, pady=(6, 10))

    def _build_output_panel(self, parent: ctk.CTkFrame) -> None:
        """Build editable plan and project-production views."""
        panel = ctk.CTkFrame(parent)
        panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(9, 4))
        ctk.CTkLabel(
            header, text="Production Workspace", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            header, text="Apply Plan Edits", width=120, command=self._apply_plan_edits
        ).pack(side="right", padx=3)
        ctk.CTkButton(
            header, text="Apply Project JSON", width=135, command=self._apply_project_json
        ).pack(side="right", padx=3)
        ctk.CTkButton(header, text="Regenerate Tab", width=120, command=self._regenerate_tab).pack(
            side="right", padx=3
        )
        self.tabs = ctk.CTkTabview(panel)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=10)
        self.tab_boxes: dict[str, ctk.CTkTextbox] = {}
        for name, editable in (
            ("Ren'Py", False),
            ("Scene Plan", True),
            ("Choices", False),
            ("Comparison", False),
            ("Asset Board", False),
            ("Story Map", False),
            ("Notes & Validation", False),
            ("Project JSON", True),
        ):
            self.tabs.add(name)
            box = ctk.CTkTextbox(
                self.tabs.tab(name),
                wrap="word",
                font=ctk.CTkFont(family="Courier New", size=12),
            )
            box.pack(fill="both", expand=True, padx=4, pady=4)
            if not editable:
                box.configure(state="disabled")
            self.tab_boxes[name] = box
        export_row = ctk.CTkFrame(panel, fg_color="transparent")
        export_row.grid(row=2, column=0, sticky="ew", padx=10, pady=9)
        export_row.columnconfigure((0, 1, 2, 3, 4), weight=1)
        for column, (text, command) in enumerate(
            (
                ("Export .rpy", self._export_rpy),
                ("Scene Report", self._export_report),
                ("Asset List", self._export_asset_list),
                ("Asset CSV", self._export_asset_csv),
                ("Playable Project", self._export_playable),
            )
        ):
            ctk.CTkButton(export_row, text=text, command=command, fg_color="#2f6da0").grid(
                row=0, column=column, sticky="ew", padx=3
            )

    def _result_for_scene(self, scene_id: str) -> VNForgeResult | None:
        """Build the current deterministic result for a stored scene."""
        project_scene = next(
            (item for item in self.project.scenes if item.plan.scene_id == scene_id),
            None,
        )
        if not project_scene:
            return None
        plan = project_scene.plan
        script = render_scene(plan)
        diagnostics = validate_scene(plan, project_scene.branching_depth)
        known_labels = {f"scene_{scene.plan.scene_id}" for scene in self.project.scenes}
        diagnostics.extend(validate_renpy_source(script, known_labels=known_labels))
        return VNForgeResult(**plan.model_dump(), renpy_script=script, diagnostics=diagnostics)

    def _refresh_all(self) -> None:
        """Synchronize every view from the current project state."""
        scene_labels = [
            f"{scene.plan.scene_id} — {scene.plan.scene_title}" for scene in self.project.scenes
        ]
        values = ["New scene", *scene_labels]
        self.scene_menu.configure(values=values)
        route_values = ["Independent scene"]
        route_values.extend(
            f"{scene.plan.scene_id} / {choice.route_label} — {choice.choice_text}"
            for scene in self.project.scenes
            for choice in scene.plan.choices
        )
        self.continuation_menu.configure(values=route_values)
        if self.current_scene_id not in {scene.plan.scene_id for scene in self.project.scenes}:
            self.current_scene_id = ""
        if self.current_scene_id:
            label = next(
                value for value in scene_labels if value.startswith(f"{self.current_scene_id} —")
            )
            self.scene_var.set(label)
            self.current_result = self._result_for_scene(self.current_scene_id)
        else:
            self.scene_var.set("New scene")
            self.current_result = None
        suffix = " *" if self.dirty else ""
        self.project_label.configure(text=f"{self.project.title}{suffix}")
        self.title(f"VNForge — {self.project.title}{suffix}")
        self._display_views()

    def _display_views(self) -> None:
        """Populate output tabs for the selected scene and whole project."""
        result = self.current_result
        if result:
            _replace_text(self.tab_boxes["Ren'Py"], result.renpy_script, True)
            plan_json = ScenePlan(
                **result.model_dump(include=set(ScenePlan.model_fields))
            ).model_dump_json(indent=2)
            _replace_text(self.tab_boxes["Scene Plan"], plan_json)
            choice_lines = []
            for choice in result.choices:
                choice_lines.extend(
                    [
                        f"[{choice.route_label}] {choice.choice_text}",
                        f"  State: {choice.variable_change}",
                        f"  Consequence: {choice.consequence}",
                        f"  Target: {choice.target_scene_id or 'local route stub'}",
                        "",
                    ]
                )
            _replace_text(self.tab_boxes["Choices"], "\n".join(choice_lines), True)
            project_scene = next(
                item for item in self.project.scenes if item.plan.scene_id == result.scene_id
            )
            planned_text = "\n".join(
                beat.text
                for beat in result.beats
                if beat.kind in {"dialogue", "narration"} and beat.text
            )
            comparison = difflib.unified_diff(
                project_scene.source_text.splitlines(),
                planned_text.splitlines(),
                fromfile="creator_prose",
                tofile="compiled_dialogue_and_narration",
                lineterm="",
            )
            _replace_text(self.tab_boxes["Comparison"], "\n".join(comparison), True)
            notes = [f"• {note}" for note in result.production_notes]
            notes.extend(
                f"\n[{item.severity.upper()}] {item.message}" for item in result.diagnostics
            )
            _replace_text(self.tab_boxes["Notes & Validation"], "\n".join(notes), True)
        else:
            for name in (
                "Ren'Py",
                "Scene Plan",
                "Choices",
                "Comparison",
                "Notes & Validation",
            ):
                _replace_text(
                    self.tab_boxes[name],
                    "Compile or select a scene to populate this view.",
                    name != "Scene Plan",
                )
        asset_lines = []
        for asset in self.project.asset_registry:
            asset_lines.extend(
                [
                    f"[{asset.status.upper()}] {asset.cue_type.upper()} — {asset.name}",
                    f"  {asset.description}",
                    f"  Variants: {', '.join(asset.variants) or 'none'}",
                    f"  Source: {asset.file_path or 'VNForge placeholder'}",
                    f"  Used in: {', '.join(asset.used_in_scenes)}",
                    "",
                ]
            )
        _replace_text(
            self.tab_boxes["Asset Board"], "\n".join(asset_lines) or "No project assets yet.", True
        )
        _replace_text(self.tab_boxes["Story Map"], self._story_map(), True)
        _replace_text(self.tab_boxes["Project JSON"], self.project.model_dump_json(indent=2))

    def _story_map(self) -> str:
        """Render a compact project branch map and continuity findings."""
        lines = [f"STORY MAP — {self.project.title}", "=" * 60, ""]
        if not self.project.scenes:
            lines.append("No scenes compiled yet.")
        for scene in self.project.scenes:
            lines.append(f"● {scene.plan.scene_id}: {scene.plan.scene_title}")
            for choice in scene.plan.choices:
                target = choice.target_scene_id or f"route:{choice.route_label}"
                lines.append(f"  └─ {choice.choice_text}  →  {target}")
            lines.append("")
        findings = analyze_project(self.project)
        lines.extend(["CONTINUITY", "-" * 60])
        lines.extend(f"[{item.severity.upper()}] {item.message}" for item in findings)
        if not findings:
            lines.append("No cross-scene continuity problems detected.")
        return "\n".join(lines)

    def _select_scene(self, selection: str) -> None:
        """Load creator inputs for a selected project scene."""
        if selection == "New scene":
            self._new_scene()
            return
        scene_id = selection.split(" — ", 1)[0]
        if self.current_scene_id and self.current_scene_id != scene_id:
            self._sync_current_scene_inputs()
        scene = next(item for item in self.project.scenes if item.plan.scene_id == scene_id)
        self.current_scene_id = scene_id
        _replace_text(self.prose_box, scene.source_text)
        reverse_genre = {value: key for key, value in GENRE_MAP.items()}
        reverse_depth = {value: key for key, value in DEPTH_MAP.items()}
        self.genre_var.set(reverse_genre.get(scene.genre, "Romance"))
        self.depth_var.set(reverse_depth.get(scene.branching_depth, DEPTHS[1]))
        self.mode_var.set(scene.creative_mode.title())
        for section, variable in self.lock_vars.items():
            variable.set(section in scene.locked_sections)
        if scene.continues_from_scene_id and scene.continues_from_route_label:
            prefix = f"{scene.continues_from_scene_id} / {scene.continues_from_route_label} —"
            selected_route = next(
                (
                    value
                    for value in self.continuation_menu.cget("values")
                    if value.startswith(prefix)
                ),
                "Independent scene",
            )
            self.continuation_var.set(selected_route)
        else:
            self.continuation_var.set("Independent scene")
        self._refresh_all()

    def _new_scene(self) -> None:
        """Clear only scene inputs while preserving the active project."""
        self._sync_current_scene_inputs()
        self.current_scene_id = ""
        self.current_result = None
        _replace_text(self.prose_box, "")
        for variable in self.lock_vars.values():
            variable.set(False)
        self.continuation_var.set("Independent scene")
        self._refresh_all()

    def _compile(self, regenerate_section: str = "") -> None:
        """Compile or regenerate a scene in a cancellable background worker."""
        source = self.prose_box.get("1.0", "end").strip()
        if not source:
            self._set_status("Paste creator prose before compiling.", error=True)
            return
        genre = GENRE_MAP[self.genre_var.get()]
        depth = DEPTH_MAP[self.depth_var.get()]
        mode = MODE_MAP[self.mode_var.get()]
        existing_scene = next(
            (item for item in self.project.scenes if item.plan.scene_id == self.current_scene_id),
            None,
        )
        previous_plan = existing_scene.plan if existing_scene else None
        locked = [name for name, variable in self.lock_vars.items() if variable.get()]
        continuation = None
        if self.continuation_var.get() != "Independent scene":
            route_prefix = self.continuation_var.get().split(" — ", 1)[0]
            source_scene_id, route_label = route_prefix.split(" / ", 1)
            continuation = (source_scene_id, route_label)
        estimate = estimate_input_tokens(source, self.project)
        self.cancel_event = threading.Event()
        self.compile_active = True
        self.compile_started_at = time.monotonic()
        self.compile_token_estimate = estimate
        self.compile_phase = "Waiting for provider"
        self.compile_run_id += 1
        self.compile_button.configure(state="disabled", text="Compiling…")
        self.cancel_button.configure(state="normal")
        self._update_compile_progress(self.compile_run_id)

        def worker() -> None:
            try:
                result = compile_scene(
                    source,
                    genre,
                    depth,
                    mode,
                    project=self.project,
                    previous_plan=previous_plan,
                    regenerate_section=regenerate_section,
                    locked_sections=locked,
                    cancel_event=self.cancel_event,
                    continues_from=continuation,
                )
                self.after(
                    0,
                    lambda: self._compile_complete(
                        result, source, genre, depth, mode, locked, continuation
                    ),
                )
            except Exception as error:
                message = str(error)
                self.after(0, lambda value=message: self._compile_failed(value))

        threading.Thread(target=worker, daemon=True).start()

    def _compile_complete(
        self,
        result: VNForgeResult,
        source: str,
        genre: str,
        depth: str,
        mode: str,
        locked: list[str],
        continuation: tuple[str, str] | None,
    ) -> None:
        """Store a validated generation and refresh project views."""
        self.compile_active = False
        self.history.checkpoint()
        plan = ScenePlan(**result.model_dump(include=set(ScenePlan.model_fields)))
        upsert_scene(
            self.project,
            source,
            genre,
            depth,
            mode,
            plan,
            locked,
            continuation,
        )
        self.current_scene_id = plan.scene_id
        self.current_result = result
        self._mark_dirty()
        self.compile_button.configure(state="normal", text="Compile Scene")
        self.cancel_button.configure(state="disabled")
        self._set_status("Compiled, validated, and added to the project.")
        self._refresh_all()
        self.tabs.set("Ren'Py")

    def _compile_failed(self, message: str) -> None:
        """Restore generation controls after cancellation or failure."""
        self.compile_active = False
        self.compile_button.configure(state="normal", text="Compile Scene")
        self.cancel_button.configure(state="disabled")
        self._set_status(message, error=True)

    def _cancel_compile(self) -> None:
        """Request cancellation between network operations."""
        if self.cancel_event:
            self.cancel_event.set()
            self.compile_phase = "Cancellation requested; waiting for current request"
            self._set_status("Cancellation requested; waiting for the current request.")

    def _update_compile_progress(self, run_id: int) -> None:
        """Show elapsed provider wait time while a compilation is active."""
        if not self.compile_active or run_id != self.compile_run_id:
            return
        elapsed = int(time.monotonic() - self.compile_started_at)
        self._set_status(
            f"{self.compile_phase} — {elapsed}s elapsed; "
            f"~{self.compile_token_estimate:,} input tokens."
        )
        self.after(1000, lambda: self._update_compile_progress(run_id))

    def _apply_plan_edits(self) -> None:
        """Validate editable Scene Plan JSON and deterministically rerender it."""
        if not self.current_scene_id:
            self._set_status("Select a compiled scene before applying plan edits.", True)
            return
        try:
            plan = ScenePlan.model_validate_json(self.tab_boxes["Scene Plan"].get("1.0", "end"))
            if plan.scene_id != self.current_scene_id:
                raise ValueError(
                    "Scene ID is stable after creation; change the title or create a new scene instead."
                )
            scene = next(
                item for item in self.project.scenes if item.plan.scene_id == self.current_scene_id
            )
            diagnostics = validate_scene(plan, scene.branching_depth)
            errors = [item.message for item in diagnostics if item.severity == "error"]
            if errors:
                raise ValueError("; ".join(errors))
        except (ValidationError, ValueError) as error:
            self._set_status(f"Plan edit rejected: {error}", True)
            return
        self.history.checkpoint()
        scene.plan_history.append(scene.plan.model_copy(deep=True))
        scene.plan_history = scene.plan_history[-20:]
        scene.plan = plan
        self.current_scene_id = plan.scene_id
        rebuild_asset_registry(self.project)
        self._mark_dirty()
        self._refresh_all()
        self._set_status("Plan edits validated and applied.")

    def _regenerate_tab(self) -> None:
        """Regenerate the semantic section represented by the active tab."""
        mapping = {
            "Ren'Py": "beats",
            "Scene Plan": "beats",
            "Choices": "choices",
            "Asset Board": "asset_cues",
            "Notes & Validation": "production_notes",
        }
        section = mapping.get(self.tabs.get())
        if not section or not self.current_scene_id:
            self._set_status("Select a scene content tab before regenerating.", True)
            return
        if self.lock_vars[section].get():
            self._set_status(f"'{section}' is locked. Unlock it before regenerating.", True)
            return
        self._compile(regenerate_section=section)

    def _apply_project_json(self) -> None:
        """Validate and apply the advanced full-project JSON editor."""
        try:
            project = VNProject.model_validate_json(
                self.tab_boxes["Project JSON"].get("1.0", "end")
            )
        except ValidationError as error:
            self._set_status(f"Project JSON rejected: {error}", True)
            return
        self.history.checkpoint()
        self.history.project = project
        rebuild_asset_registry(self.project)
        self._mark_dirty()
        self._refresh_all()

    def _new_project(self) -> None:
        """Create a project after protecting unsaved work."""
        if not self._confirm_discard():
            return
        title = simpledialog.askstring("New project", "Project title:", parent=self)
        if not title:
            return
        self.history = ProjectHistory(new_project(title.strip()))
        self.project_path = ""
        self.current_scene_id = ""
        self.dirty = False
        self._new_scene()

    def _import_document(self) -> None:
        """Import prose/Markdown or a safe subset of an existing Ren'Py script."""
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("Supported documents", "*.txt *.md *.rpy"),
                ("Ren'Py scripts", "*.rpy"),
                ("Text and Markdown", "*.txt *.md"),
                ("All files", "*"),
            ],
        )
        if not path:
            return
        try:
            source, plan = import_document(path)
        except Exception as error:
            self._set_status(f"Import failed: {error}", True)
            return
        self._new_scene()
        _replace_text(self.prose_box, source)
        if plan is None:
            self._set_status(f"Loaded {Path(path).name} as creator prose.")
            return
        choice_count = len(plan.choices)
        depth = (
            "linear"
            if choice_count == 0
            else "shallow"
            if choice_count <= 2
            else "medium"
            if choice_count <= 4
            else "deep"
        )
        self.history.checkpoint()
        upsert_scene(
            self.project,
            source,
            "slice_of_life",
            depth,
            "preserve",
            plan,
        )
        self.current_scene_id = plan.scene_id
        self._mark_dirty()
        self._refresh_all()
        self._set_status(
            "Imported supported Ren'Py statements. Review omitted/custom code in notes."
        )

    def _open_project(self) -> None:
        """Open and validate a portable ``.vnforge`` project."""
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("VNForge projects", "*.vnforge"), ("All files", "*")],
        )
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as error:
            messagebox.showerror("Cannot open project", str(error), parent=self)
            return
        self.history = ProjectHistory(project)
        self.project_path = path
        first_scene_id = project.scenes[0].plan.scene_id if project.scenes else ""
        self.current_scene_id = ""
        self.dirty = False
        if first_scene_id:
            label = next(
                f"{item.plan.scene_id} — {item.plan.scene_title}"
                for item in project.scenes
                if item.plan.scene_id == first_scene_id
            )
            self._select_scene(label)
        else:
            self._new_scene()
        self._set_status(f"Opened {Path(path).name}.")

    def _save_project(self) -> None:
        """Save to the current path or ask for one when necessary."""
        self._sync_current_scene_inputs()
        if not self.project_path:
            self._save_project_as()
            return
        try:
            self.project_path = save_project(self.project, self.project_path)
            self.dirty = False
            self._refresh_all()
            self._set_status(f"Saved {Path(self.project_path).name}.")
        except Exception as error:
            self._set_status(f"Save failed: {error}", True)

    def _save_project_as(self) -> None:
        """Choose a path and save the active project."""
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".vnforge",
            initialfile=f"{self.project.project_id}.vnforge",
            filetypes=[("VNForge projects", "*.vnforge")],
        )
        if not path:
            return
        self.project_path = path
        self._save_project()

    def _undo(self) -> None:
        """Undo the latest project-changing operation."""
        self.history.undo()
        self._mark_dirty()
        self._refresh_all()

    def _redo(self) -> None:
        """Redo the latest undone operation."""
        self.history.redo()
        self._mark_dirty()
        self._refresh_all()

    def _require_result(self) -> VNForgeResult | None:
        """Return the selected scene result or show a useful status."""
        if not self.current_result:
            self._set_status("Compile or select a scene first.", True)
            return None
        return self.current_result

    def _choose_export_dir(self) -> str:
        """Ask for an export parent directory."""
        return filedialog.askdirectory(parent=self, title="Choose export folder")

    def _export_rpy(self) -> None:
        result = self._require_result()
        destination = self._choose_export_dir() if result else ""
        if result and destination:
            self._set_status(f"Exported {export_rpy(result, destination)}.")

    def _export_report(self) -> None:
        result = self._require_result()
        destination = self._choose_export_dir() if result else ""
        if result and destination:
            self._set_status(f"Exported {export_markdown_report(result, destination)}.")

    def _export_asset_list(self) -> None:
        result = self._require_result()
        destination = self._choose_export_dir() if result else ""
        if result and destination:
            self._set_status(f"Exported {export_asset_list(result, destination)}.")

    def _export_asset_csv(self) -> None:
        destination = self._choose_export_dir()
        if destination:
            self._set_status(f"Exported {export_asset_csv(self.project, destination)}.")

    def _export_playable(self) -> None:
        """Export a self-contained project and report lint availability/results."""
        if not self.project.scenes:
            self._set_status("Compile at least one scene before playable export.", True)
            return
        destination = self._choose_export_dir()
        if not destination:
            return
        try:
            path, lint_ok, output = export_playable_project(self.project, destination)
            if lint_ok:
                self._set_status(f"Playable project exported and Ren'Py lint passed: {path}")
            else:
                self._set_status(f"Playable project exported: {path}. {output}")
        except Exception as error:
            self._set_status(f"Playable export failed: {error}", True)

    def _change_provider(self) -> None:
        """Open provider setup after protecting unsaved project work."""
        if self.dirty:
            self._save_project()
            if self.dirty:
                return
        self.destroy()
        SetupWindow().mainloop()

    def _confirm_discard(self) -> bool:
        """Protect unsaved work before replacing the current project."""
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved project",
            "Save the current project before continuing?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            self._save_project()
            return not self.dirty
        return True

    def _mark_dirty(self) -> None:
        """Mark project state as changed since the last save."""
        self.dirty = True

    def _sync_current_scene_inputs(self) -> None:
        """Persist changed scene prose, settings, and locks before navigation/save."""
        if not self.current_scene_id:
            return
        scene = next(
            (item for item in self.project.scenes if item.plan.scene_id == self.current_scene_id),
            None,
        )
        if not scene:
            return
        source = self.prose_box.get("1.0", "end").strip()
        locked = [name for name, variable in self.lock_vars.items() if variable.get()]
        genre = GENRE_MAP[self.genre_var.get()]
        depth = DEPTH_MAP[self.depth_var.get()]
        mode = MODE_MAP[self.mode_var.get()]
        new_values = (source, genre, depth, mode, locked)
        old_values = (
            scene.source_text,
            scene.genre,
            scene.branching_depth,
            scene.creative_mode,
            scene.locked_sections,
        )
        if source and new_values != old_values:
            self.history.checkpoint()
            scene.source_text = source
            scene.genre = genre
            scene.branching_depth = depth
            scene.creative_mode = mode
            scene.locked_sections = locked
            self._mark_dirty()

    def _set_status(self, message: str, error: bool = False) -> None:
        """Show concise workflow feedback."""
        self.status_label.configure(
            text=message,
            text_color="#ef7777" if error else "#aeb5ca",
        )

    def _on_close(self) -> None:
        """Close only after resolving unsaved project changes."""
        if self._confirm_discard():
            self.destroy()


def _env_is_configured() -> bool:
    """Return whether the selected provider has a retrievable API secret."""
    if not ENV_PATH.exists():
        return False
    values = load_provider_settings(str(ENV_PATH))
    provider = values.get("PROVIDER", "")
    if provider == "watsonx":
        return bool(values.get("WATSONX_API_KEY") and values.get("WATSONX_PROJECT_ID"))
    if provider == "gemini":
        return bool(values.get("GEMINI_API_KEY"))
    if provider == "openrouter":
        return bool(values.get("OPENROUTER_API_KEY"))
    if provider == "openai":
        return bool(values.get("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(values.get("ANTHROPIC_API_KEY"))
    if provider == "opencode":
        return bool(values.get("OPENCODE_API_KEY"))
    return False


def run() -> None:
    """Launch setup or the project workspace as appropriate."""
    if _env_is_configured():
        apply_provider_settings(str(ENV_PATH))
        VNForgeApp().mainloop()
    else:
        SetupWindow().mainloop()


if __name__ == "__main__":
    run()
