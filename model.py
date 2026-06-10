"""Macro document model: nodes, documents, node type specs, and value helpers."""

import uuid
from dataclasses import dataclass, field
from pathlib import Path


MACRO_VERSION = 2


def recorded_event_label(event):
    kind = event.get("kind")
    if kind == "move_path":
        return f"Mouse Path ({len(event.get('points', []))})"
    if kind == "click":
        return f"{str(event.get('button', 'left')).title()} Click"
    if kind == "drag":
        return f"{str(event.get('button', 'left')).title()} Drag"
    if kind == "key":
        return f"Key: {event.get('key', '')}"
    if kind == "hotkey":
        return f"Hotkey: {event.get('keys', '')}"
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
    selected_ids: set = field(default_factory=set)
    dirty: bool = False
    undo_stack: list[dict] = field(default_factory=list)
    redo_stack: list[dict] = field(default_factory=list)

    @property
    def tab_title(self):
        name = self.file_path.stem if self.file_path else self.name
        marker = "*" if self.dirty else ""
        return f"{marker}{name}"


NODE_TYPES = {
    "start": {"title": "Start", "defaults": {}, "description": "Workflow entry point. Playback starts here when the script has graph connections."},
    "end": {"title": "End", "defaults": {}, "description": "Workflow stop point. Playback stops this path when it reaches this node."},
    "loop": {"title": "Loop Script", "defaults": {"mode": "count", "count": 3, "stop_hotkey": ""}, "description": "Repeats the entire script a fixed number of times, or runs until a stop hotkey is pressed. The loop node itself is skipped during playback."},
    "loop_frame": {"title": "Loop Frame", "defaults": {"mode": "count", "count": 3, "stop_hotkey": "", "width": 360, "height": 300}, "description": "Loops only the nodes visually placed inside this frame. Frames can be nested for advanced workflows."},
    "if_window": {"title": "If Window", "defaults": {"title_contains": "", "wait": 0}, "description": "Checks whether the active window title contains text, then branches: the green check output runs when it matches, the red cross output when it does not. Wait keeps re-checking for up to that many seconds before deciding."},
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
    "wait": "Seconds to keep re-checking before taking the else branch. 0 checks once.",
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

FIELD_LABELS = {
    "_label": "Name",
    "count": "Repeat count",
    "mode": "Mode",
    "stop_hotkey": "Stop hotkey",
    "width": "Width",
    "height": "Height",
    "name": "Counter name",
    "start": "Start value",
    "step": "Step",
    "seconds": "Seconds",
    "title_contains": "Title contains",
    "timeout": "Timeout (s)",
    "wait": "Wait (s)",
    "hotkey": "Hotkey",
    "button": "Button",
    "x": "X",
    "y": "Y",
    "direction": "Direction",
    "amount": "Amount",
    "key": "Key",
    "keys": "Keys",
    "custom_keys": "Custom keys",
    "text": "Text",
    "variable": "Variable",
    "target": "Save to",
    "dataset": "Dataset",
    "include_blank": "Include blank",
    "save_position": "Save position",
    "source": "Source",
    "data": "Data rows",
    "file_path": "File path",
    "column": "Column",
    "command": "Command",
    "event": "Event data",
}


def field_label(key):
    return FIELD_LABELS.get(key, str(key).replace("_", " ").strip().capitalize())


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
    ("Flow", ["start", "end", "loop", "loop_frame", "if_window", "counter", "note"]),
    ("Timing", ["global_delay", "delay", "wait_window", "wait_hotkey", "wait_click"]),
    ("Mouse", ["click", "move", "save_mouse", "scroll"]),
    ("Keyboard", ["key", "hotkey", "type"]),
    ("Clipboard", ["copy", "cut", "paste", "clipboard", "save_clipboard"]),
    ("System", ["launch"]),
]


def clean_tab_title(title):
    return title.removeprefix("*")


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
