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

"""CSV / SDF / SMILES export."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox

from litextractor.chemistry import enrich_molecule
from litextractor.models import ExtractedMolecule, ExtractionResult
from litextractor.export import molecule_export_rows, write_csv, write_sdf, write_smi
from litextractor.ui.main_window import MainWindow


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


def test_write_sdf_skips_unkekulizable_records_and_keeps_the_rest(tmp_path):
    from rdkit import Chem

    # A five-membered all-aromatic carbon ring is a typical OCR error RDKit cannot kekulize.
    broken = ExtractedMolecule(smiles="c1cccc1", identifier="broken", page=2)
    sdf_path = tmp_path / "out.sdf"

    written = write_sdf(sdf_path, [_ethanol(), broken, _ethanol()])

    records = [mol for mol in Chem.SDMolSupplier(str(sdf_path)) if mol is not None]
    assert written == 2
    assert len(records) == 2
    assert all(record.GetProp("Identifier") == "EtOH" for record in records)
    assert records[0].GetProp("MW") == "46.069"


def test_sdf_status_message_reports_skipped_records():
    from litextractor.ui.main_window import _sdf_success_message

    assert _sdf_success_message("/x/out.sdf", 3, 3) == "Wrote 3 molecule(s) to out.sdf"
    assert _sdf_success_message("/x/out.sdf", 2, 3).endswith(
        "skipped 1 without a writable structure"
    )


def test_export_failure_is_reported_and_does_not_change_last_dir(
    qapp, monkeypatch, tmp_path
):
    window = MainWindow()
    window._on_extract_finished(
        ExtractionResult(pdf_path="demo.pdf", molecules=[_ethanol()], reactions=[])
    )
    output_path = tmp_path / "blocked.csv"
    previous_dir = window._last_dir
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

    monkeypatch.setattr("litextractor.ui.main_window.write_csv", fail_to_write)
    window.export_csv()

    assert len(errors) == 1
    assert str(output_path) in errors[0]
    assert "permission denied" in errors[0]
    assert window._last_dir == previous_dir
    window.close()
