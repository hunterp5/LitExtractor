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

"""Application logging setup and uncaught-exception reporting."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LOG_FILE_NAME = "patentextractor.log"

logger = logging.getLogger(__name__)

_active_log_file: Path | None = None


def active_log_file() -> Path | None:
    """Path to the session log file, if file logging was configured."""
    return _active_log_file


def default_log_dir() -> Path:
    """Platform user-data directory for PatentExtractor log files."""
    override = (os.environ.get("PATENTEXTRACTOR_LOG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PatentExtractor" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "PatentExtractor"
    xdg = (os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "patentextractor" / "logs"
    return Path.home() / ".local" / "state" / "patentextractor" / "logs"


def configure_app_logging() -> Path | None:
    """Configure root logging: console always; rotating file under the user log dir."""
    global _active_log_file
    level_name = (os.environ.get("PATENTEXTRACTOR_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root.handlers
    ):
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)

    log_to_file = (os.environ.get("PATENTEXTRACTOR_LOG_TO_FILE") or "1").strip() != "0"
    if not log_to_file:
        return None

    log_dir = default_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / _LOG_FILE_NAME
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
        _active_log_file = log_path
        return log_path
    except OSError:
        logger.warning("Could not attach file log handler", exc_info=True)
        return None


def install_crash_excepthook(*, log_path: Path | None = None) -> None:
    """Show a Qt dialog for uncaught exceptions when a QApplication exists."""
    previous = sys.excepthook

    def _hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.critical("Uncaught exception:\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app is not None:
                loc = f"\n\nLog file:\n{log_path}" if log_path else ""
                QMessageBox.critical(
                    None,
                    "PatentExtractor crashed",
                    f"{exc_type.__name__}: {exc}{loc}\n\nSee the log for the full traceback.",
                )
        except Exception:
            logger.debug("Crash dialog failed", exc_info=True)
        previous(exc_type, exc, tb)

    sys.excepthook = _hook
