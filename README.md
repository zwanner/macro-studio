# Macro Studio

<img width="1564" height="1246" alt="image" src="https://github.com/user-attachments/assets/a965d290-4f7a-43c5-aaf3-e79eefa9b5ce" />

Macro Studio is a Windows desktop macro builder with:

- A full Tkinter GUI
- A clean multi-panel editor with script tabs
- Macro recording, saving, loading, and replay
- A node canvas for building macros by dropping actions into a flow
- Built-in nodes for delays, mouse actions, keyboard shortcuts, clipboard actions, text entry, app launching, and recorded events
- App settings for record, play, and stop hotkeys
- Recent scripts from the File menu
- Loop and counter nodes for repeated workflows
- Data-driven paste from clipboard, inline rows copied from Excel, or CSV/TSV files
- Hover tooltips and inspector descriptions for node behavior and settings
- Explicit graph connections with Start and End workflow nodes
- Workflow helper controls for connecting, unlinking, auto-linking, and auto-organizing nodes

## Setup

### Download Release

Download `Macro-Studio-v0.1.0-windows-x64.zip` from the GitHub release, extract the folder, and run:

```text
Macro Studio.exe
```

Keep the extracted `_internal` folder next to the executable. The release uses PyInstaller's folder-based build for faster startup and easier troubleshooting.

Windows may show a SmartScreen warning because the app is not code-signed yet.

### Run From Source

```powershell
python -m pip install -r requirements.txt
python app.py
```

The app still opens without `pynput`, but global recording is disabled until the dependency is installed.

Macro files save as `.macro` by default. Older `.macro.json` and `.json` files still load because the file data remains JSON.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Build Windows App

```powershell
.\build.ps1
```

The build script installs runtime/build requirements, creates `assets\macro-logo.ico` from the high-resolution logo, runs tests, and packages the app with PyInstaller. The packaged executable is written to:

```powershell
dist\Macro Studio\Macro Studio.exe
```

## Default hotkeys

- Record or stop recording: `Ctrl + Shift + R`
- Play active script: `Ctrl + Shift + P`
- Stop playback or recording: `Ctrl + Shift + X`

You can change these from **Settings**. Hotkeys use pynput syntax such as `<ctrl>+<shift>+r`.

## Safety

Macro playback controls your real mouse and keyboard. Use the countdown and test macros in a harmless window first.

This project is intended for personal workflow automation. Do not use it to automate systems you do not own or have permission to control.

## Data Paste

Use a **Paste** node with `source` set to:

- `clipboard` to paste the current clipboard
- `data` to paste one row at a time from the node's multi-line data field
- `file` to paste one row at a time from a `.csv` or `.tsv` file path

When using loops, each pass advances to the next paste item. Text fields can include placeholders like `{iteration}` or `{counter}`.

## Workflow Graph

New scripts include **Start** and **End** nodes. Use **Connect From** on a selected source node, select another node, then use **Connect To** to create an execution edge. You can also drag from a node's bottom output dot to another node's top input dot. Adding a node while another node is selected automatically links the selected node to the new node. **Auto Link** rebuilds a simple Start-to-End flow using top-to-bottom node order, and **View > Auto Organize Nodes** lays the active script into a clean vertical workflow.

## License

MIT
