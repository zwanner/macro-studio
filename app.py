import ctypes
import ctypes.wintypes
import csv
import ast
import json
import subprocess
import sys
import time
import tkinter as tk
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None
    ImageDraw = None
    ImageTk = None

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


APP_TITLE = "Macro Studio"
NODE_W = 202
NODE_H = 72
NODE_DISPLAY_SCALE = 1.0
MACRO_VERSION = 2
CONFIG_PATH = Path.home() / ".macro_studio.json"
UI_FONT = "Segoe UI Variable"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSETS_DIR = APP_DIR / "assets"
APP_ICON_CANDIDATES = [
    ASSETS_DIR / "macro-logo-150.png",
    ASSETS_DIR / "macro-logo-300.png",
    ASSETS_DIR / "macro-logo-75.png",
    ASSETS_DIR / "macro-studio-logo.png",
]
MACRO_FILETYPES = [
    ("Macro files", "*.macro"),
    ("Legacy macro JSON", "*.macro.json"),
    ("JSON", "*.json"),
]
WORKSPACE_MIN_W = 1400
WORKSPACE_MIN_H = 1000

DEFAULT_SETTINGS = {
    "record_hotkey": "<ctrl>+<shift>+r",
    "play_hotkey": "<ctrl>+<shift>+p",
    "stop_hotkey": "<ctrl>+<shift>+x",
    "playback_countdown": 3,
    "recent_files": [],
}


def set_process_dpi_awareness():
    if not hasattr(ctypes, "windll"):
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def windows_ui_scale():
    if not hasattr(ctypes, "windll"):
        return 1.0
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi > 0:
            return max(1.0, dpi / 96)
    except Exception:
        pass
    try:
        dc = ctypes.windll.user32.GetDC(None)
        if not dc:
            return 1.0
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
        finally:
            ctypes.windll.user32.ReleaseDC(None, dc)
        if dpi > 0:
            return max(1.0, dpi / 96)
    except Exception:
        pass
    return 1.0


set_process_dpi_awareness()
UI_SCALE = windows_ui_scale()
NODE_DISPLAY_SCALE = min(max(UI_SCALE, 1.0), 1.35)


def ui(value):
    return int(round(value * UI_SCALE))


def graph_ui(value):
    return value * NODE_DISPLAY_SCALE


