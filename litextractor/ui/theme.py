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

"""The application's single light theme."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#eef0f4"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#141414"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#eceff4"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#2e67c8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4077f4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#b7bec7"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#767e88"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#3f4954"))
    disabled = QColor("#949ca8")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    return palette


EXTRACT_PANEL_STYLESHEET = """
QFrame#ExtractPanel {
    background-color: palette(window);
    border-right: 1px solid palette(mid);
}
"""

DETAIL_PANEL_STYLESHEET = """
QFrame#DetailPanel {
    background-color: palette(window);
    border-left: 1px solid palette(mid);
}
QFrame#DetailCard {
    background-color: palette(base);
    border: 1px solid palette(mid);
    border-radius: 8px;
}
QLabel#DetailCardTitle {
    color: palette(windowtext);
    font-weight: 600;
}
QLabel#DetailFieldName {
    color: palette(mid);
}
QLabel#DetailFieldValue {
    color: palette(windowtext);
}
QLabel#CropPreview {
    background-color: #ffffff;
    border-radius: 6px;
}
"""


def apply_light_theme(app: QApplication) -> None:
    """Use the Fusion style with the light palette, regardless of the OS color scheme."""
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(light_palette())
