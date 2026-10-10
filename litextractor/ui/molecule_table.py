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
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPixmap
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


def render_structure_pixmap(rec: ExtractedMolecule) -> QPixmap:
    try:
        mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
        if mol is None:
            return QPixmap()
        png = render_molecule_png(mol, structure_width(), structure_height())
        return pixmap_from_png(png)
    except Exception:
        return QPixmap()


def render_crop_pixmap(pixmap: QPixmap) -> QPixmap:
    """Fit a patent crop into a transparent canvas matching the Structure image size."""
    if pixmap.isNull():
        return QPixmap()
    canvas = QPixmap(structure_width(), structure_height())
    canvas.fill(Qt.transparent)
    scaled = pixmap.scaled(
        canvas.size(),
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    painter = QPainter(canvas)
    x = (canvas.width() - scaled.width()) // 2
    y = (canvas.height() - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas


class MoleculeTableModel(QAbstractTableModel):
    """Rows of extracted molecules with optional structure pixmaps."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ExtractedMolecule] = []
        self._pixmaps: list[QPixmap | None] = []
        self._crop_pixmaps: list[QPixmap | None] = []
        self._quality_texts: list[str | None] = []

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
                pix = self._structure_pixmap(index.row())
                return pix if not pix.isNull() else None
            if col == COL_PATENT_CROP:
                crop = self._crop_pixmap(index.row())
                return crop if not crop.isNull() else None
        if role == Qt.DisplayRole:
            if col == COL_STRUCTURE:
                return "" if not self._structure_pixmap(index.row()).isNull() else "—"
            if col == COL_PATENT_CROP:
                return "" if rec.crop_png else "—"
            return self._text_for(rec, col, index.row())
        if role == Qt.TextAlignmentRole and col not in (COL_STRUCTURE, COL_PATENT_CROP):
            if col in (4, 6, 8):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.UserRole:
            return rec
        return None

    def _structure_pixmap(self, row: int) -> QPixmap:
        pixmap = self._pixmaps[row]
        if pixmap is None:
            pixmap = render_structure_pixmap(self._rows[row])
            self._pixmaps[row] = pixmap
        return pixmap

    def _crop_pixmap(self, row: int) -> QPixmap:
        pixmap = self._crop_pixmaps[row]
        if pixmap is None:
            crop_png = self._rows[row].crop_png
            pixmap = pixmap_from_png(crop_png) if crop_png else QPixmap()
            if not pixmap.isNull():
                pixmap = render_crop_pixmap(pixmap)
            self._crop_pixmaps[row] = pixmap
        return pixmap

    def _text_for(self, rec: ExtractedMolecule, col: int, row: int) -> str:
        if col == 2:
            return rec.smiles
        if col == 3:
            return rec.identifier
        if col == 4:
            return "; ".join(str(page) for page in rec.page_numbers)
        if col == 5:
            return "; ".join(rec.sources) if rec.sources else rec.source
        if col == 6:
            quality_text = self._quality_texts[row]
            if quality_text is None:
                quality_text = f"{molecule_quality_score(rec):.3f}"
                self._quality_texts[row] = quality_text
            return quality_text
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

    def set_molecules(
        self, molecules: list[ExtractedMolecule], *, already_prioritized: bool = False
    ) -> None:
        self.beginResetModel()
        self._rows = (
            list(molecules) if already_prioritized else prioritize_molecules(list(molecules))
        )
        self._pixmaps = [None] * len(self._rows)
        self._crop_pixmaps = [None] * len(self._rows)
        self._quality_texts = [None] * len(self._rows)
        self.endResetModel()

    def rerender_structures(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._pixmaps = [None] * len(self._rows)
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
            return QSize(size_w, size_h)
        return QSize(structure_width(), max(sh.height(), structure_height()))


class PatentCropDelegate(QStyledItemDelegate):
    """Paints patent crops within a consistent, aspect-preserving thumbnail area."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        palette = QApplication.palette() if QApplication.instance() else opt.palette
        painter.fillRect(opt.rect, palette.color(QPalette.Base))

        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            x = opt.rect.x() + (opt.rect.width() - pix.width()) // 2
            y = opt.rect.y() + (opt.rect.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
            return

        painter.save()
        painter.setFont(opt.font)
        painter.setPen(opt.palette.text().color())
        painter.drawText(opt.rect, int(Qt.AlignCenter), "—")
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802, ARG002
        return QSize(structure_column_minimum_width(), structure_height())


class MoleculeTableView(QTableView):
    """Spreadsheet-style results table with a Structure column."""

    def __init__(self, parent=None) -> None:
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
        self.apply_structure_layout()

    def molecule_model(self) -> MoleculeTableModel:
        return self._model

    def apply_structure_layout(self) -> None:
        self.setColumnWidth(COL_STRUCTURE, structure_column_minimum_width())
        self.setColumnWidth(COL_PATENT_CROP, structure_column_minimum_width())
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
