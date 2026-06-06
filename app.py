import ctypes
import csv
import json
import subprocess
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


APP_TITLE = "Macro Studio"
NODE_W = 202
NODE_H = 72
MACRO_VERSION = 2
CONFIG_PATH = Path.home() / ".macro_studio.json"
UI_FONT = "Segoe UI Variable"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
APP_ICON_PNG = ASSETS_DIR / "macro-studio-logo.png"
WORKSPACE_MIN_W = 2200
WORKSPACE_MIN_H = 1800

DEFAULT_SETTINGS = {
    "record_hotkey": "<ctrl>+<shift>+r",
    "play_hotkey": "<ctrl>+<shift>+p",
    "stop_hotkey": "<ctrl>+<shift>+x",
    "playback_countdown": 3,
    "recent_files": [],
}

THEME = {
    "bg": "#0b1116",
    "panel": "#121b20",
    "panel_2": "#1a262d",
    "panel_3": "#24343d",
    "line": "#344955",
    "tab_outline": "#3e5663",
    "line_hot": "#42d392",
    "text": "#edf4f7",
    "muted": "#9baeba",
    "accent": "#42d392",
    "accent_dark": "#208a5a",
    "accent_text": "#06130d",
    "node": "#1b2831",
    "node_selected": "#214f3b",
    "canvas": "#080d12",
    "button": "#24333d",
    "button_hover": "#2d414d",
    "button_shadow": "#0a0f13",
    "danger": "#b94d5c",
}


PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", InputUnion)]


class WindowsInput:
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800

    VK = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "shift": 0x10,
        "shift_l": 0x10,
        "shift_r": 0x10,
        "ctrl": 0x11,
        "ctrl_l": 0x11,
        "ctrl_r": 0x11,
        "alt": 0x12,
        "alt_l": 0x12,
        "alt_r": 0x12,
        "esc": 0x1B,
        "space": 0x20,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "delete": 0x2E,
        "cmd": 0x5B,
        "win": 0x5B,
    }
    VK.update({chr(i): i for i in range(0x30, 0x3A)})
    VK.update({chr(i + 32): i for i in range(0x41, 0x5B)})
    VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})

    @staticmethod
    def _send(inp):
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    @classmethod
    def key_down(cls, key):
        vk = cls.key_to_vk(key)
        if vk is not None:
            cls._send(Input(cls.INPUT_KEYBOARD, InputUnion(ki=KeyBdInput(vk, 0, 0, 0, None))))

    @classmethod
    def key_up(cls, key):
        vk = cls.key_to_vk(key)
        if vk is not None:
            cls._send(Input(cls.INPUT_KEYBOARD, InputUnion(ki=KeyBdInput(vk, 0, cls.KEYEVENTF_KEYUP, 0, None))))

    @classmethod
    def key_tap(cls, key):
        cls.key_down(key)
        time.sleep(0.02)
        cls.key_up(key)

    @classmethod
    def hotkey(cls, keys):
        for key in keys:
            cls.key_down(key)
            time.sleep(0.02)
        for key in reversed(keys):
            cls.key_up(key)
            time.sleep(0.02)

    @classmethod
    def type_text(cls, text):
        for char in text:
            cls.key_tap(char.lower())
            time.sleep(0.01)

    @classmethod
    def move_mouse(cls, x, y):
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        ax = int(x * 65535 / max(screen_w - 1, 1))
        ay = int(y * 65535 / max(screen_h - 1, 1))
        cls._send(
            Input(
                cls.INPUT_MOUSE,
                InputUnion(mi=MouseInput(ax, ay, 0, cls.MOUSEEVENTF_MOVE | cls.MOUSEEVENTF_ABSOLUTE, 0, None)),
            )
        )

    @classmethod
    def mouse_button(cls, button, pressed):
        flags = {
            "left": (cls.MOUSEEVENTF_LEFTDOWN, cls.MOUSEEVENTF_LEFTUP),
            "right": (cls.MOUSEEVENTF_RIGHTDOWN, cls.MOUSEEVENTF_RIGHTUP),
            "middle": (cls.MOUSEEVENTF_MIDDLEDOWN, cls.MOUSEEVENTF_MIDDLEUP),
        }.get(button, (cls.MOUSEEVENTF_LEFTDOWN, cls.MOUSEEVENTF_LEFTUP))
        cls._send(Input(cls.INPUT_MOUSE, InputUnion(mi=MouseInput(0, 0, 0, flags[0 if pressed else 1], 0, None))))

    @classmethod
    def scroll(cls, amount):
        cls._send(Input(cls.INPUT_MOUSE, InputUnion(mi=MouseInput(0, 0, int(amount) * 120, cls.MOUSEEVENTF_WHEEL, 0, None))))

    @classmethod
    def key_to_vk(cls, key):
        if len(key) == 1:
            return cls.VK.get(key.lower())
        return cls.VK.get(key.lower().replace("key.", ""))


