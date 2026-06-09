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

    def test_auto_organize_nodes_arranges_and_links_workflow(self):
        self.studio.add_node("delay", x=520, y=420)
        self.studio.add_node("click", x=80, y=260)
        self.studio.doc.edges = []
        self.studio.auto_organize_nodes()

        ordered = self.studio.workflow_order()
        self.assertEqual([node.node_type for node in ordered], ["start", "click", "delay", "end"])
        self.assertEqual([node.x for node in ordered], [170, 170, 170, 170])
        self.assertEqual([node.y for node in ordered], sorted(node.y for node in ordered))

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

    def test_node_display_size_scales_without_changing_stored_node_size(self):
        self.assertEqual(app.NODE_W, 202)
        self.assertEqual(app.NODE_H, 72)
        self.assertGreaterEqual(self.studio.node_display_w(), app.NODE_W)
        self.assertGreaterEqual(self.studio.node_display_h(), app.NODE_H)

    def test_loop_script_supports_until_hotkey_settings(self):
        loop = app.MacroNode("loop", 0, 0, {"mode": "until hotkey", "count": 3, "stop_hotkey": "<ctrl>+q"})
        settings = self.studio.loop_settings(loop)
        self.assertEqual(settings["mode"], "until hotkey")
        self.assertIsNone(settings["count"])
        self.assertEqual(settings["stop_hotkey"], "<ctrl>+q")
        self.assertIn("until", self.studio.node_summary(loop))

    def test_until_hotkey_loop_runs_until_playback_stops(self):
        start = self.node("start")
        end = self.node("end")
        loop = app.MacroNode("loop", 170, 170, {"mode": "until hotkey", "count": 3, "stop_hotkey": "<ctrl>+q"})
        delay = app.MacroNode("delay", 170, 260, {"seconds": 0})
        self.studio.nodes = [start, loop, delay, end]
        self.studio.doc.edges = [
            {"from": start.node_id, "to": loop.node_id},
            {"from": loop.node_id, "to": delay.node_id},
            {"from": delay.node_id, "to": end.node_id},
        ]
        iterations = []

        def capture(node):
            if node.node_type == "delay":
                iterations.append(self.studio.play_context["iteration"])
                if len(iterations) == 3:
                    self.studio.playing = False

        with patch.object(self.studio, "start_playback_stop_listener") as start_listener, \
            patch.object(self.studio, "execute_node", capture):
            self.studio.playing = True
            self.studio.play_context = self.studio.create_play_context()
            self.studio._play_after_countdown(0)

        start_listener.assert_called_once_with("<ctrl>+q")
        self.assertEqual(iterations, [1, 2, 3])


