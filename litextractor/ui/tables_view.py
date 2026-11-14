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

"""The Tables sub-tab: each table as printed beside its parsed grid, with row-to-structure links.

The first grid column shows each row's link: the structure it matched, a choice between
several, or nothing. Rows are confirmed, linked by hand or unlinked from the context menu;
cells are corrected in place. Column headers choose the key column and which columns are shown
on the Molecules table.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..models import ExtractedMolecule, ExtractedTable, ExtractionResult, TableLink
from ..table_review import (
    RowStatus,
    confirm_link,
    edit_cell,
    link_counts,
    link_manually,
    molecule_by_id,
    row_links,
    row_status,
    set_key_column,
    toggle_shown_column,
    unlink_row,
)
from .dialogs.image_viewer import ClickableImage, ImageViewerDialog
from .qt_widget_utils import pixmap_from_png

LINK_COLUMN = 0
LINK_HEADER = "Structure"
_CROP_WIDTH = 460

# Readable on the light theme's white and alternate-row backgrounds.
_CONFIRMED_COLOR = QColor(21, 128, 61)
_ATTENTION_COLOR = QColor(217, 119, 6)
_UNLINKED_COLOR = QColor(118, 126, 136)

_NO_TABLES_TEXT = (
    "No data tables were found.\n\nTables are read from the PDF's text layer while figures "
    "are detected; scanned pages and tables printed as images come back empty."
)


def molecule_display_name(molecule: ExtractedMolecule | None) -> str:
    """Short text naming a molecule in link cells and pickers."""
    if molecule is None:
        return "(missing structure)"
    if molecule.identifier:
        return molecule.identifier
    pages = ", ".join(str(page) for page in molecule.page_numbers)
    return f"{molecule.formula or 'structure'}" + (f" (p. {pages})" if pages else "")


def link_cell_text(result: ExtractionResult, links: list[TableLink]) -> str:
    """Text of a row's link cell."""
    status = row_status(links)
    if status is RowStatus.UNLINKED:
        return "—"
    if status is RowStatus.AMBIGUOUS:
        names = ", ".join(molecule_display_name(molecule_by_id(result, link.molecule_id))
                          for link in links)
        return f"{len(links)} matches: {names}"
    link = next((link for link in links if link.confirmed), links[0])
    name = molecule_display_name(molecule_by_id(result, link.molecule_id))
    if status is RowStatus.CONFIRMED:
        return f"✓ {name}"
    return f"{name} (OCR match)" if link.method == "ocr" else name


def _link_tooltip(links: list[TableLink]) -> str:
    status = row_status(links)
    if status is RowStatus.UNLINKED:
        return "No structure matched this row. Right-click to link one."
    if status is RowStatus.AMBIGUOUS:
        return "Several structures carry this label. Right-click to choose the right one."
    if status is RowStatus.CONFIRMED:
        method = "linked by hand" if links[0].method == "manual" else "confirmed"
        return f"Structure {method}."
    if links[0].method == "ocr":
        return ("Matched once common OCR confusions (1/I/l, 0/O) were ignored. "
                "Right-click to confirm.")
    return "Suggested by matching the label. Right-click to confirm."


