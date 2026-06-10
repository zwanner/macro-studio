"""Macro Studio main application window: UI, graph editor, and persistence."""

import ctypes
import json
import queue
import threading
import time
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from config import (
    APP_DIR,
    APP_ICON_CANDIDATES,
    APP_TITLE,
    ASSETS_DIR,
    CONFIG_PATH,
    DEFAULT_SETTINGS,
    MACRO_FILETYPES,
)
from hotkeys import (
    HOTKEY_ALIASES,
    canonical_hotkey,
    display_hotkey,
    hotkey_token_set,
    normalize_hotkey_token,
)
from model import (
    FIELD_DESCRIPTIONS,
    FIELD_OPTIONS,
    MACRO_VERSION,
    MacroDocument,
    MacroNode,
    NODE_CATEGORIES,
    NODE_TYPES,
    clean_tab_title,
    recorded_event_label,
    safe_float,
    safe_int,
)
from playback import PlaybackMixin
from recorder import RecorderMixin
from render import (
    Image,
    ImageTk,
    RoundedButton,
    ScrollableFrame,
    Tooltip,
    build_antialiased_icon,
    clear_sprite_cache,
    cubic_points,
    draw_lucide_icon,
    edge_sprite,
    hex_to_rgba,
    port_sprite,
    round_rect_sprite,
    rounded_rect,
    rounded_top_rect,
    tab_sprite,
)
from theme import (
    NODE_DISPLAY_SCALE,
    NODE_H,
    NODE_W,
    THEME,
    UI_FONT,
    UI_SCALE,
    WORKSPACE_MIN_H,
    WORKSPACE_MIN_W,
    graph_ui,
    ui,
)
from winput import (
    WindowsInput,
    colorref,
    get_active_window_title,
    get_mouse_position,
)

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


