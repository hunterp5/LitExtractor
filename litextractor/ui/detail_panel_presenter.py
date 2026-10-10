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

"""Presenter for the selected-molecule detail pane."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QTableView, QWidget

from ..models import ExtractedMolecule
from ..structure_layout import DETAIL_STRUCTURE_HEIGHT, DETAIL_STRUCTURE_WIDTH
from .qt_widget_utils import pixmap_from_png

logger = logging.getLogger(__name__)


class DetailPanelPresenter:
    """Own detail-pane rendering so MainWindow can focus on composition."""

    def __init__(
        self,
        *,
        detail_structure: QLabel,
        detail_crop: QLabel,
        detail_crop_card: QWidget,
        detail_values: dict[str, QLabel],
    ) -> None:
        self._detail_structure = detail_structure
        self._detail_crop = detail_crop
        self._detail_crop_card = detail_crop_card
        self._detail_values = detail_values

    def selected_molecule(self, molecule_table: QTableView | None) -> ExtractedMolecule | None:
        """Return the currently selected molecule row from the active result table."""
        if molecule_table is None:
            return None
        selection_model = molecule_table.selectionModel()
        if selection_model is None:
            return None
        indexes = selection_model.selectedRows()
        if not indexes:
            return None
        return molecule_table.molecule_model().molecule_at(indexes[0].row())

    def refresh_selected_detail(self, molecule_table: QTableView | None) -> None:
        """Render detail widgets for the currently selected molecule."""
        record = self.selected_molecule(molecule_table)
        if record is None:
            self.clear_detail()
            return

        # Imported lazily so application startup does not load RDKit.
        from ..chemistry import molecule_quality_score, parse_mol
        from ..structure_draw import render_molecule_png

        molecule = parse_mol(smiles=record.smiles, molfile=record.molfile)
        png = b""
        if molecule is not None:
            try:
                png = render_molecule_png(molecule, DETAIL_STRUCTURE_WIDTH, DETAIL_STRUCTURE_HEIGHT)
            except Exception:
                logger.debug("Detail structure render failed", exc_info=True)
        if png:
            self._detail_structure.setPixmap(pixmap_from_png(png))
            self._detail_structure.setText("")
        else:
            self._detail_structure.setPixmap(QPixmap())
            self._detail_structure.setText("No structure")

        if record.crop_png:
            crop = pixmap_from_png(record.crop_png)
            self._detail_crop.setPixmap(
                crop.scaled(320, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._detail_crop.setText("")
            self._detail_crop_card.show()
        else:
            self._detail_crop.setPixmap(QPixmap())
            self._detail_crop.setText("—")
            self._detail_crop_card.hide()

        page = "; ".join(str(page_number) for page_number in record.page_numbers) or "—"
        score = f"{molecule_quality_score(record):.3f}"
        mw = "—" if record.molecular_weight is None else f"{record.molecular_weight:.3f}"
        source = "; ".join(record.sources) if record.sources else record.source
        values = {
            "Identifier": record.identifier or "—",
            "Page": page,
            "Source": source or "—",
            "Quality": score,
            "Formula": record.formula or "—",
            "Molecular weight": mw,
            "InChIKey": record.inchi_key or "—",
        }
        for name, value in values.items():
            self._detail_values[name].setText(value)

    def clear_detail(self) -> None:
        """Reset detail widgets to their empty state."""
        self._detail_structure.setPixmap(QPixmap())
        self._detail_structure.setText("Select a molecule")
        self._detail_crop.setPixmap(QPixmap())
        self._detail_crop.setText("—")
        self._detail_crop_card.hide()
        for value in self._detail_values.values():
            value.setText("—")