def rounded_rect(canvas, x1, y1, x2, y2, radius=8, **kwargs):
    radius = min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2))
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, width=118, height=40, accent=False, danger=False):
        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = THEME["panel"]
        super().__init__(
            parent,
            width=width,
            height=height + 4,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.text = text
        self.command = command
        self.width_px = width
        self.height_px = height
        self.fill = THEME["accent_dark"] if accent else THEME["danger"] if danger else THEME["button"]
        self.hover_fill = THEME["accent"] if accent else "#c2606e" if danger else THEME["button_hover"]
        self.text_fill = THEME["accent_text"] if accent else THEME["text"]
        self.draw(self.fill)
        self.bind("<Enter>", lambda _event: self.draw(self.hover_fill))
        self.bind("<Leave>", lambda _event: self.draw(self.fill))
        self.bind("<ButtonPress-1>", lambda _event: self.move("button", 0, 1))
        self.bind("<ButtonRelease-1>", self.on_release)

    def draw(self, fill):
        self.delete("all")
        rounded_rect(self, 3, 5, self.width_px - 1, self.height_px + 2, 7, fill=THEME["button_shadow"], outline="", tags="button")
        rounded_rect(self, 1, 1, self.width_px - 3, self.height_px - 1, 7, fill=fill, outline="#334751", tags="button")
        self.create_text(
            int(self.width_px / 2) - 1,
            int(self.height_px / 2),
            text=self.text,
            fill=self.text_fill,
            font=(UI_FONT, 10, "bold"),
            tags="button",
        )

    def on_release(self, _event):
        self.draw(self.fill)
        self.command()


class Tooltip:
    def __init__(self, widget, text, delay=700, wraplength=320):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.after_id = None
        self.tip = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, _event=None):
        self.cancel()
        self.after_id = self.widget.after(self.delay, self.show)

    def cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(self.tip, bg=THEME["button_shadow"], padx=1, pady=1)
        frame.pack()
        label = tk.Label(
            frame,
            text=self.text,
            bg=THEME["panel_3"],
            fg=THEME["text"],
            justify="left",
            wraplength=self.wraplength,
            padx=10,
            pady=8,
            font=(UI_FONT, 9),
        )
        label.pack()

    def hide(self, _event=None):
        self.cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def colorref(hex_color):
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


@dataclass
class MacroNode:
    node_type: str
    x: int
    y: int
    data: dict = field(default_factory=dict)

    @property
    def title(self):
        return self.data.get("_label") or NODE_TYPES[self.node_type]["title"]


@dataclass
class MacroDocument:
    name: str = "Untitled"
    file_path: Path | None = None
    nodes: list[MacroNode] = field(default_factory=list)
    selected: MacroNode | None = None
    dirty: bool = False

    @property
    def tab_title(self):
        name = self.file_path.stem if self.file_path else self.name
        marker = "*" if self.dirty else ""
        return f"{marker}{name}  x"


NODE_TYPES = {
    "loop": {"title": "Loop Script", "defaults": {"count": 3}, "description": "Repeats the active script a fixed number of times. The loop node itself is skipped during playback and acts as a script-level repeat setting."},
    "counter": {"title": "Counter", "defaults": {"name": "counter", "start": 1, "step": 1}, "description": "Tracks a named number while playback runs. Use placeholders like {counter} in Type Text, Set Clipboard, or Paste data values."},
    "delay": {"title": "Delay", "defaults": {"seconds": 0.5}, "description": "Pauses playback for a number of seconds. Useful between clicks, launches, and pages that need time to load."},
    "click": {"title": "Mouse Click", "defaults": {"button": "left", "x": 500, "y": 500}, "description": "Moves the mouse to a screen coordinate and clicks a button. Coordinates are absolute screen pixels."},
    "move": {"title": "Mouse Move", "defaults": {"x": 500, "y": 500}, "description": "Moves the mouse pointer to a screen coordinate without clicking."},
    "scroll": {"title": "Scroll", "defaults": {"direction": "down", "amount": 3}, "description": "Scrolls the mouse wheel up or down by a chosen amount. The mouse stays wherever it currently is."},
    "key": {"title": "Key Tap", "defaults": {"key": "enter"}, "description": "Presses and releases a single key such as enter, tab, esc, delete, or an arrow key."},
    "hotkey": {"title": "Hotkey", "defaults": {"keys": "ctrl+c"}, "description": "Presses a key combination. Use plus signs between keys, such as ctrl+s, ctrl+shift+v, or alt+tab."},
    "type": {"title": "Type Text", "defaults": {"text": "Hello"}, "description": "Types text using keyboard events. Supports placeholders like {iteration}, {loop_count}, and named counters."},
    "copy": {"title": "Copy", "defaults": {}, "description": "Runs Ctrl+C in the focused app."},
    "cut": {"title": "Cut", "defaults": {}, "description": "Runs Ctrl+X in the focused app."},
    "paste": {"title": "Paste", "defaults": {"source": "clipboard", "data": "", "file_path": "", "column": 1}, "description": "Pastes from the current clipboard, inline rows, or a CSV/TSV file. Data sources advance one item per paste, which pairs well with Loop Script."},
    "clipboard": {"title": "Set Clipboard", "defaults": {"text": "Clipboard text"}, "description": "Sets the clipboard text without immediately pasting. Supports placeholders for loops and counters."},
    "launch": {"title": "Launch App", "defaults": {"command": "notepad"}, "description": "Starts an app or command, such as notepad or a full executable path."},
    "recorded": {"title": "Recorded Event", "defaults": {"event": {}}, "description": "A captured mouse, keyboard, scroll, or grouped mouse-path event created by the recorder."},
}

