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

"""Excel export: read back from the workbook's XML (an .xlsx file is a zip of XML parts)."""

from __future__ import annotations

import html
import re
import zipfile

from PySide6.QtWidgets import QFileDialog

from litextractor.chemistry import enrich_molecule
from litextractor.excel_export import write_xlsx
from litextractor.models import (
    ExtractedMolecule,
    ExtractedReaction,
    ExtractedTable,
    ExtractionResult,
)
from litextractor.table_review import toggle_shown_column
from litextractor.tables import link_table_rows
from litextractor.ui.main_window import MainWindow


def sample_result():
    one = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="1", page=3,
                                            confidence=0.91))
    two = enrich_molecule(ExtractedMolecule(smiles="c1ccccc1N", identifier="2", page=4))
    table = ExtractedTable(
        id="T1", title="Table 2. Inhibition of EGFR: data", pages=[5],
        columns=["Compd", "IC50 (nM)"], rows=[["1", "=45"], ["2", "<0.1"], ["9", "7"]],
    )
    reaction = ExtractedReaction(page=6, reactants=["CCO"], products=["CC=O"],
                                 conditions="PCC, DCM")
    result = ExtractionResult("papers/egfr.pdf", [one, two], [reaction], tables=[table])
    result.table_links = link_table_rows([table], result.molecules)
    toggle_shown_column(result, "T1", 1)
    return result


def workbook_parts(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        text = {name: archive.read(name).decode("utf-8", "replace")
                for name in names if name.endswith(".xml")}
    sheets = re.findall(r'<sheet name="([^"]+)"', text["xl/workbook.xml"])
    strings = [html.unescape(value) for value in
               re.findall(r"<t[^>]*>([^<]*)</t>", text.get("xl/sharedStrings.xml", ""))]
    return names, text, sheets, strings


def test_workbook_has_molecules_table_data_each_table_and_reactions(tmp_path):
    path = tmp_path / "egfr.xlsx"

    counts = write_xlsx(path, sample_result())

    names, text, sheets, strings = workbook_parts(path)
    assert sheets == ["Molecules", "Table data", "T1 Table 2", "Reactions"]
    assert counts == {"Molecules": 2, "Table data": 2, "T1 Table 2": 3, "Reactions": 1}
    assert {"Structure", "SMILES", "Identifier", "Table 2 · IC50 (nM)", "CCO", "=45",
            "<0.1", "unlinked", "PCC, DCM"} <= set(strings)
    assert len([n for n in names if n.startswith("xl/media/")]) == 2  # a picture per structure


def test_values_starting_with_equals_are_text_not_formulas(tmp_path):
    path = tmp_path / "egfr.xlsx"

    write_xlsx(path, sample_result())

    _names, text, _sheets, _strings = workbook_parts(path)
    sheet_xml = "".join(v for k, v in text.items() if k.startswith("xl/worksheets/"))
    assert "<f>" not in sheet_xml


def test_numbers_are_numbers_and_pictures_can_be_left_out(tmp_path):
    path = tmp_path / "plain.xlsx"

    write_xlsx(path, sample_result(), structure_images=False)

    names, text, _sheets, strings = workbook_parts(path)
    assert not any(n.startswith("xl/media/") for n in names)
    assert strings[0] == "SMILES"  # first header of the Molecules sheet
    molecules_xml = text["xl/worksheets/sheet1.xml"]
    assert "<v>0.91</v>" in molecules_xml  # confidence written as a number


def test_sheet_names_are_valid_and_unique():
    from litextractor.excel_export import _sheet_name

    used = set()
    names = [_sheet_name(name, used) for name in
             ["Results: a/b [x]?", "Results: a/b [x]?", "A" * 40, "Molecules", "molecules"]]

    assert names == ["Results_ a_b _x__", "Results_ a_b _x__ (2)", "A" * 31, "Molecules",
                     "molecules (2)"]


def test_export_excel_from_the_file_menu(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    window._on_extract_finished(sample_result())
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *_a, **_k: (str(tmp_path / "out"), ""))

    window.export_excel()

    assert (tmp_path / "out.xlsx").is_file()
    assert window.status_label.text() == "Wrote out.xlsx: 2 molecule(s), 4 sheet(s)"
    window.close()
