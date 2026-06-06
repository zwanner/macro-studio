# Macro Studio

Macro Studio is a Windows desktop macro builder with:

- A full Tkinter GUI
- A cleaner multi-panel editor with script tabs
- Macro recording, saving, loading, and replay
- A Scratch-like node canvas for building macros by dropping actions into a flow
- Built-in nodes for delays, mouse actions, keyboard shortcuts, clipboard actions, text entry, app launching, and recorded events
- App settings for record, play, and stop hotkeys
- A recent scripts dropdown
- Loop and counter nodes for repeated workflows
- Data-driven paste from clipboard, inline rows copied from Excel, or CSV/TSV files
- Grouped recorded mouse movement paths instead of one node per tiny movement
- Hover tooltips and inspector descriptions for node behavior and settings
- Explicit graph connections with Start and End workflow nodes
- Workflow helper controls for connecting, unlinking, and auto-linking nodes

## Setup

```powershell
python -m pip install -r requirements.txt
python app.py
```

The app still opens without `pynput`, but global recording is disabled until the dependency is installed.

## Default hotkeys

- Record or stop recording: `Ctrl + Shift + R`
- Play active script: `Ctrl + Shift + P`
- Stop playback or recording: `Ctrl + Shift + X`

You can change these from **Settings**. Hotkeys use pynput syntax such as `<ctrl>+<shift>+r`.

## Safety

Macro playback controls your real mouse and keyboard. Use the countdown and test macros in a harmless window first.

## Data Paste

Use a **Paste** node with `source` set to:

- `clipboard` to paste the current clipboard
- `data` to paste one row at a time from the node's multi-line data field
- `file` to paste one row at a time from a `.csv` or `.tsv` file path

When using loops, each pass advances to the next paste item. Text fields can include placeholders like `{iteration}` or `{counter}`.

## Workflow Graph

New scripts include **Start** and **End** nodes. Use **Connect From** on a selected source node, select another node, then use **Connect To** to create an execution edge. You can also drag from a node's bottom output dot to another node's top input dot. Adding a node while another node is selected automatically links the selected node to the new node. **Auto Link** rebuilds a simple Start-to-End flow using top-to-bottom node order.
