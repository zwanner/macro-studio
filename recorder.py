"""Mouse and keyboard recording, mixed into the main app window."""

import time
from tkinter import messagebox

from hotkeys import display_hotkey

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None


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
        self.status.set("Recording stopped")

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