THEME = {
    "bg": "#0b1116",
    "panel": "#121b20",
    "panel_2": "#1a262d",
    "panel_3": "#24343d",
    "line": "#344955",
    "tab_outline": "#3e5663",
    "line_hot": "#32ff89",
    "text": "#edf4f7",
    "muted": "#9baeba",
    "success": "#32ff89",
    "warning": "#f0b45b",
    "error": "#ff4f67",
    "info": "#82cfff",
    "accent": "#32ff89",
    "accent_dark": "#22c86d",
    "accent_text": "#06130d",
    "node": "#1b2831",
    "node_selected": "#1f6f4b",
    "node_active": "#238556",
    "node_active_outline": "#32ff89",
    "canvas": "#080d12",
    "button": "#24333d",
    "button_hover": "#2d414d",
    "button_shadow": "#0a0f13",
    "danger": "#d94a5f",
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
    def paste_clipboard(cls):
        cls.key_down("ctrl")
        time.sleep(0.06)
        cls.key_tap("v")
        time.sleep(0.03)
        cls.key_up("ctrl")

    @classmethod
    def type_text(cls, text):
        for char in text:
            cls.key_tap(char.lower())
            time.sleep(0.01)

    @classmethod
    def move_mouse(cls, x, y):
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

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
        key = normalize_hotkey_token(key)
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


def rounded_top_rect(canvas, x1, y1, x2, y2, radius=10, **kwargs):
    radius = min(radius, int((x2 - x1) / 2), int(y2 - y1))
    points = [
        x1, y2,
        x1, y1 + radius,
        x1, y1,
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_lucide_icon(canvas, name, x, y, size, color, tags):
    scale = size / 24

    def point(px, py):
        return x + px * scale, y + py * scale

    def line(*coords, width=2):
        scaled = []
        for idx in range(0, len(coords), 2):
            scaled.extend(point(coords[idx], coords[idx + 1]))
        canvas.create_line(*scaled, fill=color, width=max(1, int(width * scale)), capstyle="round", joinstyle="round", tags=tags)

    def rect(px, py, w, h, radius=2):
        x1, y1 = point(px, py)
        x2, y2 = point(px + w, py + h)
        rounded_rect(canvas, x1, y1, x2, y2, max(1, int(radius * scale)), outline=color, fill="", width=max(1, int(2 * scale)), tags=tags)

    if name == "link":
        line(10, 13, 8.5, 14.5, 7, 16, 5, 16, 3.5, 14.5, 3.5, 12.5, 5, 11, 8, 8, 10, 8)
        line(14, 11, 15.5, 9.5, 17, 8, 19, 8, 20.5, 9.5, 20.5, 11.5, 19, 13, 16, 16, 14, 16)
        line(8, 12, 16, 12)
    elif name == "unlink":
        line(7, 7, 17, 17)
        line(10, 13, 8.5, 14.5, 7, 16, 5, 16, 3.5, 14.5, 3.5, 12.5, 5, 11)
        line(19, 13, 20.5, 11.5, 20.5, 9.5, 19, 8, 17, 8, 15.5, 9.5)
    elif name == "wand":
        line(15, 4, 20, 9)
        line(4, 20, 14, 10)
        line(6, 4, 6, 8)
        line(4, 6, 8, 6)
        line(19, 16, 19, 20)
        line(17, 18, 21, 18)
    elif name == "copy":
        rect(8, 8, 10, 10)
        rect(5, 5, 10, 10)
    elif name == "trash":
        line(3, 6, 21, 6)
        line(8, 6, 8, 4, 16, 4, 16, 6)
        line(6, 6, 7, 21, 17, 21, 18, 6)
        line(10, 11, 10, 17)
        line(14, 11, 14, 17)
    elif name == "arrow-up":
        line(12, 19, 12, 5)
        line(5, 12, 12, 5, 19, 12)
    elif name == "arrow-down":
        line(12, 5, 12, 19)
        line(5, 12, 12, 19, 19, 12)
    elif name == "eraser":
        line(7, 21, 21, 21)
        line(3, 15, 13, 5, 21, 13, 11, 23, 3, 15)
        line(11, 7, 19, 15)
    elif name == "record":
        x1, y1 = point(6, 6)
        x2, y2 = point(18, 18)
        canvas.create_oval(x1, y1, x2, y2, fill=color, outline=color, tags=tags)
    elif name == "play":
        coords = []
        for px, py in ((8, 5), (19, 12), (8, 19)):
            coords.extend(point(px, py))
        canvas.create_polygon(coords, fill=color, outline=color, tags=tags)
    elif name == "stop":
        x1, y1 = point(7, 7)
        x2, y2 = point(17, 17)
        canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline=color, tags=tags)


def build_antialiased_icon(name, size, color):
    if Image is None:
        return None
    scale = 5
    image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    rgba = hex_to_rgba(color)

    def point(px, py):
        factor = size * scale / 24
        return px * factor, py * factor

    def line(*coords, width=2):
        scaled = []
        for idx in range(0, len(coords), 2):
            scaled.extend(point(coords[idx], coords[idx + 1]))
        draw.line(scaled, fill=rgba, width=max(1, int(width * scale)), joint="curve")

    def rect(px, py, w, h, radius=2, fill=None):
        x1, y1 = point(px, py)
        x2, y2 = point(px + w, py + h)
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=max(1, int(radius * scale)),
            outline=rgba,
            fill=rgba if fill else None,
            width=max(1, int(2 * scale)),
        )

    if name == "unlink":
        line(5, 12, 8, 9, 10, 9)
        line(14, 15, 16, 15, 19, 12)
        line(7, 7, 17, 17)
    elif name == "wand":
        line(4, 20, 15, 9)
        line(14, 5, 19, 10)
        line(6, 4, 6, 8)
        line(4, 6, 8, 6)
        line(19, 16, 19, 20)
        line(17, 18, 21, 18)
    elif name == "copy":
        rect(8, 8, 10, 10)
        rect(5, 5, 10, 10)
    elif name == "trash":
        line(3, 6, 21, 6)
        line(8, 6, 8, 4, 16, 4, 16, 6)
        line(6, 6, 7, 21, 17, 21, 18, 6)
        line(10, 11, 10, 17)
        line(14, 11, 14, 17)
    elif name == "arrow-up":
        line(12, 19, 12, 5)
        line(5, 12, 12, 5, 19, 12)
    elif name == "arrow-down":
        line(12, 5, 12, 19)
        line(5, 12, 12, 19, 19, 12)
    elif name == "eraser":
        line(7, 21, 21, 21)
        line(3, 15, 13, 5, 21, 13, 11, 23, 3, 15)
        line(11, 7, 19, 15)
    elif name == "record":
        x1, y1 = point(7, 7)
        x2, y2 = point(17, 17)
        draw.ellipse((x1, y1, x2, y2), fill=rgba)
    elif name == "play":
        points = [point(8, 5), point(19, 12), point(8, 19)]
        draw.polygon(points, fill=rgba)
    elif name == "stop":
        x1, y1 = point(7, 7)
        x2, y2 = point(17, 17)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=max(1, int(1.5 * scale)), fill=rgba)
    else:
        line(10, 13, 8.5, 14.5, 7, 16, 5, 16, 3.5, 14.5, 3.5, 12.5, 5, 11, 8, 8, 10, 8)
        line(14, 11, 15.5, 9.5, 17, 8, 19, 8, 20.5, 9.5, 20.5, 11.5, 19, 13, 16, 16, 14, 16)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image)


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, width=118, height=40, accent=False, danger=False, icon=None):
        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = THEME["panel"]
        super().__init__(
            parent,
            width=ui(width),
            height=ui(height + 4),
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.text = text
        self.command = command
        self.icon = icon
        self.icon_image = None
        self.width_px = ui(width)
        self.height_px = ui(height)
        self.fill = THEME["accent_dark"] if accent else THEME["danger"] if danger else THEME["button"]
        self.hover_fill = THEME["accent"] if accent else "#ff5f74" if danger else THEME["button_hover"]
        self.text_fill = THEME["accent_text"] if accent else THEME["text"]
        self.draw(self.fill)
        self.bind("<Enter>", lambda _event: self.draw(self.hover_fill))
        self.bind("<Leave>", lambda _event: self.draw(self.fill))
        self.bind("<ButtonPress-1>", lambda _event: self.move("button", 0, 1))
        self.bind("<ButtonRelease-1>", self.on_release)

    def draw(self, fill):
        self.delete("all")
        rounded_rect(self, ui(3), ui(5), self.width_px - ui(1), self.height_px + ui(2), ui(7), fill=THEME["button_shadow"], outline="", tags="button")
        rounded_rect(self, ui(1), ui(1), self.width_px - ui(3), self.height_px - ui(1), ui(7), fill=fill, outline="#334751", tags="button")
        text_x = int(self.width_px / 2) - 1
        if self.icon:
            icon_size = ui(18)
            icon_x = max(ui(10), text_x - ui(48))
            icon_y = int((self.height_px - icon_size) / 2)
            self.icon_image = build_antialiased_icon(self.icon, icon_size, self.text_fill)
            if self.icon_image:
                self.create_image(icon_x, icon_y, image=self.icon_image, anchor="nw", tags="button")
            else:
                draw_lucide_icon(self, self.icon, icon_x, icon_y, icon_size, self.text_fill, "button")
            text_x += 10
        self.create_text(
            text_x,
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
        widget.bind("<Destroy>", self.cancel, add="+")

    def schedule(self, _event=None):
        self.cancel()
        self.after_id = self.widget.after(self.delay, self.show)

    def cancel(self, _event=None):
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


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, height=None, width=None, style="Panel.TFrame"):
        super().__init__(parent, style=style)
        self.canvas = tk.Canvas(
            self,
            bg=THEME["panel"],
            highlightthickness=0,
            bd=0,
            height=ui(height) if height else 1,
            width=ui(width) if width else 1,
        )
        self.inner = ttk.Frame(self.canvas, style=style)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.bind("<Configure>", self.on_vertical_canvas_configure)
        self.inner.bind("<Configure>", self.on_inner_configure)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel, add="+")
        self.inner.bind("<MouseWheel>", self.on_mousewheel, add="+")

    def on_vertical_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self.on_inner_configure()

    def on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"


