import sys
import os
import threading
import tkinter as tk

# Make sure vnforge/ root is on the path when launched from run_desktop.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk
from core.compiler import compile_scene
from core.exporters import export_rpy, export_asset_list, export_markdown_report

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

GENRES = ["Romance", "Mystery", "Thriller", "Fantasy", "Sci-Fi", "Slice of Life"]
BRANCHING_DEPTHS = ["Shallow (2 choices)", "Medium (3–4 choices)", "Deep (5+ choices)"]

PLACEHOLDER = (
    "Paste your prose scene here…\n\n"
    "Example:\n"
    "The train platform was empty. Steam curled around the iron pillars. "
    "Ren stood at the far end, staring at the tracks."
)


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

class LabeledFrame(ctk.CTkFrame):
    """A frame with a small section label above it."""

    def __init__(self, master, label: str, **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#8b8fa8").pack(anchor="w", padx=8, pady=(6, 2))


# ---------------------------------------------------------------------------
# Main App Window
# ---------------------------------------------------------------------------

class VNForgeApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("VNForge Desktop")
        self.geometry("1200x760")
        self.minsize(900, 600)
        self._compiled_scene = None

        self._build_layout()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        # Top bar
        top = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color="#1a1b2e")
        top.pack(fill="x", side="top")
        top.pack_propagate(False)
        ctk.CTkLabel(top, text="VNForge",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#7c5cd8").pack(side="left", padx=16, pady=8)
        ctk.CTkLabel(top, text="Visual Novel Compiler",
                     font=ctk.CTkFont(size=13),
                     text_color="#8b8fa8").pack(side="left", pady=8)

        # Main two-column body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        self._build_left_panel(body)
        self._build_right_panel(body)

    # ------------------------------------------------------------------
    # Left panel — input
    # ------------------------------------------------------------------

    def _build_left_panel(self, parent):
        left = ctk.CTkFrame(parent, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Scene Input",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        # Prose text box
        self.prose_box = ctk.CTkTextbox(left, wrap="word",
                                        font=ctk.CTkFont(size=13),
                                        corner_radius=8)
        self.prose_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))
        self._set_placeholder()

        # Genre dropdown
        genre_row = ctk.CTkFrame(left, fg_color="transparent")
        genre_row.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        genre_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(genre_row, text="Genre", width=90,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.genre_var = ctk.StringVar(value=GENRES[0])
        ctk.CTkOptionMenu(genre_row, values=GENRES,
                          variable=self.genre_var,
                          width=200).grid(row=0, column=1, sticky="ew")

        # Branching depth dropdown
        depth_row = ctk.CTkFrame(left, fg_color="transparent")
        depth_row.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        depth_row.columnconfigure(1, weight=1)
        ctk.CTkLabel(depth_row, text="Branching", width=90,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.depth_var = ctk.StringVar(value=BRANCHING_DEPTHS[0])
        ctk.CTkOptionMenu(depth_row, values=BRANCHING_DEPTHS,
                          variable=self.depth_var,
                          width=200).grid(row=0, column=1, sticky="ew")

        # Compile button
        self.compile_btn = ctk.CTkButton(
            left, text="⚙  Compile Scene",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            fg_color="#7c5cd8", hover_color="#5a3fb5",
            command=self._on_compile)
        self.compile_btn.grid(row=4, column=0, sticky="ew", padx=10, pady=(8, 4))

        # Status label
        self.status_label = ctk.CTkLabel(left, text="Ready.",
                                         font=ctk.CTkFont(size=11),
                                         text_color="#8b8fa8")
        self.status_label.grid(row=5, column=0, padx=12, pady=(0, 10))

        # Bind placeholder behaviour
        self.prose_box.bind("<FocusIn>", self._clear_placeholder)
        self.prose_box.bind("<FocusOut>", self._restore_placeholder)

    # ------------------------------------------------------------------
    # Right panel — output tabs
    # ------------------------------------------------------------------

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

        # Export buttons row
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

    # ------------------------------------------------------------------
    # Placeholder helpers
    # ------------------------------------------------------------------

    def _set_placeholder(self):
        self.prose_box.insert("1.0", PLACEHOLDER)
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

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def _get_prose(self) -> str:
        if getattr(self, "_placeholder_active", False):
            return ""
        return self.prose_box.get("1.0", "end").strip()

    def _on_compile(self):
        prose = self._get_prose()
        if not prose:
            self._set_status("⚠  Paste a scene before compiling.", "#e3a008")
            return

        self.compile_btn.configure(state="disabled", text="Compiling…")
        self._set_status("Sending to compiler…", "#8b8fa8")

        def run():
            scene = compile_scene(
                prose,
                self.genre_var.get(),
                self.depth_var.get(),
            )
            self.after(0, lambda: self._display_output(scene))

        threading.Thread(target=run, daemon=True).start()

    def _display_output(self, scene):
        self._compiled_scene = scene

        self._write_tab("Ren'Py Script", scene.renpy_script)

        choice_lines = []
        for c in scene.choices:
            choice_lines.append(f"[{c.label}]  {c.text}")
            if c.consequence:
                choice_lines.append(f"  → {c.consequence}")
            choice_lines.append("")
        self._write_tab("Choices", "\n".join(choice_lines))

        asset_lines = []
        for a in scene.asset_cues:
            asset_lines.append(f"[{a.type.upper()}]  {a.name}")
            asset_lines.append(f"  {a.description}")
            asset_lines.append("")
        self._write_tab("Asset Cues", "\n".join(asset_lines))

        self._write_tab("Production Notes", scene.production_notes)

        self.compile_btn.configure(state="normal", text="⚙  Compile Scene")
        self._set_status("✓ Compiled successfully.", "#22c55e")
        self.tab_view.set("Ren'Py Script")

    def _write_tab(self, tab_name: str, content: str):
        box = self._tab_boxes[tab_name]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", content)
        box.configure(state="disabled")

    def _set_status(self, msg: str, color: str = "#8b8fa8"):
        self.status_label.configure(text=msg, text_color=color)

    # ------------------------------------------------------------------
    # Export actions
    # ------------------------------------------------------------------

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


def run():
    app = VNForgeApp()
    app.mainloop()


if __name__ == "__main__":
    run()
