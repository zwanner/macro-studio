"""Mouse and keyboard recording, mixed into the main app window."""

import time
from tkinter import messagebox

from hotkeys import display_hotkey
from model import MacroNode

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


TYPED_KEY_MAP = {"space": " "}


def typed_character(key_name):
    """The literal character a recorded key event types, or None if it is not
    plain printable typing (modifiers, navigation, control chords, ...)."""
    key_name = str(key_name)
    if len(key_name) == 1 and key_name.isprintable():
        return key_name
    return TYPED_KEY_MAP.get(key_name)


class RecorderMixin:
    """Captures global mouse/keyboard events into recorded nodes. Expects the
    host class to provide settings, status, graph helpers, and Tk's after()."""

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
        # Recorded events arrive through after(0, ...), so queue coalescing
        # behind any node additions that are still pending.
        self.after(0, self.coalesce_recorded_keys)
        self.set_status("Recording stopped", "info")

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
                if started is None:
                    # The press happened before recording started; ignore the
                    # orphaned release.
                    return
                self.add_recorded_event({"kind": "click", "x": x, "y": y, "button": name, "delay": started.get("delay", 0)})

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
                # The press was never seen while recording. This is how the
                # record hotkey's own keys (e.g. ctrl/shift/r) used to leak
                # into the start of every recording; ignore the release.
                return
            self.recorded_delay()
            self.add_recorded_event({"kind": "key", "key": key_name, "delay": delay})

    @staticmethod
    def clean_key(key):
        if hasattr(key, "char") and key.char:
            return key.char
        return str(key).replace("Key.", "")

    def coalesce_recorded_keys(self, minimum_run=3):
        """Merge runs of consecutively-linked recorded printable keystrokes
        into one Type Text node, so typed words become a single editable node
        instead of one node per key."""
        runs = []
        current = []
        for node in self.workflow_order():
            char = self._recorded_typed_char(node)
            connected = bool(current) and self._has_edge(current[-1], node)
            if char is not None and (not current or connected):
                current.append(node)
                continue
            if len(current) >= minimum_run:
                runs.append(current)
            current = [node] if char is not None else []
        if len(current) >= minimum_run:
            runs.append(current)
        if not runs:
            return
        self.record_history()
        merged_keys = 0
        for run in runs:
            text = "".join(self._recorded_typed_char(node) for node in run)
            first, last = run[0], run[-1]
            type_node = MacroNode("type", first.x, first.y, {"text": text})
            run_ids = {node.node_id for node in run}
            for edge in self.doc.edges:
                if edge.get("to") == first.node_id:
                    edge["to"] = type_node.node_id
                if edge.get("from") == last.node_id:
                    edge["from"] = type_node.node_id
            self.doc.edges = [
                edge
                for edge in self.doc.edges
                if edge.get("from") not in run_ids and edge.get("to") not in run_ids
            ]
            insert_at = self.nodes.index(first)
            self.nodes.insert(insert_at, type_node)
            self.doc.nodes = [node for node in self.nodes if node.node_id not in run_ids]
            if self.selected in run:
                self.selected = type_node
            if self.record_insert_after_id in run_ids:
                self.record_insert_after_id = type_node.node_id
            merged_keys += len(run)
        self.mark_dirty()
        self.refresh()
        self.set_status(f"Merged {merged_keys} keystrokes into Type Text", "success")

    def _recorded_typed_char(self, node):
        if node.node_type != "recorded":
            return None
        event = node.data.get("event", {})
        if event.get("kind") != "key":
            return None
        return typed_character(event.get("key", ""))

    def _has_edge(self, source, target):
        return any(
            edge.get("from") == source.node_id and edge.get("to") == target.node_id
            for edge in self.doc.edges
        )