def colorref(hex_color):
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def hex_to_rgba(hex_color, alpha=255):
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


def cubic_points(p0, p1, p2, p3, steps=32):
    points = []
    for index in range(steps + 1):
        t = index / steps
        inv = 1 - t
        x = (
            inv ** 3 * p0[0]
            + 3 * inv ** 2 * t * p1[0]
            + 3 * inv * t ** 2 * p2[0]
            + t ** 3 * p3[0]
        )
        y = (
            inv ** 3 * p0[1]
            + 3 * inv ** 2 * t * p1[1]
            + 3 * inv * t ** 2 * p2[1]
            + t ** 3 * p3[1]
        )
        points.append((x, y))
    return points


def get_active_window_title():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        return ""


def get_mouse_position():
    try:
        point = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)
    except Exception:
        if mouse is not None:
            try:
                x, y = mouse.Controller().position
                return int(x), int(y)
            except Exception:
                pass
    return 0, 0


def recorded_event_label(event):
    kind = event.get("kind")
    if kind == "move_path":
        return f"Mouse Path ({len(event.get('points', []))})"
    if kind == "click":
        return f"{str(event.get('button', 'left')).title()} Click"
    if kind == "key":
        return f"Key: {event.get('key', '')}"
    if kind == "scroll":
        return "Scroll Up" if int(event.get("amount", 0)) > 0 else "Scroll Down"
    return "Recorded Action"


@dataclass
class MacroNode:
    node_type: str
    x: int
    y: int
    data: dict = field(default_factory=dict)
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def title(self):
        if self.node_type == "recorded" and not self.data.get("_label"):
            return recorded_event_label(self.data.get("event", {}))
        return self.data.get("_label") or NODE_TYPES[self.node_type]["title"]


@dataclass
class MacroDocument:
    name: str = "Untitled"
    file_path: Path | None = None
    nodes: list[MacroNode] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    selected: MacroNode | None = None
    dirty: bool = False
    undo_stack: list[dict] = field(default_factory=list)
    redo_stack: list[dict] = field(default_factory=list)

    @property
    def tab_title(self):
        name = self.file_path.stem if self.file_path else self.name
        marker = "*" if self.dirty else ""
        return f"{marker}{name}  x"


NODE_TYPES = {
    "start": {"title": "Start", "defaults": {}, "description": "Workflow entry point. Playback starts here when the script has graph connections."},
    "end": {"title": "End", "defaults": {}, "description": "Workflow stop point. Playback stops this path when it reaches this node."},
    "loop": {"title": "Loop Script", "defaults": {"mode": "count", "count": 3, "stop_hotkey": ""}, "description": "Repeats the entire script a fixed number of times, or runs until a stop hotkey is pressed. The loop node itself is skipped during playback."},
    "loop_frame": {"title": "Loop Frame", "defaults": {"mode": "count", "count": 3, "stop_hotkey": "", "width": 360, "height": 300}, "description": "Loops only the nodes visually placed inside this frame. Frames can be nested for advanced workflows."},
    "global_delay": {"title": "Global Delay", "defaults": {"seconds": 0.1}, "description": "Adds a pause between every playback node in the script. This node acts as a script-level timing setting."},
    "counter": {"title": "Counter", "defaults": {"name": "counter", "start": 1, "step": 1}, "description": "Tracks a named number while playback runs. Use placeholders like {counter} in Type Text, Set Clipboard, or Paste data values."},
    "delay": {"title": "Delay", "defaults": {"seconds": 0.5}, "description": "Pauses playback for a number of seconds. Useful between clicks, launches, and pages that need time to load."},
    "wait_window": {"title": "Wait Window", "defaults": {"title_contains": "", "timeout": 10}, "description": "Waits until the active window title contains specific text, or until the timeout expires."},
    "wait_hotkey": {"title": "Wait Hotkey", "defaults": {"hotkey": "<ctrl>+<shift>+space", "timeout": 0}, "description": "Pauses playback until a specific hotkey is pressed. Set timeout to 0 to wait indefinitely."},
    "wait_click": {"title": "Wait Click", "defaults": {"button": "any", "timeout": 0, "save_position": "yes", "variable": "first_click"}, "description": "Pauses playback until you manually click. The click passes through normally and can save its screen position into variables."},
    "note": {"title": "Note", "defaults": {"text": "Describe this part of the workflow"}, "description": "A documentation node. It is ignored during playback and helps explain larger workflows."},
    "click": {"title": "Mouse Click", "defaults": {"button": "left", "x": 500, "y": 500}, "description": "Moves the mouse to a screen coordinate and clicks a button. Coordinates are absolute screen pixels."},
    "move": {"title": "Mouse Move", "defaults": {"x": 500, "y": 500}, "description": "Moves the mouse pointer to a screen coordinate without clicking."},
    "save_mouse": {"title": "Save Mouse Position", "defaults": {"variable": "mouse"}, "description": "Saves the current mouse coordinates into variables like mouse_x and mouse_y."},
    "scroll": {"title": "Scroll", "defaults": {"direction": "down", "amount": 3}, "description": "Scrolls the mouse wheel up or down by a chosen amount. The mouse stays wherever it currently is."},
    "key": {"title": "Key Tap", "defaults": {"key": "enter"}, "description": "Presses and releases a single key such as enter, tab, esc, delete, or an arrow key."},
    "hotkey": {"title": "Hotkey", "defaults": {"keys": "ctrl+c", "custom_keys": ""}, "description": "Presses a key combination. Choose a common hotkey or set keys to custom and enter your own combo in custom_keys."},
    "type": {"title": "Type Text", "defaults": {"text": "Hello"}, "description": "Types text using keyboard events. Supports placeholders like {iteration}, {loop_index}, {loop_count}, and named counters."},
    "copy": {"title": "Copy", "defaults": {}, "description": "Runs Ctrl+C in the focused app."},
    "cut": {"title": "Cut", "defaults": {}, "description": "Runs Ctrl+X in the focused app."},
    "paste": {"title": "Paste", "defaults": {"source": "clipboard", "data": "", "file_path": "", "column": 1}, "description": "Pastes from the current clipboard, inline rows, or a CSV/TSV file. Data sources advance one item per paste, which pairs well with Loop Script."},
    "clipboard": {"title": "Set Clipboard", "defaults": {"text": "Clipboard text"}, "description": "Sets the clipboard text without immediately pasting. Supports placeholders for loops and counters."},
    "save_clipboard": {"title": "Save Clipboard", "defaults": {"target": "variable", "variable": "clipboard", "dataset": "captured_items", "file_path": "", "include_blank": "no"}, "description": "Saves current clipboard text to a variable, appends it to an in-memory dataset, or appends it to a text file."},
    "launch": {"title": "Launch App", "defaults": {"command": "notepad"}, "description": "Starts an app or command, such as notepad or a full executable path."},
    "recorded": {"title": "Recorded Event", "defaults": {"event": {}}, "description": "A captured mouse, keyboard, scroll, or grouped mouse-path event created by the recorder."},
}

