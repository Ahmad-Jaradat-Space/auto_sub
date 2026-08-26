from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _log_path() -> Path:
    """Where the diagnostic log goes.

    The packaged Windows build runs windowed, so stdout/stderr have nowhere to
    go — without this, the debugging breadcrumbs described in CLAUDE.md vanish
    and there is no way to help a user who says "it didn't work".
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        d = base / "auto_sub"
    else:
        d = Path(tempfile.gettempdir())
    d.mkdir(parents=True, exist_ok=True)
    return d / "auto_sub.log"


def _redirect_output() -> None:
    if sys.stderr is not None and sys.stderr.isatty():
        return  # running from a terminal: keep the output visible there
    try:
        f = open(_log_path(), "w", encoding="utf-8", buffering=1)
    except OSError:
        # Locked-down or redirected profile. Leaving them as None is not safe:
        # this build prints diagnostics on the Burn path, and print() to a None
        # stream raises. Swallow the output instead of crashing the app.
        f = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stderr = f


def main() -> int:
    _redirect_output()

    from PySide6.QtWidgets import QApplication
    from auto_sub.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("auto_sub")
    app.setOrganizationName("auto_sub")
    w = MainWindow()
    w.show()

    # CI launch test: build the real window, then quit with a real exit code.
    # Checking "is the process still alive" is not enough — PyInstaller's crash
    # dialog blocks waiting for a click, so a crashed build looks alive forever.
    if os.environ.get("AUTO_SUB_SMOKE"):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(3000, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
