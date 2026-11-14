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

"""Table cleanup and row-to-molecule linking, on shapes OpenChemIE returns for real PDFs."""

from __future__ import annotations

import pytest

from litextractor.extraction import extract_from_pdf
from litextractor.models import ExtractedMolecule, ExtractedTable, ExtractOptions
from litextractor.tables import (
    detect_key_column,
    link_table_rows,
    normalize_label,
    tables_from_openchemie,
)


def raw_table(page, columns, rows, title=""):
    """An OpenChemIE table result (output_bbox=True style: cells are dicts)."""
    return {
        "page": page,
        "title": {"text": title, "bbox": []},
        "footnote": {"text": "", "bbox": []},
        "figure": {"image": None, "bbox": []},
        "table": {
            "bbox": [],
            "content": {
                "columns": [{"text": text, "tag": "unknown"} for text in columns],
                "rows": [[{"text": text} for text in row] for row in rows],
            },
        },
    }


def patent_activity_pages():
    """WO 2026/136733 Table A: three side-by-side panels, printed over two pages.

    As OpenChemIE returns it: header cells merged at double spaces, the second header line as
    the first row, two empty cells inserted after each "Ex No", and the next page's first data
    row taken as its header.
    """
    first = raw_table(
        256,
        ["Ex No  CDK12/CycK  Ex No", "CDK12/CycK  Ex No", "CDK12/CycK"],
        [
            ["+DDBl", "+DDBl", "+DDBl"],
            ["1", "", "", "+++", "101", "+++", "201", "++++"],
            ["2", "", "", "+", "102", "++", "202", "\n"],
        ],
        title="Table A. Inhibition of biochemical activity of CDK12/CycK with DDB1",
    )
    second = raw_table(257, ["3", "++", "103", "+", "203", "+++"], [["4", "+++", "104", "++", "", ""]])
    return [first, second]


def test_side_by_side_panels_over_two_pages_become_one_long_table():
    (table,) = tables_from_openchemie(patent_activity_pages())

    assert table.id == "T1"
    assert table.name == "Table A"
    assert table.pages == [256, 257]
    assert table.columns == ["Ex No", "CDK12/CycK +DDBl"]
    assert table.rows == [
        ["1", "+++"], ["2", "+"], ["101", "+++"], ["102", "++"], ["201", "++++"],
        ["202", ""],  # printed without a value: kept, not dropped
        ["3", "++"], ["4", "+++"], ["103", "+"], ["104", "++"], ["203", "+++"],
    ]


def test_a_new_header_or_caption_starts_a_new_table():
    table_b = raw_table(
        258,
        ["Ex No  Luc-CycK", "Ex No", "Luc-CycK"],
        [["Degradation", "", "Degradation"], ["1", "", "", "+++", "101", "+"]],
    )
    table_c = raw_table(
        259,
        ["1", "", "", "+++", "101", "++++"],
        [["2", "", "", "++", "102", "+"]],
        title="Table  C.  Inhibition of BT-474 cell proliferation",
    )

    tables = tables_from_openchemie(patent_activity_pages() + [table_b, table_c])

    assert [table.name for table in tables] == ["Table A", "Table on p. 258", "Table C"]
    assert tables[1].columns == ["Ex No", "Luc-CycK Degradation"]
    assert tables[1].rows == [["1", "+++"], ["101", "+"]]
    # No header survives on Table C, so its panels are found from the data itself.
    assert tables[2].rows == [["1", "+++"], ["2", "++"], ["101", "++++"], ["102", "+"]]


def jak_table_1():
    columns = ["Drug", "Target JAKs", "Disease", "Approval Date"]
    first = raw_table(
        51,
        columns,
        [
            ["Abrocitinib", "JAK1, JAK2", "Atopic dermatitis", "2022"],
            ["Baricitinib", "JAK1, JAK2", "Rheumatoid arthritis", "2018 (FDA)"],
            ["", "", "COVID-19", "2020 (EUA)"],
        ],
        title="Table 1. The globally approved JAK inhibitors",
    )
    cont = raw_table(52, columns, [["Tofacitinib", "JAK1, JAK2, JAK3", "Ulcerative colitis", "2018"]],
                     title="Table 1. Cont.")
    return [first, cont]


def test_continued_journal_table_is_joined_and_blank_drug_rows_link_to_the_drug_above():
    (table,) = tables_from_openchemie(jak_table_1())
    baricitinib = ExtractedMolecule(smiles="C", identifier="Baricitinib")
    tofacitinib = ExtractedMolecule(smiles="N", identifier="tofacitinib")

    links = link_table_rows([table], [baricitinib, tofacitinib])

    assert table.pages == [51, 52] and len(table.rows) == 4
    assert table.key_column == 0
    assert [(link.row_index, link.molecule_id) for link in links] == [
        (1, baricitinib.id), (2, baricitinib.id), (3, tofacitinib.id),
    ]
    assert all(link.method == "exact" and not link.confirmed for link in links)


