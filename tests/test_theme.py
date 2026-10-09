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

"""Fusion theme apply smoke tests (same palettes as MolManager)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPalette

from patentextractor.ui.theme import (
    THEME_DARK,
    THEME_GROOVY,
    THEME_LIGHT,
    apply_application_theme,
    current_theme_name,
    palette_for_theme,
)


def test_light_and_dark_palettes_differ(qapp):  # noqa: ARG001
    light = palette_for_theme(THEME_LIGHT)
    dark = palette_for_theme(THEME_DARK)
    assert light.color(QPalette.Window) != dark.color(QPalette.Window)


def test_light_palette_is_explicitly_light_and_requirements_include_easyocr():
    light = palette_for_theme(THEME_LIGHT)
    dark = palette_for_theme(THEME_DARK)
    assert light.color(QPalette.Window).lightness() > dark.color(QPalette.Window).lightness()
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    assert "easyocr" in requirements.read_text(encoding="utf-8")


def test_apply_dark_theme(qapp):
    name = apply_application_theme(qapp, THEME_DARK)
    assert name == THEME_DARK
    assert current_theme_name() == THEME_DARK
    apply_application_theme(qapp, THEME_LIGHT)


def test_apply_application_theme_updates_current_theme_without_qapp():
    apply_application_theme(None, THEME_DARK)
    assert current_theme_name() == THEME_DARK
    apply_application_theme(None, THEME_LIGHT)
    assert current_theme_name() == THEME_LIGHT


def test_theme_defaults_to_light_and_persists_user_choice(qapp):
    from PySide6.QtCore import QSettings

    settings = QSettings("PatentExtractor", "PatentExtractor")
    from patentextractor.ui.theme import load_saved_theme_name, save_theme_name

    original_value = settings.value("gui/theme")
    had_original_value = settings.contains("gui/theme")
    try:
        settings.remove("gui/theme")
        assert load_saved_theme_name() == THEME_LIGHT
        save_theme_name(THEME_DARK)
        assert load_saved_theme_name() == THEME_DARK
        save_theme_name(THEME_LIGHT)
        assert load_saved_theme_name() == THEME_LIGHT
    finally:
        if had_original_value:
            settings.setValue("gui/theme", original_value)
        else:
            settings.remove("gui/theme")


def test_gui_menu_selection_matches_saved_theme_on_startup(qapp):
    from PySide6.QtCore import QSettings

    settings = QSettings("PatentExtractor", "PatentExtractor")
    original_value = settings.value("gui/theme")
    had_original_value = settings.contains("gui/theme")
    settings.setValue("gui/theme", THEME_DARK)

    from patentextractor.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window._gui_theme == THEME_DARK
        assert window._act_theme_dark.isChecked() is True
        assert window._act_theme_light.isChecked() is False
    finally:
        window.close()
        if had_original_value:
            settings.setValue("gui/theme", original_value)
        else:
            settings.remove("gui/theme")


def test_groovy_is_randomized(qapp):  # noqa: ARG001
    import random

    a = palette_for_theme(THEME_GROOVY, rng=random.Random(1))
    b = palette_for_theme(THEME_GROOVY, rng=random.Random(2))
    assert a.color(QPalette.Window) != b.color(QPalette.Window)


def test_structure_delegate_uses_palette_background_in_dark_mode(qapp):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QStandardItem, QStandardItemModel
    from PySide6.QtWidgets import QStyleOptionViewItem

    from patentextractor.ui.molecule_table import StructureDelegate

    original_palette = qapp.palette()
    qapp.setPalette(palette_for_theme(THEME_DARK))
    model = QStandardItemModel()
    item = QStandardItem("x")
    pix = QPixmap(20, 20)
    pix.fill(QColor(0, 255, 0))
    item.setData(pix, Qt.DecorationRole)
    model.setItem(0, 0, item)

    delegate = StructureDelegate()
    img = QImage(80, 80, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 80, 80)
    opt.palette = qapp.palette()
    opt.font = qapp.font()
    delegate.paint(painter, opt, model.index(0, 0))
    painter.end()

    try:
        bg = qapp.palette().color(QPalette.Base)
        assert img.pixelColor(0, 0).red() == bg.red()
        assert img.pixelColor(0, 0).green() == bg.green()
        assert img.pixelColor(0, 0).blue() == bg.blue()
    finally:
        qapp.setPalette(original_palette)
