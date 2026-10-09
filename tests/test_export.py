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

"""CSV / SDF / SMILES export."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox

from patentextractor.extraction import ExtractedMolecule, enrich_molecule
from patentextractor.export import molecule_export_rows, write_csv, write_sdf, write_smi
from patentextractor.ui.main_window import MainWindow


def _ethanol() -> ExtractedMolecule:
    return enrich_molecule(
        ExtractedMolecule(smiles="CCO", identifier="EtOH", page=1, source="figure")
    )


def test_export_rows_include_identifier():
    rows = molecule_export_rows([_ethanol()])
    assert rows[0]["Identifier"] == "EtOH"
    assert rows[0]["SMILES"] == "CCO"
    assert rows[0]["Formula"] == "C2H6O"


def test_export_rows_include_all_merged_pages():
    molecule = _ethanol()
    molecule.add_page(3)

    rows = molecule_export_rows([molecule])

    assert rows[0]["Page"] == "1; 3"


def test_write_csv_smi_sdf(tmp_path):
    mols = [_ethanol()]
    csv_path = tmp_path / "out.csv"
    smi_path = tmp_path / "out.smi"
    sdf_path = tmp_path / "out.sdf"
    write_csv(csv_path, mols)
    write_smi(smi_path, mols)
    n = write_sdf(sdf_path, mols)
    text = csv_path.read_text(encoding="utf-8")
    assert "EtOH" in text
    assert "CCO" in smi_path.read_text(encoding="utf-8")
    assert n == 1
    assert sdf_path.stat().st_size > 0


def test_export_failure_is_reported_and_does_not_change_last_dir(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    window._mol_table.molecule_model().set_molecules([_ethanol()])
    output_path = tmp_path / "blocked.csv"
    previous_dir = window._last_dir()
    errors: list[str] = []

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(output_path), ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: errors.append(message),
    )

    def fail_to_write(_path, _molecules):
        raise PermissionError("permission denied")

    monkeypatch.setattr("patentextractor.ui.main_window.write_csv", fail_to_write)
    window.export_csv()

    assert len(errors) == 1
    assert str(output_path) in errors[0]
    assert "permission denied" in errors[0]
    assert window._last_dir() == previous_dir
    window.close()
