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

"""Molecule table model tests."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem

from patentextractor.models import ExtractedMolecule
from patentextractor.structure_layout import (
    structure_column_minimum_width,
    structure_height,
    structure_row_height,
    structure_width,
)
from patentextractor.ui import molecule_table
from patentextractor.ui.molecule_table import (
    COL_PATENT_CROP,
    COL_STRUCTURE,
    MoleculeTableModel,
    MoleculeTableView,
    PatentCropDelegate,
    render_crop_pixmap,
)


def test_table_defers_and_caches_expensive_cell_values(qapp, monkeypatch):
    assert qapp is not None
    calls: dict[str, int] = {"structure": 0, "crop": 0, "quality": 0}

    def render_structure(_record):
        calls["structure"] += 1
        return QPixmap(10, 10)

    def decode_crop(_png):
        calls["crop"] += 1
        return QPixmap(10, 10)

    def quality_score(_record):
        calls["quality"] += 1
        return 0.75

    monkeypatch.setattr(molecule_table, "render_structure_pixmap", render_structure)
    monkeypatch.setattr(molecule_table, "pixmap_from_png", decode_crop)
    monkeypatch.setattr(molecule_table, "molecule_quality_score", quality_score)

    model = MoleculeTableModel()
    model.set_molecules(
        [
            ExtractedMolecule(smiles="CCO", crop_png=b"crop"),
            ExtractedMolecule(smiles="CCN", crop_png=b"crop"),
        ],
        already_prioritized=True,
    )
    assert calls == {"structure": 0, "crop": 0, "quality": 0}

    structure_index = model.index(0, COL_STRUCTURE)
    model.data(structure_index, Qt.DecorationRole)
    model.data(structure_index, Qt.DecorationRole)
    assert calls["structure"] == 1

    crop_index = model.index(0, COL_PATENT_CROP)
    model.data(crop_index, Qt.DecorationRole)
    model.data(crop_index, Qt.DecorationRole)
    assert calls["crop"] == 1

    quality_index = model.index(0, 6)
    assert model.data(quality_index, Qt.DisplayRole) == "0.750"
    assert model.data(quality_index, Qt.DisplayRole) == "0.750"
    assert calls["quality"] == 1

    model.set_molecules([ExtractedMolecule(smiles="CO")], already_prioritized=True)
    model.data(model.index(0, COL_STRUCTURE), Qt.DecorationRole)
    assert calls["structure"] == 2


def test_patent_crop_delegate_displays_consistent_aspect_preserving_thumbnails(qapp):
    view = MoleculeTableView()
    delegate = view.itemDelegateForColumn(COL_PATENT_CROP)
    assert isinstance(delegate, PatentCropDelegate)
    assert view.columnWidth(COL_PATENT_CROP) == structure_column_minimum_width()
    assert view.verticalHeader().defaultSectionSize() == structure_row_height()

    model = QStandardItemModel()
    landscape = QPixmap(200, 50)
    landscape.fill(QColor("red"))
    portrait = QPixmap(40, 100)
    portrait.fill(QColor("red"))
    rendered_crops = [render_crop_pixmap(pixmap) for pixmap in (landscape, portrait)]
    for pixmap in rendered_crops:
        item = QStandardItem()
        item.setData(pixmap, Qt.DecorationRole)
        model.appendRow(item)

    expected_bounds = tuple(
        (
            scaled.width(),
            scaled.height(),
        )
        for pixmap in (landscape, portrait)
        for scaled in [
            pixmap.scaled(
                structure_width(),
                structure_height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        ]
    )
    assert all(
        (pixmap.width(), pixmap.height()) == (structure_width(), structure_height())
        for pixmap in rendered_crops
    )
    for row, expected_size in enumerate(expected_bounds):
        image = QImage(
            view.columnWidth(COL_PATENT_CROP),
            structure_height() + 20,
            QImage.Format_ARGB32,
        )
        image.fill(QColor("white"))
        painter = QPainter(image)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, image.width(), image.height())
        option.palette = qapp.palette()
        option.font = qapp.font()
        delegate.paint(painter, option, model.index(row, 0))
        painter.end()

        red_pixels = [
            (x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y) == QColor("red")
        ]
        width = max(x for x, _ in red_pixels) - min(x for x, _ in red_pixels) + 1
        height = max(y for _, y in red_pixels) - min(y for _, y in red_pixels) + 1
        assert (width, height) == expected_size
