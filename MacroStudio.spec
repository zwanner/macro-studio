# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


block_cipher = None

hiddenimports = [
    "pynput._util.win32",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]

datas = [(str(path), "assets") for pattern in ("*.png", "*.ico") for path in Path("assets").glob(pattern)]

excludes = [
    "AppKit",
    "CoreFoundation",
    "HIServices",
    "Quartz",
    "Xlib",
    "evdev",
    "objc",
    "pynput._util.darwin",
    "pynput._util.uinput",
    "pynput._util.xorg",
    "pynput.keyboard._darwin",
    "pynput.keyboard._uinput",
    "pynput.keyboard._xorg",
    "pynput.mouse._darwin",
    "pynput.mouse._xorg",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Macro Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/macro-logo.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Macro Studio",
)
