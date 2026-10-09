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

"""Table model and structure-column delegate matching MolManager’s Structure look."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from ..chemistry import molecule_quality_score, parse_mol, prioritize_molecules
from ..models import ExtractedMolecule
from ..structure_layout import (
    structure_column_minimum_width,
    structure_height,
    structure_row_height,
    structure_width,
)
from ..structure_draw import render_molecule_png

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


def pixmap_from_png(png: bytes) -> QPixmap:
    pix = QPixmap()
    if png:
        pix.loadFromData(png)
    return pix


def render_structure_pixmap(rec: ExtractedMolecule) -> QPixmap:
    try:
        mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
        if mol is None:
            return QPixmap()
        png = render_molecule_png(mol, structure_width(), structure_height())
        return pixmap_from_png(png)
    except Exception:
        return QPixmap()


class MoleculeTableModel(QAbstractTableModel):
    """Rows of extracted molecules with optional structure pixmaps."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ExtractedMolecule] = []
        self._pixmaps: list[QPixmap] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(HEADERS):
            return HEADERS[section]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        rec = self._rows[index.row()]
        col = index.column()
        if role == Qt.DecorationRole:
            if col == COL_STRUCTURE:
                pix = self._pixmaps[index.row()]
                return pix if not pix.isNull() else None
            if col == COL_PATENT_CROP:
                crop = pixmap_from_png(rec.crop_png) if rec.crop_png else QPixmap()
                return crop if not crop.isNull() else None
        if role == Qt.DisplayRole:
            if col == COL_STRUCTURE:
                return "" if not self._pixmaps[index.row()].isNull() else "—"
            if col == COL_PATENT_CROP:
                return "" if rec.crop_png else "—"
            return self._text_for(rec, col)
        if role == Qt.TextAlignmentRole and col not in (COL_STRUCTURE, COL_PATENT_CROP):
            if col in (4, 6, 8):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.UserRole:
            return rec
        return None

    def _text_for(self, rec: ExtractedMolecule, col: int) -> str:
        if col == 2:
            return rec.smiles
        if col == 3:
            return rec.identifier
        if col == 4:
            return "" if rec.page is None else str(rec.page)
        if col == 5:
            return "; ".join(rec.sources) if rec.sources else rec.source
        if col == 6:
            return f"{molecule_quality_score(rec):.3f}"
        if col == 7:
            return rec.formula
        if col == 8:
            return "" if rec.molecular_weight is None else f"{rec.molecular_weight:.3f}"
        if col == 9:
            return rec.inchi_key
        return ""

    def molecule_at(self, row: int) -> ExtractedMolecule | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def molecules(self) -> list[ExtractedMolecule]:
        return list(self._rows)

    def set_molecules(self, molecules: list[ExtractedMolecule]) -> None:
        self.beginResetModel()
        self._rows = prioritize_molecules(list(molecules))
        self._pixmaps = [render_structure_pixmap(rec) for rec in self._rows]
        self.endResetModel()

    def rerender_structures(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._pixmaps = [render_structure_pixmap(rec) for rec in self._rows]
        self.endResetModel()

    def clear(self) -> None:
        self.set_molecules([])


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap on a white cell, or a placeholder."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cell_background: QColor | None = None

    def set_cell_background(self, color: QColor | None) -> None:
        self._cell_background = color

    def paint(self, painter, option, index) -> None:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        pix = index.data(Qt.DecorationRole)
        has_pix = isinstance(pix, QPixmap) and not pix.isNull()
        if has_pix:
            bg = QApplication.palette().color(QPalette.Base) if QApplication.instance() else opt.palette.color(QPalette.Base)
            painter.fillRect(opt.rect, bg)
            x = opt.rect.x() + (opt.rect.width() - pix.width()) // 2
            y = opt.rect.y() + (opt.rect.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
            return
        pal = QApplication.palette() if QApplication.instance() else opt.palette
        bg = (
            self._cell_background if self._cell_background is not None else pal.color(QPalette.Base)
        )
        painter.fillRect(opt.rect, bg)
        text = index.data(Qt.DisplayRole)
        label = text if isinstance(text, str) and text.strip() else "—"
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(opt.palette.text().color())
        margin = 6
        r = QRect(
            opt.rect.x() + margin,
            opt.rect.y() + margin,
            max(1, opt.rect.width() - 2 * margin),
            max(1, opt.rect.height() - 2 * margin),
        )
        painter.drawText(r, int(Qt.AlignCenter | Qt.TextWordWrap), label)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        sh = super().sizeHint(option, index)
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            size_w = max(sh.width(), pix.width() + 8)
            size_h = max(sh.height(), pix.height() + 8)
            if index.column() == COL_PATENT_CROP:
                size_w = max(size_w, 110)
                size_h = max(size_h, 70)
            return QSize(size_w, size_h)
        if index.column() == COL_PATENT_CROP:
            return QSize(110, 70)
        return QSize(structure_width(), max(sh.height(), structure_height()))


class MoleculeTableView(QTableView):
    """Spreadsheet-style results table with a Structure column."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = MoleculeTableModel(self)
        self._delegate = StructureDelegate(self)
        self.setModel(self._model)
        self.setItemDelegateForColumn(COL_STRUCTURE, self._delegate)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.verticalHeader().setVisible(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.apply_structure_layout()

    def molecule_model(self) -> MoleculeTableModel:
        return self._model

    def apply_structure_layout(self) -> None:
        self.setColumnWidth(COL_STRUCTURE, structure_column_minimum_width())
        self.setColumnWidth(COL_PATENT_CROP, 110)
        self.verticalHeader().setDefaultSectionSize(structure_row_height())
        self._delegate.set_cell_background(
            QApplication.palette().color(QPalette.Base) if QApplication.instance() else None
        )

    def apply_table_font(self, pt: int) -> None:
        font = QFont(self.font())
        font.setPointSize(int(pt))
        self.setFont(font)
        self.horizontalHeader().setFont(font)
        self.verticalHeader().setFont(font)

    def refresh_theme(self) -> None:
        self.apply_structure_layout()
        self.viewport().update()