FIELD_DESCRIPTIONS = {
    "_label": "Optional display name for this node. Leaving it as the default keeps the standard node title.",
    "count": "How many times to run the active script. Minimum is 1.",
    "name": "Counter name. Use the same name in placeholders, for example {counter}.",
    "start": "Initial counter value before the first step is applied.",
    "step": "How much the counter changes each time this node runs.",
    "seconds": "Pause duration in seconds. Decimals are allowed.",
    "button": "Mouse button to click.",
    "x": "Absolute screen X coordinate in pixels.",
    "y": "Absolute screen Y coordinate in pixels.",
    "direction": "Scroll wheel direction.",
    "amount": "Scroll strength. Larger numbers scroll farther.",
    "key": "Single key to press and release.",
    "keys": "Hotkey combination separated by plus signs, such as ctrl+c or ctrl+shift+s.",
    "text": "Text value. Supports placeholders like {iteration}, {loop_count}, and named counters.",
    "source": "Paste source: clipboard uses current clipboard, data uses rows in this node, file reads CSV/TSV.",
    "data": "Inline paste rows. You can paste a copied Excel column/table here; the column setting chooses which column to use.",
    "file_path": "Path to a CSV or TSV file. Use with source=file.",
    "column": "1-based column number to read from inline table data or CSV/TSV file.",
    "command": "Program or shell command to launch.",
    "event": "Raw recorded event data. Usually best left alone unless you are editing recorded playback manually.",
}

FIELD_OPTIONS = {
    ("click", "button"): ["left", "right", "middle"],
    ("hotkey", "keys"): ["ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+s", "alt+tab"],
    ("key", "key"): ["enter", "tab", "esc", "space", "backspace", "delete", "left", "right", "up", "down"],
    ("scroll", "direction"): ["down", "up"],
    ("paste", "source"): ["clipboard", "data", "file"],
}


class MacroStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.app_icon = None
        self.geometry("1260x800")
        self.minsize(1040, 660)
        self.configure(bg=THEME["bg"])
        self.settings = self.load_settings()
        self.documents = []
        self.tab_to_doc = {}
        self.untitled_counter = 0
        self.node_items = {}
        self.inspector_vars = {}
        self.suppress_dirty = False
        self.drag = None
        self.drag_moved = False
        self.zoom = 1.0
        self.recording = False
        self.playing = False
        self.record_start = 0
        self.last_recorded_move = 0
        self.last_recorded_pos = None
        self.recorded_move_path = []
        self.play_context = None
        self.listeners = []
        self.hotkey_listener = None
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
        current = self.tabs.select() if hasattr(self, "tabs") else None
        return self.tab_to_doc.get(current, self.documents[0])

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

    def _style_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", (UI_FONT, 10))
        self.option_add("*TCombobox*Listbox.background", THEME["panel_2"])
        self.option_add("*TCombobox*Listbox.foreground", THEME["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", THEME["accent_dark"])
        self.option_add("*TCombobox*Listbox.selectForeground", THEME["accent_text"])
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
            background=THEME["bg"],
            tabmargins=(0, 8, 0, 0),
            borderwidth=0,
            lightcolor=THEME["bg"],
            darkcolor=THEME["bg"],
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
        if APP_ICON_PNG.exists():
            try:
                self.app_icon = tk.PhotoImage(file=APP_ICON_PNG)
                self.iconphoto(True, self.app_icon)
            except tk.TclError:
                self.app_icon = None

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

        toolbar = ttk.Frame(self, style="Panel.TFrame", padding=(10, 8))
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.draw_header_logo(toolbar)
        ttk.Label(toolbar, text=APP_TITLE, style="Panel.TLabel", font=(UI_FONT, 13, "bold")).pack(side="left", padx=(8, 14))
        for text, command, accent in [
            ("New", self.new_macro, False),
            ("Open", self.load_macro, False),
            ("Save", self.save_macro, False),
            ("Close Tab", self.close_tab, False),
            ("Zoom -", self.zoom_out, False),
            ("Zoom +", self.zoom_in, False),
            ("Record", self.toggle_recording, True),
            ("Play", self.play_macro, True),
            ("Stop", self.stop_all, False),
            ("Settings", self.open_settings, False),
        ]:
            RoundedButton(toolbar, text=text, command=command, width=112, accent=accent).pack(side="left", padx=4)

        ttk.Label(toolbar, text="Recent", style="Panel.TLabel").pack(side="left", padx=(16, 6))
        self.recent_var = tk.StringVar(value="Open recent...")
        self.recent_combo = ttk.Combobox(toolbar, textvariable=self.recent_var, width=32, state="readonly")
        self.recent_combo.pack(side="left", padx=3)
        self.recent_combo.bind("<<ComboboxSelected>>", self.open_recent_selected)
        self.script_status = tk.StringVar(value="Saved")
        ttk.Label(toolbar, textvariable=self.script_status, style="Muted.TLabel").pack(side="left", padx=(12, 0))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(toolbar, textvariable=self.status, style="Muted.TLabel").pack(side="right")

        palette = ttk.Frame(self, style="Panel.TFrame", padding=10)
        palette.grid(row=1, column=0, rowspan=2, sticky="ns")
        ttk.Label(palette, text="Nodes", style="Panel.TLabel", font=(UI_FONT, 12, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(palette, text="Drop actions into the flow", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        for node_type, spec in NODE_TYPES.items():
            if node_type != "recorded":
                button = RoundedButton(
                    palette,
                    text=spec["title"],
                    command=lambda kind=node_type: self.add_node(kind),
                    width=174,
                    height=38,
                )
                button.pack(fill="x", pady=3)
                Tooltip(button, spec.get("description", ""))

        self.tabs = ttk.Notebook(self)
        self.tabs.configure(takefocus=False)
        self.tabs.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        self.tabs.bind("<<NotebookTabChanged>>", lambda _event: self.refresh())
        self.tabs.bind("<ButtonRelease-1>", self.on_tab_click, add="+")

        canvas_shell = ttk.Frame(self, style="Panel.TFrame")
        canvas_shell.grid(row=2, column=1, sticky="nsew", padx=(8, 8), pady=(0, 8))
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
        props.grid(row=1, column=2, rowspan=2, sticky="ns")
        ttk.Label(props, text="Inspector", style="Panel.TLabel", font=(UI_FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(props, text="Edit the selected action", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.inspector_body = ttk.Frame(props, style="Panel.TFrame")
        self.inspector_body.pack(fill="both", expand=True, pady=4)
        for text, command, danger in [
            ("Duplicate", self.duplicate_selected, False),
            ("Delete Node", self.delete_selected, True),
            ("Move Up", lambda: self.move_selected(-1), False),
            ("Move Down", lambda: self.move_selected(1), False),
            ("Clear Script", self.clear_nodes, True),
        ]:
            RoundedButton(props, text=text, command=command, width=260, height=38, danger=danger).pack(fill="x", pady=3)
        self.update_recent_menu()

    def draw_header_logo(self, parent):
        logo = tk.Canvas(parent, width=30, height=30, bg=THEME["panel"], highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 2))
        rounded_rect(logo, 3, 3, 27, 27, 7, fill=THEME["panel_3"], outline=THEME["line"])
        logo.create_line(9, 20, 9, 11, 16, 16, 22, 10, 22, 20, fill=THEME["accent"], width=3, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        for x, y in [(9, 20), (16, 16), (22, 20)]:
            logo.create_oval(x - 3, y - 3, x + 3, y + 3, fill=THEME["text"], outline=THEME["accent"])

    def _bind_shortcuts(self):
        self.bind("<Control-s>", lambda _e: self.save_macro())
        self.bind("<Control-o>", lambda _e: self.load_macro())
        self.bind("<Control-n>", lambda _e: self.new_macro())
        self.bind("<Delete>", lambda _e: self.delete_selected())
        self.bind("<space>", lambda _e: self.play_macro())
        self.bind("<Escape>", lambda _e: self.stop_all())
        self.bind("<Control-plus>", lambda _e: self.zoom_in())
        self.bind("<Control-equal>", lambda _e: self.zoom_in())
        self.bind("<Control-minus>", lambda _e: self.zoom_out())
        self.bind("<Control-0>", lambda _e: self.set_zoom(1.0))

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
            self.settings["record_hotkey"]: lambda: self.after(0, self.toggle_recording),
            self.settings["play_hotkey"]: lambda: self.after(0, self.play_macro),
            self.settings["stop_hotkey"]: lambda: self.after(0, self.stop_all),
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

    def update_current_tab_title(self):
        current = self.tabs.select()
        if current:
            self.tabs.tab(current, text=self.doc.tab_title)
        if hasattr(self, "script_status"):
            self.script_status.set("Unsaved changes" if self.doc.dirty else "Saved")
        if hasattr(self, "graph_info"):
            self.graph_info.set(
                f"{clean_tab_title(self.doc.tab_title)}  |  {len(self.nodes)} nodes  |  "
                f"Zoom {int(self.zoom * 100)}%  |  Record {display_hotkey(self.settings['record_hotkey'])}"
            )

    def on_tab_click(self, event):
        try:
            index = self.tabs.index(f"@{event.x},{event.y}")
            bbox = self.tabs.bbox(index)
        except tk.TclError:
            return
        if not bbox:
            return
        close_x1 = bbox[0] + bbox[2] - 16
        close_x2 = bbox[0] + bbox[2] - 4
        close_y1 = bbox[1] + 5
        close_y2 = bbox[1] + bbox[3] - 5
        if close_x1 <= event.x <= close_x2 and close_y1 <= event.y <= close_y2:
            self.close_tab(index)
            return "break"

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
            path = filedialog.asksaveasfilename(defaultextension=".macro.json", filetypes=[("Macro files", "*.macro.json"), ("JSON", "*.json")])
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
        defaults = dict(NODE_TYPES[node_type]["defaults"])
        if data:
            defaults.update(data)
        node = MacroNode(node_type, x or 80, y or 70 + len(self.nodes) * 88, defaults)
        self.nodes.append(node)
        self.selected = node
        self.mark_dirty()
        self.refresh()

    def refresh(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        self.node_items.clear()
        self.update_canvas_scrollregion()
        ordered = sorted(self.nodes, key=lambda n: n.y)
        for i, node in enumerate(ordered[:-1]):
            nxt = ordered[i + 1]
            color = THEME["line"]
            width = 2
            if nxt == self.selected:
                color = THEME["danger"]
                width = 3
            elif node == self.selected:
                color = THEME["accent"]
                width = 3
            self.canvas.create_line(
                self.to_screen(node.x + NODE_W / 2),
                self.to_screen(node.y + NODE_H),
                self.to_screen(nxt.x + NODE_W / 2),
                self.to_screen(nxt.y),
                fill=color,
                width=max(1, int(width * self.zoom)),
                arrow=tk.LAST,
            )
        for node in ordered:
            self.draw_node(node)
        self.update_inspector()
        self.update_current_tab_title()

    def update_canvas_scrollregion(self):
        viewport_w, viewport_h = self.canvas_viewport_size()
        if not self.nodes:
            self.canvas.configure(scrollregion=(0, 0, viewport_w, viewport_h))
            return
        max_x = WORKSPACE_MIN_W
        max_y = WORKSPACE_MIN_H
        for node in self.nodes:
            max_x = max(max_x, node.x + NODE_W + 300)
            max_y = max(max_y, node.y + NODE_H + 300)
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
        x = self.to_screen(node.x)
        y = self.to_screen(node.y)
        w = self.to_screen(NODE_W)
        h = self.to_screen(NODE_H)
        fill = THEME["node_selected"] if node == self.selected else THEME["node"]
        outline = THEME["line_hot"] if node == self.selected else THEME["line"]
        radius = max(4, int(8 * self.zoom))
        rounded_rect(self.canvas, x + self.to_screen(5), y + self.to_screen(6), x + w + self.to_screen(5), y + h + self.to_screen(6), radius, fill="#04070a", outline="")
        rect = rounded_rect(self.canvas, x, y, x + w, y + h, radius, fill=fill, outline=outline, width=max(1, int(2 * self.zoom)))
        rounded_rect(self.canvas, x, y, x + self.to_screen(8), y + h, radius, fill=THEME["accent"], outline=THEME["accent"])
        title = self.canvas.create_text(x + self.to_screen(16), y + self.to_screen(12), text=node.title, fill=THEME["text"], anchor="nw", font=(UI_FONT, max(7, int(10 * self.zoom)), "bold"))
        detail = None
        if self.zoom >= 0.72:
            detail = self.canvas.create_text(x + self.to_screen(16), y + self.to_screen(38), text=self.node_summary(node), fill=THEME["muted"], anchor="nw", font=(UI_FONT, max(8, int(9 * self.zoom))), width=max(80, self.to_screen(NODE_W - 28)))
        self.node_items[rect] = node
        self.node_items[title] = node
        if detail:
            self.node_items[detail] = node

    def node_summary(self, node):
        if node.node_type == "recorded":
            event = node.data.get("event", {})
            if event.get("kind") == "move_path":
                return f"mouse path, {len(event.get('points', []))} points"
            return f"{event.get('kind', 'event')}  +{event.get('delay', 0):.2f}s"
        if node.node_type == "loop":
            return f"run script {node.data.get('count', 1)} times"
        if node.node_type == "paste" and node.data.get("source") != "clipboard":
            source = node.data.get("source")
            if source == "data":
                count = len(self.parse_inline_paste_data(str(node.data.get("data", "")), safe_int(node.data.get("column", 1), 1)))
            else:
                count = "file"
            return f"paste from {source}: {count} items"
        visible_items = [(k, v) for k, v in node.data.items() if not k.startswith("_")]
        summary = ", ".join(f"{k}: {v}" for k, v in visible_items) or "No settings"
        return summary[:68] + "..." if len(summary) > 71 else summary

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        item = self.canvas.find_closest(canvas_x, canvas_y)
        node = self.node_items.get(item[0]) if item else None
        self.selected = node
        self.drag = (node, self.from_screen(canvas_x) - node.x, self.from_screen(canvas_y) - node.y) if node else None
        self.drag_moved = False
        self.refresh()

    def on_canvas_drag(self, event):
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
        self.refresh()

    def on_canvas_release(self, _event):
        self.drag = None
        self.nodes.sort(key=lambda n: n.y)
        if self.drag_moved:
            self.mark_dirty()
        self.drag_moved = False
        self.refresh()

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
            self.selected.data[key] = new_value
            self.mark_dirty()
            self.refresh()

    def commit_inspector_text_value(self, key, widget):
        if not self.selected or key not in self.selected.data:
            return
        new_value = widget.get("1.0", "end-1c")
        if self.selected.data.get(key) != new_value:
            self.selected.data[key] = new_value
            self.mark_dirty()
            self.refresh()

    def commit_node_label(self, var):
        if not self.selected:
            return
        value = var.get().strip()
        default_title = NODE_TYPES[self.selected.node_type]["title"]
        old_value = self.selected.data.get("_label", default_title)
        if value == default_title:
            self.selected.data.pop("_label", None)
        elif value:
            self.selected.data["_label"] = value
        if old_value != self.selected.title:
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

    def delete_selected(self):
        if self.selected in self.nodes:
            self.nodes.remove(self.selected)
            self.selected = None
            self.mark_dirty()
            self.refresh()

    def move_selected(self, direction):
        if self.selected not in self.nodes:
            return
        idx = self.nodes.index(self.selected)
        new_idx = min(max(idx + direction, 0), len(self.nodes) - 1)
        self.nodes[idx], self.nodes[new_idx] = self.nodes[new_idx], self.nodes[idx]
        self.selected.y, self.nodes[idx].y = self.nodes[idx].y, self.selected.y
        self.mark_dirty()
        self.refresh()

    def clear_nodes(self):
        if messagebox.askyesno("Clear Script", "Remove all nodes from this script?"):
            self.nodes.clear()
            self.selected = None
            self.mark_dirty()
            self.refresh()

    def new_macro(self):
        self.untitled_counter += 1
        self.add_document(MacroDocument(name=f"Untitled {self.untitled_counter}"))
        self.status.set("New script tab")

    def save_macro(self):
        self.save_document(self.doc)

    def load_macro(self):
        path = filedialog.askopenfilename(filetypes=[("Macro files", "*.macro.json"), ("JSON", "*.json")])
        if path:
            self.open_macro_file(Path(path))

    def open_macro_file(self, path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        doc = MacroDocument(
            name=path.stem,
            file_path=path,
            nodes=[MacroNode(item["type"], item.get("x", 80), item.get("y", 80), item.get("data", {})) for item in payload.get("nodes", [])],
        )
        doc.selected = doc.nodes[0] if doc.nodes else None
        self.add_document(doc)
        self.add_recent_file(path)
        self.status.set(f"Loaded {path.name}")

    def write_macro(self, doc, path):
        payload = {
            "version": MACRO_VERSION,
            "nodes": [{"type": n.node_type, "x": n.x, "y": n.y, "data": n.data} for n in doc.nodes],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add_recent_file(self, path):
        path_text = str(Path(path))
        recent = [p for p in self.settings.get("recent_files", []) if p != path_text and Path(p).exists()]
        self.settings["recent_files"] = [path_text, *recent][:10]
        self.save_settings()
        self.update_recent_menu()

    def update_recent_menu(self):
        if not hasattr(self, "recent_combo"):
            return
        values = self.settings.get("recent_files", [])
        self.recent_combo["values"] = values
        self.recent_var.set("Open recent..." if values else "No recent scripts")

    def open_recent_selected(self, _event=None):
        path_text = self.recent_var.get()
        if Path(path_text).exists():
            self.open_macro_file(Path(path_text))
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

    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if keyboard is None or mouse is None:
            messagebox.showerror("Recording unavailable", "Install pynput first:\n\npython -m pip install -r requirements.txt")
            return
        self.recording = True
        self.record_start = time.perf_counter()
        self.last_recorded_move = 0
        self.last_recorded_pos = None
        self.recorded_move_path = []
        self.status.set(f"Recording... stop with {display_hotkey(self.settings['record_hotkey'])}")
        ml = mouse.Listener(on_move=self.on_record_move, on_click=self.on_record_click, on_scroll=self.on_record_scroll)
        kl = keyboard.Listener(on_press=self.on_record_key_press, on_release=self.on_record_key_release)
        self.listeners = [ml, kl]
        for listener in self.listeners:
            listener.start()

    def stop_recording(self):
        self.recording = False
        self.flush_recorded_move_path()
        for listener in self.listeners:
            listener.stop()
        self.listeners = []
        self.status.set("Recording stopped")

    def stop_all(self):
        self.playing = False
        if self.recording:
            self.stop_recording()
        self.status.set("Stopped")

    def recorded_delay(self):
        now = time.perf_counter()
        delay = now - self.record_start
        self.record_start = now
        return delay

    def add_recorded_event(self, event):
        self.after(0, lambda: self.add_node("recorded", 330, 70 + len(self.nodes) * 78, {"event": event}))

    def on_record_move(self, x, y):
        if self.recording:
            now = time.perf_counter()
            if self.last_recorded_pos:
                px, py = self.last_recorded_pos
                if now - self.last_recorded_move < 0.08 and abs(x - px) + abs(y - py) < 28:
                    return
            self.last_recorded_move = now
            self.last_recorded_pos = (x, y)
            self.recorded_move_path.append({"x": x, "y": y, "delay": self.recorded_delay()})

    def flush_recorded_move_path(self):
        if not self.recorded_move_path:
            return
        path = self.recorded_move_path
        self.recorded_move_path = []
        self.add_recorded_event({"kind": "move_path", "points": path, "delay": 0})

    def on_record_click(self, x, y, button, pressed):
        if self.recording:
            self.flush_recorded_move_path()
            self.add_recorded_event({"kind": "click", "x": x, "y": y, "button": str(button).split(".")[-1], "pressed": pressed, "delay": self.recorded_delay()})

    def on_record_scroll(self, x, y, dx, dy):
        if self.recording:
            self.flush_recorded_move_path()
            self.add_recorded_event({"kind": "scroll", "x": x, "y": y, "amount": dy, "delay": self.recorded_delay()})

    def on_record_key_press(self, key):
        if self.recording:
            self.flush_recorded_move_path()
            self.add_recorded_event({"kind": "key", "key": self.clean_key(key), "pressed": True, "delay": self.recorded_delay()})

    def on_record_key_release(self, key):
        if self.recording:
            self.flush_recorded_move_path()
            self.add_recorded_event({"kind": "key", "key": self.clean_key(key), "pressed": False, "delay": self.recorded_delay()})

    @staticmethod
    def clean_key(key):
        if hasattr(key, "char") and key.char:
            return key.char
        return str(key).replace("Key.", "")

    def play_macro(self):
        if self.recording:
            self.stop_recording()
        if not self.nodes or self.playing:
            return
        countdown = int(self.settings.get("playback_countdown", 3))
        if not messagebox.askokcancel("Play Macro", f"Playback starts in {countdown} seconds. Move focus to the target window."):
            return
        self.playing = True
        self.play_context = self.create_play_context()
        self.status.set(f"Playing in {countdown}...")
        self.after(100, lambda: self._play_after_countdown(countdown))

    def create_play_context(self):
        return {
            "counters": {},
            "paste_index": 0,
            "paste_cache": {},
        }

    def playback_nodes_and_count(self):
        ordered = sorted(self.nodes, key=lambda n: n.y)
        loop_nodes = [node for node in ordered if node.node_type == "loop"]
        count = 1
        if loop_nodes:
            count = max(1, safe_int(loop_nodes[0].data.get("count", 1), 1))
        return [node for node in ordered if node.node_type != "loop"], count

    def _play_after_countdown(self, countdown):
        end_time = time.perf_counter() + countdown
        while self.playing and time.perf_counter() < end_time:
            self.update()
            time.sleep(0.05)
        if not self.playing:
            return
        try:
            nodes, loop_count = self.playback_nodes_and_count()
            for iteration in range(loop_count):
                self.play_context["iteration"] = iteration + 1
                self.play_context["loop_count"] = loop_count
                self.status.set(f"Playing loop {iteration + 1} of {loop_count}")
                for node in nodes:
                    if not self.playing:
                        break
                    self.execute_node(node)
                    self.update()
                if not self.playing:
                    break
            self.status.set("Playback complete" if self.playing else "Playback stopped")
        except Exception as exc:
            self.status.set("Playback failed")
            messagebox.showerror("Playback failed", str(exc))
        finally:
            self.playing = False
            self.play_context = None

    def execute_node(self, node):
        data = node.data
        kind = node.node_type
        if kind == "loop":
            return
        if kind == "counter":
            self.execute_counter(data)
        elif kind == "delay":
            self.wait_interruptible(float(data.get("seconds", 0.5)))
        elif kind == "move":
            WindowsInput.move_mouse(int(data.get("x", 0)), int(data.get("y", 0)))
        elif kind == "click":
            WindowsInput.move_mouse(int(data.get("x", 0)), int(data.get("y", 0)))
            WindowsInput.mouse_button(str(data.get("button", "left")), True)
            time.sleep(0.04)
            WindowsInput.mouse_button(str(data.get("button", "left")), False)
        elif kind == "scroll":
            amount = int(data.get("amount", 3))
            direction = str(data.get("direction", "down"))
            WindowsInput.scroll(amount if direction == "up" else -amount)
        elif kind == "key":
            WindowsInput.key_tap(str(data.get("key", "enter")))
        elif kind == "hotkey":
            WindowsInput.hotkey([k.strip() for k in str(data.get("keys", "")).split("+") if k.strip()])
        elif kind == "type":
            WindowsInput.type_text(self.render_template(str(data.get("text", ""))))
        elif kind == "copy":
            WindowsInput.hotkey(["ctrl", "c"])
        elif kind == "cut":
            WindowsInput.hotkey(["ctrl", "x"])
        elif kind == "paste":
            self.execute_paste(data)
        elif kind == "clipboard":
            self.clipboard_clear()
            self.clipboard_append(self.render_template(str(data.get("text", ""))))
            self.update()
        elif kind == "launch":
            subprocess.Popen(str(data.get("command", "")), shell=True)
        elif kind == "recorded":
            self.execute_recorded(data.get("event", {}))

    def execute_counter(self, data):
        if self.play_context is None:
            return
        name = str(data.get("name", "counter"))
        start = safe_int(data.get("start", 1), 1)
        step = safe_int(data.get("step", 1), 1)
        current = self.play_context["counters"].get(name, start - step)
        self.play_context["counters"][name] = current + step
        self.status.set(f"{name}: {self.play_context['counters'][name]}")

    def execute_paste(self, data):
        source = str(data.get("source", "clipboard"))
        if source == "clipboard":
            WindowsInput.hotkey(["ctrl", "v"])
            return
        values = self.get_paste_values(data)
        if not values:
            return
        context = self.play_context or {"paste_index": 0}
        index = context.get("paste_index", 0) % len(values)
        text = self.render_template(values[index])
        context["paste_index"] = context.get("paste_index", 0) + 1
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        WindowsInput.hotkey(["ctrl", "v"])

    def get_paste_values(self, data):
        source = str(data.get("source", "clipboard"))
        cache_key = json.dumps(data, sort_keys=True)
        if self.play_context and cache_key in self.play_context["paste_cache"]:
            return self.play_context["paste_cache"][cache_key]
        values = []
        if source == "data":
            raw = str(data.get("data", ""))
            values = self.parse_inline_paste_data(raw, safe_int(data.get("column", 1), 1))
        elif source == "file":
            values = self.load_paste_file(str(data.get("file_path", "")), safe_int(data.get("column", 1), 1))
        if self.play_context is not None:
            self.play_context["paste_cache"][cache_key] = values
        return values

    def parse_inline_paste_data(self, raw, column):
        raw = raw.replace("\r\n", "\n").strip()
        if not raw:
            return []
        if "\t" in raw:
            rows = csv.reader(raw.splitlines(), delimiter="\t")
            return [row[column - 1].strip() for row in rows if len(row) >= column and row[column - 1].strip()]
        return [line.strip() for line in raw.split("\n") if line.strip()]

    def render_template(self, text):
        if not self.play_context:
            return text
        values = {
            "iteration": self.play_context.get("iteration", 1),
            "loop_count": self.play_context.get("loop_count", 1),
        }
        values.update(self.play_context.get("counters", {}))
        for key, value in values.items():
            text = text.replace("{" + str(key) + "}", str(value))
        return text

    def load_paste_file(self, file_path, column):
        path = Path(file_path)
        if not path.exists():
            self.status.set("Paste file not found")
            return []
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        values = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for row in reader:
                if len(row) >= column and row[column - 1].strip():
                    values.append(row[column - 1].strip())
        return values

    def wait_interruptible(self, seconds):
        end_time = time.perf_counter() + seconds
        while self.playing and time.perf_counter() < end_time:
            self.update()
            time.sleep(0.02)

    def execute_recorded(self, event):
        self.wait_interruptible(float(event.get("delay", 0)))
        if not self.playing:
            return
        kind = event.get("kind")
        if kind == "move":
            WindowsInput.move_mouse(int(event.get("x", 0)), int(event.get("y", 0)))
        elif kind == "move_path":
            for point in event.get("points", []):
                if not self.playing:
                    break
                self.wait_interruptible(float(point.get("delay", 0)))
                WindowsInput.move_mouse(int(point.get("x", 0)), int(point.get("y", 0)))
        elif kind == "click":
            WindowsInput.move_mouse(int(event.get("x", 0)), int(event.get("y", 0)))
            WindowsInput.mouse_button(str(event.get("button", "left")), bool(event.get("pressed")))
        elif kind == "scroll":
            WindowsInput.move_mouse(int(event.get("x", 0)), int(event.get("y", 0)))
            WindowsInput.scroll(int(event.get("amount", 0)))
        elif kind == "key":
            if event.get("pressed"):
                WindowsInput.key_down(str(event.get("key", "")))
            else:
                WindowsInput.key_up(str(event.get("key", "")))

    def on_close(self):
        self.stop_all()
        for doc in list(self.documents):
            if not self.confirm_save_if_dirty(doc):
                return
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        self.save_settings()
        self.destroy()


def display_hotkey(hotkey):
    return hotkey.replace("<", "").replace(">", "").replace("+", " + ").title()


def clean_tab_title(title):
    return title.removeprefix("*").removesuffix("  x")


def safe_int(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


if __name__ == "__main__":
    app = MacroStudio()
    app.mainloop()
