"""Canvas drawing helpers and reusable themed widgets."""

import tkinter as tk
from tkinter import ttk

from theme import THEME, UI_FONT, ui

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None
    ImageDraw = None
    ImageTk = None


# Anti-aliased sprites are expensive to build (PIL render at 3-5x scale plus
# a LANCZOS downsample), but most are identical from frame to frame: every
# regular node shares one body size per zoom level, every port is the same
# circle, and auto-organized edges repeat the same geometry. Cache the
# finished PhotoImages keyed by geometry and colors.
_SPRITE_CACHE = {}
_SPRITE_CACHE_MAX = 1024


def clear_sprite_cache():
    """Drop all cached sprites. Must be called when a new Tk root is created,
    because PhotoImages die with the interpreter that created them."""
    _SPRITE_CACHE.clear()


def _cached_sprite(key, builder):
    sprite = _SPRITE_CACHE.get(key)
    if sprite is None:
        if len(_SPRITE_CACHE) >= _SPRITE_CACHE_MAX:
            _SPRITE_CACHE.clear()
        sprite = builder()
        _SPRITE_CACHE[key] = sprite
    return sprite


def round_rect_sprite(w, h, radius, fill, outline="", width=1):
    if Image is None:
        return None
    image_w = max(1, int(w))
    image_h = max(1, int(h))
    key = ("rrect", image_w, image_h, int(radius), fill, outline, int(width))

    def build():
        scale = 3
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
        image_small = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image_small)

    return _cached_sprite(key, build)


def port_sprite(radius, fill, outline, width):
    """Returns (photo, image_size) for a port circle."""
    if Image is None:
        return None, 0
    pad = max(width + 2, 4)
    image_size = int((radius + pad) * 2)
    key = ("port", int(radius), pad, fill, outline, int(width))

    def build():
        scale = 4
        image = Image.new("RGBA", (image_size * scale, image_size * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        inset = pad * scale
        bbox = (inset, inset, image.width - inset, image.height - inset)
        draw.ellipse(bbox, fill=hex_to_rgba(fill), outline=hex_to_rgba(outline), width=max(1, width * scale))
        image_small = image.resize((image_size, image_size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image_small)

    return _cached_sprite(key, build), image_size


def _draw_arrow_head(draw, previous, tip, color, width):
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


def edge_sprite(dx, dy, color, width):
    """Returns (photo, offset_x, offset_y) for an edge curve. The curve shape
    only depends on the start-to-end delta, so it is cached on (dx, dy)."""
    if Image is None:
        return None
    dx = int(round(dx))
    dy = int(round(dy))
    key = ("edge", dx, dy, color, int(width))

    def build():
        mid_y = max(28, dy / 2)
        points = cubic_points((0, 0), (0, mid_y), (dx, mid_y), (dx, dy), 32)
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
        _draw_arrow_head(draw, scaled_points[-2], scaled_points[-1], color, width * scale)
        image_small = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image_small), min_x, min_y

    return _cached_sprite(key, build)


def grid_tile_sprite(spacing, color):
    """Returns (photo, tile_size) for a tileable dot-grid background image.
    Tiles target ~360px square so the canvas needs few of them at any zoom."""
    if Image is None:
        return None
    spacing = max(8, int(round(spacing)))
    dots = max(2, int(round(360 / spacing)))
    size = spacing * dots
    key = ("grid", spacing, color)

    def build():
        scale = 3
        image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        radius = max(1, int(1.4 * scale))
        rgba = hex_to_rgba(color)
        for ix in range(dots):
            for iy in range(dots):
                cx = ix * spacing * scale + scale
                cy = iy * spacing * scale + scale
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=rgba)
        image_small = image.resize((size, size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image_small), size

    return _cached_sprite(key, build)


def tab_sprite(w, h, radius, fill, outline, width=1):
    if Image is None:
        return None
    image_w = max(1, int(w))
    image_h = max(1, int(h))
    key = ("tab", image_w, image_h, int(radius), fill, outline, int(width))

    def build():
        scale = 3
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
        image_small = image.resize((image_w, image_h), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image_small)

    return _cached_sprite(key, build)


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
    return _cached_sprite(("icon", name, int(size), color), lambda: _build_icon_sprite(name, size, color))


def _build_icon_sprite(name, size, color):
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
