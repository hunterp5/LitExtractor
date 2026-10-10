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

"""Pure rendering dimensions shared by drawing and Qt layout settings."""

from __future__ import annotations

DEFAULT_STRUCTURE_WIDTH = 242
DEFAULT_STRUCTURE_HEIGHT = 202
STRUCTURE_BOND_LINE_WIDTH = 1.0

_RUNTIME_WIDTH = DEFAULT_STRUCTURE_WIDTH
_RUNTIME_HEIGHT = DEFAULT_STRUCTURE_HEIGHT


def structure_width() -> int:
    """Current Structure column depiction width in pixels."""
    return _RUNTIME_WIDTH


def structure_height() -> int:
    """Current Structure column depiction height in pixels."""
    return _RUNTIME_HEIGHT


def _set_runtime_structure_size(width: int, height: int) -> None:
    """Update process-local depiction dimensions after layout settings are applied."""
    global _RUNTIME_WIDTH, _RUNTIME_HEIGHT
    _RUNTIME_WIDTH = int(width)
    _RUNTIME_HEIGHT = int(height)