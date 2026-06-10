import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
import playback
import winput


class MacroStudioTestCase(unittest.TestCase):
    def setUp(self):
        self.original_install_global_hotkeys = app.MacroStudio.install_global_hotkeys
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

    def test_auto_organize_nodes_resizes_loop_frames_around_children(self):
        start = app.MacroNode("start", 80, 80, {})
        outer = app.MacroNode("loop_frame", 100, 180, {"width": 520, "height": 520, "count": 2})
        wait = app.MacroNode("wait_click", 650, 620, {"button": "any", "timeout": 0, "save_position": "yes", "variable": "click"})
        inner = app.MacroNode("loop_frame", 180, 280, {"width": 300, "height": 300, "count": 4})
        delay = app.MacroNode("delay", 230, 360, {"seconds": 0})
        end = app.MacroNode("end", 80, 820, {})
        self.studio.nodes = [start, outer, wait, inner, delay, end]
        self.studio.doc.edges = [
            {"from": start.node_id, "to": outer.node_id},
            {"from": outer.node_id, "to": end.node_id},
        ]

        self.studio.auto_organize_nodes()

        self.assertTrue(self.studio.node_inside_frame(wait, outer))
        self.assertTrue(self.studio.node_inside_frame(inner, outer))
        self.assertTrue(self.studio.node_inside_frame(delay, inner))
        self.assertEqual(self.studio.nearest_loop_frame(wait), outer)
        self.assertEqual(self.studio.nearest_loop_frame(delay), inner)
        self.assertGreaterEqual(outer.x + self.studio.node_world_w(outer), wait.x + self.studio.node_world_w(wait))
        self.assertGreaterEqual(inner.y + self.studio.node_world_h(inner), delay.y + self.studio.node_world_h(delay))

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

    def test_loop_frame_is_available_in_flow_category(self):
        self.assertIn("loop_frame", app.NODE_TYPES)
        flow = next(items for label, items in app.NODE_CATEGORIES if label == "Flow")
        self.assertIn("loop_frame", flow)

    def test_loop_frame_body_uses_visual_containment_and_nearest_frame(self):
        outer = app.MacroNode("loop_frame", 100, 100, {"width": 420, "height": 420, "count": 2})
        inner = app.MacroNode("loop_frame", 180, 190, {"width": 220, "height": 190, "count": 3})
        outer_delay = app.MacroNode("delay", 120, 500, {"seconds": 0})
        inner_delay = app.MacroNode("delay", 230, 250, {"seconds": 0})
        outside_delay = app.MacroNode("delay", 700, 700, {"seconds": 0})
        self.studio.nodes = [outer, inner, outer_delay, inner_delay, outside_delay]

        self.assertEqual(self.studio.nearest_loop_frame(outer_delay), outer)
        self.assertEqual(self.studio.nearest_loop_frame(inner_delay), inner)
        self.assertIsNone(self.studio.nearest_loop_frame(outside_delay))
        self.assertEqual(self.studio.loop_frame_body_nodes(outer), [inner, outer_delay])
        self.assertEqual(self.studio.loop_frame_body_nodes(inner), [inner_delay])

    def test_loop_frame_resize_drag_updates_dimensions(self):
        frame = app.MacroNode("loop_frame", 100, 100, {"width": 360, "height": 300, "count": 2})
        self.studio.nodes = [frame]
        self.studio.selected = frame
        start_w = self.studio.node_world_w(frame)
        start_h = self.studio.node_world_h(frame)
        self.studio.frame_resize = {
            "node": frame,
            "start_x": 0,
            "start_y": 0,
            "start_w": start_w,
            "start_h": start_h,
        }
        event = type("Event", (), {"x": 120, "y": 90})()

        with patch.object(self.studio, "refresh") as refresh:
            self.studio.update_frame_resize(event)

        self.assertGreater(frame.data["width"], 360)
        self.assertGreater(frame.data["height"], 300)
        refresh.assert_called_once()
        self.assertTrue(refresh.call_args.kwargs["fast"])

    def test_playback_excludes_nodes_inside_loop_frames_from_top_level(self):
        start = app.MacroNode("start", 80, 80, {})
        frame = app.MacroNode("loop_frame", 80, 180, {"width": 360, "height": 240, "count": 2})
        body_delay = app.MacroNode("delay", 160, 260, {"seconds": 0})
        end = app.MacroNode("end", 80, 520, {})
        self.studio.nodes = [start, frame, body_delay, end]
        self.studio.doc.edges = []

        nodes, _loop_settings, _global_delay = self.studio.playback_nodes_and_count()

        self.assertEqual(nodes, [start, frame, end])

    def test_loop_frame_executes_body_count_times(self):
        start = app.MacroNode("start", 80, 80, {})
        frame = app.MacroNode("loop_frame", 80, 180, {"width": 360, "height": 260, "count": 3})
        delay = app.MacroNode("delay", 150, 270, {"seconds": 0})
        end = app.MacroNode("end", 80, 560, {})
        self.studio.nodes = [start, frame, delay, end]
        self.studio.doc.edges = []
        seen = []
        original_execute_node = self.studio.execute_node

        def capture(node):
            if node.node_type == "delay":
                seen.append((self.studio.play_context["iteration"], self.studio.play_context["loop_index"]))
            original_execute_node(node)

        with patch.object(self.studio, "wait_interruptible", lambda _seconds: None), \
            patch.object(self.studio, "execute_node", capture):
            self.studio.playing = True
            self.studio.play_context = self.studio.create_play_context()
            self.studio._play_after_countdown(0)

        self.assertEqual(seen, [(1, 0), (2, 1), (3, 2)])

    def test_nested_loop_frames_execute_inner_frame_as_body(self):
        start = app.MacroNode("start", 80, 80, {})
        outer = app.MacroNode("loop_frame", 80, 180, {"width": 520, "height": 420, "count": 2})
        inner = app.MacroNode("loop_frame", 170, 280, {"width": 280, "height": 220, "count": 3})
        delay = app.MacroNode("delay", 230, 360, {"seconds": 0})
        end = app.MacroNode("end", 80, 700, {})
        self.studio.nodes = [start, outer, inner, delay, end]
        self.studio.doc.edges = []
        seen = []
        original_execute_node = self.studio.execute_node

        def capture(node):
            if node.node_type == "delay":
                seen.append(node.node_id)
            original_execute_node(node)

        with patch.object(self.studio, "wait_interruptible", lambda _seconds: None), \
            patch.object(self.studio, "execute_node", capture):
            self.studio.playing = True
            self.studio.play_context = self.studio.create_play_context()
            self.studio._play_after_countdown(0)

        self.assertEqual(len(seen), 6)


