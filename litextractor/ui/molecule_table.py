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

"""Table model and structure-column delegate matching MolManager’s Structure look."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ..chemistry import molecule_quality_score, parse_mol, prioritize_molecules
from ..models import ExtractedMolecule
from ..structure_dimensions import (
    STRUCTURE_COLUMN_WIDTH,
    STRUCTURE_HEIGHT,
    STRUCTURE_ROW_HEIGHT,
    STRUCTURE_WIDTH,
)
from ..structure_draw import render_molecule_png
from .qt_widget_utils import pixmap_from_png

HEADERS = (
    "Structure",
    "Patent Crop",
    "SMILES",
    "Identifier",
    "Page",
    "Source",
    "Quality",
    "Formula",
    "MW",
    "InChIKey",
)

COL_STRUCTURE = 0
COL_PATENT_CROP = 1
COL_SMILES = 2
COL_IDENTIFIER = 3
COL_PAGE = 4
COL_SOURCE = 5
COL_QUALITY = 6
COL_FORMULA = 7
COL_MOLECULAR_WEIGHT = 8
COL_INCHI_KEY = 9

_RIGHT_ALIGNED_COLUMNS = (COL_PAGE, COL_QUALITY, COL_MOLECULAR_WEIGHT)


def render_structure_pixmap(molecule: ExtractedMolecule) -> QPixmap:
    """Depict *molecule* with RDKit as a pixmap; return a null pixmap if it cannot be drawn."""
    try:
        rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
        if rdkit_mol is None:
            return QPixmap()
        png = render_molecule_png(rdkit_mol, STRUCTURE_WIDTH, STRUCTURE_HEIGHT)
        return pixmap_from_png(png)
    except Exception:
        return QPixmap()


def render_crop_pixmap(pixmap: QPixmap) -> QPixmap:
    """Fit a patent crop into a transparent canvas matching the Structure image size."""
    if pixmap.isNull():
        return QPixmap()
    canvas = QPixmap(STRUCTURE_WIDTH, STRUCTURE_HEIGHT)
    canvas.fill(Qt.transparent)
    scaled = pixmap.scaled(
        canvas.size(),
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    painter = QPainter(canvas)
    offset_x = (canvas.width() - scaled.width()) // 2
    offset_y = (canvas.height() - scaled.height()) // 2
    painter.drawPixmap(offset_x, offset_y, scaled)
    painter.end()
    return canvas


class MoleculeTableModel(QAbstractTableModel):
    """Rows of extracted molecules with optional structure pixmaps.

    Structure, crop and quality-score values are computed lazily per row and cached.
    """

    def __init__(self, parent=None) -> None:
        """Create an empty model; per-row caches are filled on demand by ``set_molecules``."""
        super().__init__(parent)
        self._rows: list[ExtractedMolecule] = []
        self._pixmaps: list[QPixmap | None] = []
        self._crop_pixmaps: list[QPixmap | None] = []
        self._quality_texts: list[str | None] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        """Return the number of molecule rows (0 for any child index of a flat table)."""
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        """Return the number of columns defined by ``HEADERS``."""
        if parent.isValid():
            return 0
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        """Return the column title (horizontal) or 1-based row number (vertical)."""
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(HEADERS):
            return HEADERS[section]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # noqa: N802
        """Return display text, structure/crop pixmaps, alignment, or the record (``UserRole``)."""
        if not index.isValid():
            return None
        molecule = self._rows[index.row()]
        column = index.column()
        if role == Qt.DecorationRole:
            if column == COL_STRUCTURE:
                structure_pixmap = self._structure_pixmap(index.row())
                return structure_pixmap if not structure_pixmap.isNull() else None
            if column == COL_PATENT_CROP:
                crop = self._crop_pixmap(index.row())
                return crop if not crop.isNull() else None
        if role == Qt.DisplayRole:
            if column == COL_STRUCTURE:
                return "" if not self._structure_pixmap(index.row()).isNull() else "—"
            if column == COL_PATENT_CROP:
                return "" if molecule.crop_png else "—"
            return self._text_for(molecule, column, index.row())
        if role == Qt.TextAlignmentRole and column not in (COL_STRUCTURE, COL_PATENT_CROP):
            if column in _RIGHT_ALIGNED_COLUMNS:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.UserRole:
            return molecule
        return None

    def _structure_pixmap(self, row: int) -> QPixmap:
        """Return the cached structure depiction for *row*, rendering it on first use."""
        pixmap = self._pixmaps[row]
        if pixmap is None:
            pixmap = render_structure_pixmap(self._rows[row])
            self._pixmaps[row] = pixmap
        return pixmap

    def _crop_pixmap(self, row: int) -> QPixmap:
        """Return the cached, canvas-fitted patent crop for *row*, building it on first use."""
        pixmap = self._crop_pixmaps[row]
        if pixmap is None:
            crop_png = self._rows[row].crop_png
            pixmap = pixmap_from_png(crop_png) if crop_png else QPixmap()
            if not pixmap.isNull():
                pixmap = render_crop_pixmap(pixmap)
            self._crop_pixmaps[row] = pixmap
        return pixmap

    def _text_for(self, molecule: ExtractedMolecule, column: int, row: int) -> str:
        """Return the display text of a text column; *row* indexes the quality cache."""
        if column == COL_SMILES:
            return molecule.smiles
        if column == COL_IDENTIFIER:
            return molecule.identifier
        if column == COL_PAGE:
            return "; ".join(str(page) for page in molecule.page_numbers)
        if column == COL_SOURCE:
            return "; ".join(molecule.sources) if molecule.sources else molecule.source
        if column == COL_QUALITY:
            quality_text = self._quality_texts[row]
            if quality_text is None:
                quality_text = f"{molecule_quality_score(molecule):.3f}"
                self._quality_texts[row] = quality_text
            return quality_text
        if column == COL_FORMULA:
            return molecule.formula
        if column == COL_MOLECULAR_WEIGHT:
            if molecule.molecular_weight is None:
                return ""
            return f"{molecule.molecular_weight:.3f}"
        if column == COL_INCHI_KEY:
            return molecule.inchi_key
        return ""

    def molecule_at(self, row: int) -> ExtractedMolecule | None:
        """Return the molecule at *row*, or ``None`` if the row is out of range."""
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def molecules(self) -> list[ExtractedMolecule]:
        """Return a copy of the molecules in current display order."""
        return list(self._rows)

    def set_molecules(
        self, molecules: list[ExtractedMolecule], *, already_prioritized: bool = False
    ) -> None:
        """Replace all rows, ranking them unless *already_prioritized*, and reset the caches."""
        self.beginResetModel()
        self._rows = (
            list(molecules) if already_prioritized else prioritize_molecules(list(molecules))
        )
        self._pixmaps = [None] * len(self._rows)
        self._crop_pixmaps = [None] * len(self._rows)
        self._quality_texts = [None] * len(self._rows)
        self.endResetModel()


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap on a white cell, or a placeholder."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        """Draw the centered structure pixmap, or the placeholder text when there is none."""
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        painter.fillRect(style_option.rect, style_option.palette.color(QPalette.Base))
        structure_pixmap = index.data(Qt.DecorationRole)
        if isinstance(structure_pixmap, QPixmap) and not structure_pixmap.isNull():
            offset_x = (
                style_option.rect.x() + (style_option.rect.width() - structure_pixmap.width()) // 2
            )
            offset_y = (
                style_option.rect.y()
                + (style_option.rect.height() - structure_pixmap.height()) // 2
            )
            painter.drawPixmap(offset_x, offset_y, structure_pixmap)
            return
        text = index.data(Qt.DisplayRole)
        label = text if isinstance(text, str) and text.strip() else "—"
        painter.save()
        painter.setFont(style_option.font)
        painter.setPen(style_option.palette.text().color())
        margin = 6
        text_rect = QRect(
            style_option.rect.x() + margin,
            style_option.rect.y() + margin,
            max(1, style_option.rect.width() - 2 * margin),
            max(1, style_option.rect.height() - 2 * margin),
        )
        painter.drawText(text_rect, int(Qt.AlignCenter | Qt.TextWordWrap), label)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        """Return a cell size that fits the structure pixmap plus padding, or the default size."""
        base_size_hint = super().sizeHint(option, index)
        structure_pixmap = index.data(Qt.DecorationRole)
        if isinstance(structure_pixmap, QPixmap) and not structure_pixmap.isNull():
            width = max(base_size_hint.width(), structure_pixmap.width() + 8)
            height = max(base_size_hint.height(), structure_pixmap.height() + 8)
            return QSize(width, height)
        return QSize(STRUCTURE_WIDTH, max(base_size_hint.height(), STRUCTURE_HEIGHT))


class PatentCropDelegate(QStyledItemDelegate):
    """Paints patent crops within a consistent, aspect-preserving thumbnail area."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        """Draw the centered crop pixmap, or an em dash when the row has no crop."""
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        painter.fillRect(style_option.rect, style_option.palette.color(QPalette.Base))

        crop_pixmap = index.data(Qt.DecorationRole)
        if isinstance(crop_pixmap, QPixmap) and not crop_pixmap.isNull():
            offset_x = (
                style_option.rect.x() + (style_option.rect.width() - crop_pixmap.width()) // 2
            )
            offset_y = (
                style_option.rect.y() + (style_option.rect.height() - crop_pixmap.height()) // 2
            )
            painter.drawPixmap(offset_x, offset_y, crop_pixmap)
            return

        painter.save()
        painter.setFont(style_option.font)
        painter.setPen(style_option.palette.text().color())
        painter.drawText(style_option.rect, int(Qt.AlignCenter), "—")
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802, ARG002
        """Return the fixed crop-column cell size."""
        return QSize(STRUCTURE_COLUMN_WIDTH, STRUCTURE_HEIGHT)


class MoleculeTableView(QTableView):
    """Spreadsheet-style results table with a Structure column."""

    def __init__(self, parent=None) -> None:
        """Build the table with its model, structure/crop delegates, and column sizing."""
        super().__init__(parent)
        self._model = MoleculeTableModel(self)
        self._delegate = StructureDelegate(self)
        self._crop_delegate = PatentCropDelegate(self)
        self.setModel(self._model)
        self.setItemDelegateForColumn(COL_STRUCTURE, self._delegate)
        self.setItemDelegateForColumn(COL_PATENT_CROP, self._crop_delegate)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.verticalHeader().setVisible(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setColumnWidth(COL_STRUCTURE, STRUCTURE_COLUMN_WIDTH)
        self.setColumnWidth(COL_PATENT_CROP, STRUCTURE_COLUMN_WIDTH)
        self.verticalHeader().setDefaultSectionSize(STRUCTURE_ROW_HEIGHT)

    def molecule_model(self) -> MoleculeTableModel:
        """Return the table's underlying ``MoleculeTableModel``."""
        return self._model
