"""Low-level Windows input, display, and clipboard helpers (ctypes-based)."""

import ctypes
import ctypes.wintypes
import time

from hotkeys import normalize_hotkey_token


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
    KEYEVENTF_UNICODE = 0x0004
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
    def unicode_key_tap(cls, code_unit):
        cls._send(Input(cls.INPUT_KEYBOARD, InputUnion(ki=KeyBdInput(0, code_unit, cls.KEYEVENTF_UNICODE, 0, None))))
        cls._send(Input(cls.INPUT_KEYBOARD, InputUnion(ki=KeyBdInput(0, code_unit, cls.KEYEVENTF_UNICODE | cls.KEYEVENTF_KEYUP, 0, None))))

    @staticmethod
    def utf16_code_units(text):
        raw = str(text).encode("utf-16-le")
        return [int.from_bytes(raw[index:index + 2], "little") for index in range(0, len(raw), 2)]

    @classmethod
    def type_text(cls, text, should_continue=None):
        should_continue = should_continue or (lambda: True)
        for code_unit in cls.utf16_code_units(text):
            if not should_continue():
                break
            cls.unicode_key_tap(code_unit)
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


def colorref(hex_color):
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


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
        return 0, 0


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
_clipboard_api_ready = False


def _clipboard_api():
    """Returns (user32, kernel32) with clipboard function signatures declared.
    Without explicit restypes, 64-bit handles get truncated to 32 bits."""
    global _clipboard_api_ready
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not _clipboard_api_ready:
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        _clipboard_api_ready = True
    return user32, kernel32


def _open_clipboard(user32, retries=10, delay=0.01):
    for _attempt in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def get_clipboard_text():
    """Read clipboard text via the Win32 API. Safe to call from any thread."""
    if not hasattr(ctypes, "windll"):
        return ""
    user32, kernel32 = _clipboard_api()
    if not _open_clipboard(user32):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    except Exception:
        return ""
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    """Write clipboard text via the Win32 API. Safe to call from any thread."""
    if not hasattr(ctypes, "windll"):
        return False
    user32, kernel32 = _clipboard_api()
    data = str(text).encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard(user32):
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    except Exception:
        return False
    finally:
        user32.CloseClipboard()