class BranchingTests(MacroStudioTestCase):
    def build_branching_script(self):
        start = app.MacroNode("start", 80, 80, {})
        cond = app.MacroNode("if_window", 80, 180, {"title_contains": "Target", "wait": 0})
        then_node = app.MacroNode("type", 20, 300, {"text": "yes"})
        else_node = app.MacroNode("type", 300, 300, {"text": "no"})
        end = app.MacroNode("end", 80, 420, {})
        self.studio.nodes = [start, cond, then_node, else_node, end]
        self.studio.doc.edges = [
            {"from": start.node_id, "to": cond.node_id},
            {"from": cond.node_id, "to": then_node.node_id, "branch": "then"},
            {"from": cond.node_id, "to": else_node.node_id, "branch": "else"},
            {"from": then_node.node_id, "to": end.node_id},
            {"from": else_node.node_id, "to": end.node_id},
        ]
        return cond

    def run_playback(self):
        self.studio.playing = True
        self.studio.play_context = self.studio.create_play_context()
        self.studio._play_after_countdown(0)

    def test_if_window_takes_then_branch_on_match(self):
        self.build_branching_script()
        typed = []
        with patch.object(playback, "get_active_window_title", lambda: "My Target Window"), \
            patch.object(app.WindowsInput, "type_text", lambda text, _should_continue=None: typed.append(text)):
            self.run_playback()
        self.assertEqual(typed, ["yes"])

    def test_if_window_takes_else_branch_without_match(self):
        self.build_branching_script()
        typed = []
        with patch.object(playback, "get_active_window_title", lambda: "Another Window"), \
            patch.object(app.WindowsInput, "type_text", lambda text, _should_continue=None: typed.append(text)):
            self.run_playback()
        self.assertEqual(typed, ["no"])

    def test_if_window_sets_window_found_variable(self):
        self.build_branching_script()
        results = []
        original_execute = self.studio.execute_node

        def capture(node):
            original_execute(node)
            if node.node_type == "if_window":
                results.append(self.studio.play_context["variables"]["window_found"])

        with patch.object(playback, "get_active_window_title", lambda: "Target ahead"), \
            patch.object(app.WindowsInput, "type_text", lambda text, _should_continue=None: None), \
            patch.object(self.studio, "execute_node", capture):
            self.run_playback()
        self.assertEqual(results, ["yes"])

    def test_if_window_node_renders_branch_ports(self):
        self.build_branching_script()
        self.studio.refresh()
        branches = [port[2] for port in self.studio.port_items.values() if port[1] == "output"]
        self.assertIn("then", branches)
        self.assertIn("else", branches)

    def test_connection_drag_from_branch_port_creates_branch_edge(self):
        cond = self.build_branching_script()
        delay = app.MacroNode("delay", 500, 500, {"seconds": 0})
        self.studio.nodes.append(delay)
        self.studio.connection_drag = {"source": cond, "branch": "else", "line": None, "start": (0, 0)}
        event = type("Event", (), {"x": 0, "y": 0})()
        with patch.object(self.studio, "find_port_at", lambda x, y, kind=None: (delay, "input", None)):
            self.studio.finish_connection_drag(event)
        self.assertTrue(
            any(
                edge.get("branch") == "else" and edge["to"] == delay.node_id
                for edge in self.studio.doc.edges
            )
        )

    def test_workflow_without_edges_still_plays_sequentially(self):
        start = app.MacroNode("start", 80, 80, {})
        first = app.MacroNode("type", 80, 180, {"text": "a"})
        second = app.MacroNode("type", 80, 280, {"text": "b"})
        end = app.MacroNode("end", 80, 380, {})
        self.studio.nodes = [start, first, second, end]
        self.studio.doc.edges = []
        typed = []
        with patch.object(app.WindowsInput, "type_text", lambda text, _should_continue=None: typed.append(text)):
            self.run_playback()
        self.assertEqual(typed, ["a", "b"])


