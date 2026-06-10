"""UI theme, fonts, and DPI-aware scaling. Importing this module sets process
DPI awareness, so it must be imported before the Tk root window is created."""

from winput import set_process_dpi_awareness, windows_ui_scale


NODE_W = 202
NODE_H = 72
UI_FONT = "Segoe UI Variable"
WORKSPACE_MIN_W = 1400
WORKSPACE_MIN_H = 1000

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
