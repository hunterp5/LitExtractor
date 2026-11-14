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

"""Reviewing table-row links: confirming, choosing, linking by hand, correcting cells."""

from __future__ import annotations

from litextractor.models import ExtractedMolecule, ExtractedTable, ExtractionResult
from litextractor.table_review import (
    RowStatus,
    confirm_link,
    edit_cell,
    link_counts,
    link_manually,
    molecule_value,
    row_links,
    row_status,
    set_key_column,
    shown_column_header,
    toggle_shown_column,
    unlink_row,
)
from litextractor.tables import link_table_rows


def activity_result():
    """Table 2 with compounds 1, 3 (two structures carry "3"), 9 (no structure) and 1 again."""
    one = ExtractedMolecule(smiles="C", identifier="1")
    three_a = ExtractedMolecule(smiles="N", identifier="3")
    three_b = ExtractedMolecule(smiles="O", identifier="3")
    nine_as_read = ExtractedMolecule(smiles="S", identifier="Ia")
    table = ExtractedTable(
        id="T1",
        title="Table 2. Inhibition of EGFR",
        pages=[4],
        columns=["Compd", "IC50 (nM)", "Assay"],
        rows=[["1", "12", "A"], ["3", ">1000", "A"], ["9", "5", "B"], ["1", "15", "B"], ["", "", "C"]],
    )
    result = ExtractionResult("doc.pdf", [one, three_a, three_b, nine_as_read], [], tables=[table])
    result.table_links = link_table_rows([table], result.molecules)
    return result, table, (one, three_a, three_b, nine_as_read)


def statuses(result, table):
    return [row_status(row_links(result, table.id, row)) for row in range(len(table.rows))]


def test_rows_start_suggested_ambiguous_or_unlinked():
    result, table, _ = activity_result()

    assert statuses(result, table) == [
        RowStatus.SUGGESTED, RowStatus.AMBIGUOUS, RowStatus.UNLINKED, RowStatus.SUGGESTED,
        RowStatus.SUGGESTED,  # blank key: continues compound 1 from the row above
    ]
    assert link_counts(result, table) == (3, 5)


def test_choosing_one_of_an_ambiguous_rows_matches_confirms_it_and_drops_the_rest():
    result, table, (_, three_a, three_b, _) = activity_result()

    confirm_link(result, "T1", 1, three_b.id)

    (link,) = row_links(result, "T1", 1)
    assert (link.molecule_id, link.confirmed, link.ambiguous) == (three_b.id, True, False)
    assert molecule_value(result, "T1", 1, three_b.id) == ">1000"
    assert molecule_value(result, "T1", 1, three_a.id) == ""


def test_linking_by_hand_and_unlinking():
    result, table, (one, _, _, nine_as_read) = activity_result()

    link_manually(result, "T1", 2, nine_as_read.id)
    unlink_row(result, "T1", 0)

    (link,) = row_links(result, "T1", 2)
    assert (link.method, link.confirmed, link.label) == ("manual", True, "9")
    assert row_links(result, "T1", 0) == []
    assert molecule_value(result, "T1", 1, one.id) == "15"


def test_correcting_a_key_cell_rematches_it_and_the_rows_continuing_it_but_not_settled_rows():
    result, table, (one, three_a, _, nine_as_read) = activity_result()
    confirm_link(result, "T1", 0, one.id)

    edit_cell(result, table, 3, 0, "Ia")   # row 4 was read as "1": it is compound Ia
    edit_cell(result, table, 0, 0, "3")    # row 1 is confirmed: the user's choice stands

    assert [link.molecule_id for link in row_links(result, "T1", 3)] == [nine_as_read.id]
    assert [link.molecule_id for link in row_links(result, "T1", 4)] == [nine_as_read.id]
    assert [link.molecule_id for link in row_links(result, "T1", 0)] == [one.id]
    assert table.rows[0][0] == "3"
    assert three_a.id not in {link.molecule_id for link in row_links(result, "T1", 0)}


def test_editing_a_value_cell_changes_shown_values_but_not_links():
    result, table, (one, *_rest) = activity_result()
    links_before = list(result.table_links)

    edit_cell(result, table, 0, 1, "11")

    assert result.table_links == links_before
    assert molecule_value(result, "T1", 1, one.id) == "11; 15"


def test_choosing_another_key_column_rematches_the_table():
    result, table, _ = activity_result()

    set_key_column(result, table, 2)   # "Assay" values match no structure
    assert result.table_links == []
    set_key_column(result, table, None)
    assert table.key_column is None and result.table_links == []


def test_shown_columns_toggle_and_are_named_by_table_and_header():
    result, table, _ = activity_result()

    assert toggle_shown_column(result, "T1", 1) is True
    assert result.shown_table_columns == [("T1", 1)]
    assert shown_column_header(table, 1) == "Table 2 · IC50 (nM)"
    assert toggle_shown_column(result, "T1", 1) is False
    assert result.shown_table_columns == []


def test_confirming_a_compound_drawn_twice_confirms_both_copies():
    from litextractor.chemistry import enrich_molecule

    first = enrich_molecule(ExtractedMolecule(smiles="CC(N)C(=O)O", identifier="5"))
    second = enrich_molecule(ExtractedMolecule(smiles="C[C@H](N)C(=O)O", identifier="5"))
    table = ExtractedTable(id="T1", title="", pages=[1], columns=["Compd", "IC50"],
                           rows=[["5", "7"]])
    result = ExtractionResult("d.pdf", [first, second], [], tables=[table])
    result.table_links = link_table_rows([table], result.molecules)

    assert row_status(row_links(result, "T1", 0)) is RowStatus.SUGGESTED
    confirm_link(result, "T1", 0, first.id)

    assert [link.confirmed for link in row_links(result, "T1", 0)] == [True, True]
    assert molecule_value(result, "T1", 1, second.id) == "7"
