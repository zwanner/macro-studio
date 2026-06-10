"""Playback engine for macro workflows, mixed into the main app window.

Playback runs on a background daemon thread so the Tk main loop stays
responsive. Worker code must never touch Tk directly: UI updates (status
text, active-node highlight, dialogs, refresh) are marshaled to the main
thread with after(), and the clipboard is accessed through the Win32 API
helpers in winput rather than Tk's clipboard methods.
"""

import ast
import csv
import json
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from hotkeys import canonical_hotkey, display_hotkey, hotkey_token_set, normalize_hotkey_token
from model import safe_float, safe_int
from winput import (
    WindowsInput,
    get_active_window_title,
    get_clipboard_text,
    get_mouse_position,
    set_clipboard_text,
)

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


class PlaybackMixin:
    """Executes the node workflow. Expects the host class to provide the
    document properties (nodes, doc, selected), graph helpers, settings,
    status variable, and Tk plumbing (after, refresh, highlight_active_node)."""

    def _ui_call(self, callback):
        """Queue a callback for the Tk main thread. Worker code must never
        touch Tk directly; the queue is drained by a main-thread timer."""
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except tk.TclError:
                pass
            return
        self._ui_queue.put(callback)

    def _ensure_ui_drain(self):
        if not self._ui_drain_scheduled:
            self._ui_drain_scheduled = True
            self.after(33, self._drain_ui_queue)

    def _drain_ui_queue(self):
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except tk.TclError:
                pass
        thread = self.playback_thread
        if (thread and thread.is_alive()) or not self._ui_queue.empty():
            self.after(33, self._drain_ui_queue)
        else:
            self._ui_drain_scheduled = False

    def notify_status(self, text):
        self._ui_call(lambda: self.status.set(text))

    def notify_active_node(self, node_id):
        self._ui_call(lambda: self.highlight_active_node(node_id))

    def play_macro(self, from_hotkey=False):
        if self.recording:
            self.stop_recording()
        if not self.nodes or self.playing:
            return
        countdown = max(0, safe_int(self.settings.get("playback_countdown", 3), 3))
        if not from_hotkey and not messagebox.askokcancel("Play Macro", f"Playback starts in {countdown} seconds. Move focus to the target window."):
            return
        self.playing = True
        self.play_context = self.create_play_context()
        # Pin the active document so the worker never resolves it through Tk
        # and a mid-playback tab switch cannot change what is playing.
        self._play_doc = self.doc
        self.status.set(f"Playing in {countdown}...")
        self.playback_thread = threading.Thread(
            target=self._run_playback,
            args=(countdown,),
            name="macro-playback",
            daemon=True,
        )
        self._ensure_ui_drain()
        self.playback_thread.start()

    def _run_playback(self, countdown):
        try:
            self._play_after_countdown(countdown)
        finally:
            self._play_doc = None

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
        self.wait_interruptible(countdown)
        if not self.playing:
            return
        try:
            nodes, loop_settings, global_delay = self.playback_nodes_and_count()
            self.play_context["global_delay"] = global_delay
            loop_count = loop_settings["count"]
            stop_hotkey = loop_settings.get("stop_hotkey", "") if loop_settings["mode"] == "until hotkey" else self.settings.get("stop_hotkey", "")
            self.start_playback_stop_listener(stop_hotkey)
            iteration = 0
            while self.playing and (loop_count is None or iteration < loop_count):
                iteration += 1
                self.play_context["iteration"] = iteration
                self.play_context["loop_index"] = iteration - 1
                self.play_context["loop_count"] = loop_count or "until stopped"
                if loop_count is None:
                    self.notify_status(f"Playing loop {iteration}; stop with {display_hotkey(loop_settings.get('stop_hotkey', ''))}")
                else:
                    self.notify_status(f"Playing loop {iteration} of {loop_count}")
                self.execute_node_sequence(nodes, global_delay)
                if not self.playing:
                    break
            self.notify_status("Playback complete" if self.playing else "Playback stopped")
        except Exception as exc:
            self.notify_status("Playback failed")
            message = str(exc)
            self._ui_call(lambda: messagebox.showerror("Playback failed", message))
        finally:
            self.stop_playback_stop_listener()
            self.active_node_id = None
            self.playing = False
            self.play_context = None
            self._ui_call(self.refresh)

    def execute_node_sequence(self, nodes, global_delay=0):
        for index, node in enumerate(nodes):
            if not self.playing:
                break
            if global_delay > 0 and index > 0:
                self.wait_interruptible(global_delay)
            if not self.playing:
                break
            self.active_node_id = node.node_id
            self.notify_active_node(node.node_id)
            self.execute_node(node)

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
                    self.notify_status(f"{frame.title} loop {iteration}; stop with {display_hotkey(settings.get('stop_hotkey', ''))}")
                else:
                    self.notify_status(f"{frame.title} loop {iteration} of {loop_count}")
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
            WindowsInput.type_text(self.render_template(str(data.get("text", ""))), lambda: self.playing)
        elif kind == "copy":
            WindowsInput.hotkey(["ctrl", "c"])
        elif kind == "cut":
            WindowsInput.hotkey(["ctrl", "x"])
        elif kind == "paste":
            self.execute_paste(data, node.node_id)
        elif kind == "clipboard":
            set_clipboard_text(self.render_template(str(data.get("text", ""))))
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
            time.sleep(0.1)

    def hotkey_parts(self, data):
        keys = str(data.get("keys", ""))
        if keys == "custom":
            keys = str(data.get("custom_keys", ""))
        return [key.strip() for key in keys.split("+") if key.strip()]

    def wait_for_hotkey(self, hotkey, timeout):
        if keyboard is None:
            self.notify_status("Wait Hotkey unavailable: install pynput")
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
            self.notify_status(f"Wait Hotkey failed: {exc}")
            return
        end_time = None if timeout <= 0 else time.perf_counter() + timeout
        self.notify_status(f"Waiting for {display_hotkey(hotkey)}")
        try:
            while self.playing and not matched["value"]:
                if end_time is not None and time.perf_counter() >= end_time:
                    break
                time.sleep(0.05)
        finally:
            listener.stop()

    def start_playback_stop_listener(self, hotkey):
        self.stop_playback_stop_listener()
        if keyboard is None:
            self.notify_status("Loop stop hotkey unavailable: install pynput")
            return
        hotkey = canonical_hotkey(hotkey)
        if not hotkey:
            return
        try:
            self.playback_stop_listener = keyboard.GlobalHotKeys({hotkey: self.request_stop_all})
            self.playback_stop_listener.start()
        except Exception as exc:
            self.playback_stop_listener = None
            self.notify_status(f"Loop stop hotkey failed: {exc}")

    def stop_playback_stop_listener(self):
        if self.playback_stop_listener:
            try:
                self.playback_stop_listener.stop()
            except Exception:
                pass
            self.playback_stop_listener = None

    def wait_for_click(self, data):
        if mouse is None:
            self.notify_status("Wait Click unavailable: install pynput")
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
            self.notify_status(f"Wait Click failed: {exc}")
            return
        end_time = None if timeout <= 0 else time.perf_counter() + timeout
        self.notify_status("Waiting for click")
        try:
            while self.playing and not captured:
                if end_time is not None and time.perf_counter() >= end_time:
                    break
                time.sleep(0.03)
        finally:
            listener.stop()
        if captured and save_position:
            self.set_play_variable(f"{variable}_x", captured["x"])
            self.set_play_variable(f"{variable}_y", captured["y"])
            self.set_play_variable(f"{variable}_button", captured["button"])
            self.notify_status(f"Saved click to {variable}_x/y")

    def save_mouse_position(self, variable):
        x, y = get_mouse_position()
        name = variable.strip() or "mouse"
        self.set_play_variable(f"{name}_x", x)
        self.set_play_variable(f"{name}_y", y)
        self.notify_status(f"Saved mouse position to {name}_x/y")

    def save_clipboard_text(self, data):
        if not isinstance(data, dict):
            data = {"target": "variable", "variable": str(data)}
        target = str(data.get("target", "variable")).lower()
        variable = str(data.get("variable", "clipboard")).strip() or "clipboard"
        dataset = str(data.get("dataset", "captured_items")).strip() or "captured_items"
        include_blank = str(data.get("include_blank", "no")).lower() == "yes"
        value = get_clipboard_text()
        if value == "" and not include_blank:
            self.notify_status("Skipped blank clipboard")
            return
        if target == "dataset":
            self.append_dataset_value(dataset, value)
            self.notify_status(f"Appended clipboard to {dataset}")
        elif target == "file":
            path_text = self.render_template(str(data.get("file_path", ""))).strip()
            if not path_text:
                self.notify_status("Save Clipboard file path is empty")
                return
            self.append_clipboard_file(path_text, value)
            self.notify_status(f"Appended clipboard to {Path(path_text).name}")
        else:
            self.set_play_variable(variable, value)
            self.notify_status(f"Saved clipboard to {variable}")

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
        self.notify_status(f"{name}: {self.play_context['counters'][name]}")

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
        set_clipboard_text(text)
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
            self.notify_status("Paste file not found")
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
