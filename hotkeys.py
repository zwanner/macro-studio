"""Hotkey parsing, normalization, and display helpers."""


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


def display_hotkey(hotkey):
    return hotkey.replace("<", "").replace(">", "").replace("+", " + ").title()


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


def canonical_hotkey(hotkey):
    parts = [normalize_hotkey_token(part) for part in str(hotkey or "").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    modifier_order = {"ctrl": 0, "shift": 1, "alt": 2, "cmd": 3, "win": 4}
    modifiers = sorted((part for part in parts if part in modifier_order), key=lambda part: modifier_order[part])
    keys = [part for part in parts if part not in modifier_order]
    canonical_parts = modifiers + keys
    wrapped = [f"<{part}>" if part in modifier_order else part for part in canonical_parts]
    return "+".join(wrapped)
