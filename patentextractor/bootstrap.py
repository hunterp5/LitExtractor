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


def _prepare_qt_runtime() -> None:
    """Ensure Windows resolves the active venv's bundled Qt DLLs before any other Qt install."""
    if sys.platform != "win32":
        return
    try:
        venv_root = Path(sys.executable).resolve().parent.parent
        qt_dirs = [
            venv_root / "Lib" / "site-packages" / "PySide6",
            venv_root / "Lib" / "site-packages" / "PySide6" / "plugins" / "platforms",
        ]
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        for qt_dir in qt_dirs:
            if qt_dir.exists():
                qt_dir_str = str(qt_dir)
                if qt_dir_str not in path_entries:
                    os.environ["PATH"] = qt_dir_str + os.pathsep + os.environ.get("PATH", "")
                os.add_dll_directory(qt_dir_str)
    except Exception:
        pass


_prepare_qt_runtime()

from PySide6.QtWidgets import QApplication

from .app_logging import configure_app_logging, install_crash_excepthook
from .rdkit_env import configure_rdkit_for_desktop_app
from .ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    log_path = configure_app_logging()
    install_crash_excepthook(log_path=log_path)
    configure_rdkit_for_desktop_app()

    app = QApplication(argv)
    window = MainWindow()
    window.show()
    return app.exec()