class MacroStudio(PlaybackMixin, RecorderMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        clear_sprite_cache()
        self.title(APP_TITLE)
        self.app_icon = None
        self.app_icon_large = None
        self.header_logo_image = None
        self.geometry(f"{ui(1260)}x{ui(800)}")
        self.minsize(ui(1040), ui(660))
        self.configure(bg=THEME["bg"])
        self.settings = self.load_settings()
        self.documents = []
        self.tab_to_doc = {}
        self.tab_hit_boxes = []
        self.tab_image_refs = []
        self.hover_tab_close = None
        self.untitled_counter = 0
        self.node_items = {}
        self.port_items = {}
        self.resize_items = {}
        self.canvas_image_refs = []
        self.inspector_vars = {}
        self.suppress_dirty = False
        self.suppress_history = False
        self.pending_connection_source = None
        self.connection_drag = None
        self.frame_resize = None
        self.drag = None
        self.drag_moved = False
        self.drag_history_snapshot = None
        self.fast_canvas_render = False
        self.zoom = 1.0
        self.recording = False
        self.playing = False
        self.record_start = 0
        self.last_recorded_move = 0
        self.last_recorded_pos = None
        self.recorded_move_path = []
        self.recorded_pressed_keys = {}
        self.recorded_pressed_buttons = {}
        self.record_insert_after_id = None
        self.play_context = None
        self.playback_thread = None
        self._play_doc = None
        self._current_doc = None
        self._ui_queue = queue.Queue()
        self._ui_drain_scheduled = False
        self.active_node_id = None
        self.listeners = []
        self.hotkey_listener = None
        self.playback_stop_listener = None
        self._style_ui()
        self.load_app_icon()
        self._build_ui()
        self._bind_shortcuts()
        self.new_macro()
        self.apply_window_chrome()
        self.install_global_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    @property
    def doc(self):
        if not self.documents:
            self.documents.append(MacroDocument())
        if threading.current_thread() is not threading.main_thread():
            # Worker threads must not touch Tk (self.tabs). Use the document
            # pinned at playback start, falling back to the last one the main
            # thread resolved.
            for candidate in (self._play_doc, self._current_doc):
                if candidate is not None and candidate in self.documents:
                    return candidate
            return self.documents[0]
        current = self.tabs.select() if hasattr(self, "tabs") else None
        doc = self.tab_to_doc.get(current, self.documents[0])
        self._current_doc = doc
        return doc

    @property
    def nodes(self):
        return self.doc.nodes

    @nodes.setter
    def nodes(self, value):
        self.doc.nodes = value

    @property
    def selected(self):
        return self.doc.selected

    @selected.setter
    def selected(self, value):
        self.doc.selected = value

    @property
    def file_path(self):
        return self.doc.file_path

    @file_path.setter
    def file_path(self, value):
        self.doc.file_path = value

    def node_by_id(self, node_id):
        return next((node for node in self.nodes if node.node_id == node_id), None)

    def outgoing_edges(self, node):
        return [edge for edge in self.doc.edges if edge.get("from") == node.node_id]

    def incoming_edges(self, node):
        return [edge for edge in self.doc.edges if edge.get("to") == node.node_id]

    def add_edge(self, source, target, refresh=True, record=True):
        if not source or not target or source == target:
            return False
        if source.node_type == "end" or target.node_type == "start":
            return False
        edge = {"from": source.node_id, "to": target.node_id}
        if edge in self.doc.edges:
            return False
        if record:
            self.record_history()
        self.doc.edges.append(edge)
        self.mark_dirty()
        if refresh:
            self.refresh()
        return True

    def remove_edge(self, source, target):
        before = len(self.doc.edges)
        self.doc.edges = [
            edge
            for edge in self.doc.edges
            if not (edge.get("from") == source.node_id and edge.get("to") == target.node_id)
        ]
        return len(self.doc.edges) != before

    def remove_edges_for_node(self, node):
        before = len(self.doc.edges)
        self.doc.edges = [edge for edge in self.doc.edges if edge.get("from") != node.node_id and edge.get("to") != node.node_id]
        return len(self.doc.edges) != before

    def start_node(self):
        return next((node for node in self.nodes if node.node_type == "start"), None)

    def end_node(self):
        return next((node for node in self.nodes if node.node_type == "end"), None)

    def predecessor_before_end(self):
        end = self.end_node()
        if not end:
            return self.selected
        incoming = self.incoming_edges(end)
        if not incoming:
            return self.start_node()
        source = self.node_by_id(incoming[0].get("from"))
        return source or self.start_node()

    def _style_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", (UI_FONT, 10))
        self.option_add("*TCombobox*Listbox.background", THEME["panel_2"])
        self.option_add("*TCombobox*Listbox.foreground", THEME["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", THEME["accent_dark"])
        self.option_add("*TCombobox*Listbox.selectForeground", THEME["accent_text"])
        self.option_add("*Menu.background", THEME["panel"])
        self.option_add("*Menu.foreground", THEME["text"])
        self.option_add("*Menu.activeBackground", THEME["panel_3"])
        self.option_add("*Menu.activeForeground", THEME["text"])
        self.option_add("*Menu.disabledForeground", THEME["muted"])
        style.configure(".", background=THEME["bg"], foreground=THEME["text"], fieldbackground=THEME["panel"], borderwidth=0)
        style.configure("TFrame", background=THEME["bg"])
        style.configure("Panel.TFrame", background=THEME["panel"])
        style.configure("TLabel", background=THEME["bg"], foreground=THEME["text"])
        style.configure("Panel.TLabel", background=THEME["panel"], foreground=THEME["text"])
        style.configure("Muted.TLabel", background=THEME["panel"], foreground=THEME["muted"])
        style.configure("TButton", background=THEME["button"], foreground=THEME["text"], padding=(12, 7), relief="flat")
        style.map("TButton", background=[("active", THEME["button_hover"]), ("pressed", THEME["accent_dark"])])
        style.configure("Accent.TButton", background=THEME["accent_dark"], foreground=THEME["accent_text"])
        style.map("Accent.TButton", background=[("active", THEME["accent"])])
        style.configure(
            "TNotebook",
            background=THEME["panel"],
            tabmargins=(0, 8, 0, 0),
            borderwidth=0,
            bordercolor=THEME["panel"],
            lightcolor=THEME["panel"],
            darkcolor=THEME["panel"],
        )
        style.configure(
            "TNotebook.Tab",
            background=THEME["panel_2"],
            foreground=THEME["muted"],
            padding=(20, 9),
            borderwidth=1,
            bordercolor=THEME["tab_outline"],
            lightcolor=THEME["tab_outline"],
            darkcolor=THEME["tab_outline"],
            focuscolor=THEME["accent_dark"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", THEME["accent_dark"])],
            foreground=[("selected", THEME["accent_text"])],
            padding=[("selected", (26, 12))],
        )
        style.configure(
            "TCombobox",
            padding=6,
            arrowsize=14,
            fieldbackground=THEME["panel_2"],
            background=THEME["panel_2"],
            foreground=THEME["text"],
            arrowcolor=THEME["accent"],
            bordercolor=THEME["line"],
            lightcolor=THEME["line"],
            darkcolor=THEME["line"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", THEME["panel_2"])],
            foreground=[("readonly", THEME["text"])],
            background=[("readonly", THEME["panel_2"])],
        )
        style.configure("TEntry", fieldbackground=THEME["panel_2"], foreground=THEME["text"], bordercolor=THEME["line"], padding=7)

    def load_app_icon(self):
        icon_path = next((path for path in APP_ICON_CANDIDATES if path.exists()), None)
        if icon_path:
            try:
                if Image is not None:
                    source = Image.open(icon_path).convert("RGBA")
                    cropped = self.crop_pillow_transparent_padding(source)
                    self.header_logo_image = ImageTk.PhotoImage(self.resize_pillow_logo(cropped, ui(44)))
                    self.app_icon = ImageTk.PhotoImage(self.resize_pillow_logo(cropped, ui(32)))
                    self.app_icon_large = ImageTk.PhotoImage(self.resize_pillow_logo(cropped, ui(64)))
                    self.iconphoto(True, self.app_icon, self.app_icon_large)
                else:
                    self.app_icon = tk.PhotoImage(file=icon_path)
                    self.header_logo_image = self.prepare_header_logo(self.app_icon)
                    self.iconphoto(True, self.app_icon)
            except (OSError, tk.TclError):
                self.app_icon = None
                self.app_icon_large = None
                self.header_logo_image = None

    def crop_pillow_transparent_padding(self, image):
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if not bbox:
            return image
        margin = 8
        left = max(0, bbox[0] - margin)
        top = max(0, bbox[1] - margin)
        right = min(image.width, bbox[2] + margin)
        bottom = min(image.height, bbox[3] + margin)
        return image.crop((left, top, right, bottom))

    def resize_pillow_logo(self, image, target):
        scale = target / max(image.width, image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        return image.resize(size, Image.Resampling.LANCZOS)

    def prepare_header_logo(self, image):
        cropped = self.crop_transparent_padding(image)
        target = ui(44)
        max_dim = max(cropped.width(), cropped.height())
        scale = max(1, max_dim // target)
        return cropped.subsample(scale, scale)

    def crop_transparent_padding(self, image):
        width, height = image.width(), image.height()
        left, top, right, bottom = width, height, -1, -1
        step = 4
        for y in range(0, height, step):
            for x in range(0, width, step):
                if not image.transparency_get(x, y):
                    left = min(left, x)
                    top = min(top, y)
                    right = max(right, x)
                    bottom = max(bottom, y)
        if right < left or bottom < top:
            return image
        left = max(0, left - step)
        top = max(0, top - step)
        right = min(width, right + step + 1)
        bottom = min(height, bottom + step + 1)
        cropped = tk.PhotoImage()
        cropped.tk.call(cropped, "copy", image, "-from", left, top, right, bottom, "-to", 0, 0)
        return cropped

    def apply_window_chrome(self):
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            caption = ctypes.c_int(colorref(THEME["bg"]))
            text = ctypes.c_int(colorref(THEME["text"]))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        except Exception:
            pass

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.build_menu_bar()

        toolbar = ttk.Frame(self, style="Panel.TFrame", padding=(10, 8))
        toolbar.grid(row=1, column=0, columnspan=3, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        self.draw_header_logo(toolbar)
        ttk.Label(toolbar, text=APP_TITLE, style="Panel.TLabel", font=(UI_FONT, 13, "bold")).pack(side="left", padx=(8, 12))
        self.recent_var = tk.StringVar(value="Open recent...")
        self.script_status = tk.StringVar(value="Saved")
        self.script_status_label = tk.Label(toolbar, textvariable=self.script_status, bg=THEME["panel"], fg=THEME["success"], font=(UI_FONT, 10))
        self.script_status_label.pack(side="left", padx=(0, 12))
        self.status = tk.StringVar(value="Ready")
        self.status.trace_add("write", lambda *_args: self.update_status_color())
        RoundedButton(toolbar, text="Stop", command=self.stop_all, width=96, icon="stop").pack(side="right", padx=(4, 0))
        RoundedButton(toolbar, text="Play", command=self.play_macro, width=96, accent=True, icon="play").pack(side="right", padx=4)
        RoundedButton(toolbar, text="Record", command=self.toggle_recording, width=108, accent=True, icon="record").pack(side="right", padx=4)
        self.status_label = tk.Label(toolbar, textvariable=self.status, bg=THEME["panel"], fg=THEME["muted"], font=(UI_FONT, 10))
        self.status_label.pack(side="right", padx=(10, 12))
        self.update_status_color()

        palette_outer = ttk.Frame(self, style="Panel.TFrame", padding=10)
        palette_outer.grid(row=2, column=0, sticky="ns")
        palette_outer.columnconfigure(0, weight=1)
        palette_outer.rowconfigure(2, weight=1)
        ttk.Label(palette_outer, text="Nodes", style="Panel.TLabel", font=(UI_FONT, 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(palette_outer, text="Drop actions into the flow", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))
        palette_scroll = ScrollableFrame(palette_outer, width=220, style="Panel.TFrame")
        palette_scroll.grid(row=2, column=0, sticky="nsew")
        self.palette_scroll = palette_scroll
        self.build_node_palette(palette_scroll.inner)

        center = ttk.Frame(self, style="Panel.TFrame")
        center.grid(row=2, column=1, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)
        self.tab_bar = tk.Canvas(
            center,
            height=ui(50),
            bg=THEME["panel"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.tab_bar.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=(8, 0))
        self.tab_bar.bind("<Configure>", lambda _event: self.draw_tab_bar())
        self.tab_bar.bind("<ButtonRelease-1>", self.on_tab_click)
        self.tab_bar.bind("<Motion>", self.on_tab_motion)
        self.tab_bar.bind("<Leave>", self.on_tab_leave)
        self.tabs = ttk.Notebook(center)
        self.tabs.configure(takefocus=False)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _event: self.refresh())

        canvas_shell = ttk.Frame(center, style="Panel.TFrame")
        canvas_shell.grid(row=1, column=0, sticky="nsew", padx=(8, 8), pady=(0, 8))
        canvas_shell.columnconfigure(0, weight=1)
        canvas_shell.rowconfigure(1, weight=1)
        self.graph_info = tk.StringVar(value="")
        ttk.Label(
            canvas_shell,
            textvariable=self.graph_info,
            style="Muted.TLabel",
            padding=(10, 7),
        ).grid(row=0, column=0, columnspan=2, sticky="ew")
        self.canvas = tk.Canvas(
            canvas_shell,
            bg=THEME["canvas"],
            highlightthickness=1,
            highlightbackground=THEME["line"],
            xscrollincrement=16,
            yscrollincrement=16,
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas_vbar = ttk.Scrollbar(canvas_shell, orient="vertical", command=self.canvas.yview)
        self.canvas_hbar = ttk.Scrollbar(canvas_shell, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.canvas_hbar.set, yscrollcommand=self.canvas_vbar.set)
        self.canvas_vbar.grid(row=1, column=1, sticky="ns")
        self.canvas_hbar.grid(row=2, column=0, sticky="ew")
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self.edit_selected)
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom_wheel)
        self.canvas.bind("<MouseWheel>", self.on_canvas_scroll)

        props = ttk.Frame(self, style="Panel.TFrame", padding=10)
        props.grid(row=2, column=2, sticky="ns")
        ttk.Label(props, text="Inspector", style="Panel.TLabel", font=(UI_FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(props, text="Edit the selected action", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.inspector_body = ttk.Frame(props, style="Panel.TFrame")
        self.inspector_body.pack(fill="both", expand=True, pady=4)
        self.inspector_actions = ttk.Frame(props, style="Panel.TFrame")
        self.inspector_actions.pack(fill="x", pady=(6, 0))
        for column in range(2):
            self.inspector_actions.columnconfigure(column, weight=1)
        for idx, (text, command, danger, icon) in enumerate([
            ("Auto Link", self.auto_link_nodes, False, "wand"),
            ("Unlink", self.unlink_selected, False, "unlink"),
            ("Duplicate", self.duplicate_selected, False, "copy"),
            ("Delete", self.delete_selected, True, "trash"),
            ("Move Up", lambda: self.move_selected(-1), False, "arrow-up"),
            ("Move Down", lambda: self.move_selected(1), False, "arrow-down"),
            ("Clear", self.clear_nodes, True, "eraser"),
        ]):
            span = 2 if idx == 6 else 1
            width = 260 if span == 2 else 126
            button = RoundedButton(self.inspector_actions, text=text, command=command, width=width, height=38, danger=danger, icon=icon)
            button.grid(row=int(idx / 2), column=idx % 2, columnspan=span, sticky="ew", padx=3, pady=3)
        self.update_recent_menu()

    def build_menu_bar(self):
        menu_bar = tk.Frame(self, bg=THEME["panel"], highlightthickness=0, bd=0)
        menu_bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.menu_bar = menu_bar

        file_menu = self.create_styled_menu(menu_bar)
        file_menu.add_command(label="New Script", accelerator="Ctrl+N", command=self.new_macro)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.load_macro)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_macro)
        file_menu.add_separator()
        self.recent_menu = self.create_styled_menu(file_menu)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", command=self.close_tab)
        file_menu.add_command(label="Exit", command=self.on_close)
        self.add_menu_button(menu_bar, "File", file_menu)

        edit_menu = self.create_styled_menu(menu_bar)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Connect From Selected", command=self.begin_connection_from_selected)
        edit_menu.add_command(label="Connect To Selected", command=self.connect_pending_to_selected)
        edit_menu.add_command(label="Unlink Node", command=self.unlink_selected)
        edit_menu.add_command(label="Auto Link Nodes", command=self.auto_link_nodes)
        edit_menu.add_separator()
        edit_menu.add_command(label="Duplicate Node", command=self.duplicate_selected)
        edit_menu.add_command(label="Delete Node", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear Script", command=self.clear_nodes)
        self.add_menu_button(menu_bar, "Edit", edit_menu)

        view_menu = self.create_styled_menu(menu_bar)
        view_menu.add_command(label="Zoom In", accelerator="Ctrl++", command=self.zoom_in)
        view_menu.add_command(label="Zoom Out", accelerator="Ctrl+-", command=self.zoom_out)
        view_menu.add_separator()
        view_menu.add_command(label="Auto Organize Nodes", command=self.auto_organize_nodes)
        self.add_menu_button(menu_bar, "View", view_menu)

        run_menu = self.create_styled_menu(menu_bar)
        run_menu.add_command(label="Record", command=self.toggle_recording)
        run_menu.add_command(label="Play", accelerator="Space", command=self.play_macro)
        run_menu.add_command(label="Stop", accelerator="Esc", command=self.stop_all)
        self.add_menu_button(menu_bar, "Run", run_menu)

        settings_menu = self.create_styled_menu(menu_bar)
        settings_menu.add_command(label="Preferences...", command=self.open_settings)
        self.add_menu_button(menu_bar, "Settings", settings_menu)

    def create_styled_menu(self, parent):
        return tk.Menu(
            parent,
            tearoff=False,
            bg=THEME["panel"],
            fg=THEME["text"],
            activebackground=THEME["panel_3"],
            activeforeground=THEME["text"],
            disabledforeground=THEME["muted"],
            relief="flat",
            bd=0,
        )

    def add_menu_button(self, parent, label, menu):
        button = tk.Menubutton(
            parent,
            text=label,
            menu=menu,
            bg=THEME["panel"],
            fg=THEME["text"],
            activebackground=THEME["panel_3"],
            activeforeground=THEME["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            font=(UI_FONT, 10),
        )
        button.configure(cursor="hand2", takefocus=True)
        button.bind("<Button-1>", lambda event, target=button, target_menu=menu: self.post_menu(target, target_menu))
        button.bind("<Return>", lambda event, target=button, target_menu=menu: self.post_menu(target, target_menu))
        button.bind("<space>", lambda event, target=button, target_menu=menu: self.post_menu(target, target_menu))
        button.pack(side="left")
        return button

    def post_menu(self, button, menu):
        button.update_idletasks()
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        return "break"

    def build_node_palette(self, parent):
        for category, node_types in NODE_CATEGORIES:
            ttk.Label(parent, text=category, style="Panel.TLabel", font=(UI_FONT, 10, "bold")).pack(anchor="w", pady=(10, 4))
            for node_type in node_types:
                spec = NODE_TYPES[node_type]
                button = RoundedButton(
                    parent,
                    text=spec["title"],
                    command=lambda kind=node_type: self.add_node(kind),
                    width=174,
                    height=36,
                )
                button.pack(fill="x", pady=2)
                button.bind("<MouseWheel>", self.palette_scroll.on_mousewheel, add="+")
                Tooltip(button, spec.get("description", ""))

    def draw_header_logo(self, parent):
        if self.header_logo_image:
            label = tk.Label(parent, image=self.header_logo_image, bg=THEME["panel"], bd=0)
            label.pack(side="left", padx=(0, 2))
            return
        logo = tk.Canvas(parent, width=34, height=34, bg=THEME["panel"], highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 2))
        rounded_rect(logo, 3, 3, 31, 31, 8, fill=THEME["panel_3"], outline=THEME["line"])
        logo.create_line(10, 23, 10, 12, 17, 18, 24, 12, 24, 23, fill=THEME["accent"], width=3, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        for x, y in [(10, 23), (17, 18), (24, 23)]:
            logo.create_oval(x - 3, y - 3, x + 3, y + 3, fill=THEME["text"], outline=THEME["accent"])

    def _bind_shortcuts(self):
        self.bind("<Control-s>", lambda _e: self.save_macro())
        self.bind("<Control-o>", lambda _e: self.load_macro())
        self.bind("<Control-n>", lambda _e: self.new_macro())
        self.bind("<Control-z>", self.undo)
        self.bind("<Control-y>", self.redo)
        self.bind("<Delete>", lambda _e: self.delete_selected())
        self.bind("<space>", self.on_play_shortcut)
        self.bind("<Escape>", self.on_stop_shortcut)
        self.bind("<Control-plus>", lambda _e: self.zoom_in())
        self.bind("<Control-equal>", lambda _e: self.zoom_in())
        self.bind("<Control-minus>", lambda _e: self.zoom_out())
        self.bind("<Control-0>", lambda _e: self.set_zoom(1.0))

    def on_play_shortcut(self, event):
        if self.is_editing_text(event.widget):
            return None
        self.play_macro()
        return "break"

    def on_stop_shortcut(self, event):
        if self.is_editing_text(event.widget):
            return None
        self.stop_all()
        return "break"

    def is_editing_text(self, widget):
        editable_classes = {"Entry", "TEntry", "Text", "Combobox", "TCombobox", "Spinbox", "TSpinbox"}
        while widget:
            try:
                if widget.winfo_class() in editable_classes:
                    return True
                widget = widget.master
            except tk.TclError:
                return False
        return False

    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        if CONFIG_PATH.exists():
            try:
                settings.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        settings["recent_files"] = [p for p in settings.get("recent_files", []) if Path(p).exists()]
        return settings

    def save_settings(self):
        CONFIG_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def install_global_hotkeys(self):
        if keyboard is None:
            self.status.set("Install pynput for global hotkeys and recording")
            return
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        mapping = {
            canonical_hotkey(self.settings["record_hotkey"]): lambda: self.after(0, self.toggle_recording),
            canonical_hotkey(self.settings["play_hotkey"]): lambda: self.after(0, lambda: self.play_macro(from_hotkey=True)),
            canonical_hotkey(self.settings["stop_hotkey"]): self.request_stop_all,
        }
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys(mapping)
            self.hotkey_listener.start()
        except ValueError as exc:
            self.hotkey_listener = None
            self.status.set(f"Invalid hotkey setting: {exc}")

    def add_document(self, doc):
        frame = ttk.Frame(self.tabs)
        self.documents.append(doc)
        tab_id = str(frame)
        self.tab_to_doc[tab_id] = doc
        self.tabs.add(frame, text=doc.tab_title)
        self.tabs.select(frame)
        self.refresh()

    def mark_dirty(self):
        if not self.suppress_dirty:
            self.doc.dirty = True
            self.update_current_tab_title()

    def document_snapshot(self):
        return {
            "nodes": [
                {
                    "id": node.node_id,
                    "type": node.node_type,
                    "x": node.x,
                    "y": node.y,
                    "data": json.loads(json.dumps(node.data)),
                }
                for node in self.nodes
            ],
            "edges": json.loads(json.dumps(self.doc.edges)),
            "selected": self.selected.node_id if self.selected else None,
        }

    def push_history_snapshot(self, snapshot):
        if self.suppress_history:
            return
        if not self.doc.undo_stack or self.doc.undo_stack[-1] != snapshot:
            self.doc.undo_stack.append(snapshot)
            self.doc.undo_stack = self.doc.undo_stack[-100:]
        self.doc.redo_stack.clear()

    def record_history(self):
        self.push_history_snapshot(self.document_snapshot())

    def restore_snapshot(self, snapshot):
        selected_id = snapshot.get("selected")
        nodes = [
            MacroNode(
                item["type"],
                item.get("x", 80),
                item.get("y", 80),
                json.loads(json.dumps(item.get("data", {}))),
                item.get("id") or uuid.uuid4().hex[:10],
            )
            for item in snapshot.get("nodes", [])
        ]
        self.doc.nodes = nodes
        self.doc.edges = json.loads(json.dumps(snapshot.get("edges", [])))
        self.doc.selected = next((node for node in nodes if node.node_id == selected_id), None)
        self.doc.dirty = True
        self.refresh()

    def undo(self, _event=None):
        if not self.doc.undo_stack:
            self.status.set("Nothing to undo")
            return "break"
        current = self.document_snapshot()
        snapshot = self.doc.undo_stack.pop()
        self.doc.redo_stack.append(current)
        self.suppress_history = True
        try:
            self.restore_snapshot(snapshot)
        finally:
            self.suppress_history = False
        self.status.set("Undo")
        return "break"

    def redo(self, _event=None):
        if not self.doc.redo_stack:
            self.status.set("Nothing to redo")
            return "break"
        current = self.document_snapshot()
        snapshot = self.doc.redo_stack.pop()
        self.doc.undo_stack.append(current)
        self.suppress_history = True
        try:
            self.restore_snapshot(snapshot)
        finally:
            self.suppress_history = False
        self.status.set("Redo")
        return "break"

    def update_current_tab_title(self):
        current = self.tabs.select()
        if current:
            self.tabs.tab(current, text=self.doc.tab_title)
        self.draw_tab_bar()
        if hasattr(self, "script_status"):
            self.script_status.set("Unsaved changes" if self.doc.dirty else "Saved")
            self.update_script_status_color()
        if hasattr(self, "graph_info"):
            self.graph_info.set(
                f"{clean_tab_title(self.doc.tab_title)}  |  {len(self.nodes)} nodes  |  "
                f"Zoom {int(self.zoom * 100)}%  |  Record {display_hotkey(self.settings['record_hotkey'])}"
            )

    def update_script_status_color(self):
        if not hasattr(self, "script_status_label"):
            return
        color = THEME["error"] if "unsaved" in self.script_status.get().lower() else THEME["success"]
        self.script_status_label.configure(fg=color)

    def update_status_color(self):
        if not hasattr(self, "status_label"):
            return
        self.status_label.configure(fg=self.status_text_color(self.status.get()))

    def status_text_color(self, text):
        lowered = str(text).lower()
        if any(word in lowered for word in ("failed", "invalid", "unavailable", "not found", "stopped")):
            return THEME["error"]
        if any(word in lowered for word in ("playing", "recording", "waiting")):
            return THEME["success"]
        if any(word in lowered for word in ("complete", "saved", "loaded", "settings saved")):
            return THEME["success"]
        if any(word in lowered for word in ("zoom", "ready", "new script")):
            return THEME["info"]
        return THEME["muted"]

    def draw_tab_bar(self):
        if not hasattr(self, "tab_bar"):
            return
        self.tab_bar.delete("all")
        self.tab_hit_boxes = []
        self.tab_image_refs = []
        tabs = self.tabs.tabs() if hasattr(self, "tabs") else []
        selected_tab = self.tabs.select() if tabs else ""
        width = max(self.tab_bar.winfo_width(), 1)
        self.tab_bar.create_rectangle(0, 0, width, ui(50), fill=THEME["panel"], outline="")
        x = 0
        tab_font = tkfont.Font(font=(UI_FONT, 10, "bold"))
        for index, tab_id in enumerate(tabs):
            doc = self.tab_to_doc.get(tab_id)
            if not doc:
                continue
            selected = tab_id == selected_tab
            label = clean_tab_title(doc.tab_title)
            text_width = tab_font.measure(label)
            tab_w = max(ui(132 if selected else 112), min(ui(230), text_width + ui(62)))
            tab_h = ui(42 if selected else 36)
            y = ui(4 if selected else 10)
            fill = THEME["accent_dark"] if selected else THEME["panel_2"]
            outline = THEME["accent"] if selected else THEME["tab_outline"]
            self.draw_antialiased_tab(x, y, tab_w, tab_h, ui(10), fill, outline, ui(2 if selected else 1))
            text_fill = THEME["accent_text"] if selected else THEME["muted"]
            self.tab_bar.create_text(
                x + ui(20),
                y + int(tab_h / 2),
                text=label,
                fill=text_fill,
                font=(UI_FONT, 10, "bold" if selected else "normal"),
                anchor="w",
            )
            close_x = x + tab_w - ui(22)
            close_y = y + int(tab_h / 2)
            close_box = (close_x - ui(11), close_y - ui(11), close_x + ui(11), close_y + ui(11))
            close_hovered = self.hover_tab_close == index
            close_fill = THEME["panel_3"] if selected else THEME["panel"]
            close_text = THEME["error"] if close_hovered else THEME["text"]
            rounded_rect(self.tab_bar, *close_box, ui(8), fill=close_fill, outline=THEME["error"] if close_hovered else THEME["line"], tags=("tab-close",))
            self.tab_bar.create_text(close_x, close_y - ui(1), text="x", fill=close_text, font=(UI_FONT, 10, "bold"), tags=("tab-close",))
            self.tab_hit_boxes.append(
                {
                    "index": index,
                    "body": (x, y, x + tab_w, y + tab_h),
                    "close": close_box,
                }
            )
            x += tab_w + ui(2)
        self.tab_bar.create_line(0, ui(48), width, ui(48), fill=THEME["line"], width=max(1, ui(1)))

    def draw_antialiased_tab(self, x, y, w, h, radius, fill, outline, width=1):
        if Image is None:
            return rounded_top_rect(self.tab_bar, x, y, x + w, y + h, radius, fill=fill, outline=outline, width=width)
        photo = tab_sprite(w, h, radius, fill, outline, width)
        self.tab_image_refs.append(photo)
        return self.tab_bar.create_image(x, y, image=photo, anchor="nw")

    def on_tab_motion(self, event):
        hovered = None
        for box in getattr(self, "tab_hit_boxes", []):
            x1, y1, x2, y2 = box["close"]
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                hovered = box["index"]
                break
        if hovered != self.hover_tab_close:
            self.hover_tab_close = hovered
            self.draw_tab_bar()

    def on_tab_leave(self, _event):
        if self.hover_tab_close is not None:
            self.hover_tab_close = None
            self.draw_tab_bar()

    def on_tab_click(self, event):
        index = self.tab_index_at(event.x, event.y)
        if index is None:
            return
        if self.tab_close_hit(index, event.x, event.y):
            self.close_tab(index)
            return "break"
        tabs = self.tabs.tabs()
        if 0 <= index < len(tabs):
            self.tabs.select(tabs[index])
            self.refresh()
            return "break"

    def tab_index_at(self, x, y):
        for box in getattr(self, "tab_hit_boxes", []):
            x1, y1, x2, y2 = box["body"]
            if x1 <= x <= x2 and y1 <= y <= y2:
                return box["index"]
        try:
            return self.tabs.index(f"@{x},{y}")
        except tk.TclError:
            pass
        for index in range(len(self.tabs.tabs())):
            bbox = self.tabs.bbox(index)
            if not bbox:
                continue
            tab_x, tab_y, tab_w, tab_h = bbox
            if tab_x <= x <= tab_x + tab_w and tab_y <= y <= tab_y + tab_h:
                return index
        return None

    def tab_close_hit(self, index, x, y):
        for box in getattr(self, "tab_hit_boxes", []):
            if box["index"] != index:
                continue
            x1, y1, x2, y2 = box["close"]
            return x1 <= x <= x2 and y1 <= y <= y2
        try:
            bbox = self.tabs.bbox(index)
        except tk.TclError:
            return False
        if not bbox:
            return False
        tab_x, tab_y, tab_w, tab_h = bbox
        close_size = min(18, max(12, tab_h - 8))
        close_x1 = tab_x + tab_w - close_size - 5
        close_x2 = tab_x + tab_w - 4
        close_y1 = tab_y + max(3, int((tab_h - close_size) / 2))
        close_y2 = close_y1 + close_size
        return close_x1 <= x <= close_x2 and close_y1 <= y <= close_y2

    def close_tab(self, index=None):
        if not self.tabs.tabs():
            return
        if index is None:
            index = self.tabs.index(self.tabs.select())
        tab_id = self.tabs.tabs()[index]
        doc = self.tab_to_doc[tab_id]
        if not self.confirm_save_if_dirty(doc):
            return
        self.tabs.forget(index)
        self.documents.remove(doc)
        del self.tab_to_doc[tab_id]
        if not self.documents:
            self.new_macro()
        self.refresh()

    def confirm_save_if_dirty(self, doc):
        if not doc.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved Script", f"Save changes to {clean_tab_title(doc.tab_title)} before closing?")
        if answer is None:
            return False
        if answer:
            return self.save_document(doc)
        return True

    def save_document(self, doc):
        if not doc.file_path:
            path = filedialog.asksaveasfilename(defaultextension=".macro", filetypes=MACRO_FILETYPES)
            if not path:
                return False
            doc.file_path = Path(path)
        self.write_macro(doc, doc.file_path)
        doc.dirty = False
        self.add_recent_file(doc.file_path)
        self.status.set(f"Saved {doc.file_path.name}")
        self.refresh()
        return True

    def to_screen(self, value):
        return value * self.zoom

    def from_screen(self, value):
        return value / self.zoom

    def node_display_w(self):
        return graph_ui(NODE_W)

    def node_display_h(self):
        return graph_ui(NODE_H)

    def node_world_w(self, node):
        if node.node_type == "loop_frame":
            return max(self.node_display_w(), graph_ui(safe_float(node.data.get("width", 360), 360)))
        return self.node_display_w()

    def node_world_h(self, node):
        if node.node_type == "loop_frame":
            return max(self.node_display_h() * 2, graph_ui(safe_float(node.data.get("height", 300), 300)))
        return self.node_display_h()

    def loop_frame_raw_size(self, world_w, world_h):
        return max(NODE_W, world_w / NODE_DISPLAY_SCALE), max(NODE_H * 2, world_h / NODE_DISPLAY_SCALE)

    def node_center(self, node):
        return node.x + self.node_world_w(node) / 2, node.y + self.node_world_h(node) / 2

    def node_inside_frame(self, node, frame):
        if node == frame:
            return False
        if node.node_type == "loop_frame":
            node_right = node.x + self.node_world_w(node)
            node_bottom = node.y + self.node_world_h(node)
            frame_right = frame.x + self.node_world_w(frame)
            frame_bottom = frame.y + self.node_world_h(frame)
            return frame.x <= node.x and node_right <= frame_right and frame.y <= node.y and node_bottom <= frame_bottom
        center_x, center_y = self.node_center(node)
        return frame.x <= center_x <= frame.x + self.node_world_w(frame) and frame.y <= center_y <= frame.y + self.node_world_h(frame)

    def containing_loop_frames(self, node):
        frames = [frame for frame in self.nodes if frame.node_type == "loop_frame" and self.node_inside_frame(node, frame)]
        return sorted(frames, key=lambda frame: self.node_world_w(frame) * self.node_world_h(frame))

    def nearest_loop_frame(self, node):
        frames = self.containing_loop_frames(node)
        return frames[0] if frames else None

    def loop_frame_body_nodes(self, frame):
        body = [node for node in self.nodes if self.nearest_loop_frame(node) == frame]
        return sorted(body, key=lambda node: (node.y, node.x))

    def zoom_in(self):
        self.set_zoom(self.zoom * 1.15)

    def zoom_out(self):
        self.set_zoom(self.zoom / 1.15)

    def set_zoom(self, value):
        left_world = self.from_screen(self.canvas.canvasx(0)) if hasattr(self, "canvas") else 0
        top_world = self.from_screen(self.canvas.canvasy(0)) if hasattr(self, "canvas") else 0
        self.zoom = min(max(value, 0.35), 2.0)
        self.status.set(f"Editor zoom {int(self.zoom * 100)}%")
        self.update_canvas_scrollregion()
        self.restore_canvas_view(left_world, top_world)
        self.refresh()

    def restore_canvas_view(self, left_world, top_world):
        region = self.canvas.cget("scrollregion").split()
        if len(region) != 4:
            return
        x1, y1, x2, y2 = [float(value) for value in region]
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        self.canvas.xview_moveto(min(max(self.to_screen(left_world) / width, 0), 1))
        self.canvas.yview_moveto(min(max(self.to_screen(top_world) / height, 0), 1))

    def on_zoom_wheel(self, event):
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        return "break"

    def on_canvas_scroll(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def add_node(self, node_type, x=None, y=None, data=None):
        previous = self.selected
        defaults = dict(NODE_TYPES[node_type]["defaults"])
        if data:
            defaults.update(data)
        self.record_history()
        node = MacroNode(node_type, x or 80, y or 70 + len(self.nodes) * 88, defaults)
        self.nodes.append(node)
        if previous and previous in self.nodes and previous != node:
            self.add_edge(previous, node, refresh=False, record=False)
        self.selected = node
        self.mark_dirty()
        self.refresh()

    def add_recorded_node_to_flow(self, event):
        predecessor = self.node_by_id(self.record_insert_after_id) or self.predecessor_before_end()
        end = self.end_node()
        x = predecessor.x if predecessor else 330
        y = (predecessor.y + 104) if predecessor else 70 + len(self.nodes) * 90
        self.record_history()
        node = MacroNode(
            "recorded",
            x,
            y,
            {"event": event, "_label": recorded_event_label(event)},
        )
        self.nodes.append(node)
        if predecessor and end:
            self.remove_edge(predecessor, end)
            self.add_edge(predecessor, node, refresh=False, record=False)
            self.add_edge(node, end, refresh=False, record=False)
            end.x = x
            end.y = y + 104
        elif predecessor:
            self.add_edge(predecessor, node, refresh=False, record=False)
        self.record_insert_after_id = node.node_id
        self.selected = node
        self.mark_dirty()
        self.refresh()

    def refresh(self, update_inspector=True, update_status=True, update_scrollregion=True, fast=False):
        if not hasattr(self, "canvas"):
            return
        previous_fast = self.fast_canvas_render
        self.fast_canvas_render = fast
        try:
            self.canvas.delete("all")
            self.node_items.clear()
            self.port_items.clear()
            self.resize_items.clear()
            self.canvas_image_refs.clear()
            if update_scrollregion:
                self.update_canvas_scrollregion()
            ordered = sorted(self.nodes, key=lambda n: n.y)
            for node in ordered:
                if node.node_type == "loop_frame":
                    self.draw_node(node)
            self.draw_edges()
            for node in ordered:
                if node.node_type != "loop_frame":
                    self.draw_node(node)
            if update_inspector:
                self.update_inspector()
            if update_status:
                self.update_current_tab_title()
        finally:
            self.fast_canvas_render = previous_fast

    def highlight_active_node(self, node_id=None):
        """Lightweight playback indicator: draws an accent outline around the
        active node without re-rendering the whole canvas."""
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("active-glow")
        node = self.node_by_id(node_id) if node_id else None
        if not node:
            return
        x = self.to_screen(node.x)
        y = self.to_screen(node.y)
        w = self.to_screen(self.node_world_w(node))
        h = self.to_screen(self.node_world_h(node))
        pad = max(2, int(3 * self.zoom))
        rounded_rect(
            self.canvas,
            x - pad,
            y - pad,
            x + w + pad,
            y + h + pad,
            max(5, int(10 * self.zoom)),
            outline=THEME["node_active_outline"],
            fill="",
            width=max(2, int(3 * self.zoom)),
            tags="active-glow",
        )

    def draw_edges(self):
        for edge in self.doc.edges:
            source = self.node_by_id(edge.get("from"))
            target = self.node_by_id(edge.get("to"))
            if not source or not target:
                continue
            color = THEME["line"]
            width = 2
            if target == self.selected:
                color = THEME["danger"]
                width = 3
            elif source == self.selected:
                color = THEME["accent"]
                width = 3
            source_w = self.node_world_w(source)
            source_h = self.node_world_h(source)
            target_w = self.node_world_w(target)
            x1 = self.to_screen(source.x + source_w / 2)
            y1 = self.to_screen(source.y + source_h)
            x2 = self.to_screen(target.x + target_w / 2)
            y2 = self.to_screen(target.y)
            self.draw_edge_curve(x1, y1, x2, y2, color, max(1, int(width * self.zoom)))

    def draw_edge_curve(self, x1, y1, x2, y2, color, width):
        mid_y = y1 + max(28, (y2 - y1) / 2)
        if Image is None or self.fast_canvas_render:
            self.canvas.create_line(
                x1,
                y1,
                x1,
                mid_y,
                x2,
                mid_y,
                x2,
                y2,
                fill=color,
                width=width,
                arrow=tk.LAST,
                smooth=True,
            )
            return
        photo, offset_x, offset_y = edge_sprite(x2 - x1, y2 - y1, color, width)
        self.canvas_image_refs.append(photo)
        self.canvas.create_image(x1 + offset_x, y1 + offset_y, image=photo, anchor="nw")

    def update_canvas_scrollregion(self):
        viewport_w, viewport_h = self.canvas_viewport_size()
        if not self.nodes:
            self.canvas.configure(scrollregion=(0, 0, viewport_w, viewport_h))
            return
        max_x = WORKSPACE_MIN_W
        max_y = WORKSPACE_MIN_H
        for node in self.nodes:
            max_x = max(max_x, node.x + self.node_world_w(node) + 300)
            max_y = max(max_y, node.y + self.node_world_h(node) + 300)
        width = max(self.to_screen(max_x), viewport_w)
        height = max(self.to_screen(max_y), viewport_h)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def canvas_viewport_size(self):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1:
            width = 1000
        if height <= 1:
            height = 620
        return width, height

    def draw_node(self, node):
        if node.node_type == "loop_frame":
            self.draw_loop_frame(node)
            return
        x = self.to_screen(node.x)
        y = self.to_screen(node.y)
        w = self.to_screen(self.node_world_w(node))
        h = self.to_screen(self.node_world_h(node))
        active = node.node_id == self.active_node_id
        fill = THEME["node_active"] if active else THEME["node_selected"] if node == self.selected else THEME["node"]
        outline = THEME["node_active_outline"] if active else THEME["line_hot"] if node == self.selected else THEME["line"]
        outline_width = 3 if active else 2
        radius = max(4, int(8 * self.zoom))
        self.draw_antialiased_round_rect(x + self.to_screen(5), y + self.to_screen(6), w, h, radius, "#04070a", "")
        self.draw_antialiased_round_rect(x, y, w, h, radius, fill, outline, max(1, int(outline_width * self.zoom)))
        self.draw_antialiased_round_rect(x, y, self.to_screen(8), h, radius, THEME["accent"], THEME["accent"])
        rect = self.canvas.create_rectangle(x, y, x + w, y + h, fill="", outline="", width=0)
        self.draw_ports(node, x, y, w, h)
        title = self.canvas.create_text(x + self.to_screen(graph_ui(16)), y + self.to_screen(graph_ui(12)), text=node.title, fill=THEME["text"], anchor="nw", font=(UI_FONT, max(7, int(10 * self.zoom)), "bold"))
        detail = None
        if self.zoom >= 0.72:
            detail = self.canvas.create_text(x + self.to_screen(graph_ui(16)), y + self.to_screen(graph_ui(38)), text=self.node_summary(node), fill=THEME["muted"], anchor="nw", font=(UI_FONT, max(8, int(9 * self.zoom))), width=max(80, self.to_screen(self.node_display_w() - graph_ui(28))))
        self.node_items[rect] = node
        self.node_items[title] = node
        if detail:
            self.node_items[detail] = node

    def draw_loop_frame(self, node):
        x = self.to_screen(node.x)
        y = self.to_screen(node.y)
        w = self.to_screen(self.node_world_w(node))
        h = self.to_screen(self.node_world_h(node))
        active = node.node_id == self.active_node_id
        fill = "#10231f" if node != self.selected and not active else THEME["node_selected"]
        outline = THEME["node_active_outline"] if active else THEME["accent"] if node == self.selected else THEME["line"]
        outline_width = 3 if active or node == self.selected else 2
        radius = max(5, int(10 * self.zoom))
        header_h = self.to_screen(graph_ui(40))
        self.draw_antialiased_round_rect(x + self.to_screen(5), y + self.to_screen(6), w, h, radius, "#04070a", "")
        self.draw_antialiased_round_rect(x, y, w, h, radius, fill, outline, max(1, int(outline_width * self.zoom)))
        self.canvas.create_rectangle(x, y + header_h, x + w, y + header_h + max(1, int(self.zoom)), fill=THEME["line"], outline="")
        self.draw_antialiased_round_rect(x, y, self.to_screen(8), h, radius, THEME["accent"], THEME["accent"])
        rect = self.canvas.create_rectangle(x, y, x + w, y + h, fill="", outline="", width=0)
        title = self.canvas.create_text(
            x + self.to_screen(graph_ui(16)),
            y + self.to_screen(graph_ui(11)),
            text=node.title,
            fill=THEME["text"],
            anchor="nw",
            font=(UI_FONT, max(8, int(10 * self.zoom)), "bold"),
        )
        summary = self.canvas.create_text(
            x + self.to_screen(graph_ui(160)),
            y + self.to_screen(graph_ui(12)),
            text=self.node_summary(node),
            fill=THEME["muted"],
            anchor="nw",
            font=(UI_FONT, max(7, int(9 * self.zoom))),
            width=max(90, w - self.to_screen(graph_ui(176))),
        )
        self.draw_ports(node, x, y, w, h)
        self.draw_loop_resize_handle(node, x, y, w, h)
        self.node_items[rect] = node
        self.node_items[title] = node
        self.node_items[summary] = node

    def draw_loop_resize_handle(self, node, x, y, w, h):
        size = max(14, int(18 * self.zoom))
        pad = max(5, int(7 * self.zoom))
        x2 = x + w - pad
        y2 = y + h - pad
        x1 = x2 - size
        y1 = y2 - size
        handle = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=THEME["panel_3"],
            outline=THEME["accent"],
            width=max(1, int(2 * self.zoom)),
        )
        line_gap = max(4, int(5 * self.zoom))
        handle_items = [handle]
        for index in range(3):
            offset = index * line_gap
            line = self.canvas.create_line(
                x2 - offset,
                y2 - size + offset,
                x2 - size + offset,
                y2 - offset,
                fill=THEME["accent"],
                width=max(1, int(self.zoom)),
            )
            handle_items.append(line)
        for item in handle_items:
            self.resize_items[item] = node

    def draw_antialiased_round_rect(self, x, y, w, h, radius, fill, outline="", width=1):
        if Image is None or self.fast_canvas_render:
            return rounded_rect(self.canvas, x, y, x + w, y + h, radius, fill=fill, outline=outline, width=width)
        photo = round_rect_sprite(w, h, radius, fill, outline, width)
        self.canvas_image_refs.append(photo)
        return self.canvas.create_image(x, y, image=photo, anchor="nw")

    def draw_ports(self, node, x, y, w, h):
        r = max(5, int(graph_ui(7) * self.zoom))
        input_x = x + w / 2
        input_y = y
        output_x = x + w / 2
        output_y = y + h
        if node.node_type != "start":
            item = self.draw_port_circle(input_x, input_y, r, THEME["panel_3"], THEME["accent"], max(1, int(2 * self.zoom)))
            self.port_items[item] = (node, "input")
        if node.node_type != "end":
            item = self.draw_port_circle(output_x, output_y, r, THEME["accent"], THEME["text"], max(1, int(2 * self.zoom)))
            self.port_items[item] = (node, "output")

    def draw_port_circle(self, center_x, center_y, radius, fill, outline, width):
        if Image is not None and not self.fast_canvas_render:
            photo, image_size = port_sprite(radius, fill, outline, width)
            self.canvas_image_refs.append(photo)
            self.canvas.create_image(center_x - image_size / 2, center_y - image_size / 2, image=photo, anchor="nw")
        item = self.canvas.create_oval(
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
            fill="" if not self.fast_canvas_render else fill,
            outline="" if not self.fast_canvas_render else outline,
            width=0 if not self.fast_canvas_render else width,
        )
        return item

    def node_summary(self, node):
        if node.node_type == "recorded":
            event = node.data.get("event", {})
            if event.get("kind") == "move_path":
                return f"mouse path, {len(event.get('points', []))} points"
            if event.get("kind") == "click":
                return f"{event.get('button', 'left')} click +{event.get('delay', 0):.2f}s"
            if event.get("kind") == "key":
                return f"{event.get('key', 'key')} +{event.get('delay', 0):.2f}s"
            return f"{event.get('kind', 'event')} +{event.get('delay', 0):.2f}s"
        if node.node_type == "loop":
            settings = self.loop_settings(node)
            if settings["mode"] == "until hotkey":
                return f"until {settings.get('stop_hotkey', 'stop hotkey')}"
            return f"run script {settings['count']} times"
        if node.node_type == "loop_frame":
            settings = self.loop_settings(node)
            body_count = len(self.loop_frame_body_nodes(node))
            if settings["mode"] == "until hotkey":
                return f"{body_count} nodes until {settings.get('stop_hotkey', 'stop hotkey')}"
            return f"{body_count} nodes x {settings['count']}"
        if node.node_type == "paste" and node.data.get("source") != "clipboard":
            source = node.data.get("source")
            if source == "data":
                count = len(self.parse_inline_paste_data(str(node.data.get("data", "")), safe_int(node.data.get("column", 1), 1)))
            else:
                count = "file"
            return f"paste from {source}: {count} items"
        if node.node_type == "wait_click":
            variable = node.data.get("variable", "first_click")
            save = str(node.data.get("save_position", "yes")).lower() == "yes"
            return f"save to {variable}_x/y" if save else "continue after manual click"
        if node.node_type == "save_mouse":
            return f"save to {node.data.get('variable', 'mouse')}_x/y"
        if node.node_type == "save_clipboard":
            target = node.data.get("target", "variable")
            if target == "dataset":
                return f"append to {node.data.get('dataset', 'captured_items')}"
            if target == "file":
                return "append to file"
            return f"save to {{{node.data.get('variable', 'clipboard')}}}"
        visible_items = [(k, v) for k, v in node.data.items() if not k.startswith("_")]
        summary = ", ".join(f"{k}: {v}" for k, v in visible_items) or "No settings"
        return summary[:68] + "..." if len(summary) > 71 else summary

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        resize_node = self.find_resize_handle_at(canvas_x, canvas_y)
        if resize_node:
            self.selected = resize_node
            self.frame_resize = {
                "node": resize_node,
                "start_x": self.from_screen(canvas_x),
                "start_y": self.from_screen(canvas_y),
                "start_w": self.node_world_w(resize_node),
                "start_h": self.node_world_h(resize_node),
            }
            self.drag = None
            self.connection_drag = None
            self.drag_history_snapshot = self.document_snapshot()
            self.drag_moved = False
            self.refresh()
            return
        port = self.find_port_at(canvas_x, canvas_y, "output")
        if port and port[1] == "output":
            node = port[0]
            self.selected = node
            self.connection_drag = {
                "source": node,
                "line": None,
                "start": (self.to_screen(node.x + self.node_world_w(node) / 2), self.to_screen(node.y + self.node_world_h(node))),
            }
            self.drag = None
            self.drag_moved = False
            self.refresh()
            return
        item = self.canvas.find_closest(canvas_x, canvas_y)
        node = self.node_items.get(item[0]) if item else None
        self.selected = node
        self.drag = (node, self.from_screen(canvas_x) - node.x, self.from_screen(canvas_y) - node.y) if node else None
        self.drag_history_snapshot = self.document_snapshot() if node else None
        self.drag_moved = False
        self.refresh()

    def on_canvas_drag(self, event):
        if self.frame_resize:
            self.update_frame_resize(event)
            return
        if self.connection_drag:
            self.update_connection_preview(event)
            return
        if not self.drag:
            return
        node, dx, dy = self.drag
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        new_x = max(20, self.from_screen(canvas_x) - dx)
        new_y = max(56, self.from_screen(canvas_y) - dy)
        self.drag_moved = self.drag_moved or node.x != new_x or node.y != new_y
        node.x = new_x
        node.y = new_y
        self.refresh(update_inspector=False, update_status=False, update_scrollregion=False, fast=True)

    def on_canvas_release(self, event):
        if self.frame_resize:
            self.finish_frame_resize()
            return
        if self.connection_drag:
            self.finish_connection_drag(event)
            return
        self.drag = None
        self.nodes.sort(key=lambda n: n.y)
        if self.drag_moved:
            if self.drag_history_snapshot:
                self.push_history_snapshot(self.drag_history_snapshot)
            self.mark_dirty()
        self.drag_history_snapshot = None
        self.drag_moved = False
        self.refresh()

    def update_frame_resize(self, event):
        data = self.frame_resize
        node = data["node"]
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        new_w = max(self.node_display_w(), data["start_w"] + self.from_screen(canvas_x) - data["start_x"])
        new_h = max(self.node_display_h() * 2, data["start_h"] + self.from_screen(canvas_y) - data["start_y"])
        raw_w, raw_h = self.loop_frame_raw_size(new_w, new_h)
        self.drag_moved = self.drag_moved or node.data.get("width") != raw_w or node.data.get("height") != raw_h
        node.data["width"] = round(raw_w, 1)
        node.data["height"] = round(raw_h, 1)
        self.refresh(update_inspector=False, update_status=False, update_scrollregion=False, fast=True)

    def finish_frame_resize(self):
        self.frame_resize = None
        if self.drag_moved:
            if self.drag_history_snapshot:
                self.push_history_snapshot(self.drag_history_snapshot)
            self.mark_dirty()
        self.drag_history_snapshot = None
        self.drag_moved = False
        self.refresh()

    def update_connection_preview(self, event):
        if self.connection_drag.get("line"):
            self.canvas.delete(self.connection_drag["line"])
        start_x, start_y = self.connection_drag["start"]
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.connection_drag["line"] = self.canvas.create_line(
            start_x,
            start_y,
            canvas_x,
            canvas_y,
            fill=THEME["accent"],
            width=max(2, int(3 * self.zoom)),
            arrow=tk.LAST,
            dash=(6, 4),
        )

    def finish_connection_drag(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        target_port = self.find_port_at(canvas_x, canvas_y, "input")
        source = self.connection_drag["source"]
        self.connection_drag = None
        if target_port and target_port[1] == "input":
            target = target_port[0]
            if self.add_edge(source, target):
                self.status.set(f"Connected {source.title} -> {target.title}")
        else:
            self.refresh()

    def find_port_at(self, canvas_x, canvas_y, kind=None):
        radius = max(8, int(12 * self.zoom))
        items = self.canvas.find_overlapping(canvas_x - radius, canvas_y - radius, canvas_x + radius, canvas_y + radius)
        for item in reversed(items):
            port = self.port_items.get(item)
            if port and (kind is None or port[1] == kind):
                return port
        return None

    def find_resize_handle_at(self, canvas_x, canvas_y):
        radius = max(5, int(8 * self.zoom))
        items = self.canvas.find_overlapping(canvas_x - radius, canvas_y - radius, canvas_x + radius, canvas_y + radius)
        for item in reversed(items):
            node = self.resize_items.get(item)
            if node:
                return node
        return None

    def update_inspector(self):
        for child in self.inspector_body.winfo_children():
            child.destroy()
        self.inspector_vars.clear()
        if self.selected:
            ttk.Label(
                self.inspector_body,
                text=self.selected.title,
                style="Panel.TLabel",
                font=(UI_FONT, 12, "bold"),
            ).pack(anchor="w", pady=(2, 10))
            ttk.Label(
                self.inspector_body,
                text=NODE_TYPES[self.selected.node_type].get("description", ""),
                style="Muted.TLabel",
                wraplength=250,
            ).pack(anchor="w", pady=(0, 10))
            ttk.Label(
                self.inspector_body,
                text=f"Incoming: {len(self.incoming_edges(self.selected))}  |  Outgoing: {len(self.outgoing_edges(self.selected))}",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(0, 10))
            name_row = ttk.Frame(self.inspector_body, style="Panel.TFrame")
            name_row.pack(fill="x", pady=(0, 8))
            name_label = ttk.Label(name_row, text="name", style="Panel.TLabel", width=10)
            name_label.pack(side="left", padx=(0, 8))
            Tooltip(name_label, FIELD_DESCRIPTIONS["_label"])
            name_var = tk.StringVar(value=self.selected.title)
            name_entry = ttk.Entry(name_row, textvariable=name_var, width=22)
            name_entry.pack(side="left", fill="x", expand=True)
            Tooltip(name_entry, FIELD_DESCRIPTIONS["_label"])
            name_entry.bind("<FocusOut>", lambda _event, text=name_var: self.commit_node_label(text))
            name_entry.bind("<Return>", lambda _event, text=name_var: self.commit_node_label(text))
            for key, value in self.selected.data.items():
                if key == "_label":
                    continue
                row = ttk.Frame(self.inspector_body, style="Panel.TFrame")
                row.pack(fill="x", pady=5)
                label = ttk.Label(row, text=key, style="Panel.TLabel", width=10)
                label.pack(side="left", padx=(0, 8))
                field_help = self.field_description(key)
                Tooltip(label, field_help)
                initial = json.dumps(value) if isinstance(value, dict) else str(value)
                var = tk.StringVar(value=initial)
                options = FIELD_OPTIONS.get((self.selected.node_type, key))
                if self.selected.node_type == "paste" and key == "data":
                    entry = tk.Text(
                        row,
                        width=22,
                        height=5,
                        wrap="none",
                        bg=THEME["panel_2"],
                        fg=THEME["text"],
                        insertbackground=THEME["text"],
                        relief="flat",
                        padx=7,
                        pady=7,
                    )
                    entry.insert("1.0", initial)
                    entry.pack(side="left", fill="x", expand=True)
                    Tooltip(entry, field_help)
                    entry.bind("<FocusOut>", lambda _event, field=key, widget=entry: self.commit_inspector_text_value(field, widget))
                    entry.bind("<Control-Return>", lambda _event, field=key, widget=entry: self.commit_inspector_text_value(field, widget))
                    continue
                elif options:
                    entry = ttk.Combobox(row, textvariable=var, values=options, state="readonly", width=20)
                    entry.bind("<<ComboboxSelected>>", lambda _event, field=key, text=var: self.commit_inspector_value(field, text))
                else:
                    entry = ttk.Entry(row, textvariable=var, width=22)
                    entry.bind("<FocusOut>", lambda _event, field=key, text=var: self.commit_inspector_value(field, text))
                    entry.bind("<Return>", lambda _event, field=key, text=var: self.commit_inspector_value(field, text))
                entry.pack(side="left", fill="x", expand=True)
                Tooltip(entry, field_help)
                self.inspector_vars[key] = var
        else:
            ttk.Label(
                self.inspector_body,
                text="Select a node to edit its settings.",
                style="Muted.TLabel",
                wraplength=240,
            ).pack(anchor="w", pady=8)

    def field_description(self, key):
        return FIELD_DESCRIPTIONS.get(key, "Node setting used during playback.")

    def commit_inspector_value(self, key, var):
        if not self.selected or key not in self.selected.data:
            return
        new_value = self.coerce_value(var.get())
        if self.selected.data.get(key) != new_value:
            self.record_history()
            self.selected.data[key] = new_value
            self.mark_dirty()
            self.refresh()

    def commit_inspector_text_value(self, key, widget):
        if not self.selected or key not in self.selected.data:
            return
        new_value = widget.get("1.0", "end-1c")
        if self.selected.data.get(key) != new_value:
            self.record_history()
            self.selected.data[key] = new_value
            self.mark_dirty()
            self.refresh()

    def commit_node_label(self, var):
        if not self.selected:
            return
        value = var.get().strip()
        if not value:
            return
        default_title = NODE_TYPES[self.selected.node_type]["title"]
        old_value = self.selected.data.get("_label", default_title)
        changed = old_value != (value or default_title)
        if changed:
            self.record_history()
        if value == default_title:
            self.selected.data.pop("_label", None)
        elif value:
            self.selected.data["_label"] = value
        if changed:
            self.mark_dirty()
            self.refresh()

    def edit_selected(self, _event=None):
        if self.inspector_body.winfo_children():
            for child in self.inspector_body.winfo_children():
                for grandchild in child.winfo_children():
                    if isinstance(grandchild, ttk.Entry):
                        grandchild.focus_set()
                        return

    @staticmethod
    def coerce_value(value):
        value = value.strip()
        if value.startswith("{") or value.startswith("["):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    def duplicate_selected(self):
        if self.selected:
            self.add_node(self.selected.node_type, self.selected.x + 28, self.selected.y + 88, dict(self.selected.data))

    def begin_connection_from_selected(self):
        if not self.selected:
            return
        self.pending_connection_source = self.selected.node_id
        self.status.set(f"Connection source: {self.selected.title}")

    def connect_pending_to_selected(self):
        if not self.selected or not self.pending_connection_source:
            return
        source = self.node_by_id(self.pending_connection_source)
        if self.add_edge(source, self.selected):
            self.status.set(f"Connected {source.title} -> {self.selected.title}")
        self.pending_connection_source = None

    def unlink_selected(self):
        if not self.selected:
            return
        if not self.incoming_edges(self.selected) and not self.outgoing_edges(self.selected):
            return
        self.record_history()
        if self.remove_edges_for_node(self.selected):
            self.mark_dirty()
            self.refresh()
            self.status.set(f"Removed links for {self.selected.title}")

    def auto_link_nodes(self):
        starts = [node for node in self.nodes if node.node_type == "start"]
        ends = [node for node in self.nodes if node.node_type == "end"]
        middle = [node for node in self.nodes if node.node_type not in ("start", "end")]
        ordered = starts[:1] + sorted(middle, key=lambda n: (n.y, n.x)) + ends[:1]
        self.record_history()
        self.doc.edges = [{"from": a.node_id, "to": b.node_id} for a, b in zip(ordered, ordered[1:])]
        self.mark_dirty()
        self.refresh()
        self.status.set("Auto-linked nodes top-to-bottom")

    def auto_organize_nodes(self):
        if not self.nodes:
            return
        self.record_history()
        frames = [node for node in self.nodes if node.node_type == "loop_frame"]
        if frames:
            membership = self.loop_frame_membership_snapshot()
            top_level = [node for node in self.nodes if self.nearest_loop_frame(node) is None]
            ordered = self.organized_order(top_level)
            self.layout_scope(ordered, membership, 170, 96)
        else:
            ordered = self.organized_order(self.nodes)
            x = 170
            y = 96
            gap = 118
            for index, node in enumerate(ordered):
                node.x = x
                node.y = y + index * gap
            self.doc.edges = [{"from": a.node_id, "to": b.node_id} for a, b in zip(ordered, ordered[1:])]
        self.selected = self.selected if self.selected in self.nodes else ordered[0]
        self.mark_dirty()
        self.refresh()
        self.status.set("Auto-organized nodes")

    def organized_order(self, candidates):
        if not self.doc.edges:
            starts = [node for node in candidates if node.node_type == "start"]
            ends = [node for node in candidates if node.node_type == "end"]
            middle = [node for node in candidates if node.node_type not in ("start", "end")]
            return starts[:1] + sorted(middle, key=lambda n: (n.y, n.x)) + ends[:1]
        candidate_ids = {node.node_id for node in candidates}
        ordered = [node for node in self.workflow_order() if node.node_id in candidate_ids]
        ordered_ids = {node.node_id for node in ordered}
        missing = [node for node in candidates if node.node_id not in ordered_ids]
        starts = [node for node in missing if node.node_type == "start"]
        ends = [node for node in missing if node.node_type == "end"]
        middle = [node for node in missing if node.node_type not in ("start", "end")]
        ordered = starts + ordered + sorted(middle, key=lambda n: (n.y, n.x)) + ends
        seen = set()
        unique = []
        for node in ordered:
            if node.node_id not in seen:
                unique.append(node)
                seen.add(node.node_id)
        return unique

    def loop_frame_membership_snapshot(self):
        membership = {frame.node_id: [] for frame in self.nodes if frame.node_type == "loop_frame"}
        for node in self.nodes:
            frame = self.nearest_loop_frame(node)
            if frame:
                membership.setdefault(frame.node_id, []).append(node)
        return membership

    def layout_scope(self, nodes, membership, x, y):
        cursor_y = y
        gap = 118
        for node in self.organized_order(nodes):
            node.x = x
            node.y = cursor_y
            if node.node_type == "loop_frame":
                body = membership.get(node.node_id, [])
                self.layout_scope(body, membership, x + 72, cursor_y + 92)
                self.resize_loop_frame_to_children(node, body)
            cursor_y += self.node_world_h(node) + gap
        return cursor_y

    def resize_loop_frame_to_children(self, frame, children):
        if not children:
            raw_w, raw_h = self.loop_frame_raw_size(self.node_display_w() * 1.8, self.node_display_h() * 2.4)
            frame.data["width"] = round(raw_w, 1)
            frame.data["height"] = round(raw_h, 1)
            return
        padding = 72
        bottom_padding = 72
        right = max(child.x + self.node_world_w(child) for child in children)
        bottom = max(child.y + self.node_world_h(child) for child in children)
        world_w = max(self.node_display_w() * 1.8, right - frame.x + padding)
        world_h = max(self.node_display_h() * 2.4, bottom - frame.y + bottom_padding)
        raw_w, raw_h = self.loop_frame_raw_size(world_w, world_h)
        frame.data["width"] = round(raw_w, 1)
        frame.data["height"] = round(raw_h, 1)

    def delete_selected(self):
        if self.selected in self.nodes:
            self.record_history()
            self.remove_edges_for_node(self.selected)
            self.nodes.remove(self.selected)
            self.selected = None
            self.mark_dirty()
            self.refresh()

    def move_selected(self, direction):
        if self.selected not in self.nodes:
            return
        idx = self.nodes.index(self.selected)
        new_idx = min(max(idx + direction, 0), len(self.nodes) - 1)
        if new_idx == idx:
            return
        self.record_history()
        self.nodes[idx], self.nodes[new_idx] = self.nodes[new_idx], self.nodes[idx]
        self.selected.y, self.nodes[idx].y = self.nodes[idx].y, self.selected.y
        self.mark_dirty()
        self.refresh()

    def clear_nodes(self):
        if messagebox.askyesno("Clear Script", "Remove all nodes from this script?"):
            self.record_history()
            self.nodes.clear()
            self.doc.edges.clear()
            self.selected = None
            self.mark_dirty()
            self.refresh()

    def new_macro(self):
        self.untitled_counter += 1
        start = MacroNode("start", 80, 80, {})
        end = MacroNode("end", 80, 220, {})
        self.add_document(
            MacroDocument(
                name=f"Untitled {self.untitled_counter}",
                nodes=[start, end],
                edges=[{"from": start.node_id, "to": end.node_id}],
            )
        )
        self.status.set("New script tab")

    def save_macro(self):
        self.save_document(self.doc)

    def load_macro(self):
        path = filedialog.askopenfilename(filetypes=MACRO_FILETYPES)
        if path:
            self.open_macro_file(Path(path))

    def open_macro_file(self, path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        nodes = [
            MacroNode(
                item["type"],
                item.get("x", 80),
                item.get("y", 80),
                item.get("data", {}),
                item.get("id") or item.get("node_id") or uuid.uuid4().hex[:10],
            )
            for item in payload.get("nodes", [])
        ]
        doc = MacroDocument(
            name=path.stem,
            file_path=path,
            nodes=nodes,
            edges=payload.get("edges", []),
        )
        if not doc.edges and len(doc.nodes) > 1:
            ordered = sorted(doc.nodes, key=lambda n: (n.y, n.x))
            doc.edges = [{"from": a.node_id, "to": b.node_id} for a, b in zip(ordered, ordered[1:])]
        doc.selected = doc.nodes[0] if doc.nodes else None
        self.add_document(doc)
        self.add_recent_file(path)
        self.status.set(f"Loaded {path.name}")

    def write_macro(self, doc, path):
        payload = {
            "version": MACRO_VERSION,
            "nodes": [{"id": n.node_id, "type": n.node_type, "x": n.x, "y": n.y, "data": n.data} for n in doc.nodes],
            "edges": doc.edges,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add_recent_file(self, path):
        path_text = str(Path(path))
        recent = [p for p in self.settings.get("recent_files", []) if p != path_text and Path(p).exists()]
        self.settings["recent_files"] = [path_text, *recent][:10]
        self.save_settings()
        self.update_recent_menu()

    def update_recent_menu(self):
        values = self.settings.get("recent_files", [])
        if hasattr(self, "recent_combo"):
            self.recent_combo["values"] = values
        if hasattr(self, "recent_var"):
            self.recent_var.set("Open recent..." if values else "No recent scripts")
        if hasattr(self, "recent_menu"):
            self.recent_menu.delete(0, "end")
            if not values:
                self.recent_menu.add_command(label="No recent scripts", state="disabled")
                return
            for path_text in values:
                label = Path(path_text).name or path_text
                self.recent_menu.add_command(
                    label=label,
                    command=lambda selected=path_text: self.open_recent_path(selected),
                )

    def open_recent_path(self, path_text):
        path = Path(path_text)
        if path.exists():
            self.open_macro_file(path)

    def open_recent_selected(self, _event=None):
        path_text = self.recent_var.get()
        self.open_recent_path(path_text)
        self.recent_var.set("Open recent...")

    def open_settings(self):
        if hasattr(self, "modal_overlay") and self.modal_overlay.winfo_exists():
            self.modal_overlay.lift()
            return
        self.modal_overlay = tk.Frame(self, bg="#05080b")
        self.modal_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.modal_overlay.lift()
        self.modal_overlay.grab_set()

        card_shadow = tk.Frame(self.modal_overlay, bg=THEME["button_shadow"])
        card_shadow.place(relx=0.5, rely=0.5, anchor="center", width=468, height=338)
        card = tk.Frame(self.modal_overlay, bg=THEME["panel"], highlightthickness=1, highlightbackground=THEME["line"])
        card.place(relx=0.5, rely=0.5, anchor="center", width=456, height=326)
        fields = {}
        rows = [
            ("Record hotkey", "record_hotkey"),
            ("Play hotkey", "play_hotkey"),
            ("Stop hotkey", "stop_hotkey"),
            ("Playback countdown", "playback_countdown"),
        ]
        body = ttk.Frame(card, style="Panel.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Settings", style="Panel.TLabel", font=(UI_FONT, 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        for idx, (label, key) in enumerate(rows, start=1):
            ttk.Label(body, text=label, style="Panel.TLabel").grid(row=idx, column=0, sticky="w", padx=(0, 12), pady=6)
            var = tk.StringVar(value=str(self.settings[key]))
            ttk.Entry(body, textvariable=var, width=28).grid(row=idx, column=1, sticky="ew", pady=6)
            fields[key] = var
        ttk.Label(body, text="Use pynput format, like <ctrl>+<shift>+r", style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 12))

        def save():
            try:
                countdown = max(0, int(fields["playback_countdown"].get()))
            except ValueError:
                messagebox.showerror("Invalid countdown", "Playback countdown must be a number.")
                return
            for key in ("record_hotkey", "play_hotkey", "stop_hotkey"):
                self.settings[key] = fields[key].get().strip()
            self.settings["playback_countdown"] = countdown
            self.save_settings()
            self.install_global_hotkeys()
            self.refresh()
            self.close_modal()
            self.status.set("Settings saved")

        buttons = ttk.Frame(body, style="Panel.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        RoundedButton(buttons, text="Cancel", command=self.close_modal, width=96, height=36).pack(side="left", padx=4)
        RoundedButton(buttons, text="Save", command=save, width=96, height=36, accent=True).pack(side="left", padx=4)
        self.bind("<Escape>", lambda _event: self.close_modal(), add="+")

    def close_modal(self):
        if hasattr(self, "modal_overlay") and self.modal_overlay.winfo_exists():
            self.modal_overlay.grab_release()
            self.modal_overlay.destroy()

    def stop_all(self):
        self.playing = False
        if self.recording:
            self.stop_recording()
        self.stop_playback_stop_listener()
        self.status.set("Stopped")

    def request_stop_all(self):
        self.playing = False
        self.recording = False
        try:
            self.after(0, self.stop_all)
        except RuntimeError:
            pass

    def on_close(self):
        self.stop_all()
        for doc in list(self.documents):
            if not self.confirm_save_if_dirty(doc):
                return
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        self.save_settings()
        self.destroy()


if __name__ == "__main__":
    app = MacroStudio()
    app.mainloop()