def test_reference_lists_and_non_tables_are_dropped_but_captioned_citing_tables_kept():
    references = raw_table(
        16,
        ["2.", "Sharma, B.; Singh, V.J. Epidermal growth factor receptor inhibitors"],
        [
            ["recent progress. Bioorganic Chem. 2021, 116, 105393. [CrossRef] [PubMed]"],
            ["3.", "Guardiola, S.; et al. A Third Shot at EGFR. Trends"],
            ["Pharmacol. Sci. 2019, 40, 941–955. [CrossRef] [PubMed]"],
        ],
    )
    single_column = raw_table(10, ["Figure 3. Small molecules"], [["4.7.2. Quercetin"]])
    no_text = {"page": 20, "title": "", "figure": {"image": None}, "table": {"content": None}}
    receptors = raw_table(
        2,
        ["Receptor", "Synonym", "Discovery"],
        [["EGFR", "erbB1, HER", "Carpenter et al. (1975)"], ["ErbB2", "HER2, neu", "Stern et al. (1986)"]],
        title="Table 1. The synonym and discovery of four members of the EGFR family.",
    )

    tables = tables_from_openchemie([references, single_column, no_text, receptors])

    assert [table.name for table in tables] == ["Table 1"]


@pytest.mark.parametrize(
    ("label", "normalized"),
    [("Compound (12a)", "12a"), ("Ex. 5", "5"), ("12A.", "12a"), ("Geﬁtinib", "gefitinib"),
     ("Exemestane", "exemestane"), ("Example 101", "101")],
)
def test_label_normalization(label, normalized):
    assert normalize_label(label) == normalized


def _table(columns, rows, **kwargs):
    return ExtractedTable(id="T1", title="", pages=[1], columns=columns, rows=rows, **kwargs)


def test_ocr_confusions_link_as_ocr_matches_and_shared_labels_are_ambiguous():
    ocr_read = ExtractedMolecule(smiles="C", identifier="Ia")      # printed "1a"
    first_3 = ExtractedMolecule(smiles="N", identifier="3")
    second_3 = ExtractedMolecule(smiles="O", identifier="3; 7")
    table = _table(["Compd", "IC50 (nM)"], [["1a", "12"], ["3", ">1000"], ["9", "5"]])

    links = link_table_rows([table], [ocr_read, first_3, second_3])

    assert [(l.row_index, l.molecule_id, l.method, l.ambiguous) for l in links] == [
        (0, ocr_read.id, "ocr", False),
        (1, first_3.id, "exact", True),
        (1, second_3.id, "exact", True),
    ]


def test_trade_names_and_ligatures_in_a_name_column_still_match():
    gefitinib = ExtractedMolecule(smiles="C", identifier="Gefitinib")
    table = _table(["Name (Trade Name)", "Targets"], [["Geﬁtinib (Iressa)", "EGFR"]])

    links = link_table_rows([table], [gefitinib])

    assert [link.molecule_id for link in links] == [gefitinib.id]


def test_key_column_comes_from_header_then_label_overlap_then_id_like_first_column():
    by_header = _table(["IC50", "Ex No"], [["5", "1"]])
    by_overlap = _table(["Value", "Label"], [["5", "12a"], ["6", "12b"], ["7", "x"]])
    by_ids = _table(["", ""], [["1", "+++"], ["2", "++"]])
    text_only = _table(["Reversible", "Irreversible"], [["Brigatinib", "Afatinib"]])

    assert detect_key_column(by_header) == 1
    assert detect_key_column(by_overlap, {"12a", "12b"}) == 1
    assert detect_key_column(by_ids) == 0
    assert detect_key_column(text_only) is None


class TableClient:
    """Fake OpenChemIE returning one figure with molecules "1" and "2" and Table A."""

    def __init__(self):
        self.detections = 0

    def extract_figures_and_tables_from_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        self.detections += 1
        tables = patent_activity_pages()
        for table in tables:
            table["page"] -= 1  # OpenChemIE pages are zero-based
        return {"figures": [{"figure": {"image": "fig"}, "page": 255}], "tables": tables}

    def extract_molecules_from_figures(self, figures, **kwargs):
        del kwargs
        return [{"molecules": [{"smiles": "CCO", "bbox": (0, 0, 0.4, 0.4)},
                               {"smiles": "CCN", "bbox": (0.5, 0.5, 0.9, 0.9)}]} for _ in figures]

    def extract_molecule_corefs_from_figures(self, figures, **kwargs):
        del kwargs
        return [
            {
                "bboxes": [
                    {"category": "[Mol]", "bbox": (0, 0, 0.4, 0.4)},
                    {"category": "[Idt]", "bbox": (0, 0.4, 0.2, 0.5), "text": "1"},
                    {"category": "[Mol]", "bbox": (0.5, 0.5, 0.9, 0.9)},
                    {"category": "[Idt]", "bbox": (0.5, 0.9, 0.7, 1.0), "text": "103"},
                ],
                "corefs": [[0, 1], [2, 3]],
            }
            for _ in figures
        ]


def test_extraction_returns_tables_with_global_pages_and_links_to_final_molecules():
    options = ExtractOptions(text=False, reactions=False)

    result = extract_from_pdf("dummy.pdf", options, client=TableClient())

    (table,) = result.tables
    assert table.pages == [256, 257]
    by_id = {molecule.id: molecule for molecule in result.molecules}
    linked = {(table.rows[link.row_index][0], by_id[link.molecule_id].identifier)
              for link in result.table_links}
    assert linked == {("1", "1"), ("103", "103")}


def test_tables_can_be_turned_off_and_extracted_without_figures():
    client = TableClient()
    no_tables = extract_from_pdf(
        "dummy.pdf", ExtractOptions(text=False, tables=False), client=client
    )
    tables_only = extract_from_pdf(
        "dummy.pdf", ExtractOptions(figures=False, text=False, corefs=False, tables=True),
        client=client,
    )

    assert no_tables.tables == [] and no_tables.table_links == []
    assert len(tables_only.tables) == 1 and tables_only.molecules == []
    assert client.detections == 2
