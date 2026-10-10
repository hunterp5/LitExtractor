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

"""A molecule/reaction table pair for one extraction run."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..models import ExtractionResult
from .molecule_table import MoleculeTableView


class ExtractionResultTab(QWidget):
    """Own the tables and extraction result shown in one top-level result tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the Molecules and Reactions sub-tabs; no result is loaded yet."""
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    def set_result(self, result: ExtractionResult) -> None:
        """Populate both tables from one extraction result."""
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

        self.tabs.setTabText(0, f"Molecules ({len(result.molecules)})")
        self.tabs.setTabText(1, f"Reactions ({len(result.reactions)})")
