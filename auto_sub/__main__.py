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
        return
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
