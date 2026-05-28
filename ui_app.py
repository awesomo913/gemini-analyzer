"""Main application UI — modern dark-themed Gemini Analyzer."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import re
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging

from parser import Conversation, parse_input
from categorizer import categorize_all
from config_manager import Config, APP_NAME, APP_VERSION
from diagnostics import generate_report
from reconstruct import ProjectThread, reconstruct_projects, build_timeline
from insights import (
    default_client_from_config, summarize_project, review_project,
    ProjectSummary, ProjectReview,
)
from export import write_project_bundle, write_dedup_report
from llm_client import is_available as llm_is_available, ENV_KEY as LLM_ENV_KEY
from llm_cache import LLMCache

logger = logging.getLogger(__name__)

# ── Color Themes ──────────────────────────────────────────────────────────

DARK = {
    "bg": "#1e1e2e",
    "bg_secondary": "#252538",
    "bg_tertiary": "#2d2d44",
    "bg_input": "#1a1a2e",
    "fg": "#e0e0e0",
    "fg_dim": "#888899",
    "fg_bright": "#ffffff",
    "accent": "#7c3aed",
    "accent_hover": "#6d28d9",
    "accent_light": "#a78bfa",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "border": "#3d3d5c",
    "highlight": "#334155",
    "code_bg": "#0d1117",
    "code_fg": "#c9d1d9",
    "selection": "#264f78",
    "scrollbar": "#4a4a6a",
    "tag_bg": "#3b3b5c",
}

LIGHT = {
    "bg": "#f8f9fa",
    "bg_secondary": "#ffffff",
    "bg_tertiary": "#e9ecef",
    "bg_input": "#ffffff",
    "fg": "#212529",
    "fg_dim": "#6c757d",
    "fg_bright": "#000000",
    "accent": "#7c3aed",
    "accent_hover": "#6d28d9",
    "accent_light": "#8b5cf6",
    "success": "#059669",
    "warning": "#d97706",
    "error": "#dc2626",
    "border": "#dee2e6",
    "highlight": "#e8e8ff",
    "code_bg": "#f6f8fa",
    "code_fg": "#24292f",
    "selection": "#b4d5fe",
    "scrollbar": "#c4c4c4",
    "tag_bg": "#e2e3e5",
}


def _apply_theme(root: tk.Tk, colors: dict) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=colors["bg"])

    style.configure(".", background=colors["bg"], foreground=colors["fg"],
                    fieldbackground=colors["bg_input"], borderwidth=0,
                    font=("Segoe UI", 11))

    style.configure("TFrame", background=colors["bg"])
    style.configure("Secondary.TFrame", background=colors["bg_secondary"])
    style.configure("Tertiary.TFrame", background=colors["bg_tertiary"])

    style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"),
                    foreground=colors["accent_light"])
    style.configure("Subtitle.TLabel", font=("Segoe UI", 13),
                    foreground=colors["fg_dim"])
    style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"),
                    foreground=colors["fg_bright"])
    style.configure("Dim.TLabel", foreground=colors["fg_dim"])
    style.configure("Success.TLabel", foreground=colors["success"])
    style.configure("Warning.TLabel", foreground=colors["warning"])
    style.configure("Error.TLabel", foreground=colors["error"])
    style.configure("Status.TLabel", background=colors["bg_tertiary"],
                    foreground=colors["fg_dim"], padding=(8, 4))
    style.configure("Tag.TLabel", background=colors["tag_bg"],
                    foreground=colors["accent_light"], padding=(6, 2),
                    font=("Segoe UI", 9))

    style.configure("TButton", background=colors["bg_tertiary"],
                    foreground=colors["fg"], padding=(12, 6),
                    font=("Segoe UI", 10))
    style.map("TButton",
              background=[("active", colors["accent_hover"]),
                          ("pressed", colors["accent"])],
              foreground=[("active", "#ffffff")])

    style.configure("Accent.TButton", background=colors["accent"],
                    foreground="#ffffff", font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", colors["accent_hover"])])

    style.configure("TEntry", fieldbackground=colors["bg_input"],
                    foreground=colors["fg"], insertcolor=colors["fg"],
                    padding=6)

    style.configure("Treeview", background=colors["bg_secondary"],
                    foreground=colors["fg"],
                    fieldbackground=colors["bg_secondary"],
                    rowheight=28, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=colors["bg_tertiary"],
                    foreground=colors["fg_bright"],
                    font=("Segoe UI", 10, "bold"))
    style.map("Treeview",
              background=[("selected", colors["highlight"])],
              foreground=[("selected", colors["fg_bright"])])

    style.configure("TNotebook", background=colors["bg"])
    style.configure("TNotebook.Tab", background=colors["bg_tertiary"],
                    foreground=colors["fg_dim"], padding=(14, 6),
                    font=("Segoe UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", colors["bg_secondary"])],
              foreground=[("selected", colors["fg_bright"])])

    style.configure("TPanedwindow", background=colors["border"])
    style.configure("TSeparator", background=colors["border"])

    style.configure("Horizontal.TProgressbar",
                    background=colors["accent"],
                    troughcolor=colors["bg_tertiary"])

    style.configure("TLabelframe", background=colors["bg"],
                    foreground=colors["fg_dim"])
    style.configure("TLabelframe.Label", background=colors["bg"],
                    foreground=colors["fg_dim"], font=("Segoe UI", 10))

    style.configure("TCombobox", fieldbackground=colors["bg_input"],
                    foreground=colors["fg"], selectbackground=colors["selection"])

    style.configure("Vertical.TScrollbar",
                    background=colors["scrollbar"],
                    troughcolor=colors["bg"],
                    borderwidth=0, width=10)


class GeminiAnalyzerApp:

    def __init__(self) -> None:
        self.config = Config()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry(
            f"{self.config.get('window_width')}x{self.config.get('window_height')}"
        )
        self.root.minsize(900, 600)

        self.colors = DARK if self.config.theme == "dark" else LIGHT
        _apply_theme(self.root, self.colors)

        self.conversations: list[Conversation] = []
        self.filtered_conversations: list[Conversation] = []
        self.selected_conversation: Optional[Conversation] = None

        # Phase 2-4 backend integration
        self._project_threads: list[ProjectThread] = []
        self._thread_by_iid: dict[str, ProjectThread] = {}
        self.selected_thread: Optional[ProjectThread] = None
        self._project_summaries: dict[str, ProjectSummary] = {}  # keyed by thread.name
        self._project_reviews: dict[str, ProjectReview] = {}
        self.llm_client = default_client_from_config(self.config)
        self.llm_cache = LLMCache(enabled=self.config.get("llm_cache_enabled", True))

        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self._update_status("Ready — Open a Gemini Takeout export to begin")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        saved_x = self.config.get("window_x")
        saved_y = self.config.get("window_y")
        if saved_x is not None and saved_y is not None:
            self.root.geometry(f"+{saved_x}+{saved_y}")

    def run(self) -> None:
        self.root.mainloop()

    # ── Menu Bar ─────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root, bg=self.colors["bg_tertiary"],
                         fg=self.colors["fg"], activebackground=self.colors["accent"],
                         activeforeground="#ffffff", relief="flat")

        file_menu = tk.Menu(menubar, tearoff=0, bg=self.colors["bg_secondary"],
                           fg=self.colors["fg"], activebackground=self.colors["accent"],
                           activeforeground="#ffffff")
        file_menu.add_command(label="Open File...        Ctrl+O", command=self._open_file)
        file_menu.add_command(label="Open Folder...      Ctrl+Shift+O", command=self._open_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Export Results...    Ctrl+E", command=self._export_results)
        file_menu.add_separator()
        file_menu.add_command(label="Exit                Alt+F4", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=self.colors["bg_secondary"],
                           fg=self.colors["fg"], activebackground=self.colors["accent"],
                           activeforeground="#ffffff")
        view_menu.add_command(label="Toggle Theme        Ctrl+T", command=self._toggle_theme)
        view_menu.add_separator()
        view_menu.add_command(label="Increase Font       Ctrl++", command=lambda: self._change_font(1))
        view_menu.add_command(label="Decrease Font       Ctrl+-", command=lambda: self._change_font(-1))
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=self.colors["bg_secondary"],
                            fg=self.colors["fg"], activebackground=self.colors["accent"],
                            activeforeground="#ffffff")
        tools_menu.add_command(label="Run Diagnostics     F12", command=self._run_diagnostics)
        tools_menu.add_command(label="Find Duplicates → save report…",
                               command=self._save_dedup_report)
        tools_menu.add_separator()
        tools_menu.add_command(label="Reset Settings", command=self._reset_settings)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=self.colors["bg_secondary"],
                           fg=self.colors["fg"], activebackground=self.colors["accent"],
                           activeforeground="#ffffff")
        help_menu.add_command(label="Keyboard Shortcuts  F1", command=self._show_shortcuts)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # ── Main UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # Top toolbar
        toolbar = ttk.Frame(main, style="Tertiary.TFrame")
        toolbar.pack(fill="x", padx=0, pady=0)
        self._build_toolbar(toolbar)

        # Main paned area
        paned = ttk.PanedWindow(main, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # Left: sidebar with categories + conversation list
        left_frame = ttk.Frame(paned, width=380)
        paned.add(left_frame, weight=1)
        self._build_sidebar(left_frame)

        # Right: content area with notebook tabs
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=3)
        self._build_content_area(right_frame)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(main, textvariable=self.status_var,
                                    style="Status.TLabel", anchor="w")
        self.status_bar.pack(fill="x", side="bottom")

        # Progress bar (hidden by default, packs above status bar when needed)
        self.progress = ttk.Progressbar(main, mode="indeterminate",
                                        style="Horizontal.TProgressbar")

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        inner = ttk.Frame(parent, style="Tertiary.TFrame")
        inner.pack(fill="x", padx=8, pady=6)

        ttk.Button(inner, text="\u2750 Open File",
                   command=self._open_file).pack(side="left", padx=(0, 4))
        ttk.Button(inner, text="\u2751 Open Folder",
                   command=self._open_folder).pack(side="left", padx=(0, 4))

        ttk.Separator(inner, orient="vertical").pack(side="left", fill="y",
                                                      padx=8, pady=2)

        ttk.Label(inner, text="\u2315", style="Tertiary.TFrame",
                  font=("Segoe UI", 14)).pack(side="left", padx=(0, 4))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_conversations())
        search_entry = ttk.Entry(inner, textvariable=self.search_var, width=35)
        search_entry.pack(side="left", padx=(0, 8))
        search_entry.insert(0, "")

        self._search_placeholder = True

        self.filter_category = tk.StringVar(value="All Categories")
        self.category_combo = ttk.Combobox(
            inner, textvariable=self.filter_category,
            values=["All Categories"], state="readonly", width=22
        )
        self.category_combo.pack(side="left", padx=(0, 8))
        self.category_combo.bind("<<ComboboxSelected>>",
                                  lambda _: self._filter_conversations())

        self.filter_code_only = tk.BooleanVar(value=False)
        code_check = ttk.Checkbutton(
            inner, text="Code Only",
            variable=self.filter_code_only,
            command=self._filter_conversations,
        )
        code_check.pack(side="left", padx=(0, 8))

        self.count_label = ttk.Label(inner, text="0 conversations",
                                     style="Dim.TLabel")
        self.count_label.pack(side="right")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        # Category tree
        cat_frame = ttk.LabelFrame(parent, text="Categories", padding=4)
        cat_frame.pack(fill="x", padx=4, pady=(4, 2))

        self.cat_tree = ttk.Treeview(cat_frame, height=8, show="tree",
                                      selectmode="browse")
        cat_scroll = ttk.Scrollbar(cat_frame, orient="vertical",
                                    command=self.cat_tree.yview)
        self.cat_tree.configure(yscrollcommand=cat_scroll.set)
        self.cat_tree.pack(side="left", fill="both", expand=True)
        cat_scroll.pack(side="right", fill="y")
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)

        # Stats panel
        stats_frame = ttk.LabelFrame(parent, text="Statistics", padding=4)
        stats_frame.pack(fill="x", padx=4, pady=2)
        self.stats_text = tk.Text(stats_frame, height=4, wrap="word",
                                  bg=self.colors["bg_secondary"],
                                  fg=self.colors["fg_dim"],
                                  font=("Segoe UI", 9),
                                  relief="flat", borderwidth=0)
        self.stats_text.pack(fill="x")
        self.stats_text.configure(state="disabled")

        # Conversation list
        conv_frame = ttk.LabelFrame(parent, text="Conversations", padding=4)
        conv_frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        self.conv_tree = ttk.Treeview(
            conv_frame,
            columns=("date", "msgs", "code"),
            show="headings",
            selectmode="browse",
        )
        self.conv_tree.heading("date", text="Date")
        self.conv_tree.heading("msgs", text="Msgs")
        self.conv_tree.heading("code", text="Code")
        self.conv_tree.column("date", width=80, minwidth=60)
        self.conv_tree.column("msgs", width=40, minwidth=30, anchor="center")
        self.conv_tree.column("code", width=40, minwidth=30, anchor="center")

        conv_scroll = ttk.Scrollbar(conv_frame, orient="vertical",
                                     command=self.conv_tree.yview)
        self.conv_tree.configure(yscrollcommand=conv_scroll.set)
        self.conv_tree.pack(side="left", fill="both", expand=True)
        conv_scroll.pack(side="right", fill="y")
        self.conv_tree.bind("<<TreeviewSelect>>", self._on_conversation_select)

    def _build_content_area(self, parent: ttk.Frame) -> None:
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Conversation viewer
        conv_tab = ttk.Frame(self.notebook)
        self.notebook.add(conv_tab, text="  \u2709 Conversation  ")
        self._build_conversation_tab(conv_tab)

        # Tab 2: Code Extractor
        code_tab = ttk.Frame(self.notebook)
        self.notebook.add(code_tab, text="  \u2702 Code Extractor  ")
        self._build_code_tab(code_tab)

        # Tab 3: Projects / Apps
        projects_tab = ttk.Frame(self.notebook)
        self.notebook.add(projects_tab, text="  \u2692 Projects & Apps  ")
        self._build_projects_tab(projects_tab)

        # Tab 4: Timeline
        timeline_tab = ttk.Frame(self.notebook)
        self.notebook.add(timeline_tab, text="  \u29d7 Timeline  ")
        self._build_timeline_tab(timeline_tab)

        # Tab 5: Overview / Dashboard
        overview_tab = ttk.Frame(self.notebook)
        self.notebook.add(overview_tab, text="  \u2637 Overview  ")
        self._build_overview_tab(overview_tab)

    def _build_conversation_tab(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill="x", padx=8, pady=(8, 4))

        self.conv_title_var = tk.StringVar(value="Select a conversation")
        ttk.Label(header, textvariable=self.conv_title_var,
                  style="Heading.TLabel").pack(side="left")

        self.conv_meta_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.conv_meta_var,
                  style="Dim.TLabel").pack(side="right")

        # Tags frame
        self.tags_frame = ttk.Frame(parent)
        self.tags_frame.pack(fill="x", padx=8, pady=(0, 4))

        # Message display
        msg_frame = ttk.Frame(parent)
        msg_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.msg_text = tk.Text(
            msg_frame,
            wrap="word",
            bg=self.colors["bg_secondary"],
            fg=self.colors["fg"],
            font=("Segoe UI", self.config.get("font_size", 11)),
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=8,
            selectbackground=self.colors["selection"],
            insertbackground=self.colors["fg"],
            spacing1=2,
            spacing3=2,
        )
        msg_scroll = ttk.Scrollbar(msg_frame, orient="vertical",
                                    command=self.msg_text.yview)
        self.msg_text.configure(yscrollcommand=msg_scroll.set)
        self.msg_text.pack(side="left", fill="both", expand=True)
        msg_scroll.pack(side="right", fill="y")

        self.msg_text.tag_configure("user_header", foreground=self.colors["accent_light"],
                                     font=("Segoe UI", 11, "bold"), spacing1=12)
        self.msg_text.tag_configure("model_header", foreground=self.colors["success"],
                                     font=("Segoe UI", 11, "bold"), spacing1=12)
        self.msg_text.tag_configure("user_msg", foreground=self.colors["fg"],
                                     lmargin1=16, lmargin2=16)
        self.msg_text.tag_configure("model_msg", foreground=self.colors["fg"],
                                     lmargin1=16, lmargin2=16)
        self.msg_text.tag_configure("code_block", background=self.colors["code_bg"],
                                     foreground=self.colors["code_fg"],
                                     font=("Consolas", self.config.get("code_font_size", 12)),
                                     lmargin1=24, lmargin2=24, spacing1=4, spacing3=4)
        self.msg_text.tag_configure("code_lang", foreground=self.colors["fg_dim"],
                                     font=("Consolas", 9), lmargin1=24)
        self.msg_text.tag_configure("timestamp", foreground=self.colors["fg_dim"],
                                     font=("Segoe UI", 9))
        self.msg_text.tag_configure("separator", foreground=self.colors["border"])

        self.msg_text.configure(state="disabled")

    def _build_code_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Code Blocks Found",
                  style="Heading.TLabel").pack(side="left")

        self.code_count_var = tk.StringVar(value="0 blocks")
        ttk.Label(top, textvariable=self.code_count_var,
                  style="Dim.TLabel").pack(side="right")

        # ── Filter row 1: Language, Conversation, Search ──
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill="x", padx=8, pady=(0, 2))

        ttk.Label(filter_frame, text="Language:").pack(side="left", padx=(0, 4))
        self.code_lang_filter = tk.StringVar(value="All")
        self.code_lang_combo = ttk.Combobox(
            filter_frame, textvariable=self.code_lang_filter,
            values=["All"], state="readonly", width=14
        )
        self.code_lang_combo.pack(side="left", padx=(0, 10))
        self.code_lang_combo.bind("<<ComboboxSelected>>",
                                   lambda _: self._filter_code_blocks())

        ttk.Label(filter_frame, text="Conversation:").pack(side="left", padx=(0, 4))
        self.code_conv_filter = tk.StringVar(value="All")
        self.code_conv_combo = ttk.Combobox(
            filter_frame, textvariable=self.code_conv_filter,
            values=["All"], state="readonly", width=28
        )
        self.code_conv_combo.pack(side="left", padx=(0, 10))
        self.code_conv_combo.bind("<<ComboboxSelected>>",
                                   lambda _: self._filter_code_blocks())

        ttk.Label(filter_frame, text="\u2315").pack(side="left", padx=(0, 4))
        self.code_search_var = tk.StringVar()
        self.code_search_var.trace_add("write", lambda *_: self._filter_code_blocks())
        code_search = ttk.Entry(filter_frame, textvariable=self.code_search_var, width=20)
        code_search.pack(side="left", padx=(0, 4))

        # ── Filter row 2: Min lines, activity type, action buttons ──
        filter_frame2 = ttk.Frame(parent)
        filter_frame2.pack(fill="x", padx=8, pady=(0, 4))

        ttk.Label(filter_frame2, text="Min lines:").pack(side="left", padx=(0, 4))
        self.code_min_lines = tk.IntVar(value=0)
        min_lines_spin = ttk.Spinbox(
            filter_frame2, from_=0, to=9999, width=6,
            textvariable=self.code_min_lines,
            command=self._filter_code_blocks,
        )
        min_lines_spin.pack(side="left", padx=(0, 10))

        ttk.Label(filter_frame2, text="Activity:").pack(side="left", padx=(0, 4))
        self.code_activity_filter = tk.StringVar(value="All")
        self.code_activity_combo = ttk.Combobox(
            filter_frame2, textvariable=self.code_activity_filter,
            values=["All"], state="readonly", width=18
        )
        self.code_activity_combo.pack(side="left", padx=(0, 10))
        self.code_activity_combo.bind("<<ComboboxSelected>>",
                                       lambda _: self._filter_code_blocks())

        # Action buttons (right side)
        ttk.Button(filter_frame2, text="\u2398 Copy Selected",
                   command=self._copy_selected_code,
                   style="Accent.TButton").pack(side="right", padx=(4, 0))
        ttk.Button(filter_frame2, text="Copy All Visible",
                   command=self._copy_all_visible_code).pack(side="right", padx=(4, 0))
        ttk.Button(filter_frame2, text="Export Visible...",
                   command=self._export_visible_code).pack(side="right", padx=(4, 0))

        # Split: code list on top, code preview below
        paned = ttk.PanedWindow(parent, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Code blocks list
        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=1)

        self.code_tree = ttk.Treeview(
            list_frame,
            columns=("language", "conversation", "lines", "preview"),
            show="headings",
            selectmode="extended",
        )
        self.code_tree.heading("language", text="Language")
        self.code_tree.heading("conversation", text="From Conversation")
        self.code_tree.heading("lines", text="Lines")
        self.code_tree.heading("preview", text="Preview")
        self.code_tree.column("language", width=90, minwidth=60)
        self.code_tree.column("conversation", width=250, minwidth=120)
        self.code_tree.column("lines", width=50, minwidth=40, anchor="center")
        self.code_tree.column("preview", width=400, minwidth=200)

        code_list_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                          command=self.code_tree.yview)
        self.code_tree.configure(yscrollcommand=code_list_scroll.set)
        self.code_tree.pack(side="left", fill="both", expand=True)
        code_list_scroll.pack(side="right", fill="y")
        self.code_tree.bind("<<TreeviewSelect>>", self._on_code_block_select)

        # Code preview
        preview_frame = ttk.Frame(paned)
        paned.add(preview_frame, weight=2)

        preview_header = ttk.Frame(preview_frame)
        preview_header.pack(fill="x", pady=(4, 0))

        self.code_preview_info = tk.StringVar(value="Select a code block to preview")
        ttk.Label(preview_header, textvariable=self.code_preview_info,
                  style="Dim.TLabel").pack(side="left")

        ttk.Button(preview_header, text="\u2398 Copy This Block",
                   command=self._copy_selected_code,
                   style="Accent.TButton").pack(side="right")

        self.code_preview = tk.Text(
            preview_frame,
            wrap="none",
            bg=self.colors["code_bg"],
            fg=self.colors["code_fg"],
            font=("Consolas", self.config.get("code_font_size", 12)),
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=8,
            selectbackground=self.colors["selection"],
            insertbackground=self.colors["fg"],
        )
        code_h_scroll = ttk.Scrollbar(preview_frame, orient="horizontal",
                                       command=self.code_preview.xview)
        code_v_scroll = ttk.Scrollbar(preview_frame, orient="vertical",
                                       command=self.code_preview.yview)
        self.code_preview.configure(xscrollcommand=code_h_scroll.set,
                                     yscrollcommand=code_v_scroll.set)
        code_v_scroll.pack(side="right", fill="y")
        code_h_scroll.pack(side="bottom", fill="x")
        self.code_preview.pack(fill="both", expand=True)
        self.code_preview.configure(state="disabled")

        self._all_code_blocks: list[dict] = []
        self._visible_code_blocks: list[dict] = []

    def _build_projects_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Detected Projects & Apps",
                  style="Heading.TLabel").pack(side="left")

        self.project_count_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.project_count_var,
                  style="Dim.TLabel").pack(side="right")

        # ── Project action bar ──
        proj_actions = ttk.Frame(parent)
        proj_actions.pack(fill="x", padx=8, pady=(0, 4))

        ttk.Button(proj_actions, text="Export Selected (code only)",
                   command=self._export_selected_projects).pack(side="left", padx=(0, 6))
        ttk.Button(proj_actions, text="Export All (code only)",
                   command=self._export_all_projects).pack(side="left", padx=(0, 6))
        ttk.Button(proj_actions, text="Copy Selected Code",
                   command=self._copy_selected_project_code).pack(side="left", padx=(0, 6))
        ttk.Button(proj_actions, text="Export Claude-ready Bundles…",
                   command=self._export_claude_bundles_selected,
                   style="Accent.TButton").pack(side="left", padx=(12, 6))

        ttk.Label(proj_actions, text="Shift/Ctrl+click for multi-select",
                  style="Dim.TLabel").pack(side="right")

        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Project list — multi-select
        proj_list_frame = ttk.Frame(paned)
        paned.add(proj_list_frame, weight=1)

        self.proj_tree = ttk.Treeview(
            proj_list_frame,
            columns=("name", "convs", "span", "blocks", "langs"),
            show="headings",
            selectmode="extended",
        )
        self.proj_tree.heading("name", text="Project")
        self.proj_tree.heading("convs", text="Convs")
        self.proj_tree.heading("span", text="Span")
        self.proj_tree.heading("blocks", text="Code")
        self.proj_tree.heading("langs", text="Languages")
        self.proj_tree.column("name", width=240, minwidth=120)
        self.proj_tree.column("convs", width=60, anchor="center")
        self.proj_tree.column("span", width=70, anchor="center")
        self.proj_tree.column("blocks", width=60, anchor="center")
        self.proj_tree.column("langs", width=180)

        proj_scroll = ttk.Scrollbar(proj_list_frame, orient="vertical",
                                     command=self.proj_tree.yview)
        self.proj_tree.configure(yscrollcommand=proj_scroll.set)
        self.proj_tree.pack(side="left", fill="both", expand=True)
        proj_scroll.pack(side="right", fill="y")
        self.proj_tree.bind("<<TreeviewSelect>>", self._on_project_select)

        # Project detail
        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)

        # Per-project LLM/bundle action bar (sits above the detail Text widget)
        detail_actions = ttk.Frame(detail_frame)
        detail_actions.pack(fill="x", padx=4, pady=(4, 0))
        self.proj_llm_status = tk.StringVar(
            value=("LLM ready" if llm_is_available() else f"LLM idle — set {LLM_ENV_KEY} to enable")
        )
        ttk.Button(detail_actions, text="Summarize (LLM)",
                   command=self._llm_summarize_selected_project).pack(side="left", padx=(0, 4))
        ttk.Button(detail_actions, text="Deep Review (LLM)",
                   command=self._llm_review_selected_project).pack(side="left", padx=(0, 4))
        ttk.Button(detail_actions, text="Export Claude Bundle…",
                   command=self._export_claude_bundle_single).pack(side="left", padx=(0, 4))
        ttk.Label(detail_actions, textvariable=self.proj_llm_status,
                  style="Dim.TLabel").pack(side="right")

        text_frame = ttk.Frame(detail_frame)
        text_frame.pack(fill="both", expand=True)

        self.proj_detail = tk.Text(
            text_frame,
            wrap="word",
            bg=self.colors["bg_secondary"],
            fg=self.colors["fg"],
            font=("Segoe UI", self.config.get("font_size", 11)),
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=8,
        )
        proj_detail_scroll = ttk.Scrollbar(text_frame, orient="vertical",
                                            command=self.proj_detail.yview)
        self.proj_detail.configure(yscrollcommand=proj_detail_scroll.set)
        self.proj_detail.pack(side="left", fill="both", expand=True)
        proj_detail_scroll.pack(side="right", fill="y")

        self.proj_detail.tag_configure("heading", font=("Segoe UI", 13, "bold"),
                                        foreground=self.colors["accent_light"],
                                        spacing1=8)
        self.proj_detail.tag_configure("subheading", font=("Segoe UI", 11, "bold"),
                                        foreground=self.colors["fg_bright"],
                                        spacing1=6)
        self.proj_detail.tag_configure("code", background=self.colors["code_bg"],
                                        foreground=self.colors["code_fg"],
                                        font=("Consolas", self.config.get("code_font_size", 12)),
                                        lmargin1=16, lmargin2=16)
        self.proj_detail.tag_configure("dim", foreground=self.colors["fg_dim"])
        self.proj_detail.configure(state="disabled")

        self._project_data: dict = {}

    def _build_timeline_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="Activity over time",
                  style="Heading.TLabel").pack(side="left")

        ttk.Label(top, text="Bucket:").pack(side="left", padx=(20, 4))
        self.timeline_period = tk.StringVar(value="month")
        period_combo = ttk.Combobox(
            top, textvariable=self.timeline_period,
            values=["day", "month", "year"], state="readonly", width=8,
        )
        period_combo.pack(side="left")
        period_combo.bind("<<ComboboxSelected>>", lambda _: self._rebuild_timeline())

        self.timeline_summary_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.timeline_summary_var,
                  style="Dim.TLabel").pack(side="right")

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.timeline_tree = ttk.Treeview(
            tree_frame,
            columns=("period", "total", "bar", "top_categories"),
            show="headings",
            selectmode="browse",
        )
        self.timeline_tree.heading("period", text="Period")
        self.timeline_tree.heading("total", text="Conversations")
        self.timeline_tree.heading("bar", text="")
        self.timeline_tree.heading("top_categories", text="Top categories")
        self.timeline_tree.column("period", width=110, minwidth=80)
        self.timeline_tree.column("total", width=110, minwidth=80, anchor="center")
        self.timeline_tree.column("bar", width=200, minwidth=100)
        self.timeline_tree.column("top_categories", width=500, minwidth=200)

        tl_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                   command=self.timeline_tree.yview)
        self.timeline_tree.configure(yscrollcommand=tl_scroll.set)
        self.timeline_tree.pack(side="left", fill="both", expand=True)
        tl_scroll.pack(side="right", fill="y")

    def _rebuild_timeline(self) -> None:
        if not hasattr(self, "timeline_tree"):
            return
        self.timeline_tree.delete(*self.timeline_tree.get_children())
        if not self.conversations:
            self.timeline_summary_var.set("")
            return
        period = self.timeline_period.get() if hasattr(self, "timeline_period") else "month"
        buckets = build_timeline(self.conversations, period=period)
        max_total = max((b["total"] for b in buckets), default=1)
        peak = max(buckets, key=lambda b: b["total"]) if buckets else None

        for b in buckets:
            bar_len = int((b["total"] / max_total) * 40) if max_total else 0
            bar = "█" * bar_len + "░" * (40 - bar_len)
            top_cats = ", ".join(
                f"{c} ({n})" for c, n in list(b.get("by_category", {}).items())[:4]
            )
            self.timeline_tree.insert("", "end",
                                       values=(b["period"], b["total"], bar, top_cats))
        if peak:
            self.timeline_summary_var.set(
                f"{len(buckets)} buckets · peak {peak['period']} = {peak['total']:,} conversations"
            )

    def _build_overview_tab(self, parent: ttk.Frame) -> None:
        self.overview_text = tk.Text(
            parent,
            wrap="word",
            bg=self.colors["bg_secondary"],
            fg=self.colors["fg"],
            font=("Segoe UI", self.config.get("font_size", 11)),
            relief="flat",
            borderwidth=0,
            padx=20,
            pady=16,
        )
        overview_scroll = ttk.Scrollbar(parent, orient="vertical",
                                         command=self.overview_text.yview)
        self.overview_text.configure(yscrollcommand=overview_scroll.set)
        self.overview_text.pack(side="left", fill="both", expand=True)
        overview_scroll.pack(side="right", fill="y")

        self.overview_text.tag_configure("title", font=("Segoe UI", 20, "bold"),
                                          foreground=self.colors["accent_light"],
                                          spacing1=8, spacing3=12)
        self.overview_text.tag_configure("heading", font=("Segoe UI", 14, "bold"),
                                          foreground=self.colors["fg_bright"],
                                          spacing1=16, spacing3=4)
        self.overview_text.tag_configure("subheading", font=("Segoe UI", 12, "bold"),
                                          foreground=self.colors["accent_light"],
                                          spacing1=8, spacing3=2)
        self.overview_text.tag_configure("stat", font=("Consolas", 12),
                                          foreground=self.colors["success"],
                                          lmargin1=20)
        self.overview_text.tag_configure("body", lmargin1=20, lmargin2=20)
        self.overview_text.tag_configure("dim", foreground=self.colors["fg_dim"],
                                          lmargin1=20)

        self.overview_text.configure(state="disabled")
        self._show_welcome()

    # ── Keyboard Shortcuts ───────────────────────────────────────────

    def _bind_keys(self) -> None:
        self.root.bind("<Control-o>", lambda e: self._open_file())
        self.root.bind("<Control-O>", lambda e: self._open_folder())
        self.root.bind("<Control-e>", lambda e: self._export_results())
        self.root.bind("<Control-t>", lambda e: self._toggle_theme())
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<Control-plus>", lambda e: self._change_font(1))
        self.root.bind("<Control-minus>", lambda e: self._change_font(-1))
        self.root.bind("<Control-equal>", lambda e: self._change_font(1))
        self.root.bind("<F1>", lambda e: self._show_shortcuts())
        self.root.bind("<F12>", lambda e: self._run_diagnostics())
        self.root.bind("<Escape>", lambda e: self._clear_search())

    def _focus_search(self) -> None:
        for child in self.root.winfo_children():
            self._find_and_focus_search(child)

    def _find_and_focus_search(self, widget) -> None:
        if isinstance(widget, ttk.Entry):
            widget.focus_set()
            widget.select_range(0, "end")
            return
        for child in widget.winfo_children():
            self._find_and_focus_search(child)

    def _clear_search(self) -> None:
        self.search_var.set("")

    # ── File Operations ──────────────────────────────────────────────

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Gemini Export",
            filetypes=[
                ("All Supported", "*.zip *.json *.html *.htm"),
                ("ZIP Archives", "*.zip"),
                ("HTML Files", "*.html *.htm"),
                ("JSON Files", "*.json"),
                ("All Files", "*.*"),
            ],
            initialdir=self.config.get("last_open_path") or str(Path.home()),
        )
        if path:
            self._load_data(Path(path))

    def _open_folder(self) -> None:
        path = filedialog.askdirectory(
            title="Open Gemini Export Folder",
            initialdir=self.config.get("last_open_path") or str(Path.home()),
        )
        if path:
            self._load_data(Path(path))

    def _load_data(self, path: Path) -> None:
        self.config.set("last_open_path", str(path.parent))
        self.config.add_recent_file(str(path))
        self.config.save()

        self._update_status(f"Loading {path.name}...")
        self.progress.pack(fill="x", padx=8, pady=2, side="bottom", before=self.status_bar)
        self.progress.start(15)

        def _worker():
            try:
                convs = parse_input(path)
                convs = categorize_all(convs)
                convs.sort(key=lambda c: c.create_time or datetime.min, reverse=True)
                self.root.after(0, lambda: self._on_data_loaded(convs, path))
            except Exception as e:
                logger.error("Load failed: %s", e, exc_info=True)
                self.root.after(0, lambda: self._on_load_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_data_loaded(self, convs: list[Conversation], path: Path) -> None:
        self.progress.stop()
        self.progress.pack_forget()

        self.conversations = convs
        self.filtered_conversations = list(convs)
        self._rebuild_all()
        self._update_status(
            f"Loaded {len(convs)} conversations from {path.name}"
        )

    def _on_load_error(self, error: str) -> None:
        self.progress.stop()
        self.progress.pack_forget()
        self._update_status(f"Error: {error}")
        messagebox.showerror("Load Error", f"Failed to load data:\n{error}")

    # ── Rebuild UI After Data Load ───────────────────────────────────

    def _rebuild_all(self) -> None:
        self._rebuild_categories()
        self._rebuild_conversation_list()
        self._rebuild_code_blocks()
        self._rebuild_projects()
        self._rebuild_timeline()
        self._rebuild_overview()
        self._update_stats()

    def _rebuild_categories(self) -> None:
        self.cat_tree.delete(*self.cat_tree.get_children())

        cat_counts: dict[str, dict[str, int]] = {}
        for conv in self.conversations:
            cat = conv.category
            sub = conv.subcategory or "Other"
            if cat not in cat_counts:
                cat_counts[cat] = {}
            cat_counts[cat][sub] = cat_counts[cat].get(sub, 0) + 1

        all_id = self.cat_tree.insert("", "end",
                                       text=f"All ({len(self.conversations)})",
                                       values=("all",))

        categories = ["All Categories"]
        for cat_name in sorted(cat_counts.keys()):
            subs = cat_counts[cat_name]
            total = sum(subs.values())
            cat_id = self.cat_tree.insert("", "end",
                                           text=f"{cat_name} ({total})")
            categories.append(cat_name)
            for sub_name in sorted(subs.keys()):
                self.cat_tree.insert(cat_id, "end",
                                      text=f"{sub_name} ({subs[sub_name]})")

        self.category_combo["values"] = categories
        self.filter_category.set("All Categories")

    def _rebuild_conversation_list(self) -> None:
        self.conv_tree.delete(*self.conv_tree.get_children())

        for conv in self.filtered_conversations:
            date_str = ""
            if conv.create_time:
                date_str = conv.create_time.strftime("%Y-%m-%d")
            code_str = "\u2713" if conv.has_code else ""

            title = conv.title[:60]
            if len(conv.title) > 60:
                title += "..."

            self.conv_tree.insert("", "end",
                                   text=title,
                                   values=(date_str, conv.message_count, code_str),
                                   iid=conv.id)

        self.count_label.configure(
            text=f"{len(self.filtered_conversations)} conversations"
        )

    def _rebuild_code_blocks(self) -> None:
        self._all_code_blocks = []
        # Store the parent conversation ref and activity type alongside each block
        for conv in self.conversations:
            for block in conv.all_code_blocks:
                block["_activity_type"] = conv.activity_type
                self._all_code_blocks.append(block)

        # Populate filter dropdowns
        langs = sorted(set(b["language"] for b in self._all_code_blocks))
        self.code_lang_combo["values"] = ["All"] + langs
        self.code_lang_filter.set("All")

        conv_titles = sorted(set(
            b.get("conversation_title", "")[:50]
            for b in self._all_code_blocks if b.get("conversation_title")
        ))
        self.code_conv_combo["values"] = ["All"] + conv_titles
        self.code_conv_filter.set("All")

        act_types = sorted(set(
            b.get("_activity_type", "") for b in self._all_code_blocks
            if b.get("_activity_type")
        ))
        self.code_activity_combo["values"] = ["All"] + act_types
        self.code_activity_filter.set("All")

        self._filter_code_blocks()

    def _filter_code_blocks(self) -> None:
        lang_filter = self.code_lang_filter.get()
        conv_filter = self.code_conv_filter.get()
        search_text = self.code_search_var.get().lower().strip()
        activity_filter = self.code_activity_filter.get()
        try:
            min_lines = self.code_min_lines.get()
        except (tk.TclError, ValueError):
            min_lines = 0

        filtered = []
        for b in self._all_code_blocks:
            if lang_filter != "All" and b["language"] != lang_filter:
                continue
            if conv_filter != "All":
                title = b.get("conversation_title", "")[:50]
                if title != conv_filter:
                    continue
            if activity_filter != "All" and b.get("_activity_type", "") != activity_filter:
                continue
            line_count = b["code"].count("\n") + 1
            if min_lines > 0 and line_count < min_lines:
                continue
            if search_text and search_text not in b["code"].lower():
                continue
            filtered.append(b)

        self._visible_code_blocks = filtered

        self.code_tree.delete(*self.code_tree.get_children())
        for i, block in enumerate(self._visible_code_blocks):
            lines = block["code"].count("\n") + 1
            preview = block["code"][:80].replace("\n", " ").strip()
            conv_title = block.get("conversation_title", "")[:40]

            self.code_tree.insert("", "end", iid=str(i),
                                   values=(block["language"], conv_title,
                                           lines, preview))

        self.code_count_var.set(f"{len(self._visible_code_blocks)} blocks")

    def _rebuild_projects(self) -> None:
        """Use union-find reconstruction to stitch fragmented activity entries
        into multi-conversation project threads (Phase 2 backend)."""
        self._project_data = {}
        self._thread_by_iid = {}
        self._pdata_key_by_iid: dict[str, str] = {}

        try:
            self._project_threads = reconstruct_projects(self.conversations, min_size=2)
        except Exception as e:
            logger.error("Project reconstruction failed: %s", e, exc_info=True)
            self._project_threads = []

        self.proj_tree.delete(*self.proj_tree.get_children())
        seen_keys: dict[str, int] = {}
        for i, t in enumerate(self._project_threads):
            iid = f"t{i}"
            self._thread_by_iid[iid] = t

            # Back-compat: _project_data[display_name] -> list[Conversation],
            # used by the existing code-only export/copy paths. Disambiguate
            # duplicate names. We also remember iid -> key so selection lookups
            # don't return raw iids and silently miss the dict.
            key = t.name or f"Project {i}"
            if key in seen_keys:
                seen_keys[key] += 1
                key = f"{key} ({seen_keys[key]})"
            else:
                seen_keys[key] = 1
            self._project_data[key] = t.conversations
            self._pdata_key_by_iid[iid] = key

            span = f"{t.span_days}d" if t.span_days is not None else "?"
            langs = ", ".join(t.languages) if t.languages else ""
            self.proj_tree.insert(
                "", "end", iid=iid,
                values=(t.name[:60], t.size, span, t.code_block_count, langs),
            )

        coding_count = sum(
            1 for c in self.conversations
            if c.category == "Coding & Programming" or c.coding_project_name
        )
        total = len(self._project_threads)
        self.project_count_var.set(
            f"{total} reconstructed project{'s' if total != 1 else ''} "
            f"(from {coding_count} coding conversations)"
        )

    def _rebuild_overview(self) -> None:
        self.overview_text.configure(state="normal")
        self.overview_text.delete("1.0", "end")

        total = len(self.conversations)
        if total == 0:
            self._show_welcome()
            return

        coding = len([c for c in self.conversations if c.category == "Coding & Programming"])
        apps = len([c for c in self.conversations
                    if any("app-creation" in t for t in c.tags)])
        code_blocks = len(self._all_code_blocks)
        projects = len(self._project_data)

        cat_counts = {}
        for c in self.conversations:
            cat_counts[c.category] = cat_counts.get(c.category, 0) + 1

        lang_counts = {}
        for b in self._all_code_blocks:
            lang_counts[b["language"]] = lang_counts.get(b["language"], 0) + 1

        self.overview_text.insert("end", "Gemini Export Analysis\n", "title")
        self.overview_text.insert("end", "\nQuick Stats\n", "heading")
        self.overview_text.insert("end", f"  Total Conversations:     {total}\n", "stat")
        self.overview_text.insert("end", f"  Coding Conversations:    {coding}\n", "stat")
        self.overview_text.insert("end", f"  App/Program Creations:   {apps}\n", "stat")
        self.overview_text.insert("end", f"  Total Code Blocks:       {code_blocks}\n", "stat")
        self.overview_text.insert("end", f"  Detected Projects:       {projects}\n", "stat")

        self.overview_text.insert("end", "\nCategories Breakdown\n", "heading")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            bar = "\u2588" * int(pct / 3) + "\u2591" * (33 - int(pct / 3))
            self.overview_text.insert("end",
                                       f"  {cat:<30} {count:>4}  ({pct:5.1f}%)  {bar}\n", "body")

        if lang_counts:
            self.overview_text.insert("end", "\nProgramming Languages\n", "heading")
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                bar = "\u2588" * min(count, 40)
                self.overview_text.insert("end",
                                           f"  {lang:<20} {count:>4}  {bar}\n", "body")

        if self._project_data:
            self.overview_text.insert("end", "\nDetected Projects & Apps\n", "heading")
            for name in sorted(self._project_data.keys()):
                convs = self._project_data[name]
                blocks = sum(len(c.all_code_blocks) for c in convs)
                self.overview_text.insert("end",
                                           f"  \u25B8 {name}  ({len(convs)} convs, {blocks} code blocks)\n",
                                           "body")

        dates = [c.create_time for c in self.conversations if c.create_time]
        if dates:
            self.overview_text.insert("end", "\nTimeline\n", "heading")
            earliest = min(dates).strftime("%Y-%m-%d")
            latest = max(dates).strftime("%Y-%m-%d")
            self.overview_text.insert("end",
                                       f"  First conversation:  {earliest}\n", "body")
            self.overview_text.insert("end",
                                       f"  Last conversation:   {latest}\n", "body")

        self.overview_text.configure(state="disabled")

    def _show_welcome(self) -> None:
        self.overview_text.configure(state="normal")
        self.overview_text.delete("1.0", "end")

        self.overview_text.insert("end", f"{APP_NAME}\n", "title")
        self.overview_text.insert("end", "\nGetting Started\n", "heading")
        self.overview_text.insert("end",
            "1. Go to Google Takeout (takeout.google.com)\n", "body")
        self.overview_text.insert("end",
            "2. Select 'Gemini Apps' and download your data\n", "body")
        self.overview_text.insert("end",
            "3. Use File > Open to load the exported JSON or ZIP\n", "body")
        self.overview_text.insert("end", "\nFeatures\n", "heading")
        self.overview_text.insert("end",
            "\u25B8  Automatic categorization of all conversations\n", "body")
        self.overview_text.insert("end",
            "\u25B8  Detect coding projects, apps, and programs you built\n", "body")
        self.overview_text.insert("end",
            "\u25B8  Extract all code blocks with one-click copy\n", "body")
        self.overview_text.insert("end",
            "\u25B8  Filter by category, language, or search terms\n", "body")
        self.overview_text.insert("end",
            "\u25B8  Export results for use in other tools\n", "body")
        self.overview_text.insert("end", "\nKeyboard Shortcuts\n", "heading")
        self.overview_text.insert("end",
            "  Ctrl+O    Open file          Ctrl+F    Search\n", "dim")
        self.overview_text.insert("end",
            "  Ctrl+E    Export results      Ctrl+T    Toggle theme\n", "dim")
        self.overview_text.insert("end",
            "  Ctrl++/-  Font size           F12       Diagnostics\n", "dim")
        self.overview_text.insert("end",
            "  F1        Show shortcuts      Esc       Clear search\n", "dim")

        self.overview_text.configure(state="disabled")

    def _update_stats(self) -> None:
        self.stats_text.configure(state="normal")
        self.stats_text.delete("1.0", "end")

        total = len(self.conversations)
        coding = len([c for c in self.conversations if c.category == "Coding & Programming"])
        code_blocks = len(self._all_code_blocks)

        self.stats_text.insert("end",
            f"Total: {total}  |  Coding: {coding}  |  Code blocks: {code_blocks}")

        self.stats_text.configure(state="disabled")

    # ── Selection Handlers ───────────────────────────────────────────

    def _on_category_select(self, event) -> None:
        selection = self.cat_tree.selection()
        if not selection:
            return
        text = self.cat_tree.item(selection[0], "text")
        if text.startswith("All"):
            self.filter_category.set("All Categories")
        else:
            cat_name = re.sub(r'\s*\(\d+\)$', '', text)
            if cat_name in [c.category for c in self.conversations]:
                self.filter_category.set(cat_name)
            else:
                parent = self.cat_tree.parent(selection[0])
                if parent:
                    parent_text = self.cat_tree.item(parent, "text")
                    parent_cat = re.sub(r'\s*\(\d+\)$', '', parent_text)
                    self.filter_category.set(parent_cat)

        self._filter_conversations()

    def _on_conversation_select(self, event) -> None:
        selection = self.conv_tree.selection()
        if not selection:
            return
        conv_id = selection[0]
        conv = next((c for c in self.conversations if c.id == conv_id), None)
        if conv:
            self.selected_conversation = conv
            self._display_conversation(conv)

    def _on_code_block_select(self, event) -> None:
        selection = self.code_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        if 0 <= idx < len(self._visible_code_blocks):
            block = self._visible_code_blocks[idx]
            self._display_code_preview(block)

    def _on_project_select(self, event) -> None:
        selection = self.proj_tree.selection()
        if not selection:
            return
        iid = selection[0]
        thread = self._thread_by_iid.get(iid)
        if thread is not None:
            self.selected_thread = thread
            self._display_project(thread)

    # ── Display Helpers ──────────────────────────────────────────────

    def _display_conversation(self, conv: Conversation) -> None:
        self.conv_title_var.set(conv.title[:80])

        meta_parts = []
        if conv.create_time:
            meta_parts.append(conv.create_time.strftime("%Y-%m-%d %H:%M"))
        meta_parts.append(f"{conv.message_count} messages")
        if conv.category:
            meta_parts.append(conv.category)
        self.conv_meta_var.set(" | ".join(meta_parts))

        for w in self.tags_frame.winfo_children():
            w.destroy()
        for tag in conv.tags[:10]:
            lbl = ttk.Label(self.tags_frame, text=tag, style="Tag.TLabel")
            lbl.pack(side="left", padx=2, pady=2)

        self.msg_text.configure(state="normal")
        self.msg_text.delete("1.0", "end")

        for msg in conv.messages:
            if msg.role == "user":
                header_tag = "user_header"
                msg_tag = "user_msg"
                prefix = "\u25B6 You"
            else:
                header_tag = "model_header"
                msg_tag = "model_msg"
                prefix = "\u25C6 Gemini"

            self.msg_text.insert("end", f"{prefix}", header_tag)
            if msg.timestamp:
                self.msg_text.insert("end",
                    f"  {msg.timestamp.strftime('%H:%M')}", "timestamp")
            self.msg_text.insert("end", "\n")

            if msg.attachments:
                self.msg_text.insert(
                    "end",
                    f"  📎 attachments: {', '.join(msg.attachments)}\n",
                    "timestamp",
                )

            text = msg.text or ""
            parts = re.split(r'(```\w*\n?[\s\S]*?```)', text)

            for part in parts:
                code_match = re.match(r'```(\w*)\n?([\s\S]*?)```', part)
                if code_match:
                    lang = code_match.group(1) or "code"
                    code = code_match.group(2)
                    self.msg_text.insert("end", f"  [{lang}]\n", "code_lang")
                    self.msg_text.insert("end", code + "\n", "code_block")
                    self.msg_text.insert("end", "\n")
                else:
                    self.msg_text.insert("end", part.strip() + "\n", msg_tag)

            self.msg_text.insert("end", "\n" + "\u2500" * 60 + "\n", "separator")

        self.msg_text.configure(state="disabled")
        self.msg_text.see("1.0")

        self.notebook.select(0)

    def _display_code_preview(self, block: dict) -> None:
        self.code_preview.configure(state="normal")
        self.code_preview.delete("1.0", "end")
        self.code_preview.insert("1.0", block["code"])
        self.code_preview.configure(state="disabled")

        lines = block["code"].count("\n") + 1
        self.code_preview_info.set(
            f"{block['language']}  |  {lines} lines  |  "
            f"From: {block.get('conversation_title', 'Unknown')[:50]}"
        )

    def _display_project(self, thread: ProjectThread) -> None:
        self.proj_detail.configure(state="normal")
        self.proj_detail.delete("1.0", "end")

        self.proj_detail.insert("end", f"{thread.name}\n", "heading")

        span = f"{thread.span_days}d" if thread.span_days is not None else "unknown"
        when = ""
        if thread.first_activity and thread.last_activity:
            when = f"  |  {thread.first_activity.date()} \u2192 {thread.last_activity.date()}"
        self.proj_detail.insert(
            "end",
            f"{thread.size} fragments stitched  |  span {span}  |  "
            f"{thread.code_block_count} code blocks  |  "
            f"Languages: {', '.join(thread.languages) or 'none'}  |  "
            f"merged by: {thread.merge_basis}{when}\n\n", "dim")

        # Show LLM summary if we already have one
        summary = self._project_summaries.get(thread.name)
        if summary:
            self.proj_detail.insert("end", "AI summary\n", "subheading")
            if summary.what_it_is:
                self.proj_detail.insert("end", f"{summary.what_it_is}\n", "dim")
            extras = []
            if summary.status:
                extras.append(f"Status: {summary.status}")
            if summary.next_step:
                extras.append(f"Next: {summary.next_step}")
            if extras:
                self.proj_detail.insert("end", "  ".join(extras) + "\n", "dim")
            self.proj_detail.insert("end", "\n")

        # Show full review if we have one
        review = self._project_reviews.get(thread.name)
        if review and review.markdown:
            self.proj_detail.insert("end", "AI review\n", "subheading")
            self.proj_detail.insert("end", review.markdown + "\n\n", "dim")

        for conv in thread.conversations:
            date = ""
            if conv.create_time:
                date = conv.create_time.strftime(" (%Y-%m-%d)")
            self.proj_detail.insert("end",
                f"\u25B8 {conv.title[:60]}{date}\n", "subheading")

            # Surface attachments (parsed today, hidden before Phase 4)
            attach_names = [a for m in conv.messages for a in (m.attachments or [])]
            if attach_names:
                shown = ", ".join(attach_names[:6])
                more = " \u2026" if len(attach_names) > 6 else ""
                self.proj_detail.insert(
                    "end",
                    f"  \uD83D\uDCCE attachments: {shown}{more}\n",
                    "dim",
                )

            blocks = conv.all_code_blocks
            if blocks:
                self.proj_detail.insert("end",
                    f"  {len(blocks)} code block(s):\n", "dim")
                for block in blocks[:5]:
                    preview = block["code"][:100].replace("\n", " ")
                    self.proj_detail.insert("end",
                        f"    [{block['language']}] {preview}...\n", "code")
                if len(blocks) > 5:
                    self.proj_detail.insert("end",
                        f"    ... and {len(blocks) - 5} more blocks\n", "dim")
            self.proj_detail.insert("end", "\n")

        self.proj_detail.configure(state="disabled")

    # ── Filter ───────────────────────────────────────────────────────

    def _filter_conversations(self) -> None:
        search = self.search_var.get().lower().strip()
        cat_filter = self.filter_category.get()
        code_only = self.filter_code_only.get()

        filtered = []
        for conv in self.conversations:
            if cat_filter != "All Categories" and conv.category != cat_filter:
                continue
            if code_only and not conv.has_code:
                continue
            if search:
                searchable = (conv.title + " " + conv.full_text).lower()
                if search not in searchable:
                    continue
            filtered.append(conv)

        self.filtered_conversations = filtered
        self._rebuild_conversation_list()

    # ── Copy Operations ──────────────────────────────────────────────

    def _copy_selected_code(self) -> None:
        selection = self.code_tree.selection()
        if not selection:
            self._update_status("No code block selected")
            return
        parts = []
        for item_id in selection:
            idx = int(item_id)
            if 0 <= idx < len(self._visible_code_blocks):
                block = self._visible_code_blocks[idx]
                if len(selection) > 1:
                    parts.append(f"// === [{block['language']}] From: {block.get('conversation_title', '')} ===")
                parts.append(block["code"])
                parts.append("")
        if parts:
            combined = "\n".join(parts).rstrip()
            self.root.clipboard_clear()
            self.root.clipboard_append(combined)
            self._update_status(
                f"Copied {len(selection)} block{'s' if len(selection) > 1 else ''} to clipboard"
            )

    def _copy_all_visible_code(self) -> None:
        if not self._visible_code_blocks:
            self._update_status("No code blocks to copy")
            return
        parts = []
        for block in self._visible_code_blocks:
            parts.append(f"// === [{block['language']}] From: {block.get('conversation_title', '')} ===")
            parts.append(block["code"])
            parts.append("")

        combined = "\n".join(parts)
        self.root.clipboard_clear()
        self.root.clipboard_append(combined)
        self._update_status(
            f"Copied {len(self._visible_code_blocks)} code blocks to clipboard"
        )

    def _export_visible_code(self) -> None:
        """Export all currently visible (filtered) code blocks to a file."""
        if not self._visible_code_blocks:
            self._update_status("No code blocks to export — adjust filters")
            return

        path = filedialog.asksaveasfilename(
            title="Export Filtered Code Blocks",
            defaultextension=".txt",
            filetypes=[
                ("Text File", "*.txt"),
                ("Python", "*.py"),
                ("JavaScript", "*.js"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return

        filepath = Path(path)
        try:
            lines = []
            for block in self._visible_code_blocks:
                lines.append(f"# === [{block['language']}] From: {block.get('conversation_title', '')} ===")
                lines.append(block["code"])
                lines.append("")
                lines.append("")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            self._update_status(
                f"Exported {len(self._visible_code_blocks)} code blocks to {filepath.name}"
            )
        except OSError as e:
            logger.error("Export failed: %s", e)
            self._update_status(f"Export failed: {e}")

    def _get_selected_project_names(self) -> list[str]:
        """Return the list of project keys (matching _project_data) currently
        selected in proj_tree. Maps tree iids (e.g. 't0') back to display keys."""
        out: list[str] = []
        for iid in self.proj_tree.selection():
            key = self._pdata_key_by_iid.get(iid)
            if key is not None:
                out.append(key)
        return out

    def _collect_project_code(self, project_names: list[str]) -> dict[str, list[dict]]:
        """Collect all code blocks per project for the given project names."""
        result = {}
        for name in project_names:
            if name in self._project_data:
                blocks = []
                for conv in self._project_data[name]:
                    blocks.extend(conv.all_code_blocks)
                result[name] = blocks
        return result

    def _export_selected_projects(self) -> None:
        """Export code from all selected projects to a folder."""
        names = self._get_selected_project_names()
        if not names:
            self._update_status("No projects selected — click projects in the list first")
            return
        self._export_projects_to_folder(names)

    def _export_all_projects(self) -> None:
        """Export code from every project to a folder."""
        if not self._project_data:
            self._update_status("No projects loaded")
            return
        self._export_projects_to_folder(list(self._project_data.keys()))

    def _export_projects_to_folder(self, project_names: list[str]) -> None:
        """Write each project's code to a separate file in a chosen folder."""
        folder = filedialog.askdirectory(title="Choose Export Folder")
        if not folder:
            return

        folder_path = Path(folder)
        project_code = self._collect_project_code(project_names)
        exported = 0

        for name, blocks in project_code.items():
            if not blocks:
                continue
            # Sanitize filename
            safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(" ", "_")
            if not safe_name:
                safe_name = f"project_{exported}"

            filepath = folder_path / f"{safe_name}_code.txt"
            try:
                lines = [f"# Project: {name}", f"# Code blocks: {len(blocks)}", ""]
                for block in blocks:
                    lines.append(f"# --- [{block['language']}] From: {block.get('conversation_title', '')} ---")
                    lines.append(block["code"])
                    lines.append("")
                    lines.append("")

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                exported += 1
            except OSError as e:
                logger.error("Failed to export project %s: %s", name, e)

        self._update_status(
            f"Exported {exported} project{'s' if exported != 1 else ''} to {folder_path.name}/"
        )

    def _copy_selected_project_code(self) -> None:
        """Copy all code from selected projects to clipboard."""
        names = self._get_selected_project_names()
        if not names:
            self._update_status("No projects selected")
            return

        project_code = self._collect_project_code(names)
        parts = []
        block_count = 0
        for name, blocks in project_code.items():
            if not blocks:
                continue
            parts.append(f"// ======== Project: {name} ========")
            parts.append("")
            for block in blocks:
                parts.append(f"// --- [{block['language']}] From: {block.get('conversation_title', '')} ---")
                parts.append(block["code"])
                parts.append("")
                block_count += 1
            parts.append("")

        if parts:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(parts))
            self._update_status(
                f"Copied {block_count} code blocks from {len(names)} project{'s' if len(names) > 1 else ''}"
            )
        else:
            self._update_status("Selected projects have no code blocks")

    # ── Export ────────────────────────────────────────────────────────

    def _export_results(self) -> None:
        if not self.conversations:
            self._update_status("Nothing to export — load data first")
            return

        path = filedialog.asksaveasfilename(
            title="Export Analysis Results",
            defaultextension=".json",
            filetypes=[
                ("JSON", "*.json"),
                ("Text Report", "*.txt"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return

        filepath = Path(path)
        try:
            if filepath.suffix == ".json":
                self._export_json(filepath)
            else:
                self._export_text(filepath)
            self._update_status(f"Exported to {filepath.name}")
        except OSError as e:
            logger.error("Export failed: %s", e)
            self._update_status(f"Export failed: {e}")

    def _export_json(self, path: Path) -> None:
        data = {
            "export_date": datetime.now().isoformat(),
            "total_conversations": len(self.conversations),
            "conversations": [],
        }
        for conv in self.conversations:
            entry = {
                "id": conv.id,
                "title": conv.title,
                "category": conv.category,
                "subcategory": conv.subcategory,
                "tags": conv.tags,
                "project_name": conv.coding_project_name,
                "message_count": conv.message_count,
                "has_code": conv.has_code,
                "code_blocks": conv.all_code_blocks,
                "create_time": conv.create_time.isoformat() if conv.create_time else None,
            }
            data["conversations"].append(entry)

        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _export_text(self, path: Path) -> None:
        lines = [f"{APP_NAME} Export Report", "=" * 60, ""]

        cat_counts = {}
        for c in self.conversations:
            cat_counts[c.category] = cat_counts.get(c.category, 0) + 1

        lines.append("CATEGORIES:")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {count}")
        lines.append("")

        coding_convs = [c for c in self.conversations if c.category == "Coding & Programming"]
        if coding_convs:
            lines.append("CODING CONVERSATIONS:")
            for conv in coding_convs:
                date = conv.create_time.strftime("%Y-%m-%d") if conv.create_time else "N/A"
                lines.append(f"  [{date}] {conv.title[:60]}")
                if conv.coding_project_name:
                    lines.append(f"    Project: {conv.coding_project_name}")
                blocks = conv.all_code_blocks
                if blocks:
                    langs = set(b["language"] for b in blocks)
                    lines.append(f"    Code: {len(blocks)} blocks ({', '.join(langs)})")
            lines.append("")

        lines.append("ALL CODE BLOCKS:")
        for block in self._all_code_blocks:
            lines.append(f"\n--- [{block['language']}] From: {block.get('conversation_title', '')} ---")
            lines.append(block["code"])

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # ── Theme Toggle ─────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        if self.config.theme == "dark":
            self.config.theme = "light"
            self.colors = LIGHT
        else:
            self.config.theme = "dark"
            self.colors = DARK
        self.config.save()

        _apply_theme(self.root, self.colors)

        for widget in (self.msg_text, self.code_preview, self.overview_text,
                       self.proj_detail, self.stats_text):
            widget.configure(bg=self.colors["bg_secondary"], fg=self.colors["fg"])

        self._update_status(f"Switched to {self.config.theme} theme")

    def _change_font(self, delta: int) -> None:
        current = self.config.get("font_size", 11)
        new_size = max(8, min(current + delta, 24))
        self.config.set("font_size", new_size)
        self.config.save()

        for widget in (self.msg_text, self.overview_text, self.proj_detail):
            widget.configure(font=("Segoe UI", new_size))

        code_size = max(8, min(self.config.get("code_font_size", 12) + delta, 24))
        self.config.set("code_font_size", code_size)
        self.code_preview.configure(font=("Consolas", code_size))

        self._update_status(f"Font size: {new_size}")

    # ── Diagnostics ──────────────────────────────────────────────────

    def _run_diagnostics(self) -> None:
        app_state = {
            "loaded_conversations": len(self.conversations),
            "code_blocks": len(self._all_code_blocks),
            "projects": len(self._project_data),
            "theme": self.config.theme,
            "window_size": f"{self.root.winfo_width()}x{self.root.winfo_height()}",
        }
        report = generate_report(app_state=app_state, save_to_desktop=True)

        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self._update_status("Diagnostic report saved to Desktop and copied to clipboard")

    def _reset_settings(self) -> None:
        if messagebox.askyesno("Reset Settings",
                               "Reset all settings to defaults?"):
            self.config.reset()
            self._update_status("Settings reset to defaults")

    # ── Help Dialogs ─────────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        shortcuts = (
            "Ctrl+O        Open file\n"
            "Ctrl+Shift+O  Open folder\n"
            "Ctrl+E        Export results\n"
            "Ctrl+F        Focus search\n"
            "Ctrl+T        Toggle dark/light theme\n"
            "Ctrl++/-      Increase/decrease font size\n"
            "F1            Show this help\n"
            "F12           Run diagnostics\n"
            "Escape        Clear search"
        )
        messagebox.showinfo("Keyboard Shortcuts", shortcuts)

    def _show_about(self) -> None:
        messagebox.showinfo("About",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Analyze and categorize your Gemini conversation exports.\n"
            "Extract code blocks and identify projects easily.\n\n"
            "Built for Windows, macOS, and Linux.")

    # ── Utility ──────────────────────────────────────────────────────

    def _update_status(self, text: str) -> None:
        self.status_var.set(text)
        logger.info("Status: %s", text)

    # ── LLM + bundle + dedup handlers (Phase 4) ──────────────────────

    def _run_in_background(self, work, on_done, label: str) -> None:
        """Run `work()` off the UI thread, then schedule `on_done(result, err)`
        on it. Backend functions already fail soft; we still wrap so a bug here
        can't freeze the UI, and we surface the error message to the callback
        so the status line shows something actionable, not a generic 'failed'."""
        self.proj_llm_status.set(label)

        def _worker():
            err = None
            try:
                result = work()
            except Exception as e:
                logger.error("%s failed: %s", label, e, exc_info=True)
                result = None
                err = str(e) or e.__class__.__name__
            self.root.after(0, lambda: on_done(result, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _llm_summarize_selected_project(self) -> None:
        t = self.selected_thread
        if t is None:
            self._update_status("Select a project first.")
            return
        if not llm_is_available():
            messagebox.showinfo(
                "LLM not available",
                f"Set the {LLM_ENV_KEY} environment variable, then restart the app.",
            )
            return

        def work():
            return summarize_project(t, self.llm_client, self.llm_cache)

        def done(summary, err):
            # Always cache the result on its project; only touch the visible
            # status/detail if the same project is still selected, so a fast
            # click-away doesn't stomp the new selection's UI.
            still_selected = self.selected_thread is t
            if summary is None:
                if still_selected:
                    detail = f": {err}" if err else " — check logs"
                    self.proj_llm_status.set(f"Summarize failed{detail}")
                self._update_status(f"LLM summarize failed for '{t.name}'.")
                return
            self._project_summaries[t.name] = summary
            if still_selected:
                self.proj_llm_status.set(f"Summary ready ({summary.model})")
                self._display_project(t)

        self._run_in_background(work, done, f"Summarizing '{t.name}' …")

    def _llm_review_selected_project(self) -> None:
        t = self.selected_thread
        if t is None:
            self._update_status("Select a project first.")
            return
        if not llm_is_available():
            messagebox.showinfo(
                "LLM not available",
                f"Set the {LLM_ENV_KEY} environment variable, then restart the app.",
            )
            return

        def work():
            return review_project(t, self.llm_client, self.llm_cache)

        def done(review, err):
            still_selected = self.selected_thread is t
            if review is None or not review.markdown:
                if still_selected:
                    detail = f": {err}" if err else " — check logs"
                    self.proj_llm_status.set(f"Review failed{detail}")
                self._update_status(f"LLM review failed for '{t.name}'.")
                return
            self._project_reviews[t.name] = review
            if still_selected:
                self.proj_llm_status.set(f"Review ready ({review.model})")
                self._display_project(t)

        self._run_in_background(work, done, f"Reviewing '{t.name}' …")

    def _export_claude_bundle_single(self) -> None:
        t = self.selected_thread
        if t is None:
            self._update_status("Select a project first.")
            return
        folder = filedialog.askdirectory(title="Choose folder for the Claude-ready bundle")
        if not folder:
            return
        try:
            path = write_project_bundle(
                t, Path(folder),
                summary=self._project_summaries.get(t.name),
                review=self._project_reviews.get(t.name),
            )
        except (OSError, RuntimeError) as e:
            logger.error("Bundle export failed: %s", e)
            self._update_status(f"Bundle export failed: {e}")
            return
        self._update_status(f"Wrote Claude bundle: {path.name}")

    def _export_claude_bundles_selected(self) -> None:
        iids = list(self.proj_tree.selection())
        threads = [self._thread_by_iid[i] for i in iids if i in self._thread_by_iid]
        if not threads:
            self._update_status("No projects selected.")
            return
        folder = filedialog.askdirectory(title="Choose folder for Claude-ready bundles")
        if not folder:
            return
        out = Path(folder)
        written = 0
        for t in threads:
            try:
                write_project_bundle(
                    t, out,
                    summary=self._project_summaries.get(t.name),
                    review=self._project_reviews.get(t.name),
                )
                written += 1
            except (OSError, RuntimeError) as e:
                logger.error("Skipping %s: %s", t.name, e)
        self._update_status(
            f"Wrote {written} Claude bundle{'s' if written != 1 else ''} to {out.name}/"
        )

    def _save_dedup_report(self) -> None:
        if not self.conversations:
            self._update_status("Load data first.")
            return
        folder = filedialog.askdirectory(title="Choose folder to save the dedup report")
        if not folder:
            return

        def work():
            return write_dedup_report(self.conversations, Path(folder))

        def done(path, err):
            if path is None:
                detail = f": {err}" if err else " — check logs."
                self._update_status(f"Dedup report failed{detail}")
                return
            self._update_status(f"Dedup report saved: {path.name} (source files untouched)")

        self._run_in_background(work, done, "Scanning for duplicates …")

    def _on_close(self) -> None:
        try:
            self.config.set("window_width", self.root.winfo_width())
            self.config.set("window_height", self.root.winfo_height())
            self.config.set("window_x", self.root.winfo_x())
            self.config.set("window_y", self.root.winfo_y())
            self.config.save()
        except Exception as e:
            # Don't let a save failure prevent shutdown — but make it visible.
            logger.error("Window state save on close failed: %s", e, exc_info=True)
        self.root.destroy()
