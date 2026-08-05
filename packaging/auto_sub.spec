# PyInstaller spec for the portable Windows build.
#
# Build with:  pyinstaller packaging/auto_sub.spec --noconfirm
# Output:      dist/auto_sub/  (onedir — zip this whole folder and hand it over)
#
# onedir, not onefile: onefile unpacks ~400 MB to a temp dir on every launch,
# which makes startup slow and trips antivirus far more often.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

# The bundled Arabic font — libass gets pointed at this via fontsdir.
datas += [("../auto_sub/assets", "auto_sub/assets")]

# faster-whisper ships the Silero VAD ONNX model as package data; vad_filter=True
# fails without it.
datas += collect_data_files("faster_whisper")

# CTranslate2 and onnxruntime carry native libraries PyInstaller does not find
# by following imports alone.
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("av")

hiddenimports += [
    "ctranslate2",
    "onnxruntime",
    "tokenizers",
    "av",
    "huggingface_hub",
]

# ffmpeg is fetched by the CI workflow into packaging/ffmpeg/ (exes + their DLLs).
# core/burn.py looks for an `ffmpeg` folder next to the executable.
#
# These go in `datas`, NOT `binaries`: PyInstaller dependency-scans everything in
# `binaries` and copies each DLL a second time into the bundle root, which cost
# ~130 MB of pure duplication. `datas` is copied verbatim. ffmpeg.exe finds its
# own DLLs because Windows resolves them from the executable's directory.
import os
_ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "ffmpeg")
if os.path.isdir(_ffmpeg_dir):
    for name in os.listdir(_ffmpeg_dir):
        datas += [(os.path.join(_ffmpeg_dir, name), "ffmpeg")]


a = Analysis(
    ["../auto_sub/__main__.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Keep the bundle down: these are pulled in transitively but never used.
    excludes=[
        "torch",
        "ultralytics",
        "matplotlib",
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick3D",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="auto_sub",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # no terminal window; output goes to the log file
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="auto_sub",
)
