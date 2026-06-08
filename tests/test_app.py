import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


class MacroStudioTestCase(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(app.MacroStudio, "install_global_hotkeys", lambda self: None),
            patch.object(app.MacroStudio, "apply_window_chrome", lambda self: None),
            patch.object(app.MacroStudio, "_style_ui", lambda self: None),
        ]
        for item in self.patches:
            item.start()
        self.studio = app.MacroStudio()
        self.studio.update()

    def tearDown(self):
        try:
            self.studio.update()
            self.studio.update_idletasks()
            self.studio.destroy()
        except Exception:
            pass
        for item in reversed(self.patches):
            item.stop()

    def node(self, node_type):
        return next(node for node in self.studio.nodes if node.node_type == node_type)


class GraphTests(MacroStudioTestCase):
    def test_new_macro_starts_with_start_and_end(self):
        self.assertEqual([node.node_type for node in self.studio.nodes], ["start", "end"])
        start = self.node("start")
        end = self.node("end")
        self.assertEqual(self.studio.doc.edges, [{"from": start.node_id, "to": end.node_id}])

    def test_add_node_auto_connects_from_selected_node(self):
        start = self.node("start")
        self.studio.selected = start
        self.studio.add_node("delay")
        delay = self.studio.selected
        self.assertTrue(
            any(edge["from"] == start.node_id and edge["to"] == delay.node_id for edge in self.studio.doc.edges)
        )

    def test_invalid_start_end_edges_are_rejected(self):
        start = self.node("start")
        end = self.node("end")
        self.studio.add_node("delay")
        delay = self.studio.selected
        self.assertFalse(self.studio.add_edge(end, delay))
        self.assertFalse(self.studio.add_edge(delay, start))

    def test_auto_link_orders_start_middle_end(self):
        self.studio.add_node("delay", x=300, y=300)
        self.studio.add_node("click", x=120, y=200)
        self.studio.auto_link_nodes()
        self.assertEqual([node.node_type for node in self.studio.workflow_order()], ["start", "click", "delay", "end"])

    def test_playback_sets_and_clears_active_node(self):
        self.studio.selected = self.node("start")
        self.studio.add_node("delay", x=120, y=180)
        delay = self.studio.selected
        self.studio.auto_link_nodes()
        seen = []

        def capture_active(node):
            seen.append((node.node_id, self.studio.active_node_id))

        with patch.object(self.studio, "execute_node", capture_active):
            self.studio.playing = True
            self.studio.play_context = self.studio.create_play_context()
            self.studio._play_after_countdown(0)

        self.assertIn((delay.node_id, delay.node_id), seen)
        self.assertIsNone(self.studio.active_node_id)


class PersistenceTests(MacroStudioTestCase):
    def test_save_and_load_preserves_node_ids_and_edges(self):
        self.studio.add_node("delay")
        self.studio.auto_link_nodes()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.macro.json"
            self.studio.write_macro(self.studio.doc, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("id", payload["nodes"][0])
            self.assertGreaterEqual(len(payload["edges"]), 1)

            self.studio.open_macro_file(path)
            loaded = self.studio.doc
            self.assertEqual(len(loaded.edges), len(payload["edges"]))
            self.assertEqual(
                sorted(node.node_id for node in loaded.nodes),
                sorted(item["id"] for item in payload["nodes"]),
            )


class RecordingTests(MacroStudioTestCase):
    def test_recorded_nodes_insert_between_start_and_end(self):
        start = self.node("start")
        self.studio.record_insert_after_id = start.node_id
        self.studio.add_recorded_node_to_flow({"kind": "click", "x": 10, "y": 20, "button": "left", "delay": 0.2})
        self.studio.add_recorded_node_to_flow({"kind": "key", "key": "enter", "delay": 0.1})
        self.assertEqual([node.title for node in self.studio.workflow_order()], ["Start", "Left Click", "Key: enter", "End"])

    def test_click_press_release_collapses_to_one_recorded_node(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Button:
            def __str__(self):
                return "Button.left"

        self.studio.on_record_click(10, 20, Button(), True)
        self.studio.on_record_click(10, 20, Button(), False)
        self.studio.update()
        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].title, "Left Click")
        self.assertNotIn("pressed", recorded[0].data["event"])

    def test_key_press_release_collapses_to_one_recorded_node(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Key:
            char = "a"

        self.studio.on_record_key_press(Key())
        self.studio.on_record_key_release(Key())
        self.studio.update()
        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].title, "Key: a")
        self.assertNotIn("pressed", recorded[0].data["event"])