class PersistenceTests(MacroStudioTestCase):
    def test_save_and_load_preserves_node_ids_and_edges(self):
        self.studio.add_node("delay")
        self.studio.auto_link_nodes()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.macro"
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
    def test_mouse_move_uses_direct_physical_cursor_position(self):
        calls = []

        class FakeUser32:
            def SetCursorPos(self, x, y):
                calls.append((x, y))
                return 1

        class FakeWindll:
            user32 = FakeUser32()

        with patch.object(app.ctypes, "windll", FakeWindll()):
            app.WindowsInput.move_mouse("123", "456")

        self.assertEqual(calls, [(123, 456)])

    def test_parse_inline_paste_data_supports_excel_style_tabs(self):
        self.assertEqual(self.studio.parse_inline_paste_data("A\tB\nC\tD", 2), ["B", "D"])
        self.assertEqual(self.studio.parse_inline_paste_data("one\ntwo\n", 1), ["one", "two"])

    def test_render_template_uses_loop_and_counter_values(self):
        self.studio.play_context = {
            "iteration": 2,
            "loop_count": 5,
            "counters": {"counter": 9},
            "variables": {},
            "datasets": {},
            "paste_index": 0,
            "paste_cache": {},
        }
        self.assertEqual(self.studio.render_template("item-{counter}-{iteration}/{loop_count}"), "item-9-2/5")

    def test_render_template_uses_saved_variables(self):
        self.studio.play_context = self.studio.create_play_context()
        self.studio.set_play_variable("first_click_x", 345)
        self.studio.set_play_variable("first_click_y", 678)
        self.assertEqual(self.studio.render_template("{first_click_x},{first_click_y}"), "345,678")

    def test_capture_nodes_are_available(self):
        self.assertIn("wait_click", app.NODE_TYPES)
        self.assertIn("save_mouse", app.NODE_TYPES)
        self.assertIn("save_clipboard", app.NODE_TYPES)
        timing_nodes = dict(app.NODE_CATEGORIES)["Timing"]
        mouse_nodes = dict(app.NODE_CATEGORIES)["Mouse"]
        clipboard_nodes = dict(app.NODE_CATEGORIES)["Clipboard"]
        self.assertIn("wait_click", timing_nodes)
        self.assertIn("save_mouse", mouse_nodes)
        self.assertIn("save_clipboard", clipboard_nodes)

    def test_mouse_nodes_accept_saved_coordinate_placeholders(self):
        self.studio.play_context = self.studio.create_play_context()
        self.studio.set_play_variable("first_click_x", 111)
        self.studio.set_play_variable("first_click_y", 222)

        with patch.object(app.WindowsInput, "move_mouse") as move:
            self.studio.execute_node(app.MacroNode("move", 0, 0, {"x": "{first_click_x}", "y": "{first_click_y}"}))

        move.assert_called_once_with(111, 222)

    def test_save_clipboard_node_stores_clipboard_variable(self):
        self.studio.play_context = self.studio.create_play_context()
        self.studio.clipboard_clear()
        self.studio.clipboard_append("copied value")
        self.studio.execute_node(app.MacroNode("save_clipboard", 0, 0, {"variable": "captured"}))
        self.assertEqual(self.studio.play_context["variables"]["captured"], "copied value")

    def test_save_clipboard_node_appends_dataset_values(self):
        self.studio.play_context = self.studio.create_play_context()
        node = app.MacroNode(
            "save_clipboard",
            0,
            0,
            {"target": "dataset", "dataset": "items", "variable": "clipboard", "file_path": "", "include_blank": "no"},
        )
        for value in ("alpha", "beta"):
            self.studio.clipboard_clear()
            self.studio.clipboard_append(value)
            self.studio.execute_node(node)

        self.assertEqual(self.studio.play_context["datasets"]["items"], ["alpha", "beta"])
        self.assertEqual(self.studio.play_context["variables"]["items"], "alpha\nbeta")
        self.assertEqual(self.studio.play_context["variables"]["items_count"], 2)
        self.assertEqual(self.studio.play_context["variables"]["items_last"], "beta")
        self.assertEqual(self.studio.render_template("{items_count}:{items_last}"), "2:beta")

    def test_save_clipboard_node_skips_blank_values_by_default(self):
        self.studio.play_context = self.studio.create_play_context()
        self.studio.clipboard_clear()
        self.studio.execute_node(app.MacroNode("save_clipboard", 0, 0, {"target": "dataset", "dataset": "items"}))
        self.assertNotIn("items", self.studio.play_context["datasets"])

    def test_save_clipboard_node_appends_to_file(self):
        self.studio.play_context = self.studio.create_play_context()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "captures.txt"
            node = app.MacroNode(
                "save_clipboard",
                0,
                0,
                {"target": "file", "file_path": str(path), "include_blank": "no"},
            )
            for value in ("one", "two"):
                self.studio.clipboard_clear()
                self.studio.clipboard_append(value)
                self.studio.execute_node(node)

            self.assertEqual(path.read_text(encoding="utf-8"), "one\ntwo\n")

    def test_save_mouse_node_stores_coordinates(self):
        self.studio.play_context = self.studio.create_play_context()
        with patch.object(app, "get_mouse_position", lambda: (12, 34)):
            self.studio.execute_node(app.MacroNode("save_mouse", 0, 0, {"variable": "pos"}))
        self.assertEqual(self.studio.play_context["variables"]["pos_x"], 12)
        self.assertEqual(self.studio.play_context["variables"]["pos_y"], 34)

    def test_wait_click_node_can_save_click_location(self):
        class FakeListener:
            def __init__(self, on_click):
                self.on_click = on_click

            def start(self):
                self.on_click(77, 88, "Button.left", True)

            def stop(self):
                pass

        fake_mouse = type("FakeMouse", (), {"Listener": FakeListener})
        self.studio.playing = True
        self.studio.play_context = self.studio.create_play_context()

        with patch.object(app, "mouse", fake_mouse):
            self.studio.execute_node(
                app.MacroNode(
                    "wait_click",
                    0,
                    0,
                    {"button": "left", "timeout": 0, "save_position": "yes", "variable": "first_click"},
                )
            )

        self.assertEqual(self.studio.play_context["variables"]["first_click_x"], 77)
        self.assertEqual(self.studio.play_context["variables"]["first_click_y"], 88)
        self.assertEqual(self.studio.play_context["variables"]["first_click_button"], "left")

    def test_header_logo_is_cropped_and_scaled(self):
        self.assertIsNotNone(self.studio.app_icon)
        self.assertIsNotNone(self.studio.header_logo_image)
        self.assertLessEqual(max(self.studio.header_logo_image.width(), self.studio.header_logo_image.height()), app.ui(60))
        self.assertGreaterEqual(min(self.studio.header_logo_image.width(), self.studio.header_logo_image.height()), 30)
        if app.Image is not None:
            self.assertIsNotNone(self.studio.app_icon_large)
            self.assertEqual(max(self.studio.header_logo_image.width(), self.studio.header_logo_image.height()), app.ui(44))

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
        view_button = next(button for button in buttons if button.cget("text") == "View")
        view_menu = self.studio.nametowidget(view_button["menu"])
        view_labels = [
            view_menu.entrycget(index, "label")
            for index in range(view_menu.index("end") + 1)
            if view_menu.type(index) != "separator"
        ]
        self.assertIn("Auto Organize Nodes", view_labels)

    def test_uses_new_logo_assets_and_macro_extension(self):
        self.assertEqual(app.APP_ICON_CANDIDATES[0].name, "macro-logo-150.png")
        self.assertTrue(app.APP_ICON_CANDIDATES[0].exists())
        self.assertTrue((app.ASSETS_DIR / "macro-logo-300.png").exists())
        self.assertTrue((app.ASSETS_DIR / "macro-logo.svg").exists())
        self.assertEqual(app.MACRO_FILETYPES[0], ("Macro files", "*.macro"))

    def test_script_tabs_show_close_button_and_clean_title_removes_it(self):
        title = self.studio.doc.tab_title
        self.assertTrue(title.endswith("  x"))
        self.assertEqual(app.clean_tab_title(title), self.studio.doc.name)

    def test_clicking_tab_close_button_closes_only_that_tab(self):
        self.studio.new_macro()
        second_tab = self.studio.tabs.tabs()[1]
        self.studio.update()
        self.studio.update_idletasks()
        self.studio.draw_tab_bar()
        close_x1, close_y1, close_x2, close_y2 = self.studio.tab_hit_boxes[0]["close"]
        event = type("Event", (), {"x": int((close_x1 + close_x2) / 2), "y": int((close_y1 + close_y2) / 2)})()

        with patch.object(self.studio, "confirm_save_if_dirty", lambda doc: True):
            self.assertEqual(self.studio.on_tab_click(event), "break")

        self.assertEqual(self.studio.tabs.tabs(), (second_tab,))

    def test_clicking_tab_body_does_not_close_tab(self):
        self.studio.new_macro()
        self.studio.update()
        self.studio.update_idletasks()
        self.studio.draw_tab_bar()
        body_x1, body_y1, _body_x2, _body_y2 = self.studio.tab_hit_boxes[0]["body"]
        event = type("Event", (), {"x": body_x1 + 12, "y": body_y1 + 12})()

        self.assertEqual(self.studio.on_tab_click(event), "break")
        self.assertEqual(len(self.studio.tabs.tabs()), 2)

    def test_tab_close_hit_uses_right_side_of_tab_bbox(self):
        self.studio.tab_hit_boxes = []
        with patch.object(self.studio.tabs, "bbox", lambda index: (10, 4, 120, 30)):
            self.assertTrue(self.studio.tab_close_hit(0, 121, 19))
            self.assertFalse(self.studio.tab_close_hit(0, 40, 19))

    def test_inspector_actions_use_grid_and_icons(self):
        buttons = self.studio.inspector_actions.winfo_children()
        self.assertEqual(len(buttons), 7)
        self.assertTrue(all(button.grid_info() for button in buttons))
        icons = [getattr(button, "icon", None) for button in buttons]
        self.assertNotIn("link", icons)
        self.assertIn("trash", icons)

    def test_toolbar_run_buttons_have_icons(self):
        buttons = [
            child for child in self.studio.winfo_children()[1].winfo_children()
            if isinstance(child, app.RoundedButton)
        ]
        self.assertIn("record", [button.icon for button in buttons])
        self.assertIn("play", [button.icon for button in buttons])
        self.assertIn("stop", [button.icon for button in buttons])

    def test_tab_close_hover_tracks_close_button(self):
        self.studio.draw_tab_bar()
        close_x1, close_y1, close_x2, close_y2 = self.studio.tab_hit_boxes[0]["close"]
        event = type("Event", (), {"x": int((close_x1 + close_x2) / 2), "y": int((close_y1 + close_y2) / 2)})()
        self.studio.on_tab_motion(event)
        self.assertEqual(self.studio.hover_tab_close, 0)
        self.studio.on_tab_leave(event)
        self.assertIsNone(self.studio.hover_tab_close)

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
        self.assertEqual(app.hex_to_rgba("#32ff89"), (50, 255, 137, 255))

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
        nodes, loop_settings, global_delay = self.studio.playback_nodes_and_count()

        self.assertEqual(loop_settings["count"], 1)
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
