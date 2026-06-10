# Changelog

## Unreleased

- Moved macro playback to a background thread so the app window stays responsive during playback and no longer freezes on long waits.
- Reworked playback rendering: a lightweight highlight outline now tracks the active node instead of redrawing the whole canvas for every executed node.
- Added sprite caching for anti-aliased node, port, edge, tab, and icon rendering (roughly 14x faster full-canvas refresh on mid-size graphs).
- Fixed the record hotkey leaking ctrl/shift/r key nodes into the start of hotkey-started recordings.
- Recorded runs of plain typed keystrokes now merge into a single editable Type Text node after recording stops.
- The global play hotkey no longer opens a confirmation dialog, so it no longer steals focus from the target window; the countdown still applies.
- Playback now reads and writes the clipboard through the Win32 API, making clipboard nodes thread-safe and more reliable.
- Split the single-file app into focused modules (`model`, `playback`, `recorder`, `render`, `winput`, `hotkeys`, `theme`, `config`) with `app.py` as the UI layer.

## v0.2.1 - 2026-06-09

- Added nested Loop Frame workflow behavior with visual containment and frame-body playback.
- Added drag-resizing for Loop Frame nodes.
- Improved Auto Organize so loop frames organize and resize around child nodes.
- Added per-node Paste cursors so CSV/TSV data continues across nested loop iterations.
- Added `{loop_index}` and simple coordinate math for offset workflows.
- Added Undo and Redo with `Ctrl+Z` and `Ctrl+Y`.
- Improved Type Text so capitalization, punctuation, spaces, tabs, and newlines are typed exactly.
- Fixed playback stop hotkey behavior for normal non-loop scripts and long Type Text nodes.
- Fixed global hotkey normalization for loose hotkey formats like `shift+ctrl+x`.
- Improved graph drag performance with a fast interactive render path.
- Expanded README documentation with installation, build, node, workflow, and architecture details.

## v0.2.0 - 2026-06-09

- Added workflow capture nodes for waiting on a click, saving mouse position, and saving clipboard data.
- Expanded Save Clipboard with variable, dataset, and file append targets.
- Added Loop Script mode for fixed counts or running until a stop hotkey.
- Fixed high-DPI mouse playback coordinates while preserving usable UI scaling.
- Improved script tabs, close buttons, inspector action layout, icons, and graph node scaling.
- Added third-party notices for the icon styling attribution.

## v0.1.0 - 2026-06-08

- Added Windows packaging with PyInstaller.
- Added node-based workflow editor with Start and End nodes.
- Added record, save, load, and playback for mouse and keyboard macros.
- Added grouped recorded mouse movement paths.
- Added workflow nodes for loops, counters, delays, global delay, hotkeys, clipboard, data paste, app launch, and waits.
- Added `.macro` file extension while keeping `.macro.json` and `.json` loading compatibility.
- Added modern dark UI, script tabs, inspector editing, custom menu bar, and anti-aliased graph visuals.
- Added regression test suite.
