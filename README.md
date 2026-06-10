# Macro Studio

<img width="1894" height="1245" alt="image" src="https://github.com/user-attachments/assets/6fffe6e8-fdbd-4209-85e4-9910a6babec3" />

Macro Studio is a Windows desktop automation tool for recording, editing, and replaying mouse and keyboard workflows. It combines a traditional macro recorder with a visual node graph so simple click-and-type tasks can grow into repeatable workflow automations without writing code.

The project is currently focused on Windows automation and ships as both a Python source app and a PyInstaller-packaged Windows executable.

## Highlights

- Record mouse clicks, mouse paths, scrolls, and keyboard actions.
- Save and load scripts as `.macro` files.
- Build workflows visually with Start, End, action, timing, clipboard, and loop nodes.
- Use explicit graph connections by dragging between node ports.
- Edit selected node settings in the inspector.
- Work with multiple scripts through tabs.
- Use global hotkeys for record, play, and stop.
- Paste data from the clipboard, inline rows, CSV files, or TSV files.
- Loop workflows by count or until a stop hotkey is pressed.
- Use nested Loop Frame nodes to repeat only part of a workflow.
- Save click positions, mouse positions, and clipboard values as variables for later nodes.
- Use placeholders and simple math in coordinate fields, such as `{first_click_x}+({loop_index}*50)`.
- Type text exactly, including spaces, capitalization, punctuation, tabs, and newlines.
- Undo and redo graph edits with `Ctrl+Z` and `Ctrl+Y`.
- Auto-organize node graphs, including loop frames that resize around child nodes.

## Common Use Cases

- Repeating UI clicks with a changing paste value from a CSV file.
- Copying values from one app and appending them to a dataset or text file.
- Waiting for a manual click, saving that click position, then returning to it later.
- Running a workflow a fixed number of times.
- Running a workflow until a stop hotkey is pressed.
- Building nested loops, such as “for each selected item, paste four rows of data.”
- Recording rough actions, then cleaning them into a more readable node workflow.

## Download And Install

Download the latest Windows release from the GitHub Releases page:

