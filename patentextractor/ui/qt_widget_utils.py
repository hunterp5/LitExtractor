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

"""Small Qt widget helpers shared across dialogs (keep dependency-free beyond PySide6)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTextEdit, QWidget


def monospace_text_font() -> QFont:
    f = QFont("Consolas")
    if not f.exactMatch():
        f = QFont("Courier New")
    f.setStyleHint(QFont.Monospace)
    return f


def apply_monospace_to_text_edit(w: QTextEdit) -> None:
    w.setFont(monospace_text_font())


def make_window_minimizable(widget: QWidget) -> None:
    """Add minimize and maximize buttons to a secondary top-level window (e.g. ``QDialog``)."""
    flags = widget.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)
