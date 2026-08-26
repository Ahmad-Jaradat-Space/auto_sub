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

# reframe.py loads cv2.data.haarcascades + "haarcascade_frontalface_default.xml".
# The stock cv2 hook collects loader config, not cv2/data/*.xml, so the default
# "Vertical 9:16" export died with "OpenCV could not load face cascade".
datas += collect_data_files("cv2", includes=["data/*.xml"])

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

# NOTE: ffmpeg is deliberately NOT listed here. The workflow copies it into
# dist/auto_sub/ffmpeg/ *after* this spec runs.
#
# Handing it to PyInstaller — via `binaries` or `datas`, it makes no difference —
# triggers "binary vs. data reclassification", which dependency-scans the DLLs and
# copies each one a second time into the bundle root: ~130 MB of pure duplication.
# core/burn.py::_bundle_dirs() looks for `ffmpeg/` next to the exe, so a plain
# post-build copy is both smaller and simpler.


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