[Macro Studio Releases](https://github.com/zwanner/macro-studio/releases)

For v0.2.1, download:

```text
Macro-Studio-v0.2.1-windows.zip
```

Extract the zip and run:

```text
Macro Studio.exe
```

Keep the extracted `_internal` folder next to the executable. Macro Studio currently uses PyInstaller's folder-based build because it starts faster and is easier to troubleshoot than a single-file executable.

Windows SmartScreen may warn that the app is from an unknown publisher because the executable is not code-signed yet.

## Run From Source

Requirements:

- Windows 10 or Windows 11
- Python 3.11 or newer recommended
- `pip`

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the app:

```powershell
python app.py
```

The app can open without `pynput`, but recording and global hotkeys require it. The packaged release includes the required runtime dependencies.

## Build From Source

Install runtime and build dependencies, run tests, and package the app:

```powershell
.\build.ps1
```

The build output is written to:

```text
dist\Macro Studio\Macro Studio.exe
```

To skip tests during a local build:

```powershell
.\build.ps1 -SkipTests
```

To create a release zip manually after building:

```powershell
Compress-Archive -Path "dist\Macro Studio" -DestinationPath "dist\Macro-Studio-v0.2.1-windows.zip" -Force
```

## Test Suite

Run all regression tests:

```powershell
python -m unittest discover -s tests -v
```

The test suite covers graph behavior, persistence, node execution helpers, recording cleanup, hotkey normalization, data paste behavior, loop frames, undo/redo, and UI regression checks.

## Workflow Graph

Every script starts with a Start node and an End node. Nodes are connected by edges:

- Drag from a node's bottom output port to another node's top input port.
- Add a node while another node is selected to auto-connect from the selected node.
- Use inspector actions such as Auto Link, Unlink, Duplicate, Delete, Move Up, Move Down, and Clear.
- Use `View > Auto Organize Nodes` to lay out the current workflow.

The graph supports nested visual containers through Loop Frame nodes. Nodes placed inside a Loop Frame run as that frame's body. A smaller Loop Frame inside a larger Loop Frame becomes a nested loop.

## Node Categories

### Flow

- Start: workflow entry point.
- End: workflow exit point.
- Loop Script: repeats the whole script by count or until a hotkey.
- Loop Frame: repeats only nodes visually placed inside the frame.
- Counter: increments a named counter for use in placeholders.
- Note: adds documentation to the graph and is ignored during playback.

### Timing

- Global Delay: adds a delay between playback nodes.
- Delay: pauses for a fixed number of seconds.
- Wait Window: waits for an active window title match.
- Wait Hotkey: pauses until a hotkey is pressed.
- Wait Click: pauses for a manual click and can save the click position.

### Mouse

- Mouse Click: moves to coordinates and clicks.
- Mouse Move: moves to coordinates without clicking.
- Save Mouse Position: stores the current mouse position in variables.
- Scroll: scrolls up or down.

### Keyboard

- Key Tap: taps a single key.
- Hotkey: presses a key combination.
- Type Text: types exact text, including whitespace, punctuation, capitalization, tabs, and newlines.

### Clipboard

- Copy: sends `Ctrl+C`.
- Cut: sends `Ctrl+X`.
- Paste: pastes from clipboard, inline data, CSV, or TSV.
- Set Clipboard: sets clipboard text.
- Save Clipboard: saves clipboard text to a variable, dataset, or file.

### System

- Launch App: starts an app or shell command.

## Data Paste

The Paste node supports three sources:

- `clipboard`: paste the current clipboard.
- `data`: paste one row at a time from the node's multi-line data field.
- `file`: paste one row at a time from a CSV or TSV file.

Paste nodes keep their own cursor during playback. This means a Paste-from-file node inside a 4x nested loop continues through the file across outer loop iterations:

```text
outer pass 1: rows 1-4
outer pass 2: rows 5-8
outer pass 3: rows 9-12
```

The `column` field is 1-based. Set it to `1` for the first CSV/TSV column, `2` for the second, and so on.

## Variables And Placeholders

Several nodes can save values into the playback context:

- Wait Click can save `{first_click_x}`, `{first_click_y}`, and `{first_click_button}`.
- Save Mouse Position can save `{mouse_x}` and `{mouse_y}` or another variable prefix.
- Counter can expose `{counter}` or another named counter.
- Save Clipboard can expose a variable, dataset count, and dataset last value.
- Loops expose `{iteration}`, `{loop_index}`, and `{loop_count}`.

Text fields and coordinate fields can use placeholders:

```text
{first_click_x}
{first_click_y}
{iteration}
{loop_index}
{loop_count}
{items_count}
{items_last}
```

Coordinate fields also support simple math:

```text
x: {first_click_x}+({loop_index}*50)
y: {first_click_y}-10
```

This is useful for moving through repeated rows, columns, or offset targets.

## Hotkeys

Default hotkeys:

- Record or stop recording: `Ctrl + Shift + R`
- Play active script: `Ctrl + Shift + P`
- Stop playback or recording: `Ctrl + Shift + X`

You can change hotkeys from Settings.

Internally hotkeys are normalized to `pynput` syntax. These are equivalent:

```text
shift+ctrl+x
ctrl+shift+x
<ctrl>+<shift>+x
```

## File Format

Macro Studio saves scripts as `.macro` files. The contents are JSON so files can still be inspected, backed up, versioned, and repaired manually if needed.

Older `.macro.json` and `.json` files still load for compatibility.

## Project Structure

```text
app.py                  Main Tkinter window, graph editor, and persistence
playback.py             Playback engine (runs on a background thread)
recorder.py             Global mouse/keyboard recording and cleanup
model.py                Node and document model, node type definitions
render.py               Drawing helpers, sprite cache, themed widgets
winput.py               Windows input, clipboard, and display APIs (ctypes)
hotkeys.py              Hotkey parsing and normalization
theme.py                Colors, fonts, and DPI-aware scaling
config.py               Paths, file types, and default settings
tests/test_app.py        Regression tests
assets/                 Logos, icons, and interface screenshot assets
build.ps1               Windows build script
MacroStudio.spec        PyInstaller configuration
requirements.txt        Runtime dependencies
requirements-build.txt  Packaging dependencies
CHANGELOG.md            Release notes
LICENSE                 Non-commercial source license
```

## Framework And Architecture

Macro Studio is built with:

- Python
- Tkinter and ttk for the desktop GUI
- Pillow for anti-aliased graph and icon rendering
- pynput for global recording and hotkey listeners
- Windows `SendInput` and cursor APIs for playback
- PyInstaller for Windows packaging
- unittest for regression testing

The app is organized into focused modules. The core pieces are:

- `MacroDocument` / `MacroNode` (`model.py`): an open script tab with nodes, edges, dirty state, and undo/redo history; typed graph nodes with stable IDs.
- `MacroStudio` (`app.py`): the main Tk window, graph editor, inspector, tabs, and persistence layer.
- `PlaybackMixin` (`playback.py`): the workflow execution engine. Playback runs on a background daemon thread so the UI stays responsive; UI updates are queued back to the main thread, and the clipboard is accessed through the Win32 API so worker code never touches Tk.
- `RecorderMixin` (`recorder.py`): global event capture, including post-recording cleanup that merges typed keystroke runs into Type Text nodes.
- `WindowsInput` (`winput.py`): low-level Windows input helpers for mouse, keyboard, Unicode text, and thread-safe clipboard access.

The graph renderer has two modes:

- Normal render: anti-aliased, polished rendering for idle editing.
- Fast render: simplified rendering while dragging nodes or resizing loop frames.

Anti-aliased sprites (node bodies, ports, edge curves, tabs, icons) are cached by geometry and color, so repeated refreshes reuse finished images instead of re-rendering through Pillow. During playback, only a highlight outline moves between nodes; the canvas is not redrawn per executed node.

## Safety Notes

Macro playback controls your real mouse and keyboard. Test scripts in a harmless window first, keep the stop hotkey available, and avoid running new workflows against important data until you have watched them succeed.

Macro Studio is intended for personal workflow automation. Do not use it to automate systems you do not own or do not have permission to control.

## Known Limitations

- Windows is the supported target platform.
- The app is not code-signed yet.
- Very large graphs may still need further rendering optimization.
- The UI is currently Tkinter-based; a future migration to a modern UI stack remains possible.

## License

Macro Studio is source-available for non-commercial use. You may use, copy, modify, and share the software for non-commercial purposes, but you may not sell it, redistribute it for payment, or include it in a paid product or paid service without permission.

See [LICENSE](LICENSE) for the full terms.
