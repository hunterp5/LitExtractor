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

"""The Molecules, Reactions and Tables sub-tabs of one extraction run."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Signal
from PySide6.QtWidgets import QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..models import ExtractionResult
from ..table_review import molecule_value, shown_column_header, table_by_id
from .molecule_table import MoleculeTableView
from .tables_view import TablesView

MOLECULES_TAB, REACTIONS_TAB, TABLES_TAB = 0, 1, 2


class ExtractionResultTab(QWidget):
    """Own the tables and extraction result shown in one top-level result tab."""

    #: Table links, values or shown columns changed (the detail pane should be redrawn).
    table_data_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the Molecules, Reactions and Tables sub-tabs; no result is loaded yet."""
        super().__init__(parent)
        self.result: ExtractionResult | None = None

        self.tabs = QTabWidget(self)
        self.molecule_table = MoleculeTableView(self.tabs)
        self.reaction_table = QTableWidget(0, 5, self.tabs)
        self.reaction_table.setHorizontalHeaderLabels(
            ["Page", "Reactants", "Products", "Conditions", "Source"]
        )
        self.reaction_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.reaction_table.setAlternatingRowColors(True)
        self.reaction_table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.molecule_table, "Molecules")
        self.tabs.addTab(self.reaction_table, "Reactions")
        self.tables_view = TablesView(self.tabs)
        self.tabs.addTab(self.tables_view, "Tables")
        self.tables_view.table_data_changed.connect(self._on_table_data_changed)
        self.tables_view.show_molecule_requested.connect(self.show_molecule)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    def set_result(self, result: ExtractionResult) -> None:
        """Populate the sub-tabs from one extraction result."""
        self.result = result
        self.molecule_table.molecule_model().set_molecules(
            result.molecules, already_prioritized=True
        )
        self.reaction_table.setRowCount(0)
        for reaction in result.reactions:
            row = self.reaction_table.rowCount()
            self.reaction_table.insertRow(row)
            values = [
                "" if reaction.page is None else str(reaction.page),
                " + ".join(reaction.reactants),
                " + ".join(reaction.products),
                reaction.conditions,
                reaction.source,
            ]
            for column, value in enumerate(values):
                self.reaction_table.setItem(row, column, QTableWidgetItem(value))

        self.tables_view.set_result(result)
        self._update_shown_columns()

        self.tabs.setTabText(MOLECULES_TAB, f"Molecules ({len(result.molecules)})")
        self.tabs.setTabText(REACTIONS_TAB, f"Reactions ({len(result.reactions)})")
        # Reactions are off by default; their tab only shows when they were looked for.
        self.tabs.setTabVisible(REACTIONS_TAB, result.reactions_requested or bool(result.reactions))
        self.tabs.setTabText(TABLES_TAB, f"Tables ({len(result.tables)})")

    def show_molecule(self, molecule_id: str) -> None:
        """Switch to the Molecules sub-tab and select the molecule with *molecule_id*."""
        row = self.molecule_table.molecule_model().row_of(molecule_id)
        if row is None:
            return
        self.tabs.setCurrentIndex(MOLECULES_TAB)
        self.molecule_table.selectionModel().select(
            self.molecule_table.molecule_model().index(row, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.molecule_table.scrollTo(self.molecule_table.molecule_model().index(row, 0))

    def _update_shown_columns(self) -> None:
        """Show the table columns the user chose as extra columns of the molecule table."""
        result = self.result
        shown = [
            (table, column)
            for table_id, column in result.shown_table_columns
            if (table := table_by_id(result, table_id)) is not None
        ]
        self.molecule_table.molecule_model().set_extra_columns(
            [shown_column_header(table, column) for table, column in shown],
            lambda molecule, i: molecule_value(result, shown[i][0].id, shown[i][1], molecule.id),
        )

    def _on_table_data_changed(self) -> None:
        """Keep the molecule table's selection while its table columns are redrawn."""
        selected = self.molecule_table.selectionModel().selectedRows()
        molecule = (
            self.molecule_table.molecule_model().molecule_at(selected[0].row()) if selected else None
        )
        self._update_shown_columns()
        if molecule is not None:
            row = self.molecule_table.molecule_model().row_of(molecule.id)
            if row is not None:
                self.molecule_table.selectRow(row)
        self.table_data_changed.emit()
