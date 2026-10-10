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

"""Light theme tests."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPixmap, QStandardItem
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem

from litextractor.ui.molecule_table import StructureDelegate
from litextractor.ui.theme import DETAIL_PANEL_STYLESHEET, apply_light_theme, light_palette


def test_light_palette_is_light():
    palette = light_palette()
    assert palette.color(QPalette.Window).lightness() > 200
    assert palette.color(QPalette.Base) == QColor("#ffffff")


def test_apply_light_theme_sets_palette(qapp):
    apply_light_theme(qapp)
    assert qapp.palette().color(QPalette.Window) == light_palette().color(QPalette.Window)


def test_detail_crop_preview_has_white_background():
    assert "QLabel#CropPreview" in DETAIL_PANEL_STYLESHEET
    assert "background-color: #ffffff;" in DETAIL_PANEL_STYLESHEET


def test_requirements_include_easyocr():
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    assert "easyocr" in requirements.read_text(encoding="utf-8")


def test_structure_delegate_paints_palette_base_background(qapp):
    model = QStandardItemModel()
    item = QStandardItem("x")
    pix = QPixmap(20, 20)
    pix.fill(QColor(0, 255, 0))
    item.setData(pix, Qt.DecorationRole)
    model.setItem(0, 0, item)

    img = QImage(80, 80, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 80, 80)
    opt.palette = light_palette()
    opt.font = qapp.font()
    StructureDelegate().paint(painter, opt, model.index(0, 0))
    painter.end()

    assert img.pixelColor(0, 0) == QColor("#ffffff")