class TableGridModel(QAbstractTableModel):
    """One table's rows, with a leading link column; data cells are editable."""

    links_changed = Signal()

    def __init__(self, parent=None) -> None:
        """Create an empty model; ``set_table`` fills it."""
        super().__init__(parent)
        self._result: ExtractionResult | None = None
        self._table: ExtractedTable | None = None

    @property
    def table(self) -> ExtractedTable | None:
        """The table shown, or None."""
        return self._table

    def set_table(self, result: ExtractionResult | None, table: ExtractedTable | None) -> None:
        """Show *table* of *result*."""
        self.beginResetModel()
        self._result, self._table = result, table
        self.endResetModel()

    def refresh(self) -> None:
        """Redraw everything after links or the key column changed."""
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        """Return the number of table rows."""
        if parent.isValid() or self._table is None:
            return 0
        return len(self._table.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        """Return the link column plus the table's own columns."""
        if parent.isValid() or self._table is None:
            return 0
        return len(self._table.columns) + 1

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        """Column headers (the key column is bold and marked); 1-based row numbers."""
        if self._table is None:
            return None
        if orientation == Qt.Vertical:
            return str(section + 1) if role == Qt.DisplayRole else None
        if section == LINK_COLUMN:
            return LINK_HEADER if role == Qt.DisplayRole else None
        column = section - 1
        is_key = column == self._table.key_column
        if role == Qt.DisplayRole:
            header = self._table.columns[column] or f"Column {column + 1}"
            return f"{header} (key)" if is_key else header
        if role == Qt.FontRole and is_key:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ToolTipRole:
            shown = (self._table.id, column) in self._result.shown_table_columns
            notes = ["Rows are matched to structures by this column."] if is_key else []
            if shown:
                notes.append("Shown on the Molecules table.")
            notes.append("Right-click for options.")
            return " ".join(notes)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # noqa: N802
        """Cell text; for the link column also its colour and an explanation."""
        if not index.isValid() or self._table is None:
            return None
        row = index.row()
        if index.column() == LINK_COLUMN:
            links = row_links(self._result, self._table.id, row)
            if role == Qt.DisplayRole:
                return link_cell_text(self._result, links)
            if role == Qt.ForegroundRole:
                return self._link_color(links)
            if role == Qt.ToolTipRole:
                return _link_tooltip(links)
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._table.rows[row][index.column() - 1]
        return None

    @staticmethod
    def _link_color(links: list[TableLink]) -> QColor:
        status = row_status(links)
        if status is RowStatus.CONFIRMED:
            return _CONFIRMED_COLOR
        if status is RowStatus.UNLINKED:
            return _UNLINKED_COLOR
        if status is RowStatus.AMBIGUOUS or links[0].method == "ocr":
            return _ATTENTION_COLOR
        return QColor()

    def flags(self, index: QModelIndex):
        """Data cells are editable; the link column is not."""
        flags = super().flags(index)
        if index.isValid() and index.column() != LINK_COLUMN:
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:  # noqa: N802
        """Correct a cell; a corrected key cell re-matches the rows that use it."""
        if role != Qt.EditRole or not index.isValid() or index.column() == LINK_COLUMN:
            return False
        column = index.column() - 1
        text = str(value).strip()
        if self._table.rows[index.row()][column] == text:
            return False
        edit_cell(self._result, self._table, index.row(), column, text)
        if column == self._table.key_column:
            self.refresh()
        else:
            self.dataChanged.emit(index, index)
        self.links_changed.emit()
        return True


class TablesView(QWidget):
    """Choose a table; see it as printed beside its grid; review its row links."""

    #: Links, cell values or the shown columns changed: the molecule table and detail pane
    #: should be redrawn.
    table_data_changed = Signal()
    #: The user asked to see a linked structure (its molecule id).
    show_molecule_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the table chooser, crop pane and grid; no result is loaded yet."""
        super().__init__(parent)
        self._result: ExtractionResult | None = None

        self.table_combo = QComboBox()
        self.table_combo.currentIndexChanged.connect(self._show_table)
        self.summary_label = QLabel()
        header_row = QHBoxLayout()
        header_row.addWidget(self.table_combo, 1)
        header_row.addWidget(self.summary_label)
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.crop_container = QWidget()
        self._crop_layout = QVBoxLayout(self.crop_container)
        self._crop_layout.setContentsMargins(4, 4, 4, 4)
        crop_scroll = QScrollArea()
        crop_scroll.setWidgetResizable(True)
        crop_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        crop_scroll.setWidget(self.crop_container)
        crop_scroll.viewport().installEventFilter(self)
        self._crop_scroll = crop_scroll
        self._crop_images: list[tuple[ClickableImage, object]] = []

        self.grid_model = TableGridModel(self)
        self.grid_model.links_changed.connect(self._after_change)
        self.grid = QTableView()
        self.grid.setModel(self.grid_model)
        self.grid.setSelectionBehavior(QTableView.SelectRows)
        self.grid.setSelectionMode(QTableView.SingleSelection)
        self.grid.setAlternatingRowColors(True)
        self.grid.setWordWrap(True)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._row_menu)
        self.grid.doubleClicked.connect(self._open_link)
        header = self.grid.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_menu)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(crop_scroll)
        splitter.addWidget(self.grid)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([_CROP_WIDTH, 3 * _CROP_WIDTH // 2])

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.addLayout(header_row)
        content_layout.addWidget(self.title_label)
        content_layout.addWidget(splitter, 1)

        self.empty_label = QLabel(_NO_TABLES_TEXT)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)

        self._stack = QStackedWidget()
        self._stack.addWidget(self.empty_label)
        self._stack.addWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    # ------------------------------------------------------------------ showing

    def set_result(self, result: ExtractionResult) -> None:
        """Show the tables of *result*."""
        self._result = result
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        for table in result.tables:
            self.table_combo.addItem(self._combo_text(table), table.id)
        self.table_combo.blockSignals(False)
        self._stack.setCurrentIndex(1 if result.tables else 0)
        self._show_table(0 if result.tables else -1)

    def current_table(self) -> ExtractedTable | None:
        """The table being shown."""
        return self.grid_model.table

    def show_table(self, table_id: str, row_index: int | None = None) -> None:
        """Show a table by id and select one of its rows."""
        position = self.table_combo.findData(table_id)
        if position < 0:
            return
        self.table_combo.setCurrentIndex(position)
        if row_index is not None:
            self.grid.selectRow(row_index)
            self.grid.scrollTo(self.grid_model.index(row_index, LINK_COLUMN))

    def _combo_text(self, table: ExtractedTable) -> str:
        pages = ", ".join(str(page) for page in table.pages)
        linked, total = link_counts(self._result, table)
        return f"{table.name}  ·  p. {pages}  ·  {linked}/{total} rows linked"

    def _show_table(self, position: int) -> None:
        table = self._result.tables[position] if self._result and position >= 0 else None
        self.grid_model.set_table(self._result, table)
        self._show_crops(table)
        self.title_label.setText(table.title if table else "")
        self.title_label.setVisible(bool(table and table.title))
        self._update_summary()
        if table is not None:
            self.grid.resizeColumnsToContents()
            for column in range(self.grid_model.columnCount()):
                self.grid.setColumnWidth(column, min(self.grid.columnWidth(column), 260))

    def _show_crops(self, table: ExtractedTable | None) -> None:
        while self._crop_layout.count():
            item = self._crop_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._crop_images = []
        crops = table.crops_png if table else []
        for position, png in enumerate(crops):
            pixmap = pixmap_from_png(png)
            if pixmap.isNull():
                continue
            label = ClickableImage()
            label.setObjectName("TableCrop")
            label.double_clicked.connect(
                lambda pixmap=pixmap, position=position: self.open_crop(
                    pixmap, position, len(crops)
                )
            )
            label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._crop_images.append((label, pixmap))
            self._crop_layout.addWidget(label)
        if self._crop_layout.count() == 0:
            placeholder = QLabel("No image of this table.")
            placeholder.setAlignment(Qt.AlignCenter)
            self._crop_layout.addWidget(placeholder)
        self._crop_layout.addStretch(1)
        self._fit_crops()

    def _fit_crops(self) -> None:
        """Scale the table images to the width of their pane (never above actual size)."""
        width = max(40, self._crop_scroll.viewport().width() - 12)
        for label, pixmap in self._crop_images:
            label.setPixmap(
                pixmap.scaledToWidth(min(pixmap.width(), width), Qt.SmoothTransformation)
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Refit the table images when their pane is resized."""
        if watched is self._crop_scroll.viewport() and event.type() == QEvent.Resize:
            self._fit_crops()
        return super().eventFilter(watched, event)

    def open_crop(self, pixmap, position: int = 0, count: int = 1) -> ImageViewerDialog:
        """Open a table image full size in a zoomable window beside the grid."""
        table = self.current_table()
        title = table.name if table is not None else "Table"
        if table is not None and table.pages:
            title += f" · p. {', '.join(str(page) for page in table.pages)}"
        if count > 1:
            title += f" · image {position + 1} of {count}"
        viewer = ImageViewerDialog(pixmap, title, self)
        viewer.show()
        viewer.raise_()
        return viewer

    def _update_summary(self) -> None:
        table = self.current_table()
        if table is None:
            self.summary_label.setText("")
            return
        linked, total = link_counts(self._result, table)
        if table.key_column is None:
            self.summary_label.setText("No key column: right-click a header to choose one")
        else:
            self.summary_label.setText(f"{linked} of {total} rows linked")
        position = self.table_combo.currentIndex()
        if position >= 0:
            self.table_combo.setItemText(position, self._combo_text(table))

    def _after_change(self) -> None:
        self._update_summary()
        self.table_data_changed.emit()

    # ------------------------------------------------------------------ row actions

    def _row_menu(self, position: QPoint) -> None:
        index = self.grid.indexAt(position)
        table = self.current_table()
        if not index.isValid() or table is None:
            return
        row = index.row()
        links = row_links(self._result, table.id, row)
        menu = QMenu(self)
        actions = {}
        status = row_status(links)
        if status is RowStatus.SUGGESTED:
            name = molecule_display_name(molecule_by_id(self._result, links[0].molecule_id))
            actions[menu.addAction(f"Confirm link to {name}")] = (
                lambda: confirm_link(self._result, table.id, row, links[0].molecule_id))
        if status is RowStatus.AMBIGUOUS:
            choose = menu.addMenu("Choose structure")
            for link in links:
                name = molecule_display_name(molecule_by_id(self._result, link.molecule_id))
                actions[choose.addAction(name)] = (
                    lambda molecule_id=link.molecule_id: confirm_link(
                        self._result, table.id, row, molecule_id))
        actions[menu.addAction("Link to structure…")] = lambda: self._link_by_hand(row)
        if links:
            actions[menu.addAction("Unlink")] = lambda: unlink_row(self._result, table.id, row)
            menu.addSeparator()
            for link in links:
                name = molecule_display_name(molecule_by_id(self._result, link.molecule_id))
                go = menu.addAction(f"Show {name} in Molecules")
                go.triggered.connect(
                    lambda _checked=False, molecule_id=link.molecule_id:
                    self.show_molecule_requested.emit(molecule_id))
        chosen = menu.exec(self.grid.viewport().mapToGlobal(position))
        if chosen in actions and actions[chosen]() is not False:
            self.grid_model.refresh()
            self.grid.selectRow(row)
            self._after_change()

    def _link_by_hand(self, row: int) -> bool:
        """Ask which structure the row describes; return False if the user cancelled."""
        table = self.current_table()
        molecules = self._result.molecules
        if not molecules:
            return False
        names = [
            f"{molecule_display_name(molecule)}  —  {molecule.formula or molecule.smiles[:40]}"
            for molecule in molecules
        ]
        current = [link.molecule_id for link in row_links(self._result, table.id, row)]
        start = next((i for i, m in enumerate(molecules) if m.id in current), 0)
        name, accepted = QInputDialog.getItem(
            self, "Link row to structure", f"Structure for row {row + 1}:", names, start, False
        )
        if not accepted or name not in names:
            return False
        link_manually(self._result, table.id, row, molecules[names.index(name)].id)
        return True

    def _open_link(self, index: QModelIndex) -> None:
        """Double-clicking a link cell shows its structure (or asks for one if unlinked)."""
        table = self.current_table()
        if not index.isValid() or index.column() != LINK_COLUMN or table is None:
            return
        links = row_links(self._result, table.id, index.row())
        if row_status(links) in (RowStatus.SUGGESTED, RowStatus.CONFIRMED):
            confirmed = next((link for link in links if link.confirmed), links[0])
            self.show_molecule_requested.emit(confirmed.molecule_id)
        elif self._link_by_hand(index.row()):
            self.grid_model.refresh()
            self._after_change()

    # ------------------------------------------------------------------ column actions

    def _column_menu(self, position: QPoint) -> None:
        table = self.current_table()
        section = self.grid.horizontalHeader().logicalIndexAt(position)
        if table is None or section <= LINK_COLUMN:
            return
        column = section - 1
        menu = QMenu(self)
        shown = (table.id, column) in self._result.shown_table_columns
        show = menu.addAction("Show on Molecules table")
        show.setCheckable(True)
        show.setChecked(shown)
        key = menu.addAction("Match rows by this column")
        key.setCheckable(True)
        key.setChecked(column == table.key_column)
        chosen = menu.exec(self.grid.horizontalHeader().mapToGlobal(position))
        if chosen is show:
            toggle_shown_column(self._result, table.id, column)
        elif chosen is key:
            set_key_column(self._result, table, None if column == table.key_column else column)
        else:
            return
        self.grid_model.refresh()
        self._after_change()
