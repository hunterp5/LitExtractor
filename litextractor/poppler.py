# This file is part of LitExtractor.
# Copyright (C) 2026 Hunter Picard
#
# LitExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# LitExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with LitExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""Find Poppler (pdftoppm, pdfinfo) when it is installed but not on PATH.

pdf2image runs Poppler's command-line tools by name. They are often installed where a shell
finds them but the app does not: in the conda environment a venv was created from (not
activated), or in Homebrew's folder when the app is started from the Dock or an IDE, which do
not read the shell's PATH. The first folder holding both tools is put at the front of PATH.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOLS = ("pdftoppm", "pdfinfo")


def _candidate_folders() -> list[Path]:
    prefixes = [sys.prefix, sys.base_prefix, os.environ.get("CONDA_PREFIX", "")]
    folders: list[Path] = []
    for prefix in filter(None, prefixes):
        folders += [Path(prefix) / "bin", Path(prefix) / "Library" / "bin"]
    folders += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/local/bin")]
    return folders


def _has_tools(folder: Path) -> bool:
    suffix = ".exe" if sys.platform == "win32" else ""
    return all((folder / f"{tool}{suffix}").is_file() for tool in _TOOLS)


def ensure_poppler_on_path(folders: list[Path] | None = None) -> Path | None:
    """Make Poppler's tools findable; return the folder added to PATH, or None.

    Nothing changes when the tools are already on PATH or cannot be found anywhere.
    """
    if all(shutil.which(tool) for tool in _TOOLS):
        return None
    for folder in folders if folders is not None else _candidate_folders():
        if _has_tools(folder):
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            logger.info("Using Poppler from %s", folder)
            return folder
    logger.warning("Poppler (pdftoppm, pdfinfo) was not found; PDF pages cannot be rendered.")
    return None


def poppler_available() -> bool:
    """True when Poppler's tools can be run."""
    return all(shutil.which(tool) for tool in _TOOLS)