class PersistenceTests(MacroStudioTestCase):
    def test_corrupt_macro_file_shows_error_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.macro"
            path.write_text("{not valid json", encoding="utf-8")
            errors = []
            doc_count = len(self.studio.documents)
            with patch.object(app.messagebox, "showerror", lambda *args, **kwargs: errors.append(args)):
                self.studio.open_macro_file(path)
            self.assertEqual(len(self.studio.documents), doc_count)
            self.assertEqual(len(errors), 1)

    def test_non_dict_macro_payload_shows_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.macro"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            errors = []
            with patch.object(app.messagebox, "showerror", lambda *args, **kwargs: errors.append(args)):
                self.studio.open_macro_file(path)
            self.assertEqual(len(errors), 1)

    def test_unknown_node_types_load_as_inert_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.macro"
            payload = {
                "version": 99,
                "nodes": [
                    {"id": "n1", "type": "start", "x": 80, "y": 80, "data": {}},
                    {"id": "n2", "type": "teleport", "x": 80, "y": 200, "data": {"warp": 9}},
                    {"id": "n3", "type": "end", "x": 80, "y": 320, "data": {}},
                ],
                "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            warnings = []
            with patch.object(app.messagebox, "showwarning", lambda *args, **kwargs: warnings.append(args)):
                self.studio.open_macro_file(path)
            self.assertEqual([node.node_type for node in self.studio.nodes], ["start", "note", "end"])
            note = self.studio.nodes[1]
            self.assertIn("teleport", note.title)
            self.assertEqual(len(warnings), 1)
            self.studio.refresh()  # must render without raising

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

    def test_press_drag_release_records_drag_node(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Button:
            def __str__(self):
                return "Button.left"

        self.studio.on_record_click(10, 20, Button(), True)
        self.studio.on_record_move(60, 80)
        self.studio.on_record_click(200, 240, Button(), False)
        self.studio.update()

        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(recorded), 1)
        event = recorded[0].data["event"]
        self.assertEqual(event["kind"], "drag")
        self.assertEqual((event["x"], event["y"]), (10, 20))
        self.assertEqual((event["x2"], event["y2"]), (200, 240))
        self.assertEqual(len(event["points"]), 1)
        self.assertEqual(recorded[0].title, "Left Drag")

    def test_recorded_drag_replays_press_move_release(self):
        calls = []
        self.studio.playing = True
        with patch.object(app.WindowsInput, "move_mouse", lambda x, y: calls.append(("move", x, y))), \
            patch.object(app.WindowsInput, "mouse_button", lambda button, pressed: calls.append(("button", button, pressed))), \
            patch.object(app.time, "sleep", lambda _seconds: None):
            self.studio.execute_recorded(
                {
                    "kind": "drag",
                    "x": 1,
                    "y": 2,
                    "x2": 50,
                    "y2": 60,
                    "button": "left",
                    "points": [{"x": 25, "y": 30, "delay": 0}],
                    "delay": 0,
                }
            )
        self.assertEqual(
            calls,
            [
                ("move", 1, 2),
                ("button", "left", True),
                ("move", 25, 30),
                ("move", 50, 60),
                ("button", "left", False),
            ],
        )

    def test_ctrl_combo_records_hotkey_node(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        ctrl_key = type("Ctrl", (), {"char": None, "__str__": lambda self: "Key.ctrl_l"})()
        c_key = type("C", (), {"char": "\x03"})()

        self.studio.on_record_key_press(ctrl_key)
        self.studio.on_record_key_press(c_key)
        self.studio.on_record_key_release(c_key)
        self.studio.on_record_key_release(ctrl_key)
        self.studio.update()

        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(recorded), 1)
        event = recorded[0].data["event"]
        self.assertEqual(event["kind"], "hotkey")
        self.assertEqual(event["keys"], "ctrl+c")
        self.assertEqual(recorded[0].title, "Hotkey: ctrl+c")

    def test_bare_modifier_tap_records_nothing(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        ctrl_key = type("Ctrl", (), {"char": None, "__str__": lambda self: "Key.ctrl_l"})()
        self.studio.on_record_key_press(ctrl_key)
        self.studio.on_record_key_release(ctrl_key)
        self.studio.update()

        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(recorded, [])

    def test_shift_typing_stays_plain_keys(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        shift_key = type("Shift", (), {"char": None, "__str__": lambda self: "Key.shift"})()
        upper_key = type("A", (), {"char": "A"})()
        self.studio.on_record_key_press(shift_key)
        self.studio.on_record_key_press(upper_key)
        self.studio.on_record_key_release(upper_key)
        self.studio.on_record_key_release(shift_key)
        self.studio.update()

        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].data["event"]["kind"], "key")
        self.assertEqual(recorded[0].data["event"]["key"], "A")

    def test_key_release_without_press_is_ignored(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Key:
            char = "r"

        # Simulates releasing the record hotkey just after it started
        # recording: the press was never captured, so no node should appear.
        self.studio.on_record_key_release(Key())
        self.studio.update()
        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(recorded, [])

    def test_click_release_without_press_is_ignored(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Button:
            def __str__(self):
                return "Button.left"

        self.studio.on_record_click(10, 20, Button(), False)
        self.studio.update()
        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(recorded, [])

    def _record_typed_keys(self, text):
        class Key:
            def __init__(self, char):
                self.char = char

        for char in text:
            key = Key(char)
            self.studio.on_record_key_press(key)
            self.studio.on_record_key_release(key)

    def test_typed_keys_coalesce_into_single_type_node(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        self._record_typed_keys("hello")
        self.studio.update()
        self.studio.stop_recording()
        self.studio.update()

        type_nodes = [node for node in self.studio.nodes if node.node_type == "type"]
        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        self.assertEqual(len(type_nodes), 1)
        self.assertEqual(type_nodes[0].data["text"], "hello")
        self.assertEqual(recorded, [])
        self.assertEqual(
            [node.node_type for node in self.studio.workflow_order()],
            ["start", "type", "end"],
        )

    def test_short_typed_runs_are_not_coalesced(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        self._record_typed_keys("hi")
        self.studio.update()
        self.studio.stop_recording()
        self.studio.update()

        recorded = [node for node in self.studio.nodes if node.node_type == "recorded"]
        type_nodes = [node for node in self.studio.nodes if node.node_type == "type"]
        self.assertEqual(len(recorded), 2)
        self.assertEqual(type_nodes, [])

    def test_coalescing_preserves_non_typed_events(self):
        self.studio.recording = True
        self.studio.record_start = time.perf_counter()
        self.studio.record_insert_after_id = self.node("start").node_id

        class Button:
            def __str__(self):
                return "Button.left"

        self._record_typed_keys("abc")
        self.studio.on_record_click(10, 20, Button(), True)
        self.studio.on_record_click(10, 20, Button(), False)
        self._record_typed_keys("x")
        self.studio.update()
        self.studio.stop_recording()
        self.studio.update()

        order = [node.node_type for node in self.studio.workflow_order()]
        self.assertEqual(order, ["start", "type", "recorded", "recorded", "end"])
        type_node = next(node for node in self.studio.nodes if node.node_type == "type")
        self.assertEqual(type_node.data["text"], "abc")


class PlaybackThreadingTests(MacroStudioTestCase):
    def test_play_macro_runs_playback_on_background_thread(self):
        self.studio.settings["playback_countdown"] = 0
        thread_checks = []

        with patch.object(app.messagebox, "askokcancel", lambda *args, **kwargs: True), \
            patch.object(self.studio, "execute_node", lambda node: thread_checks.append(threading.current_thread() is not threading.main_thread())):
            self.studio.play_macro()
            thread = self.studio.playback_thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.studio.update()
        self.assertTrue(thread_checks)
        self.assertTrue(all(thread_checks))
        self.assertFalse(self.studio.playing)

    def test_hotkey_play_skips_confirmation_dialog(self):
        self.studio.settings["playback_countdown"] = 0
        dialog_calls = []

        with patch.object(app.messagebox, "askokcancel", lambda *args, **kwargs: dialog_calls.append("asked") or True):
            self.studio.play_macro(from_hotkey=True)
            thread = self.studio.playback_thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)

        self.studio.update()
        self.assertEqual(dialog_calls, [])
        self.assertFalse(self.studio.playing)

    def test_button_play_still_asks_for_confirmation(self):
        dialog_calls = []

        with patch.object(app.messagebox, "askokcancel", lambda *args, **kwargs: dialog_calls.append("asked") or False):
            self.studio.play_macro()

        self.assertEqual(dialog_calls, ["asked"])
        self.assertIsNone(self.studio.playback_thread)
        self.assertFalse(self.studio.playing)


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
            "loop_index": 1,
            "loop_count": 5,
            "counters": {"counter": 9},
            "variables": {},
            "datasets": {},
            "paste_index": 0,
            "paste_cache": {},
        }
        self.assertEqual(self.studio.render_template("item-{counter}-{loop_index}-{iteration}/{loop_count}"), "item-9-1-2/5")

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

    def test_mouse_nodes_accept_saved_coordinate_math_offsets(self):
        self.studio.play_context = self.studio.create_play_context()
        self.studio.set_play_variable("first_click_x", 111)
        self.studio.set_play_variable("first_click_y", 222)
        self.studio.play_context["loop_index"] = 3

        with patch.object(app.WindowsInput, "move_mouse") as move:
            self.studio.execute_node(app.MacroNode("move", 0, 0, {"x": "{first_click_x}+({loop_index}*25)", "y": "({first_click_y}-10)"}))

        move.assert_called_once_with(186, 212)

    def test_workflow_nodes_cover_click_paste_loop_and_wait_click_sequence(self):
        self.assertIn("wait_click", app.NODE_TYPES)
        self.assertIn("loop_frame", app.NODE_TYPES)
        self.assertIn("click", app.NODE_TYPES)
        self.assertIn("paste", app.NODE_TYPES)
        self.assertIn("key", app.NODE_TYPES)
        self.assertEqual(app.NODE_TYPES["paste"]["defaults"]["source"], "clipboard")
        self.assertIn("file", app.FIELD_OPTIONS[("paste", "source")])

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
        # Tk's clipboard_clear never empties the system clipboard, so blank it
        # for real; playback reads the actual Windows clipboard.
        winput.set_clipboard_text("")
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
        with patch.object(playback, "get_mouse_position", lambda: (12, 34)):
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

        with patch.object(playback, "mouse", fake_mouse):
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

    def test_tab_titles_are_clean_with_dirty_marker_prefix(self):
        self.assertEqual(self.studio.doc.tab_title, self.studio.doc.name)
        self.studio.doc.dirty = True
        self.assertEqual(self.studio.doc.tab_title, f"*{self.studio.doc.name}")
        self.assertEqual(app.clean_tab_title(self.studio.doc.tab_title), self.studio.doc.name)

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

    def test_drag_uses_fast_canvas_refresh(self):
        start = self.node("start")
        self.studio.drag = [(start, 0, 0)]
        calls = []

        def capture_refresh(**kwargs):
            calls.append(kwargs)

        event = type("Event", (), {"x": 240, "y": 260})()
        with patch.object(self.studio, "refresh", capture_refresh):
            self.studio.on_canvas_drag(event)

        self.assertTrue(calls)
        self.assertTrue(calls[-1]["fast"])
        self.assertFalse(calls[-1]["update_inspector"])
        self.assertFalse(calls[-1]["update_status"])
        self.assertFalse(calls[-1]["update_scrollregion"])

    @unittest.skipIf(app.Image is None, "Pillow is unavailable")
    def test_repeated_refresh_reuses_cached_sprites(self):
        import render
        self.studio.refresh()
        cache_size_after_first = len(render._SPRITE_CACHE)
        self.assertGreater(cache_size_after_first, 0)
        self.studio.refresh()
        self.assertEqual(len(render._SPRITE_CACHE), cache_size_after_first)

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
        with patch.object(playback, "keyboard", fake_keyboard):
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
        with patch.object(playback, "keyboard", fake_keyboard):
            self.studio.playing = True
            self.studio.wait_for_hotkey("<ctrl>+space", 1)

        self.assertEqual(calls, ["start", "stop"])

    def test_wait_hotkey_token_normalization(self):
        self.assertEqual(app.hotkey_token_set("<ctrl>+<shift>+space"), {"ctrl", "shift", "space"})
        self.assertEqual(app.hotkey_token_set("control + a"), {"ctrl", "a"})
        self.assertEqual(app.canonical_hotkey("shift+ctrl+x"), "<ctrl>+<shift>+x")
        self.assertEqual(app.canonical_hotkey("<shift>+<control>+space"), "<ctrl>+<shift>+space")

    def test_loop_stop_listener_normalizes_hotkey_syntax(self):
        mappings = []

        class FakeGlobalHotKeys:
            def __init__(self, mapping):
                mappings.append(mapping)

            def start(self):
                pass

            def stop(self):
                pass

        fake_keyboard = type("FakeKeyboard", (), {"GlobalHotKeys": FakeGlobalHotKeys})
        with patch.object(playback, "keyboard", fake_keyboard):
            self.studio.start_playback_stop_listener("shift+ctrl+x")

        self.assertEqual(list(mappings[0].keys()), ["<ctrl>+<shift>+x"])

    def test_global_hotkeys_install_without_existing_listener(self):
        mappings = []

        class FakeGlobalHotKeys:
            def __init__(self, mapping):
                mappings.append(mapping)

            def start(self):
                pass

            def stop(self):
                pass

        fake_keyboard = type("FakeKeyboard", (), {"GlobalHotKeys": FakeGlobalHotKeys})
        with patch.object(app, "keyboard", fake_keyboard):
            self.studio.hotkey_listener = None
            self.original_install_global_hotkeys(self.studio)

        self.assertIn("<ctrl>+<shift>+x", mappings[0])

    def test_default_stop_hotkey_listener_starts_for_non_loop_playback(self):
        start_listener_calls = []
        start = self.node("start")
        end = self.node("end")
        text = app.MacroNode("type", 80, 160, {"text": "hello world"})
        self.studio.nodes = [start, text, end]
        self.studio.doc.edges = [
            {"from": start.node_id, "to": text.node_id},
            {"from": text.node_id, "to": end.node_id},
        ]

        with patch.object(self.studio, "start_playback_stop_listener", lambda hotkey: start_listener_calls.append(hotkey)), \
            patch.object(app.WindowsInput, "type_text", lambda _text, _should_continue=None: None):
            self.studio.playing = True
            self.studio.play_context = self.studio.create_play_context()
            self.studio._play_after_countdown(0)

        self.assertEqual(start_listener_calls, [self.studio.settings["stop_hotkey"]])

    def test_playback_stop_hotkey_callback_stops_immediately(self):
        mappings = []

        class FakeGlobalHotKeys:
            def __init__(self, mapping):
                mappings.append(mapping)

            def start(self):
                pass

            def stop(self):
                pass

        fake_keyboard = type("FakeKeyboard", (), {"GlobalHotKeys": FakeGlobalHotKeys})
        with patch.object(playback, "keyboard", fake_keyboard), patch.object(self.studio, "after", lambda _delay, callback: None):
            self.studio.playing = True
            self.studio.start_playback_stop_listener("shift+ctrl+x")
            mappings[0]["<ctrl>+<shift>+x"]()

        self.assertFalse(self.studio.playing)

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

    def test_type_text_emits_exact_unicode_text(self):
        sent = []
        text = "Hello, WORLD! 1+2 = 3.\nNext\tTab"
        with patch.object(app.WindowsInput, "unicode_key_tap", lambda code_unit: sent.append(code_unit)), \
            patch.object(app.time, "sleep", lambda _seconds: None):
            app.WindowsInput.type_text(text)

        self.assertEqual(sent, app.WindowsInput.utf16_code_units(text))

    def test_type_node_stops_when_playback_stops_mid_text(self):
        sent = []

        def capture(code_unit):
            sent.append(code_unit)
            self.studio.playing = False

        self.studio.playing = True
        with patch.object(app.WindowsInput, "unicode_key_tap", capture), patch.object(app.time, "sleep", lambda _seconds: None):
            self.studio.execute_node(app.MacroNode("type", 0, 0, {"text": "abc"}))

        self.assertEqual(sent, app.WindowsInput.utf16_code_units("a"))

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

    def test_file_paste_continues_across_nested_loop_iterations(self):
        start = app.MacroNode("start", 80, 80, {})
        outer = app.MacroNode("loop_frame", 80, 180, {"width": 620, "height": 520, "count": 2})
        inner = app.MacroNode("loop_frame", 150, 270, {"width": 420, "height": 320, "count": 4})
        end = app.MacroNode("end", 80, 780, {})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.csv"
            path.write_text("\n".join(f"item-{index}" for index in range(1, 9)), encoding="utf-8")
            paste = app.MacroNode("paste", 220, 360, {"source": "file", "file_path": str(path), "column": 1})
            self.studio.nodes = [start, outer, inner, paste, end]
            self.studio.doc.edges = [
                {"from": start.node_id, "to": outer.node_id},
                {"from": outer.node_id, "to": end.node_id},
            ]
            pasted = []

            def capture_paste():
                pasted.append(self.studio.clipboard_get())

            with patch.object(app.WindowsInput, "paste_clipboard", capture_paste), \
                patch.object(app.time, "sleep", lambda _seconds: None):
                self.studio.playing = True
                self.studio.play_context = self.studio.create_play_context()
                self.studio._play_after_countdown(0)

        self.assertEqual(pasted, [f"item-{index}" for index in range(1, 9)])

    def test_paste_cursors_are_tracked_per_node(self):
        self.studio.play_context = self.studio.create_play_context()
        data = {"source": "data", "data": "first\nsecond", "column": 1}
        pasted = []

        def capture_paste():
            pasted.append(self.studio.clipboard_get())

        with patch.object(app.WindowsInput, "paste_clipboard", capture_paste), \
            patch.object(app.time, "sleep", lambda _seconds: None):
            self.studio.execute_paste(data, "paste-a")
            self.studio.execute_paste(data, "paste-a")
            self.studio.execute_paste(data, "paste-b")

        self.assertEqual(pasted, ["first", "second", "first"])

    def test_duplicate_node_deep_copies_nested_data(self):
        self.studio.add_node(
            "recorded",
            x=100,
            y=100,
            data={"event": {"kind": "click", "x": 1, "y": 2, "button": "left", "delay": 0}},
        )
        original = self.studio.selected
        self.studio.duplicate_selected()
        duplicate = self.studio.selected
        self.assertIsNot(duplicate, original)
        duplicate.data["event"]["x"] = 999
        self.assertEqual(original.data["event"]["x"], 1)

    def test_add_node_does_not_share_nested_defaults(self):
        self.studio.add_node("recorded")
        first = self.studio.selected
        self.studio.add_node("recorded")
        second = self.studio.selected
        first.data["event"]["kind"] = "click"
        self.assertNotIn("kind", second.data["event"])

    def test_inspector_shows_friendly_field_labels(self):
        self.studio.add_node("wait_window")
        self.studio.update_inspector()
        labels = []
        for row in self.studio.inspector_body.winfo_children():
            for child in row.winfo_children():
                if child.winfo_class() == "TLabel":
                    labels.append(child.cget("text"))
        self.assertIn("Title contains", labels)
        self.assertIn("Timeout (s)", labels)
        self.assertNotIn("title_contains", labels)

    def test_stop_all_sets_calm_status_color(self):
        self.studio.stop_all()
        self.assertEqual(self.studio.status.get(), "Stopped")
        self.assertEqual(str(self.studio.status_label.cget("foreground")), app.THEME["info"])

    def test_zoom_anchors_to_cursor_position(self):
        self.studio.update()
        canvas = self.studio.canvas
        anchor = (150, 120)
        before_world = self.studio.from_screen(canvas.canvasx(anchor[0]))
        self.studio.set_zoom(1.6, anchor=anchor)
        after_world = self.studio.from_screen(canvas.canvasx(anchor[0]))
        # xscrollincrement quantizes scrolling, so allow one increment of drift
        self.assertAlmostEqual(before_world, after_world, delta=16)

    def test_right_click_on_node_posts_node_context_menu(self):
        self.studio.update()
        self.studio.refresh()
        start = self.node("start")
        x = int(self.studio.to_screen(start.x + 20))
        y = int(self.studio.to_screen(start.y + 20))
        event = type("Event", (), {"x": x, "y": y, "x_root": 0, "y_root": 0})()
        posted = []
        with patch.object(app.tk.Menu, "tk_popup", lambda menu, px, py: posted.append((px, py))):
            self.assertEqual(self.studio.on_canvas_context(event), "break")
        self.assertEqual(self.studio.selected, start)
        self.assertEqual(len(posted), 1)

    def test_box_select_selects_enclosed_nodes(self):
        self.studio.update()
        self.studio.refresh()
        start = self.node("start")
        end = self.node("end")
        press = type("Event", (), {"x": 700, "y": 30, "state": 0})()
        drag = type("Event", (), {"x": 5, "y": 700, "state": 0})()
        self.studio.on_canvas_press(press)
        self.assertIsNotNone(self.studio.box_select)
        self.studio.on_canvas_drag(drag)
        self.studio.on_canvas_release(drag)
        self.assertIn(start.node_id, self.studio.selected_ids)
        self.assertIn(end.node_id, self.studio.selected_ids)
        self.assertIsNone(self.studio.box_select)

    def test_group_drag_moves_all_selected_nodes_together(self):
        self.studio.update()
        self.studio.refresh()
        start = self.node("start")
        end = self.node("end")
        self.studio.doc.selected_ids = {start.node_id, end.node_id}
        self.studio.doc.selected = start
        start_pos = (start.x, start.y)
        end_pos = (end.x, end.y)
        press_x = int(self.studio.to_screen(start.x + 30))
        press_y = int(self.studio.to_screen(start.y + 20))
        press = type("Event", (), {"x": press_x, "y": press_y, "state": 0})()
        move = type("Event", (), {"x": press_x + 100, "y": press_y + 60, "state": 0})()
        self.studio.on_canvas_press(press)
        self.assertEqual(len(self.studio.drag), 2)
        self.studio.on_canvas_drag(move)
        self.studio.on_canvas_release(move)
        start_delta = (start.x - start_pos[0], start.y - start_pos[1])
        end_delta = (end.x - end_pos[0], end.y - end_pos[1])
        self.assertEqual(start_delta, end_delta)
        self.assertGreater(start_delta[0], 0)

    def test_ctrl_click_toggles_node_selection(self):
        self.studio.update()
        self.studio.refresh()
        start = self.node("start")
        end = self.node("end")
        self.studio.selected = start
        x = int(self.studio.to_screen(end.x + 30))
        y = int(self.studio.to_screen(end.y + 20))
        ctrl_click = type("Event", (), {"x": x, "y": y, "state": 0x0004})()
        self.studio.on_canvas_press(ctrl_click)
        self.assertEqual(self.studio.selected_ids, {start.node_id, end.node_id})
        self.studio.refresh()
        self.studio.on_canvas_press(ctrl_click)
        self.assertEqual(self.studio.selected_ids, {start.node_id})

    def test_group_delete_removes_all_selected(self):
        self.studio.selected = self.node("start")
        self.studio.add_node("delay")
        self.studio.add_node("click")
        delay = next(node for node in self.studio.nodes if node.node_type == "delay")
        click = next(node for node in self.studio.nodes if node.node_type == "click")
        self.studio.doc.selected_ids = {delay.node_id, click.node_id}
        self.studio.doc.selected = delay
        self.studio.delete_selected()
        types = [node.node_type for node in self.studio.nodes]
        self.assertEqual(sorted(types), ["end", "start"])
        self.studio.undo()
        self.assertEqual(len(self.studio.nodes), 4)

    def test_group_duplicate_preserves_internal_edges(self):
        self.studio.selected = self.node("start")
        self.studio.add_node("delay")
        delay = self.studio.selected
        self.studio.add_node("click")
        click = self.studio.selected
        self.assertTrue(
            any(edge["from"] == delay.node_id and edge["to"] == click.node_id for edge in self.studio.doc.edges)
        )
        self.studio.doc.selected_ids = {delay.node_id, click.node_id}
        self.studio.doc.selected = delay
        self.studio.duplicate_selected()
        self.assertEqual(len([n for n in self.studio.nodes if n.node_type == "delay"]), 2)
        self.assertEqual(len([n for n in self.studio.nodes if n.node_type == "click"]), 2)
        clones = self.studio.selection_nodes()
        self.assertEqual(len(clones), 2)
        clone_ids = {node.node_id for node in clones}
        internal = [
            edge
            for edge in self.studio.doc.edges
            if edge["from"] in clone_ids and edge["to"] in clone_ids
        ]
        self.assertEqual(len(internal), 1)

    def test_select_all_shortcut_selects_every_node(self):
        self.studio.add_node("delay")
        self.assertEqual(self.studio.on_select_all(), "break")
        self.assertEqual(len(self.studio.selected_ids), len(self.studio.nodes))

    def test_undo_and_redo_restore_deleted_node(self):
        self.studio.selected = self.node("start")
        self.studio.add_node("delay")
        delay_id = self.studio.selected.node_id

        self.studio.delete_selected()
        self.assertIsNone(self.studio.node_by_id(delay_id))

        self.studio.undo()
        self.assertIsNotNone(self.studio.node_by_id(delay_id))

        self.studio.redo()
        self.assertIsNone(self.studio.node_by_id(delay_id))

    def test_key_lookup_normalizes_control_aliases(self):
        self.assertEqual(app.WindowsInput.key_to_vk("control"), app.WindowsInput.VK["ctrl"])
        self.assertEqual(app.WindowsInput.key_to_vk("Key.ctrl_l"), app.WindowsInput.VK["ctrl"])


if __name__ == "__main__":
    unittest.main()
