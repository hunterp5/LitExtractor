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
from ..structure_dimensions import DETAIL_STRUCTURE_HEIGHT, DETAIL_STRUCTURE_WIDTH
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
        """Store the detail-pane widgets that this presenter updates.

        Args:
            detail_structure: Label showing the RDKit depiction of the selected molecule.
            detail_crop: Label showing the scaled patent crop.
            detail_crop_card: Container of ``detail_crop``, hidden when there is no crop.
            detail_values: Value labels keyed by field name (Identifier, Page, Source,
                Quality, Formula, Molecular weight, InChIKey).
        """
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
        molecule = self.selected_molecule(molecule_table)
        if molecule is None:
            self.clear_detail()
            return

        self._show_structure(molecule)
        self._show_crop(molecule)
        for field_name, text in self._detail_text_values(molecule).items():
            self._detail_values[field_name].setText(text)

    def _show_structure(self, molecule: ExtractedMolecule) -> None:
        """Depict *molecule* in the structure label, or show a "No structure" placeholder."""
        # Imported lazily so application startup does not load RDKit.
        from ..chemistry import parse_mol
        from ..structure_draw import render_molecule_png

        rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
        structure_png = b""
        if rdkit_mol is not None:
            try:
                structure_png = render_molecule_png(
                    rdkit_mol, DETAIL_STRUCTURE_WIDTH, DETAIL_STRUCTURE_HEIGHT
                )
            except Exception:
                logger.debug("Detail structure render failed", exc_info=True)
        if structure_png:
            self._detail_structure.setPixmap(pixmap_from_png(structure_png))
            self._detail_structure.setText("")
        else:
            self._detail_structure.setPixmap(QPixmap())
            self._detail_structure.setText("No structure")

    def _show_crop(self, molecule: ExtractedMolecule) -> None:
        """Show the scaled patent crop and its card, or hide the card when there is no crop."""
        if molecule.crop_png:
            crop_pixmap = pixmap_from_png(molecule.crop_png)
            self._detail_crop.setPixmap(
                crop_pixmap.scaled(320, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._detail_crop.setText("")
            self._detail_crop_card.show()
        else:
            self._detail_crop.setPixmap(QPixmap())
            self._detail_crop.setText("—")
            self._detail_crop_card.hide()

    @staticmethod
    def _detail_text_values(molecule: ExtractedMolecule) -> dict[str, str]:
        """Return the text for each detail field of *molecule*, using "—" for blanks."""
        # Imported lazily so application startup does not load RDKit.
        from ..chemistry import molecule_quality_score

        pages_text = "; ".join(str(page_number) for page_number in molecule.page_numbers) or "—"
        quality_text = f"{molecule_quality_score(molecule):.3f}"
        if molecule.molecular_weight is None:
            molecular_weight_text = "—"
        else:
            molecular_weight_text = f"{molecule.molecular_weight:.3f}"
        source_text = "; ".join(molecule.sources) if molecule.sources else molecule.source
        return {
            "Identifier": molecule.identifier or "—",
            "Page": pages_text,
            "Source": source_text or "—",
            "Quality": quality_text,
            "Formula": molecule.formula or "—",
            "Molecular weight": molecular_weight_text,
            "InChIKey": molecule.inchi_key or "—",
        }

    def clear_detail(self) -> None:
        """Reset detail widgets to their empty state."""
        self._detail_structure.setPixmap(QPixmap())
        self._detail_structure.setText("Select a molecule")
        self._detail_crop.setPixmap(QPixmap())
        self._detail_crop.setText("—")
        self._detail_crop_card.hide()
        for value in self._detail_values.values():
            value.setText("—")
