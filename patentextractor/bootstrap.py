# This file is part of PatentExtractor.
# Copyright (C) 2026 Hunter Picard
#
# PatentExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PatentExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PatentExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""Application bootstrap and Qt runtime initialization."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
_DLL_DIRECTORY_HANDLES: list[object] = []


def _prepare_qt_runtime() -> None:
    """Ensure Windows resolves the active venv's bundled Qt DLLs before any other Qt install."""
    if sys.platform != "win32":
        return
    try:
        venv_root = Path(sys.executable).resolve().parent.parent
    except (OSError, RuntimeError) as exc:
        logger.warning("Could not resolve the active Python environment for Qt DLL setup: %s", exc)
        return

    qt_dirs = [
        venv_root / "Lib" / "site-packages" / "PySide6",
        venv_root / "Lib" / "site-packages" / "PySide6" / "plugins" / "platforms",
    ]
    for qt_dir in qt_dirs:
        try:
            if not qt_dir.exists():
                continue
            qt_dir_str = str(qt_dir)
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
            if qt_dir_str not in path_entries:
                os.environ["PATH"] = qt_dir_str + os.pathsep + os.environ.get("PATH", "")
            handle = os.add_dll_directory(qt_dir_str)
        except (OSError, AttributeError) as exc:
            logger.warning("Could not register Qt DLL directory %s: %s", qt_dir, exc)
            continue
        _DLL_DIRECTORY_HANDLES.append(handle)


_prepare_qt_runtime()

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app_logging import configure_app_logging, install_crash_excepthook
from .ui.main_window import MainWindow
from .ui.theme import initialize_application_theme


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    log_path = configure_app_logging()
    install_crash_excepthook(log_path=log_path)
    app = QApplication(argv)
    initialize_application_theme(app)
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.start_cuda_probe)
    return app.exec()
