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

"""Values printed under or beside structures in figures (activities, pharmacokinetics)."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from litextractor import text_labels
from litextractor.export import write_csv
from litextractor.figure_values import (
    fix_ocr_text,
    join_baselines,
    parse_figure_values,
    parse_value_line,
    values_near,
)
from litextractor.models import ExtractedMolecule, ExtractionResult
from litextractor.table_export import long_rows
from litextractor.text_labels import FigurePlacement, TextLine, apply_text_layer_labels


@pytest.mark.parametrize(
    ("read", "fixed"),
    [
        ("FAK: ICs0 = 1.0 nM", "FAK: IC50 = 1.0 nM"),
        ("EGFR: ICso =3 nM", "EGFR: IC50 =3 nM"),
        ("Cmax(nglmL) = 75.4", "Cmax(ng/mL) = 75.4"),
        ("CL(mLlminlkg) 36", "CL(mL/min/kg) 36"),
        ("CL(Llhlkg) = 9.75", "CL(L/h/kg) = 9.75"),
        ("t12(h) = 5", "t1/2(h) = 5"),
        ("tiz(min) = 43.6", "t1/2(min) = 43.6"),
        ("AUCo-(ug*h/L) = 4398.88", "AUC0-(ug*h/L) = 4398.88"),
        ("Fofo 16.37", "F% 16.37"),
        ("Gefitinib", "Gefitinib"),
    ],
)
def test_ocr_misreadings_are_undone(read, fixed):
    assert fix_ocr_text(read) == fixed


def test_pieces_of_one_line_are_joined_but_values_side_by_side_are_not():
    lines = join_baselines([
        TextLine((257, 700, 283, 708), "FAK: IC50"),
        TextLine((288, 701, 305, 708), "1.0 nM"),
        TextLine((263, 515, 327, 525), "FAK: IC50 = 0.07 nM"),
        TextLine((337, 515, 369, 524), "FAK: IC50"),
        TextLine((374, 516, 401, 524), "4.65 nM"),
        TextLine((157, 393, 194, 400), "AUC(ng*h/mL)"),
        TextLine((199, 394, 213, 400), "2757"),
        TextLine((219, 395, 282, 405), "FAK: IC50 = 4.34 nM"),
    ])

    assert sorted(line.text for line in lines) == [
        "AUC(ng*h/mL) 2757", "FAK: IC50 1.0 nM", "FAK: IC50 4.65 nM", "FAK: IC50 = 0.07 nM",
        "FAK: IC50 = 4.34 nM",
    ]


def test_each_structure_gets_the_value_centred_below_it():
    left, right = (100, 300, 200, 400), (220, 300, 320, 400)
    lines = [
        TextLine((140, 285, 160, 295), "12"),               # the label, not a value
        TextLine((115, 272, 185, 282), "FAK: IC50 = 2.75 nM"),
        TextLine((235, 272, 305, 282), "FAK: IC50 = 1.87 nM"),
        TextLine((150, 350, 160, 358), "NH"),                # atom label inside the drawing
    ]

    assert values_near([left, right], lines, None) == [
        ["FAK: IC50 = 2.75 nM"], ["FAK: IC50 = 1.87 nM"],
    ]


def test_a_block_printed_beside_a_structure_is_its_own_not_the_one_above():
    # Compound 11's activity and rat PK are printed to its right, just under compound 9.
    nine, eleven = (232, 329, 321, 450), (98, 201, 207, 323)
    block = [
        TextLine((214, 305, 264, 314), "FAK: IC50 = 45 nM"),
        TextLine((213, 297, 275, 306), "in rat: 5 mg/kg IV dose"),
        TextLine((213, 290, 263, 298), "Cmax(ug/L) = 2292"),
        TextLine((215, 282, 253, 289), "Tmax(h) = 0.08"),
    ]

    assert values_near([nine, eleven], block, None) == [[], [line.text for line in block]]


def test_repeat_counts_and_substituents_are_not_values():
    structure = (100, 300, 200, 400)
    lines = [TextLine((130, 285, 170, 295), "n = 8"), TextLine((130, 275, 170, 284), "R = Me")]

    assert values_near([structure], lines, None) == [[]]


def test_value_lines_are_split_into_name_value_number_and_unit():
    activity = parse_value_line("FAK: IC50 = <0.5 nM")
    assert (activity.name, activity.value, activity.qualifier, activity.number, activity.unit) == (
        "FAK IC50", "<0.5 nM", "<", 0.5, "nM"
    )
    clearance = parse_value_line("CL(mL/min/kg) 36")
    assert (clearance.name, clearance.number, clearance.unit) == ("CL(mL/min/kg)", 36.0, "mL/min/kg")
    assert parse_value_line("in rat: 5 mg/kg IV dose") is None


def test_values_carry_the_heading_they_were_printed_under():
    values = parse_figure_values([
        "FAK: IC50 = 1.2 nM", "in human: 100 mg/kg PO dose", "Cmax(ng/mL) = 75.4",
        "Tmax(h) = 2.1",
    ])

    assert [(value.name, value.heading) for value in values] == [
        ("FAK IC50", ""),
        ("Cmax(ng/mL)", "in human: 100 mg/kg PO dose"),
        ("Tmax(h)", "in human: 100 mg/kg PO dose"),
    ]


def test_values_of_compounds_sharing_a_drawing_are_headed_by_their_substituent():
    values = parse_figure_values([
        "43: R = Et", "FAK: IC50 = N.T.", "45: R = Ph", "FAK: IC50 = 19 nM",
        "iPrOH, 80 °C, 8 h", "64% yield", "Solubility(mg/mL) = 456",
    ])

    assert [(value.name, value.value, value.heading) for value in values] == [
        ("FAK IC50", "N.T.", "43: R = Et"),
        ("FAK IC50", "19 nM", "45: R = Ph"),
        ("Solubility(mg/mL)", "456", "45: R = Ph"),
    ]


@pytest.mark.parametrize(
    ("text", "is_value"),
    [
        ("FAK: IC50 = 4.0 nM", True), ("in rat: 5 mg/kg IV dose", True),
        ("CL(mL/min/kg) 36", True), ("cLogP = 3.1", True), ("Dmax 99%, DC50 3.0 nM", True),
        ("iPrOH, 80 °C, 8 h", False), ("64% yield", False), ("Cl", False), ("n = 8", False),
        ("Fig: 24 FAK protacs 66-68", False), ("Lead compounds 49", False),
    ],
)
def test_value_lines_are_activities_doses_and_properties_not_conditions(text, is_value):
    from litextractor.figure_values import is_value_line

    assert is_value_line(text) is is_value


class FakeReader:
    def __init__(self, detections):
        self.detections = detections

    def readtext(self, pixels):
        del pixels
        return self.detections


def test_ocr_values_under_a_structure_are_stored_on_its_molecule(monkeypatch):
    # Figure (100, 100)-(300, 400) read at one pixel per point; structure at (150, 250)-(250, 370).
    monkeypatch.setattr(text_labels, "page_text_lines", lambda pdf, page: ([], (0, 0, 612, 792)))
    reader = FakeReader([
        ([[90, 147], [110, 147], [110, 155], [90, 155]], "12", 0.9),
        ([[60, 157], [95, 157], [95, 165], [60, 165]], "FAK: ICs0", 0.9),
        ([[99, 157], [125, 157], [125, 165], [99, 165]], "=45 nM", 0.9),
    ])
    molecule = ExtractedMolecule(smiles="C", figure_index=0, bbox=(0.25, 0.1, 0.75, 0.5))

    apply_text_layer_labels([molecule], [FigurePlacement(0, (100, 100, 300, 400))], "doc.pdf",
                            [np.zeros((300, 200))], reader)

    assert molecule.identifier == "12"
    assert molecule.figure_values == ["FAK: IC50 =45 nM"]


def test_figure_values_are_exported_in_the_csv_and_the_long_form(tmp_path):
    molecule = ExtractedMolecule(smiles="CCO", identifier="11", page=5,
                                 figure_values=["FAK: IC50 = 45 nM", "in rat: 5 mg/kg IV dose",
                                                "Tmax(h) = 0.08"])
    result = ExtractionResult("doc.pdf", [molecule], [])

    write_csv(tmp_path / "m.csv", [molecule], result)
    with (tmp_path / "m.csv").open(encoding="utf-8") as handle:
        (row,) = csv.DictReader(handle)
    lines = long_rows(result)

    assert row["Figure values"] == "FAK: IC50 = 45 nM; in rat: 5 mg/kg IV dose; Tmax(h) = 0.08"
    assert [(line["Table"], line["Column"], line["Number"], line["Unit"], line["Table title"])
            for line in lines] == [
        ("Figure", "FAK IC50", "45", "nM", ""),
        ("Figure", "Tmax(h)", "0.08", "h", "in rat: 5 mg/kg IV dose"),
    ]
    assert lines[0]["Row label"] == "11" and lines[0]["Pages"] == "5"


def test_excel_has_a_table_data_sheet_for_figure_values_alone(tmp_path):
    from litextractor.excel_export import write_xlsx

    molecule = ExtractedMolecule(smiles="CCO", identifier="11", figure_values=["FAK: IC50 = 45 nM"])

    counts = write_xlsx(tmp_path / "r.xlsx", ExtractionResult("doc.pdf", [molecule], []),
                        structure_images=False)

    assert counts == {"Molecules": 1, "Table data": 1}


def test_the_detail_pane_lists_figure_values_before_table_rows():
    from litextractor.ui.detail_panel_presenter import table_data_html

    molecule = ExtractedMolecule(smiles="CCO", figure_values=["FAK: IC50 < 1 nM"])

    text = table_data_html(molecule, ExtractionResult("doc.pdf", [molecule], []))

    assert text == "<b>Printed with the structure</b><br>FAK: IC50 &lt; 1 nM"