FIELD_DESCRIPTIONS = {
    "_label": "Optional display name for this node. Leaving it as the default keeps the standard node title.",
    "count": "How many times to run the active script. Minimum is 1.",
    "mode": "Loop behavior. Use count for fixed repeats or until hotkey for unknown repetition counts.",
    "stop_hotkey": "Optional hotkey that stops an until-hotkey loop. Leave blank to use the app Stop hotkey from Settings.",
    "width": "Frame width in graph units.",
    "height": "Frame height in graph units.",
    "name": "Counter name. Use the same name in placeholders, for example {counter}.",
    "start": "Initial counter value before the first step is applied.",
    "step": "How much the counter changes each time this node runs.",
    "seconds": "Pause duration in seconds. Decimals are allowed.",
    "title_contains": "Window-title text to wait for. Matching is case-insensitive.",
    "timeout": "Maximum seconds to wait before continuing.",
    "hotkey": "Hotkey to wait for, using pynput syntax such as <ctrl>+<shift>+space.",
    "button": "Mouse button to click.",
    "x": "Absolute screen X coordinate in pixels. Supports placeholders and simple math, such as {first_click_x}+20.",
    "y": "Absolute screen Y coordinate in pixels. Supports placeholders and simple math, such as {first_click_y}-10.",
    "direction": "Scroll wheel direction.",
    "amount": "Scroll strength. Larger numbers scroll farther.",
    "key": "Single key to press and release.",
    "keys": "Hotkey combination separated by plus signs, such as ctrl+c or ctrl+shift+s.",
    "custom_keys": "Custom hotkey combination used when keys is set to custom, such as ctrl+shift+a.",
    "text": "Text value. Supports placeholders like {iteration}, {loop_index}, {loop_count}, and named counters.",
    "variable": "Variable base name. Values are available later as placeholders, such as {first_click_x}, {first_click_y}, or {clipboard}.",
    "target": "Where to save clipboard text: a variable, a playback dataset, or a file.",
    "dataset": "Dataset name used for collected values. Appended items are available as {dataset}, {dataset_count}, and {dataset_last}.",
    "include_blank": "Whether blank clipboard values should be saved.",
    "save_position": "Whether this node should save the clicked screen coordinate into variables.",
    "source": "Paste source: clipboard uses current clipboard, data uses rows in this node, file reads CSV/TSV.",
    "data": "Inline paste rows. You can paste a copied Excel column/table here; the column setting chooses which column to use.",
    "file_path": "Path to a CSV or TSV file. Use with source=file.",
    "column": "1-based column number to read from inline table data or CSV/TSV file.",
    "command": "Program or shell command to launch.",
    "event": "Raw recorded event data. Usually best left alone unless you are editing recorded playback manually.",
}

FIELD_OPTIONS = {
    ("loop", "mode"): ["count", "until hotkey"],
    ("loop_frame", "mode"): ["count", "until hotkey"],
    ("click", "button"): ["left", "right", "middle"],
    ("wait_click", "button"): ["any", "left", "right", "middle"],
    ("wait_click", "save_position"): ["yes", "no"],
    ("hotkey", "keys"): ["ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+s", "alt+tab", "custom"],
    ("key", "key"): ["enter", "tab", "esc", "space", "backspace", "delete", "left", "right", "up", "down"],
    ("scroll", "direction"): ["down", "up"],
    ("paste", "source"): ["clipboard", "data", "file"],
    ("save_clipboard", "target"): ["variable", "dataset", "file"],
    ("save_clipboard", "include_blank"): ["no", "yes"],
}

NODE_CATEGORIES = [
    ("Flow", ["start", "end", "loop", "loop_frame", "counter", "note"]),
    ("Timing", ["global_delay", "delay", "wait_window", "wait_hotkey", "wait_click"]),
    ("Mouse", ["click", "move", "save_mouse", "scroll"]),
    ("Keyboard", ["key", "hotkey", "type"]),
    ("Clipboard", ["copy", "cut", "paste", "clipboard", "save_clipboard"]),
    ("System", ["launch"]),
]


