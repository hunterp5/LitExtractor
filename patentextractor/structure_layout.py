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

"""Structure render sizing, row heights, and persisted layout state."""

from __future__ import annotations

from PySide6.QtCore import QSettings

DEFAULT_STRUCTURE_WIDTH = 242
DEFAULT_STRUCTURE_HEIGHT = 202
DEFAULT_STRUCTURE_ROW_HEIGHT = 212
STRUCTURE_ROW_HEIGHT_PADDING = DEFAULT_STRUCTURE_ROW_HEIGHT - DEFAULT_STRUCTURE_HEIGHT

MIN_STRUCTURE_WIDTH = 80
MAX_STRUCTURE_WIDTH = 640
MIN_STRUCTURE_HEIGHT = 60
MAX_STRUCTURE_HEIGHT = 540

STRUCTURE_WIDTH = DEFAULT_STRUCTURE_WIDTH
STRUCTURE_HEIGHT = DEFAULT_STRUCTURE_HEIGHT
STRUCTURE_ROW_HEIGHT = DEFAULT_STRUCTURE_ROW_HEIGHT

STRUCTURE_BOND_LINE_WIDTH = 1.0
STRUCTURE_COLUMN_HORIZONTAL_PADDING = 28

DETAIL_STRUCTURE_WIDTH = 360
DETAIL_STRUCTURE_HEIGHT = 280

_SETTINGS_ORG = "PatentExtractor"
_SETTINGS_APP = "PatentExtractor"
_SETTINGS_KEY_STRUCTURE_WIDTH = "structure/depict_width"
_SETTINGS_KEY_STRUCTURE_HEIGHT = "structure/depict_height"

_RUNTIME_WIDTH = DEFAULT_STRUCTURE_WIDTH
_RUNTIME_HEIGHT = DEFAULT_STRUCTURE_HEIGHT

# Backwards-compatible aliases for older naming.
DEFAULT_STRUCTURE_DEPICT_WIDTH = DEFAULT_STRUCTURE_WIDTH
DEFAULT_STRUCTURE_DEPICT_HEIGHT = DEFAULT_STRUCTURE_HEIGHT
DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT = DEFAULT_STRUCTURE_ROW_HEIGHT
STRUCTURE_DEPICT_BOND_LINE_WIDTH = STRUCTURE_BOND_LINE_WIDTH
STRUCTURE_DEPICT_WIDTH = STRUCTURE_WIDTH
STRUCTURE_DEPICT_HEIGHT = STRUCTURE_HEIGHT
STRUCTURE_ROW_DEFAULT_HEIGHT = STRUCTURE_ROW_HEIGHT


def _clamp_structure_width(width: int) -> int:
    return max(MIN_STRUCTURE_WIDTH, min(MAX_STRUCTURE_WIDTH, int(width)))


def _clamp_structure_height(height: int) -> int:
    return max(MIN_STRUCTURE_HEIGHT, min(MAX_STRUCTURE_HEIGHT, int(height)))


def structure_width() -> int:
    """Current Structure column depiction width in pixels."""
    return _RUNTIME_WIDTH


def structure_height() -> int:
    """Current Structure column depiction height in pixels."""
    return _RUNTIME_HEIGHT


def structure_row_height() -> int:
    """Default table row height for the Structure column."""
    return structure_height() + STRUCTURE_ROW_HEIGHT_PADDING


def structure_column_minimum_width(*, zoomed: bool = False) -> int:
    """Minimum Structure column width so the depiction is never clipped horizontally."""
    depict_w = structure_width() * (2 if zoomed else 1)
    return int(depict_w) + int(STRUCTURE_COLUMN_HORIZONTAL_PADDING)


# Legacy names retained for compatibility with existing code and tests.
def structure_depiict_width() -> int:
    return structure_width()


def structure_depiict_height() -> int:
    return structure_height()


def structure_row_default_height() -> int:
    return structure_row_height()


def load_saved_structure_size() -> tuple[int, int]:
    """Return saved depiction size, or defaults when unset."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    try:
        w = int(settings.value(_SETTINGS_KEY_STRUCTURE_WIDTH, 0))
    except (TypeError, ValueError):
        w = 0
    try:
        h = int(settings.value(_SETTINGS_KEY_STRUCTURE_HEIGHT, 0))
    except (TypeError, ValueError):
        h = 0
    if w <= 0 or h <= 0:
        return DEFAULT_STRUCTURE_WIDTH, DEFAULT_STRUCTURE_HEIGHT
    return _clamp_structure_width(w), _clamp_structure_height(h)


def load_saved_structure_depiict_size() -> tuple[int, int]:
    return load_saved_structure_size()


def set_structure_size(width: int, height: int, *, persist: bool = True) -> tuple[int, int]:
    """Apply depiction size for new renders and optionally persist to QSettings."""
    global _RUNTIME_WIDTH, _RUNTIME_HEIGHT
    w = _clamp_structure_width(width)
    h = _clamp_structure_height(height)
    _RUNTIME_WIDTH = w
    _RUNTIME_HEIGHT = h
    if persist:
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue(_SETTINGS_KEY_STRUCTURE_WIDTH, w)
        settings.setValue(_SETTINGS_KEY_STRUCTURE_HEIGHT, h)
    return w, h


def set_structure_depiict_size(width: int, height: int, *, persist: bool = True) -> tuple[int, int]:
    return set_structure_size(width, height, persist=persist)


def apply_structure_size(width: int, height: int, *, persist: bool = True) -> tuple[int, int]:
    return set_structure_size(width, height, persist=persist)


def apply_structure_depiict_size(width: int, height: int, *, persist: bool = True) -> tuple[int, int]:
    return set_structure_size(width, height, persist=persist)


def _load_runtime_structure_size_from_settings() -> None:
    w, h = load_saved_structure_size()
    set_structure_size(w, h, persist=False)


_load_runtime_structure_size_from_settings()