class DataAndUiTests(MacroStudioTestCase):
    def test_parse_inline_paste_data_supports_excel_style_tabs(self):
        self.assertEqual(self.studio.parse_inline_paste_data("A\tB\nC\tD", 2), ["B", "D"])
        self.assertEqual(self.studio.parse_inline_paste_data("one\ntwo\n", 1), ["one", "two"])

    def test_render_template_uses_loop_and_counter_values(self):
        self.studio.play_context = {
            "iteration": 2,
            "loop_count": 5,
            "counters": {"counter": 9},
            "paste_index": 0,
            "paste_cache": {},
        }
        self.assertEqual(self.studio.render_template("item-{counter}-{iteration}/{loop_count}"), "item-9-2/5")

    def test_header_logo_is_cropped_and_scaled(self):
        self.assertIsNotNone(self.studio.app_icon)
        self.assertIsNotNone(self.studio.header_logo_image)
        self.assertLessEqual(max(self.studio.header_logo_image.width(), self.studio.header_logo_image.height()), 60)
        self.assertGreaterEqual(min(self.studio.header_logo_image.width(), self.studio.header_logo_image.height()), 30)

    def test_app_uses_standard_menu_bar_instead_of_recent_toolbar_combo(self):
        buttons = [child for child in self.studio.menu_bar.winfo_children() if child.winfo_class() == "Menubutton"]
        labels = [child.cget("text") for child in buttons]
        self.assertEqual(labels, ["File", "Edit", "View", "Run", "Settings"])
        self.assertEqual(str(self.studio.menu_bar.cget("background")), app.THEME["panel"])
        self.assertEqual(str(self.studio.recent_menu.cget("background")), app.THEME["panel"])
        self.assertFalse(self.studio["menu"])
        self.assertTrue(hasattr(self.studio, "recent_menu"))
        self.assertFalse(hasattr(self.studio, "recent_combo"))
        self.assertTrue(buttons[0].bind("<Button-1>"))

    def test_custom_menu_buttons_post_dropdowns(self):
        file_button = next(
            child for child in self.studio.menu_bar.winfo_children()
            if child.winfo_class() == "Menubutton" and child.cget("text") == "File"
        )
        menu = file_button["menu"]
        menu_widget = self.studio.nametowidget(menu)
        calls = []

        with patch.object(menu_widget, "tk_popup", lambda x, y: calls.append((x, y))), patch.object(menu_widget, "grab_release", lambda: None):
            self.assertEqual(self.studio.post_menu(file_button, menu_widget), "break")

        self.assertEqual(len(calls), 1)

    def test_script_and_status_labels_are_color_coded(self):
        self.studio.doc.dirty = False
        self.studio.update_current_tab_title()
        self.assertEqual(str(self.studio.script_status_label.cget("foreground")), app.THEME["success"])

        self.studio.doc.dirty = True
        self.studio.update_current_tab_title()
        self.assertEqual(str(self.studio.script_status_label.cget("foreground")), app.THEME["error"])

        self.studio.status.set("Playing loop 1 of 1")
        self.assertEqual(str(self.studio.status_label.cget("foreground")), app.THEME["success"])
        self.studio.status.set("Stopped")
        self.assertEqual(str(self.studio.status_label.cget("foreground")), app.THEME["error"])
        self.studio.status.set("Playback complete")
        self.assertEqual(str(self.studio.status_label.cget("foreground")), app.THEME["success"])

    def test_space_and_escape_shortcuts_ignore_text_editors(self):
        calls = []
        entry = app.ttk.Entry(self.studio)
        text = app.tk.Text(self.studio)
        event = type("Event", (), {})()

        with patch.object(self.studio, "play_macro", lambda: calls.append("play")):
            event.widget = entry
            self.assertIsNone(self.studio.on_play_shortcut(event))

        with patch.object(self.studio, "stop_all", lambda: calls.append("stop")):
            event.widget = text
            self.assertIsNone(self.studio.on_stop_shortcut(event))

        self.assertEqual(calls, [])

    def test_space_shortcut_still_runs_outside_text_editors(self):
        calls = []
        button = app.ttk.Frame(self.studio)
        event = type("Event", (), {"widget": button})()

        with patch.object(self.studio, "play_macro", lambda: calls.append("play")):
            self.assertEqual(self.studio.on_play_shortcut(event), "break")

        self.assertEqual(calls, ["play"])

    def test_curve_helpers_return_expected_geometry(self):
        points = app.cubic_points((0, 0), (0, 10), (10, 10), (10, 20), 4)
        self.assertEqual(points[0], (0, 0))
        self.assertEqual(points[-1], (10, 20))
        self.assertEqual(app.hex_to_rgba("#42d392"), (66, 211, 146, 255))

    @unittest.skipIf(app.Image is None, "Pillow is unavailable")
    def test_canvas_uses_antialiased_images_for_edges_and_ports(self):
        self.studio.refresh()
        self.assertGreaterEqual(len(self.studio.canvas_image_refs), 3)
        self.assertGreaterEqual(len(self.studio.port_items), 2)

    @unittest.skipIf(app.Image is None, "Pillow is unavailable")
    def test_nodes_use_antialiased_panel_images_with_text_hit_targets(self):
        self.studio.refresh()
        image_count = len(self.studio.canvas_image_refs)
        self.assertGreaterEqual(image_count, len(self.studio.nodes) * 3)
        self.assertTrue(self.studio.node_items)

    def test_wait_hotkey_node_is_available_in_timing_category(self):
        self.assertIn("wait_hotkey", app.NODE_TYPES)
        timing = dict(app.NODE_CATEGORIES)["Timing"]
        self.assertIn("wait_hotkey", timing)
        self.assertIn("hotkey", app.NODE_TYPES["wait_hotkey"]["defaults"])

    def test_global_delay_is_script_level_timing_node(self):
        self.assertIn("global_delay", app.NODE_TYPES)
        timing = dict(app.NODE_CATEGORIES)["Timing"]
        self.assertIn("global_delay", timing)

        self.studio.doc.edges = []
        self.studio.add_node("global_delay", x=100, y=120, data={"seconds": "0.25"})
        nodes, loop_count, global_delay = self.studio.playback_nodes_and_count()

        self.assertEqual(loop_count, 1)
        self.assertEqual(global_delay, 0.25)
        self.assertNotIn("global_delay", [node.node_type for node in nodes])

    def test_wait_hotkey_timeout_returns_without_match(self):
        calls = []

        class FakeListener:
            def __init__(self, on_press=None, on_release=None):
                self.on_press = on_press
                self.on_release = on_release

            def start(self):
                calls.append("start")

            def stop(self):
                calls.append("stop")

        fake_keyboard = type("FakeKeyboard", (), {"Listener": FakeListener})
        with patch.object(app, "keyboard", fake_keyboard):
            self.studio.playing = True
            self.studio.wait_for_hotkey("<ctrl>+x", 0.01)

        self.assertEqual(calls, ["start", "stop"])

    def test_wait_hotkey_accepts_ctrl_space_format(self):
        calls = []

        class FakeKey:
            def __init__(self, name):
                self.name = name

            def __str__(self):
                return f"Key.{self.name}"

        class FakeListener:
            def __init__(self, on_press=None, on_release=None):
                self.on_press = on_press
                self.on_release = on_release

            def start(self):
                calls.append("start")
                self.on_press(FakeKey("ctrl_l"))
                self.on_press(FakeKey("space"))

            def stop(self):
                calls.append("stop")

        fake_keyboard = type("FakeKeyboard", (), {"Listener": FakeListener})
        with patch.object(app, "keyboard", fake_keyboard):
            self.studio.playing = True
            self.studio.wait_for_hotkey("<ctrl>+space", 1)

        self.assertEqual(calls, ["start", "stop"])

    def test_wait_hotkey_token_normalization(self):
        self.assertEqual(app.hotkey_token_set("<ctrl>+<shift>+space"), {"ctrl", "shift", "space"})
        self.assertEqual(app.hotkey_token_set("control + a"), {"ctrl", "a"})

    def test_hotkey_node_includes_select_all_and_custom_option(self):
        options = app.FIELD_OPTIONS[("hotkey", "keys")]
        self.assertIn("ctrl+a", options)
        self.assertIn("custom", options)

    def test_hotkey_node_uses_custom_keys_when_selected(self):
        self.assertEqual(
            self.studio.hotkey_parts({"keys": "custom", "custom_keys": "ctrl+shift+a"}),
            ["ctrl", "shift", "a"],
        )
        self.assertEqual(self.studio.hotkey_parts({"keys": "ctrl+a", "custom_keys": "ctrl+shift+a"}), ["ctrl", "a"])

    def test_paste_uses_dedicated_clipboard_shortcut(self):
        calls = []
        with patch.object(app.WindowsInput, "paste_clipboard", lambda: calls.append("paste")):
            self.studio.execute_paste({"source": "clipboard"})

        self.assertEqual(calls, ["paste"])

    def test_data_paste_sets_clipboard_before_pasting(self):
        calls = []
        with patch.object(app.WindowsInput, "paste_clipboard", lambda: calls.append("paste")), patch.object(app.time, "sleep", lambda _seconds: None):
            self.studio.execute_paste({"source": "data", "data": "first\nsecond", "column": 1})

        self.assertEqual(calls, ["paste"])
        self.assertEqual(self.studio.clipboard_get(), "first")

    def test_key_lookup_normalizes_control_aliases(self):
        self.assertEqual(app.WindowsInput.key_to_vk("control"), app.WindowsInput.VK["ctrl"])
        self.assertEqual(app.WindowsInput.key_to_vk("Key.ctrl_l"), app.WindowsInput.VK["ctrl"])


if __name__ == "__main__":
    unittest.main()