class MacroStudio(tk.Tk):
    def __init__(self):
        super().__init__()
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
        self.canvas_image_refs = []
        self.inspector_vars = {}
        self.suppress_dirty = False
        self.suppress_history = False
        self.pending_connection_source = None
        self.connection_drag = None
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
        scale = 3
        image_w = max(1, int(w))
        image_h = max(1, int(h))
        image = Image.new("RGBA", (image_w * scale, image_h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        fill_rgba = hex_to_rgba(fill)
        outline_rgba = hex_to_rgba(outline)
        r = max(1, int(radius * scale))
        stroke = max(1, int(width * scale))
        bbox = (0, 0, image.width - 1, image.height + r)
        draw.rounded_rectangle(bbox, radius=r, fill=fill_rgba)
        draw.rectangle((0, r, image.width, image.height), fill=fill_rgba)
        draw.line((r, stroke // 2, image.width - r, stroke // 2), fill=outline_rgba, width=stroke)
        draw.arc((0, 0, r * 2, r * 2), 180, 270, fill=outline_rgba, width=stroke)
        draw.arc((image.width - r * 2, 0, image.width, r * 2), 270, 360, fill=outline_rgba, width=stroke)
        draw.line((stroke // 2, r, stroke // 2, image.height), fill=outline_rgba, width=stroke)
        draw.line((image.width - stroke // 2, r, image.width - stroke // 2, image.height), fill=outline_rgba, width=stroke)
        draw.line((0, image.height - stroke // 2, image.width, image.height - stroke // 2), fill=outline_rgba, width=stroke)
        image = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
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
        points = cubic_points((x1, y1), (x1, mid_y), (x2, mid_y), (x2, y2), 32)
        pad = max(14, width * 4)
        min_x = min(point[0] for point in points) - pad
        min_y = min(point[1] for point in points) - pad
        max_x = max(point[0] for point in points) + pad
        max_y = max(point[1] for point in points) + pad
        scale = 3
        image_w = max(1, int(max_x - min_x))
        image_h = max(1, int(max_y - min_y))
        image = Image.new("RGBA", (image_w * scale, image_h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        scaled_points = [((point[0] - min_x) * scale, (point[1] - min_y) * scale) for point in points]
        draw.line(scaled_points, fill=hex_to_rgba(color), width=max(1, width * scale), joint="curve")
        self.draw_antialiased_arrow(draw, scaled_points[-2], scaled_points[-1], color, width * scale)
        image = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.canvas_image_refs.append(photo)
        self.canvas.create_image(min_x, min_y, image=photo, anchor="nw")

    def draw_antialiased_arrow(self, draw, previous, tip, color, width):
        dx = tip[0] - previous[0]
        dy = tip[1] - previous[1]
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        arrow_len = max(10, width * 3.6)
        arrow_w = max(7, width * 2.2)
        base_x = tip[0] - ux * arrow_len
        base_y = tip[1] - uy * arrow_len
        polygon = [
            tip,
            (base_x + px * arrow_w / 2, base_y + py * arrow_w / 2),
            (base_x - px * arrow_w / 2, base_y - py * arrow_w / 2),
        ]
        draw.polygon(polygon, fill=hex_to_rgba(color))

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
        self.node_items[rect] = node
        self.node_items[title] = node
        self.node_items[summary] = node

    def draw_antialiased_round_rect(self, x, y, w, h, radius, fill, outline="", width=1):
        if Image is None or self.fast_canvas_render:
            return rounded_rect(self.canvas, x, y, x + w, y + h, radius, fill=fill, outline=outline, width=width)
        scale = 3
        image_w = max(1, int(w))
        image_h = max(1, int(h))
        image = Image.new("RGBA", (image_w * scale, image_h * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        bbox = (0, 0, image.width - 1, image.height - 1)
        draw.rounded_rectangle(
            bbox,
            radius=max(1, int(radius * scale)),
            fill=hex_to_rgba(fill) if fill else None,
            outline=hex_to_rgba(outline) if outline else None,
            width=max(1, int(width * scale)) if outline else 1,
        )
        image = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
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
            scale = 4
            pad = max(width + 2, 4)
            image_size = int((radius + pad) * 2)
            image = Image.new("RGBA", (image_size * scale, image_size * scale), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            inset = pad * scale
            bbox = (inset, inset, image.width - inset, image.height - inset)
            draw.ellipse(bbox, fill=hex_to_rgba(fill), outline=hex_to_rgba(outline), width=max(1, width * scale))
            image = image.resize((image_size, image_size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
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
        ordered = self.workflow_order() if self.doc.edges else []
        if not ordered or len(ordered) != len(self.nodes) or any(node.node_type == "end" for node in ordered[:-1]):
            starts = [node for node in self.nodes if node.node_type == "start"]
            ends = [node for node in self.nodes if node.node_type == "end"]
            middle = [node for node in self.nodes if node.node_type not in ("start", "end")]
            ordered = starts[:1] + sorted(middle, key=lambda n: (n.y, n.x)) + ends[:1]
        x = 170
        y = 96
        gap = 118
        self.record_history()
        for index, node in enumerate(ordered):
            node.x = x
            node.y = y + index * gap
        self.doc.edges = [{"from": a.node_id, "to": b.node_id} for a, b in zip(ordered, ordered[1:])]
        self.selected = self.selected if self.selected in self.nodes else ordered[0]
        self.mark_dirty()
        self.refresh()
        self.status.set("Auto-organized nodes")

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
        self.recorded_pressed_keys = {}
        self.recorded_pressed_buttons = {}
        self.record_insert_after_id = self.predecessor_before_end().node_id if self.predecessor_before_end() else None
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
        self.stop_playback_stop_listener()
        self.status.set("Stopped")

    def recorded_delay(self):
        now = time.perf_counter()
        delay = now - self.record_start
        self.record_start = now
        return delay

    def add_recorded_event(self, event):
        self.after(0, lambda: self.add_recorded_node_to_flow(event))

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
            name = str(button).split(".")[-1]
            if pressed:
                self.flush_recorded_move_path()
                self.recorded_pressed_buttons[name] = {"x": x, "y": y, "delay": self.recorded_delay()}
            else:
                started = self.recorded_pressed_buttons.pop(name, None)
                delay = self.recorded_delay() if started is None else started.get("delay", 0)
                self.add_recorded_event({"kind": "click", "x": x, "y": y, "button": name, "delay": delay})

    def on_record_scroll(self, x, y, dx, dy):
        if self.recording:
            self.flush_recorded_move_path()
            self.add_recorded_event({"kind": "scroll", "x": x, "y": y, "amount": dy, "delay": self.recorded_delay()})

    def on_record_key_press(self, key):
        if self.recording:
            self.flush_recorded_move_path()
            key_name = self.clean_key(key)
            if key_name not in self.recorded_pressed_keys:
                self.recorded_pressed_keys[key_name] = self.recorded_delay()

    def on_record_key_release(self, key):
        if self.recording:
            key_name = self.clean_key(key)
            delay = self.recorded_pressed_keys.pop(key_name, None)
            if delay is None:
                delay = self.recorded_delay()
            else:
                self.recorded_delay()
            self.add_recorded_event({"kind": "key", "key": key_name, "delay": delay})

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
            "variables": {},
            "datasets": {},
            "paste_index": 0,
            "paste_indices": {},
            "paste_cache": {},
        }

    def playback_nodes_and_count(self):
        ordered = self.workflow_order()
        if not ordered:
            ordered = sorted(self.nodes, key=lambda n: (n.y, n.x))
        loop_nodes = [node for node in ordered if node.node_type == "loop"]
        loop_settings = {"mode": "count", "count": 1, "stop_hotkey": ""}
        if loop_nodes:
            loop_settings = self.loop_settings(loop_nodes[0])
        global_delay_nodes = [node for node in ordered if node.node_type == "global_delay"]
        global_delay = 0
        if global_delay_nodes:
            global_delay = max(0, safe_float(global_delay_nodes[0].data.get("seconds", 0), 0))
        script_level_nodes = {"loop", "global_delay"}
        return [
            node
            for node in ordered
            if node.node_type not in script_level_nodes and self.nearest_loop_frame(node) is None
        ], loop_settings, global_delay

    def loop_settings(self, node):
        mode = str(node.data.get("mode", "count")).lower()
        if mode in ("until hotkey", "until_hotkey", "hotkey"):
            return {
                "mode": "until hotkey",
                "count": None,
                "stop_hotkey": str(node.data.get("stop_hotkey", "")).strip() or self.settings.get("stop_hotkey", ""),
            }
        return {
            "mode": "count",
            "count": max(1, safe_int(node.data.get("count", 1), 1)),
            "stop_hotkey": "",
        }

    def workflow_order(self):
        if not self.doc.edges:
            return sorted(self.nodes, key=lambda n: (n.y, n.x))
        starts = [node for node in self.nodes if node.node_type == "start"]
        start = starts[0] if starts else min(self.nodes, key=lambda n: (n.y, n.x), default=None)
        if not start:
            return []
        order = []
        visited_edges = set()
        active_nodes = set()

        def visit(node):
            if node.node_id in active_nodes:
                return
            active_nodes.add(node.node_id)
            order.append(node)
            if node.node_type == "end":
                active_nodes.remove(node.node_id)
                return
            outgoing = sorted(
                self.outgoing_edges(node),
                key=lambda edge: (
                    (self.node_by_id(edge.get("to")).y if self.node_by_id(edge.get("to")) else 0),
                    (self.node_by_id(edge.get("to")).x if self.node_by_id(edge.get("to")) else 0),
                ),
            )
            for edge in outgoing:
                edge_key = (edge.get("from"), edge.get("to"))
                target = self.node_by_id(edge.get("to"))
                if not target or edge_key in visited_edges:
                    continue
                visited_edges.add(edge_key)
                visit(target)
            active_nodes.remove(node.node_id)

        visit(start)
        return order

    def _play_after_countdown(self, countdown):
        end_time = time.perf_counter() + countdown
        while self.playing and time.perf_counter() < end_time:
            self.update()
            time.sleep(0.05)
        if not self.playing:
            return
        try:
            nodes, loop_settings, global_delay = self.playback_nodes_and_count()
            self.play_context["global_delay"] = global_delay
            loop_count = loop_settings["count"]
            if loop_settings["mode"] == "until hotkey":
                self.start_playback_stop_listener(loop_settings.get("stop_hotkey", ""))
            iteration = 0
            while self.playing and (loop_count is None or iteration < loop_count):
                iteration += 1
                self.play_context["iteration"] = iteration
                self.play_context["loop_index"] = iteration - 1
                self.play_context["loop_count"] = loop_count or "until stopped"
                if loop_count is None:
                    self.status.set(f"Playing loop {iteration}; stop with {display_hotkey(loop_settings.get('stop_hotkey', ''))}")
                else:
                    self.status.set(f"Playing loop {iteration} of {loop_count}")
                self.execute_node_sequence(nodes, global_delay)
                if not self.playing:
                    break
            self.status.set("Playback complete" if self.playing else "Playback stopped")
        except Exception as exc:
            self.status.set("Playback failed")
            messagebox.showerror("Playback failed", str(exc))
        finally:
            self.stop_playback_stop_listener()
            self.active_node_id = None
            self.playing = False
            self.play_context = None
            self.refresh()

    def execute_node_sequence(self, nodes, global_delay=0):
        for index, node in enumerate(nodes):
            if not self.playing:
                break
            if global_delay > 0 and index > 0:
                self.wait_interruptible(global_delay)
            if not self.playing:
                break
            self.active_node_id = node.node_id
            self.refresh()
            self.update()
            self.execute_node(node)
            self.update()

    def execute_loop_frame(self, frame):
        body = self.loop_frame_body_nodes(frame)
        if not body:
            return
        settings = self.loop_settings(frame)
        loop_count = settings["count"]
        if settings["mode"] == "until hotkey":
            self.start_playback_stop_listener(settings.get("stop_hotkey", ""))
        previous_iteration = self.play_context.get("iteration") if self.play_context else None
        previous_loop_index = self.play_context.get("loop_index") if self.play_context else None
        previous_loop_count = self.play_context.get("loop_count") if self.play_context else None
        global_delay = self.play_context.get("global_delay", 0) if self.play_context else 0
        iteration = 0
        try:
            while self.playing and (loop_count is None or iteration < loop_count):
                iteration += 1
                if self.play_context is not None:
                    self.play_context["iteration"] = iteration
                    self.play_context["loop_index"] = iteration - 1
                    self.play_context["loop_count"] = loop_count or "until stopped"
                if loop_count is None:
                    self.status.set(f"{frame.title} loop {iteration}; stop with {display_hotkey(settings.get('stop_hotkey', ''))}")
                else:
                    self.status.set(f"{frame.title} loop {iteration} of {loop_count}")
                self.execute_node_sequence(body, global_delay)
        finally:
            if self.play_context is not None:
                if previous_iteration is None:
                    self.play_context.pop("iteration", None)
                else:
                    self.play_context["iteration"] = previous_iteration
                if previous_loop_index is None:
                    self.play_context.pop("loop_index", None)
                else:
                    self.play_context["loop_index"] = previous_loop_index
                if previous_loop_count is None:
                    self.play_context.pop("loop_count", None)
                else:
                    self.play_context["loop_count"] = previous_loop_count

    def execute_node(self, node):
        data = node.data
        kind = node.node_type
        if kind in ("start", "end", "loop", "global_delay", "note"):
            return
        if kind == "counter":
            self.execute_counter(data)
        elif kind == "delay":
            self.wait_interruptible(safe_float(data.get("seconds", 0.5), 0.5))
        elif kind == "loop_frame":
            self.execute_loop_frame(node)
        elif kind == "wait_window":
            self.wait_for_window_title(str(data.get("title_contains", "")), safe_float(data.get("timeout", 10), 10))
        elif kind == "wait_hotkey":
            self.wait_for_hotkey(str(data.get("hotkey", "")), safe_float(data.get("timeout", 0), 0))
        elif kind == "wait_click":
            self.wait_for_click(data)
        elif kind == "move":
            WindowsInput.move_mouse(self.resolve_int(data.get("x", 0)), self.resolve_int(data.get("y", 0)))
        elif kind == "click":
            WindowsInput.move_mouse(self.resolve_int(data.get("x", 0)), self.resolve_int(data.get("y", 0)))
            WindowsInput.mouse_button(str(data.get("button", "left")), True)
            time.sleep(0.04)
            WindowsInput.mouse_button(str(data.get("button", "left")), False)
        elif kind == "save_mouse":
            self.save_mouse_position(str(data.get("variable", "mouse")))
        elif kind == "scroll":
            amount = int(data.get("amount", 3))
            direction = str(data.get("direction", "down"))
            WindowsInput.scroll(amount if direction == "up" else -amount)
        elif kind == "key":
            WindowsInput.key_tap(str(data.get("key", "enter")))
        elif kind == "hotkey":
            WindowsInput.hotkey(self.hotkey_parts(data))
        elif kind == "type":
            WindowsInput.type_text(self.render_template(str(data.get("text", ""))))
        elif kind == "copy":
            WindowsInput.hotkey(["ctrl", "c"])
        elif kind == "cut":
            WindowsInput.hotkey(["ctrl", "x"])
        elif kind == "paste":
            self.execute_paste(data, node.node_id)
        elif kind == "clipboard":
            self.clipboard_clear()
            self.clipboard_append(self.render_template(str(data.get("text", ""))))
            self.update()
        elif kind == "save_clipboard":
            self.save_clipboard_text(data)
        elif kind == "launch":
            subprocess.Popen(str(data.get("command", "")), shell=True)
        elif kind == "recorded":
            self.execute_recorded(data.get("event", {}))

    def wait_for_window_title(self, text, timeout):
        if not text:
            self.wait_interruptible(timeout)
            return
        needle = text.lower()
        end_time = time.perf_counter() + timeout
        while self.playing and time.perf_counter() < end_time:
            title = get_active_window_title().lower()
            if needle in title:
                return
            self.update()
            time.sleep(0.1)

    def hotkey_parts(self, data):
        keys = str(data.get("keys", ""))
        if keys == "custom":
            keys = str(data.get("custom_keys", ""))
        return [key.strip() for key in keys.split("+") if key.strip()]

    def wait_for_hotkey(self, hotkey, timeout):
        if keyboard is None:
            self.status.set("Wait Hotkey unavailable: install pynput")
            return
        target = hotkey_token_set(hotkey)
        if not target:
            return
        matched = {"value": False}
        pressed = set()

        def on_press(key):
            token = normalize_hotkey_token(self.clean_key(key))
            if not token:
                return None
            pressed.add(token)
            if target.issubset(pressed):
                matched["value"] = True
                return False
            return None

        def on_release(key):
            token = normalize_hotkey_token(self.clean_key(key))
            if token:
                pressed.discard(token)
            return None

        try:
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.start()
        except Exception as exc:
            self.status.set(f"Wait Hotkey failed: {exc}")
            return
        end_time = None if timeout <= 0 else time.perf_counter() + timeout
        self.status.set(f"Waiting for {display_hotkey(hotkey)}")
        try:
            while self.playing and not matched["value"]:
                if end_time is not None and time.perf_counter() >= end_time:
                    break
                self.update()
                time.sleep(0.05)
        finally:
            listener.stop()

    def start_playback_stop_listener(self, hotkey):
        self.stop_playback_stop_listener()
        if keyboard is None:
            self.status.set("Loop stop hotkey unavailable: install pynput")
            return
        hotkey = str(hotkey or "").strip()
        if not hotkey:
            return
        try:
            self.playback_stop_listener = keyboard.GlobalHotKeys({hotkey: lambda: self.after(0, self.stop_all)})
            self.playback_stop_listener.start()
        except Exception as exc:
            self.playback_stop_listener = None
            self.status.set(f"Loop stop hotkey failed: {exc}")

    def stop_playback_stop_listener(self):
        if self.playback_stop_listener:
            try:
                self.playback_stop_listener.stop()
            except Exception:
                pass
            self.playback_stop_listener = None

    def wait_for_click(self, data):
        if mouse is None:
            self.status.set("Wait Click unavailable: install pynput")
            return
        target_button = str(data.get("button", "any")).lower()
        timeout = safe_float(data.get("timeout", 0), 0)
        save_position = str(data.get("save_position", "yes")).lower() == "yes"
        variable = str(data.get("variable", "first_click")).strip() or "first_click"
        captured = {}

        def on_click(x, y, button, pressed):
            if not pressed:
                return None
            button_name = str(button).split(".")[-1].lower()
            if target_button != "any" and button_name != target_button:
                return None
            captured.update({"x": int(x), "y": int(y), "button": button_name})
            return False

        try:
            listener = mouse.Listener(on_click=on_click)
            listener.start()
        except Exception as exc:
            self.status.set(f"Wait Click failed: {exc}")
            return
        end_time = None if timeout <= 0 else time.perf_counter() + timeout
        self.status.set("Waiting for click")
        try:
            while self.playing and not captured:
                if end_time is not None and time.perf_counter() >= end_time:
                    break
                self.update()
                time.sleep(0.03)
        finally:
            listener.stop()
        if captured and save_position:
            self.set_play_variable(f"{variable}_x", captured["x"])
            self.set_play_variable(f"{variable}_y", captured["y"])
            self.set_play_variable(f"{variable}_button", captured["button"])
            self.status.set(f"Saved click to {variable}_x/y")

    def save_mouse_position(self, variable):
        x, y = get_mouse_position()
        name = variable.strip() or "mouse"
        self.set_play_variable(f"{name}_x", x)
        self.set_play_variable(f"{name}_y", y)
        self.status.set(f"Saved mouse position to {name}_x/y")

    def save_clipboard_text(self, data):
        if not isinstance(data, dict):
            data = {"target": "variable", "variable": str(data)}
        target = str(data.get("target", "variable")).lower()
        variable = str(data.get("variable", "clipboard")).strip() or "clipboard"
        dataset = str(data.get("dataset", "captured_items")).strip() or "captured_items"
        include_blank = str(data.get("include_blank", "no")).lower() == "yes"
        try:
            value = self.clipboard_get()
        except tk.TclError:
            value = ""
        if value == "" and not include_blank:
            self.status.set("Skipped blank clipboard")
            return
        if target == "dataset":
            self.append_dataset_value(dataset, value)
            self.status.set(f"Appended clipboard to {dataset}")
        elif target == "file":
            path_text = self.render_template(str(data.get("file_path", ""))).strip()
            if not path_text:
                self.status.set("Save Clipboard file path is empty")
                return
            self.append_clipboard_file(path_text, value)
            self.status.set(f"Appended clipboard to {Path(path_text).name}")
        else:
            self.set_play_variable(variable, value)
            self.status.set(f"Saved clipboard to {variable}")

    def append_dataset_value(self, name, value):
        if self.play_context is None:
            self.play_context = self.create_play_context()
        dataset = self.play_context.setdefault("datasets", {}).setdefault(str(name), [])
        dataset.append(value)
        self.set_play_variable(name, "\n".join(str(item) for item in dataset))
        self.set_play_variable(f"{name}_count", len(dataset))
        self.set_play_variable(f"{name}_last", value)

    def append_clipboard_file(self, file_path, value):
        path = Path(file_path).expanduser()
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(str(value).replace("\r\n", "\n").replace("\r", "\n"))
            handle.write("\n")

    def set_play_variable(self, name, value):
        if self.play_context is None:
            self.play_context = self.create_play_context()
        self.play_context.setdefault("variables", {})[str(name)] = value

    def execute_counter(self, data):
        if self.play_context is None:
            return
        name = str(data.get("name", "counter"))
        start = safe_int(data.get("start", 1), 1)
        step = safe_int(data.get("step", 1), 1)
        current = self.play_context["counters"].get(name, start - step)
        self.play_context["counters"][name] = current + step
        self.status.set(f"{name}: {self.play_context['counters'][name]}")

    def execute_paste(self, data, node_id=None):
        source = str(data.get("source", "clipboard"))
        if source == "clipboard":
            WindowsInput.paste_clipboard()
            return
        values = self.get_paste_values(data)
        if not values:
            return
        context = self.play_context or {"paste_index": 0, "paste_indices": {}}
        cursor_key = str(node_id or json.dumps(data, sort_keys=True))
        paste_indices = context.setdefault("paste_indices", {})
        index = paste_indices.get(cursor_key, 0) % len(values)
        text = self.render_template(values[index])
        paste_indices[cursor_key] = paste_indices.get(cursor_key, 0) + 1
        context["paste_index"] = max(context.get("paste_index", 0), paste_indices[cursor_key])
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        time.sleep(0.05)
        WindowsInput.paste_clipboard()

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
            "loop_index": self.play_context.get("loop_index", max(0, safe_int(self.play_context.get("iteration", 1), 1) - 1)),
            "loop_count": self.play_context.get("loop_count", 1),
        }
        values.update(self.play_context.get("counters", {}))
        values.update(self.play_context.get("variables", {}))
        for name, items in self.play_context.get("datasets", {}).items():
            values[name] = "\n".join(str(item) for item in items)
            values[f"{name}_count"] = len(items)
            values[f"{name}_last"] = items[-1] if items else ""
        for key, value in values.items():
            text = text.replace("{" + str(key) + "}", str(value))
        return text

    def resolve_int(self, value, fallback=0):
        rendered = self.render_template(str(value)).strip()
        calculated = self.evaluate_numeric_expression(rendered)
        if calculated is not None:
            return int(round(calculated))
        return safe_int(rendered, fallback)

    def evaluate_numeric_expression(self, text):
        try:
            parsed = ast.parse(text, mode="eval")
            return self.evaluate_numeric_ast(parsed.body)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
            return None

    def evaluate_numeric_ast(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self.evaluate_numeric_ast(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            left = self.evaluate_numeric_ast(node.left)
            right = self.evaluate_numeric_ast(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            return left % right
        raise ValueError("Unsupported numeric expression")

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
            if "pressed" in event:
                WindowsInput.mouse_button(str(event.get("button", "left")), bool(event.get("pressed")))
            else:
                button = str(event.get("button", "left"))
                WindowsInput.mouse_button(button, True)
                time.sleep(0.04)
                WindowsInput.mouse_button(button, False)
        elif kind == "scroll":
            WindowsInput.move_mouse(int(event.get("x", 0)), int(event.get("y", 0)))
            WindowsInput.scroll(int(event.get("amount", 0)))
        elif kind == "key":
            if "pressed" not in event:
                WindowsInput.key_tap(str(event.get("key", "")))
            elif event.get("pressed"):
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


HOTKEY_ALIASES = {
    "control": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt_l": "alt",
    "alt_r": "alt",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
    "win_l": "win",
    "win_r": "win",
    "return": "enter",
    "escape": "esc",
}


def normalize_hotkey_token(token):
    token = str(token).strip().lower()
    if not token:
        return ""
    token = token.removeprefix("key.")
    token = token.strip("<>")
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        token = token[1:-1]
    return HOTKEY_ALIASES.get(token, token)


def hotkey_token_set(hotkey):
    return {
        token
        for token in (normalize_hotkey_token(part) for part in str(hotkey).split("+"))
        if token
    }


def clean_tab_title(title):
    return title.removeprefix("*").removesuffix("  x")


def safe_int(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


if __name__ == "__main__":
    app = MacroStudio()
    app.mainloop()
