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

"""Table data exports: wide (molecule CSV/SDF), long, and each table as printed."""

from __future__ import annotations

import csv

import pytest
from PySide6.QtWidgets import QFileDialog

from litextractor.chemistry import enrich_molecule
from litextractor.export import write_csv, write_sdf
from litextractor.models import ExtractedMolecule, ExtractedTable, ExtractionResult
from litextractor.table_export import (
    header_unit,
    long_rows,
    parse_value,
    write_long_csv,
    write_table_csvs,
)
from litextractor.table_review import confirm_link, toggle_shown_column
from litextractor.tables import link_table_rows
from litextractor.ui.main_window import MainWindow


@pytest.mark.parametrize(
    ("text", "parsed"),
    [("12", ("", 12.0)), ("<0.1", ("<", 0.1)), ("≥ 50", (">=", 50.0)), ("1,200", ("", 1200.0)),
     ("12 ± 3", ("", 12.0)), ("−0.5", ("", -0.5)), ("+++", ("", None)), ("NT", ("", None)),
     ("2003 (FDA)", ("", None)), ("", ("", None))],
)
def test_measurements_are_parsed_and_anything_else_is_left_unparsed(text, parsed):
    assert parse_value(text) == parsed


@pytest.mark.parametrize(
    ("header", "unit"),
    [("IC50 (nM)", "nM"), ("Yield [%]", "%"), ("Ki (μM)", "μM"), ("Dose (mg/kg)", "mg/kg"),
     ("Name (Trade Name)", ""), ("Targets", "")],
)
def test_units_come_from_the_end_of_the_header(header, unit):
    assert header_unit(header) == unit


def activity_result():
    one = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="1"))
    three_a = enrich_molecule(ExtractedMolecule(smiles="CCN", identifier="3"))
    three_b = enrich_molecule(ExtractedMolecule(smiles="CCC", identifier="3"))
    table = ExtractedTable(
        id="T1", title="Table 2. EGFR inhibition", pages=[4, 5],
        columns=["Compd", "IC50 (nM)", "Selectivity"],
        rows=[["1", "<0.1", "+++"], ["3", "12", ""], ["9", "40", "+"]],
    )
    result = ExtractionResult("doc.pdf", [one, three_a, three_b], [], tables=[table])
    result.table_links = link_table_rows([table], result.molecules)
    return result, (one, three_a, three_b)


def test_long_rows_give_one_line_per_linked_value_with_parsed_numbers():
    result, (one, three_a, three_b) = activity_result()

    lines = long_rows(result)

    assert [(l["Identifier"], l["Row"], l["Column"], l["Value"], l["Qualifier"], l["Number"],
             l["Unit"], l["Link"]) for l in lines] == [
        ("1", "1", "IC50 (nM)", "<0.1", "<", "0.1", "nM", "suggested"),
        ("1", "1", "Selectivity", "+++", "", "", "", "suggested"),
        ("3", "2", "IC50 (nM)", "12", "", "12", "nM", "ambiguous"),
        ("3", "2", "IC50 (nM)", "12", "", "12", "nM", "ambiguous"),
    ]
    assert lines[0]["Table"] == "Table 2" and lines[0]["Pages"] == "4; 5"
    assert lines[0]["InChIKey"] == one.inchi_key
    assert len(long_rows(result, include_ambiguous=False)) == 2

    confirm_link(result, "T1", 1, three_b.id)
    assert [(l["SMILES"], l["Link"]) for l in long_rows(result)][2:] == [("CCC", "confirmed")]


def test_each_table_is_written_as_printed_with_unlinked_rows_and_link_status(tmp_path):
    result, _ = activity_result()

    (path,) = write_table_csvs(tmp_path / "tables", result)

    assert path.name == "T1 Table 2.csv"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["Structure", "SMILES", "Link", "Compd", "IC50 (nM)", "Selectivity"],
        ["1", "CCO", "suggested", "1", "<0.1", "+++"],
        ["3; 3", "CCN; CCC", "ambiguous", "3", "12", ""],
        ["", "", "unlinked", "9", "40", "+"],
    ]


def test_molecule_csv_and_sdf_carry_the_shown_table_columns(tmp_path):
    from rdkit import Chem

    result, (one, three_a, three_b) = activity_result()
    toggle_shown_column(result, "T1", 1)

    write_csv(tmp_path / "wide.csv", result.molecules, result)
    write_sdf(tmp_path / "wide.sdf", result.molecules, result)

    with (tmp_path / "wide.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["Table 2 · IC50 (nM)"] for row in rows] == ["<0.1", "", ""]  # "3" is ambiguous
    records = list(Chem.SDMolSupplier(str(tmp_path / "wide.sdf")))
    assert records[0].GetProp("Table 2 · IC50 (nM)") == "<0.1"
    assert not records[1].HasProp("Table 2 · IC50 (nM)")


def test_table_exports_from_the_file_menu(qapp, monkeypatch, tmp_path):
    result, _ = activity_result()
    window = MainWindow()
    window._on_extract_finished(result)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *_a, **_k: (str(tmp_path / "long.csv"), ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(tmp_path))

    window.export_table_data()
    assert window.status_label.text() == "Wrote 4 table value(s) to long.csv"
    window.export_tables()
    assert (tmp_path / "T1 Table 2.csv").is_file()
    assert window.status_label.text().startswith("Wrote 1 table(s)")
    window.close()


def test_long_csv_header(tmp_path):
    result, _ = activity_result()
    write_long_csv(tmp_path / "long.csv", result)
    header = (tmp_path / "long.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("Identifier,SMILES,InChIKey,Table,Table title,Pages,Row")
