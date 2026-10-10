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

"""Settings dialog to change application-wide and table font sizes (live, theme-safe)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from ..theme import DEFAULT_FONT_PT, MAX_FONT_PT, MIN_FONT_PT


class FontSettingsDialog(QDialog):
    """Pick application-wide and table font sizes; emits preview signals while adjusting."""

    app_font_size_previewed = Signal(int)
    table_font_size_previewed = Signal(int)

    def __init__(self, current_app_pt: int, current_table_pt: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Font")
        self.setMinimumWidth(340)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._app_spin = self._make_spin(current_app_pt)
        self._app_spin.valueChanged.connect(lambda pt: self.app_font_size_previewed.emit(int(pt)))
        form.addRow("Application font size:", self._app_spin)

        self._table_spin = self._make_spin(current_table_pt)
        self._table_spin.valueChanged.connect(
            lambda pt: self.table_font_size_previewed.emit(int(pt))
        )
        form.addRow("Table font size:", self._table_spin)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_default)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        make_window_minimizable(self)

    @staticmethod
    def _make_spin(current_pt: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(MIN_FONT_PT, MAX_FONT_PT)
        spin.setSuffix(" pt")
        spin.setValue(max(MIN_FONT_PT, min(MAX_FONT_PT, int(current_pt or DEFAULT_FONT_PT))))
        return spin

    def _reset_default(self) -> None:
        self._app_spin.setValue(DEFAULT_FONT_PT)
        self._table_spin.setValue(DEFAULT_FONT_PT)

    def selected_app_point_size(self) -> int:
        return int(self._app_spin.value())

    def selected_table_point_size(self) -> int:
        return int(self._table_spin.value())
